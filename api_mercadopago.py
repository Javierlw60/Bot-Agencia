"""Webhook y utilidades HTTP de Mercado Pago."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from mercadopago_config import obtener_config_mercadopago
from mercadopago_seguridad import validar_firma_webhook, validar_user_id_notificacion
from mercadopago_servicio import (
    MercadoPagoError,
    procesar_pago_aprobado,
    procesar_preapproval_autorizada,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mercadopago", tags=["mercadopago"])

_TOPICS_PAGO = {"payment", "payments"}
_TOPICS_SUSCRIPCION = {
    "subscription_preapproval",
    "preapproval",
    "authorized_payment",
}


def _extraer_data_id(request: Request, body: dict[str, Any]) -> str | None:
    query_id = request.query_params.get("data.id") or request.query_params.get("id")
    if query_id:
        return str(query_id)

    data = body.get("data")
    if isinstance(data, dict) and data.get("id") is not None:
        return str(data["id"])
    if body.get("id") is not None and body.get("type"):
        return str(body["id"])
    return None


def _extraer_topic(request: Request, body: dict[str, Any]) -> str:
    topic = (
        request.query_params.get("type")
        or request.query_params.get("topic")
        or body.get("type")
        or body.get("topic")
        or body.get("action")
        or ""
    )
    return str(topic).lower()


def _validar_seguridad_webhook(
    request: Request,
    body: dict[str, Any],
    data_id: str | None,
) -> None:
    cfg = obtener_config_mercadopago()
    if not cfg["validar_webhook"]:
        return

    ok_user, msg_user = validar_user_id_notificacion(body.get("user_id"), cfg["user_id"])
    if not ok_user:
        raise HTTPException(status_code=401, detail=msg_user)

    ok_sig, msg_sig = validar_firma_webhook(
        secret=cfg["webhook_secret"],
        x_signature=request.headers.get("x-signature"),
        x_request_id=request.headers.get("x-request-id"),
        data_id=data_id,
    )
    if not ok_sig:
        raise HTTPException(status_code=401, detail=msg_sig)


@router.post("/webhook")
async def webhook_mercadopago(request: Request):
    """
    Recibe notificaciones IPN/Webhooks de Mercado Pago.
    Configurá la URL en Tu integración → Webhooks:
    https://tu-dominio/api/mercadopago/webhook
    """
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        body = {}

    data_id = _extraer_data_id(request, body)
    topic = _extraer_topic(request, body)

    try:
        _validar_seguridad_webhook(request, body, data_id)
    except HTTPException:
        logger.warning("Webhook MP rechazado por seguridad (topic=%s)", topic)
        raise

    if not data_id:
        return JSONResponse({"ok": True, "ignorado": True, "motivo": "Sin data.id"})

    resultado: dict[str, Any] = {"ok": True, "topic": topic, "data_id": data_id}

    try:
        if topic in _TOPICS_PAGO or "payment" in topic:
            resultado["resultado"] = procesar_pago_aprobado(data_id)
        elif topic in _TOPICS_SUSCRIPCION or "preapproval" in topic:
            resultado["resultado"] = procesar_preapproval_autorizada(data_id)
        else:
            resultado["ignorado"] = True
            resultado["motivo"] = f"Topic '{topic}' no gestionado."
    except MercadoPagoError as exc:
        logger.error("Error procesando webhook MP: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info("Webhook MP procesado: %s", resultado)
    return JSONResponse(resultado)


@router.get("/webhook")
async def webhook_mercadopago_get(request: Request):
    """Algunas notificaciones legacy de MP llegan por GET."""
    body = {
        "type": request.query_params.get("topic") or request.query_params.get("type"),
        "data": {"id": request.query_params.get("id") or request.query_params.get("data.id")},
        "user_id": request.query_params.get("user_id"),
    }
    data_id = _extraer_data_id(request, body)
    topic = _extraer_topic(request, body)

    try:
        _validar_seguridad_webhook(request, body, data_id)
    except HTTPException:
        logger.warning("Webhook MP GET rechazado (topic=%s)", topic)
        raise

    if not data_id:
        return {"ok": True, "ignorado": True}

    if topic in _TOPICS_PAGO or "payment" in topic:
        return {"ok": True, "resultado": procesar_pago_aprobado(data_id)}
    if topic in _TOPICS_SUSCRIPCION or "preapproval" in topic:
        return {"ok": True, "resultado": procesar_preapproval_autorizada(data_id)}
    return {"ok": True, "ignorado": True, "topic": topic}
