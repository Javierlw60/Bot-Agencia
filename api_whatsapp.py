"""Webhook de WhatsApp Cloud API: mensajes de texto y audio."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from inventory import resolver_destino_por_receptor_whatsapp
from models.database import Agencia, Sucursal, Vendedor
from suscripcion_agencias import evaluar_agencia_para_operar
from whatsapp_config import whatsapp_phone_number_id, whatsapp_verify_token
from whatsapp_entrada import procesar_audio_whatsapp, procesar_texto_whatsapp

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp-webhook"])


def _verificar_suscripcion_meta(
    hub_mode: str | None,
    hub_verify_token: str | None,
    hub_challenge: str | None,
) -> PlainTextResponse:
    """GET de Meta: devuelve hub.challenge si el verify token coincide."""
    esperado = whatsapp_verify_token()
    if hub_mode == "subscribe" and hub_verify_token == esperado:
        logger.info("Webhook WhatsApp verificado correctamente.")
        return PlainTextResponse(content=hub_challenge or "")
    logger.warning(
        "Verificación webhook rechazada (mode=%s, token_coincide=%s)",
        hub_mode,
        hub_verify_token == esperado,
    )
    raise HTTPException(status_code=403, detail="Token de verificación inválido.")


def _linea_whatsapp_respuesta(
    agencia: Agencia,
    sucursal: Sucursal | None,
    vendedor: Vendedor | None = None,
) -> str:
    if vendedor and vendedor.telefono_whatsapp:
        return vendedor.telefono_whatsapp
    if sucursal and sucursal.telefono_whatsapp:
        return sucursal.telefono_whatsapp
    return agencia.whatsapp_phone_number_id


def _extraer_mensajes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mensajes: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            phone_id = (value.get("metadata") or {}).get("phone_number_id")
            for msg in value.get("messages", []):
                mensajes.append(
                    {
                        "phone_number_id": phone_id,
                        "from": msg.get("from"),
                        "type": msg.get("type"),
                        "id": msg.get("id"),
                        "text": (msg.get("text") or {}).get("body"),
                        "audio_id": (msg.get("audio") or {}).get("id"),
                    }
                )
    return mensajes


def _resolver_phone_number_id(msg: dict[str, Any], fallback: str | None = None) -> str:
    """Phone Number ID del mensaje (metadata) o fallback (.env / URL legacy)."""
    return (
        str(msg.get("phone_number_id") or "").strip()
        or (fallback or "").strip()
        or whatsapp_phone_number_id()
    )


def _procesar_un_mensaje(msg: dict[str, Any], phone_number_id: str) -> dict[str, Any]:
    telefono = str(msg.get("from") or "")
    if not telefono:
        return {"ok": False, "motivo": "sin_telefono"}

    agencia, sucursal, vendedor = resolver_destino_por_receptor_whatsapp(phone_number_id)
    if not agencia:
        logger.warning("Webhook WA sin agencia para phone_id=%s", phone_number_id)
        return {"ok": False, "motivo": "Agencia no encontrada", "phone_number_id": phone_number_id}

    linea_respuesta = _linea_whatsapp_respuesta(agencia, sucursal, vendedor)

    puede, mensaje_bloqueo = evaluar_agencia_para_operar(agencia.id)
    if not puede:
        from whatsapp import enviar_respuesta_bot

        if mensaje_bloqueo:
            enviar_respuesta_bot(
                telefono_destino=telefono,
                mensaje=mensaje_bloqueo,
                whatsapp_phone_number_id=linea_respuesta,
                modo_respuesta=agencia.modo_respuesta,
                imprimir_texto_en_consola=False,
            )
        return {"ok": False, "bloqueado": True, "phone_number_id": phone_number_id}

    tipo = msg.get("type")
    if tipo == "text" and msg.get("text"):
        respuesta = procesar_texto_whatsapp(
            agencia, telefono, msg["text"], sucursal=sucursal, vendedor=vendedor
        )
        return {"ok": True, "tipo": "text", "respuesta": respuesta, "phone_number_id": phone_number_id}
    if tipo == "audio" and msg.get("audio_id"):
        resultado = procesar_audio_whatsapp(
            agencia=agencia,
            telefono=telefono,
            media_id=msg["audio_id"],
            whatsapp_message_id=msg.get("id"),
            sucursal=sucursal,
            vendedor=vendedor,
        )
        return {"ok": True, "tipo": "audio", "phone_number_id": phone_number_id, **resultado}
    return {"ok": True, "tipo": tipo, "ignorado": True, "phone_number_id": phone_number_id}


def _procesar_payload_webhook(
    payload: dict[str, Any],
    phone_number_id_fallback: str | None = None,
) -> dict[str, Any]:
    """Procesa el JSON completo que Meta envía por POST."""
    if payload.get("object") and payload.get("object") != "whatsapp_business_account":
        logger.debug("Webhook ignorado (object=%s)", payload.get("object"))
        return {"ok": True, "procesados": 0, "motivo": "object_no_whatsapp"}

    mensajes = _extraer_mensajes(payload)
    if not mensajes:
        # Meta también envía statuses (entregado/leído); no hay mensajes nuevos.
        return {"ok": True, "procesados": 0, "motivo": "sin_mensajes"}

    resultados = []
    for msg in mensajes:
        phone_id = _resolver_phone_number_id(msg, phone_number_id_fallback)
        if not phone_id:
            resultados.append({"ok": False, "motivo": "phone_number_id_no_configurado"})
            continue
        resultados.append(_procesar_un_mensaje(msg, phone_id))

    return {"ok": True, "procesados": len(resultados), "resultados": resultados}


@router.get("/webhook")
async def verificar_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """
    Validación inicial de Meta (Callback URL).
    Meta envía GET con hub.mode=subscribe y hub.verify_token.
    """
    return _verificar_suscripcion_meta(hub_mode, hub_verify_token, hub_challenge)


@router.post("/webhook")
async def recibir_webhook(request: Request):
    """Recibe notificaciones de WhatsApp (mensajes entrantes)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    logger.info("POST /webhook recibido (object=%s)", payload.get("object"))
    return _procesar_payload_webhook(payload)


@router.get("/webhook/whatsapp/{phone_number_id}")
async def verificar_webhook_whatsapp_legacy(
    phone_number_id: str,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Ruta legacy con phone_number_id en la URL (sigue soportada)."""
    return _verificar_suscripcion_meta(hub_mode, hub_verify_token, hub_challenge)


@router.post("/webhook/whatsapp/{phone_number_id}")
async def recibir_webhook_whatsapp_legacy(phone_number_id: str, request: Request):
    """Ruta legacy: usa phone_number_id de la URL solo como fallback."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    return _procesar_payload_webhook(payload, phone_number_id_fallback=phone_number_id)
