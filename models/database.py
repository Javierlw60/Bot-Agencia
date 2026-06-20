import datetime

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
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

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
    mp_media_id = Column(String(80), nullable=True)
    whatsapp_message_id = Column(String(80), nullable=True)
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


DATABASE_URL = "sqlite:///./bot_agencias_multitenant.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def inicializar_base_de_datos():
    Base.metadata.create_all(bind=engine)
    _migrar_columnas_leads()
    _migrar_columnas_agencias()
    _migrar_columnas_autos()
    _migrar_columnas_citas()
    _migrar_tabla_mensajes()
    _migrar_tabla_pagos_mp()
    _migrar_tabla_historial_conversaciones()
    _migrar_tablas_auth()
    _sembrar_usuario_demo()


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
    with engine.begin() as conn:
        for nombre_col, tipo in columnas.items():
            try:
                conn.execute(text(f"ALTER TABLE agencias ADD COLUMN {nombre_col} {tipo}"))
            except Exception:
                pass
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
    with engine.begin() as conn:
        for nombre_col, tipo in columnas.items():
            try:
                conn.execute(text(f"ALTER TABLE autos ADD COLUMN {nombre_col} {tipo}"))
            except Exception:
                pass


def _migrar_columnas_citas():
    columnas = {
        "estado": "VARCHAR(20)",
        "recordatorio_enviado": "BOOLEAN",
    }
    with engine.begin() as conn:
        for nombre_col, tipo in columnas.items():
            try:
                conn.execute(text(f"ALTER TABLE citas ADD COLUMN {nombre_col} {tipo}"))
            except Exception:
                pass
        try:
            conn.execute(
                text("UPDATE citas SET estado = 'confirmada' WHERE estado IS NULL")
            )
            conn.execute(
                text("UPDATE citas SET recordatorio_enviado = 0 WHERE recordatorio_enviado IS NULL")
            )
        except Exception:
            pass


def _migrar_tabla_mensajes():
    Base.metadata.tables["mensajes_conversacion"].create(bind=engine, checkfirst=True)


def _migrar_tabla_pagos_mp():
    Base.metadata.tables["pagos_mercadopago"].create(bind=engine, checkfirst=True)


def _migrar_tabla_historial_conversaciones():
    Base.metadata.tables["historial_conversaciones"].create(bind=engine, checkfirst=True)


def _migrar_tablas_auth():
    Base.metadata.tables["usuarios"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["tokens_verificacion"].create(bind=engine, checkfirst=True)


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
    with engine.begin() as conn:
        for nombre_col, tipo in columnas.items():
            try:
                conn.execute(
                    text(f"ALTER TABLE prospectos_leads ADD COLUMN {nombre_col} {tipo}")
                )
            except Exception:
                pass
