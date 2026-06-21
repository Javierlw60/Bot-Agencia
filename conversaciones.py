import datetime

from models.database import MensajeConversacion, SessionLocal


def guardar_mensaje(
    agencia_id: int,
    telefono: str,
    rol: str,
    contenido: str,
    lead_id: int | None = None,
) -> None:
    texto = (contenido or "").strip()
    if not texto:
        return
    db = SessionLocal()
    try:
        db.add(
            MensajeConversacion(
                agencia_id=agencia_id,
                lead_id=lead_id,
                telefono_cliente=telefono,
                rol=rol,
                contenido=texto,
            )
        )
        db.commit()
    finally:
        db.close()


def vincular_mensajes_a_lead(agencia_id: int, telefono: str, lead_id: int) -> None:
    db = SessionLocal()
    try:
        (
            db.query(MensajeConversacion)
            .filter(
                MensajeConversacion.agencia_id == agencia_id,
                MensajeConversacion.telefono_cliente == telefono,
                MensajeConversacion.lead_id.is_(None),
            )
            .update({MensajeConversacion.lead_id: lead_id}, synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()


def obtener_historial(
    agencia_id: int,
    telefono: str,
    lead_id: int | None = None,
) -> list[dict]:
    db = SessionLocal()
    try:
        query = db.query(MensajeConversacion).filter(
            MensajeConversacion.agencia_id == agencia_id,
            MensajeConversacion.telefono_cliente == telefono,
        )
        if lead_id:
            query = query.filter(
                (MensajeConversacion.lead_id == lead_id)
                | (MensajeConversacion.lead_id.is_(None))
            )
        mensajes = query.order_by(MensajeConversacion.fecha_creacion.asc()).all()
        return [
            {
                "rol": m.rol,
                "texto": m.contenido,
                "fecha": m.fecha_creacion.strftime("%d/%m/%Y %H:%M") if m.fecha_creacion else "",
            }
            for m in mensajes
        ]
    finally:
        db.close()


MIN_PRESUPUESTO_ARS = 500_000


def _formatear_precio_ars(valor) -> str:
    entero = int(round(float(valor)))
    return "$" + f"{entero:,}".replace(",", ".")


def _presupuesto_es_valido(valor) -> bool:
    if valor is None:
        return False
    try:
        return float(valor) >= MIN_PRESUPUESTO_ARS
    except (TypeError, ValueError):
        return False


def _describir_interes(lead, cita=None) -> str | None:
    if lead.auto:
        partes = [lead.auto.marca, lead.auto.modelo]
        if getattr(lead.auto, "version", None):
            partes.append(str(lead.auto.version))
        return " ".join(p for p in partes if p).strip() or None
    if cita and cita.auto_interes:
        return str(cita.auto_interes).strip() or None
    return None


def _describir_entrega_usado(lead) -> str | None:
    partes: list[str] = []
    if lead.usado_marca_modelo:
        partes.append(str(lead.usado_marca_modelo).strip())
    if lead.usado_ano:
        partes.append(str(lead.usado_ano))
    if lead.usado_km is not None:
        partes.append(f"{int(lead.usado_km):,} km".replace(",", "."))
    if lead.usado_patente:
        partes.append(f"Pat. {lead.usado_patente}")
    if partes:
        return " · ".join(partes)
    if _presupuesto_es_valido(lead.presupuesto_estimado):
        return _formatear_precio_ars(lead.presupuesto_estimado)
    return None


def _resolver_patente_unidad(lead, cita=None) -> str:
    if lead.auto and getattr(lead.auto, "patente", None):
        patente = str(lead.auto.patente).strip()
        if patente:
            return patente.upper()
    if lead.auto_interes_id or lead.auto or (cita and cita.auto_interes):
        return "Consultar unidad"
    return "Sin asignar"


def resumen_comercial_lead(lead, cita=None) -> dict:
    if not lead:
        return {"items": []}

    items: list[str] = []
    interes = _describir_interes(lead, cita)
    precio_lista = None
    precio_lista_label = "A cotizar"
    patente_label = _resolver_patente_unidad(lead, cita)

    if lead.auto and lead.auto.precio_referencia_ars:
        try:
            precio_lista = float(lead.auto.precio_referencia_ars)
        except (TypeError, ValueError):
            precio_lista = None
        if precio_lista and precio_lista > 0:
            precio_lista_label = _formatear_precio_ars(precio_lista)

    if interes:
        items.append(f"Interés: {interes}")
        items.append(f"Precio de lista: {precio_lista_label}")
        items.append(f"Patente: {patente_label}")
    elif cita and cita.auto_interes:
        items.append(f"Interés: {cita.auto_interes}")
        items.append("Precio de lista: Consultar")
        items.append(f"Patente: {patente_label}")

    entrega = _describir_entrega_usado(lead)
    if entrega:
        items.append(f"Entrega/Usado estimado: {entrega}")

    return {
        "interes": interes,
        "precio_lista": precio_lista,
        "precio_lista_label": precio_lista_label,
        "patente_unidad": patente_label,
        "entrega_usado": entrega,
        "items": items,
    }
