"""Envío de correos de verificación vía Resend.

Variables:
  RESEND_API_KEY  → obligatoria en producción
  SMTP_FROM       → opcional; default noreply@bot-agencias.com.ar
  DASHBOARD_BASE_URL / APP_URL / FRONTEND_URL → enlace de verificación

Estrategia:
  1) API HTTPS Resend
  2) Si falla (p.ej. Cloudflare 1010 desde Render) → SMTP Resend
     (smtp.resend.com, user=resend, password=RESEND_API_KEY)
  3) Sin API key → imprime el enlace en logs (solo desarrollo)
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


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=30) as resp:
        cuerpo = resp.read().decode("utf-8")
        return json.loads(cuerpo) if cuerpo else {}


def _enviar_por_resend_api(
    destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str, api_key: str
) -> bool:
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
        "Accept": "application/json",
        "User-Agent": "BotAgencias/1.0 (+https://bot-agencias.com.ar)",
    }
    try:
        data = _post_json("https://api.resend.com/emails", payload, headers)
        msg_id = data.get("id", "")
        print(
            f"[AUTH EMAIL] Enviado por Resend API a {destino} "
            f"from={_remitente_email()} id={msg_id}"
        )
        logger.info("[AUTH EMAIL] Resend API OK destino=%s id=%s", destino, msg_id)
        return True
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        print(f"[AUTH EMAIL] Error Resend API HTTP {exc.code}: {detalle[:500]}")
        logger.error("[AUTH EMAIL] Resend API HTTP %s: %s", exc.code, detalle[:500])
        return False
    except (URLError, Exception) as exc:
        print(f"[AUTH EMAIL] Error Resend API: {exc}")
        logger.error("[AUTH EMAIL] Resend API: %s", exc)
        return False


def _enviar_por_resend_smtp(
    destino: str, asunto: str, cuerpo_texto: str, cuerpo_html: str, api_key: str
) -> bool:
    """SMTP oficial de Resend: suele funcionar cuando la API HTTPS está bloqueada (CF 1010)."""
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
        f"[AUTH EMAIL] Intentando Resend → {destino} "
        f"from={_remitente_email()} key=***{_resend_api_key()[-4:]}"
    )

    if _enviar_por_resend_api(destino, asunto, cuerpo_texto, cuerpo_html, api_key):
        return True

    print("[AUTH EMAIL] API falló; reintentando por SMTP Resend (smtp.resend.com)...")
    if _enviar_por_resend_smtp(destino, asunto, cuerpo_texto, cuerpo_html, api_key):
        return True

    print(
        "[AUTH EMAIL] Falló API y SMTP de Resend. "
        "Revisá: 1) RESEND_API_KEY correcta  2) dominio bot-agencias.com.ar "
        f"verificado en Resend  3) remitente {REMITENTE_DEFAULT}"
    )
    print(cuerpo_texto)
    return False
