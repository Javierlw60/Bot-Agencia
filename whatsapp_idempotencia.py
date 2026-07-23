"""Idempotencia de webhooks de WhatsApp (Meta reintenta si tarda o hay 2 URLs)."""

from __future__ import annotations

import datetime
import threading
import time

from sqlalchemy import Column, DateTime, Integer, String

from models.database import Base, SessionLocal, engine

# Evita doble procesamiento concurrente del mismo wamid en el mismo proceso.
_locks: dict[str, float] = {}
_locks_guard = threading.Lock()
_LOCK_TTL_SEG = 120
_tabla_lista = False


class WhatsappEventoProcesado(Base):
    __tablename__ = "whatsapp_eventos_procesados"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(200), unique=True, nullable=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)


def asegurar_tabla_idempotencia_whatsapp() -> None:
    global _tabla_lista
    if _tabla_lista:
        return
    try:
        Base.metadata.tables["whatsapp_eventos_procesados"].create(
            bind=engine, checkfirst=True
        )
    except Exception as exc:
        print(f"[WA IDEMP] No se pudo crear tabla: {exc}")
    _tabla_lista = True


def _limpiar_locks_viejos(ahora: float) -> None:
    vencidos = [k for k, ts in _locks.items() if ahora - ts > _LOCK_TTL_SEG]
    for k in vencidos:
        _locks.pop(k, None)


def reclamar_mensaje_whatsapp(message_id: str | None) -> bool:
    """
    True = este worker debe procesarlo.
    False = ya se procesó o otro worker lo tiene (no responder de nuevo).
    """
    mid = (message_id or "").strip()
    if not mid:
        return True

    ahora = time.monotonic()
    with _locks_guard:
        _limpiar_locks_viejos(ahora)
        if mid in _locks:
            print(f"[WA IDEMP] Skip (en vuelo): {mid[:48]}…")
            return False
        _locks[mid] = ahora

    asegurar_tabla_idempotencia_whatsapp()
    db = SessionLocal()
    try:
        existe = (
            db.query(WhatsappEventoProcesado)
            .filter(WhatsappEventoProcesado.message_id == mid)
            .first()
        )
        if existe:
            print(f"[WA IDEMP] Skip (ya procesado): {mid[:48]}…")
            return False
        db.add(WhatsappEventoProcesado(message_id=mid))
        db.commit()
        return True
    except Exception as exc:
        db.rollback()
        print(f"[WA IDEMP] Skip (conflicto/ya existe): {mid[:48]}… ({exc})")
        return False
    finally:
        db.close()


def liberar_lock_mensaje(message_id: str | None) -> None:
    mid = (message_id or "").strip()
    if not mid:
        return
    with _locks_guard:
        _locks.pop(mid, None)


def liberar_reclamo_si_fallo(message_id: str | None) -> None:
    """Si el procesamiento falló, borra el reclamo para que Meta pueda reintentar."""
    mid = (message_id or "").strip()
    liberar_lock_mensaje(mid)
    if not mid:
        return
    asegurar_tabla_idempotencia_whatsapp()
    db = SessionLocal()
    try:
        (
            db.query(WhatsappEventoProcesado)
            .filter(WhatsappEventoProcesado.message_id == mid)
            .delete(synchronize_session=False)
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[WA IDEMP] No se pudo liberar reclamo {mid[:48]}…: {exc}")
    finally:
        db.close()
