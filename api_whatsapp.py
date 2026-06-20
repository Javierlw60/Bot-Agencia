"""Webhook de WhatsApp Cloud API: mensajes de texto y audio."""

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from models.database import Agencia, SessionLocal
from suscripcion_agencias import evaluar_agencia_para_operar
from whatsapp_entrada import procesar_audio_whatsapp, procesar_texto_whatsapp

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp-webhook"])

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "bot_agencias_verify")


def _obtener_agencia_por_phone_id(phone_number_id: str) -> Agencia | None:
    db = SessionLocal()
    try:
        return (
            db.query(Agencia)
            .filter(Agencia.whatsapp_phone_number_id == phone_number_id)
            .first()
        )
    finally:
        db.close()


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


@router.get("/webhook/whatsapp/{phone_number_id}")
async def verificar_webhook_whatsapp(
    phone_number_id: str,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Verificación requerida por Meta al configurar el webhook."""
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge or "")
    raise HTTPException(status_code=403, detail="Token de verificación inválido.")


@router.post("/webhook/whatsapp/{phone_number_id}")
async def recibir_webhook_whatsapp(phone_number_id: str, request: Request):
    """Procesa mensajes entrantes (texto o audio) y delega al bot."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    agencia = _obtener_agencia_por_phone_id(phone_number_id)
    if not agencia:
        logger.warning("Webhook WA sin agencia para phone_id=%s", phone_number_id)
        return {"ok": False, "motivo": "Agencia no encontrada"}

    puede, mensaje_bloqueo = evaluar_agencia_para_operar(agencia.id)
    if not puede:
        from whatsapp import enviar_respuesta_bot

        telefono_bloqueo = None
        for item in _extraer_mensajes(payload):
            telefono_bloqueo = item.get("from")
            break
        if telefono_bloqueo and mensaje_bloqueo:
            enviar_respuesta_bot(
                telefono_destino=telefono_bloqueo,
                mensaje=mensaje_bloqueo,
                whatsapp_phone_number_id=agencia.whatsapp_phone_number_id,
                modo_respuesta=agencia.modo_respuesta,
                imprimir_texto_en_consola=False,
            )
        return {"ok": False, "bloqueado": True}

    resultados = []
    for msg in _extraer_mensajes(payload):
        if msg.get("phone_number_id") and msg["phone_number_id"] != phone_number_id:
            continue

        telefono = str(msg.get("from") or "")
        if not telefono:
            continue

        tipo = msg.get("type")
        if tipo == "text" and msg.get("text"):
            respuesta = procesar_texto_whatsapp(agencia, telefono, msg["text"])
            resultados.append({"tipo": "text", "respuesta": respuesta})
        elif tipo == "audio" and msg.get("audio_id"):
            resultado = procesar_audio_whatsapp(
                agencia=agencia,
                telefono=telefono,
                media_id=msg["audio_id"],
                whatsapp_message_id=msg.get("id"),
            )
            resultados.append({"tipo": "audio", **resultado})
        else:
            resultados.append({"tipo": tipo, "ignorado": True})

    return {"ok": True, "procesados": len(resultados), "resultados": resultados}
