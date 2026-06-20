import datetime

from citas import obtener_fecha_hoy_argentina
from models.database import Agencia, SessionLocal

ESTADO_ACTIVO = "activo"
ESTADO_BLOQUEADO = "bloqueado"
DIAS_RENOVACION_PAGO = 30
DIAS_AVISO_VENCIMIENTO = 3
PREFIJO_REFERENCIA_AGENCIA = "agencia:"
MENSAJE_SERVICIO_SUSPENDIDO = (
    "Tu servicio ha sido suspendido, por favor contactá al soporte"
)


def _hoy() -> datetime.date:
    return obtener_fecha_hoy_argentina()


def agencia_esta_vencida(agencia: Agencia, referencia: datetime.date | None = None) -> bool:
    if not agencia.fecha_vencimiento:
        return False
    return (referencia or _hoy()) > agencia.fecha_vencimiento


def agencia_vence_pronto(
    agencia: Agencia,
    dias: int = DIAS_AVISO_VENCIMIENTO,
    referencia: datetime.date | None = None,
) -> bool:
    """True si faltan entre 0 y N días para el vencimiento (inclusive)."""
    if not agencia.fecha_vencimiento:
        return False
    hoy = referencia or _hoy()
    if agencia.fecha_vencimiento < hoy:
        return False
    restantes = (agencia.fecha_vencimiento - hoy).days
    return restantes <= dias


def referencia_externa_agencia(agencia_id: int) -> str:
    return f"{PREFIJO_REFERENCIA_AGENCIA}{agencia_id}"


def extraer_agencia_id_de_referencia(valor: str | None) -> int | None:
    if not valor:
        return None
    texto = str(valor).strip()
    if texto.startswith(PREFIJO_REFERENCIA_AGENCIA):
        try:
            return int(texto.split(":", 1)[1])
        except (IndexError, ValueError):
            return None
    if texto.isdigit():
        return int(texto)
    return None


def renovar_suscripcion_agencia(
    agencia_id: int,
    dias: int = DIAS_RENOVACION_PAGO,
    db=None,
) -> Agencia | None:
    """Activa la agencia y extiende vencimiento desde hoy."""
    cerrar_db = db is None
    if db is None:
        db = SessionLocal()
    try:
        agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
        if not agencia:
            return None
        hoy = _hoy()
        agencia.estado_pago = ESTADO_ACTIVO
        agencia.fecha_vencimiento = hoy + datetime.timedelta(days=dias)
        db.commit()
        db.refresh(agencia)
        print(
            f"[SUSCRIPCIÓN] Agencia '{agencia.nombre}' (ID {agencia.id}) renovada "
            f"hasta {agencia.fecha_vencimiento}"
        )
        return agencia
    finally:
        if cerrar_db:
            db.close()


def bloquear_agencia(agencia: Agencia, db) -> bool:
    if agencia.estado_pago == ESTADO_BLOQUEADO:
        return False
    agencia.estado_pago = ESTADO_BLOQUEADO
    db.commit()
    return True


def procesar_vencimientos_vencidos() -> int:
    """Cron diario: bloquea agencias cuya fecha_vencimiento ya pasó."""
    hoy = _hoy()
    bloqueadas = 0
    db = SessionLocal()
    try:
        agencias = (
            db.query(Agencia)
            .filter(
                Agencia.fecha_vencimiento.isnot(None),
                Agencia.fecha_vencimiento < hoy,
                Agencia.estado_pago != ESTADO_BLOQUEADO,
            )
            .all()
        )
        for agencia in agencias:
            agencia.estado_pago = ESTADO_BLOQUEADO
            bloqueadas += 1
            print(
                f"[SUSCRIPCIÓN] Agencia '{agencia.nombre}' (ID {agencia.id}) "
                f"bloqueada — vencimiento {agencia.fecha_vencimiento}"
            )
        if bloqueadas:
            db.commit()
    finally:
        db.close()
    return bloqueadas


def evaluar_agencia_para_operar(agencia_id: int) -> tuple[bool, str | None]:
    """
    Verifica si la agencia puede usar el bot.
    Aplica bloqueo inmediato si la fecha de vencimiento ya pasó.
    """
    db = SessionLocal()
    try:
        agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
        if not agencia:
            return False, "Agencia no encontrada."

        if agencia_esta_vencida(agencia):
            bloquear_agencia(agencia, db)
            return False, MENSAJE_SERVICIO_SUSPENDIDO

        if (agencia.estado_pago or ESTADO_ACTIVO) != ESTADO_ACTIVO:
            return False, MENSAJE_SERVICIO_SUSPENDIDO

        return True, None
    finally:
        db.close()


def evaluar_agencia_por_whatsapp_id(phone_number_id: str) -> tuple[Agencia | None, str | None]:
    """Para webhooks de WhatsApp: resuelve agencia por phone_number_id."""
    db = SessionLocal()
    try:
        agencia = (
            db.query(Agencia)
            .filter(Agencia.whatsapp_phone_number_id == phone_number_id)
            .first()
        )
        if not agencia:
            return None, "Agencia no encontrada."
    finally:
        db.close()

    puede, mensaje = evaluar_agencia_para_operar(agencia.id)
    if not puede:
        return agencia, mensaje
    return agencia, None
