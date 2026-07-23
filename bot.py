import logging
logger = logging.getLogger("bot")
import datetime
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from citas import (
    _buscar_cita_activa_sesion,
    _extraer_fecha_hora_para_actualizar,
    _extraer_hora_explicita,
    _normalizar as _normalizar_cita,
    actualizar_hora_cita,
    detectar_cambio_horario,
    detectar_visita,
    es_horario_madrugada,
    obtener_ahora_argentina,
    obtener_fecha_hoy_argentina,
    procesar_cita_si_corresponde,
)
from conversaciones import guardar_mensaje, vincular_mensajes_a_lead
from suscripcion_agencias import evaluar_agencia_para_operar
from inventory import (
    buscar_autos_por_texto,
    cliente_en_cierre_sin_fotos,
    cliente_pide_fotos,
    cliente_pide_mas_fotos,
    formatear_fotos_para_whatsapp,
    formatear_opciones_stock_cruzado,
    guardar_lead_comercial,
    limpiar_placeholders_imagen_en_texto,
    listar_origenes_fotos_auto,
    obtener_auto_por_id,
    obtener_inventario_agencia,
    obtener_nombre_sucursal,
)
from models.database import Agencia, SessionLocal, inicializar_base_de_datos
from whatsapp import enviar_imagen_whatsapp, enviar_respuesta_bot
from whatsapp_linea import linea_envio_whatsapp_api
from permuta import (
    INSTRUCCIONES_PERMUTA,
    extraer_datos_usado_en_segundo_plano,
    resumen_usado_sesion,
)
from personalizacion_bot import (
    mensaje_bienvenida_agencia,
    obtener_direccion_bot,
    obtener_nombre_agencia_bot,
    obtener_nombre_bot,
    obtener_sucursal,
    obtener_telefono_contacto_bot,
    obtener_vendedor,
)
from prompts import generar_prompt_maestro

load_dotenv()

_gemini_client: genai.Client | None = None
_BACKOFF_INICIAL_SEG = 2
_MAX_REINTENTOS_429 = 2
_HTTP_SIN_REINTENTOS_SDK = types.HttpOptions(
    retry_options=types.HttpRetryOptions(attempts=1),
)

_DIAS_ES = (
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
)
_MESES_ES = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)
_DIAS_LABORALES = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
}

_SALUDOS = frozenset({
    "hola", "holaa", "holaaa", "buenas", "buendia", "buenosdias",
    "buenastardes", "buenasnoches", "quetal", "hey", "hi", "hello",
    "comoestas", "comoandas", "saludos", "quehubo", "qhubo", "buen",
    "dia", "dias", "tardes", "noches", "que", "tal", "como", "andas", "estas",
})

_FRASES_SOLO_SALUDO = (
    "hola",
    "buenas",
    "buen dia",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "que tal",
    "como estas",
    "como andas",
    "hey",
    "saludos",
)

_PALABRAS_CONSULTA = frozenset({
    "quiero", "busco", "necesito", "precio", "presupuesto", "ver", "verlo",
    "permuta", "usado", "auto", "coche", "vehiculo", "modelo", "financiacion",
    "info", "informacion", "catalogo", "stock", "disponible", "interesa",
    "voro", "bora", "vora", "cronos", "nivus", "fiat", "volkswagen", "vw",
})

_CONECTORES_CONSULTA = frozenset({"y", "e"})

_PALABRAS_EVASION = frozenset({
    "no", "na", "nop", "nada", "ninguno", "ninguna", "si", "sí", "ok", "okay",
    "dale", "bueno", "gracias", "paso", "skip", "hola", "holaa", "buenas", "hey",
    "vos", "vos?", "mmm", "mm", "ah", "eh", "ya", "listo",
})

_FRASES_EVASION_NOMBRE = (
    "quiero ver un auto",
    "quiero un auto",
    "ver un auto",
    "ver autos",
    "quiero verlo",
    "me interesa un auto",
)

_MENSAJE_PEDIR_NOMBRE_REAL = (
    "Por favor, decime tu nombre real para poder registrarte correctamente."
)


@dataclass
class PresentacionCliente:
    nombre: str | None = None
    apellido: str | None = None
    nombre_valido: bool = False
    es_solo_saludo: bool = False
    tiene_consulta_comercial: bool = False
    mensaje_para_continuar: str | None = None


@dataclass
class SesionCliente:
    agencia_id: int
    telefono: str
    nombre_cliente: str | None = None
    apellido_cliente: str | None = None
    auto_interes_id: int | None = None
    presupuesto: float | None = None
    usado_marca_modelo: str | None = None
    usado_ano: int | None = None
    usado_km: int | None = None
    usado_patente: str | None = None
    usado_estado: str | None = None
    usado_vtv_vigente: str | None = None
    usado_es_titular: str | None = None
    interes_alto: bool = False
    quiere_permuta: bool = False
    lead_id: int | None = None
    cita_registrada_id: int | None = None
    sucursal_origen_id: int | None = None
    vendedor_origen_id: int | None = None
    line_whatsapp_id: str | None = None
    cuota_diaria_agotada: bool = False
    # Autos a los que ya se les envió el álbum en esta conversación (anti-loop).
    autos_con_fotos_enviadas: set[int] = field(default_factory=set)
    # Si el último mensaje entrante fue audio → responder en voz (espejo).
    entrada_fue_audio: bool = False
    historial: list[str] = field(default_factory=list)


def _persistir_mensaje(sesion: SesionCliente, rol: str, texto: str) -> None:
    guardar_mensaje(
        agencia_id=sesion.agencia_id,
        telefono=sesion.telefono,
        rol=rol,
        contenido=texto,
        lead_id=sesion.lead_id,
    )


