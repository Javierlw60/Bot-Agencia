import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()


def _base_url() -> str:
    return os.getenv("DASHBOARD_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


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

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "noreply@botagencias.local")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not smtp_host:
        print(f"\n[AUTH EMAIL -> {destino}]")
        print(cuerpo_texto)
        print()
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = smtp_from
    msg["To"] = destino
    msg.attach(MIMEText(cuerpo_texto, "plain", "utf-8"))
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if os.getenv("SMTP_TLS", "true").lower() != "false":
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [destino], msg.as_string())
        return True
    except Exception as exc:
        print(f"[AUTH EMAIL] Error SMTP: {exc}")
        print(cuerpo_texto)
        return False
