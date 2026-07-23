import re

from dashboard.media import obtener_fotos_auto
from models.database import Agencia, Auto, ProspectoLead, SessionLocal, Sucursal, Vendedor

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


def _normalizar_linea_whatsapp(valor: str | None) -> str:
    if not valor:
        return ""
    return re.sub(r"\D", "", str(valor))


def _mapa_nombres_sucursales(db, agencia_id: int) -> dict[int, str]:
    sucursales = (
        db.query(Sucursal)
        .filter(Sucursal.agencia_id == agencia_id)
        .order_by(Sucursal.numero)
        .all()
    )
    return {s.id: s.nombre for s in sucursales}


def obtener_nombre_sucursal(agencia_id: int, sucursal_id: int | None) -> str:
    if not sucursal_id:
        return "Sucursal principal"
    db = SessionLocal()
    try:
        suc = (
            db.query(Sucursal)
            .filter(Sucursal.id == sucursal_id, Sucursal.agencia_id == agencia_id)
            .first()
        )
        return suc.nombre if suc else "Sucursal"
    finally:
        db.close()


def _vendedor_principal_de_sucursal(db, sucursal: Sucursal | None) -> Vendedor | None:
    if not sucursal:
        return None
    principal = (
        db.query(Vendedor)
        .filter(
            Vendedor.sucursal_id == sucursal.id,
            Vendedor.es_principal.is_(True),
        )
        .order_by(Vendedor.id)
        .first()
    )
    if principal:
        return principal
    return (
        db.query(Vendedor)
        .filter(Vendedor.sucursal_id == sucursal.id)
        .order_by(Vendedor.id)
        .first()
    )


def resolver_destino_por_receptor_whatsapp(
    phone_number_id: str,
) -> tuple[Agencia | None, Sucursal | None, Vendedor | None]:
    """
    Identifica AGENCIA → SUCURSAL principal → VENDEDOR principal.

    La línea de WhatsApp Business (Phone Number ID de Meta) pertenece solo a la
    agencia. Los celulares de vendedores/sucursales no rutean mensajes entrantes.
    """
    db = SessionLocal()
    try:
        normalizado = _normalizar_linea_whatsapp(phone_number_id)

        agencia = None
        for candidata in db.query(Agencia).all():
            id_ag = (candidata.whatsapp_phone_number_id or "").strip()
            if not id_ag:
                continue
            if id_ag == phone_number_id or (
                normalizado and _normalizar_linea_whatsapp(id_ag) == normalizado
            ):
                agencia = candidata
                break

        if not agencia:
            return None, None, None

        suc = (
            db.query(Sucursal)
            .filter(Sucursal.agencia_id == agencia.id, Sucursal.es_principal.is_(True))
            .order_by(Sucursal.numero)
            .first()
        )
        if not suc:
            suc = (
                db.query(Sucursal)
                .filter(Sucursal.agencia_id == agencia.id)
                .order_by(Sucursal.numero)
                .first()
            )
        return agencia, suc, _vendedor_principal_de_sucursal(db, suc)
    finally:
        db.close()


def resolver_sucursal_por_receptor_whatsapp(
    phone_number_id: str,
) -> tuple[Agencia | None, Sucursal | None]:
    """Compatibilidad: devuelve solo (agencia, sucursal)."""
    agencia, sucursal, _ = resolver_destino_por_receptor_whatsapp(phone_number_id)
    return agencia, sucursal


def resolver_sucursal_id_cita(
    agencia_id: int,
    sucursal_origen_id: int | None,
    auto_interes_id: int | None,
) -> int | None:
    """Sede de la cita: por defecto origen; si el auto está en otra sede, esa sede."""
    if auto_interes_id:
        auto = obtener_auto_por_id(agencia_id, auto_interes_id)
        if auto and auto.sucursal_id:
            if sucursal_origen_id and auto.sucursal_id == sucursal_origen_id:
                return sucursal_origen_id
            return auto.sucursal_id
    return sucursal_origen_id


def obtener_inventario_agencia(agencia_id: int) -> str:
    db = SessionLocal()
    try:
        mapa = _mapa_nombres_sucursales(db, agencia_id)
        autos = (
            db.query(Auto)
            .filter(Auto.agencia_id == agencia_id, Auto.estado == "Disponible")
            .order_by(Auto.sucursal_id, Auto.marca, Auto.modelo)
            .all()
        )
        if not autos:
            return "Sin stock disponible."

        lines = []
        for auto in autos:
            fotos = obtener_fotos_auto(auto)
            foto_hint = f" | Fotos: {len(fotos)}" if fotos else ""
            sucursal = mapa.get(auto.sucursal_id, "Sin sucursal")
            km = f" | {auto.kilometros:,} km".replace(",", ".") if auto.kilometros else ""
            lines.append(
                f"- ID: {auto.id} | [{sucursal}] | {auto.marca} {auto.modelo} ({auto.version}) | "
                f"Año: {auto.ano}{km} | Tipo: {auto.tipo} | Patente: {auto.patente} | "
                f"Precio ref.: ${auto.precio_referencia_ars:,.0f}{foto_hint}"
            )
        return "\n".join(lines)
    finally:
        db.close()


