"""
Servidor web: dashboard + recordatorios + control de suscripción de agencias.

Ejecutar: uvicorn app:app --reload --port 8080
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api_bot import router as bot_router
from api_mercadopago import router as mercadopago_router
from api_whatsapp import router as whatsapp_router
from auth.middleware import MiddlewareAutenticacion
from auth.routes import router as auth_router
from dashboard.middleware_sucursal import MiddlewareSucursalActiva
from dashboard.routes import router as dashboard_router
from middleware_bot import MiddlewareAgenciaActiva
from models.database import DATABASE_URL, es_postgres, es_sqlite, inicializar_base_de_datos
from paths_datos import ensure_static_subdirs, static_dir
from scheduler_tareas import detener_schedulers, iniciar_schedulers

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
_static_writable = ensure_static_subdirs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    inicializar_base_de_datos()
    iniciar_schedulers()
    yield
    detener_schedulers()


app = FastAPI(title="Bot Agencias Multi-Tenant", version="0.5.0", lifespan=lifespan)

app.add_middleware(MiddlewareAutenticacion)
app.add_middleware(MiddlewareAgenciaActiva)
app.add_middleware(MiddlewareSucursalActiva)

# Uploads/caché pueden vivir en disco persistente (DATA_DIR); assets del repo en /static.
app.mount(
    "/static/uploads",
    StaticFiles(directory=str(_static_writable / "uploads")),
    name="static-uploads",
)
app.mount(
    "/static/cache",
    StaticFiles(directory=str(_static_writable / "cache")),
    name="static-cache",
)
app.mount(
    "/static/temp",
    StaticFiles(directory=str(_static_writable / "temp")),
    name="static-temp",
)
app.mount(
    "/static/audit",
    StaticFiles(directory=str(_static_writable / "audit")),
    name="static-audit",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(bot_router)
app.include_router(mercadopago_router)
app.include_router(whatsapp_router)


@app.get("/")
def inicio():
    return RedirectResponse(url="/auth/login", status_code=302)


@app.get("/health")
def health():
    motor = "postgres" if es_postgres() else ("sqlite" if es_sqlite() else "otro")
    destino = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    return {
        "status": "ok",
        "dashboard": "/auth/login",
        "recordatorios": "activo",
        "suscripcion_cron": "activo",
        "database": {"motor": motor, "destino": destino},
        "static_writable": str(static_dir()),
        "mercadopago_webhook": "/api/mercadopago/webhook",
        "whatsapp_webhook": "/webhook",
        "whatsapp_webhook_legacy": "/webhook/whatsapp/{phone_number_id}",
        "legal": {
            "privacy": "/privacy",
            "terms": "/terms",
            "contacto": "/contacto",
        },
    }


@app.get("/privacy", response_class=HTMLResponse)
async def pagina_privacidad(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="legal/pagina.html",
        context={
            "titulo": "Política de privacidad",
            "contenido": (
                "Bot Agencias es un panel de gestión y asistente comercial por WhatsApp "
                "para agencias automotrices. Recopilamos únicamente los datos necesarios "
                "para operar el servicio: información de cuenta del panel, datos de leads "
                "y citas, mensajes intercambiados con el bot, y metadatos técnicos "
                "(fecha, teléfono, identificadores de WhatsApp).\n\n"
                "Usamos estos datos para brindar el servicio contratado, mejorar la "
                "atención comercial y cumplir obligaciones legales. No vendemos datos "
                "personales a terceros. Los datos se almacenan en servidores seguros y "
                "se conservan mientras la cuenta esté activa o sea requerido por ley.\n\n"
                "Podés solicitar acceso, corrección o eliminación de tus datos en la "
                "página de contacto (/contacto). Para consultas sobre privacidad, escribinos "
                "desde el correo registrado en tu cuenta de agencia."
            ),
        },
    )


@app.get("/terms", response_class=HTMLResponse)
async def pagina_terminos(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="legal/pagina.html",
        context={
            "titulo": "Condiciones del servicio",
            "contenido": (
                "Al usar Bot Agencias aceptás estas condiciones. El servicio permite "
                "gestionar inventario, leads, citas y conversaciones comerciales por "
                "WhatsApp bajo suscripción.\n\n"
                "La agencia es responsable de la veracidad de la información cargada, "
                "del cumplimiento de normas de protección al consumidor y de contar con "
                "consentimiento válido para contactar a sus clientes por WhatsApp.\n\n"
                "Nos reservamos el derecho de suspender cuentas por incumplimiento, "
                "uso abusivo o falta de pago. El servicio se provee \"tal cual\"; no "
                "garantizamos disponibilidad ininterrumpida. Las modificaciones a estas "
                "condiciones se publicarán en esta misma URL."
            ),
        },
    )


@app.get("/contacto", response_class=HTMLResponse)
async def pagina_contacto(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="legal/pagina.html",
        context={
            "titulo": "Contacto y eliminación de datos",
            "contenido": (
                "Si deseás eliminar tus datos personales asociados a Bot Agencias, "
                "seguí estos pasos:\n\n"
                "1. Enviá un correo desde la dirección registrada en tu cuenta de agencia "
                "indicando \"Solicitud de eliminación de datos\".\n"
                "2. Incluí tu nombre, nombre de la agencia y teléfono vinculado al bot.\n"
                "3. Procesaremos la solicitud en un plazo máximo de 30 días hábiles y "
                "confirmaremos por correo cuando la eliminación haya finalizado.\n\n"
                "También podés solicitar acceso, rectificación o exportación de tus datos "
                "por el mismo canal. Si sos cliente final de una agencia (usuario de "
                "WhatsApp), contactá directamente a la agencia; ellos gestionan tus datos "
                "como responsables del tratamiento."
            ),
        },
    )
