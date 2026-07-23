"""Webhook de WhatsApp Cloud API: mensajes de texto y audio."""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from inventory import resolver_destino_por_receptor_whatsapp
from models.database import Agencia, SessionLocal, Sucursal, Vendedor
from suscripcion_agencias import evaluar_agencia_para_operar
from whatsapp_config import whatsapp_phone_number_id, whatsapp_verify_token
from whatsapp_entrada import procesar_audio_whatsapp, procesar_texto_whatsapp
from whatsapp_linea import linea_envio_whatsapp_api, parece_celular_argentino

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp-webhook"])
_LOG_PREFIX = "[WEBHOOK WA]"


def _verificar_suscripcion_meta(
    hub_mode: str | None,
    hub_verify_token: str | None,
    hub_challenge: str | None,
) -> PlainTextResponse:
    """GET de Meta: devuelve hub.challenge si el verify token coincide."""
    esperado = whatsapp_verify_token()
    if hub_mode == "subscribe" and hub_verify_token == esperado:
        logger.info("Webhook WhatsApp verificado correctamente.")
        return PlainTextResponse(content=hub_challenge or "")
    logger.warning(
        "Verificación webhook rechazada (mode=%s, token_coincide=%s)",
        hub_mode,
        hub_verify_token == esperado,
    )
    raise HTTPException(status_code=403, detail="Token de verificación inválido.")


def _normalizar_phone_id(valor: str | None) -> str:
    if not valor:
        return ""
    return re.sub(r"\D", "", str(valor).strip())


def _avisos_formato_phone_number_id(phone_id: str) -> list[str]:
    """Detecta IDs con formato sospechoso (celular 549… vs Phone Number ID de Meta)."""
    avisos: list[str] = []
    crudo = (phone_id or "").strip()
    if not crudo:
        avisos.append("El phone_number_id está vacío.")
        return avisos

    if re.search(r"[A-Za-z]", crudo):
        avisos.append(
            f"El ID contiene letras ({crudo!r}). Meta suele enviar solo dígitos."
        )

    if re.search(r"[\s+()-]", crudo):
        avisos.append(
            f"El ID tiene espacios o símbolos ({crudo!r}). "
            "Compará la versión normalizada sin caracteres extra."
        )

    normalizado = _normalizar_phone_id(crudo)
    if normalizado.startswith("54") and len(normalizado) >= 11:
        avisos.append(
            f"El ID normalizado ({normalizado}) parece un número de celular argentino (549…), "
            "no un Phone Number ID de Meta. En la BD y al enviar mensajes debe ir el ID "
            "numérico de Meta (ej. 1086244571248216), no el 549…."
        )

    if normalizado and len(normalizado) < 10:
        avisos.append(
            f"El ID normalizado ({normalizado}) es muy corto para un Phone Number ID de Meta."
        )

    return avisos


def _imprimir_ids_registrados_en_bd(phone_id_buscado: str) -> None:
    """Lista IDs de la BD para comparar con el que llegó de Meta."""
    normalizado_buscado = _normalizar_phone_id(phone_id_buscado)
    db = SessionLocal()
    try:
        agencias = db.query(Agencia).order_by(Agencia.id).all()
        vendedores = db.query(Vendedor).order_by(Vendedor.id).all()
        sucursales = db.query(Sucursal).order_by(Sucursal.id).all()

        print(f"{_LOG_PREFIX} --- IDs registrados en base de datos ---")
        print(f"{_LOG_PREFIX} .env WHATSAPP_PHONE_NUMBER_ID = {whatsapp_phone_number_id()!r}")

        hallado_en_agencia = False
        hallado_en_equipo = False

        if not agencias:
            print(f"{_LOG_PREFIX} (sin agencias en la BD)")
        for ag in agencias:
            id_ag = (ag.whatsapp_phone_number_id or "").strip()
            norm_ag = _normalizar_phone_id(id_ag)
            coincide = (
                id_ag == phone_id_buscado
                or (normalizado_buscado and norm_ag == normalizado_buscado)
            )
            marca = " <-- COINCIDE" if coincide else ""
            if coincide:
                hallado_en_agencia = True
            print(
                f"{_LOG_PREFIX}   Agencia id={ag.id} nombre={ag.nombre!r} "
                f"whatsapp_phone_number_id={id_ag!r} normalizado={norm_ag!r}{marca}"
            )

        for ven in vendedores:
            tel = (ven.telefono_whatsapp or "").strip()
            norm_tel = _normalizar_phone_id(tel)
            coincide = (
                tel == phone_id_buscado
                or (normalizado_buscado and norm_tel == normalizado_buscado)
            )
            marca = " <-- COINCIDE (debería estar en la AGENCIA, no en el vendedor)" if coincide else ""
            if coincide:
                hallado_en_equipo = True
            print(
                f"{_LOG_PREFIX}   Vendedor id={ven.id} nombre={ven.nombre!r} "
                f"telefono_whatsapp={tel!r} normalizado={norm_tel!r}{marca}"
            )

        for suc in sucursales:
            tel = (suc.telefono_whatsapp or "").strip()
            norm_tel = _normalizar_phone_id(tel)
            coincide = (
                tel == phone_id_buscado
                or (normalizado_buscado and norm_tel == normalizado_buscado)
            )
            marca = " <-- COINCIDE (debería estar en la AGENCIA, no en la sucursal)" if coincide else ""
            if coincide:
                hallado_en_equipo = True
            print(
                f"{_LOG_PREFIX}   Sucursal id={suc.id} nombre={suc.nombre!r} "
                f"telefono_whatsapp={tel!r} normalizado={norm_tel!r}{marca}"
            )
        if hallado_en_equipo and not hallado_en_agencia:
            print(
                f"{_LOG_PREFIX} AVISO: el Phone Number ID está en vendedor/sucursal. "
                "El ruteo intentará auto-reparar moviéndolo a la agencia."
            )
        print(f"{_LOG_PREFIX} --- fin comparación BD ---")
    finally:
        db.close()