def _entregar_respuesta_whatsapp(
    agencia: Agencia,
    telefono: str,
    texto: str,
    via_whatsapp: bool = False,
    sesion: SesionCliente | None = None,
) -> None:
    """Muestra la respuesta en consola y/o la envía por WhatsApp (una sola modalidad)."""
    from formato_hora import normalizar_horas_mensaje_24h

    # Gemini a veces dice "2 hs"; forzamos 14:00 hs en texto y en el audio.
    texto = normalizar_horas_mensaje_24h(texto or "")

    if not via_whatsapp:
        print("\nBot:", texto)
    sucursal = _sucursal_sesion_bot(sesion) if sesion else None
    vendedor = _vendedor_sesion_bot(sesion) if sesion else None
    line_id = linea_envio_whatsapp_api(
        agencia,
        phone_number_id_receptor=sesion.line_whatsapp_id if sesion else None,
        sucursal=sucursal,
        vendedor=vendedor,
    )
    # UNA sola entrega por turno (nunca texto+audio juntos: molesta y duplica).
    # Audio in → solo voz. Texto in → texto (o voz si la agencia está en "voz").
    modo_agencia = (agencia.modo_respuesta or "texto").strip().lower()
    if sesion and sesion.entrada_fue_audio:
        modo = "voz"
    elif modo_agencia == "voz":
        modo = "voz"
    else:
        # "texto" y "ambas" → una sola respuesta en texto cuando el cliente escribió.
        modo = "texto"

    enviar_respuesta_bot(
        telefono_destino=telefono,
        mensaje=texto,
        whatsapp_phone_number_id=line_id,
        modo_respuesta=modo,
        imprimir_texto_en_consola=not via_whatsapp,
    )


def _base_url_publica() -> str:
    for nombre in ("DASHBOARD_BASE_URL", "APP_URL", "FRONTEND_URL"):
        valor = os.getenv(nombre, "").strip().rstrip("/")
        if valor:
            return valor
    return "http://127.0.0.1:8080"


def _enviar_fotos_auto_whatsapp(
    agencia: Agencia,
    telefono: str,
    auto,
    sesion: SesionCliente | None = None,
) -> int:
    """Envía fotos reales del auto por WhatsApp. Devuelve cuántas se enviaron."""
    origenes = listar_origenes_fotos_auto(auto, base_url=_base_url_publica())
    if not origenes:
        return 0

    line_id = linea_envio_whatsapp_api(
        agencia,
        phone_number_id_receptor=sesion.line_whatsapp_id if sesion else None,
        sucursal=_sucursal_sesion_bot(sesion) if sesion else None,
        vendedor=_vendedor_sesion_bot(sesion) if sesion else None,
    )
    enviadas = 0
    for idx, origen in enumerate(origenes):
        caption = ""
        if idx == 0:
            caption = f"{auto.marca} {auto.modelo} {auto.ano}".strip()
        # Si no hay archivo local, intentar URL pública absoluta.
        destino = origen
        if origen.startswith("/") and not origen.startswith("//"):
            local_ok = origen  # enviar_imagen resuelve /static/...
            destino = local_ok
        ok = enviar_imagen_whatsapp(
            telefono_destino=telefono,
            imagen_url_o_ruta=destino,
            whatsapp_phone_number_id=line_id,
            caption=caption,
        )
        if not ok and origen.startswith("/"):
            # Fallback: link público por si el archivo no está en este filesystem.
            url_publica = f"{_base_url_publica()}{origen}"
            ok = enviar_imagen_whatsapp(
                telefono_destino=telefono,
                imagen_url_o_ruta=url_publica,
                whatsapp_phone_number_id=line_id,
                caption=caption,
            )
        if ok:
            enviadas += 1
    return enviadas


def _formatear_fecha_es(fecha: datetime.date) -> str:
    return f"{_DIAS_ES[fecha.weekday()]} {fecha.day} de {_MESES_ES[fecha.month - 1]} de {fecha.year}"


def _proxima_fecha_dia_semana(desde: datetime.date, dia_objetivo: int) -> datetime.date:
    dias_adelante = (dia_objetivo - desde.weekday()) % 7
    if dias_adelante == 0:
        dias_adelante = 7
    return desde + datetime.timedelta(days=dias_adelante)


def _generar_contexto_temporal() -> str:
    ahora = obtener_ahora_argentina()
    hoy = obtener_fecha_hoy_argentina(ahora)
    manana_calendario = hoy + datetime.timedelta(days=1)
    pasado_manana = hoy + datetime.timedelta(days=2)
    madrugada = es_horario_madrugada(ahora)
    fecha_hoy_texto = _formatear_fecha_es(hoy)

    lineas = [
        "CONTEXTO TEMPORAL (ancla obligatoria para agendar visitas):",
        f"Fecha y día de hoy: {fecha_hoy_texto}.",
        f"Hora actual en Argentina: {ahora.strftime('%H:%M')}.",
    ]

    if madrugada:
        lineas.extend([
            f"ATENCIÓN — MADRUGADA: El cliente está hablando de madrugada ({ahora.strftime('%H:%M')} hs Argentina).",
            (
                f"Si dice 'mañana', se refiere a HOY MISMO por la mañana ({fecha_hoy_texto}), "
                f"NO al día calendario siguiente ({_formatear_fecha_es(manana_calendario)})."
            ),
            (
                f"Ejemplo: ahora es {fecha_hoy_texto} a las {ahora.strftime('%H:%M')}; "
                f"'voy mañana' = visita hoy {fecha_hoy_texto} en horario de mañana (09:00-13:00)."
            ),
            (
                f"'Mañana' del cliente en madrugada = HOY ({fecha_hoy_texto}). "
                f"Confirmá con repregunta antes de agendar."
            ),
        ])
    else:
        lineas.append(f"Mañana (día calendario siguiente): {_formatear_fecha_es(manana_calendario)}.")

    lineas.extend([
        f"Pasado mañana: {_formatear_fecha_es(pasado_manana)}.",
        "Próxima ocurrencia de cada día laboral:",
    ])

    for nombre, numero in _DIAS_LABORALES.items():
        if nombre == "miercoles":
            continue
        proxima = _proxima_fecha_dia_semana(hoy, numero)
        lineas.append(f"- Próximo {nombre}: {_formatear_fecha_es(proxima)}.")

    if madrugada:
        lineas.append(
            "Regla madrugada: si el cliente dice 'mañana', validá con repregunta vendedora "
            f"(ej: '¡Dale! Te referís a venir hoy mismo {fecha_hoy_texto} a la mañana, ¿no? "
            "Confirmame y ya te reservo el lugar'). No pases la visita al día siguiente sin confirmar."
        )
    else:
        lineas.append(
            "Regla: interpretá 'mañana' como el día siguiente a hoy; "
            "'el lunes/martes/...' como la próxima ocurrencia de ese día; "
            "'el próximo viernes' (u otro día) como la ocurrencia de ese día en la semana siguiente "
            "si el de esta semana ya pasó o es hoy. Siempre confirmá la fecha civil exacta al cliente."
        )
    return "\n".join(lineas)


