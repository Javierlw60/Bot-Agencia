"""Configuración centralizada de WhatsApp Cloud API (variables de entorno)."""

import os

from dotenv import load_dotenv

load_dotenv()


def whatsapp_verify_token() -> str:
    """Token que Meta envía en hub.verify_token al validar el webhook."""
    return (
        os.getenv("WHATSAPP_VERIFY_TOKEN")
        or os.getenv("VERIFY_TOKEN")
        or "bot_agencias_verify"
    ).strip()


def whatsapp_access_token() -> str:
    """Access Token permanente o temporal de Meta Graph API."""
    return (
        os.getenv("WHATSAPP_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or ""
    ).strip()


def whatsapp_phone_number_id() -> str:
    """Phone Number ID por defecto (Meta) si el payload no lo trae."""
    return (
        os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        or os.getenv("PHONE_NUMBER_ID")
        or os.getenv("AUTH_WHATSAPP_PHONE_NUMBER_ID")
        or ""
    ).strip()


def whatsapp_api_version() -> str:
    return os.getenv("WHATSAPP_API_VERSION", "v21.0").strip()


def whatsapp_modo() -> str:
    return os.getenv("WHATSAPP_MODO", "consola").lower().strip()
