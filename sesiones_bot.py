"""Gestión de sesiones del bot para conversaciones por WhatsApp."""

from models.database import MensajeConversacion, ProspectoLead, SessionLocal

from bot import SesionCliente

_sesiones_activas: dict[tuple[int, str], SesionCliente] = {}
_MAX_HISTORIAL = 40


def _hidratar_sesion_desde_bd(sesion: SesionCliente) -> None:
    db = SessionLocal()
    try:
        lead = (
            db.query(ProspectoLead)
            .filter(
                ProspectoLead.agencia_id == sesion.agencia_id,
                ProspectoLead.telefono_cliente == sesion.telefono,
            )
            .order_by(ProspectoLead.id.desc())
            .first()
        )
        if lead:
            sesion.lead_id = lead.id
            sesion.nombre_cliente = lead.nombre_cliente
            sesion.apellido_cliente = lead.apellido_cliente
            sesion.auto_interes_id = lead.auto_interes_id
            if lead.presupuesto_estimado is not None:
                sesion.presupuesto = float(lead.presupuesto_estimado)
            sesion.usado_marca_modelo = lead.usado_marca_modelo
            sesion.usado_ano = lead.usado_ano
            sesion.usado_km = lead.usado_km
            sesion.usado_patente = lead.usado_patente
            sesion.usado_estado = lead.usado_estado
            sesion.usado_vtv_vigente = lead.usado_vtv_vigente
            sesion.usado_es_titular = lead.usado_es_titular
            if lead.usado_marca_modelo:
                sesion.quiere_permuta = True

        mensajes = (
            db.query(MensajeConversacion)
            .filter(
                MensajeConversacion.agencia_id == sesion.agencia_id,
                MensajeConversacion.telefono_cliente == sesion.telefono,
            )
            .order_by(MensajeConversacion.fecha_creacion.desc())
            .limit(_MAX_HISTORIAL)
            .all()
        )
        mensajes = list(reversed(mensajes))
        for msg in mensajes:
            prefijo = "Cliente" if msg.rol == "cliente" else "Bot"
            sesion.historial.append(f"{prefijo}: {msg.contenido}")
    finally:
        db.close()


def obtener_o_crear_sesion(agencia_id: int, telefono: str) -> SesionCliente:
    clave = (agencia_id, telefono)
    if clave in _sesiones_activas:
        return _sesiones_activas[clave]

    sesion = SesionCliente(agencia_id=agencia_id, telefono=telefono)
    _hidratar_sesion_desde_bd(sesion)
    _sesiones_activas[clave] = sesion
    return sesion


def limpiar_sesion(agencia_id: int, telefono: str) -> None:
    _sesiones_activas.pop((agencia_id, telefono), None)
