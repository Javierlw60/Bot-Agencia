import json
import urllib.error
import urllib.request
from typing import Any

from models.database import Agencia, PagoMercadoPago, SessionLocal
from mercadopago_config import MP_API_BASE, obtener_config_mercadopago
from suscripcion_agencias import (
    DIAS_RENOVACION_PAGO,
    extraer_agencia_id_de_referencia,
    referencia_externa_agencia,
    renovar_suscripcion_agencia,
)

TIPO_PAGO_MANUAL = "manual"
TIPO_PAGO_SUSCRIPCION = "suscripcion"


class MercadoPagoError(Exception):
    pass


def _request_mp(
    metodo: str,
    path: str,
    payload: dict | None = None,
    access_token: str | None = None,
) -> dict[str, Any]:
    cfg = obtener_config_mercadopago()
    token = access_token or cfg["access_token"]
    if not token:
        raise MercadoPagoError("MERCADOPAGO_ACCESS_TOKEN no configurado.")

    url = f"{MP_API_BASE}{path}"
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            cuerpo = resp.read().decode("utf-8")
            return json.loads(cuerpo) if cuerpo else {}
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        raise MercadoPagoError(f"MP HTTP {exc.code}: {detalle}") from exc
    except urllib.error.URLError as exc:
        raise MercadoPagoError(f"Error de red con Mercado Pago: {exc}") from exc


def obtener_pago(payment_id: str | int) -> dict[str, Any]:
    return _request_mp("GET", f"/v1/payments/{payment_id}")


def obtener_preapproval(preapproval_id: str) -> dict[str, Any]:
    return _request_mp("GET", f"/preapproval/{preapproval_id}")


def _metadata_pago(pago: dict[str, Any]) -> dict[str, Any]:
    metadata = pago.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _clasificar_tipo_pago(pago: dict[str, Any]) -> str:
    metadata = _metadata_pago(pago)
    tipo = str(metadata.get("tipo_pago", TIPO_PAGO_MANUAL)).lower()
    if tipo == TIPO_PAGO_SUSCRIPCION:
        return TIPO_PAGO_SUSCRIPCION
    return TIPO_PAGO_MANUAL


def _resolver_agencia_id_desde_pago(pago: dict[str, Any]) -> int | None:
    agencia_id = extraer_agencia_id_de_referencia(pago.get("external_reference"))
    if agencia_id:
        return agencia_id

    metadata = pago.get("metadata") or {}
    if isinstance(metadata, dict):
        valor = metadata.get("agencia_id")
        if valor is not None:
            try:
                return int(valor)
            except (TypeError, ValueError):
                pass
    return None


def _resolver_agencia_id_desde_preapproval(preapproval: dict[str, Any]) -> int | None:
    agencia_id = extraer_agencia_id_de_referencia(preapproval.get("external_reference"))
    if agencia_id:
        return agencia_id

    metadata = preapproval.get("metadata") or {}
    if isinstance(metadata, dict):
        valor = metadata.get("agencia_id")
        if valor is not None:
            try:
                return int(valor)
            except (TypeError, ValueError):
                pass
    return None


def _pago_ya_procesado(db, resource_id: str) -> bool:
    return (
        db.query(PagoMercadoPago)
        .filter(PagoMercadoPago.mp_resource_id == str(resource_id))
        .first()
        is not None
    )


def _registrar_pago_procesado(
    db,
    agencia_id: int,
    resource_id: str,
    tipo: str,
    monto: float | None,
) -> None:
    db.add(
        PagoMercadoPago(
            agencia_id=agencia_id,
            mp_resource_id=str(resource_id),
            tipo=tipo,
            monto=monto,
        )
    )
    db.commit()


def _aplicar_renovacion_por_pago(
    db,
    agencia_id: int,
    payment_id: str | int,
    pago: dict[str, Any],
) -> dict[str, Any]:
    """Flujo unificado: idempotencia + renovación para pago manual o de suscripción."""
    resource_id = str(payment_id)
    if _pago_ya_procesado(db, resource_id):
        return {
            "procesado": True,
            "duplicado": True,
            "agencia_id": agencia_id,
            "tipo_pago": _clasificar_tipo_pago(pago),
            "motivo": "Pago ya registrado (idempotencia).",
        }

    agencia = renovar_suscripcion_agencia(agencia_id, DIAS_RENOVACION_PAGO, db=db)
    if not agencia:
        return {
            "procesado": False,
            "motivo": f"Agencia {agencia_id} no encontrada.",
        }

    tipo_pago = _clasificar_tipo_pago(pago)
    monto = pago.get("transaction_amount")
    _registrar_pago_procesado(
        db,
        agencia_id=agencia_id,
        resource_id=resource_id,
        tipo=tipo_pago,
        monto=float(monto) if monto is not None else None,
    )
    return {
        "procesado": True,
        "agencia_id": agencia_id,
        "tipo_pago": tipo_pago,
        "fecha_vencimiento": str(agencia.fecha_vencimiento),
        "estado_pago": agencia.estado_pago,
    }


