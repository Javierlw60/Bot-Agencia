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


def resumen_comercial_lead(lead) -> dict:
    if not lead:
        return {}
    items = []
    if lead.presupuesto_estimado:
        items.append(f"Presupuesto: ${float(lead.presupuesto_estimado):,.0f}")
    if lead.usado_marca_modelo:
        items.append(f"Permuta/usado: {lead.usado_marca_modelo}")
    if lead.auto and lead.auto_interes_id:
        items.append(f"Interés: {lead.auto.marca} {lead.auto.modelo}")
    elif lead.auto_interes_id:
        items.append(f"Auto ID interés: {lead.auto_interes_id}")
    return {
        "presupuesto": float(lead.presupuesto_estimado) if lead.presupuesto_estimado else None,
        "permuta": lead.usado_marca_modelo,
        "items": items,
    }
