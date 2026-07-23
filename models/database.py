import datetime
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

load_dotenv()

Base = declarative_base()


class Agencia(Base):
    __tablename__ = "agencias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    nombre_agencia = Column(String(100), nullable=True)
    nombre_bot = Column(String(80), nullable=True)
    whatsapp_phone_number_id = Column(String(50), unique=True, nullable=False)
    prompt_personalizado = Column(Text, nullable=True)
    logo_url = Column(String(500), nullable=True)
    color_primario = Column(String(20), nullable=True, default="#3B82F6")
    direccion = Column(String(200), nullable=True)
    telefono_contacto = Column(String(30), nullable=True)
    fecha_vencimiento = Column(Date, nullable=True)
    estado_pago = Column(String(20), default="activo")
    mp_preapproval_id = Column(String(80), nullable=True)
    mp_renovacion_automatica = Column(Boolean, default=False)
    modo_respuesta = Column(String(20), default="texto")

    autos = relationship("Auto", back_populates="agencia")
    leads = relationship("ProspectoLead", back_populates="agencia")


class Auto(Base):
    __tablename__ = "autos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=True)
    marca = Column(String(50), nullable=False)
    modelo = Column(String(50), nullable=False)
    version = Column(String(100), nullable=False)
    ano = Column(Integer, nullable=False)
    tipo = Column(String(30), nullable=False)
    patente = Column(String(15), nullable=False)
    chasis = Column(String(20), nullable=True)
    motor = Column(String(30), nullable=True)
    uso = Column(String(50), nullable=True)
    precio_referencia_ars = Column(Numeric(14, 2), nullable=False)
    estado = Column(String(20), default="Disponible")
    foto_principal_url = Column(String(500), nullable=True)
    fotos_json = Column(Text, nullable=True)
    kilometros = Column(Integer, nullable=True)

    agencia = relationship("Agencia", back_populates="autos")
    leads = relationship("ProspectoLead", back_populates="auto")


class ProspectoLead(Base):
    __tablename__ = "prospectos_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=True)
    vendedor_id = Column(Integer, ForeignKey("vendedores.id"), nullable=True)
    telefono_cliente = Column(String(30), nullable=False)
    nombre_cliente = Column(String(80), nullable=True)
    apellido_cliente = Column(String(80), nullable=True)
    auto_interes_id = Column(Integer, ForeignKey("autos.id"), nullable=True)
    presupuesto_estimado = Column(Numeric(14, 2), nullable=True)
    usado_marca_modelo = Column(String(120), nullable=True)
    usado_ano = Column(Integer, nullable=True)
    usado_km = Column(Integer, nullable=True)
    usado_patente = Column(String(15), nullable=True)
    usado_estado = Column(Text, nullable=True)
    usado_vtv_vigente = Column(String(20), nullable=True)
    usado_es_titular = Column(String(20), nullable=True)
    estado_comercial = Column(String(30), default="Esperando_Llamada")
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)

    agencia = relationship("Agencia", back_populates="leads")
    auto = relationship("Auto", back_populates="leads")
    citas = relationship("Cita", back_populates="cliente")


class Cita(Base):
    __tablename__ = "citas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("prospectos_leads.id"), nullable=False)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=True)
    vendedor_id = Column(Integer, ForeignKey("vendedores.id"), nullable=True)
    fecha_cita = Column(Date, nullable=False)
    hora_cita = Column(String(10), nullable=False)
    auto_interes = Column(String(150), nullable=True)
    estado = Column(String(20), default="confirmada")
    recordatorio_enviado = Column(Boolean, default=False)
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)

    cliente = relationship("ProspectoLead", back_populates="citas")


class MensajeConversacion(Base):
    __tablename__ = "mensajes_conversacion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    lead_id = Column(Integer, ForeignKey("prospectos_leads.id"), nullable=True)
    telefono_cliente = Column(String(30), nullable=False)
    rol = Column(String(10), nullable=False)
    contenido = Column(Text, nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)


