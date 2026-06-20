import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from auth.sesiones import COOKIE_SESION, leer_sesion
from models.database import SessionLocal, Usuario

_RUTA_DASHBOARD = re.compile(r"^/dashboard/(\d+)")
_RUTA_PWA = re.compile(r"^/dashboard/\d+/(manifest\.webmanifest|sw\.js)$")
_PREFIJOS_PUBLICOS = (
    "/auth",
    "/static",
    "/health",
    "/webhook",
    "/api/mercadopago",
    "/api/bot",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class MiddlewareAutenticacion(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        if path == "/":
            return RedirectResponse(url="/auth/login", status_code=302)

        if any(path.startswith(p) for p in _PREFIJOS_PUBLICOS):
            return await call_next(request)

        if _RUTA_PWA.match(path):
            return await call_next(request)

        match = _RUTA_DASHBOARD.match(path)
        if not match:
            return await call_next(request)

        payload = leer_sesion(request.cookies.get(COOKIE_SESION))
        if not payload:
            return RedirectResponse(url="/auth/login", status_code=303)

        agencia_solicitada = int(match.group(1))
        if payload.get("aid") != agencia_solicitada:
            return RedirectResponse(url=f"/dashboard/{payload['aid']}", status_code=303)

        db = SessionLocal()
        try:
            usuario = (
                db.query(Usuario)
                .filter(Usuario.id == payload["uid"], Usuario.activo.is_(True))
                .first()
            )
            if not usuario or usuario.agencia_id != agencia_solicitada:
                resp = RedirectResponse(url="/auth/login", status_code=303)
                resp.delete_cookie(COOKIE_SESION)
                return resp
            request.state.usuario = usuario
        finally:
            db.close()

        return await call_next(request)
