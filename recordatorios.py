import datetime
import os

from sqlalchemy.orm import joinedload

from citas import obtener_ahora_argentina
from models.database import Agencia, Cita, ProspectoLead, SessionLocal
from whatsapp import enviar_mensaje_whatsapp

VENTANA_RECORDATORIO_HORAS = 2
ESTADO_CITA_CONFIRMADA = "confirmada"


def _parsear_hora_cita(hora_str: str) -> datetime.time | None:
    if not hora_str:
        return None
    partes = hora_str.strip().split(":")
    try:
        hora = int(partes[0])
        minuto = int(partes[1]) if len(partes) > 1 else 0
        return datetime.time(hora, minuto)
    except (ValueError, IndexError):
        return None


def _datetime_cita(cita: Cita) -> datetime.datetime | None:
    hora = _parsear_hora_cita(cita.hora_cita)
    if hora is None or not cita.fecha_cita:
        return None
    return datetime.datetime.combine(cita.fecha_cita, hora, tzinfo=obtener_ahora_argentina().tzinfo)


def _nombre_cliente(lead: ProspectoLead) -> str:
    partes = [lead.nombre_cliente, lead.apellido_cliente]
    nombre = " ".join(p for p in partes if p and str(p).strip())
    return nombre.strip() or "Cliente"


def _auto_descripcion(cita: Cita, lead: ProspectoLead) -> str:
    if cita.auto_interes and str(cita.auto_interes).strip():
        return str(cita.auto_interes).strip()
    if lead.auto:
        return f"{lead.auto.marca} {lead.auto.modelo}"
    return "el vehículo de tu interés"


def formatear_mensaje_recordatorio(
    nombre_cliente: str,
    hora_cita: str,
    auto: str,
    direccion_agencia: str,
    telefono_agencia: str,
    nombre_agencia: str,
) -> str:
    return (
        f"¡Hola {nombre_cliente}! Te esperamos hoy a las {hora_cita} para ver el {auto}. "
        f"Recordá que lo tenemos reservado para tu visita. "
        f"Estamos en {direccion_agencia}. "
        f"Cualquier cosa nos avisás al {telefono_agencia}. "
        f"¡Saludos, Agencia {nombre_agencia}!"
    )


def obtener_citas_pendientes_recordatorio(
    ventana_horas: int = VENTANA_RECORDATORIO_HORAS,
) -> list[tuple[Cita, ProspectoLead, Agencia]]:
    ahora = obtener_ahora_argentina()
    fin_ventana = ahora + datetime.timedelta(hours=ventana_horas)
    candidatas: list[tuple[Cita, ProspectoLead, Agencia]] = []

    db = SessionLocal()
    try:
        citas = (
            db.query(Cita)
            .options(
                joinedload(Cita.cliente).joinedload(ProspectoLead.auto),
                joinedload(Cita.cliente).joinedload(ProspectoLead.agencia),
            )
            .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
            .filter(
                Cita.estado == ESTADO_CITA_CONFIRMADA,
                Cita.recordatorio_enviado.is_(False),
            )
            .all()
        )

        for cita in citas:
            momento = _datetime_cita(cita)
            if momento is None:
                continue
            if ahora <= momento <= fin_ventana:
                lead = cita.cliente
                agencia = lead.agencia if lead else None
                if lead and agencia:
                    candidatas.append((cita, lead, agencia))
    finally:
        db.close()

    return candidatas


def procesar_recordatorios_pendientes() -> int:
    enviados = 0
    candidatas = obtener_citas_pendientes_recordatorio()

    for cita, lead, agencia in candidatas:
        nombre = _nombre_cliente(lead)
        auto = _auto_descripcion(cita, lead)
        direccion = agencia.direccion or "nuestra agencia"
        telefono_agencia = agencia.telefono_contacto or agencia.whatsapp_phone_number_id

        mensaje = formatear_mensaje_recordatorio(
            nombre_cliente=nombre,
            hora_cita=cita.hora_cita,
            auto=auto,
            direccion_agencia=direccion,
            telefono_agencia=telefono_agencia,
            nombre_agencia=agencia.nombre,
        )

        ok = enviar_mensaje_whatsapp(
            telefono_destino=lead.telefono_cliente,
            mensaje=mensaje,
            whatsapp_phone_number_id=agencia.whatsapp_phone_number_id,
        )

        if not ok:
            continue

        db = SessionLocal()
        try:
            cita_db = db.query(Cita).filter(Cita.id == cita.id).first()
            if cita_db:
                cita_db.recordatorio_enviado = True
                db.commit()
                enviados += 1
                print(
                    f"Recordatorio enviado a {nombre} para la cita de las {cita.hora_cita}"
                )
        finally:
            db.close()

    return enviados