class HistorialConversacion(Base):
    """Auditoría de mensajes de audio entrantes (STT)."""

    __tablename__ = "historial_conversaciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    cliente_id = Column(Integer, ForeignKey("prospectos_leads.id"), nullable=True)
    telefono_cliente = Column(String(30), nullable=False)
    audio_path = Column(String(500), nullable=False)
    audio_url = Column(String(500), nullable=True)
    transcripcion = Column(Text, nullable=False)
    mp_media_id = Column(String(120), nullable=True)
    # wamid de Meta suele superar 80 caracteres.
    whatsapp_message_id = Column(String(200), nullable=True)
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nombre = Column(String(100), nullable=False)
    telefono_whatsapp = Column(String(30), nullable=False)
    email_verificado = Column(Boolean, default=False)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)

    agencia = relationship("Agencia", backref="usuarios")


class TokenVerificacion(Base):
    __tablename__ = "tokens_verificacion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo = Column(String(30), nullable=False)
    codigo_hash = Column(String(64), nullable=False)
    expira_en = Column(DateTime, nullable=False)
    usado = Column(Boolean, default=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)

    usuario = relationship("Usuario", backref="tokens")


class PagoMercadoPago(Base):
    """Registro idempotente de notificaciones de pago procesadas."""

    __tablename__ = "pagos_mercadopago"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    mp_resource_id = Column(String(80), unique=True, nullable=False)
    tipo = Column(String(40), nullable=False)
    monto = Column(Numeric(14, 2), nullable=True)
    fecha_procesado = Column(DateTime, default=datetime.datetime.utcnow)


class Sucursal(Base):
    __tablename__ = "sucursales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    numero = Column(Integer, nullable=False)
    nombre = Column(String(100), nullable=False)
    nombre_comercial = Column(String(100), nullable=True)
    asesor_virtual_nombre = Column(String(80), nullable=True)
    color_primario = Column(String(20), nullable=True)
    direccion = Column(String(200), nullable=True)
    telefono_whatsapp = Column(String(30), nullable=False, default="")
    es_principal = Column(Boolean, default=False)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)

    agencia = relationship("Agencia", backref="sucursales")
    vendedores = relationship(
        "Vendedor",
        back_populates="sucursal",
        cascade="all, delete-orphan",
        order_by="Vendedor.id",
    )


class Vendedor(Base):
    """Asesor de una sucursal con su propia línea de WhatsApp e identidad de bot.

    Jerarquía estricta: Agencia > Sucursal > Vendedor. Cada vendedor pertenece a
    una sola sucursal y tiene un teléfono único (no se mezclan entre sucursales).
    """

    __tablename__ = "vendedores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agencia_id = Column(Integer, ForeignKey("agencias.id"), nullable=False)
    sucursal_id = Column(Integer, ForeignKey("sucursales.id"), nullable=False)
    nombre = Column(String(100), nullable=False, default="Vendedor")
    asesor_virtual_nombre = Column(String(80), nullable=True)
    nombre_comercial = Column(String(100), nullable=True)
    color_primario = Column(String(20), nullable=True)
    logo_url = Column(String(500), nullable=True)
    telefono_whatsapp = Column(String(30), nullable=False, unique=True)
    modo_respuesta = Column(String(20), nullable=True)
    es_principal = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.datetime.utcnow)

    sucursal = relationship("Sucursal", back_populates="vendedores")
    agencia = relationship("Agencia")


def _normalizar_database_url(url: str) -> str:
    """Acepta URLs de Supabase/Render y las adapta al driver psycopg v3."""
    valor = (url or "").strip()
    if not valor:
        return valor
    if valor.startswith("postgres://"):
        valor = "postgresql://" + valor[len("postgres://") :]
    if valor.startswith("postgresql://") and "+psycopg" not in valor.split("://", 1)[0]:
        valor = "postgresql+psycopg://" + valor[len("postgresql://") :]
    return valor


