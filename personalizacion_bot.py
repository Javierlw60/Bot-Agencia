"""Identidad del bot por vendedor → sucursal → agencia (con fallbacks)."""

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
    for fuente in (vendedor, sucursal):
        valor = _valor(fuente, "color_primario")
        if valor:
            return valor
    valor = _valor(agencia, "color_primario")
    return valor or COLOR_PRIMARIO_DEFAULT


def obtener_nombre_bot(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    for fuente in (vendedor, sucursal):
        valor = _valor(fuente, "asesor_virtual_nombre")
        if valor:
            return valor
    valor = _valor(agencia, "nombre_bot")
    return valor or NOMBRE_BOT_DEFAULT


def obtener_nombre_agencia_bot(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    for fuente in (vendedor, sucursal):
        valor = _valor(fuente, "nombre_comercial")
        if valor:
            return valor
    valor = (
        _valor(agencia, "nombre_agencia")
        or _valor(agencia, "nombre")
    )
    return valor or NOMBRE_AGENCIA_DEFAULT


def obtener_logo_bot(
    agencia: Agencia,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str | None:
    valor = _valor(vendedor, "logo_url")
    if valor:
        return valor
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
