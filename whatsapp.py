import json
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from modo_respuesta import (
    debe_enviar_texto,
    debe_enviar_voz,
    normalizar_modo_respuesta,
)
from texto_a_voz import convertir_texto_a_voz, url_publica_audio

load_dotenv()

GRAPH_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _modo_whatsapp() -> str:
    from whatsapp_config import whatsapp_modo
    return whatsapp_modo()


def _token() -> str:
    from whatsapp_config import whatsapp_access_token
    return whatsapp_access_token()


def _normalizar_telefono(telefono: str) -> str:
    return re.sub(r"\D", "", telefono.strip())


def _post_json(url: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            cuerpo = resp.read().decode("utf-8")
            return json.loads(cuerpo) if cuerpo else {}
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        print(f"[WHATSAPP] HTTP {exc.code}: {detalle}")
        raise
    except URLError as exc:
        print(f"[WHATSAPP] Error de red: {exc}")
        raise


def _multipart_archivo(
    archivo: Path,
    *,
    tipo_media: str | None = None,
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    contenido = archivo.read_bytes()
    mime = tipo_media or mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
    partes: list[bytes] = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="messaging_product"\r\n\r\n',
        b"whatsapp\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="type"\r\n\r\n',
        f"{mime}\r\n".encode(),
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{archivo.name}"\r\n'
        ).encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        contenido,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(partes), boundary


def _multipart_audio(archivo: Path) -> tuple[bytes, str]:
    return _multipart_archivo(
        archivo, tipo_media=mimetypes.guess_type(archivo.name)[0] or "audio/mpeg"
    )


def _get_json(url: str, token: str) -> dict[str, Any]:
    req = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(req, timeout=60) as resp:
            cuerpo = resp.read().decode("utf-8")
            return json.loads(cuerpo) if cuerpo else {}
    except HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        print(f"[WHATSAPP] HTTP GET {exc.code}: {detalle}")
        raise
    except URLError as exc:
        print(f"[WHATSAPP] Error de red GET: {exc}")
        raise


def _descargar_binario(url: str, token: str) -> bytes:
    req = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    with urlopen(req, timeout=120) as resp:
        return resp.read()


def descargar_media_whatsapp(
    media_id: str,
    destino: Path,
    token: str | None = None,
) -> Path:
    """
    Descarga un archivo multimedia desde los servidores de Meta.
    1) GET /{media-id} → URL firmada
    2) GET URL → bytes del archivo
    """
    access_token = token or _token()
    if not access_token:
        raise RuntimeError("WHATSAPP_ACCESS_TOKEN no configurado.")

    meta = _get_json(f"{GRAPH_API_BASE}/{media_id}", access_token)
    url_media = meta.get("url")
    if not url_media:
        raise RuntimeError(f"Meta no devolvió URL para media {media_id}: {meta}")

    contenido = _descargar_binario(url_media, access_token)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)
    return destino


def _subir_media(
    whatsapp_phone_number_id: str,
    ruta_archivo: Path,
    token: str,
    *,
    tipo_media: str | None = None,
) -> str:
    cuerpo, boundary = _multipart_archivo(ruta_archivo, tipo_media=tipo_media)
    url = f"{GRAPH_API_BASE}/{whatsapp_phone_number_id}/media"
    req = Request(
        url,
        data=cuerpo,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    media_id = data.get("id")
    if not media_id:
        raise RuntimeError(f"WhatsApp no devolvió media id: {data}")
    return str(media_id)


def _subir_audio(whatsapp_phone_number_id: str, ruta_audio: Path, token: str) -> str:
    return _subir_media(whatsapp_phone_number_id, ruta_audio, token)


def _ruta_local_imagen(url_o_ruta: str) -> Path | None:
    valor = (url_o_ruta or "").strip()
    if not valor:
        return None
    candidato = Path(valor)
    if candidato.is_file():
        return candidato
    if valor.startswith("/static/"):
        from paths_datos import static_dir

        rel = valor[len("/static/") :]
        local = static_dir() / rel
        if local.is_file():
            return local
        # Fallback al static del repo (assets no persistentes).
        local_repo = Path(__file__).resolve().parent / "static" / rel
        if local_repo.is_file():
            return local_repo
    return None


def enviar_imagen_whatsapp(
    telefono_destino: str,
    imagen_url_o_ruta: str,
    whatsapp_phone_number_id: str,
    caption: str = "",
) -> bool:
    """
    Envía una imagen por WhatsApp Cloud API.
    Preferencia: subir archivo local. Si no hay archivo, usa link público https.
    """
    telefono = _normalizar_telefono(telefono_destino)
    origen = (imagen_url_o_ruta or "").strip()
    if not telefono or not origen:
        return False

    modo = _modo_whatsapp()
    if modo == "consola":
        print(f"\n[WHATSAPP IMAGEN -> +{telefono} | linea {whatsapp_phone_number_id}]")
        print(f"Origen: {origen}")
        if caption:
            print(f"Caption: {caption}")
        print()
        return True

    if modo != "api":
        print(f"[WHATSAPP] Modo desconocido: {modo}")
        return False

    token = _token()
    if not token:
        print("[WHATSAPP] WHATSAPP_ACCESS_TOKEN no configurado.")
        return False

    url = f"{GRAPH_API_BASE}/{whatsapp_phone_number_id}/messages"
    imagen_payload: dict[str, Any] = {}
    local = _ruta_local_imagen(origen)
    try:
        if local is not None:
            mime = mimetypes.guess_type(local.name)[0] or "image/jpeg"
            if not mime.startswith("image/"):
                mime = "image/jpeg"
            media_id = _subir_media(
                whatsapp_phone_number_id, local, token, tipo_media=mime
            )
            imagen_payload["id"] = media_id
        elif origen.startswith(("https://", "http://")):
            imagen_payload["link"] = origen
        else:
            print(f"[WHATSAPP] Imagen no accesible (ni archivo local ni URL): {origen}")
            return False

        if caption.strip():
            imagen_payload["caption"] = caption.strip()[:1024]

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono,
            "type": "image",
            "image": imagen_payload,
        }
        _post_json(url, payload, token)
        return True
    except Exception as exc:
        print(
            f"[WHATSAPP] Error enviando imagen a +{telefono} "
            f"(linea {whatsapp_phone_number_id}): {exc}"
        )
        return False


