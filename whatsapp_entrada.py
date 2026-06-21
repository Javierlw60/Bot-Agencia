"""Orquestación del bot para mensajes entrantes de WhatsApp (texto y audio)."""

from pathlib import Path

from audio_a_texto import SpeechToTextError, convertir_audio_a_texto
from auditoria_audio import (
    archivar_audio_auditoria,
    eliminar_archivo_temporal,
    registrar_interaccion_audio,
)
from bot import SesionCliente, _enviar_bienvenida_inicial, _finalizar_y_guardar_lead, _procesar_mensaje
from models.database import Agencia, Sucursal, Vendedor
from sesiones_bot import obtener_o_crear_sesion
from whatsapp import descargar_media_whatsapp, enviar_respuesta_bot

DIR_TEMP_AUDIO = Path(__file__).resolve().parent / "static" / "temp" / "whatsapp"


def _aplicar_sucursal_sesion(
    sesion: SesionCliente,
    sucursal: Sucursal | None,
    vendedor: Vendedor | None = None,
) -> None:
    if sucursal:
        sesion.sucursal_origen_id = sucursal.id
    if vendedor:
        sesion.vendedor_origen_id = vendedor.id
        if vendedor.sucursal_id:
            sesion.sucursal_origen_id = vendedor.sucursal_id
        if vendedor.telefono_whatsapp:
            sesion.line_whatsapp_id = vendedor.telefono_whatsapp
    elif sucursal and sucursal.telefono_whatsapp:
        sesion.line_whatsapp_id = sucursal.telefono_whatsapp


def _linea_whatsapp_respuesta(agencia: Agencia, sesion: SesionCliente) -> str:
    if sesion.line_whatsapp_id:
        return sesion.line_whatsapp_id
    return agencia.whatsapp_phone_number_id


def procesar_texto_whatsapp(
    agencia: Agencia,
    telefono: str,
    texto: str,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    """Pasa un mensaje escrito a la lógica principal del bot."""
    sesion = obtener_o_crear_sesion(agencia.id, telefono)
    _aplicar_sucursal_sesion(sesion, sucursal, vendedor)
    _enviar_bienvenida_inicial(sesion, agencia, via_whatsapp=True)
    respuesta = _procesar_mensaje(sesion, agencia, texto, via_whatsapp=True)
    _finalizar_y_guardar_lead(sesion)
    return respuesta


def procesar_audio_whatsapp(
    agencia: Agencia,
    telefono: str,
    media_id: str,
    whatsapp_message_id: str | None = None,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> dict:
    """
    Flujo completo de audio entrante:
    descarga → STT → auditoría → limpieza → procesar_mensaje.
    """
    DIR_TEMP_AUDIO.mkdir(parents=True, exist_ok=True)
    archivo_temp = DIR_TEMP_AUDIO / f"{media_id}.ogg"
    resultado = {
        "ok": False,
        "transcripcion": None,
        "respuesta": None,
        "auditoria_id": None,
    }

    try:
        descargar_media_whatsapp(media_id, archivo_temp)
        transcripcion = convertir_audio_a_texto(archivo_temp)
        resultado["transcripcion"] = transcripcion

        audio_archivado = archivar_audio_auditoria(
            archivo_temporal=archivo_temp,
            agencia_id=agencia.id,
            telefono=telefono,
            mp_media_id=media_id,
        )
        sesion = obtener_o_crear_sesion(agencia.id, telefono)
        _aplicar_sucursal_sesion(sesion, sucursal, vendedor)
        auditoria_id = registrar_interaccion_audio(
            agencia_id=agencia.id,
            telefono=telefono,
            audio_archivado=audio_archivado,
            transcripcion=transcripcion,
            mp_media_id=media_id,
            whatsapp_message_id=whatsapp_message_id,
            cliente_id=sesion.lead_id,
        )
        resultado["auditoria_id"] = auditoria_id

        _enviar_bienvenida_inicial(sesion, agencia, via_whatsapp=True)
        respuesta = _procesar_mensaje(
            sesion,
            agencia,
            transcripcion,
            via_whatsapp=True,
            etiqueta_cliente=f"[Audio transcrito] {transcripcion}",
        )
        _finalizar_y_guardar_lead(sesion)
        resultado["respuesta"] = respuesta
        resultado["ok"] = True
        return resultado
    except SpeechToTextError as exc:
        sesion = obtener_o_crear_sesion(agencia.id, telefono)
        _aplicar_sucursal_sesion(sesion, sucursal, vendedor)
        mensaje_error = (
            "No pude entender el audio. ¿Podés escribirme tu consulta por texto?"
        )
        enviar_respuesta_bot(
            telefono_destino=telefono,
            mensaje=mensaje_error,
            whatsapp_phone_number_id=_linea_whatsapp_respuesta(agencia, sesion),
            modo_respuesta=agencia.modo_respuesta,
            imprimir_texto_en_consola=False,
        )
        resultado["respuesta"] = mensaje_error
        resultado["error"] = str(exc)
        return resultado
    except Exception as exc:
        resultado["error"] = str(exc)
        raise
    finally:
        eliminar_archivo_temporal(archivo_temp)