def procesar_pago_aprobado(payment_id: str | int) -> dict[str, Any]:
    """Consulta el pago en MP, valida estado y renueva la agencia (manual o suscripción)."""
    pago = obtener_pago(payment_id)
    estado = (pago.get("status") or "").lower()
    if estado != "approved":
        return {
            "procesado": False,
            "motivo": f"Pago {payment_id} con estado '{estado}', no aprobado.",
        }

    agencia_id = _resolver_agencia_id_desde_pago(pago)
    if not agencia_id:
        return {
            "procesado": False,
            "motivo": f"Pago {payment_id} sin referencia de agencia.",
        }

    db = SessionLocal()
    try:
        return _aplicar_renovacion_por_pago(db, agencia_id, payment_id, pago)
    finally:
        db.close()


def procesar_preapproval_autorizada(preapproval_id: str) -> dict[str, Any]:
    """Marca renovación automática cuando la suscripción queda autorizada."""
    preapproval = obtener_preapproval(preapproval_id)
    estado = (preapproval.get("status") or "").lower()
    if estado != "authorized":
        return {
            "procesado": False,
            "motivo": f"Preapproval {preapproval_id} con estado '{estado}'.",
        }

    agencia_id = _resolver_agencia_id_desde_preapproval(preapproval)
    if not agencia_id:
        return {
            "procesado": False,
            "motivo": f"Preapproval {preapproval_id} sin referencia de agencia.",
        }

    db = SessionLocal()
    try:
        agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
        if not agencia:
            return {
                "procesado": False,
                "motivo": f"Agencia {agencia_id} no encontrada.",
            }

        agencia.mp_preapproval_id = str(preapproval_id)
        agencia.mp_renovacion_automatica = True
        db.commit()

        return {
            "procesado": True,
            "agencia_id": agencia_id,
            "mp_preapproval_id": str(preapproval_id),
            "renovacion_automatica": True,
            "motivo": "Suscripción autorizada; la renovación llegará con el webhook de pago.",
        }
    finally:
        db.close()


def crear_suscripcion_recurrente(
    agencia: Agencia,
    payer_email: str,
) -> dict[str, Any]:
    """
    Crea una preapproval (suscripción) y devuelve init_point para el checkout de MP.
    Usa plan global (MERCADOPAGO_PLAN_ID) o crea suscripción sin plan.
    """
    cfg = obtener_config_mercadopago()
    external_reference = referencia_externa_agencia(agencia.id)
    back_url = f"{cfg['base_url']}/dashboard/{agencia.id}?suscripcion=ok"

    payload: dict[str, Any] = {
        "reason": f"Bot Agencias — {agencia.nombre}",
        "external_reference": external_reference,
        "payer_email": payer_email.strip(),
        "back_url": back_url,
        "status": "pending",
        "metadata": {
            "agencia_id": agencia.id,
            "tipo_pago": TIPO_PAGO_SUSCRIPCION,
        },
    }

    if cfg["plan_id"]:
        payload["preapproval_plan_id"] = cfg["plan_id"]
    else:
        payload["auto_recurring"] = {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": cfg["monto_mensual"],
            "currency_id": cfg["moneda"],
        }

    return _request_mp("POST", "/preapproval", payload)


def crear_preferencia_pago_unico(
    agencia: Agencia,
    payer_email: str,
) -> dict[str, Any]:
    """
    Crea una preferencia de Checkout para un pago único del mes actual.
    La renovación se aplica cuando el webhook recibe el pago aprobado.
    """
    cfg = obtener_config_mercadopago()
    external_reference = referencia_externa_agencia(agencia.id)
    base = f"{cfg['base_url']}/dashboard/{agencia.id}"

    payload: dict[str, Any] = {
        "items": [
            {
                "title": f"Bot Agencias — Mes actual ({agencia.nombre})",
                "quantity": 1,
                "unit_price": cfg["monto_mensual"],
                "currency_id": cfg["moneda"],
            }
        ],
        "payer": {"email": payer_email.strip()},
        "external_reference": external_reference,
        "metadata": {
            "agencia_id": agencia.id,
            "tipo_pago": TIPO_PAGO_MANUAL,
        },
        "back_urls": {
            "success": f"{base}?pago=ok",
            "failure": f"{base}?pago=error",
            "pending": f"{base}?pago=pendiente",
        },
        "auto_return": "approved",
        "notification_url": f"{cfg['base_url']}/api/mercadopago/webhook",
    }

    return _request_mp("POST", "/checkout/preferences", payload)