def _log_diagnostico_ruteo(
    phone_id_buscado: str,
    meta_metadata_id: str | None = None,
    fallback_url: str | None = None,
) -> None:
    """Logs explícitos para depurar por qué el bot no responde."""
    print(f"{_LOG_PREFIX} === Diagnóstico phone_number_id ===")
    print(
        f"{_LOG_PREFIX} ID recibido de Meta (metadata.phone_number_id) = "
        f"{meta_metadata_id!r}"
    )
    if fallback_url:
        print(f"{_LOG_PREFIX} Fallback ruta legacy (URL) = {fallback_url!r}")
    print(f"{_LOG_PREFIX} ID usado para buscar en BD = {phone_id_buscado!r}")
    print(
        f"{_LOG_PREFIX} ID normalizado para comparar = "
        f"{_normalizar_phone_id(phone_id_buscado)!r}"
    )

    if meta_metadata_id and str(meta_metadata_id).strip() != phone_id_buscado:
        print(
            f"{_LOG_PREFIX} AVISO: el ID de Meta ({meta_metadata_id!r}) difiere del ID "
            f"final usado ({phone_id_buscado!r}); se aplicó fallback .env/URL."
        )

    avisos = _avisos_formato_phone_number_id(phone_id_buscado)
    if meta_metadata_id and meta_metadata_id != phone_id_buscado:
        avisos.extend(_avisos_formato_phone_number_id(str(meta_metadata_id)))

    if avisos:
        print(f"{_LOG_PREFIX} Avisos de formato:")
        for aviso in avisos:
            print(f"{_LOG_PREFIX}   - {aviso}")
    else:
        print(f"{_LOG_PREFIX} Formato del ID: sin alertas.")

    _imprimir_ids_registrados_en_bd(phone_id_buscado)


def _log_resultado_ruteo(
    phone_id_buscado: str,
    agencia: Agencia | None,
    sucursal: Sucursal | None,
    vendedor: Vendedor | None,
) -> None:
    if agencia:
        print(
            f"{_LOG_PREFIX} RESULTADO: agencia ENCONTRADA → id={agencia.id} "
            f"nombre={agencia.nombre!r} "
            f"whatsapp_phone_number_id={agencia.whatsapp_phone_number_id!r}"
        )
        if sucursal:
            print(
                f"{_LOG_PREFIX}   Sucursal: id={sucursal.id} nombre={sucursal.nombre!r} "
                f"telefono_whatsapp={sucursal.telefono_whatsapp!r}"
            )
        if vendedor:
            print(
                f"{_LOG_PREFIX}   Vendedor: id={vendedor.id} nombre={vendedor.nombre!r} "
                f"telefono_whatsapp={vendedor.telefono_whatsapp!r}"
            )
        linea_envio = _linea_whatsapp_respuesta(
            agencia, sucursal, vendedor, phone_number_id_receptor=phone_id_buscado
        )
        print(f"{_LOG_PREFIX}   Línea que se usará para ENVIAR respuesta = {linea_envio!r}")
        if parece_celular_argentino(linea_envio):
            print(
                f"{_LOG_PREFIX}   AVISO ENVÍO: la línea parece celular 549…; "
                f"debe ser Phone Number ID de Meta."
            )
    else:
        print(
            f"{_LOG_PREFIX} RESULTADO: agencia NO ENCONTRADA para phone_id="
            f"{phone_id_buscado!r}. El bot no procesará ni responderá este mensaje."
        )
    print(f"{_LOG_PREFIX} === Fin diagnóstico ===")


