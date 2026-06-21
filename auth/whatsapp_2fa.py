from whatsapp import enviar_mensaje_texto_whatsapp
from whatsapp_config import whatsapp_phone_number_id


def _phone_number_id_plataforma() -> str:
    return (
        whatsapp_phone_number_id()
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
