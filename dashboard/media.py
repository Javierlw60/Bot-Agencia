import json
from pathlib import Path
from urllib.parse import unquote

from models.database import Auto


def _url_limpia(url: str | None) -> str | None:
    if not url:
        return None
    limpia = unquote(str(url).strip())
    return limpia or None


def _ruta_local_desde_url(url: str, base_static: Path) -> Path | None:
    prefijo = "/static/"
    if not url.startswith(prefijo):
        return None
    return base_static / url.removeprefix(prefijo)


def obtener_fotos_auto(auto: Auto) -> list[str]:
    fotos: list[str] = []
    vistos: set[str] = set()

    if auto.fotos_json:
        try:
            extra = json.loads(auto.fotos_json)
            if isinstance(extra, list):
                for url in extra:
                    limpia = _url_limpia(url)
                    if limpia and limpia not in vistos:
                        fotos.append(limpia)
                        vistos.add(limpia)
        except json.JSONDecodeError:
            pass

    principal = _url_limpia(auto.foto_principal_url)
    if principal and principal not in vistos:
        fotos.insert(0, principal)

    return fotos


def filtrar_fotos_visibles(auto: Auto, base_static: Path) -> tuple[list[str], list[str]]:
    validas: list[str] = []
    invalidas: list[str] = []

    for url in obtener_fotos_auto(auto):
        ruta_local = _ruta_local_desde_url(url, base_static)
        if ruta_local is not None:
            if ruta_local.is_file():
                validas.append(url)
            else:
                invalidas.append(url)
        else:
            validas.append(url)

    return validas, invalidas


def sincronizar_fotos_auto(auto: Auto, base_static: Path) -> list[str]:
    validas, invalidas = filtrar_fotos_visibles(auto, base_static)
    if invalidas:
        guardar_fotos_auto(auto, validas)
    return validas


def eliminar_foto_de_auto(auto: Auto, foto_url: str) -> bool:
    objetivo = _url_limpia(foto_url)
    if not objetivo:
        return False
    fotos = obtener_fotos_auto(auto)
    nuevas = [f for f in fotos if _url_limpia(f) != objetivo]
    if len(nuevas) == len(fotos):
        return False
    guardar_fotos_auto(auto, nuevas)
    return True


def definir_portada_auto(auto: Auto, foto_url: str) -> bool:
    objetivo = _url_limpia(foto_url)
    if not objetivo:
        return False
    fotos = obtener_fotos_auto(auto)
    if objetivo not in fotos:
        return False
    reordenadas = [objetivo] + [f for f in fotos if _url_limpia(f) != objetivo]
    guardar_fotos_auto(auto, reordenadas, principal=objetivo)
    return True


def obtener_portada_auto(auto: Auto) -> str | None:
    return _url_limpia(auto.foto_principal_url)


def guardar_fotos_auto(auto: Auto, fotos: list[str], principal: str | None = None) -> None:
    fotos_limpias = [_url_limpia(f) for f in fotos]
    fotos_limpias = [f for f in fotos_limpias if f]
    if principal and principal in fotos_limpias:
        auto.foto_principal_url = principal
    elif fotos_limpias:
        auto.foto_principal_url = fotos_limpias[0]
    else:
        auto.foto_principal_url = None
    auto.fotos_json = json.dumps(fotos_limpias, ensure_ascii=False) if fotos_limpias else None


def agregar_foto_a_auto(auto: Auto, url: str) -> None:
    limpia = _url_limpia(url)
    if not limpia:
        return
    fotos = obtener_fotos_auto(auto)
    if limpia not in fotos:
        fotos.append(limpia)
    guardar_fotos_auto(auto, fotos)


def url_publica_upload(agencia_id: int, auto_id: int, nombre_archivo: str) -> str:
    return f"/static/uploads/agencia_{agencia_id}/auto_{auto_id}/{nombre_archivo}"


def directorio_upload(agencia_id: int, auto_id: int, base: Path) -> Path:
    destino = base / "uploads" / f"agencia_{agencia_id}" / f"auto_{auto_id}"
    destino.mkdir(parents=True, exist_ok=True)
    return destino
