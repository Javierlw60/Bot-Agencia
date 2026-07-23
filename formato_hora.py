"""Formato de hora 24h para texto, BD y TTS (evitar confusión 2pm vs 14:00)."""

from __future__ import annotations

import datetime
import re

_NUMEROS_ES = (
    "cero",
    "una",
    "dos",
    "tres",
    "cuatro",
    "cinco",
    "seis",
    "siete",
    "ocho",
    "nueve",
    "diez",
    "once",
    "doce",
    "trece",
    "catorce",
    "quince",
    "dieciséis",
    "diecisiete",
    "dieciocho",
    "diecinueve",
    "veinte",
    "veintiuna",
    "veintidós",
    "veintitrés",
)


def formatear_hora_24h(hora: datetime.time | str) -> str:
    """Siempre HH:MM en 24 horas (ej. 14:00)."""
    if isinstance(hora, str):
        partes = hora.strip().split(":")
        h = int(partes[0])
        m = int(partes[1]) if len(partes) > 1 else 0
        hora = datetime.time(h, m)
    return f"{hora.hour:02d}:{hora.minute:02d}"


def _numero_en_palabras(n: int) -> str:
    if 0 <= n <= 23:
        return _NUMEROS_ES[n]
    return str(n)


def hora_para_voz(hora: datetime.time | str) -> str:
    """
    Cómo debe sonar la hora en audio, sin ambigüedad.
    14:00 → 'catorce horas'
    14:30 → 'catorce y treinta'
    """
    texto = formatear_hora_24h(hora)
    h, m = map(int, texto.split(":"))
    palabra_h = _numero_en_palabras(h)
    if m == 0:
        return f"{palabra_h} horas"
    if m == 15:
        return f"{palabra_h} y cuarto"
    if m == 30:
        return f"{palabra_h} y media"
    return f"{palabra_h} y {_numero_en_palabras(m)}"


def expandir_horas_para_tts(texto: str) -> str:
    """Reemplaza 14:00 / 14 hs / 14hs por forma hablada clara en 24h."""

    def _repl_hhmm(match: re.Match[str]) -> str:
        h = int(match.group(1))
        m = int(match.group(2))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return match.group(0)
        return hora_para_voz(datetime.time(h, m))

    def _repl_hs(match: re.Match[str]) -> str:
        h = int(match.group(1))
        if not (0 <= h <= 23):
            return match.group(0)
        return hora_para_voz(datetime.time(h, 0))

    out = re.sub(
        r"\b([01]?\d|2[0-3]):([0-5]\d)(?:\s*hs\.?)?(?=\s|$|[.,;:!?])",
        _repl_hhmm,
        texto,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\b([01]?\d|2[0-3])\s*hs\.?\b", _repl_hs, out, flags=re.IGNORECASE)
    # Evitar que el TTS lea "2pm" si quedó en el texto.
    out = re.sub(r"\b(\d{1,2})\s*p\.?\s*m\.?\b", lambda m: hora_para_voz(_pm_a_24(int(m.group(1)))), out, flags=re.IGNORECASE)
    out = re.sub(r"\b(\d{1,2})\s*a\.?\s*m\.?\b", lambda m: hora_para_voz(datetime.time(int(m.group(1)) % 12, 0)), out, flags=re.IGNORECASE)
    return out


def _pm_a_24(hora_12: int) -> datetime.time:
    if hora_12 == 12:
        return datetime.time(12, 0)
    return datetime.time((hora_12 % 12) + 12, 0)


def interpretar_hora_12h_si_aplica(
    horas: int,
    minutos: int,
    sufijo: str | None,
    contexto_norm: str = "",
) -> datetime.time | None:
    """
    Convierte 2pm / 2 a.m. / 'de la tarde' a 24h.
    Si no hay sufijo, deja la hora en 24h tal cual (0-23).
    """
    if not (0 <= horas <= 23 and 0 <= minutos <= 59):
        return None
    suf = (sufijo or "").strip().lower().replace(".", "")
    if suf in {"pm", "p m"}:
        if horas < 12:
            horas += 12
        elif horas == 12:
            pass
        return datetime.time(horas, minutos)
    if suf in {"am", "a m"}:
        if horas == 12:
            horas = 0
        return datetime.time(horas, minutos)

    # "a las 2 de la tarde" / "para las 2 de la tarde"
    if horas <= 12 and re.search(r"\bde la tarde\b|\bpor la tarde\b|\ba la tarde\b", contexto_norm):
        if horas < 12:
            horas += 12
        return datetime.time(horas, minutos)
    if horas <= 12 and re.search(r"\bde la manana\b|\bpor la manana\b|\ba la manana\b", contexto_norm):
        if horas == 12:
            horas = 0
        return datetime.time(horas, minutos)

    return datetime.time(horas, minutos)
