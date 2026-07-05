from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import os
import secrets

from auth.passwords import hash_password
from auth.sesiones import (
    COOKIE_PENDIENTE_2FA,
    COOKIE_SESION,
    crear_token_pendiente_2fa,
    crear_token_sesion,
)
from auth.servicio import (
    CODIGO_2FA_DESARROLLO,
    confirmar_2fa,
    iniciar_login,
    obtener_usuario_por_id,
    registrar_usuario,
    usar_2fa_desarrollo,
    verificar_email,
)
from models.database import Agencia, SessionLocal, Usuario

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_OPTS = {
    "httponly": True,
    "samesite": "lax",
    "max_age": 60 * 60 * 24 * 7,
}


def _es_host_local(request: Request) -> bool:
    host = (request.url.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    client = (request.client.host if request.client else "").lower()
    return client in {"127.0.0.1", "::1"}


@router.get("/login", response_class=HTMLResponse)
async def pagina_login(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={
            "error": request.query_params.get("error"),
            "ok": request.query_params.get("ok"),
            "supabase_url": os.getenv("SUPABASE_URL", "").strip(),
            "supabase_anon_key": os.getenv("SUPABASE_ANON_KEY", "").strip(),
        },
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
    from auth.sesiones import leer_pendiente_2fa

    if not request.cookies.get(COOKIE_PENDIENTE_2FA):
        return RedirectResponse(url="/auth/login?error=sesion_2fa", status_code=303)

    codigo_desarrollo = None
    pendiente = leer_pendiente_2fa(request.cookies.get(COOKIE_PENDIENTE_2FA))
    if pendiente:
        db = SessionLocal()
        try:
            usuario = obtener_usuario_por_id(db, pendiente["uid"])
            if usuario and usar_2fa_desarrollo(usuario.email):
                codigo_desarrollo = CODIGO_2FA_DESARROLLO
        finally:
            db.close()

    return templates.TemplateResponse(
        request=request,
        name="auth/verificar_2fa.html",
        context={
            "error": request.query_params.get("error"),
            "codigo_desarrollo": codigo_desarrollo,
        },
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
async def procesar_login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        usuario, error, ingreso_directo = iniciar_login(
            db,
            email,
            password,
            es_entorno_local=_es_host_local(request),
        )
        if error or not usuario:
            from urllib.parse import quote
            return RedirectResponse(
                url=f"/auth/login?error={quote(error or 'No se pudo iniciar sesión.')}",
                status_code=303,
            )
        if ingreso_directo:
            sesion = crear_token_sesion(usuario.id, usuario.agencia_id)
            resp = RedirectResponse(url=f"/dashboard/{usuario.agencia_id}", status_code=303)
            resp.set_cookie(COOKIE_SESION, sesion, **_COOKIE_OPTS)
            return resp

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


@router.get("/oauth-callback", response_class=HTMLResponse)
async def pagina_oauth_callback(request: Request):
    """Página intermedia: Supabase devuelve acá; el JS completa la sesión y llama al backend."""
    return templates.TemplateResponse(
        request=request,
        name="auth/oauth_callback.html",
        context={
            "supabase_url": os.getenv("SUPABASE_URL", "").strip(),
            "supabase_anon_key": os.getenv("SUPABASE_ANON_KEY", "").strip(),
        },
    )


@router.post("/cerrar-sesion")
async def cerrar_sesion():
    resp = RedirectResponse(url="/auth/login", status_code=303)
    resp.delete_cookie(COOKIE_SESION)
    resp.delete_cookie(COOKIE_PENDIENTE_2FA)
    return resp

# =====================================================================
# ENDPOINT PARA GOOGLE OAUTH CON SUPABASE
# =====================================================================
@router.get("/supabase-callback")
async def supabase_callback(request: Request, email: str = "", nombre: str = ""):
    """Recibe email/nombre tras OAuth en el cliente y abre sesión en la BD local."""
    email_norm = email.strip().lower()
    if not email_norm:
        return RedirectResponse(
            url="/auth/login?error=No se recibió un correo válido de Google.",
            status_code=303,
        )

    db = SessionLocal()
    try:
        usuario = db.query(Usuario).filter(Usuario.email == email_norm).first()

        if not usuario:
            nueva_agencia = Agencia(
                nombre=f"Agencia de {nombre.strip() or email_norm.split('@')[0]}",
                whatsapp_phone_number_id=f"oauth_{secrets.token_hex(12)}",
                estado_pago="activo",
            )
            db.add(nueva_agencia)
            db.flush()

            usuario = Usuario(
                email=email_norm,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                nombre=(nombre.strip() or email_norm.split("@")[0])[:100],
                telefono_whatsapp=f"sin-oauth-{secrets.token_hex(4)}",
                email_verificado=True,
                agencia_id=nueva_agencia.id,
                activo=True,
            )
            db.add(usuario)
            db.commit()
            db.refresh(usuario)
        elif not usuario.email_verificado:
            usuario.email_verificado = True
            db.commit()

        sesion = crear_token_sesion(usuario.id, usuario.agencia_id)
        resp = RedirectResponse(url=f"/dashboard/{usuario.agencia_id}", status_code=303)
        resp.set_cookie(COOKIE_SESION, sesion, **_COOKIE_OPTS)
        return resp

    except Exception as e:
        print(f"Error en callback Supabase: {e}")
        return RedirectResponse(
            url="/auth/login?error=Error interno al procesar el acceso con Google.",
            status_code=303,
        )
    finally:
        db.close()
