from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from auth.sesiones import (
    COOKIE_PENDIENTE_2FA,
    COOKIE_SESION,
    crear_token_pendiente_2fa,
    crear_token_sesion,
)
from auth.servicio import (
    confirmar_2fa,
    iniciar_login,
    registrar_usuario,
    verificar_email,
)
from models.database import SessionLocal

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_OPTS = {
    "httponly": True,
    "samesite": "lax",
    "max_age": 60 * 60 * 24 * 7,
}


@router.get("/login", response_class=HTMLResponse)
async def pagina_login(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"error": request.query_params.get("error"), "ok": request.query_params.get("ok")},
    )


@router.get("/registro", response_class=HTMLResponse)
async def pagina_registro(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/registro.html",
        context={"error": request.query_params.get("error")},
    )


@router.get("/verificar-2fa", response_class=HTMLResponse)
async def pagina_verificar_2fa(request: Request):
    if not request.cookies.get(COOKIE_PENDIENTE_2FA):
        return RedirectResponse(url="/auth/login?error=sesion_2fa", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth/verificar_2fa.html",
        context={"error": request.query_params.get("error")},
    )


@router.get("/registro-enviado", response_class=HTMLResponse)
async def pagina_registro_enviado(request: Request):
    return templates.TemplateResponse(request=request, name="auth/registro_enviado.html", context={})


@router.get("/verificar-email")
async def enlace_verificar_email(token: str = ""):
    db = SessionLocal()
    try:
        ok, mensaje = verificar_email(db, token)
        param = "ok=email" if ok else f"error={mensaje[:120]}"
        return RedirectResponse(url=f"/auth/login?{param}", status_code=303)
    finally:
        db.close()


@router.post("/registro")
async def procesar_registro(
    nombre: str = Form(...),
    nombre_agencia: str = Form(...),
    email: str = Form(...),
    telefono: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if password != password_confirm:
        return RedirectResponse(url="/auth/registro?error=Las contraseñas no coinciden.", status_code=303)

    db = SessionLocal()
    try:
        _, error = registrar_usuario(db, email, password, telefono, nombre, nombre_agencia)
        if error:
            from urllib.parse import quote
            return RedirectResponse(url=f"/auth/registro?error={quote(error)}", status_code=303)
        return RedirectResponse(url="/auth/registro-enviado", status_code=303)
    finally:
        db.close()


@router.post("/login")
async def procesar_login(email: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        usuario, error = iniciar_login(db, email, password)
        if error or not usuario:
            from urllib.parse import quote
            return RedirectResponse(
                url=f"/auth/login?error={quote(error or 'No se pudo iniciar sesión.')}",
                status_code=303,
            )
        token_2fa = crear_token_pendiente_2fa(usuario.id)
        resp = RedirectResponse(url="/auth/verificar-2fa", status_code=303)
        resp.set_cookie(
            COOKIE_PENDIENTE_2FA,
            token_2fa,
            httponly=True,
            samesite="lax",
            max_age=60 * 10,
        )
        return resp
    finally:
        db.close()


@router.post("/verificar-2fa")
async def procesar_verificar_2fa(request: Request, codigo: str = Form(...)):
    from auth.sesiones import leer_pendiente_2fa

    pendiente = leer_pendiente_2fa(request.cookies.get(COOKIE_PENDIENTE_2FA))
    if not pendiente:
        return RedirectResponse(url="/auth/login?error=La verificación expiró. Iniciá sesión de nuevo.", status_code=303)

    db = SessionLocal()
    try:
        usuario, error = confirmar_2fa(db, pendiente["uid"], codigo)
        if error or not usuario:
            from urllib.parse import quote
            return RedirectResponse(
                url=f"/auth/verificar-2fa?error={quote(error or 'Código inválido.')}",
                status_code=303,
            )

        sesion = crear_token_sesion(usuario.id, usuario.agencia_id)
        resp = RedirectResponse(url=f"/dashboard/{usuario.agencia_id}", status_code=303)
        resp.set_cookie(COOKIE_SESION, sesion, **_COOKIE_OPTS)
        resp.delete_cookie(COOKIE_PENDIENTE_2FA)
        return resp
    finally:
        db.close()


@router.post("/cerrar-sesion")
async def cerrar_sesion():
    resp = RedirectResponse(url="/auth/login", status_code=303)
    resp.delete_cookie(COOKIE_SESION)
    resp.delete_cookie(COOKIE_PENDIENTE_2FA)
    return resp
