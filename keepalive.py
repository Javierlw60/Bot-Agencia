"""Keep-alive: ping periódico a /health para evitar sleep del servicio (Render free).

Render (y similares) apagan el proceso tras ~15 min sin tráfico HTTP entrante.
Un ping a la URL pública cuenta como actividad y mantiene el bot despierto.

Variables:
  KEEPALIVE_ACTIVO=true|false   (default: true si hay DASHBOARD_BASE_URL/APP_URL pública)
  KEEPALIVE_INTERVALO_MIN=10
  KEEPALIVE_URL=https://...     (opcional; si no, usa DASHBOARD_BASE_URL/APP_URL + /health)
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request


def _url_publica_base() -> str:
    for nombre in ("KEEPALIVE_URL", "DASHBOARD_BASE_URL", "APP_URL", "FRONTEND_URL"):
        valor = (os.getenv(nombre) or "").strip().rstrip("/")
        if not valor:
            continue
        if nombre == "KEEPALIVE_URL":
            return valor
        return f"{valor}/health"
    return ""


def _es_url_local(url: str) -> bool:
    bajo = url.lower()
    return any(
        host in bajo
        for host in (
            "://127.0.0.1",
            "://localhost",
            "://0.0.0.0",
            "://[::1]",
        )
    )


def keepalive_habilitado() -> bool:
    flag = (os.getenv("KEEPALIVE_ACTIVO") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    # Por defecto: activo solo si hay URL pública (no localhost).
    url = _url_publica_base()
    return bool(url) and not _es_url_local(url)


def intervalo_keepalive_minutos() -> int:
    try:
        valor = int(os.getenv("KEEPALIVE_INTERVALO_MIN", "10"))
    except ValueError:
        valor = 10
    return max(5, min(valor, 14))


def ejecutar_keepalive() -> bool:
    """Hace GET a /health. Devuelve True si respondió OK."""
    url = _url_publica_base()
    if not url:
        print("[KEEPALIVE] Sin URL pública (DASHBOARD_BASE_URL/APP_URL). Skip.")
        return False
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "BotAgencias-KeepAlive/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
            if ok:
                print(f"[KEEPALIVE] OK → {url}")
            else:
                print(f"[KEEPALIVE] Respuesta {resp.status} → {url}")
            return ok
    except urllib.error.HTTPError as exc:
        print(f"[KEEPALIVE] HTTP {exc.code} → {url}")
        return False
    except Exception as exc:
        print(f"[KEEPALIVE] Error → {url}: {exc}")
        return False