def _respuesta_si_agencia_bloqueada(agencia_id: int) -> str | None:
    puede, mensaje = evaluar_agencia_para_operar(agencia_id)
    return mensaje if not puede else None


def _obtener_agencia(agencia_id: int) -> Agencia | None:
    db = SessionLocal()
    try:
        return db.query(Agencia).filter(Agencia.id == agencia_id).first()
    finally:
        db.close()


def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _extraer_presupuesto(texto: str) -> float | None:
    texto_norm = _normalizar_texto(texto).replace(",", ".")
    min_valido = 500_000

    def _aceptar(valor: float | None) -> float | None:
        if valor is None or valor < min_valido:
            return None
        return valor

    if "millon" in texto_norm:
        numeros = re.findall(r"\d+", texto_norm)
        if numeros:
            return _aceptar(float(numeros[0]) * 1_000_000)

    if re.fullmatch(r"\d{1,2}\.\d{3}\.\d{2}", texto_norm):
        return _aceptar(float(texto_norm.split(".")[0]) * 1_000_000)

    match = re.search(r"\d{1,3}(?:\.\d{3})+|\d+(?:\.\d+)?", texto_norm)
    if match:
        raw = match.group(0)
        if raw.count(".") >= 2:
            partes = raw.split(".")
            if len(partes[-1]) <= 2:
                raw = "".join(partes[:-1])
            else:
                raw = raw.replace(".", "")
        elif raw.count(".") == 1 and len(raw.split(".")[-1]) == 3:
            raw = raw.replace(".", "")
        return _aceptar(float(raw))

    numeros = re.findall(r"\d+", texto_norm)
    if not numeros:
        return None

    valor = float(numeros[0])
    if valor < 1_000_000:
        valor *= 1_000_000
    return _aceptar(valor)


def _extraer_nombre_apellido(texto: str) -> tuple[str | None, str | None]:
    partes = [p for p in texto.strip().split() if p]
    if not partes:
        return None, None
    if len(partes) == 1:
        return partes[0].title(), None
    return partes[0].title(), " ".join(p.title() for p in partes[1:])


def _limpiar_texto_presentacion(texto: str) -> str:
    return re.sub(r"[!?.,;:]+$", "", texto.strip()).strip()


def _tiene_consulta_comercial(texto_norm: str) -> bool:
    palabras = set(texto_norm.split())
    if palabras & _PALABRAS_CONSULTA:
        return True
    return any(
        marca in texto_norm
        for marca in ["bora", "cronos", "nivus", "fiat", "volkswagen", "vw"]
    )


def _es_solo_saludo(texto_norm: str) -> bool:
    texto = texto_norm.strip()
    if not texto:
        return False
    if texto.replace(" ", "") in _SALUDOS:
        return True
    for frase in _FRASES_SOLO_SALUDO:
        if texto == frase:
            return True
    palabras = texto.split()
    if len(palabras) <= 2 and palabras[0] in {"hola", "buenas", "hey", "saludos"}:
        return not _tiene_consulta_comercial(texto)
    return False


def _parece_nombre_propio(nombre: str | None, texto_completo: str = "") -> bool:
    if not nombre:
        return False
    norm = _normalizar_texto(nombre)
    if norm in _PALABRAS_EVASION or norm in _SALUDOS or norm in _PALABRAS_CONSULTA:
        return False
    if nombre.isdigit():
        return False
    if not re.match(r"^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ'-]+$", nombre):
        return False

    texto_norm = _normalizar_texto(_limpiar_texto_presentacion(texto_completo))
    palabras_entrada = texto_norm.split()
    if len(palabras_entrada) == 1 and len(norm) < 3:
        return False
    return True


def _es_entrada_nombre_invalida(texto: str) -> bool:
    texto_limpio = _limpiar_texto_presentacion(texto)
    if not texto_limpio:
        return True

    texto_norm = _normalizar_texto(texto_limpio)
    if _es_solo_saludo(texto_norm):
        return True
    if _tiene_consulta_comercial(texto_norm):
        return False

    for frase in _FRASES_EVASION_NOMBRE:
        if texto_norm == frase or frase in texto_norm:
            return True

    palabras = texto_norm.split()
    if len(palabras) == 1:
        return len(palabras[0]) < 3 or palabras[0] in _PALABRAS_EVASION
    if palabras and all(palabra in _PALABRAS_EVASION for palabra in palabras):
        return True
    return False


def _separar_nombre_y_consulta(fragmento: str) -> tuple[str | None, str | None, str | None]:
    palabras = fragmento.split()
    nombre_partes: list[str] = []
    consulta_partes: list[str] = []
    en_consulta = False

    for indice, palabra in enumerate(palabras):
        palabra_limpia = palabra.strip(",.;:!?")
        palabra_norm = _normalizar_texto(palabra_limpia)
        if not palabra_norm:
            continue

        if not en_consulta and palabra_norm in _CONECTORES_CONSULTA:
            if indice + 1 < len(palabras):
                siguiente = _normalizar_texto(palabras[indice + 1].strip(",.;:!?"))
                if siguiente in _PALABRAS_CONSULTA:
                    en_consulta = True
            continue

        if not en_consulta and palabra_norm in _PALABRAS_CONSULTA:
            en_consulta = True

        if en_consulta:
            consulta_partes.append(palabra_limpia)
        elif palabra_norm not in _SALUDOS and not palabra_norm.isdigit():
            nombre_partes.append(palabra_limpia)

    if not nombre_partes:
        return None, None, fragmento.strip() or None

    nombre, apellido = _extraer_nombre_apellido(" ".join(nombre_partes))
    consulta = " ".join(consulta_partes).strip() or None
    return nombre, apellido, consulta


