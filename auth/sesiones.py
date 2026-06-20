import hashlib
import hmac
import json
import os
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

COOKIE_SESION = "ba_session"
COOKIE_PENDIENTE_2FA = "ba_2fa"
_DURACION_SESION_SEG = 60 * 60 * 24 * 7
_DURACION_PENDIENTE_2FA_SEG = 60 * 10


def _secreto() -> bytes:
    key = os.getenv("AUTH_SECRET_KEY", "").strip()
    if not key:
        key = "cambiar-en-produccion-" + os.getenv("GEMINI_API_KEY", "dev")[:16]
    return key.encode("utf-8")


def _firmar(payload: dict[str, Any]) -> str:
    cuerpo = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    firma = hmac.new(_secreto(), cuerpo, hashlib.sha256).hexdigest()
    return json.dumps({"p": payload, "s": firma}, separators=(",", ":"))


def _verificar(token: str) -> dict[str, Any] | None:
    try:
        data = json.loads(token)
        payload = data["p"]
        firma = data["s"]
        cuerpo = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        esperada = hmac.new(_secreto(), cuerpo, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(firma, esperada):
            return None
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def crear_token_sesion(usuario_id: int, agencia_id: int) -> str:
    return _firmar({
        "uid": usuario_id,
        "aid": agencia_id,
        "exp": time.time() + _DURACION_SESION_SEG,
        "t": "session",
    })


def crear_token_pendiente_2fa(usuario_id: int) -> str:
    return _firmar({
        "uid": usuario_id,
        "exp": time.time() + _DURACION_PENDIENTE_2FA_SEG,
        "t": "2fa",
    })


def leer_sesion(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    payload = _verificar(token)
    if not payload or payload.get("t") != "session":
        return None
    return payload


def leer_pendiente_2fa(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    payload = _verificar(token)
    if not payload or payload.get("t") != "2fa":
        return None
    return payload
