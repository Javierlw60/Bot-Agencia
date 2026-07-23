import datetime
import shutil
from pathlib import Path

from models.database import HistorialConversacion, ProspectoLead, SessionLocal
from paths_datos import static_dir

DIR_AUDIT_AUDIO = static_dir() / "audit" / "audio"
DIR_TEMP_AUDIO = static_dir() / "temp" / "whatsapp"
DIR_AUDIT_AUDIO.mkdir(parents=True, exist_ok=True)
DIR_TEMP_AUDIO.mkdir(parents=True, exist_ok=True)


def _resolver_cliente_id(agencia_id: int, telefono: str) -> int | None:
    db = SessionLocal()
    try:
        lead = (
            db.query(ProspectoLead)
            .filter(
                ProspectoLead.agencia_id == agencia_id,
                ProspectoLead.telefono_cliente == telefono,
            )
            .order_by(ProspectoLead.id.desc())
            .first()
        )
        return lead.id if lead else None
    finally:
        db.close()


def _url_publica_desde_path(ruta: Path) -> str:
    import os

    base = os.getenv("DASHBOARD_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    try:
        rel = ruta.resolve().relative_to(static_dir().resolve())
    except ValueError:
        rel = Path("audit") / "audio" / ruta.name
    return f"{base}/static/{rel.as_posix()}"


def archivar_audio_auditoria(
    archivo_temporal: Path,
    agencia_id: int,
    telefono: str,
    mp_media_id: str | None = None,
) -> Path:
    """Copia el audio a almacenamiento permanente de auditoría."""
    destino_dir = DIR_AUDIT_AUDIO / f"agencia_{agencia_id}"
    destino_dir.mkdir(parents=True, exist_ok=True)
    marca = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    sufijo = archivo_temporal.suffix or ".ogg"
    nombre = f"{marca}_{mp_media_id or 'audio'}{sufijo}"
    destino = destino_dir / nombre
    shutil.copy2(archivo_temporal, destino)
    return destino


def registrar_interaccion_audio(
    agencia_id: int,
    telefono: str,
    audio_archivado: Path,
    transcripcion: str,
    mp_media_id: str | None = None,
    whatsapp_message_id: str | None = None,
    cliente_id: int | None = None,
) -> int:
    db = SessionLocal()
    try:
        registro = HistorialConversacion(
            agencia_id=agencia_id,
            cliente_id=cliente_id or _resolver_cliente_id(agencia_id, telefono),
            telefono_cliente=telefono,
            audio_path=str(audio_archivado),
            audio_url=_url_publica_desde_path(audio_archivado),
            transcripcion=transcripcion.strip(),
            mp_media_id=mp_media_id,
            whatsapp_message_id=whatsapp_message_id,
        )
        db.add(registro)
        db.commit()
        db.refresh(registro)
        return registro.id
    finally:
        db.close()


def eliminar_archivo_temporal(ruta: Path) -> None:
    try:
        if ruta.exists():
            ruta.unlink()
    except OSError as exc:
        print(f"[STT] No se pudo borrar temporal {ruta}: {exc}")