def _extraer_nombre_de_presentacion(texto: str) -> tuple[str | None, str | None, str | None]:
    texto_limpio = _limpiar_texto_presentacion(texto)
    texto_norm = _normalizar_texto(texto_limpio)

    for patron in (
        r"(?:me llamo|mi nombre es)\s+(.+)$",
        r"soy\s+(.+)$",
    ):
        coincidencia = re.search(patron, texto_norm)
        if coincidencia:
            return _separar_nombre_y_consulta(coincidencia.group(1).strip())

    resto = texto_norm
    for saludo in ("hola", "buenas", "hey", "que tal", "buen dia", "buenos dias"):
        if resto.startswith(saludo):
            resto = resto[len(saludo):].strip(" ,.!")
            break

    if resto.startswith("soy "):
        return _separar_nombre_y_consulta(resto[4:].strip())

    if _tiene_consulta_comercial(texto_norm):
        if len(texto_norm.split()) == 1:
            return None, None, texto_limpio
        return None, None, texto_limpio

    nombre, apellido = _extraer_nombre_apellido(texto_limpio)
    if nombre and _normalizar_texto(nombre) in _PALABRAS_CONSULTA:
        return None, None, texto_limpio
    return nombre, apellido, None


def _interpretar_presentacion(texto: str) -> PresentacionCliente:
    texto_limpio = _limpiar_texto_presentacion(texto)
    if not texto_limpio:
        return PresentacionCliente()

    texto_norm = _normalizar_texto(texto_limpio)
    tiene_consulta = _tiene_consulta_comercial(texto_norm)

    if _es_solo_saludo(texto_norm):
        return PresentacionCliente(es_solo_saludo=True)

    nombre, apellido, resto = _extraer_nombre_de_presentacion(texto_limpio)
    if nombre and _parece_nombre_propio(nombre, texto_limpio):
        mensaje_continuar = resto or (texto_limpio if tiene_consulta else None)
        return PresentacionCliente(
            nombre=nombre,
            apellido=apellido,
            nombre_valido=True,
            tiene_consulta_comercial=tiene_consulta,
            mensaje_para_continuar=mensaje_continuar,
        )

    return PresentacionCliente(
        tiene_consulta_comercial=tiene_consulta,
        mensaje_para_continuar=texto_limpio if tiene_consulta else None,
    )


def _sucursal_sesion_bot(sesion: SesionCliente) -> object | None:
    return obtener_sucursal(sesion.agencia_id, sesion.sucursal_origen_id)


def _vendedor_sesion_bot(sesion: SesionCliente) -> object | None:
    return obtener_vendedor(sesion.agencia_id, sesion.vendedor_origen_id)


def _armar_datos_ubicacion(agencia: Agencia, sesion: SesionCliente) -> str:
    sucursal = _sucursal_sesion_bot(sesion)
    direccion = obtener_direccion_bot(agencia, sucursal)
    telefono = obtener_telefono_contacto_bot(agencia)
    nombre_suc = ""
    if sesion.sucursal_origen_id:
        nombre_suc = obtener_nombre_sucursal(sesion.agencia_id, sesion.sucursal_origen_id)
    lineas = ["DATOS DE UBICACIÓN (OBLIGATORIOS — no inventar nada fuera de esto):"]
    if nombre_suc:
        lineas.append(f"- Sucursal de contacto: {nombre_suc}")
    if direccion:
        lineas.append(f"- Dirección oficial: {direccion}")
    else:
        lineas.append(
            "- Dirección oficial: NO CARGADA. Decile que un asesor se la confirma; "
            "PROHIBIDO inventar calles o números."
        )
    if telefono:
        lineas.append(f"- Teléfono de contacto: {telefono}")
    return "\n".join(lineas)


_PATRON_PEDIDO_DIRECCION = re.compile(
    r"\b("
    r"direcci[oó]n|ubicaci[oó]n|donde\s+quedan|donde\s+est[aá]n|"
    r"donde\s+queda|donde\s+est[aá]|como\s+lleg[oa]|c[oó]mo\s+lleg[oa]|"
    r"donde\s+los\s+encuentro|domicilio|mapa"
    r")\b",
    re.IGNORECASE,
)


def cliente_pide_direccion(texto: str) -> bool:
    return bool(_PATRON_PEDIDO_DIRECCION.search(texto or ""))


def _respuesta_direccion_agencia(agencia: Agencia, sesion: SesionCliente) -> str:
    sucursal = _sucursal_sesion_bot(sesion)
    direccion = obtener_direccion_bot(agencia, sucursal)
    nombre_agencia = obtener_nombre_agencia_bot(agencia, sucursal)
    nombre_suc = ""
    if sesion.sucursal_origen_id:
        nombre_suc = obtener_nombre_sucursal(sesion.agencia_id, sesion.sucursal_origen_id)

    if direccion:
        sede = f" ({nombre_suc})" if nombre_suc else ""
        return (
            f"Dale, {nombre_agencia}{sede} está en *{direccion}*. "
            "¡Te esperamos!"
        )
    return (
        f"Todavía no tengo la dirección cargada de {nombre_agencia} en el sistema. "
        "Un asesor te la confirma en un momento."
    )


