"""Identidad del bot: agencia (principal) → sucursal (sede) → fallbacks."""

from models.database import Agencia, SessionLocal, Sucursal, Vendedor

NOMBRE_BOT_DEFAULT = "Asesor"
NOMBRE_AGENCIA_DEFAULT = "nuestra agencia"
COLOR_PRIMARIO_DEFAULT = "#3B82F6"


def obtener_sucursal(agencia_id: int, sucursal_id: int | None) -> Sucursal | None:
    if not sucursal_id:
        return None
    db = SessionLocal()
    try:
        return (
            db.query(Sucursal)
            .filter(Sucursal.id == sucursal_id, Sucursal.agencia_id == agencia_id)
            .first()
        )
    finally:
        db.close()


def obtener_vendedor(agencia_id: int, vendedor_id: int | None) -> Vendedor | None:
    if not vendedor_id:
        return None
    db = SessionLocal()
    try:
        return (
            db.query(Vendedor)
            .filter(Vendedor.id == vendedor_id, Vendedor.agencia_id == agencia_id)
            .first()
        )
    finally:
        db.close()


def _valor(obj, attr: str) -> str:
    return (getattr(obj, attr, None) or "").strip() if obj is not None else ""


def obtener_color_primario(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    """Color de marca: agencia → sucursal (vendedor ya no define la marca del bot)."""
    del vendedor  # compatibilidad de firma; no se usa
    for fuente in (agencia, sucursal):
        valor = _valor(fuente, "color_primario")
        if valor:
            return valor
    return COLOR_PRIMARIO_DEFAULT


def obtener_nombre_bot(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    """Nombre del asesor virtual: agencia → sucursal."""
    del vendedor
    valor = _valor(agencia, "nombre_bot")
    if valor:
        return valor
    valor = _valor(sucursal, "asesor_virtual_nombre")
    return valor or NOMBRE_BOT_DEFAULT


def obtener_nombre_agencia_bot(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    """Nombre comercial que dice el bot: agencia (oficial) → sucursal."""
    del vendedor
    valor = _valor(agencia, "nombre_agencia") or _valor(agencia, "nombre")
    if valor:
        return valor
    valor = _valor(sucursal, "nombre_comercial")
    return valor or NOMBRE_AGENCIA_DEFAULT


def obtener_direccion_bot(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
) -> str | None:
    """Dirección oficial para visitas: agencia → sucursal de contacto."""
    valor = _valor(agencia, "direccion") or _valor(sucursal, "direccion")
    return valor or None


def obtener_telefono_contacto_bot(agencia: Agencia) -> str | None:
    valor = _valor(agencia, "telefono_contacto")
    return valor or None


def obtener_logo_bot(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str | None:
    del sucursal, vendedor
    return (getattr(agencia, "logo_url", None) or None)


def mensaje_bienvenida_agencia(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    nombre_bot = obtener_nombre_bot(agencia, sucursal, vendedor)
    nombre_agencia = obtener_nombre_agencia_bot(agencia, sucursal, vendedor)
    return (
        f"Hola, soy {nombre_bot}, tu asesor virtual de {nombre_agencia}. "
        "¿En qué puedo ayudarte hoy?"
    )
