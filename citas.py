import datetime
import re
import unicodedata

from models.database import Auto, Cita, ProspectoLead, SessionLocal

# Argentina no usa horario de verano desde 2009 (UTC-3 permanente).
ZONA_ARGENTINA = datetime.timezone(datetime.timedelta(hours=-3))

DIAS_SEMANA = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
}


def obtener_ahora_argentina() -> datetime.datetime:
    return datetime.datetime.now(ZONA_ARGENTINA)


def es_horario_madrugada(ahora: datetime.datetime | None = None) -> bool:
    momento = ahora or obtener_ahora_argentina()
    return 0 <= momento.hour < 6


def obtener_fecha_hoy_argentina(ahora: datetime.datetime | None = None) -> datetime.date:
    return (ahora or obtener_ahora_argentina()).date()


def _contexto_menciona_manana_como_dia(contexto: str) -> bool:
    if re.search(r"\b(voy manana|paso manana|el manana|para manana)\b", contexto):
        return True
    if re.search(r"\bmanana\b", contexto) and not re.search(r"a la manana|por la manana", contexto):
        return True
    if re.search(r"\bmañana\b", contexto) and not re.search(r"a la mañana|por la mañana", contexto):
        return True
    return False


def _resolver_fecha_manana(hoy: datetime.date, ahora: datetime.datetime | None = None) -> datetime.date:
    if es_horario_madrugada(ahora):
        return hoy
    return hoy + datetime.timedelta(days=1)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def detectar_visita(texto: str, historial: list[str] | None = None) -> bool:
    texto_norm = _normalizar(texto)
    contexto = _normalizar(" ".join((historial or [])[-4:]))

    claves_visita = [
        "voy a verlo",
        "voy a ver",
        "voy mañana",
        "voy manana",
        "paso hoy",
        "paso mañana",
        "paso manana",
        "ir a verlo",
        "ir a la agencia",
        "dale voy",
        "quiero verlo",
        "voy al local",
        "paso por",
        "voy a pasar",
        "nos vemos",
        "confirmo la visita",
        "agendado",
        "reservo turno",
        "quiero pasar",
    ]
    if any(c in texto_norm for c in claves_visita):
        return True

    claves_horario = ["a la tarde", "a la mañana", "a la manana", "por la tarde", "por la mañana"]
    tiene_horario = any(c in texto_norm for c in claves_horario)
    tiene_dia = any(
        d in texto_norm for d in ["hoy", "manana", "mañana", "lunes", "martes", "miercoles", "jueves", "viernes"]
    )
    tiene_hora_explicita = bool(
        _extraer_hora_explicita(texto_norm)
        or re.search(r"\b\d{1,2}(:\d{2})?\s*(hs|h|horas?)?\b", texto_norm)
    )

    if (tiene_horario or tiene_hora_explicita) and tiene_dia:
        return True

    if sesion_en_cierre_de_visita(contexto) and (tiene_horario or tiene_hora_explicita or tiene_dia):
        return True

    return False


def sesion_en_cierre_de_visita(contexto: str) -> bool:
    indicadores = [
        "mañana o a la tarde",
        "manana o a la tarde",
        "hoy o mañana",
        "hoy o manana",
        "coordinar",
        "visita",
        "turno",
        "agenda",
        "pasar a verlo",
        "veni a verlo",
    ]
    return any(i in contexto for i in indicadores)


def _ajustar_a_horario_laboral(fecha: datetime.date, hora: datetime.time) -> tuple[datetime.date, datetime.time]:
    while fecha.weekday() >= 5:
        fecha += datetime.timedelta(days=1)

    minutos = hora.hour * 60 + hora.minute

    if minutos < 9 * 60:
        return fecha, datetime.time(9, 0)
    if 13 * 60 <= minutos < 14 * 60:
        return fecha, datetime.time(14, 0)
    if minutos >= 18 * 60:
        fecha += datetime.timedelta(days=1)
        while fecha.weekday() >= 5:
            fecha += datetime.timedelta(days=1)
        return fecha, datetime.time(9, 0)

    return fecha, hora