def formatear_opciones_stock_cruzado(
    autos: list[Auto],
    agencia_id: int,
    sucursal_origen_id: int | None = None,
) -> str:
    if not autos:
        return ""

    db = SessionLocal()
    try:
        mapa = _mapa_nombres_sucursales(db, agencia_id)
    finally:
        db.close()

    origen = mapa.get(sucursal_origen_id, "la sucursal por la que te contactó")
    lineas = [
        "STOCK CRUZADO (todas las sedes de la agencia):",
        f"El cliente escribió por la línea de {origen}. Proponé agendar la visita allí por defecto.",
        "Si elige un auto que está en otra sede, ofrecé también coordinar turno en esa sede.",
        "Opciones encontradas:",
    ]
    for indice, auto in enumerate(autos, start=1):
        sucursal = mapa.get(auto.sucursal_id, "Sin sucursal")
        km = f" · {auto.kilometros:,} km".replace(",", ".") if auto.kilometros else ""
        lineas.append(
            f"{indice}. [{sucursal}] {auto.marca} {auto.modelo} {auto.ano} — "
            f"{auto.version}{km} — ${auto.precio_referencia_ars:,.0f} — ID {auto.id}"
        )
    return "\n".join(lineas)


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


_MAX_FOTOS_WHATSAPP = 8
_PATRON_PLACEHOLDER_IMAGEN = re.compile(
    r"\[?\s*IMAGEN\s*\d*[^\]\n]*\]?",
    re.IGNORECASE,
)
_PATRON_LINEA_URL_FOTO = re.compile(
    r"^(?:📷\s*)?(?:Fotos\s*[—\-].*)?https?://\S+$|^/static/\S+$",
    re.IGNORECASE,
)


def listar_origenes_fotos_auto(auto: Auto, base_url: str = "") -> list[str]:
    """Orígenes para envío WA: paths /static/... (subida local) o URLs http(s)."""
    del base_url  # se usa en el fallback de envío, no acá
    fotos = obtener_fotos_auto(auto)
    return [f for f in fotos[:_MAX_FOTOS_WHATSAPP] if f]


def formatear_fotos_para_whatsapp(auto: Auto, base_url: str = "") -> str:
    """Texto de respaldo con URLs (solo si no se pueden enviar como media)."""
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


def limpiar_placeholders_imagen_en_texto(texto: str) -> str:
    """Saca inventos tipo [IMAGEN 1 del …] y líneas que solo son URLs de foto."""
    if not texto:
        return texto
    limpio = _PATRON_PLACEHOLDER_IMAGEN.sub("", texto)
    lineas: list[str] = []
    for linea in limpio.splitlines():
        t = linea.strip()
        if not t:
            lineas.append("")
            continue
        if t.startswith("📷 Fotos"):
            continue
        if t.startswith(("http://", "https://", "/static/")):
            continue
        if _PATRON_LINEA_URL_FOTO.match(t):
            continue
        lineas.append(linea)
    # Colapsar saltos múltiples
    resultado = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()
    return resultado


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
    sucursal_id: int | None = None,
    vendedor_id: int | None = None,
) -> int:
    db = SessionLocal()
    try:
        if sucursal_id is None:
            principal = (
                db.query(Sucursal)
                .filter(Sucursal.agencia_id == agencia_id, Sucursal.es_principal.is_(True))
                .first()
            )
            if not principal:
                principal = (
                    db.query(Sucursal)
                    .filter(Sucursal.agencia_id == agencia_id)
                    .order_by(Sucursal.numero)
                    .first()
                )
            sucursal_id = principal.id if principal else None
        else:
            suc = (
                db.query(Sucursal)
                .filter(Sucursal.id == sucursal_id, Sucursal.agencia_id == agencia_id)
                .first()
            )
            if not suc:
                sucursal_id = None

        if lead_id:
            lead = db.query(ProspectoLead).filter(ProspectoLead.id == lead_id).first()
            if not lead:
                lead = ProspectoLead(
                    agencia_id=agencia_id,
                    telefono_cliente=telefono,
                    sucursal_id=sucursal_id,
                )
                db.add(lead)
        else:
            lead = ProspectoLead(
                agencia_id=agencia_id,
                telefono_cliente=telefono,
                sucursal_id=sucursal_id,
            )
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
        if vendedor_id and getattr(lead, "vendedor_id", None) is None:
            lead.vendedor_id = vendedor_id

        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()