def _respuesta_rapida_reprogramacion(
    sesion: SesionCliente,
    agencia: Agencia,
    texto: str,
) -> str | None:
    """
    Si el cliente solo pide cambiar la hora de una cita existente, actualiza la BD
    y responde corto (sin Gemini): evita disculpas largas y hora inventada.
    """
    if not detectar_cambio_horario(texto):
        return None
    if _tiene_consulta_comercial(_normalizar_texto(texto)):
        return None

    hora = _extraer_hora_explicita(_normalizar_cita(texto))
    if hora is None:
        return None

    cita = _buscar_cita_activa_sesion(sesion)
    if not cita:
        return None

    fecha_hora = _extraer_fecha_hora_para_actualizar(texto, sesion.historial, cita)
    if not fecha_hora:
        return None

    fecha_cita, hora_cita = fecha_hora
    actualizar_hora_cita(cita.id, fecha_cita, hora_cita)
    sesion.cita_registrada_id = cita.id

    dia = _DIAS_ES[fecha_cita.weekday()]
    mes = _MESES_ES[fecha_cita.month - 1]
    fecha_txt = f"{dia} {fecha_cita.day} de {mes}"
    from formato_hora import formatear_hora_24h

    hora_txt = formatear_hora_24h(hora_cita)

    sucursal = _sucursal_sesion_bot(sesion)
    direccion = obtener_direccion_bot(agencia, sucursal)
    extra = f" en {direccion}" if direccion else ""
    return (
        f"Listo, tu visita quedó para el {fecha_txt} a las {hora_txt} hs{extra}. "
        "Te esperamos."
    )


def _enviar_bienvenida_inicial(
    sesion: SesionCliente,
    agencia: Agencia,
    via_whatsapp: bool = False,
) -> bool:
    """Saludo personalizado al iniciar conversación (solo si no hay historial)."""
    if sesion.historial:
        return False
    sucursal = _sucursal_sesion_bot(sesion)
    vendedor = _vendedor_sesion_bot(sesion)
    mensaje = mensaje_bienvenida_agencia(agencia, sucursal, vendedor)
    sesion.historial.append(f"Bot: {mensaje}")
    _persistir_mensaje(sesion, "bot", mensaje)
    _entregar_respuesta_whatsapp(
        agencia, sesion.telefono, mensaje, via_whatsapp=via_whatsapp, sesion=sesion
    )
    return True


def _responder_captura_nombre(
    agencia: Agencia,
    presentacion: PresentacionCliente,
) -> str:
    if presentacion.es_solo_saludo:
        return (
            f"{mensaje_bienvenida_agencia(agencia)} "
            "¿Me decís tu nombre y apellido así te registro y seguimos?"
        )
    if presentacion.tiene_consulta_comercial:
        return (
            "¡Dale, te ayudo con eso enseguida! "
            "Antes de seguir, ¿me pasás tu nombre y apellido?"
        )
    return (
        "Para atenderte mejor necesito registrarte. "
        "¿Me decís tu nombre y apellido?"
    )


def _mensaje_transicion_gemini(
    presentacion: PresentacionCliente,
    ultimo_mensaje: str,
) -> str:
    if presentacion.mensaje_para_continuar:
        return presentacion.mensaje_para_continuar
    return ultimo_mensaje


def _nombre_para_saludo(sesion: SesionCliente) -> str:
    if sesion.nombre_cliente and sesion.apellido_cliente:
        return f"{sesion.nombre_cliente} {sesion.apellido_cliente}"
    if sesion.nombre_cliente:
        return sesion.nombre_cliente
    return ""


def _normalizar_telefono(texto: str) -> str:
    return re.sub(r"[\s\-]+", "", texto.strip())


def _validar_telefono(texto: str) -> str | None:
    telefono = _normalizar_telefono(texto)
    if not telefono.isdigit():
        return None
    if not (10 <= len(telefono) <= 13):
        return None
    return telefono


_MENSAJE_TELEFONO_INVALIDO = (
    "⚠️ Número de teléfono inválido. Por favor, ingresá un número de contacto válido "
    "(ej: 1112345678)."
)


def _solicitar_telefono_valido() -> str | None:
    while True:
        entrada = input("Ingresá tu teléfono simulado (ej: 1112345678): ").strip()
        if entrada.lower() in {"salir", "exit", "quit"}:
            return None

        telefono = _validar_telefono(entrada)
        if telefono:
            return telefono

        print(_MENSAJE_TELEFONO_INVALIDO)


def _responder_agradecimiento_telefono() -> str:
    return (
        "¡Gracias! Ya tengo tu número registrado. "
        "Para empezar, ¿me decís tu nombre y apellido?"
    )


def _capturar_nombre_cliente(
    sesion: SesionCliente,
    agencia: Agencia,
) -> str | None:
    bloqueo = _respuesta_si_agencia_bloqueada(sesion.agencia_id)
    if bloqueo:
        _entregar_respuesta_whatsapp(agencia, sesion.telefono, bloqueo)
        return bloqueo

    mensaje_telefono = _responder_agradecimiento_telefono()
    sesion.historial.append(f"Bot: {mensaje_telefono}")
    _persistir_mensaje(sesion, "bot", mensaje_telefono)
    _entregar_respuesta_whatsapp(agencia, sesion.telefono, mensaje_telefono)

    ultimo_mensaje = ""
    presentacion_final: PresentacionCliente | None = None

    while not sesion.nombre_cliente:
        bloqueo = _respuesta_si_agencia_bloqueada(sesion.agencia_id)
        if bloqueo:
            _entregar_respuesta_whatsapp(agencia, sesion.telefono, bloqueo)
            return bloqueo

        ultimo_mensaje = input("\nVos: ").strip()
        if ultimo_mensaje.lower() in {"salir", "exit", "quit"}:
            return None

        presentacion = _interpretar_presentacion(ultimo_mensaje)
        if presentacion.nombre_valido:
            sesion.nombre_cliente = presentacion.nombre
            sesion.apellido_cliente = presentacion.apellido
            presentacion_final = presentacion
            break

        sesion.historial.append(f"Cliente: {ultimo_mensaje}")
        _persistir_mensaje(sesion, "cliente", ultimo_mensaje)
        if presentacion.tiene_consulta_comercial:
            respuesta = _responder_captura_nombre(agencia, presentacion)
        elif _es_entrada_nombre_invalida(ultimo_mensaje):
            respuesta = _MENSAJE_PEDIR_NOMBRE_REAL
        else:
            respuesta = _responder_captura_nombre(agencia, presentacion)
        sesion.historial.append(f"Bot: {respuesta}")
        _persistir_mensaje(sesion, "bot", respuesta)
        _entregar_respuesta_whatsapp(agencia, sesion.telefono, respuesta)

    assert presentacion_final is not None
    mensaje_gemini = _mensaje_transicion_gemini(presentacion_final, ultimo_mensaje)
    return _procesar_mensaje(sesion, agencia, mensaje_gemini)


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY no configurada. Creá un archivo .env con tu clave.")
        _gemini_client = genai.Client(
            api_key=api_key,
            http_options=_HTTP_SIN_REINTENTOS_SDK,
        )
    return _gemini_client


