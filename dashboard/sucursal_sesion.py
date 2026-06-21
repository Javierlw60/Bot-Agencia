"""Persistencia de la sucursal activa del dashboard (cookie firmada por agencia)."""

import hashlib
import hmac
import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import Response

load_dotenv()

COOKIE_SUCURSAL = "ba_sucursal_nav"
_DURACION_SEG = 60 * 60 * 24 * 30


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


def leer_sucursal_cookie(request: Request, agencia_id: int) -> int | None:
    token = request.cookies.get(COOKIE_SUCURSAL)
    if not token:
        return None
    payload = _verificar(token)
    if not payload or payload.get("t") != "sucursal_nav":
        return None
    if payload.get("aid") != agencia_id:
        return None
    sid = payload.get("sid")
    return int(sid) if sid is not None else None


def escribir_sucursal_cookie(response: Response, agencia_id: int, sucursal_id: int) -> None:
    token = _firmar({
        "aid": agencia_id,
        "sid": sucursal_id,
        "exp": time.time() + _DURACION_SEG,
        "t": "sucursal_nav",
    })
    response.set_cookie(
        COOKIE_SUCURSAL,
        token,
        max_age=_DURACION_SEG,
        httponly=True,
        samesite="lax",
        path="/",
    )
