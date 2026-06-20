import datetime

from models.database import Cita, ProspectoLead, SessionLocal, inicializar_base_de_datos


def _obtener_citas_por_fecha(fecha: datetime.date) -> list[tuple[Cita, ProspectoLead]]:
    db = SessionLocal()
    try:
        return (
            db.query(Cita, ProspectoLead)
            .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
            .filter(Cita.fecha_cita == fecha)
            .order_by(Cita.hora_cita.asc())
            .all()
        )
    finally:
        db.close()


def _imprimir_bloque(titulo: str, fecha: datetime.date):
    citas = _obtener_citas_por_fecha(fecha)
    fecha_txt = fecha.strftime("%d/%m/%Y")

    print("=" * 60)
    print(f"{titulo} ({fecha_txt})")
    print("=" * 60)

    if not citas:
        print("Sin citas agendadas.")
        print()
        return

    for cita, lead in citas:
        nombre = lead.nombre_cliente or "Sin nombre"
        apellido = lead.apellido_cliente or "Sin apellido"
        telefono = lead.telefono_cliente or "Sin teléfono"
        auto = cita.auto_interes or "Sin auto especificado"

        print(f"- {cita.hora_cita} hs | {nombre} {apellido}")
        print(f"  Nombre:   {nombre}")
        print(f"  Apellido: {apellido}")
        print(f"  Teléfono: {telefono}")
        print(f"  Auto:     {auto}")
        print(f"  ID cita: {cita.id} | ID cliente (lead): {lead.id}")
        print()


def generar_reporte():
    inicializar_base_de_datos()
    hoy = datetime.date.today()
    manana = hoy + datetime.timedelta(days=1)

    print("\nREPORTE DE CITAS - AGENCIA")
    print(f"Generado: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}\n")

    _imprimir_bloque("CITAS PARA HOY", hoy)
    _imprimir_bloque("CITAS PARA MAÑANA", manana)

    print("Fin del reporte.")


if __name__ == "__main__":
    generar_reporte()
