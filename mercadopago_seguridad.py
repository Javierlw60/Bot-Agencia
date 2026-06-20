import hashlib
import hmac
import time
from typing import Any


def _parsear_x_signature(x_signature: str) -> dict[str, str]:
    partes: dict[str, str] = {}
    for fragmento in x_signature.split(","):
        fragmento = fragmento.strip()
        if "=" not in fragmento:
            continue
        clave, valor = fragmento.split("=", 1)
        partes[clave.strip()] = valor.strip()
    return partes


def construir_manifest_firma(
    data_id: str | None,
    x_request_id: str | None,
    ts: str | None,
) -> str:
    """Plantilla oficial de Mercado Pago para validar x-signature."""
    bloques: list[str] = []
    if data_id:
        bloques.append(f"id:{str(data_id).lower()};")
    if x_request_id:
        bloques.append(f"request-id:{x_request_id};")
    if ts:
        bloques.append(f"ts:{ts};")
    return "".join(bloques)


def validar_firma_webhook(
    secret: str,
    x_signature: str | None,
    x_request_id: str | None,
    data_id: str | None,
    tolerancia_segundos: int = 300,
) -> tuple[bool, str]:
    if not secret:
        return False, "Falta MERCADOPAGO_WEBHOOK_SECRET."
    if not x_signature:
        return False, "Encabezado x-signature ausente."

    partes = _parsear_x_signature(x_signature)
    ts = partes.get("ts")
    v1 = partes.get("v1")
    if not ts or not v1:
        return False, "x-signature inválido (falta ts o v1)."

    try:
        ts_ms = int(ts)
    except ValueError:
        return False, "Timestamp de x-signature inválido."

    ahora_ms = int(time.time() * 1000)
    if abs(ahora_ms - ts_ms) > tolerancia_segundos * 1000:
        return False, "Notificación fuera de la ventana de tolerancia."

    manifest = construir_manifest_firma(data_id, x_request_id, ts)
    calculado = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculado, v1):
        return False, "Firma x-signature no coincide."

    return True, ""


def validar_user_id_notificacion(user_id: Any, user_id_esperado: str) -> tuple[bool, str]:
    if not user_id_esperado:
        return True, ""
    if user_id is None:
        return False, "Notificación sin user_id."
    if str(user_id).strip() != str(user_id_esperado).strip():
        return False, "user_id de la notificación no coincide con la cuenta configurada."
    return True, ""
