"""Nombres personalizados del bot por agencia."""

from models.database import Agencia

NOMBRE_BOT_DEFAULT = "Asesor"
NOMBRE_AGENCIA_DEFAULT = "nuestra agencia"


def obtener_nombre_bot(agencia: Agencia) -> str:
    valor = (getattr(agencia, "nombre_bot", None) or "").strip()
    return valor or NOMBRE_BOT_DEFAULT


def obtener_nombre_agencia_bot(agencia: Agencia) -> str:
    valor = (
        (getattr(agencia, "nombre_agencia", None) or "")
        or (getattr(agencia, "nombre", None) or "")
    ).strip()
    return valor or NOMBRE_AGENCIA_DEFAULT


def mensaje_bienvenida_agencia(agencia: Agencia) -> str:
    nombre_bot = obtener_nombre_bot(agencia)
    nombre_agencia = obtener_nombre_agencia_bot(agencia)
    return (
        f"Hola, soy {nombre_bot}, tu asesor virtual de {nombre_agencia}. "
        "¿En qué puedo ayudarte hoy?"
    )
