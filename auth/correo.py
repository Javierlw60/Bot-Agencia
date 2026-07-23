"""Envío de correos de verificación vía Resend (SDK oficial).

Variables:
  RESEND_API_KEY  → obligatoria en producción
  SMTP_FROM       → opcional; default noreply@bot-agencias.com.ar
  DASHBOARD_BASE_URL / APP_URL / FRONTEND_URL → enlace de verificación

Estrategia:
  1) SDK oficial `resend` (pip install resend) — headers correctos p/ Cloudflare
  2) Si falla → SMTP Resend (smtp.resend.com)
  3) Sin API key → imprime el enlace en logs (solo desarrollo)
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("auth.correo")

REMITENTE_DEFAULT = "noreply@bot-agencias.com.ar"
REMITENTE_NOMBRE = "Bot Agencias"
RESEND_SMTP_HOST = "smtp.resend.com"
RESEND_SMTP_PORT = 587


def _base_url() -> str:
    for nombre in ("DASHBOARD_BASE_URL", "APP_URL", "FRONTEND_URL"):
        valor = os.getenv(nombre, "").strip().rstrip("/")
        if valor:
            return valor
    return "http://127.0.0.1:8080"


def _resend_api_key() -> str:
    """Limpia comillas/espacios por si se pegó mal en Render."""
    cruda = os.getenv("RESEND_API_KEY", "").strip()
    if len(cruda) >= 2 and cruda[0] == cruda[-1] and cruda[0] in ("'", '"'):
        cruda = cruda[1:-1].strip()
    return cruda


def _remitente_email() -> str:
    crudo = os.getenv("SMTP_FROM", "").strip()
    if not crudo:
        return REMITENTE_DEFAULT
    _, email = parseaddr(crudo)
    return (email or crudo).strip() or REMITENTE_DEFAULT


def _remitente_header() -> str:
    return formataddr((REMITENTE_NOMBRE, _remitente_email()))


def _armar_mime(destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = _remitente_header()
    msg["To"] = destino
    msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))
    return msg


def _enviar_por_resend_sdk(
    destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str, api_key: str
) -> bool:
    """Usa el SDK oficial (incluye User-Agent y manejo de errores de Cloudflare)."""
    try:
        import resend
    except ImportError:
        print("[AUTH EMAIL] Falta el paquete 'resend'. Agregalo a requirements.txt.")
        logger.error("[AUTH EMAIL] Paquete resend no instalado")
        return False

    resend.api_key = api_key
    params = {
        "from": _remitente_header(),
        "to": [destino],
        "subject": asunto,
        "html": cuerpo_html,
        "text": cuerpo_texto,
    }
    try:
        resultado = resend.Emails.send(params)
        msg_id = ""
        if isinstance(resultado, dict):
            msg_id = str(resultado.get("id") or "")
        else:
            msg_id = str(getattr(resultado, "id", "") or "")
        print(
            f"[AUTH EMAIL] Enviado por Resend SDK a {destino} "
            f"from={_remitente_email()} id={msg_id}"
        )
        logger.info("[AUTH EMAIL] Resend SDK OK destino=%s id=%s", destino, msg_id)
        return True
    except Exception as exc:
        print(f"[AUTH EMAIL] Error Resend SDK: {exc}")
        logger.error("[AUTH EMAIL] Resend SDK: %s", exc)
        return False


def _enviar_por_resend_smtp(
    destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str, api_key: str
) -> bool:
    """SMTP oficial de Resend como respaldo."""
    msg = _armar_mime(destino, asunto, cuerpo_texto, cuerpo_html)
    remitente = _remitente_email()
    try:
        with smtplib.SMTP(RESEND_SMTP_HOST, RESEND_SMTP_PORT, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login("resend", api_key)
            server.sendmail(remitente, [destino], msg.as_string())
        print(
            f"[AUTH EMAIL] Enviado por Resend SMTP a {destino} "
            f"from={remitente} via {RESEND_SMTP_HOST}:{RESEND_SMTP_PORT}"
        )
        logger.info("[AUTH EMAIL] Resend SMTP OK destino=%s", destino)
        return True
    except Exception as exc:
        print(f"[AUTH EMAIL] Error Resend SMTP: {exc}")
        logger.error("[AUTH EMAIL] Resend SMTP: %s", exc)
        return False


def correo_configurado() -> bool:
    return bool(_resend_api_key())


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

    api_key = _resend_api_key()
    if not api_key:
        print(f"\n[AUTH EMAIL -> {destino}] (falta RESEND_API_KEY; solo logs)")
        print(cuerpo_texto)
        print(
            "\n[AUTH EMAIL] En Render → Environment agregá RESEND_API_KEY "
            f"y verificá el dominio en Resend. Remitente: {REMITENTE_DEFAULT}\n"
        )
        return True

    print(
        f"[AUTH EMAIL] Intentando Resend SDK → {destino} "
        f"from={_remitente_email()} key=***{api_key[-4:]}"
    )

    if _enviar_por_resend_sdk(destino, asunto, cuerpo_texto, cuerpo_html, api_key):
        return True

    print("[AUTH EMAIL] SDK falló; reintentando por SMTP Resend (smtp.resend.com)...")
    if _enviar_por_resend_smtp(destino, asunto, cuerpo_texto, cuerpo_html, api_key):
        return True

    print(
        "[AUTH EMAIL] Falló SDK y SMTP de Resend. "
        "Revisá: 1) RESEND_API_KEY correcta  2) dominio bot-agencias.com.ar "
        f"verificado en Resend  3) remitente {REMITENTE_DEFAULT}"
    )
    print(cuerpo_texto)
    return False