def _sqlite_default_path() -> Path:
    """Si hay DATA_DIR (disco persistente), el .db vive ahí."""
    data = os.getenv("DATA_DIR", "").strip()
    if data:
        base = Path(data)
        base.mkdir(parents=True, exist_ok=True)
        return base / "bot_agencias_multitenant.db"
    return Path(__file__).resolve().parent.parent / "bot_agencias_multitenant.db"


def _resolver_database_url() -> str:
    cruda = os.getenv("DATABASE_URL", "").strip()
    if cruda:
        return _normalizar_database_url(cruda)
    return f"sqlite:///{_sqlite_default_path().as_posix()}"


def _crear_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Postgres / Supabase: pool_pre_ping evita conexiones muertas tras idle.
    return create_engine(url, pool_pre_ping=True)


DATABASE_URL = _resolver_database_url()
engine = _crear_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def es_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def es_postgres() -> bool:
    return engine.dialect.name in ("postgresql", "postgres")


def _tabla_tiene_columna(nombre_tabla: str, nombre_columna: str) -> bool:
    try:
        cols = {c["name"] for c in inspect(engine).get_columns(nombre_tabla)}
        return nombre_columna in cols
    except Exception:
        return False


def _agregar_columna_si_falta(nombre_tabla: str, nombre_columna: str, tipo_sql: str) -> None:
    if _tabla_tiene_columna(nombre_tabla, nombre_columna):
        return
    with engine.begin() as conn:
        if es_postgres():
            conn.execute(
                text(
                    f"ALTER TABLE {nombre_tabla} "
                    f"ADD COLUMN IF NOT EXISTS {nombre_columna} {tipo_sql}"
                )
            )
        else:
            try:
                conn.execute(
                    text(f"ALTER TABLE {nombre_tabla} ADD COLUMN {nombre_columna} {tipo_sql}")
                )
            except Exception:
                pass


def _ampliar_varchar_si_corta(
    nombre_tabla: str,
    nombre_columna: str,
    longitud: int,
) -> None:
    """Ensancha VARCHAR existentes (create_all no altera anchos en Postgres)."""
    if not _tabla_tiene_columna(nombre_tabla, nombre_columna):
        return
    tipo_sql = f"VARCHAR({longitud})"
    with engine.begin() as conn:
        try:
            if es_postgres():
                conn.execute(
                    text(
                        f"ALTER TABLE {nombre_tabla} "
                        f"ALTER COLUMN {nombre_columna} TYPE {tipo_sql}"
                    )
                )
            elif es_sqlite():
                # SQLite no aplica límites VARCHAR de forma estricta; no-op.
                pass
            else:
                conn.execute(
                    text(
                        f"ALTER TABLE {nombre_tabla} "
                        f"MODIFY COLUMN {nombre_columna} {tipo_sql}"
                    )
                )
        except Exception as exc:
            print(
                f"[DB] No se pudo ampliar {nombre_tabla}.{nombre_columna} "
                f"a {tipo_sql}: {exc}"
            )


def inicializar_base_de_datos():
    Base.metadata.create_all(bind=engine)
    _migrar_columnas_leads()
    _migrar_columnas_agencias()
    _migrar_columnas_autos()
    _migrar_columnas_citas()
    _migrar_tabla_vendedores()
    _migrar_columnas_vendedor_en_entidades()
    _migrar_tabla_mensajes()
    _migrar_tabla_pagos_mp()
    _migrar_tabla_historial_conversaciones()
    _migrar_tablas_auth()
    _agregar_columnas_identidad_sucursales()
    _migrar_tabla_sucursales()
    _migrar_columnas_sucursales()
    _migrar_backfill_identidad_sucursales()
    _migrar_sucursal_en_entidades()
    _sembrar_vendedor_principal()
    _migrar_estados_cita()
    _migrar_lineas_bot_a_agencia()
    _sembrar_usuario_demo()