def _linea_whatsapp_respuesta(
    agencia: Agencia,
    sucursal: Sucursal | None,
    vendedor: Vendedor | None = None,
    *,
    phone_number_id_receptor: str | None = None,
) -> str:
    return linea_envio_whatsapp_api(
        agencia,
        phone_number_id_receptor=phone_number_id_receptor,
        sucursal=sucursal,
        vendedor=vendedor,
    )


def _extraer_mensajes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mensajes: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            phone_id = (value.get("metadata") or {}).get("phone_number_id")
            for msg in value.get("messages", []):
                mensajes.append(
                    {
                        "phone_number_id": phone_id,
                        "from": msg.get("from"),
                        "type": msg.get("type"),
                        "id": msg.get("id"),
                        "text": (msg.get("text") or {}).get("body"),
                        "audio_id": (msg.get("audio") or {}).get("id"),
                    }
                )
    return mensajes


def _resolver_phone_number_id(msg: dict[str, Any], fallback: str | None = None) -> str:
    """Phone Number ID del mensaje (metadata) o fallback (.env / URL legacy)."""
    return (
        str(msg.get("phone_number_id") or "").strip()
        or (fallback or "").strip()
        or whatsapp_phone_number_id()
    )


def _procesar_un_mensaje(
    msg: dict[str, Any],
    phone_number_id: str,
    *,
    meta_metadata_id: str | None = None,
    fallback_url: str | None = None,
) -> dict[str, Any]:
    from whatsapp_idempotencia import liberar_lock_mensaje, reclamar_mensaje_whatsapp

    telefono = str(msg.get("from") or "")
    if not telefono:
        print(f"{_LOG_PREFIX} Mensaje sin teléfono remitente (from vacío).")
        return {"ok": False, "motivo": "sin_telefono"}

    wa_message_id = str(msg.get("id") or "").strip() or None
    if not reclamar_mensaje_whatsapp(wa_message_id):
        return {
            "ok": True,
            "duplicado": True,
            "motivo": "mensaje_ya_procesado",
            "whatsapp_message_id": wa_message_id,
        }

    try:
        resultado = _procesar_un_mensaje_interno(
            msg,
            phone_number_id,
            meta_metadata_id=meta_metadata_id,
            fallback_url=fallback_url,
            wa_message_id=wa_message_id,
        )
        # Si respondimos (aunque STT diga ok=False), no re-procesar el mismo wamid.
        liberar_lock_mensaje(wa_message_id)
        return resultado
    except Exception:
        from whatsapp_idempotencia import liberar_reclamo_si_fallo

        liberar_reclamo_si_fallo(wa_message_id)
        raise


def _procesar_un_mensaje_interno(
    msg: dict[str, Any],
    phone_number_id: str,
    *,
    meta_metadata_id: str | None = None,
    fallback_url: str | None = None,
    wa_message_id: str | None = None,
) -> dict[str, Any]:
    telefono = str(msg.get("from") or "")
    _log_diagnostico_ruteo(
        phone_number_id,
        meta_metadata_id=meta_metadata_id,
        fallback_url=fallback_url,
    )
    agencia, sucursal, vendedor = resolver_destino_por_receptor_whatsapp(phone_number_id)
    _log_resultado_ruteo(phone_number_id, agencia, sucursal, vendedor)

    if not agencia:
        logger.warning("Webhook WA sin agencia para phone_id=%s", phone_number_id)
        return {"ok": False, "motivo": "Agencia no encontrada", "phone_number_id": phone_number_id}

    linea_respuesta = _linea_whatsapp_respuesta(
        agencia, sucursal, vendedor, phone_number_id_receptor=phone_number_id
    )

    puede, mensaje_bloqueo = evaluar_agencia_para_operar(agencia.id)
    if not puede:
        from whatsapp import enviar_respuesta_bot

        if mensaje_bloqueo:
            enviar_respuesta_bot(
                telefono_destino=telefono,
                mensaje=mensaje_bloqueo,
                whatsapp_phone_number_id=linea_respuesta,
                modo_respuesta="texto",
                imprimir_texto_en_consola=False,
            )
        return {"ok": False, "bloqueado": True, "phone_number_id": phone_number_id}

    tipo = msg.get("type")
    if tipo == "text" and msg.get("text"):
        respuesta = procesar_texto_whatsapp(
            agencia,
            telefono,
            msg["text"],
            sucursal=sucursal,
            vendedor=vendedor,
            phone_number_id_meta=phone_number_id,
        )
        return {"ok": True, "tipo": "text", "respuesta": respuesta, "phone_number_id": phone_number_id}
    if tipo == "audio" and msg.get("audio_id"):
        resultado = procesar_audio_whatsapp(
            agencia=agencia,
            telefono=telefono,
            media_id=msg["audio_id"],
            whatsapp_message_id=wa_message_id or msg.get("id"),
            sucursal=sucursal,
            vendedor=vendedor,
            phone_number_id_meta=phone_number_id,
        )
        return {"ok": True, "tipo": "audio", "phone_number_id": phone_number_id, **resultado}
    return {"ok": True, "tipo": tipo, "ignorado": True, "phone_number_id": phone_number_id}


