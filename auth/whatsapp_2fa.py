import os

from dotenv import load_dotenv

from whatsapp import enviar_mensaje_texto_whatsapp

load_dotenv()


def _phone_number_id_plataforma() -> str:
    return (
        os.getenv("AUTH_WHATSAPP_PHONE_NUMBER_ID", "").strip()
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        or "109283746561234"
    )


def enviar_codigo_2fa(telefono: str, codigo: str, nombre: str) -> bool:
    mensaje = (
        f"*{nombre}*, tu código de acceso al panel de Bot Agencias es:\n\n"
        f"*{codigo}*\n\n"
        f"Vence en 10 minutos. No lo compartas con nadie.\n"
        f"Si no solicitaste este código, ignorá este mensaje."
    )
    return enviar_mensaje_texto_whatsapp(
        telefono_destino=telefono,
        mensaje=mensaje,
        whatsapp_phone_number_id=_phone_number_id_plataforma(),
        imprimir_en_consola=True,
    )