def _detalle_error_api(error: Exception) -> str:
    return str(error).lower()


def _es_cuota_agotada(error: Exception) -> bool:
    if isinstance(error, genai_errors.ClientError) and error.code == 429:
        return True
    texto = _detalle_error_api(error)
    return (
        "429" in texto
        or "resource exhausted" in texto
        or "resource_exhausted" in texto
        or "rate limit" in texto
        or "too many requests" in texto
    )


def _es_cuota_diaria_agotada(error: Exception) -> bool:
    texto = _detalle_error_api(error).replace("_", "").replace("-", "")
    return (
        "perday" in texto
        or "freetierrequests" in texto
        or "generatecontentfreetierrequests" in texto
    )


def _es_limite_por_minuto_reintentable(error: Exception) -> bool:
    if not _es_cuota_agotada(error) or _es_cuota_diaria_agotada(error):
        return False
    texto = _detalle_error_api(error).replace("_", "").replace("-", "")
    return "perminute" in texto or "permin" in texto


def _marcar_cuota_diaria_agotada(sesion: SesionCliente | None, error: Exception) -> None:
    if sesion is not None:
        sesion.cuota_diaria_agotada = True


def _generar_respuesta_gemini(
    client: genai.Client,
    historial: list[str],
    prompt_sistema: str,
    sesion: SesionCliente | None = None,
) -> str:
    if sesion and sesion.cuota_diaria_agotada:
        raise genai_errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "Cuota diaria agotada en esta sesión.",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )

    contents = _historial_a_contents(historial)
    config = types.GenerateContentConfig(
        system_instruction=prompt_sistema,
        temperature=0.4,
    )

    intento = 0
    espera_seg = _BACKOFF_INICIAL_SEG
    ultimo_error: Exception | None = None

    while intento <= _MAX_REINTENTOS_429:
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=config,
            )
            return (response.text or "").strip()
        except ValueError:
            raise
        except Exception as e:
            ultimo_error = e
            if _es_cuota_diaria_agotada(e):
                _marcar_cuota_diaria_agotada(sesion, e)
                raise

            puede_reintentar = _es_limite_por_minuto_reintentable(e) and intento < _MAX_REINTENTOS_429
            if not puede_reintentar:
                raise

            time.sleep(espera_seg)
            espera_seg *= 2
            intento += 1

    if ultimo_error:
        raise ultimo_error
    return ""


def _historial_a_contents(historial: list[str]) -> list[types.Content]:
    contents: list[types.Content] = []
    for linea in historial:
        if linea.startswith("Cliente:"):
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=linea.removeprefix("Cliente:").strip())],
                )
            )
        elif linea.startswith("Bot:"):
            contents.append(
                types.Content(
                    role="model",
                    parts=[types.Part(text=linea.removeprefix("Bot:").strip())],
                )
            )
    return contents


def _construir_directiva_vendedor(agencia: Agencia, sesion: SesionCliente) -> str:
    nombre = _nombre_para_saludo(sesion)
    contexto_cliente = (
        f"DATOS DEL CLIENTE YA REGISTRADOS: Nombre: {nombre or 'sin nombre'}. "
        f"Teléfono: {sesion.telefono}."
    )
    contexto_usado = ""
    if sesion.quiere_permuta:
        contexto_usado = f"\nDATOS DEL USADO YA MENCIONADOS: {resumen_usado_sesion(sesion)}"
    contexto_fotos = ""
    contexto_sucursal = ""
    if sesion.sucursal_origen_id:
        nombre_suc = obtener_nombre_sucursal(sesion.agencia_id, sesion.sucursal_origen_id)
        contexto_sucursal = (
            f"\nSUCURSAL DE CONTACTO: El cliente escribió por WhatsApp de {nombre_suc}. "
            "Al agendar una visita, proponé esa sede por defecto. Si elige un auto que está "
            "en otra sucursal, ofrecé también coordinar turno en la sede donde está el vehículo."
        )
    if sesion.auto_interes_id:
        auto = obtener_auto_por_id(sesion.agencia_id, sesion.auto_interes_id)
        if auto:
            origenes = listar_origenes_fotos_auto(auto, base_url=_base_url_publica())
            if origenes:
                contexto_fotos = (
                    f"\nFOTOS DE PREVENTA DISPONIBLES para {auto.marca} {auto.modelo} "
                    f"({len(origenes)} archivo/s). Si el cliente pide ver fotos/imágenes, "
                    "confirmá con entusiasmo que se las mandás ahora. "
                    "PROHIBIDO inventar [IMAGEN …], pegar URLs o simular adjuntos: "
                    "el sistema enviará las fotos reales automáticamente después de tu texto."
                )
    return (
        f"{agencia.prompt_personalizado or ''}\n"
        f"{contexto_cliente}{contexto_sucursal}{contexto_usado}{contexto_fotos}\n"
        f"{INSTRUCCIONES_PERMUTA}\n"
        "PERSONALIDAD: vendedor argentino de usados, ágil y canchero, SIN teatro. "
        "Respuestas cortas (1-3 oraciones). Si el cliente da señal de compra, cerrá visita "
        "con día y hora concretos. No repitas speeches ni te disculpes de más. "
        "Usá el nombre del cliente cuando lo tengas."
    )