def _migrar_lineas_bot_a_agencia() -> None:
    """Mueve Phone Number IDs de Meta pegados en vendedores/sucursales → agencia."""
    try:
        from inventory import migrar_linea_bot_desde_env, migrar_lineas_bot_desde_equipo

        n = migrar_lineas_bot_desde_equipo()
        if n:
            print(f"[DB] Líneas de bot reparadas desde equipo: {n}")
        if migrar_linea_bot_desde_env():
            print("[DB] Línea de bot sincronizada desde WHATSAPP_PHONE_NUMBER_ID (.env)")
    except Exception as exc:
        print(f"[DB] No se pudo migrar líneas de bot desde equipo: {exc}")


def _migrar_columnas_agencias():
    columnas = {
        "logo_url": "VARCHAR(500)",
        "color_primario": "VARCHAR(20)",
        "direccion": "VARCHAR(200)",
        "telefono_contacto": "VARCHAR(30)",
        "fecha_vencimiento": "DATE",
        "estado_pago": "VARCHAR(20)",
        "mp_preapproval_id": "VARCHAR(80)",
        "mp_renovacion_automatica": "BOOLEAN",
        "modo_respuesta": "VARCHAR(20)",
        "nombre_agencia": "VARCHAR(100)",
        "nombre_bot": "VARCHAR(80)",
    }
    for nombre_col, tipo in columnas.items():
        _agregar_columna_si_falta("agencias", nombre_col, tipo)
    with engine.begin() as conn:
        try:
            conn.execute(
                text("UPDATE agencias SET estado_pago = 'activo' WHERE estado_pago IS NULL")
            )
            conn.execute(
                text("UPDATE agencias SET modo_respuesta = 'texto' WHERE modo_respuesta IS NULL")
            )
        except Exception:
            pass


def _migrar_columnas_autos():
    columnas = {
        "foto_principal_url": "VARCHAR(500)",
        "fotos_json": "TEXT",
        "kilometros": "INTEGER",
    }
    for nombre_col, tipo in columnas.items():
        _agregar_columna_si_falta("autos", nombre_col, tipo)


def _migrar_columnas_citas():
    columnas = {
        "estado": "VARCHAR(20)",
        "recordatorio_enviado": "BOOLEAN",
    }
    for nombre_col, tipo in columnas.items():
        _agregar_columna_si_falta("citas", nombre_col, tipo)
    with engine.begin() as conn:
        try:
            conn.execute(
                text("UPDATE citas SET estado = 'confirmada' WHERE estado IS NULL")
            )
            # Postgres exige FALSE; SQLite acepta 0/FALSE.
            literal_false = "FALSE" if es_postgres() else "0"
            conn.execute(
                text(
                    f"UPDATE citas SET recordatorio_enviado = {literal_false} "
                    "WHERE recordatorio_enviado IS NULL"
                )
            )
        except Exception:
            pass


def _migrar_tabla_mensajes():
    Base.metadata.tables["mensajes_conversacion"].create(bind=engine, checkfirst=True)


def _migrar_tabla_pagos_mp():
    Base.metadata.tables["pagos_mercadopago"].create(bind=engine, checkfirst=True)


def _migrar_tabla_historial_conversaciones():
    Base.metadata.tables["historial_conversaciones"].create(bind=engine, checkfirst=True)
    # Producción tenía VARCHAR(80): audio_url (~93) y wamid (~82+) reventaban el INSERT.
    for columna, largo in (
        ("audio_path", 500),
        ("audio_url", 500),
        ("mp_media_id", 120),
        ("whatsapp_message_id", 200),
        ("telefono_cliente", 30),
    ):
        _ampliar_varchar_si_corta("historial_conversaciones", columna, largo)


