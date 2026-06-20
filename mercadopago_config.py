import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

MP_API_BASE = "https://api.mercadopago.com"


@lru_cache
def obtener_config_mercadopago() -> dict:
    return {
        "access_token": os.getenv("MERCADOPAGO_ACCESS_TOKEN", "").strip(),
        "user_id": os.getenv("MERCADOPAGO_USER_ID", "").strip(),
        "webhook_secret": os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "").strip(),
        "validar_webhook": os.getenv("MERCADOPAGO_WEBHOOK_VALIDAR", "true").lower()
        in ("1", "true", "yes", "si"),
        "plan_id": os.getenv("MERCADOPAGO_PLAN_ID", "").strip(),
        "monto_mensual": float(os.getenv("MERCADOPAGO_SUSCRIPCION_MONTO", "29999")),
        "moneda": os.getenv("MERCADOPAGO_MONEDA", "ARS"),
        "base_url": os.getenv("DASHBOARD_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
    }


def mercadopago_configurado() -> bool:
    cfg = obtener_config_mercadopago()
    return bool(cfg["access_token"])
