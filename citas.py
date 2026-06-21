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
        "pasame la direccion",
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
    tiene_hora_explicita = bool(re.search(r"\b\d{1,2}(:\d{2})?\s*(hs|h|horas?)?\b", texto_norm))

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


def _extraer_hora_explicita(texto_norm: str) -> datetime.time | None:
    patrones = [
        r"(?:a las?|para las?|tipo)\s*(\d{1,2})(?::(\d{2}))?",
        r"(\d{1,2}):(\d{2})\s*(?:hs|h|horas?)?",
        r"(\d{1,2})\s*(?:hs|horas)\b",
        r"\b(\d{1,2})(?::(\d{2}))?\s*(?:hs|h|horas?)\b",
    ]
    for patron in patrones:
        match = re.search(patron, texto_norm)
        if not match:
            continue
        horas = int(match.group(1))
        minutos = int(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else 0
        if 0 <= horas <= 23 and 0 <= minutos <= 59:
            return datetime.time(horas, minutos)
    return None


def _obtener_hora_acordada(texto: str, historial: list[str] | None = None) -> datetime.time | None:
    hora = _extraer_hora_explicita(_normalizar(texto))
    if hora:
        return hora

    for linea in reversed(historial or []):
        if not linea.startswith("Cliente:"):
            continue
        mensaje_cliente = linea.removeprefix("Cliente:").strip()
        hora = _extraer_hora_explicita(_normalizar(mensaje_cliente))
        if hora:
            return hora

    for linea in reversed(historial or []):
        if not linea.startswith("Bot:"):
            continue
        mensaje_bot = linea.removeprefix("Bot:").strip()
        hora = _extraer_hora_explicita(_normalizar(mensaje_bot))
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
            for t in ["a la mañana", "por la mañana", "por la manana", "turno mañana", "turno manana"]
        ):
            hora = datetime.time(10, 0)
        elif re.search(r"\btarde\b", contexto) and "mañana o a la tarde" not in contexto:
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
            hora_cita=hora_cita.strftime("%H:%M"),
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


def procesar_cita_si_corresponde(sesion) -> int | None:
    if sesion.cita_registrada_id:
        return sesion.cita_registrada_id

    ultimo_mensaje = ""
    for linea in reversed(sesion.historial):
        if linea.startswith("Cliente:"):
            ultimo_mensaje = linea.removeprefix("Cliente:").strip()
            break

    if not detectar_visita(ultimo_mensaje, sesion.historial):
        return None

    fecha_hora = extraer_fecha_hora_cita(ultimo_mensaje, sesion.historial)
    if not fecha_hora:
        return None

    fecha_cita, hora_cita = fecha_hora
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