def _procesar_payload_webhook(
    payload: dict[str, Any],
    phone_number_id_fallback: str | None = None,
) -> dict[str, Any]:
    """Procesa el JSON completo que Meta envía por POST."""
    if payload.get("object") and payload.get("object") != "whatsapp_business_account":
        logger.debug("Webhook ignorado (object=%s)", payload.get("object"))
        return {"ok": True, "procesados": 0, "motivo": "object_no_whatsapp"}

    mensajes = _extraer_mensajes(payload)
    if not mensajes:
        # Meta también envía statuses (entregado/leído); no hay mensajes nuevos.
        print(
            f"{_LOG_PREFIX} POST sin mensajes nuevos (solo estados u otro evento). "
            f"object={payload.get('object')!r}"
        )
        return {"ok": True, "procesados": 0, "motivo": "sin_mensajes"}

    print(f"{_LOG_PREFIX} Mensajes entrantes a procesar: {len(mensajes)}")
    resultados = []
    for msg in mensajes:
        meta_id = msg.get("phone_number_id")
        phone_id = _resolver_phone_number_id(msg, phone_number_id_fallback)
        if not phone_id:
            print(
                f"{_LOG_PREFIX} ERROR: phone_number_id no configurado. "
                f"Meta metadata={meta_id!r}, fallback={phone_number_id_fallback!r}, "
                f".env={whatsapp_phone_number_id()!r}"
            )
            resultados.append({"ok": False, "motivo": "phone_number_id_no_configurado"})
            continue
        resultados.append(
            _procesar_un_mensaje(
                msg,
                phone_id,
                meta_metadata_id=str(meta_id) if meta_id is not None else None,
                fallback_url=phone_number_id_fallback,
            )
        )

    print(f"{_LOG_PREFIX} Resumen procesamiento: {resultados}")
    return {"ok": True, "procesados": len(resultados), "resultados": resultados}


@router.get("/webhook")
async def verificar_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """
    Validación inicial de Meta (Callback URL).
    Meta envía GET con hub.mode=subscribe y hub.verify_token.
    """
    return _verificar_suscripcion_meta(hub_mode, hub_verify_token, hub_challenge)


@router.post("/webhook")
async def recibir_webhook(request: Request):
    """Recibe notificaciones de WhatsApp (mensajes entrantes)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    logger.info("POST /webhook recibido (object=%s)", payload.get("object"))
    resultado = _procesar_payload_webhook(payload)
    print(f"{_LOG_PREFIX} POST /webhook finalizado → {resultado}")
    return resultado


@router.get("/webhook/whatsapp/{phone_number_id}")
async def verificar_webhook_whatsapp_legacy(
    phone_number_id: str,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Ruta legacy con phone_number_id en la URL (sigue soportada)."""
    return _verificar_suscripcion_meta(hub_mode, hub_verify_token, hub_challenge)


@router.post("/webhook/whatsapp/{phone_number_id}")
async def recibir_webhook_whatsapp_legacy(phone_number_id: str, request: Request):
    """Ruta legacy: usa phone_number_id de la URL solo como fallback."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    print(f"{_LOG_PREFIX} POST /webhook/whatsapp/{phone_number_id} (legacy)")
    return _procesar_payload_webhook(payload, phone_number_id_fallback=phone_number_id)
