import datetime

from sqlalchemy import or_

from models.database import Agencia, Auto, SessionLocal, inicializar_base_de_datos
from inventory import guardar_lead_comercial, obtener_inventario_agencia


def inyectar_datos_semilla():
    db = SessionLocal()
    try:
        if db.query(Agencia).filter(
            or_(
                Agencia.nombre == "Agencia Central Demo",
                Agencia.whatsapp_phone_number_id == "109283746561234",
            )
        ).first():
            return

        agencia = Agencia(
            nombre="Agencia Central Demo",
            whatsapp_phone_number_id="109283746561234",
            prompt_personalizado="Priorizá clientes que consulten por financiación o permuta.",
            direccion="Av. Corrientes 1234, CABA",
            telefono_contacto="11 4567-8900",
            fecha_vencimiento=datetime.date.today() + datetime.timedelta(days=365),
            estado_pago="activo",
        )
        db.add(agencia)
        db.commit()
        db.refresh(agencia)

        autos = [
            Auto(
                agencia_id=agencia.id,
                marca="Fiat",
                modelo="Cronos",
                version="1.3 Precision CVT",
                ano=2023,
                tipo="Sedan",
                patente="AG184UC",
                chasis="8AP359AHKRU332832",
                motor="552820598612178",
                uso="Particular",
                precio_referencia_ars=27638000,
                estado="Disponible",
            ),
            Auto(
                agencia_id=agencia.id,
                marca="Volkswagen",
                modelo="Nivus",
                version="200 TSI Comfort",
                ano=2023,
                tipo="SUV",
                patente="AG333CL",
                chasis="9BWCH6CH6PP038009",
                motor="DHS539125",
                uso="Particular",
                precio_referencia_ars=34829000,
                estado="Disponible",
            ),
            Auto(
                agencia_id=agencia.id,
                marca="Volkswagen",
                modelo="Bora",
                version="1.8T Highline",
                ano=2010,
                tipo="Sedan",
                patente="JEV290",
                chasis="3VWSE29M8AM050569",
                motor="AUQ702679",
                uso="Particular",
                precio_referencia_ars=16515000,
                estado="Disponible",
            ),
        ]
        db.add_all(autos)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    inicializar_base_de_datos()
    inyectar_datos_semilla()
    print("[OK] Base de datos SQLite local inicializada.")

    inventario = obtener_inventario_agencia(1)
    print("\n[INVENTARIO ENCONTRADO EN BD]:\n", inventario)

    lead_id = guardar_lead_comercial(
        agencia_id=1,
        telefono="1163052331",
        auto_id=2,
        presupuesto=28000000.00,
    )
    print(f"\n[OK] Lead comercial multi-tenant insertado con éxito en BD. ID asignado: {lead_id}")
    print("\nPara probar el bot interactivo, ejecutá: python bot.py")
