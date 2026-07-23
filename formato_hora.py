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

# Para citas de agencia: "a las 2" / "2 hs" casi siempre es tarde (14:00).
_HORAS_TARDE_IMPLICITA = {1, 2, 3, 4, 5, 6, 7}

_PALABRA_A_HORA = {
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
}


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
    14:30 → 'catorce y media'
    15:15 → 'quince y cuarto'
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
    if m == 45:
        return f"{palabra_h} y cuarenta y cinco"
    return f"{palabra_h} y {_numero_en_palabras(m)}"


def _a_24h_cita(hora: int, minuto: int = 0) -> datetime.time:
    """Si es 1–7 sin contexto am/pm, asumimos tarde (13–19) para visitas."""
    if hora in _HORAS_TARDE_IMPLICITA:
        hora = hora + 12
    return datetime.time(hora % 24, minuto)


def _token_a_hora(token: str) -> int | None:
    t = (token or "").strip().lower()
    if t.isdigit():
        v = int(t)
        return v if 0 <= v <= 23 else None
    return _PALABRA_A_HORA.get(t)


def normalizar_horas_mensaje_24h(texto: str) -> str:
    """
    Reescribe el mensaje saliente a formato 24h explícito (14:00 hs).
    Corrige '2 hs', '2HS', 'a las 2', 'a las dos', '2pm', etc.
    """
    if not texto:
        return texto
    out = texto
    palabras = "|".join(sorted(_PALABRA_A_HORA.keys(), key=len, reverse=True))

    def _fmt(h: int, m: int = 0) -> str:
        return f"{formatear_hora_24h(datetime.time(h % 24, m))} hs"

    def _hora_cita_desde(h: int, m: int = 0) -> tuple[int, int]:
        if h in _HORAS_TARDE_IMPLICITA:
            h += 12
        return h, m

    # 2pm / 2 p.m. / 2am
    def _repl_pm(m: re.Match[str]) -> str:
        h = int(m.group(1))
        mins = int(m.group(2) or 0)
        if h < 12:
            h += 12
        return _fmt(h, mins)

    def _repl_am(m: re.Match[str]) -> str:
        h = int(m.group(1)) % 12
        mins = int(m.group(2) or 0)
        return _fmt(h, mins)

    out = re.sub(
        r"\b(\d{1,2})(?::([0-5]\d))?\s*p\.?\s*m\.?\b",
        _repl_pm,
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\b(\d{1,2})(?::([0-5]\d))?\s*a\.?\s*m\.?\b",
        _repl_am,
        out,
        flags=re.IGNORECASE,
    )

    # "a las 2 de la tarde" / "para las dos de la tarde"
    def _repl_tarde(m: re.Match[str]) -> str:
        h = _token_a_hora(m.group(2))
        if h is None:
            return m.group(0)
        mins = int(m.group(3) or 0)
        if h < 12:
            h += 12
        return f"{m.group(1)} {_fmt(h, mins)}"

    out = re.sub(
        rf"\b(a las?|para las?)\s*(\d{{1,2}}|{palabras})(?::([0-5]\d))?\s*"
        rf"(?:de la|por la)?\s*tarde\b",
        _repl_tarde,
        out,
        flags=re.IGNORECASE,
    )

    # "a las 2 hs" / "a las 2HS" / "para las 14:00 hs" / "a las dos hs"
    def _repl_a_las_hs(m: re.Match[str]) -> str:
        h = _token_a_hora(m.group(2))
        if h is None:
            return m.group(0)
        mins = int(m.group(3) or 0)
        h, mins = _hora_cita_desde(h, mins)
        return f"{m.group(1)} {_fmt(h, mins)}"

    out = re.sub(
        rf"\b(a las?|para las?)\s*(\d{{1,2}}|{palabras})(?::([0-5]\d))?\s*hs\.?\b",
        _repl_a_las_hs,
        out,
        flags=re.IGNORECASE,
    )

    # "2 hs" / "2HS" / "3hs" / "14:30hs" (sin "a las")
    def _repl_n_hs(m: re.Match[str]) -> str:
        h = int(m.group(1))
        mins = int(m.group(2) or 0)
        h, mins = _hora_cita_desde(h, mins)
        if not (0 <= h <= 23):
            return m.group(0)
        return _fmt(h, mins)

    out = re.sub(
        r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*hs\.?\b",
        _repl_n_hs,
        out,
        flags=re.IGNORECASE,
    )

    # "a las 2" / "a las dos" / "para las 3:30" (sin hs/am/pm ni ':' colgado)
    def _repl_a_las(m: re.Match[str]) -> str:
        h = _token_a_hora(m.group(2))
        if h is None:
            return m.group(0)
        mins = int(m.group(3) or 0)
        h, mins = _hora_cita_desde(h, mins)
        return f"{m.group(1)} {_fmt(h, mins)}"

    out = re.sub(
        rf"\b(a las?|para las?)\s*(\d{{1,2}}|{palabras})(?::([0-5]\d))?"
        rf"(?!\d)(?!:)(?!\s*hs\.?\b)(?!\s*(?:a\.?\s*m\.?|p\.?\s*m\.?|am|pm)\b)",
        _repl_a_las,
        out,
        flags=re.IGNORECASE,
    )

    out = re.sub(r"\bhs\.?\s+hs\.?\b", "hs", out, flags=re.IGNORECASE)
    out = re.sub(r"(:\d{2}\s*hs):\d{2}\s*hs\b", r"\1", out, flags=re.IGNORECASE)
    return out


def expandir_horas_para_tts(texto: str) -> str:
    """Normaliza a 24h y reemplaza 14:00 / 14 hs por forma hablada clara."""
    out = normalizar_horas_mensaje_24h(texto)

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
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\b([01]?\d|2[0-3])\s*hs\.?\b", _repl_hs, out, flags=re.IGNORECASE)
    out = re.sub(
        r"\b(\d{1,2})\s*p\.?\s*m\.?\b",
        lambda m: hora_para_voz(_pm_a_24(int(m.group(1)))),
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\b(\d{1,2})\s*a\.?\s*m\.?\b",
        lambda m: hora_para_voz(datetime.time(int(m.group(1)) % 12, 0)),
        out,
        flags=re.IGNORECASE,
    )
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