def _migrar_tablas_auth():
    Base.metadata.tables["usuarios"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["tokens_verificacion"].create(bind=engine, checkfirst=True)


def _migrar_tabla_sucursales():
    Base.metadata.tables["sucursales"].create(bind=engine, checkfirst=True)
    _agregar_columna_si_falta("sucursales", "telefono_whatsapp", "VARCHAR(30)")
    db = SessionLocal()
    try:
        agencias = db.query(Agencia).all()
        for agencia in agencias:
            existentes = (
                db.query(Sucursal)
                .filter(Sucursal.agencia_id == agencia.id)
                .order_by(Sucursal.numero)
                .all()
            )
            if existentes:
                continue
            db.add(
                Sucursal(
                    agencia_id=agencia.id,
                    numero=1,
                    nombre="Sucursal 1",
                    direccion=agencia.direccion,
                    telefono_whatsapp=(
                        agencia.whatsapp_phone_number_id
                        or agencia.telefono_contacto
                        or ""
                    ),
                    es_principal=True,
                )
            )
        db.commit()
    finally:
        db.close()


def _migrar_columnas_sucursales():
    db = SessionLocal()
    try:
        for agencia in db.query(Agencia).all():
            sucursales = (
                db.query(Sucursal)
                .filter(Sucursal.agencia_id == agencia.id)
                .order_by(Sucursal.numero)
                .all()
            )
            if not sucursales:
                continue
            fallback = (
                agencia.whatsapp_phone_number_id
                or agencia.telefono_contacto
                or ""
            )
            principal = next((s for s in sucursales if s.es_principal), sucursales[0])
            for suc in sucursales:
                if suc.telefono_whatsapp:
                    continue
                if suc.id == principal.id:
                    suc.telefono_whatsapp = fallback or "5491100000000"
                else:
                    suc.telefono_whatsapp = principal.telefono_whatsapp or fallback or "5491100000000"
        db.commit()
    finally:
        db.close()


def _agregar_columnas_identidad_sucursales():
    columnas = {
        "nombre_comercial": "VARCHAR(100)",
        "asesor_virtual_nombre": "VARCHAR(80)",
        "color_primario": "VARCHAR(20)",
    }
    for nombre_col, tipo in columnas.items():
        _agregar_columna_si_falta("sucursales", nombre_col, tipo)


def _migrar_backfill_identidad_sucursales():
    db = SessionLocal()
    try:
        for agencia in db.query(Agencia).all():
            nombre_comercial = (agencia.nombre_agencia or agencia.nombre or "").strip() or None
            asesor = (agencia.nombre_bot or "").strip() or None
            color = (agencia.color_primario or "#3B82F6").strip() or "#3B82F6"
            sucursales = (
                db.query(Sucursal)
                .filter(Sucursal.agencia_id == agencia.id)
                .all()
            )
            for suc in sucursales:
                if not suc.nombre_comercial:
                    suc.nombre_comercial = nombre_comercial
                if not suc.asesor_virtual_nombre:
                    suc.asesor_virtual_nombre = asesor
                if not suc.color_primario:
                    suc.color_primario = color
        db.commit()
    finally:
        db.close()


def _migrar_sucursal_en_entidades():
    for tabla in ("autos", "prospectos_leads", "citas"):
        _agregar_columna_si_falta(tabla, "sucursal_id", "INTEGER")

    db = SessionLocal()
    try:
        agencias = db.query(Agencia).all()
        for agencia in agencias:
            principal = (
                db.query(Sucursal)
                .filter(Sucursal.agencia_id == agencia.id, Sucursal.es_principal.is_(True))
                .order_by(Sucursal.numero)
                .first()
            )
            if not principal:
                principal = (
                    db.query(Sucursal)
                    .filter(Sucursal.agencia_id == agencia.id)
                    .order_by(Sucursal.numero)
                    .first()
                )
            if not principal:
                continue

            db.query(Auto).filter(
                Auto.agencia_id == agencia.id,
                Auto.sucursal_id.is_(None),
            ).update({Auto.sucursal_id: principal.id}, synchronize_session=False)

            db.query(ProspectoLead).filter(
                ProspectoLead.agencia_id == agencia.id,
                ProspectoLead.sucursal_id.is_(None),
            ).update({ProspectoLead.sucursal_id: principal.id}, synchronize_session=False)

            citas = (
                db.query(Cita)
                .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
                .filter(
                    ProspectoLead.agencia_id == agencia.id,
                    Cita.sucursal_id.is_(None),
                )
                .all()
            )
            for cita in citas:
                cita.sucursal_id = cita.cliente.sucursal_id or principal.id

        db.commit()
    finally:
        db.close()


def _migrar_tabla_vendedores():
    Base.metadata.tables["vendedores"].create(bind=engine, checkfirst=True)


def _migrar_columnas_vendedor_en_entidades():
    for tabla in ("prospectos_leads", "citas"):
        _agregar_columna_si_falta(tabla, "vendedor_id", "INTEGER")


def _sembrar_vendedor_principal():
    """Crea un 'Vendedor Principal' por sucursal heredando su línea de WhatsApp e
    identidad de bot. No pisa vendedores ya existentes ni mezcla teléfonos."""
    db = SessionLocal()
    try:
        telefonos_usados = {
            (v.telefono_whatsapp or "").strip()
            for v in db.query(Vendedor).all()
            if (v.telefono_whatsapp or "").strip()
        }
        for suc in db.query(Sucursal).all():
            existentes = (
                db.query(Vendedor)
                .filter(Vendedor.sucursal_id == suc.id)
                .count()
            )
            if existentes:
                continue
            telefono = (suc.telefono_whatsapp or "").strip()
            # Si la línea de la sucursal ya está tomada por otro vendedor, no la
            # duplicamos (los teléfonos son únicos y no se mezclan).
            if telefono and telefono in telefonos_usados:
                telefono = ""
            agencia = db.query(Agencia).filter(Agencia.id == suc.agencia_id).first()
            logo = agencia.logo_url if agencia else None
            db.add(
                Vendedor(
                    agencia_id=suc.agencia_id,
                    sucursal_id=suc.id,
                    nombre="Vendedor Principal",
                    asesor_virtual_nombre=suc.asesor_virtual_nombre,
                    nombre_comercial=suc.nombre_comercial,
                    color_primario=suc.color_primario,
                    logo_url=logo,
                    telefono_whatsapp=telefono or f"sin-linea-suc-{suc.id}",
                    modo_respuesta=None,
                    es_principal=True,
                    activo=True,
                )
            )
            if telefono:
                telefonos_usados.add(telefono)
        db.commit()
    finally:
        db.close()


def _migrar_estados_cita():
    """Normaliza los estados de cita legacy a los canónicos del embudo."""
    from estado_cita import normalizar_estado_cita

    db = SessionLocal()
    try:
        for cita in db.query(Cita).all():
            canonico = normalizar_estado_cita(cita.estado)
            if cita.estado != canonico:
                cita.estado = canonico
        db.commit()
    finally:
        db.close()


def _sembrar_usuario_demo():
    """Crea un usuario demo vinculado a la agencia 1 para entornos de desarrollo."""
    from auth.passwords import hash_password

    db = SessionLocal()
    try:
        if db.query(Usuario).count() > 0:
            return
        agencia = db.query(Agencia).filter(Agencia.id == 1).first()
        if not agencia:
            return
        usuario = Usuario(
            email="admin@demo.local",
            password_hash=hash_password("Demo1234"),
            nombre="Administrador Demo",
            telefono_whatsapp="5491163052331",
            email_verificado=True,
            agencia_id=agencia.id,
            activo=True,
        )
        db.add(usuario)
        db.commit()
    finally:
        db.close()


def _migrar_columnas_leads():
    columnas = {
        "nombre_cliente": "VARCHAR(80)",
        "apellido_cliente": "VARCHAR(80)",
        "usado_marca_modelo": "VARCHAR(120)",
        "usado_ano": "INTEGER",
        "usado_km": "INTEGER",
        "usado_patente": "VARCHAR(15)",
        "usado_estado": "TEXT",
        "usado_vtv_vigente": "VARCHAR(20)",
        "usado_es_titular": "VARCHAR(20)",
    }
    for nombre_col, tipo in columnas.items():
        _agregar_columna_si_falta("prospectos_leads", nombre_col, tipo)
