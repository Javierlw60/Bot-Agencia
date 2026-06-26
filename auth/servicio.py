import datetime
import hashlib
import os
import re
import secrets

from sqlalchemy.orm import Session

from auth.correo import enviar_correo_verificacion
from auth.passwords import hash_password, verificar_password
from auth.whatsapp_2fa import enviar_codigo_2fa
from models.database import Agencia, TokenVerificacion, Usuario

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DURACION_EMAIL_HORAS = 24
_DURACION_2FA_MIN = 10
_EMAIL_ADMIN_DEMO = "admin@demo.local"
CODIGO_2FA_DESARROLLO = "123456"


def _normalizar_email(email: str) -> str:
    return email.strip().lower()


def _normalizar_telefono(telefono: str) -> str:
    return re.sub(r"\D", "", telefono.strip())


def _generar_codigo_6() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_token(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def _flag_env_activa(nombre: str) -> bool:
    return os.getenv(nombre, "").strip().lower() in {"1", "true", "yes", "on"}


def usar_2fa_desarrollo(email: str, *, es_entorno_local: bool = False) -> bool:
    """En local/demo no envía WhatsApp real y puede omitir el paso 2FA."""
    if es_entorno_local:
        return True
    email_norm = _normalizar_email(email)
    if email_norm == _EMAIL_ADMIN_DEMO:
        return True
    if _flag_env_activa("AUTH_2FA_DEV") or _flag_env_activa("AUTH_DEV_BYPASS"):
        return True
    base_url = (
        os.getenv("DASHBOARD_BASE_URL")
        or os.getenv("APP_URL")
        or ""
    ).strip().lower()
    return any(host in base_url for host in ("127.0.0.1", "localhost", "0.0.0.0"))


def _crear_token(db: Session, usuario_id: int, tipo: str, valor_plano: str, horas: float) -> str:
    token = TokenVerificacion(
        usuario_id=usuario_id,
        tipo=tipo,
        codigo_hash=_hash_token(valor_plano),
        expira_en=datetime.datetime.utcnow() + datetime.timedelta(hours=horas),
        usado=False,
    )
    db.add(token)
    return valor_plano


def validar_formato_registro(
    email: str, password: str, telefono: str, nombre: str, nombre_agencia: str
) -> str | None:
    if not nombre.strip():
        return "Ingresá tu nombre."
    if not nombre_agencia.strip():
        return "Ingresá el nombre de tu agencia."
    if not _EMAIL_RE.match(_normalizar_email(email)):
        return "Ingresá un correo electrónico válido."
    if len(password) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if len(_normalizar_telefono(telefono)) < 8:
        return "Ingresá un número de WhatsApp válido (con código de país)."
    return None


def registrar_usuario(
    db: Session,
    email: str,
    password: str,
    telefono: str,
    nombre: str,
    nombre_agencia: str,
) -> tuple[Usuario | None, str | None]:
    error = validar_formato_registro(email, password, telefono, nombre, nombre_agencia)
    if error:
        return None, error

    email_norm = _normalizar_email(email)
    if db.query(Usuario).filter(Usuario.email == email_norm).first():
        return None, "Ya existe una cuenta con ese correo."

    agencia = Agencia(
        nombre=nombre_agencia.strip(),
        whatsapp_phone_number_id=f"reg_{secrets.token_hex(8)}",
        telefono_contacto=telefono.strip(),
        estado_pago="activo",
    )
    db.add(agencia)
    db.flush()

    usuario = Usuario(
        email=email_norm,
        password_hash=hash_password(password),
        nombre=nombre.strip(),
        telefono_whatsapp=_normalizar_telefono(telefono),
        email_verificado=False,
        agencia_id=agencia.id,
        activo=True,
    )
    db.add(usuario)
    db.flush()

    token_email = secrets.token_urlsafe(32)
    _crear_token(db, usuario.id, "email_verificacion", token_email, _DURACION_EMAIL_HORAS)
    db.commit()
    db.refresh(usuario)

    enviar_correo_verificacion(usuario.email, token_email, usuario.nombre)
    return usuario, None


def verificar_email(db: Session, token: str) -> tuple[bool, str]:
    if not token.strip():
        return False, "El enlace de verificación no es válido."
    token_hash = _hash_token(token.strip())
    registro = (
        db.query(TokenVerificacion)
        .filter(
            TokenVerificacion.tipo == "email_verificacion",
            TokenVerificacion.codigo_hash == token_hash,
            TokenVerificacion.usado.is_(False),
            TokenVerificacion.expira_en > datetime.datetime.utcnow(),
        )
        .first()
    )
    if not registro:
        return False, "El enlace expiró o ya fue utilizado."

    usuario = db.query(Usuario).filter(Usuario.id == registro.usuario_id).first()
    if not usuario:
        return False, "No se encontró la cuenta."

    usuario.email_verificado = True
    registro.usado = True
    db.commit()
    return True, "Correo verificado. Ya podés iniciar sesión."


def iniciar_login(
    db: Session,
    email: str,
    password: str,
    *,
    es_entorno_local: bool = False,
) -> tuple[Usuario | None, str | None, bool]:
    """Devuelve (usuario, error, ingreso_directo). ingreso_directo=True omite el paso 2FA."""
    email_norm = _normalizar_email(email)
    usuario = db.query(Usuario).filter(Usuario.email == email_norm, Usuario.activo.is_(True)).first()
    if not usuario or not verificar_password(password, usuario.password_hash):
        return None, "Correo o contraseña incorrectos.", False

    if not usuario.email_verificado:
        return None, "Confirmá tu correo antes de ingresar. Revisá tu bandeja de entrada.", False

    if usar_2fa_desarrollo(email_norm, es_entorno_local=es_entorno_local):
        print(
            f"[AUTH DEV] Ingreso directo sin WhatsApp/2FA para {email_norm} "
            f"(local={es_entorno_local})."
        )
        return usuario, None, True

    codigo = _generar_codigo_6()
    _crear_token(db, usuario.id, "login_2fa", codigo, _DURACION_2FA_MIN / 60)
    db.commit()

    enviado = enviar_codigo_2fa(usuario.telefono_whatsapp, codigo, usuario.nombre)
    if not enviado:
        if usar_2fa_desarrollo(email_norm, es_entorno_local=True):
            print(
                f"[AUTH DEV] WhatsApp falló para {email_norm}; "
                f"ingreso directo habilitado en modo demo/local."
            )
            return usuario, None, True
        return None, "No pudimos enviar el código por WhatsApp. Revisá la configuración o intentá más tarde.", False

    return usuario, None, False


def confirmar_2fa(db: Session, usuario_id: int, codigo: str) -> tuple[Usuario | None, str | None]:
    codigo_limpio = re.sub(r"\D", "", codigo.strip())
    if len(codigo_limpio) != 6:
        return None, "Ingresá el código de 6 dígitos que recibiste por WhatsApp."

    token_hash = _hash_token(codigo_limpio)
    registro = (
        db.query(TokenVerificacion)
        .filter(
            TokenVerificacion.usuario_id == usuario_id,
            TokenVerificacion.tipo == "login_2fa",
            TokenVerificacion.codigo_hash == token_hash,
            TokenVerificacion.usado.is_(False),
            TokenVerificacion.expira_en > datetime.datetime.utcnow(),
        )
        .order_by(TokenVerificacion.id.desc())
        .first()
    )
    if not registro:
        return None, "Código incorrecto o vencido. Volvé a iniciar sesión."

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id, Usuario.activo.is_(True)).first()
    if not usuario:
        return None, "Cuenta no encontrada."

    registro.usado = True
    db.commit()
    return usuario, None


def obtener_usuario_por_id(db: Session, usuario_id: int) -> Usuario | None:
    return db.query(Usuario).filter(Usuario.id == usuario_id, Usuario.activo.is_(True)).first()
