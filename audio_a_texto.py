"""
Speech-to-Text para audios de WhatsApp.

Motores (STT_MOTOR):
  - auto   → Gemini si hay GEMINI_API_KEY, si no OpenAI Whisper, si no local
  - gemini → Google Gemini (usa GEMINI_API_KEY, ya configurada para el bot)
  - openai → OpenAI Whisper API (requiere OPENAI_API_KEY)
  - local  → faster-whisper (pip install faster-whisper)
"""

from __future__ import annotations

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
STT_MOTOR = os.getenv("STT_MOTOR", "auto").strip().lower()
STT_IDIOMA = os.getenv("STT_IDIOMA", "es")
# gemini-2.0-flash fue retirado (404 desde jun 2026). Default alineado con el chat del bot.
STT_GEMINI_MODELO = os.getenv("STT_GEMINI_MODELO", "gemini-2.5-flash").strip()
# Si el modelo principal falla con 404/NOT_FOUND, se prueban estos en orden.
_STT_GEMINI_FALLBACKS = [
    m.strip()
    for m in os.getenv(
        "STT_GEMINI_FALLBACKS",
        "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash",
    ).split(",")
    if m.strip()
]


class SpeechToTextError(Exception):
    pass


def _token_openai() -> str:
    token = os.getenv("OPENAI_API_KEY", "").strip()
    if not token:
        raise SpeechToTextError("OPENAI_API_KEY no configurada para STT.")
    return token


def _token_gemini() -> str:
    token = (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )
    if not token:
        raise SpeechToTextError("GEMINI_API_KEY no configurada para STT.")
    return token


def _mime_audio(archivo: Path) -> str:
    mime = mimetypes.guess_type(archivo.name)[0]
    if mime:
        return mime
    ext = archivo.suffix.lower()
    return {
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
    }.get(ext, "audio/ogg")


def _multipart_transcripcion(archivo: Path, modelo: str, idioma: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    contenido = archivo.read_bytes()
    mime = _mime_audio(archivo)
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


def _modelos_gemini_stt() -> list[str]:
    orden: list[str] = []
    for modelo in [STT_GEMINI_MODELO, *_STT_GEMINI_FALLBACKS]:
        if modelo and modelo not in orden:
            orden.append(modelo)
    return orden


def _es_error_modelo_inexistente(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(
        marca in texto
        for marca in (
            "404",
            "not_found",
            "not found",
            "no longer available",
            "is not found",
            "model not found",
        )
    )


def _transcribir_gemini(archivo: Path) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise SpeechToTextError(
            "Falta el paquete google-genai para STT con Gemini."
        ) from exc

    api_key = _token_gemini()
    client = genai.Client(api_key=api_key)
    audio_bytes = archivo.read_bytes()
    prompt = (
        "Transcribí este audio de WhatsApp al español. "
        "Devolvé SOLO la transcripción literal del habla, sin comillas, "
        "sin comentarios ni puntuación inventada de más. "
        f"Idioma esperado: {STT_IDIOMA}."
    )
    errores: list[str] = []
    for modelo in _modelos_gemini_stt():
        try:
            respuesta = client.models.generate_content(
                model=modelo,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=audio_bytes, mime_type=_mime_audio(archivo)),
                ],
            )
        except Exception as exc:
            errores.append(f"{modelo}: {exc}")
            if _es_error_modelo_inexistente(exc):
                print(f"[STT] Modelo Gemini no disponible ({modelo}), probando otro…")
                continue
            raise SpeechToTextError(f"Gemini STT falló: {exc}") from exc

        texto = (getattr(respuesta, "text", None) or "").strip()
        if not texto:
            errores.append(f"{modelo}: sin texto")
            continue
        if modelo != STT_GEMINI_MODELO:
            print(f"[STT] Gemini OK con modelo fallback={modelo}")
        return texto

    detalle = " | ".join(errores) if errores else "sin detalle"
    raise SpeechToTextError(f"Gemini STT falló con todos los modelos: {detalle}")


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


def _motores_auto() -> list[str]:
    orden: list[str] = []
    if os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip():
        orden.append("gemini")
    if os.getenv("OPENAI_API_KEY", "").strip():
        orden.append("openai")
    orden.append("local")
    return orden


def transcribir_audio(archivo: Path) -> str:
    """Convierte un archivo de audio a texto."""
    if not archivo.exists() or archivo.stat().st_size == 0:
        raise SpeechToTextError(f"Archivo de audio inválido: {archivo}")

    motor = STT_MOTOR or "auto"
    if motor == "auto":
        motores = _motores_auto()
        errores: list[str] = []
        for nombre in motores:
            try:
                if nombre == "gemini":
                    texto = _transcribir_gemini(archivo)
                elif nombre == "openai":
                    texto = _transcribir_openai(archivo)
                else:
                    texto = _transcribir_local(archivo)
                print(f"[STT] OK con motor={nombre}")
                return texto
            except SpeechToTextError as exc:
                errores.append(f"{nombre}: {exc}")
                print(f"[STT] Falló motor={nombre}: {exc}")
        raise SpeechToTextError(
            "Ningún motor STT pudo transcribir. "
            + " | ".join(errores)
            + ". Configurá GEMINI_API_KEY (recomendado) u OPENAI_API_KEY, "
            "o STT_MOTOR=local con faster-whisper."
        )

    if motor == "gemini":
        return _transcribir_gemini(archivo)
    if motor == "local":
        return _transcribir_local(archivo)
    if motor == "openai":
        return _transcribir_openai(archivo)
    raise SpeechToTextError(
        f"STT_MOTOR={motor!r} no soportado. Usá auto|gemini|openai|local."
    )


def convertir_audio_a_texto(archivo: Path) -> str:
    """Alias público para el flujo de WhatsApp."""
    return transcribir_audio(archivo)