def _extraer_datos_en_segundo_plano(sesion: SesionCliente, texto: str) -> None:
    texto_norm = _normalizar_texto(texto)

    presupuesto = _extraer_presupuesto(texto)
    if presupuesto:
        sesion.presupuesto = presupuesto

    autos = buscar_autos_por_texto(sesion.agencia_id, texto)
    if autos:
        match_id = re.search(r"\bid\s*(\d+)\b", texto_norm)
        if match_id:
            auto_id = int(match_id.group(1))
            for auto in autos:
                if auto.id == auto_id:
                    sesion.auto_interes_id = auto.id
                    break
        elif len(autos) == 1:
            sesion.auto_interes_id = autos[0].id
        else:
            match_opcion = re.search(r"\b(opci[oó]n|numero|n[úu]mero)\s*(\d+)\b", texto_norm)
            if match_opcion:
                indice = int(match_opcion.group(2))
                if 1 <= indice <= len(autos):
                    sesion.auto_interes_id = autos[indice - 1].id

    extraer_datos_usado_en_segundo_plano(sesion, texto)

    if any(
        c in texto_norm
        for c in [
            "tengo el dinero",
            "tengo la plata",
            "tengo efectivo",
            "compro",
            "lo compro",
            "me lo llevo",
            "lo reservo",
            "voy a verlo",
            "me interesa",
        ]
    ):
        sesion.interes_alto = True


def _procesar_mensaje(
    sesion: SesionCliente,
    agencia: Agencia,
    mensaje: str,
    via_whatsapp: bool = False,
    etiqueta_cliente: str | None = None,
) -> str:
    bloqueo = _respuesta_si_agencia_bloqueada(sesion.agencia_id)
    if bloqueo:
        sesion.historial.append(f"Cliente: {mensaje.strip()}")
        _persistir_mensaje(sesion, "cliente", etiqueta_cliente or mensaje.strip())
        sesion.historial.append(f"Bot: {bloqueo}")
        _persistir_mensaje(sesion, "bot", bloqueo)
        _entregar_respuesta_whatsapp(
            agencia, sesion.telefono, bloqueo, via_whatsapp=via_whatsapp, sesion=sesion
        )
        return bloqueo

    texto = mensaje.strip()
    if not texto:
        respuesta_vacia = "Pasame un dato, ¿qué auto estás buscando?"
        _entregar_respuesta_whatsapp(
            agencia, sesion.telefono, respuesta_vacia, via_whatsapp=via_whatsapp, sesion=sesion
        )
        return respuesta_vacia

    sesion.historial.append(f"Cliente: {texto}")
    _persistir_mensaje(sesion, "cliente", etiqueta_cliente or texto)
    _extraer_datos_en_segundo_plano(sesion, texto)

    # Pedido de dirección: respuesta determinística con la dirección real de la BD.
    if cliente_pide_direccion(texto):
        respuesta_bot = _respuesta_direccion_agencia(agencia, sesion)
        sesion.historial.append(f"Bot: {respuesta_bot}")
        _persistir_mensaje(sesion, "bot", respuesta_bot)
        # No disparar lógica de cita por "pasame la dirección".
        _entregar_respuesta_whatsapp(
            agencia, sesion.telefono, respuesta_bot, via_whatsapp=via_whatsapp, sesion=sesion
        )
        return respuesta_bot

    # Reprogramar cita con hora explícita: una sola confirmación corta (sin Gemini).
    respuesta_repro = _respuesta_rapida_reprogramacion(sesion, agencia, texto)
    if respuesta_repro:
        sesion.historial.append(f"Bot: {respuesta_repro}")
        _persistir_mensaje(sesion, "bot", respuesta_repro)
        _entregar_respuesta_whatsapp(
            agencia, sesion.telefono, respuesta_repro, via_whatsapp=via_whatsapp, sesion=sesion
        )
        return respuesta_repro

    inventario = obtener_inventario_agencia(sesion.agencia_id)
    directivas = _construir_directiva_vendedor(agencia, sesion)
    if _tiene_consulta_comercial(_normalizar_texto(texto)):
        coincidencias = buscar_autos_por_texto(sesion.agencia_id, texto)
        if coincidencias:
            bloque_stock = formatear_opciones_stock_cruzado(
                coincidencias,
                sesion.agencia_id,
                sesion.sucursal_origen_id,
            )
            directivas = f"{directivas}\n\n{bloque_stock}"

    prompt_sistema = generar_prompt_maestro(
        nombre_agencia=obtener_nombre_agencia_bot(
            agencia, _sucursal_sesion_bot(sesion), _vendedor_sesion_bot(sesion)
        ),
        inventario_texto=inventario,
        contexto_temporal=_generar_contexto_temporal(),
        datos_ubicacion=_armar_datos_ubicacion(agencia, sesion),
        directivas=directivas,
    )

    try:
        client = _get_gemini_client()
        respuesta_bot = _generar_respuesta_gemini(
            client,
            sesion.historial,
            prompt_sistema,
            sesion=sesion,
        )
        if not respuesta_bot:
            respuesta_bot = "Che, se me trabó un segundo. ¿Me repetís lo último?"
    except ValueError:
        respuesta_bot = (
            "Falta configurar GEMINI_API_KEY en el archivo .env. "
            "Cuando la tengas, reiniciá el bot."
        )
    except genai_errors.ClientError as e:
        logger.error("[GEMINI ClientError] %s", e, exc_info=True)
        if sesion.cuota_diaria_agotada or _es_cuota_diaria_agotada(e):
            respuesta_bot = (
                "Llegamos al límite diario de consultas con la IA. "
                "Probá de nuevo mañana o contactá a la agencia por teléfono."
            )
        elif _es_cuota_agotada(e):
            respuesta_bot = (
                "Estoy con mucha demanda en este momento y no pude procesar tu mensaje. "
                "Esperá unos segundos y escribime de nuevo, ¿dale?"
            )
        else:
            respuesta_bot = "Che, se me cortó la señal en el playón. ¿Me repetís lo último?"
    except Exception as e:
        logger.error("[GEMINI Exception] %s", e, exc_info=True)
        respuesta_bot = "Che, se me cortó la señal en el playón. ¿Me repetís lo último?"

    # Gemini a veces inventa [IMAGEN 1…] o dice "2 hs"; normalizar antes de guardar/enviar.
    from formato_hora import normalizar_horas_mensaje_24h

    respuesta_bot = limpiar_placeholders_imagen_en_texto(respuesta_bot)
    respuesta_bot = normalizar_horas_mensaje_24h(respuesta_bot)

    sesion.historial.append(f"Bot: {respuesta_bot}")
    _persistir_mensaje(sesion, "bot", respuesta_bot)

    procesar_cita_si_corresponde(sesion)

    auto_fotos = None
    enviar_fotos = False
    if (
        sesion.auto_interes_id
        and cliente_pide_fotos(texto)
        and not cliente_en_cierre_sin_fotos(texto)
        and not detectar_visita(texto, sesion.historial)
    ):
        ya_enviadas = sesion.auto_interes_id in sesion.autos_con_fotos_enviadas
        if ya_enviadas and not cliente_pide_mas_fotos(texto):
            # Evita el loop: "me mandaste fotos → sigo charlando → te mando todo de nuevo".
            logger.info(
                "[FOTOS] Omitido reenvío auto_id=%s (ya enviadas en esta sesión)",
                sesion.auto_interes_id,
            )
        else:
            auto_fotos = obtener_auto_por_id(sesion.agencia_id, sesion.auto_interes_id)
            if auto_fotos and listar_origenes_fotos_auto(auto_fotos):
                enviar_fotos = True
                if not respuesta_bot.strip():
                    respuesta_bot = (
                        f"¡Dale! Te mando las fotos del "
                        f"{auto_fotos.marca} {auto_fotos.modelo} {auto_fotos.ano}."
                    )

    _entregar_respuesta_whatsapp(
        agencia, sesion.telefono, respuesta_bot, via_whatsapp=via_whatsapp, sesion=sesion
    )

    if enviar_fotos and auto_fotos is not None:
        enviadas = _enviar_fotos_auto_whatsapp(
            agencia, sesion.telefono, auto_fotos, sesion=sesion
        )
        if enviadas > 0:
            sesion.autos_con_fotos_enviadas.add(auto_fotos.id)
        if enviadas == 0:
            bloque_fotos = formatear_fotos_para_whatsapp(
                auto_fotos, base_url=_base_url_publica()
            )
            if bloque_fotos:
                _entregar_respuesta_whatsapp(
                    agencia,
                    sesion.telefono,
                    bloque_fotos,
                    via_whatsapp=via_whatsapp,
                    sesion=sesion,
                )
                sesion.autos_con_fotos_enviadas.add(auto_fotos.id)

    return respuesta_bot


