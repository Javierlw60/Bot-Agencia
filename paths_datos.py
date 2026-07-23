"""Rutas de datos persistentes (BD local y archivos subidos).

En Render el disco del contenedor es efímero. Para no perder fotos/uploads:
  1) Creá un Persistent Disk
  2) Montalo p.ej. en /var/data
  3) Variable: DATA_DIR=/var/data

La base de datos de producción debe ir a Postgres (DATABASE_URL de Supabase).
DATA_DIR solo cubre archivos (fotos, TTS, temp) y el SQLite de desarrollo local.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROYECTO = Path(__file__).resolve().parent


@lru_cache
def data_dir() -> Path:
    cruda = os.getenv("DATA_DIR", "").strip()
    if cruda:
        ruta = Path(cruda)
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta
    return _PROYECTO


@lru_cache
def static_dir() -> Path:
    """
    Directorio 'static' escribible.
    Con DATA_DIR → <DATA_DIR>/static (persistente).
    Sin DATA_DIR → <proyecto>/static (local / efímero en Render).
    """
    if os.getenv("DATA_DIR", "").strip():
        ruta = data_dir() / "static"
    else:
        ruta = _PROYECTO / "static"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def ensure_static_subdirs() -> Path:
    base = static_dir()
    for rel in (
        "uploads",
        "cache/tts",
        "temp/whatsapp",
        "audit/audio",
    ):
        (base / rel).mkdir(parents=True, exist_ok=True)
    return base
