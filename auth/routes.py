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
    CODIGO_2FA_DESARROLLO,
    confirmar_2fa,
    iniciar_login,
    obtener_usuario_por_id,
    registrar_usuario,
    usar_2fa_desarrollo,
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
    """
    Recibe la confirmación de login de Supabase.
    Si el usuario no existe en la base de datos de la agencia, lo registra con una nueva.
    """
    if not email:
        return RedirectResponse(url="/auth/login?error=No se recibió un correo válido de Google.", status_code=303)

    db = SessionLocal()
    try:
        from models.models import Usuario, Agencia  # Ajustá la importación según tus modelos locales
        
        # 1. Verificar si el usuario ya existe por su email
        usuario = db.query(Usuario).filter(Usuario.email == email).first()
        
        if not usuario:
            # Si el usuario es nuevo (se logueó con Google de una), le creamos su Agencia de prueba
            nueva_agencia = Agencia(nombre=f"Agencia de {nombre or 'Nuevo Usuario'}")
            db.add(nueva_agencia)
            db.commit()
            db.refresh(nueva_agencia)
            
            # Registramos el nuevo usuario asignado a esa agencia
            usuario = Usuario(
                email=email,
                nombre=nombre or email.split("@")[0],
                agencia_id=nueva_agencia.id,
                telefono="",
                activo=True
            )
            db.add(usuario)
            db.commit()
            db.refresh(usuario)
        
        # 2. Generar el token de sesión idéntico al tuyo tradicional
        sesion = crear_token_sesion(usuario.id, usuario.agencia_id)
        
        # 3. Redirigir directo al dashboard fucsia de su sucursal
        resp = RedirectResponse(url=f"/dashboard/{usuario.agencia_id}", status_code=303)
        resp.set_cookie(COOKIE_SESION, sesion, **_COOKIE_OPTS)
        return resp
        
    except Exception as e:
        print(f"Error en callback Supabase: {str(e)}")
        return RedirectResponse(url=f"/auth/login?error=Error interno al procesar el acceso con Google.", status_code=303)
    finally:
        db.close()
