"""



Servidor web: dashboard + recordatorios + control de suscripción de agencias.



Ejecutar: uvicorn app:app --reload --port 8080



"""



from contextlib import asynccontextmanager

from pathlib import Path



from fastapi import FastAPI

from fastapi.responses import RedirectResponse

from fastapi.staticfiles import StaticFiles



from api_bot import router as bot_router
from api_mercadopago import router as mercadopago_router
from api_whatsapp import router as whatsapp_router

from auth.middleware import MiddlewareAutenticacion
from auth.routes import router as auth_router
from dashboard.routes import router as dashboard_router

from middleware_bot import MiddlewareAgenciaActiva

from models.database import inicializar_base_de_datos

from scheduler_tareas import detener_schedulers, iniciar_schedulers



BASE_DIR = Path(__file__).resolve().parent

(BASE_DIR / "static" / "uploads").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "static" / "cache" / "tts").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "static" / "temp" / "whatsapp").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "static" / "audit" / "audio").mkdir(parents=True, exist_ok=True)





@asynccontextmanager

async def lifespan(app: FastAPI):

    inicializar_base_de_datos()

    iniciar_schedulers()

    yield

    detener_schedulers()





app = FastAPI(title="Bot Agencias Multi-Tenant", version="0.5.0", lifespan=lifespan)

app.add_middleware(MiddlewareAutenticacion)
app.add_middleware(MiddlewareAgenciaActiva)

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

    return {

        "status": "ok",

        "dashboard": "/auth/login",

        "recordatorios": "activo",

        "suscripcion_cron": "activo",
        "mercadopago_webhook": "/api/mercadopago/webhook",
        "whatsapp_webhook": "/webhook/whatsapp/{phone_number_id}",

    }


