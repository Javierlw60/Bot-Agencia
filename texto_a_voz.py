"""
Conversión texto → audio con caché local.

Motor recomendado: edge-tts (Microsoft Edge neural voices).
- Gratuito, sin API key, baja latencia y buena calidad en español rioplatense.
- Alternativa de pago/enterprise: Google Cloud TTS o ElevenLabs (configurable a futuro).
"""

import asyncio
import hashlib
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from paths_datos import static_dir

load_dotenv()

CACHE_TTS_DIR = static_dir() / "cache" / "tts"
CACHE_TTS_DIR.mkdir(parents=True, exist_ok=True)
VOZ_DEFAULT = os.getenv("TTS_VOZ", "es-AR-ElenaNeural")
MAX_CARACTERES_TTS = int(os.getenv("TTS_MAX_CARACTERES", "1500"))


def _normalizar_texto_tts(texto: str) -> str:
    limpio = re.sub(r"https?://\S+", "", texto)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    if len(limpio) > MAX_CARACTERES_TTS:
        limpio = limpio[: MAX_CARACTERES_TTS - 3].rstrip() + "..."
    return limpio


def _clave_cache(texto: str, voz: str) -> str:
    payload = f"{voz}|{_normalizar_texto_tts(texto)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ruta_cache(texto: str, voz: str | None = None) -> Path:
    voz_usada = (voz or VOZ_DEFAULT).strip()
    nombre = f"{_clave_cache(texto, voz_usada)}.mp3"
    return CACHE_TTS_DIR / nombre


async def _generar_audio_async(texto: str, destino: Path, voz: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(texto, voz)
    await communicate.save(str(destino))


def _correr_coro(coro):
    """Ejecuta una corrutina aunque ya haya un event loop (uvicorn/FastAPI)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Ya hay loop: correr en un hilo con su propio asyncio.run.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=120)


def convertir_texto_a_voz(texto: str, voz: str | None = None) -> Path:
    """
    Convierte texto a MP3 y devuelve la ruta del archivo.
    Reutiliza caché si la misma frase ya fue sintetizada.
    """
    if not texto or not str(texto).strip():
        raise ValueError("El texto para TTS no puede estar vacío.")

    CACHE_TTS_DIR.mkdir(parents=True, exist_ok=True)
    voz_usada = (voz or VOZ_DEFAULT).strip()
    texto_tts = _normalizar_texto_tts(texto)
    if not texto_tts:
        raise ValueError("El texto quedó vacío tras limpiar URLs.")

    destino = _ruta_cache(texto, voz_usada)
    if destino.exists() and destino.stat().st_size > 0:
        return destino

    _correr_coro(_generar_audio_async(texto_tts, destino, voz_usada))
    if not destino.exists() or destino.stat().st_size == 0:
        raise RuntimeError("edge-tts no generó el archivo de audio.")
    return destino


def url_publica_audio(ruta: Path) -> str:
    """URL HTTP del audio servido por FastAPI (/static/...)."""
    base = os.getenv("DASHBOARD_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    try:
        rel = ruta.resolve().relative_to(static_dir().resolve())
    except ValueError:
        rel = Path("cache") / "tts" / ruta.name
    return f"{base}/static/{rel.as_posix()}"


def audio_en_cache(texto: str, voz: str | None = None) -> bool:
    return _ruta_cache(texto, voz).exists()
