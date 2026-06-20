"""
Speech-to-Text para audios de WhatsApp.

Motor recomendado: OpenAI Whisper API (whisper-1)
- Muy preciso en español rioplatense, ~USD 0.006/minuto.
- Alternativa local sin costo: STT_MOTOR=local con faster-whisper (requiere pip install faster-whisper).
"""

import json
import mimetypes
import os
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_BASE = "https://api.openai.com/v1"
STT_MOTOR = os.getenv("STT_MOTOR", "openai").strip().lower()
STT_IDIOMA = os.getenv("STT_IDIOMA", "es")


class SpeechToTextError(Exception):
    pass


def _token_openai() -> str:
    token = os.getenv("OPENAI_API_KEY", "").strip()
    if not token:
        raise SpeechToTextError("OPENAI_API_KEY no configurada para STT.")
    return token


def _multipart_transcripcion(archivo: Path, modelo: str, idioma: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    contenido = archivo.read_bytes()
    mime = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
    partes: list[bytes] = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{archivo.name}"\r\n'
        ).encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        contenido,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="model"\r\n\r\n',
        f"{modelo}\r\n".encode(),
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="language"\r\n\r\n',
        f"{idioma}\r\n".encode(),
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="response_format"\r\n\r\n',
        b"json\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(partes), boundary


def _transcribir_openai(archivo: Path) -> str:
    cuerpo, boundary = _multipart_transcripcion(archivo, "whisper-1", STT_IDIOMA)
    req = Request(
        f"{OPENAI_API_BASE}/audio/transcriptions",
        data=cuerpo,
        headers={
            "Authorization": f"Bearer {_token_openai()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        raise SpeechToTextError(f"Whisper API HTTP {exc.code}: {detalle}") from exc
    except URLError as exc:
        raise SpeechToTextError(f"Error de red con Whisper API: {exc}") from exc

    texto = (data.get("text") or "").strip()
    if not texto:
        raise SpeechToTextError("Whisper no devolvió texto en la transcripción.")
    return texto


def _transcribir_local(archivo: Path) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SpeechToTextError(
            "Instalá faster-whisper para STT local: pip install faster-whisper"
        ) from exc

    modelo_nombre = os.getenv("STT_MODELO_LOCAL", "small")
    model = WhisperModel(modelo_nombre, device="cpu", compute_type="int8")
    segmentos, _ = model.transcribe(str(archivo), language=STT_IDIOMA)
    partes = [seg.text.strip() for seg in segmentos if seg.text.strip()]
    texto = " ".join(partes).strip()
    if not texto:
        raise SpeechToTextError("El motor local no detectó voz en el audio.")
    return texto


def transcribir_audio(archivo: Path) -> str:
    """Convierte un archivo de audio a texto."""
    if not archivo.exists() or archivo.stat().st_size == 0:
        raise SpeechToTextError(f"Archivo de audio inválido: {archivo}")

    if STT_MOTOR == "local":
        return _transcribir_local(archivo)
    return _transcribir_openai(archivo)


def convertir_audio_a_texto(archivo: Path) -> str:
    """Alias público para el flujo de WhatsApp."""
    return transcribir_audio(archivo)
