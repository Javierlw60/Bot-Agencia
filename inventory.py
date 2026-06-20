import re

from dashboard.media import obtener_fotos_auto
from models.database import Auto, ProspectoLead, SessionLocal

MARCA_ALIASES = {
    "vw": "volkswagen",
    "volks": "volkswagen",
    "volkswagen": "volkswagen",
    "fiat": "fiat",
}


def _expandir_aliases_marca(texto: str) -> str:
    resultado = texto.lower()
    for alias, marca in MARCA_ALIASES.items():
        resultado = re.sub(rf"\b{re.escape(alias)}\b", marca, resultado)
    return resultado


def obtener_inventario_agencia(agencia_id: int) -> str:
    db = SessionLocal()
    try:
        autos = (
            db.query(Auto)
            .filter(Auto.agencia_id == agencia_id, Auto.estado == "Disponible")
            .all()
        )
        if not autos:
            return "Sin stock disponible."

        lines = []
        for auto in autos:
            fotos = obtener_fotos_auto(auto)
            foto_hint = f" | Fotos: {len(fotos)}" if fotos else ""
            lines.append(
                f"- ID: {auto.id} | {auto.marca} {auto.modelo} ({auto.version}) | "
                f"Año: {auto.ano} | Tipo: {auto.tipo} | Patente: {auto.patente} | "
                f"Precio ref.: ${auto.precio_referencia_ars:,.0f}{foto_hint}"
            )
        return "\n".join(lines)
    finally:
        db.close()


def obtener_autos_disponibles(agencia_id: int) -> list[Auto]:
    db = SessionLocal()
    try:
        return (
            db.query(Auto)
            .filter(Auto.agencia_id == agencia_id, Auto.estado == "Disponible")
            .all()
        )
    finally:
        db.close()


def buscar_autos_por_texto(agencia_id: int, texto: str) -> list[Auto]:
    texto_lower = _expandir_aliases_marca(texto.strip())
    coincidencias: list[Auto] = []

    for auto in obtener_autos_disponibles(agencia_id):
        candidatos = [
            auto.marca.lower(),
            auto.modelo.lower(),
            f"{auto.marca} {auto.modelo}".lower(),
            auto.patente.lower(),
        ]
        if any(c in texto_lower for c in candidatos):
            coincidencias.append(auto)

    return coincidencias


def obtener_auto_por_id(agencia_id: int, auto_id: int) -> Auto | None:
    db = SessionLocal()
    try:
        return (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
    finally:
        db.close()


_PATRON_PEDIDO_FOTOS = re.compile(
    r"\b(foto|fotos|imagen|imagenes|imágenes|fotito|fotitos|"
    r"mostrame|mostrá|mandame|mandá|enviame|enviá|ver\s+(el\s+)?auto|"
    r"quiero\s+ver|me\s+mostras|me\s+mostrás)\b",
    re.IGNORECASE,
)


def cliente_pide_fotos(texto: str) -> bool:
    return bool(_PATRON_PEDIDO_FOTOS.search(texto))


def formatear_fotos_para_whatsapp(auto: Auto, base_url: str = "") -> str:
    fotos = obtener_fotos_auto(auto)
    if not fotos:
        return ""
    titulo = f"📷 Fotos — {auto.marca} {auto.modelo} {auto.ano}"
    urls = []
    for foto in fotos:
        if foto.startswith("/") and base_url:
            urls.append(base_url.rstrip("/") + foto)
        else:
            urls.append(foto)
    return titulo + "\n" + "\n".join(urls)


def buscar_auto_por_texto(agencia_id: int, texto: str) -> Auto | None:
    coincidencias = buscar_autos_por_texto(agencia_id, texto)
    if len(coincidencias) == 1:
        return coincidencias[0]
    return None


def guardar_lead_comercial(
    agencia_id: int,
    telefono: str,
    auto_id: int | None = None,
    presupuesto: float | None = None,
    nombre_cliente: str | None = None,
    apellido_cliente: str | None = None,
    usado_marca_modelo: str | None = None,
    usado_ano: int | None = None,
    usado_km: int | None = None,
    usado_patente: str | None = None,
    usado_estado: str | None = None,
    usado_vtv_vigente: str | None = None,
    usado_es_titular: str | None = None,
    lead_id: int | None = None,
) -> int:
    db = SessionLocal()
    try:
        if lead_id:
            lead = db.query(ProspectoLead).filter(ProspectoLead.id == lead_id).first()
            if not lead:
                lead = ProspectoLead(agencia_id=agencia_id, telefono_cliente=telefono)
                db.add(lead)
        else:
            lead = ProspectoLead(agencia_id=agencia_id, telefono_cliente=telefono)
            db.add(lead)

        if nombre_cliente:
            lead.nombre_cliente = nombre_cliente
        if apellido_cliente:
            lead.apellido_cliente = apellido_cliente
        if auto_id:
            lead.auto_interes_id = auto_id
        if presupuesto:
            lead.presupuesto_estimado = presupuesto
        if usado_marca_modelo:
            lead.usado_marca_modelo = usado_marca_modelo
        if usado_ano:
            lead.usado_ano = usado_ano
        if usado_km:
            lead.usado_km = usado_km
        if usado_patente:
            lead.usado_patente = usado_patente
        if usado_estado:
            lead.usado_estado = usado_estado
        if usado_vtv_vigente:
            lead.usado_vtv_vigente = usado_vtv_vigente
        if usado_es_titular:
            lead.usado_es_titular = usado_es_titular

        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()