def _proximo_dia_semana(desde: datetime.date, dia_objetivo: int) -> datetime.date:
    dias_adelante = (dia_objetivo - desde.weekday()) % 7
    if dias_adelante == 0:
        dias_adelante = 7
    return desde + datetime.timedelta(days=dias_adelante)


def _es_franja_horaria(texto_norm: str, inicio: int) -> bool:
    """True si el HH:MM en `inicio` forma parte de una franja tipo 09:00-13:00 / 09:00 a 13:00."""
    ventana = texto_norm[max(0, inicio - 8) : inicio + 24]
    return bool(
        re.search(
            r"\d{1,2}:\d{2}\s*(?:a|-|–|—|/|hasta)\s*\d{1,2}:\d{2}",
            ventana,
        )
    )


def _es_recordatorio_antes(texto_norm: str, inicio: int) -> bool:
    """True si el número es '1 hora antes' / 'N horas antes' (no hora de cita)."""
    ventana = texto_norm[inicio : inicio + 28]
    return bool(re.search(r"^\d{1,2}(?::\d{2})?\s*horas?\s+antes\b", ventana))


HORAS_EN_PALABRAS = {
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


def _hora_desde_token(token: str) -> int | None:
    token = (token or "").strip().lower()
    if token.isdigit():
        valor = int(token)
        return valor if 0 <= valor <= 23 else None
    # "dieciséis" ya normalizado pierde tilde → dieciseis
    return HORAS_EN_PALABRAS.get(token)


def _extraer_hora_explicita(texto_norm: str, *, solo_confirmacion: bool = False) -> datetime.time | None:
    """
    Extrae la hora de la cita en 24h.

    Prioriza 'a las 14', 'para las 10:00', 'para las catorce', '2pm', '2 de la tarde'.
    Ignora franjas de atención (09:00-13:00) y '1 hora antes'.
    """
    from formato_hora import interpretar_hora_12h_si_aplica

    token_hora = r"(\d{1,2}|" + "|".join(sorted(HORAS_EN_PALABRAS.keys(), key=len, reverse=True)) + r")"
    sufijo_ampm = r"(?:\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm))?"

    def _armar(horas_tok: str, minutos_tok: str | None, sufijo: str | None) -> datetime.time | None:
        horas = _hora_desde_token(horas_tok)
        if horas is None:
            return None
        minutos = int(minutos_tok or 0)
        return interpretar_hora_12h_si_aplica(horas, minutos, sufijo, texto_norm)

    # 0) 2pm / 2 p.m. / 2am (sin "a las")
    for match in re.finditer(
        rf"\b(\d{{1,2}})(?::(\d{{2}}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|am|pm)\b",
        texto_norm,
    ):
        hora = _armar(match.group(1), match.group(2), match.group(3))
        if hora:
            return hora

    # 1) Confirmaciones explícitas: "a las 10", "para las catorce", "tipo 10", "a las 2pm"
    for match in re.finditer(
        rf"(?:a las?|para las?|tipo)\s*{token_hora}(?::(\d{{2}}))?{sufijo_ampm}",
        texto_norm,
    ):
        if _es_recordatorio_antes(texto_norm, match.start(1)):
            continue
        hora = _armar(match.group(1), match.group(2), match.group(3) if match.lastindex and match.lastindex >= 3 else None)
        if hora:
            return hora

    if solo_confirmacion:
        for match in re.finditer(
            rf"(?:te esperamos|quedamos|quedo|qued[oó]|confirmad[oa]|cita|"
            rf"reprogram|cambiamos|pasamos|la dejamos|la dej[eé])\b.{{0,100}}?"
            rf"(?:a las?|para las?)\s*{token_hora}(?::(\d{{2}}))?{sufijo_ampm}",
            texto_norm,
        ):
            hora = _armar(match.group(1), match.group(2), match.group(3) if match.lastindex and match.lastindex >= 3 else None)
            if hora:
                return hora
        if re.search(r"\b(te esperamos|quedamos|cita|reprogram|cambiamos)\b", texto_norm):
            for match in re.finditer(
                rf"(?:a las?|para las?)\s*{token_hora}(?::(\d{{2}}))?{sufijo_ampm}",
                texto_norm,
            ):
                hora = _armar(match.group(1), match.group(2), match.group(3) if match.lastindex and match.lastindex >= 3 else None)
                if hora:
                    return hora
        return None

    # 2) HH:MM / N hs — pero NO franjas ni "N horas antes"
    for patron in (
        rf"(\d{{1,2}}):(\d{{2}})\s*(?:hs|h|horas?)?",
        rf"{token_hora}\s*(?:hs|horas)\b",
        rf"\b{token_hora}(?::(\d{{2}}))?\s*(?:hs|h|horas?)\b",
    ):
        for match in re.finditer(patron, texto_norm):
            if _es_franja_horaria(texto_norm, match.start(1)):
                continue
            if _es_recordatorio_antes(texto_norm, match.start(1)):
                continue
            minutos_tok = (
                match.group(2)
                if match.lastindex and match.lastindex >= 2 and match.group(2)
                else None
            )
            hora = _armar(match.group(1), minutos_tok, None)
            if hora:
                return hora
    return None


def _obtener_hora_acordada(texto: str, historial: list[str] | None = None) -> datetime.time | None:
    # 1) Mensaje actual del cliente
    hora = _extraer_hora_explicita(_normalizar(texto))
    if hora:
        return hora

    # 2) Mensajes previos del cliente (más recientes primero)
    for linea in reversed(historial or []):
        if not linea.startswith("Cliente:"):
            continue
        mensaje_cliente = linea.removeprefix("Cliente:").strip()
        hora = _extraer_hora_explicita(_normalizar(mensaje_cliente))
        if hora:
            return hora

    # 3) Confirmaciones del bot ("te esperamos a las 10"), nunca franjas 09:00-13:00
    for linea in reversed(historial or []):
        if not linea.startswith("Bot:"):
            continue
        mensaje_bot = linea.removeprefix("Bot:").strip()
        hora = _extraer_hora_explicita(_normalizar(mensaje_bot), solo_confirmacion=True)
        if hora:
            return hora

    return None


def _obtener_fecha_acordada(texto: str, historial: list[str] | None = None) -> datetime.date | None:
    contexto = _normalizar(" ".join((historial or [])[-8:] + [texto]))
    ahora = obtener_ahora_argentina()
    hoy = obtener_fecha_hoy_argentina(ahora)
    fecha: datetime.date | None = None

    if "pasado manana" in contexto:
        return hoy + datetime.timedelta(days=2)
    if "hoy" in contexto:
        return hoy
    if _contexto_menciona_manana_como_dia(contexto):
        return _resolver_fecha_manana(hoy, ahora)

    for nombre, numero in DIAS_SEMANA.items():
        if re.search(rf"\b{nombre}\b", contexto):
            return _proximo_dia_semana(hoy, numero)

    return fecha


def extraer_fecha_hora_cita(texto: str, historial: list[str] | None = None) -> tuple[datetime.date, datetime.time] | None:
    historial = historial or []
    contexto = _normalizar(" ".join(historial[-8:] + [texto]))
    ahora = obtener_ahora_argentina()
    hoy = obtener_fecha_hoy_argentina(ahora)

    fecha = _obtener_fecha_acordada(texto, historial)
    hora = _obtener_hora_acordada(texto, historial)

    if hora is None:
        if any(t in contexto for t in ["a la tarde", "por la tarde", "turno tarde"]):
            hora = datetime.time(15, 0)
        elif any(
            t in contexto
            for t in [
                "a la manana",
                "por la manana",
                "turno manana",
                "a la mañana",
                "por la mañana",
                "turno mañana",
            ]
        ):
            hora = datetime.time(10, 0)
        elif re.search(r"\btarde\b", contexto) and "manana o a la tarde" not in contexto and "mañana o a la tarde" not in contexto:
            hora = datetime.time(15, 0)

    if fecha is None and hora is not None and sesion_en_cierre_de_visita(contexto):
        fecha = hoy

    if fecha is None or hora is None:
        return None

    return _ajustar_a_horario_laboral(fecha, hora)


def _obtener_descripcion_auto(auto_id: int | None) -> str | None:
    if not auto_id:
        return None
    db = SessionLocal()
    try:
        auto = db.query(Auto).filter(Auto.id == auto_id).first()
        if not auto:
            return None
        return f"{auto.marca} {auto.modelo} {auto.version} ({auto.ano})"
    finally:
        db.close()


def asegurar_lead_id(
    agencia_id: int,
    telefono: str,
    nombre_cliente: str | None = None,
    apellido_cliente: str | None = None,
    auto_id: int | None = None,
    presupuesto: float | None = None,
    usado_marca_modelo: str | None = None,
    usado_ano: int | None = None,
    usado_km: int | None = None,
    usado_patente: str | None = None,
    usado_estado: str | None = None,
    usado_vtv_vigente: str | None = None,
    usado_es_titular: str | None = None,
    lead_id_existente: int | None = None,
    sucursal_id: int | None = None,
    vendedor_id: int | None = None,
) -> int:
    from inventory import guardar_lead_comercial

    return guardar_lead_comercial(
        agencia_id=agencia_id,
        telefono=telefono,
        auto_id=auto_id,
        presupuesto=presupuesto,
        nombre_cliente=nombre_cliente,
        apellido_cliente=apellido_cliente,
        usado_marca_modelo=usado_marca_modelo,
        usado_ano=usado_ano,
        usado_km=usado_km,
        usado_patente=usado_patente,
        usado_estado=usado_estado,
        usado_vtv_vigente=usado_vtv_vigente,
        usado_es_titular=usado_es_titular,
        lead_id=lead_id_existente,
        sucursal_id=sucursal_id,
        vendedor_id=vendedor_id,
    )


def guardar_cita(
    cliente_id: int,
    fecha_cita: datetime.date,
    hora_cita: datetime.time,
    auto_interes: str | None = None,
    sucursal_id: int | None = None,
    vendedor_id: int | None = None,
) -> int:
    from formato_hora import formatear_hora_24h

    db = SessionLocal()
    try:
        lead = db.query(ProspectoLead).filter(ProspectoLead.id == cliente_id).first()
        if sucursal_id is None and lead:
            sucursal_id = lead.sucursal_id
        if vendedor_id is None and lead:
            vendedor_id = getattr(lead, "vendedor_id", None)
        cita = Cita(
            cliente_id=cliente_id,
            sucursal_id=sucursal_id,
            vendedor_id=vendedor_id,
            fecha_cita=fecha_cita,
            hora_cita=formatear_hora_24h(hora_cita),
            auto_interes=auto_interes,
            estado="pendiente",
            recordatorio_enviado=False,
        )
        db.add(cita)
        db.commit()
        db.refresh(cita)
        return cita.id
    finally:
        db.close()


def actualizar_hora_cita(cita_id: int, fecha_cita: datetime.date, hora_cita: datetime.time) -> bool:
    """Actualiza fecha/hora si el cliente confirma un horario más preciso."""
    from formato_hora import formatear_hora_24h

    db = SessionLocal()
    try:
        cita = db.query(Cita).filter(Cita.id == cita_id).first()
        if not cita:
            return False
        nueva_hora = formatear_hora_24h(hora_cita)
        if cita.fecha_cita == fecha_cita and cita.hora_cita == nueva_hora:
            return False
        print(
            f"[CITAS] Actualizando cita id={cita_id}: "
            f"{cita.fecha_cita} {cita.hora_cita} → {fecha_cita} {nueva_hora}"
        )
        cita.fecha_cita = fecha_cita
        cita.hora_cita = nueva_hora
        # Si cambia el horario, permitir reenviar recordatorio.
        cita.recordatorio_enviado = False
        db.commit()
        return True
    finally:
        db.close()


def _buscar_cita_activa_sesion(sesion) -> Cita | None:
    """Busca la cita pendiente/confirmada del lead (o del teléfono) en BD."""
    db = SessionLocal()
    try:
        lead_id = getattr(sesion, "lead_id", None)
        if lead_id:
            cita = (
                db.query(Cita)
                .filter(
                    Cita.cliente_id == lead_id,
                    Cita.estado.in_(("pendiente", "confirmada")),
                )
                .order_by(Cita.id.desc())
                .first()
            )
            if cita:
                # Evitar DetachedInstance al cerrar sesión.
                db.expunge(cita)
                return cita

        lead = (
            db.query(ProspectoLead)
            .filter(
                ProspectoLead.agencia_id == sesion.agencia_id,
                ProspectoLead.telefono_cliente == sesion.telefono,
            )
            .order_by(ProspectoLead.id.desc())
            .first()
        )
        if not lead:
            return None
        sesion.lead_id = lead.id
        cita = (
            db.query(Cita)
            .filter(
                Cita.cliente_id == lead.id,
                Cita.estado.in_(("pendiente", "confirmada")),
            )
            .order_by(Cita.id.desc())
            .first()
        )
        if cita:
            db.expunge(cita)
        return cita
    finally:
        db.close()


def detectar_cambio_horario(texto: str) -> bool:
    """True si el cliente pide cambiar/reprogramar o da una hora explícita."""
    texto_norm = _normalizar(texto or "")
    if _extraer_hora_explicita(texto_norm):
        return True
    return bool(
        re.search(
            r"\b("
            r"cambi|reprogram|pasalo|pasala|pasarla|pasarlo|pasame|pasamos|pasar|"
            r"mejor a|otra hora|otro horario|en vez de|en lugar de|"
            r"antes a las|despues a las|después a las"
            r")\b",
            texto_norm,
        )
    )


def _extraer_fecha_hora_para_actualizar(
    texto: str,
    historial: list[str] | None,
    cita_actual: Cita | None,
) -> tuple[datetime.date, datetime.time] | None:
    """Como extraer_fecha_hora_cita, pero si falta fecha usa la de la cita existente."""
    fecha_hora = extraer_fecha_hora_cita(texto, historial)
    if fecha_hora:
        return fecha_hora

    hora = _obtener_hora_acordada(texto, historial)
    if hora is None:
        hora = _extraer_hora_explicita(_normalizar(texto))
    if hora is None:
        return None

    fecha = _obtener_fecha_acordada(texto, historial)
    if fecha is None and cita_actual is not None and cita_actual.fecha_cita:
        fecha = cita_actual.fecha_cita
    if fecha is None:
        fecha = obtener_fecha_hoy_argentina()
    return _ajustar_a_horario_laboral(fecha, hora)


def procesar_cita_si_corresponde(sesion) -> int | None:
    """
    Crea o actualiza la cita según el historial.

    Importante: si ya existe una cita en BD, cualquier hora nueva explícita
    ("a las 11", "cambiá a las 11") la actualiza aunque el bot solo lo diga
    en el chat.

    La hora del **cliente** gana siempre frente a la del bot (Gemini a veces
    repite la hora vieja al decir "listo").
    """
    ultimo_mensaje = ""
    ultimo_bot = ""
    for linea in reversed(sesion.historial):
        if not ultimo_mensaje and linea.startswith("Cliente:"):
            ultimo_mensaje = linea.removeprefix("Cliente:").strip()
        if not ultimo_bot and linea.startswith("Bot:"):
            ultimo_bot = linea.removeprefix("Bot:").strip()
        if ultimo_mensaje and ultimo_bot:
            break

    cita_existente = _buscar_cita_activa_sesion(sesion)
    if cita_existente:
        sesion.cita_registrada_id = cita_existente.id

    hora_cliente = _extraer_hora_explicita(_normalizar(ultimo_mensaje))
    quiere_visita = detectar_visita(ultimo_mensaje, sesion.historial)
    quiere_cambiar = bool(cita_existente) and (
        detectar_cambio_horario(ultimo_mensaje)
        or (not hora_cliente and detectar_cambio_horario(ultimo_bot))
    )

    if not quiere_visita and not quiere_cambiar:
        return sesion.cita_registrada_id

    # Priorizar SIEMPRE la hora explícita del cliente.
    texto_para_hora = ultimo_mensaje
    if not hora_cliente and quiere_cambiar:
        if _extraer_hora_explicita(_normalizar(ultimo_bot), solo_confirmacion=True):
            texto_para_hora = ultimo_bot

    # Al calcular, no dejar que el historial (hora vieja / reply del bot) pise
    # la hora que el cliente acaba de pedir.
    historial_para_hora = list(sesion.historial)
    if hora_cliente:
        historial_para_hora = [
            l for l in historial_para_hora if not l.startswith("Bot:")
        ][-6:]

    fecha_hora = _extraer_fecha_hora_para_actualizar(
        texto_para_hora, historial_para_hora, cita_existente
    )
    if not fecha_hora and quiere_cambiar and ultimo_bot and not hora_cliente:
        fecha_hora = _extraer_fecha_hora_para_actualizar(
            ultimo_bot, sesion.historial, cita_existente
        )
    if not fecha_hora:
        return sesion.cita_registrada_id

    fecha_cita, hora_cita = fecha_hora

    if sesion.cita_registrada_id:
        actualizar_hora_cita(sesion.cita_registrada_id, fecha_cita, hora_cita)
        return sesion.cita_registrada_id

    from inventory import resolver_sucursal_id_cita

    vendedor_id = getattr(sesion, "vendedor_origen_id", None)
    sucursal_cita_id = resolver_sucursal_id_cita(
        sesion.agencia_id,
        getattr(sesion, "sucursal_origen_id", None),
        sesion.auto_interes_id,
    )
    sesion.lead_id = asegurar_lead_id(
        agencia_id=sesion.agencia_id,
        telefono=sesion.telefono,
        nombre_cliente=sesion.nombre_cliente,
        apellido_cliente=sesion.apellido_cliente,
        auto_id=sesion.auto_interes_id,
        presupuesto=sesion.presupuesto,
        usado_marca_modelo=sesion.usado_marca_modelo,
        usado_ano=sesion.usado_ano,
        usado_km=sesion.usado_km,
        usado_patente=sesion.usado_patente,
        usado_estado=sesion.usado_estado,
        usado_vtv_vigente=sesion.usado_vtv_vigente,
        usado_es_titular=sesion.usado_es_titular,
        lead_id_existente=sesion.lead_id,
        sucursal_id=getattr(sesion, "sucursal_origen_id", None),
        vendedor_id=vendedor_id,
    )
    from conversaciones import vincular_mensajes_a_lead

    vincular_mensajes_a_lead(sesion.agencia_id, sesion.telefono, sesion.lead_id)

    auto_interes = _obtener_descripcion_auto(sesion.auto_interes_id)
    cita_id = guardar_cita(
        cliente_id=sesion.lead_id,
        fecha_cita=fecha_cita,
        hora_cita=hora_cita,
        auto_interes=auto_interes,
        sucursal_id=sucursal_cita_id,
        vendedor_id=vendedor_id,
    )
    sesion.cita_registrada_id = cita_id
    return cita_id
