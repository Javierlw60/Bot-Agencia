"""Middleware y dependencias para bloquear el bot si la agencia está suspendida."""

import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from suscripcion_agencias import (
    MENSAJE_SERVICIO_SUSPENDIDO,
    evaluar_agencia_para_operar,
    evaluar_agencia_por_whatsapp_id,
)

_RUTA_BOT_AGENCIA = re.compile(r"^/api/bot/(\d+)")
_RUTA_WEBHOOK_WHATSAPP = re.compile(r"^/webhook(?:/whatsapp/([^/]+))?$")


class MiddlewareAgenciaActiva(BaseHTTPMiddleware):
    """Intercepta peticiones del bot antes de procesar ventas."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        mensaje_bloqueo: str | None = None

        match_bot = _RUTA_BOT_AGENCIA.match(path)
        if match_bot:
            agencia_id = int(match_bot.group(1))
            puede, mensaje = evaluar_agencia_para_operar(agencia_id)
            if not puede:
                mensaje_bloqueo = mensaje

        match_wa = _RUTA_WEBHOOK_WHATSAPP.match(path)
        if match_wa:
            phone_id = match_wa.group(1)
            if phone_id:
                _, mensaje = evaluar_agencia_por_whatsapp_id(phone_id)
                if mensaje and mensaje != "Agencia no encontrada.":
                    mensaje_bloqueo = mensaje

        if mensaje_bloqueo:
            # El webhook de WhatsApp gestiona el bloqueo enviando mensaje al cliente.
            if match_wa and request.method == "POST":
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "bloqueado": True,
                    "respuesta": mensaje_bloqueo or MENSAJE_SERVICIO_SUSPENDIDO,
                },
            )

        return await call_next(request)


def require_agencia_activa(agencia_id: int) -> None:
    puede, mensaje = evaluar_agencia_para_operar(agencia_id)
    if not puede:
        raise HTTPException(
            status_code=403,
            detail=mensaje or MENSAJE_SERVICIO_SUSPENDIDO,
        )