def enviar_mensaje_texto_whatsapp(
    telefono_destino: str,
    mensaje: str,
    whatsapp_phone_number_id: str,
    imprimir_en_consola: bool = True,
) -> bool:
    telefono = _normalizar_telefono(telefono_destino)
    if not telefono or not mensaje.strip():
        return False

    modo = _modo_whatsapp()
    if modo == "consola":
        if imprimir_en_consola:
            print(f"\n[WHATSAPP TEXTO -> +{telefono} | linea {whatsapp_phone_number_id}]")
            print(mensaje)
            print()
        return True

    if modo == "api":
        token = _token()
        if not token:
            print("[WHATSAPP] WHATSAPP_ACCESS_TOKEN no configurado.")
            return False
        url = f"{GRAPH_API_BASE}/{whatsapp_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono,
            "type": "text",
            "text": {"preview_url": False, "body": mensaje},
        }
        try:
            _post_json(url, payload, token)
            return True
        except Exception as exc:
            print(
                f"[WHATSAPP] Error enviando texto a +{telefono} "
                f"(linea {whatsapp_phone_number_id}): {exc}"
            )
            return False

    print(f"[WHATSAPP] Modo desconocido: {modo}")
    return False


def enviar_audio_whatsapp(
    telefono_destino: str,
    ruta_audio: Path,
    whatsapp_phone_number_id: str,
) -> bool:
    telefono = _normalizar_telefono(telefono_destino)
    if not telefono or not ruta_audio.exists():
        return False

    modo = _modo_whatsapp()
    if modo == "consola":
        print(f"\n[WHATSAPP AUDIO -> +{telefono} | linea {whatsapp_phone_number_id}]")
        print(f"Archivo: {ruta_audio}")
        print(f"URL pública: {url_publica_audio(ruta_audio)}")
        print()
        return True

    if modo == "api":
        token = _token()
        if not token:
            print("[WHATSAPP] WHATSAPP_ACCESS_TOKEN no configurado.")
            return False
        try:
            media_id = _subir_audio(whatsapp_phone_number_id, ruta_audio, token)
            url = f"{GRAPH_API_BASE}/{whatsapp_phone_number_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": telefono,
                "type": "audio",
                "audio": {"id": media_id},
            }
            _post_json(url, payload, token)
            return True
        except Exception as exc:
            print(f"[WHATSAPP] Error enviando audio: {exc}")
            return False

    print(f"[WHATSAPP] Modo desconocido: {modo}")
    return False


def enviar_mensaje_whatsapp(
    telefono_destino: str,
    mensaje: str,
    whatsapp_phone_number_id: str,
) -> bool:
    """Compatibilidad con recordatorios y flujos legacy (solo texto)."""
    return enviar_mensaje_texto_whatsapp(
        telefono_destino=telefono_destino,
        mensaje=mensaje,
        whatsapp_phone_number_id=whatsapp_phone_number_id,
    )


def enviar_respuesta_bot(
    telefono_destino: str,
    mensaje: str,
    whatsapp_phone_number_id: str,
    modo_respuesta: str | None = None,
    imprimir_texto_en_consola: bool = True,
) -> dict[str, bool]:
    """
    Envía la respuesta del bot según la preferencia de la agencia:
    texto, voz o ambas.
    """
    modo = normalizar_modo_respuesta(modo_respuesta)
    resultado = {"texto": False, "voz": False}

    if debe_enviar_texto(modo):
        resultado["texto"] = enviar_mensaje_texto_whatsapp(
            telefono_destino=telefono_destino,
            mensaje=mensaje,
            whatsapp_phone_number_id=whatsapp_phone_number_id,
            imprimir_en_consola=imprimir_texto_en_consola,
        )

    if debe_enviar_voz(modo):
        try:
            ruta_audio = convertir_texto_a_voz(mensaje)
            resultado["voz"] = enviar_audio_whatsapp(
                telefono_destino=telefono_destino,
                ruta_audio=ruta_audio,
                whatsapp_phone_number_id=whatsapp_phone_number_id,
            )
        except Exception as exc:
            print(f"[WHATSAPP] No se pudo generar/enviar audio: {exc}")
            if not resultado["texto"]:
                resultado["texto"] = enviar_mensaje_texto_whatsapp(
                    telefono_destino=telefono_destino,
                    mensaje=mensaje,
                    whatsapp_phone_number_id=whatsapp_phone_number_id,
                    imprimir_en_consola=imprimir_texto_en_consola,
                )

    return resultado
