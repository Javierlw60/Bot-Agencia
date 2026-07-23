"""Envío de correos de verificación.

Proveedores (prioridad):
  1. RESEND_API_KEY  → API de Resend
  2. SENDGRID_API_KEY → API de SendGrid
  3. SMTP_HOST (+ USER/PASSWORD/PORT) → SMTP clásico (Gmail, Outlook, etc.)
  4. Sin config → imprime el enlace en logs (solo desarrollo)

Variables:
  SMTP_HOST, SMTP_PORT (587|465), SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TLS
  RESEND_API_KEY, SENDGRID_API_KEY
  DASHBOARD_BASE_URL / APP_URL / FRONTEND_URL (para armar el enlace)
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("auth.correo")


def _base_url() -> str:
    for nombre in ("DASHBOARD_BASE_URL", "APP_URL", "FRONTEND_URL"):
        valor = os.getenv(nombre, "").strip().rstrip("/")
        if valor:
            return valor
    return "http://127.0.0.1:8080"


def _smtp_from() -> str:
    return (
        os.getenv("SMTP_FROM", "").strip()
        or os.getenv("SMTP_USER", "").strip()
        or "noreply@bot-agencias.com.ar"
    )


def _armar_mensaje(
    destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = formataddr(("Bot Agencias", _smtp_from()))
    msg["To"] = destino
    msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))
    return msg


def _enviar_por_smtp(destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return False

    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    usar_tls = os.getenv("SMTP_TLS", "true").lower() not in ("0", "false", "no")
    remitente = _smtp_from()
    msg = _armar_mensaje(destino, asunto, cuerpo_texto, cuerpo_html)

    try:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as server:
                if user and password:
                    server.login(user, password)
                server.sendmail(remitente, [destino], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                if usar_tls:
                    server.starttls(context=ssl.create_default_context())
                if user and password:
                    server.login(user, password)
                server.sendmail(remitente, [destino], msg.as_string())
        logger.info("[AUTH EMAIL] Enviado por SMTP a %s (host=%s:%s)", destino, host, port)
        print(f"[AUTH EMAIL] Enviado por SMTP a {destino} via {host}:{port}")
        return True
    except Exception as exc:
        logger.error("[AUTH EMAIL] Error SMTP: %s", exc)
        print(f"[AUTH EMAIL] Error SMTP: {exc}")
        return False


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=30) as resp:
        cuerpo = resp.read().decode("utf-8")
        return json.loads(cuerpo) if cuerpo else {}


def _enviar_por_resend(destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        return False

    payload = {
        "from": _smtp_from(),
        "to": [destino],
        "subject": asunto,
        "text": cuerpo_texto,
        "html": cuerpo_html,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        _post_json("https://api.resend.com/emails", payload, headers)
        logger.info("[AUTH EMAIL] Enviado por Resend a %s", destino)
        print(f"[AUTH EMAIL] Enviado por Resend a {destino}")
        return True
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        logger.error("[AUTH EMAIL] Error Resend HTTP %s: %s", exc.code, detalle)
        print(f"[AUTH EMAIL] Error Resend HTTP {exc.code}: {detalle}")
        return False
    except (URLError, Exception) as exc:
        logger.error("[AUTH EMAIL] Error Resend: %s", exc)
        print(f"[AUTH EMAIL] Error Resend: {exc}")
        return False


def _enviar_por_sendgrid(destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str) -> bool:
    api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if not api_key:
        return False

    payload = {
        "personalizations": [{"to": [{"email": destino}]}],
        "from": {"email": _smtp_from(), "name": "Bot Agencias"},
        "subject": asunto,
        "content": [
            {"type": "text/plain", "value": cuerpo_texto},
            {"type": "text/html", "value": cuerpo_html},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        _post_json("https://api.sendgrid.com/v3/mail/send", payload, headers)
        logger.info("[AUTH EMAIL] Enviado por SendGrid a %s", destino)
        print(f"[AUTH EMAIL] Enviado por SendGrid a {destino}")
        return True
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        # SendGrid responde 202 vacío a menudo; 202 no llega como HTTPError.
        logger.error("[AUTH EMAIL] Error SendGrid HTTP %s: %s", exc.code, detalle)
        print(f"[AUTH EMAIL] Error SendGrid HTTP {exc.code}: {detalle}")
        return False
    except (URLError, Exception) as exc:
        logger.error("[AUTH EMAIL] Error SendGrid: %s", exc)
        print(f"[AUTH EMAIL] Error SendGrid: {exc}")
        return False


def _imprimir_en_consola(destino: str, cuerpo_texto: str) -> bool:
    print(f"\n[AUTH EMAIL -> {destino}] (sin proveedor configurado; solo logs)")
    print(cuerpo_texto)
    print(
        "\n[AUTH EMAIL] Configurá RESEND_API_KEY, SENDGRID_API_KEY "
        "o SMTP_HOST/SMTP_USER/SMTP_PASSWORD en Render.\n"
    )
    return True


def correo_configurado() -> bool:
    return bool(
        os.getenv("RESEND_API_KEY", "").strip()
        or os.getenv("SENDGRID_API_KEY", "").strip()
        or os.getenv("SMTP_HOST", "").strip()
    )


def enviar_correo_verificacion(destino: str, token: str, nombre: str) -> bool:
    enlace = f"{_base_url()}/auth/verificar-email?token={token}"
    asunto = "Confirmá tu cuenta — Bot Agencias"
    cuerpo_texto = (
        f"Hola {nombre},\n\n"
        f"Gracias por registrarte. Confirmá tu correo haciendo clic en este enlace:\n\n"
        f"{enlace}\n\n"
        f"El enlace vence en 24 horas.\n\n"
        f"Si no creaste esta cuenta, ignorá este mensaje."
    )
    cuerpo_html = (
        f"<p>Hola <strong>{nombre}</strong>,</p>"
        f"<p>Gracias por registrarte en Bot Agencias. Confirmá tu correo:</p>"
        f'<p><a href="{enlace}">Verificar mi correo</a></p>'
        f"<p>O copiá este enlace: {enlace}</p>"
        f"<p>El enlace vence en 24 horas.</p>"
    )

    if _enviar_por_resend(destino, asunto, cuerpo_texto, cuerpo_html):
        return True
    if _enviar_por_sendgrid(destino, asunto, cuerpo_texto, cuerpo_html):
        return True
    if os.getenv("SMTP_HOST", "").strip():
        ok = _enviar_por_smtp(destino, asunto, cuerpo_texto, cuerpo_html)
        if ok:
            return True
        # Si SMTP falló, igual dejamos el enlace en logs para no bloquear el alta.
        print(cuerpo_texto)
        return False

    return _imprimir_en_consola(destino, cuerpo_texto)
