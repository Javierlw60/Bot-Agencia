"""Envío de correos de verificación vía Resend.

Variables:
  RESEND_API_KEY  → obligatoria en producción
  SMTP_FROM       → opcional; default noreply@bot-agencias.com.ar
  DASHBOARD_BASE_URL / APP_URL / FRONTEND_URL → para armar el enlace

Fallback de desarrollo: si no hay RESEND_API_KEY, imprime el enlace en logs.
También acepta SMTP_* como respaldo opcional.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("auth.correo")

REMITENTE_DEFAULT = "noreply@bot-agencias.com.ar"
REMITENTE_NOMBRE = "Bot Agencias"


def _base_url() -> str:
    for nombre in ("DASHBOARD_BASE_URL", "APP_URL", "FRONTEND_URL"):
        valor = os.getenv(nombre, "").strip().rstrip("/")
        if valor:
            return valor
    return "http://127.0.0.1:8080"


def _remitente_email() -> str:
    """Siempre usa noreply@bot-agencias.com.ar salvo override explícito de SMTP_FROM."""
    crudo = os.getenv("SMTP_FROM", "").strip()
    if not crudo:
        return REMITENTE_DEFAULT
    _, email = parseaddr(crudo)
    return (email or crudo).strip() or REMITENTE_DEFAULT


def _remitente_header() -> str:
    return formataddr((REMITENTE_NOMBRE, _remitente_email()))


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
        "from": _remitente_header(),
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
        data = _post_json("https://api.resend.com/emails", payload, headers)
        msg_id = data.get("id", "")
        logger.info(
            "[AUTH EMAIL] Enviado por Resend a %s (from=%s id=%s)",
            destino,
            _remitente_email(),
            msg_id,
        )
        print(
            f"[AUTH EMAIL] Enviado por Resend a {destino} "
            f"from={_remitente_email()} id={msg_id}"
        )
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


def _enviar_por_smtp(destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str) -> bool:
    """Respaldo opcional si no hay Resend."""
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        return False

    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    usar_tls = os.getenv("SMTP_TLS", "true").lower() not in ("0", "false", "no")
    remitente = _remitente_email()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = _remitente_header()
    msg["To"] = destino
    msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

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
        print(f"[AUTH EMAIL] Enviado por SMTP a {destino} via {host}:{port}")
        return True
    except Exception as exc:
        print(f"[AUTH EMAIL] Error SMTP: {exc}")
        return False


def correo_configurado() -> bool:
    return bool(os.getenv("RESEND_API_KEY", "").strip() or os.getenv("SMTP_HOST", "").strip())


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

    if os.getenv("SMTP_HOST", "").strip():
        ok = _enviar_por_smtp(destino, asunto, cuerpo_texto, cuerpo_html)
        if ok:
            return True
        print(cuerpo_texto)
        return False

    print(f"\n[AUTH EMAIL -> {destino}] (falta RESEND_API_KEY; solo logs)")
    print(cuerpo_texto)
    print(
        "\n[AUTH EMAIL] En Render agregá RESEND_API_KEY. "
        f"Remitente: {REMITENTE_DEFAULT}\n"
    )
    return True
