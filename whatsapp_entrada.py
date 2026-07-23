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
from whatsapp_linea import linea_envio_whatsapp_api

DIR_TEMP_AUDIO = Path(__file__).resolve().parent / "static" / "temp" / "whatsapp"


def _aplicar_sucursal_sesion(
    sesion: SesionCliente,
    sucursal: Sucursal | None,
    vendedor: Vendedor | None = None,
    *,
    phone_number_id_meta: str | None = None,
) -> None:
    if sucursal:
        sesion.sucursal_origen_id = sucursal.id
    if vendedor:
        sesion.vendedor_origen_id = vendedor.id
        if vendedor.sucursal_id:
            sesion.sucursal_origen_id = vendedor.sucursal_id
    if phone_number_id_meta:
        sesion.line_whatsapp_id = phone_number_id_meta


def _linea_whatsapp_respuesta(
    agencia: Agencia,
    sesion: SesionCliente,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    return linea_envio_whatsapp_api(
        agencia,
        phone_number_id_receptor=sesion.line_whatsapp_id,
        sucursal=sucursal,
        vendedor=vendedor,
    )


def procesar_texto_whatsapp(
    agencia: Agencia,
    telefono: str,
    texto: str,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
    *,
    phone_number_id_meta: str | None = None,
) -> str:
    """Pasa un mensaje escrito a la lógica principal del bot."""
    sesion = obtener_o_crear_sesion(agencia.id, telefono)
    _aplicar_sucursal_sesion(
        sesion, sucursal, vendedor, phone_number_id_meta=phone_number_id_meta
    )
    sesion.entrada_fue_audio = False
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
    *,
    phone_number_id_meta: str | None = None,
) -> dict:
    """
    Flujo completo de audio entrante:
    descarga → STT → auditoría → limpieza → procesar_mensaje.
    Responde en voz (espejo de modalidad).
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
        print(f"[STT] Transcribiendo audio media_id={media_id}…")
        transcripcion = convertir_audio_a_texto(archivo_temp)
        resultado["transcripcion"] = transcripcion
        print(f"[STT] Transcripción: {transcripcion!r}")

        audio_archivado = archivar_audio_auditoria(
            archivo_temporal=archivo_temp,
            agencia_id=agencia.id,
            telefono=telefono,
            mp_media_id=media_id,
        )
        sesion = obtener_o_crear_sesion(agencia.id, telefono)
        _aplicar_sucursal_sesion(
            sesion, sucursal, vendedor, phone_number_id_meta=phone_number_id_meta
        )
        sesion.entrada_fue_audio = True
        # La auditoría no debe frenar la respuesta al cliente (p.ej. VARCHAR corto).
        try:
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
        except Exception as exc:
            print(f"[STT] Auditoría de audio falló (se continúa igual): {exc}")

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
        print(f"[STT] Error: {exc}")
        sesion = obtener_o_crear_sesion(agencia.id, telefono)
        _aplicar_sucursal_sesion(
            sesion, sucursal, vendedor, phone_number_id_meta=phone_number_id_meta
        )
        mensaje_error = (
            "No pude entender el audio. ¿Podés escribirme tu consulta por texto?"
        )
        # Fallback siempre en texto (no intentar TTS si STT falló).
        enviar_respuesta_bot(
            telefono_destino=telefono,
            mensaje=mensaje_error,
            whatsapp_phone_number_id=_linea_whatsapp_respuesta(
                agencia, sesion, sucursal=sucursal, vendedor=vendedor
            ),
            modo_respuesta="texto",
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
