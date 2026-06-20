"""Endpoints del bot (webhook / API) con guard de suscripción."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from middleware_bot import require_agencia_activa
from models.database import Agencia, SessionLocal
from suscripcion_agencias import evaluar_agencia_para_operar
from whatsapp_entrada import procesar_texto_whatsapp

router = APIRouter(prefix="/api/bot", tags=["bot"])


class MensajeEntrada(BaseModel):
    telefono: str
    mensaje: str


class MensajeSalida(BaseModel):
    ok: bool
    respuesta: str


@router.post("/{agencia_id}/mensaje", response_model=MensajeSalida)
async def recibir_mensaje_bot(agencia_id: int, payload: MensajeEntrada):
    """
    Punto de entrada HTTP para mensajes del bot (texto).
    El middleware bloquea agencias suspendidas antes de llegar aquí.
    """
    require_agencia_activa(agencia_id)

    db = SessionLocal()
    try:
        agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
        if not agencia:
            raise HTTPException(status_code=404, detail="Agencia no encontrada")

        respuesta = procesar_texto_whatsapp(agencia, payload.telefono, payload.mensaje)
        return MensajeSalida(ok=True, respuesta=respuesta)
    finally:
        db.close()


@router.get("/{agencia_id}/estado-suscripcion")
async def estado_suscripcion(agencia_id: int):
    puede, mensaje = evaluar_agencia_para_operar(agencia_id)
    return {
        "activo": puede,
        "mensaje": mensaje if not puede else None,
    }
