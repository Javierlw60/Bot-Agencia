"""Middleware que persiste la sucursal activa en cookie tras cada vista del dashboard."""

import re

from starlette.middleware.base import BaseHTTPMiddleware

from dashboard.sucursal_sesion import escribir_sucursal_cookie

_RUTA_DASHBOARD = re.compile(r"^/dashboard/(\d+)")


class MiddlewareSucursalActiva(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        guardar = getattr(request.state, "sucursal_cookie_guardar", None)
        if not guardar:
            return response

        match = _RUTA_DASHBOARD.match(request.url.path)
        if not match:
            return response

        agencia_id, sucursal_id = guardar
        if int(match.group(1)) != agencia_id:
            return response

        escribir_sucursal_cookie(response, agencia_id, sucursal_id)
        return response