def _finalizar_y_guardar_lead(sesion: SesionCliente) -> int | None:
    if sesion.lead_id:
        vincular_mensajes_a_lead(sesion.agencia_id, sesion.telefono, sesion.lead_id)
        return sesion.lead_id
    if not (
        sesion.auto_interes_id
        or sesion.presupuesto
        or sesion.quiere_permuta
        or sesion.nombre_cliente
        or sesion.interes_alto
    ):
        return None
    lead_id = guardar_lead_comercial(
        agencia_id=sesion.agencia_id,
        telefono=sesion.telefono,
        auto_id=sesion.auto_interes_id,
        presupuesto=sesion.presupuesto,
        nombre_cliente=sesion.nombre_cliente,
        apellido_cliente=sesion.apellido_cliente,
        usado_marca_modelo=sesion.usado_marca_modelo,
        usado_ano=sesion.usado_ano,
        usado_km=sesion.usado_km,
        usado_patente=sesion.usado_patente,
        usado_estado=sesion.usado_estado,
        usado_vtv_vigente=sesion.usado_vtv_vigente,
        usado_es_titular=sesion.usado_es_titular,
        lead_id=sesion.lead_id,
        sucursal_id=sesion.sucursal_origen_id,
        vendedor_id=sesion.vendedor_origen_id,
    )
    sesion.lead_id = lead_id
    vincular_mensajes_a_lead(sesion.agencia_id, sesion.telefono, lead_id)
    return lead_id


def _limpiar_terminal() -> None:
    if os.name == "nt":
        os.system("cls")
    else:
        print("\033c", end="")


def ejecutar_simulador(agencia_id: int = 1):
    inicializar_base_de_datos()
    agencia = _obtener_agencia(agencia_id)
    if not agencia:
        print(f"No existe la agencia con ID {agencia_id}. Ejecutá main.py primero.")
        return

    bloqueo = _respuesta_si_agencia_bloqueada(agencia_id)
    if bloqueo:
        print(f"\nBot: {bloqueo}")
        return

    inventario = obtener_inventario_agencia(agencia_id)

    _limpiar_terminal()
    telefono = _solicitar_telefono_valido()
    if telefono is None:
        print("\nSesión finalizada.")
        return
    sesion = SesionCliente(agencia_id=agencia_id, telefono=telefono)
    _enviar_bienvenida_inicial(sesion, agencia)

    primera_respuesta = _capturar_nombre_cliente(sesion, agencia)
    if primera_respuesta is None:
        print("\nSesión finalizada.")
        return

    while True:
        mensaje = input("\nVos: ").strip()
        if mensaje.lower() in {"salir", "exit", "quit"}:
            break
        if mensaje.lower() == "inventario":
            print("\nBot - Stock actual:\n", inventario)
            continue

        bloqueo = _respuesta_si_agencia_bloqueada(sesion.agencia_id)
        if bloqueo:
            _entregar_respuesta_whatsapp(agencia, sesion.telefono, bloqueo)
            continue

        _procesar_mensaje(sesion, agencia, mensaje)

    _finalizar_y_guardar_lead(sesion)

    print("\nSesión finalizada.")


if __name__ == "__main__":
    ejecutar_simulador()
