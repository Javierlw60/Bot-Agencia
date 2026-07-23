import datetime
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload

from dashboard.import_stock import importar_csv
from dashboard.sucursal_sesion import leer_sucursal_cookie
from citas import obtener_fecha_hoy_argentina
from conversaciones import obtener_historial, resumen_comercial_lead
from dashboard.media import (
    agregar_foto_a_auto,
    directorio_upload,
    definir_portada_auto,
    eliminar_foto_de_auto,
    guardar_fotos_auto,
    obtener_fotos_auto,
    obtener_portada_auto,
    sincronizar_fotos_auto,
    url_publica_upload,
)
from estado_cita import (
    ESTADO_PERDIDA,
    ESTADO_VENTA,
    ESTADOS_CITA,
    ESTADOS_VALIDOS,
    etiqueta_estado_cita,
    normalizar_estado_cita,
)
from mercadopago_config import mercadopago_configurado, obtener_config_mercadopago
from mercadopago_servicio import (
    MercadoPagoError,
    crear_preferencia_pago_unico,
    crear_suscripcion_recurrente,
)
from models.database import (
    Agencia,
    Auto,
    Cita,
    ProspectoLead,
    SessionLocal,
    Sucursal,
    Vendedor,
    engine,
)
from modo_respuesta import (
    ETIQUETAS_MODO_RESPUESTA,
    MODOS_RESPUESTA_VALIDOS,
    normalizar_modo_respuesta,
)
from paths_datos import static_dir
from personalizacion_bot import (
    NOMBRE_AGENCIA_DEFAULT,
    NOMBRE_BOT_DEFAULT,
    mensaje_bienvenida_agencia,
    obtener_color_primario,
    obtener_logo_bot,
    obtener_nombre_agencia_bot,
    obtener_nombre_bot,
)
from suscripcion_agencias import ESTADO_ACTIVO, ESTADO_BLOQUEADO, agencia_vence_pronto
from whatsapp_linea import es_phone_number_id_meta, parece_celular_argentino

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger_estadisticas = logging.getLogger("dashboard.estadisticas")

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_CLAVE_SIN_ASIGNAR = 0


def _static_base() -> Path:
    return static_dir()


def _obtener_agencia(db, agencia_id: int) -> Agencia:
    agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
    if not agencia:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    return agencia


def _contexto_base(
    request: Request,
    agencia: Agencia,
    pagina: str,
    sucursal_activa: Sucursal | None = None,
) -> dict:
    return {
        "request": request,
        "agencia": agencia,
        "pagina_activa": pagina,
        "sucursal_activa": sucursal_activa,
        "color_primario": obtener_color_primario(agencia, sucursal_activa),
        "nombre_comercial_actual": obtener_nombre_agencia_bot(agencia, sucursal_activa),
    }


def _contexto_dashboard(
    request: Request,
    db,
    agencia: Agencia,
    pagina: str,
    sucursal_param: int | None = None,
) -> dict:
    ctx_suc = _contexto_sucursales(request, db, agencia.id, sucursal_param)
    ctx = _contexto_base(request, agencia, pagina, ctx_suc["sucursal_activa"])
    ctx.update(ctx_suc)
    return ctx


def _ordenar_autos(query):
    return query.order_by(func.lower(Auto.marca), func.lower(Auto.modelo))


def _query_autos_agencia(db, agencia_id: int):
    return db.query(Auto).filter(Auto.agencia_id == agencia_id)


def _metricas_agencia(
    db,
    agencia_id: int,
    sucursal_id: int | None = None,
) -> dict:
    """Conteos reales desde la BD; única fuente de verdad para el dashboard."""
    hoy = obtener_fecha_hoy_argentina()
    autos = _query_autos_agencia(db, agencia_id)
    leads = db.query(ProspectoLead).filter(ProspectoLead.agencia_id == agencia_id)
    if sucursal_id:
        autos = autos.filter(Auto.sucursal_id == sucursal_id)
        leads = leads.filter(ProspectoLead.sucursal_id == sucursal_id)
    return {
        "total_autos": autos.count(),
        "disponibles": autos.filter(func.lower(Auto.estado) == "disponible").count(),
        "total_leads": leads.count(),
        "citas_hoy": len(_citas_del_dia(db, agencia_id, hoy, sucursal_id)),
    }


def _citas_del_dia(
    db,
    agencia_id: int,
    fecha: datetime.date,
    sucursal_id: int | None = None,
) -> list[tuple[Cita, ProspectoLead]]:
    query = (
        db.query(Cita, ProspectoLead)
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(
            ProspectoLead.agencia_id == agencia_id,
            Cita.fecha_cita == fecha,
        )
    )
    if sucursal_id:
        query = query.filter(
            or_(
                Cita.sucursal_id == sucursal_id,
                and_(Cita.sucursal_id.is_(None), ProspectoLead.sucursal_id == sucursal_id),
            )
        )
    return query.order_by(Cita.hora_cita).all()


def _nombre_cliente_lead(lead: ProspectoLead) -> str:
    partes = [lead.nombre_cliente, lead.apellido_cliente]
    nombre = " ".join(p for p in partes if p and str(p).strip()).strip()
    return nombre or "Sin nombre"


def _serializar_cita(
    cita: Cita,
    lead: ProspectoLead,
    mapa_sucursales: dict[int, str] | None = None,
    mapa_vendedores: dict[int, str] | None = None,
) -> dict:
    sucursal_nombre = "Sin sucursal"
    if cita.sucursal_id and mapa_sucursales:
        sucursal_nombre = mapa_sucursales.get(cita.sucursal_id, "Sin sucursal")
    vendedor_id = getattr(cita, "vendedor_id", None)
    vendedor_nombre = None
    if vendedor_id and mapa_vendedores:
        vendedor_nombre = mapa_vendedores.get(vendedor_id)
    return {
        "id": cita.id,
        "hora": cita.hora_cita,
        "fecha": cita.fecha_cita.strftime("%d/%m/%Y"),
        "fecha_iso": cita.fecha_cita.isoformat(),
        "cliente": _nombre_cliente_lead(lead),
        "nombre": lead.nombre_cliente or "",
        "apellido": lead.apellido_cliente or "",
        "telefono": lead.telefono_cliente,
        "auto": cita.auto_interes or "Sin auto especificado",
        "patente": (lead.auto.patente.strip().upper() if lead.auto and getattr(lead.auto, "patente", None) and lead.auto.patente.strip() else None),
        "estado": normalizar_estado_cita(cita.estado),
        "estado_label": etiqueta_estado_cita(cita.estado),
        "sucursal": sucursal_nombre,
        "vendedor_id": vendedor_id,
        "vendedor": vendedor_nombre,
        "recordatorio_enviado": bool(cita.recordatorio_enviado),
    }


def _mapa_vendedores(db, agencia_id: int) -> dict[int, str]:
    return {
        v.id: v.nombre
        for v in db.query(Vendedor).filter(Vendedor.agencia_id == agencia_id).all()
    }


def _vendedores_por_sucursal(db, agencia_id: int) -> dict[int, list[dict]]:
    """Mapa {sucursal_id: [{id, nombre}]} para poblar selects dinámicos."""
    resultado: dict[int, list[dict]] = {}
    vendedores = (
        db.query(Vendedor)
        .filter(Vendedor.agencia_id == agencia_id)
        .order_by(Vendedor.es_principal.desc(), Vendedor.id)
        .all()
    )
    for v in vendedores:
        resultado.setdefault(v.sucursal_id, []).append({"id": v.id, "nombre": v.nombre})
    return resultado


PERIODOS_ESTADISTICA = {
    "semanal": "Esta semana",
    "mensual": "Este mes",
    "anual": "Este año",
}


def _filtro_sucursal_cita(sucursal_id: int | None):
    """Incluye citas legacy sin sucursal_id pero cuyo lead pertenece a la sucursal."""
    if not sucursal_id:
        return None
    return or_(
        Cita.sucursal_id == sucursal_id,
        and_(Cita.sucursal_id.is_(None), ProspectoLead.sucursal_id == sucursal_id),
    )


def _aplicar_filtro_sucursal_estadisticas(query, sucursal_id: int | None):
    filtro = _filtro_sucursal_cita(sucursal_id)
    if filtro is not None:
        query = query.filter(filtro)
    return query


def _query_citas_estadisticas(
    db,
    agencia_id: int,
    desde: datetime.date,
    hasta: datetime.date,
    sucursal_id: int | None,
):
    q = (
        db.query(Cita)
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(
            ProspectoLead.agencia_id == agencia_id,
            Cita.fecha_cita >= desde,
            Cita.fecha_cita <= hasta,
        )
    )
    return _aplicar_filtro_sucursal_estadisticas(q, sucursal_id)


def _sql_compilado(query) -> str:
    try:
        return str(
            query.statement.compile(
                dialect=engine.dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
    except Exception:
        return str(query.statement)


def _fila_metricas_vendedor(
    vendedor_id: int | None,
    nombre: str,
    sucursal: str,
    es_principal: bool = False,
    telefono_wa_me: str | None = None,
) -> dict:
    return {
        "vendedor_id": vendedor_id,
        "vendedor": nombre,
        "sucursal": sucursal,
        "es_principal": es_principal,
        "telefono_wa_me": telefono_wa_me,
        "es_lider": False,
        "total": 0,
        "concretadas": 0,
        "perdidas": 0,
        "en_proceso": 0,
        "tasa_conversion": 0.0,
    }


def _telefono_para_wa_me(valor: str | None) -> str | None:
    """Devuelve dígitos E.164 para wa.me, o None si no es un teléfono de contacto válido."""
    raw = (valor or "").strip()
    if not raw or raw.startswith("sin-linea"):
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 10 or len(digits) > 15:
        return None
    return digits


def _marcar_lider_conversion(filas: list[dict]) -> None:
    """Marca es_lider al vendedor con mayor conversión (excluye 'Sin asignar')."""
    for fila in filas:
        fila["es_lider"] = False
    candidatos = [
        f for f in filas
        if f.get("vendedor_id") is not None and (f.get("total") or 0) > 0
    ]
    if not candidatos:
        return
    candidatos.sort(
        key=lambda f: (f["tasa_conversion"], f["concretadas"], f["total"]),
        reverse=True,
    )
    candidatos[0]["es_lider"] = True


def _acumular_estado_en_fila(fila: dict, estado: str | None, cantidad: int, tot: dict) -> None:
    estado_norm = normalizar_estado_cita(estado)
    fila["total"] += cantidad
    tot["total"] += cantidad
    if estado_norm == ESTADO_VENTA:
        fila["concretadas"] += cantidad
        tot["concretadas"] += cantidad
    elif estado_norm == ESTADO_PERDIDA:
        fila["perdidas"] += cantidad
        tot["perdidas"] += cantidad
    else:
        fila["en_proceso"] += cantidad
        tot["en_proceso"] += cantidad


def _auditar_estadisticas_citas(
    db,
    agencia_id: int,
    sucursal_id: int | None,
    periodo: str,
    desde: datetime.date,
    hasta: datetime.date,
    q_base,
    q_agrupada,
) -> None:
    total_rango = q_base.count()
    sin_vendedor = q_base.filter(Cita.vendedor_id.is_(None)).count()
    por_estado_raw = (
        db.query(Cita.estado, func.count(Cita.id))
        .select_from(Cita)
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(
            ProspectoLead.agencia_id == agencia_id,
            Cita.fecha_cita >= desde,
            Cita.fecha_cita <= hasta,
        )
    )
    por_estado_raw = _aplicar_filtro_sucursal_estadisticas(por_estado_raw, sucursal_id)
    por_estado_raw = por_estado_raw.group_by(Cita.estado).all()
    por_estado = {
        (estado or "(null)"): cantidad for estado, cantidad in por_estado_raw
    }
    por_estado_norm = {}
    for estado, cantidad in por_estado_raw:
        clave = normalizar_estado_cita(estado)
        por_estado_norm[clave] = por_estado_norm.get(clave, 0) + cantidad

    logger_estadisticas.info(
        "[estadisticas] agencia=%s sucursal=%s periodo=%s rango=%s..%s | "
        "citas_en_rango=%s sin_vendedor=%s estados_raw=%s estados_norm=%s",
        agencia_id,
        sucursal_id,
        periodo,
        desde.isoformat(),
        hasta.isoformat(),
        total_rango,
        sin_vendedor,
        por_estado,
        por_estado_norm,
    )
    print(
        f"[estadisticas] agencia={agencia_id} sucursal={sucursal_id} periodo={periodo} "
        f"rango={desde.isoformat()}..{hasta.isoformat()} | "
        f"citas_en_rango={total_rango} sin_vendedor={sin_vendedor} "
        f"estados_raw={por_estado} estados_norm={por_estado_norm}",
        flush=True,
    )
    sql_base = _sql_compilado(q_base)
    sql_agrupada = _sql_compilado(q_agrupada)
    logger_estadisticas.info("[estadisticas] SQL base: %s", sql_base)
    logger_estadisticas.info("[estadisticas] SQL agrupada (vendedor+estado): %s", sql_agrupada)
    print(f"[estadisticas] SQL base: {sql_base}", flush=True)
    print(f"[estadisticas] SQL agrupada: {sql_agrupada}", flush=True)


def _rango_estadistica(
    periodo: str,
    hoy: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date]:
    hoy = hoy or obtener_fecha_hoy_argentina()
    if periodo == "mensual":
        desde = hoy.replace(day=1)
        if hoy.month == 12:
            hasta = hoy.replace(day=31)
        else:
            hasta = hoy.replace(month=hoy.month + 1, day=1) - datetime.timedelta(days=1)
        return desde, hasta
    if periodo == "anual":
        return hoy.replace(month=1, day=1), hoy.replace(month=12, day=31)
    # semanal: semana actual comenzando el domingo.
    dias_desde_domingo = (hoy.weekday() + 1) % 7
    desde = hoy - datetime.timedelta(days=dias_desde_domingo)
    return desde, desde + datetime.timedelta(days=6)


def _construir_estadisticas_vendedores(
    db,
    agencia_id: int,
    sucursal_id: int | None,
    periodo: str,
) -> dict:
    periodo = periodo if periodo in PERIODOS_ESTADISTICA else "semanal"
    desde, hasta = _rango_estadistica(periodo)
    mapa_suc = _mapa_sucursales(db, agencia_id)

    q_vend = db.query(Vendedor).filter(Vendedor.agencia_id == agencia_id)
    if sucursal_id:
        q_vend = q_vend.filter(Vendedor.sucursal_id == sucursal_id)
    vendedores = q_vend.order_by(Vendedor.es_principal.desc(), Vendedor.id).all()
    ids_vendedor = {v.id for v in vendedores}

    acum: dict[int, dict] = {}
    for v in vendedores:
        acum[v.id] = _fila_metricas_vendedor(
            v.id,
            v.nombre,
            mapa_suc.get(v.sucursal_id, "Sin sucursal"),
            es_principal=bool(v.es_principal),
            telefono_wa_me=_telefono_para_wa_me(v.telefono_whatsapp),
        )
    acum[_CLAVE_SIN_ASIGNAR] = _fila_metricas_vendedor(
        None,
        "Sin asignar",
        mapa_suc.get(sucursal_id, "Todas") if sucursal_id else "Todas",
        es_principal=False,
    )

    q_base = _query_citas_estadisticas(db, agencia_id, desde, hasta, sucursal_id)
    q_agrupada = (
        db.query(Cita.vendedor_id, Cita.estado, func.count(Cita.id))
        .select_from(Cita)
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(
            ProspectoLead.agencia_id == agencia_id,
            Cita.fecha_cita >= desde,
            Cita.fecha_cita <= hasta,
        )
        .group_by(Cita.vendedor_id, Cita.estado)
    )
    q_agrupada = _aplicar_filtro_sucursal_estadisticas(q_agrupada, sucursal_id)

    _auditar_estadisticas_citas(
        db, agencia_id, sucursal_id, periodo, desde, hasta, q_base, q_agrupada
    )

    tot = {"total": 0, "concretadas": 0, "perdidas": 0, "en_proceso": 0}
    for vendedor_id, estado, cantidad in q_agrupada.all():
        if vendedor_id is None or vendedor_id not in ids_vendedor:
            clave = _CLAVE_SIN_ASIGNAR
        else:
            clave = vendedor_id
        _acumular_estado_en_fila(acum[clave], estado, cantidad, tot)

    sin_asignar = acum[_CLAVE_SIN_ASIGNAR]
    filas = [acum[v.id] for v in vendedores]
    for fila in filas:
        fila["tasa_conversion"] = (
            round(fila["concretadas"] / fila["total"] * 100, 1) if fila["total"] else 0.0
        )
    # Orden principal: % conversión (mayor a menor).
    filas.sort(
        key=lambda f: (f["tasa_conversion"], f["concretadas"], f["total"]),
        reverse=True,
    )
    _marcar_lider_conversion(filas)
    if sin_asignar["total"] > 0:
        sin_asignar["tasa_conversion"] = (
            round(sin_asignar["concretadas"] / sin_asignar["total"] * 100, 1)
            if sin_asignar["total"]
            else 0.0
        )
        filas.append(sin_asignar)

    tot["tasa_conversion"] = (
        round(tot["concretadas"] / tot["total"] * 100, 1) if tot["total"] else 0.0
    )

    return {
        "periodo": periodo,
        "periodo_label": PERIODOS_ESTADISTICA[periodo],
        "rango": {
            "desde": desde.strftime("%d/%m/%Y"),
            "hasta": hasta.strftime("%d/%m/%Y"),
            "desde_iso": desde.isoformat(),
            "hasta_iso": hasta.isoformat(),
        },
        "sucursal_id": sucursal_id,
        "vendedores": filas,
        "totales": tot,
    }


def _buscar_citas(
    db,
    agencia_id: int,
    telefono: str | None = None,
    nombre: str | None = None,
    apellido: str | None = None,
    fecha: datetime.date | None = None,
    sucursal_id: int | None = None,
    vendedor_id: int | None = None,
    limite: int = 50,
) -> list[tuple[Cita, ProspectoLead]]:
    telefono = (telefono or "").strip().replace(" ", "").replace("-", "")
    nombre = (nombre or "").strip()
    apellido = (apellido or "").strip()
    if (
        not telefono
        and not nombre
        and not apellido
        and not fecha
        and not sucursal_id
        and not vendedor_id
    ):
        return []

    query = (
        db.query(Cita, ProspectoLead)
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(ProspectoLead.agencia_id == agencia_id)
    )
    if telefono:
        query = query.filter(ProspectoLead.telefono_cliente.contains(telefono))
    if nombre:
        query = query.filter(
            func.lower(ProspectoLead.nombre_cliente).contains(nombre.lower())
        )
    if apellido:
        query = query.filter(
            func.lower(ProspectoLead.apellido_cliente).contains(apellido.lower())
        )
    if fecha:
        query = query.filter(Cita.fecha_cita == fecha)
    if sucursal_id:
        query = query.filter(Cita.sucursal_id == sucursal_id)
    if vendedor_id:
        query = query.filter(Cita.vendedor_id == vendedor_id)
    return (
        query.order_by(Cita.fecha_cita.desc(), Cita.hora_cita.desc())
        .limit(limite)
        .all()
    )


def _citas_en_rango(
    db,
    agencia_id: int,
    desde: datetime.date,
    hasta: datetime.date,
    sucursal_id: int | None = None,
) -> list[tuple[Cita, ProspectoLead]]:
    query = (
        db.query(Cita, ProspectoLead)
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(
            ProspectoLead.agencia_id == agencia_id,
            Cita.fecha_cita >= desde,
            Cita.fecha_cita <= hasta,
        )
    )
    if sucursal_id:
        query = query.filter(
            or_(
                Cita.sucursal_id == sucursal_id,
                and_(Cita.sucursal_id.is_(None), ProspectoLead.sucursal_id == sucursal_id),
            )
        )
    return query.order_by(Cita.fecha_cita, Cita.hora_cita).all()


def _rango_predictivo_fechas(
    rango: str,
    hoy: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date]:
    hoy = hoy or obtener_fecha_hoy_argentina()
    if rango == "15dias":
        return hoy, hoy + datetime.timedelta(days=15)
    if rango == "mes":
        return hoy, hoy + datetime.timedelta(days=30)
    return hoy, hoy + datetime.timedelta(days=7)


def _listar_citas_predictivas(
    db,
    agencia_id: int,
    sucursal_id: int | None,
    rango: str = "semana",
) -> list[dict]:
    desde, hasta = _rango_predictivo_fechas(rango)
    mapa = _mapa_sucursales(db, agencia_id)
    mapa_vend = _mapa_vendedores(db, agencia_id)
    filas = _citas_en_rango(db, agencia_id, desde, hasta, sucursal_id)
    return [_serializar_cita(c, l, mapa, mapa_vend) for c, l in filas]


# weekday(): lunes=0 ... domingo=6
DIAS_ABREV_ES = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
COLOR_SIN_SUCURSAL = "#64748b"


def _citas_agrupadas_dia_sucursal(
    db,
    agencia_id: int,
    desde: datetime.date,
    hasta: datetime.date,
) -> dict[tuple[str, int | None], int]:
    """Cuenta citas agrupadas por fecha_cita y sucursal_id en SQL."""
    filas = (
        db.query(
            Cita.fecha_cita,
            Cita.sucursal_id,
            func.count(Cita.id),
        )
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(
            ProspectoLead.agencia_id == agencia_id,
            Cita.fecha_cita >= desde,
            Cita.fecha_cita <= hasta,
        )
        .group_by(Cita.fecha_cita, Cita.sucursal_id)
        .all()
    )
    agrupado: dict[tuple[str, int | None], int] = {}
    for fecha, suc_id, cantidad in filas:
        agrupado[(fecha.isoformat(), suc_id)] = int(cantidad)
    return agrupado


def _meta_sucursales_analitica(db, agencia_id: int, agrupado_keys) -> list[dict]:
    sucursales = _listar_sucursales(db, agencia_id)
    meta = [
        {
            "id": s.id,
            "nombre": s.nombre,
            "color": getattr(s, "color_primario", None) or "#3B82F6",
        }
        for s in sucursales
    ]
    if any(suc_id is None for (_fecha, suc_id) in agrupado_keys):
        meta.append({"id": None, "nombre": "Sin sucursal", "color": COLOR_SIN_SUCURSAL})
    return meta


def _datasets_por_dia(meta: list[dict], dias: list[datetime.date], agrupado) -> list[dict]:
    datasets = []
    for s in meta:
        data = [agrupado.get((d.isoformat(), s["id"]), 0) for d in dias]
        if sum(data) == 0 and s["id"] is None:
            continue
        datasets.append({
            "sucursal_id": s["id"],
            "label": s["nombre"],
            "color": s["color"],
            "data": data,
        })
    return datasets


def _datasets_por_bucket(meta: list[dict], buckets: list[tuple[datetime.date, datetime.date]], agrupado) -> list[dict]:
    datasets = []
    for s in meta:
        data = []
        for inicio, fin in buckets:
            total = 0
            dia = inicio
            while dia <= fin:
                total += agrupado.get((dia.isoformat(), s["id"]), 0)
                dia += datetime.timedelta(days=1)
            data.append(total)
        if sum(data) == 0 and s["id"] is None:
            continue
        datasets.append({
            "sucursal_id": s["id"],
            "label": s["nombre"],
            "color": s["color"],
            "data": data,
        })
    return datasets


def _construir_analitica_citas(
    db,
    agencia_id: int,
    sucursal_id: int | None,
) -> dict:
    hoy = obtener_fecha_hoy_argentina()

    # --- Vista semanal: semana actual comenzando el DOMINGO ---
    dias_desde_domingo = (hoy.weekday() + 1) % 7
    inicio_semana = hoy - datetime.timedelta(days=dias_desde_domingo)
    dias_semana = [inicio_semana + datetime.timedelta(days=i) for i in range(7)]
    semanal_labels = [
        f"{DIAS_ABREV_ES[d.weekday()]} {d.strftime('%d/%m')}" for d in dias_semana
    ]
    agr_semana = _citas_agrupadas_dia_sucursal(db, agencia_id, dias_semana[0], dias_semana[-1])
    meta_semana = _meta_sucursales_analitica(db, agencia_id, agr_semana.keys())
    semanal_datasets = _datasets_por_dia(meta_semana, dias_semana, agr_semana)
    semanal_values = [
        sum(agr_semana.get((d.isoformat(), s["id"]), 0) for s in meta_semana)
        for d in dias_semana
    ]

    # --- Vista mensual: últimas 4 semanas (domingo a sábado) ---
    mensual_buckets: list[tuple[datetime.date, datetime.date]] = []
    mensual_labels: list[str] = []
    for semana_atras in range(3, -1, -1):
        fin = inicio_semana - datetime.timedelta(days=semana_atras * 7) + datetime.timedelta(days=6)
        inicio = fin - datetime.timedelta(days=6)
        mensual_buckets.append((inicio, fin))
        mensual_labels.append(f"{inicio.strftime('%d/%m')}–{fin.strftime('%d/%m')}")
    mes_inicio = mensual_buckets[0][0]
    mes_fin = mensual_buckets[-1][1]
    agr_mes = _citas_agrupadas_dia_sucursal(db, agencia_id, mes_inicio, mes_fin)
    meta_mes = _meta_sucursales_analitica(db, agencia_id, agr_mes.keys())
    mensual_datasets = _datasets_por_bucket(meta_mes, mensual_buckets, agr_mes)
    mensual_values = [
        sum(
            agr_mes.get((( inicio + datetime.timedelta(days=i) ).isoformat(), s["id"]), 0)
            for s in meta_mes
            for i in range((fin - inicio).days + 1)
        )
        for inicio, fin in mensual_buckets
    ]

    return {
        "semanal": {
            "labels": semanal_labels,
            "values": semanal_values,
            "datasets": semanal_datasets,
        },
        "mensual": {
            "labels": mensual_labels,
            "values": mensual_values,
            "datasets": mensual_datasets,
        },
        "calendario": _construir_calendario_mes(db, agencia_id, hoy.year, hoy.month, sucursal_id),
    }


MESES_ES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
)


def _construir_calendario_mes(
    db,
    agencia_id: int,
    anio: int,
    mes: int,
    sucursal_id: int | None,
) -> dict:
    if mes == 12:
        ultimo_dia_mes = datetime.date(anio + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        ultimo_dia_mes = datetime.date(anio, mes + 1, 1) - datetime.timedelta(days=1)
    primer_dia_mes = datetime.date(anio, mes, 1)
    dias_ocupados: dict[str, int] = {}
    for cita, _ in _citas_en_rango(db, agencia_id, primer_dia_mes, ultimo_dia_mes, sucursal_id):
        clave = cita.fecha_cita.isoformat()
        dias_ocupados[clave] = dias_ocupados.get(clave, 0) + 1

    hoy = obtener_fecha_hoy_argentina()
    return {
        "anio": anio,
        "mes": mes,
        "mes_nombre": MESES_ES[mes - 1],
        "primer_dia": primer_dia_mes.isoformat(),
        "ultimo_dia": ultimo_dia_mes.isoformat(),
        "dias_ocupados": dias_ocupados,
        "hoy": hoy.isoformat(),
    }


def _construir_feed_citas(db, agencia_id: int, sucursal_id: int | None = None) -> dict:
    hoy = obtener_fecha_hoy_argentina()
    manana = hoy + datetime.timedelta(days=1)
    citas_hoy = _citas_del_dia(db, agencia_id, hoy, sucursal_id)
    citas_manana = _citas_del_dia(db, agencia_id, manana, sucursal_id)
    mapa = _mapa_sucursales(db, agencia_id)
    mapa_vend = _mapa_vendedores(db, agencia_id)
    return {
        "fecha_hoy": hoy.strftime("%d/%m/%Y"),
        "fecha_manana": manana.strftime("%d/%m/%Y"),
        "citas_hoy": [_serializar_cita(c, l, mapa, mapa_vend) for c, l in citas_hoy],
        "citas_manana": [_serializar_cita(c, l, mapa, mapa_vend) for c, l in citas_manana],
    }


def _listar_sucursales(db, agencia_id: int) -> list[Sucursal]:
    return (
        db.query(Sucursal)
        .filter(Sucursal.agencia_id == agencia_id)
        .order_by(Sucursal.numero)
        .all()
    )


def _resolver_sucursal_activa(
    db,
    agencia_id: int,
    sucursal_id: int | None = None,
) -> Sucursal:
    sucursales = _listar_sucursales(db, agencia_id)
    if not sucursales:
        sucursal = Sucursal(
            agencia_id=agencia_id,
            numero=1,
            nombre="Sucursal 1",
            es_principal=True,
        )
        agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
        if agencia:
            # La línea de WhatsApp Business vive solo en la agencia; la sucursal
            # no hereda el Phone Number ID como si fuera un celular.
            sucursal.telefono_whatsapp = ""
            sucursal.nombre_comercial = agencia.nombre_agencia or agencia.nombre
            sucursal.asesor_virtual_nombre = agencia.nombre_bot
            sucursal.color_primario = agencia.color_primario or "#3B82F6"
        db.add(sucursal)
        db.commit()
        db.refresh(sucursal)
        return sucursal
    if sucursal_id:
        for suc in sucursales:
            if suc.id == sucursal_id:
                return suc
    for suc in sucursales:
        if suc.es_principal:
            return suc
    return sucursales[0]


def _mapa_sucursales(db, agencia_id: int) -> dict[int, str]:
    return {s.id: s.nombre for s in _listar_sucursales(db, agencia_id)}


def _listar_vendedores(db, sucursal_id: int) -> list[Vendedor]:
    return (
        db.query(Vendedor)
        .filter(Vendedor.sucursal_id == sucursal_id)
        .order_by(Vendedor.es_principal.desc(), Vendedor.id)
        .all()
    )


def _normalizar_telefono(valor: str) -> str:
    return (valor or "").strip().replace(" ", "").replace("-", "")


def _vendedor_sin_celular(vendedor: Vendedor | None) -> bool:
    tel = (vendedor.telefono_whatsapp or "").strip() if vendedor else ""
    return not tel or tel.startswith("sin-linea") or es_phone_number_id_meta(tel)


def _agencia_tiene_linea_bot(agencia: Agencia) -> bool:
    linea = (agencia.whatsapp_phone_number_id or "").strip()
    return bool(linea) and not linea.startswith("reg_") and not linea.startswith("sin-linea")


def _liberar_linea_bot_en_equipo(db, agencia_id: int, linea: str) -> None:
    """Quita la línea del bot de vendedores/sucursales que la tenían duplicada."""
    norm = _normalizar_telefono(linea)
    if not norm:
        return
    for vend in db.query(Vendedor).filter(Vendedor.agencia_id == agencia_id).all():
        if _normalizar_telefono(vend.telefono_whatsapp) == norm:
            vend.telefono_whatsapp = f"sin-linea-{vend.id}"
    for suc in db.query(Sucursal).filter(Sucursal.agencia_id == agencia_id).all():
        if _normalizar_telefono(suc.telefono_whatsapp) == norm:
            suc.telefono_whatsapp = ""


def _migrar_linea_bot_desde_equipo(db, agencia: Agencia) -> bool:
    """
    Si el Phone Number ID de Meta quedó en un vendedor/sucursal (modelo viejo),
    lo mueve a la agencia y libera esos campos.
    """
    cambiado = False
    linea_actual = (agencia.whatsapp_phone_number_id or "").strip()
    necesita_linea = not _agencia_tiene_linea_bot(agencia)

    candidatos: list[str] = []
    for vend in db.query(Vendedor).filter(Vendedor.agencia_id == agencia.id).all():
        tel = (vend.telefono_whatsapp or "").strip()
        if tel and es_phone_number_id_meta(tel):
            candidatos.append(tel)
    for suc in db.query(Sucursal).filter(Sucursal.agencia_id == agencia.id).all():
        tel = (suc.telefono_whatsapp or "").strip()
        if tel and es_phone_number_id_meta(tel):
            candidatos.append(tel)

    if necesita_linea and candidatos:
        agencia.whatsapp_phone_number_id = candidatos[0]
        linea_actual = candidatos[0]
        cambiado = True

    if linea_actual and _agencia_tiene_linea_bot(agencia):
        antes = [
            (v.id, v.telefono_whatsapp)
            for v in db.query(Vendedor).filter(Vendedor.agencia_id == agencia.id).all()
        ]
        _liberar_linea_bot_en_equipo(db, agencia.id, linea_actual)
        despues = [
            (v.id, v.telefono_whatsapp)
            for v in db.query(Vendedor).filter(Vendedor.agencia_id == agencia.id).all()
        ]
        if antes != despues:
            cambiado = True
        for suc in db.query(Sucursal).filter(Sucursal.agencia_id == agencia.id).all():
            tel = (suc.telefono_whatsapp or "").strip()
            if tel and (
                _normalizar_telefono(tel) == _normalizar_telefono(linea_actual)
                or es_phone_number_id_meta(tel)
            ):
                suc.telefono_whatsapp = ""
                cambiado = True

    # Cualquier celular Meta residual en vendedores (aunque la agencia ya tenía línea).
    for vend in db.query(Vendedor).filter(Vendedor.agencia_id == agencia.id).all():
        tel = (vend.telefono_whatsapp or "").strip()
        if tel and es_phone_number_id_meta(tel):
            vend.telefono_whatsapp = f"sin-linea-{vend.id}"
            cambiado = True

    if cambiado:
        db.commit()
        db.refresh(agencia)
    return cambiado


def _asegurar_vendedor_sucursal(db, sucursal: Sucursal, agencia: Agencia) -> list[Vendedor]:
    """Garantiza al menos un vendedor por sucursal (Vendedor Principal)."""
    vendedores = _listar_vendedores(db, sucursal.id)
    if vendedores:
        return vendedores

    vendedor = Vendedor(
        agencia_id=agencia.id,
        sucursal_id=sucursal.id,
        nombre="Vendedor Principal",
        asesor_virtual_nombre=None,
        nombre_comercial=None,
        color_primario=None,
        logo_url=None,
        telefono_whatsapp=f"sin-linea-suc-{sucursal.id}",
        modo_respuesta=None,
        es_principal=True,
        activo=True,
    )
    db.add(vendedor)
    db.commit()
    db.refresh(vendedor)
    return _listar_vendedores(db, sucursal.id)


def _resolver_vendedor_activo(
    db,
    sucursal: Sucursal,
    vendedor_id: int | None = None,
) -> Vendedor | None:
    vendedores = _listar_vendedores(db, sucursal.id)
    if not vendedores:
        return None
    if vendedor_id:
        for v in vendedores:
            if v.id == vendedor_id:
                return v
    for v in vendedores:
        if v.es_principal:
            return v
    return vendedores[0]


def _validar_vendedor(db, agencia_id: int, sucursal_id: int, vendedor_id: int) -> Vendedor:
    vendedor = (
        db.query(Vendedor)
        .filter(
            Vendedor.id == vendedor_id,
            Vendedor.agencia_id == agencia_id,
            Vendedor.sucursal_id == sucursal_id,
        )
        .first()
    )
    if not vendedor:
        raise HTTPException(status_code=400, detail="Vendedor inválido")
    return vendedor


def _vendedor_desde_query(request: Request) -> int | None:
    raw = request.query_params.get("vendedor")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _validar_sucursal(db, agencia_id: int, sucursal_id: int) -> Sucursal:
    sucursal = (
        db.query(Sucursal)
        .filter(Sucursal.id == sucursal_id, Sucursal.agencia_id == agencia_id)
        .first()
    )
    if not sucursal:
        raise HTTPException(status_code=400, detail="Sucursal inválida")
    return sucursal


def _sucursal_desde_query(request: Request) -> int | None:
    raw = request.query_params.get("sucursal")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _resolver_sucursal_navegacion(
    request: Request,
    db,
    agencia_id: int,
    sucursal_param: int | None = None,
) -> Sucursal:
    """
    Prioridad: ?sucursal= en URL → cookie persistida → sucursal principal.
    Si la URL trae ?sucursal= válido, marca la cookie para el middleware.
    """
    if sucursal_param is None:
        sucursal_param = _sucursal_desde_query(request)

    explicito_en_url = "sucursal" in request.query_params
    if explicito_en_url and sucursal_param is not None:
        sucursales = _listar_sucursales(db, agencia_id)
        for suc in sucursales:
            if suc.id == sucursal_param:
                request.state.sucursal_cookie_guardar = (agencia_id, suc.id)
                return suc

    persistida = leer_sucursal_cookie(request, agencia_id)
    if persistida is not None:
        sucursal = _resolver_sucursal_activa(db, agencia_id, persistida)
        if sucursal.id == persistida:
            return sucursal

    return _resolver_sucursal_activa(db, agencia_id, None)


def _contexto_sucursales(
    request: Request,
    db,
    agencia_id: int,
    sucursal_id: int | None = None,
) -> dict:
    sucursal_activa = _resolver_sucursal_navegacion(request, db, agencia_id, sucursal_id)
    return {
        "sucursales": _listar_sucursales(db, agencia_id),
        "sucursal_activa": sucursal_activa,
    }


def _contexto_configuracion(db, request: Request, agencia: Agencia, sucursal_id: int | None) -> dict:
    _migrar_linea_bot_desde_equipo(db, agencia)
    sucursales = _listar_sucursales(db, agencia.id)
    sucursal_activa = _resolver_sucursal_navegacion(request, db, agencia.id, sucursal_id)
    vendedores = _asegurar_vendedor_sucursal(db, sucursal_activa, agencia)
    vendedor_activo = _resolver_vendedor_activo(
        db, sucursal_activa, _vendedor_desde_query(request)
    )
    ctx = _contexto_base(request, agencia, "configuracion", sucursal_activa)
    ctx["color_primario"] = obtener_color_primario(agencia, sucursal_activa)
    ctx["modos_respuesta"] = [
        (modo, ETIQUETAS_MODO_RESPUESTA[modo]) for modo in sorted(MODOS_RESPUESTA_VALIDOS)
    ]
    ctx["modo_respuesta_actual"] = normalizar_modo_respuesta(agencia.modo_respuesta)
    ctx.update(
        {
            "sucursales": sucursales,
            "sucursal_activa": sucursal_activa,
            "vendedores": vendedores,
            "vendedor_activo": vendedor_activo,
            "vendedor_sin_celular": _vendedor_sin_celular(vendedor_activo),
            "agencia_sin_linea_bot": not _agencia_tiene_linea_bot(agencia),
            "nombre_comercial_actual": obtener_nombre_agencia_bot(
                agencia, sucursal_activa
            ),
            "asesor_virtual_actual": obtener_nombre_bot(agencia, sucursal_activa),
            "logo_bot_actual": obtener_logo_bot(agencia, sucursal_activa),
            "mensaje_bienvenida": mensaje_bienvenida_agencia(agencia, sucursal_activa),
            "nombre_bot_default": NOMBRE_BOT_DEFAULT,
            "nombre_agencia_default": NOMBRE_AGENCIA_DEFAULT,
        }
    )
    return ctx


async def _guardar_logo_agencia(agencia: Agencia, archivo_logo: UploadFile) -> str | None:
    if not archivo_logo or not archivo_logo.filename:
        return None
    extension = Path(archivo_logo.filename).suffix.lower()
    if extension not in EXTENSIONES_IMAGEN:
        return None
    destino = _static_base() / "uploads" / f"agencia_{agencia.id}"
    destino.mkdir(parents=True, exist_ok=True)
    nombre_archivo = f"logo{extension}"
    ruta = destino / nombre_archivo
    ruta.write_bytes(await archivo_logo.read())
    return f"/static/uploads/agencia_{agencia.id}/{nombre_archivo}"


@router.get("/{agencia_id}/manifest.webmanifest")
async def manifest_pwa(agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        color = agencia.color_primario or "#3B82F6"
        nombre_corto = (agencia.nombre or "Panel")[:12]
        iconos = [
            {
                "src": "/static/icons/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
            },
            {
                "src": "/static/icons/maskable.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "maskable",
            },
        ]
        if agencia.logo_url:
            iconos.insert(
                0,
                {
                    "src": agencia.logo_url,
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
            )
        return JSONResponse(
            {
                "name": f"{agencia.nombre} — Panel",
                "short_name": nombre_corto,
                "description": f"Panel de gestión de {agencia.nombre}",
                "start_url": f"/dashboard/{agencia_id}",
                "scope": f"/dashboard/{agencia_id}/",
                "display": "standalone",
                "orientation": "any",
                "background_color": "#0f172a",
                "theme_color": color,
                "lang": "es-AR",
                "icons": iconos,
            },
            media_type="application/manifest+json",
        )
    finally:
        db.close()


@router.get("/{agencia_id}/sw.js")
async def service_worker_js(agencia_id: int):
    contenido = (BASE_DIR / "static" / "sw.js").read_text(encoding="utf-8")
    return Response(
        content=contenido,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


@router.get("/{agencia_id}", response_class=HTMLResponse)
async def panel_principal(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_dashboard(request, db, agencia, "inicio", sucursal)
        sucursal_activa = ctx["sucursal_activa"]
        hoy = obtener_fecha_hoy_argentina()
        citas_hoy = _citas_del_dia(db, agencia_id, hoy, sucursal_activa.id)

        ctx.update(_metricas_agencia(db, agencia_id, sucursal_activa.id))
        _mapa_vend_inicio = _mapa_vendedores(db, agencia_id)
        ctx.update({
            "fecha_hoy": hoy.strftime("%d/%m/%Y"),
            "citas_hoy_lista": [
                _serializar_cita(c, l, None, _mapa_vend_inicio) for c, l in citas_hoy
            ],
            "citas_predictivas_inicial": _listar_citas_predictivas(
                db, agencia_id, sucursal_activa.id, "semana"
            ),
            "rango_predictivo_default": "semana",
        })
        return templates.TemplateResponse(request=request, name="dashboard/index.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/inventario", response_class=HTMLResponse)
async def listar_inventario(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_dashboard(request, db, agencia, "inventario", sucursal)
        sucursal_activa = ctx["sucursal_activa"]
        autos = _ordenar_autos(
            _query_autos_agencia(db, agencia_id).filter(
                Auto.sucursal_id == sucursal_activa.id
            )
        ).all()
        metricas = _metricas_agencia(db, agencia_id, sucursal_activa.id)
        ctx.update({
            "autos": autos,
            "total_stock": metricas["total_autos"],
            "disponibles": metricas["disponibles"],
        })
        return templates.TemplateResponse(request=request, name="dashboard/inventario.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/leads", response_class=HTMLResponse)
async def listar_leads(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_dashboard(request, db, agencia, "leads", sucursal)
        sucursal_activa = ctx["sucursal_activa"]
        leads = (
            db.query(ProspectoLead)
            .filter(
                ProspectoLead.agencia_id == agencia_id,
                ProspectoLead.sucursal_id == sucursal_activa.id,
            )
            .order_by(ProspectoLead.fecha_creacion.desc())
            .all()
        )
        metricas = _metricas_agencia(db, agencia_id, sucursal_activa.id)
        ctx.update({"leads": leads, "total_leads": metricas["total_leads"]})
        return templates.TemplateResponse(request=request, name="dashboard/leads.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/citas", response_class=HTMLResponse)
async def listar_citas(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_dashboard(request, db, agencia, "citas", sucursal)
        sucursal_activa = ctx["sucursal_activa"]
        ctx.update({
            "feed_inicial": _construir_feed_citas(db, agencia_id, sucursal_activa.id),
            "analitica_citas": _construir_analitica_citas(db, agencia_id, sucursal_activa.id),
            "vendedores_por_sucursal": _vendedores_por_sucursal(db, agencia_id),
            "estados_cita": ESTADOS_CITA,
            "estadisticas_inicial": _construir_estadisticas_vendedores(
                db, agencia_id, sucursal_activa.id, "semanal"
            ),
        })
        return templates.TemplateResponse(request=request, name="dashboard/citas.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/citas/feed")
async def feed_citas(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal_activa = _resolver_sucursal_navegacion(request, db, agencia_id, sucursal)
        return JSONResponse(_construir_feed_citas(db, agencia_id, sucursal_activa.id))
    finally:
        db.close()


@router.get("/{agencia_id}/citas/predictivas")
async def citas_predictivas(
    request: Request,
    agencia_id: int,
    rango: str = "semana",
    sucursal: int | None = None,
):
    if rango not in {"semana", "15dias", "mes"}:
        rango = "semana"
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal_activa = _resolver_sucursal_navegacion(request, db, agencia_id, sucursal)
        desde, hasta = _rango_predictivo_fechas(rango)
        citas = _listar_citas_predictivas(db, agencia_id, sucursal_activa.id, rango)
        return JSONResponse({
            "rango": rango,
            "desde": desde.isoformat(),
            "hasta": hasta.isoformat(),
            "total": len(citas),
            "citas": citas,
        })
    finally:
        db.close()


@router.get("/{agencia_id}/citas/analitica")
async def citas_analitica(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal_activa = _resolver_sucursal_navegacion(request, db, agencia_id, sucursal)
        return JSONResponse(_construir_analitica_citas(db, agencia_id, sucursal_activa.id))
    finally:
        db.close()


@router.get("/{agencia_id}/citas/estadisticas")
async def citas_estadisticas(
    agencia_id: int,
    periodo: str = "semanal",
    sucursal: int | None = None,
):
    """Métricas de conversión por vendedor. sucursal=None → todas las sucursales."""
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        return JSONResponse(
            _construir_estadisticas_vendedores(db, agencia_id, sucursal, periodo)
        )
    finally:
        db.close()


@router.get("/{agencia_id}/citas/calendario")
async def citas_calendario(
    request: Request,
    agencia_id: int,
    anio: int,
    mes: int,
    sucursal: int | None = None,
):
    if mes < 1 or mes > 12 or anio < 2000 or anio > 2100:
        return JSONResponse({"error": "Mes o año inválido"}, status_code=400)
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal_activa = _resolver_sucursal_navegacion(request, db, agencia_id, sucursal)
        return JSONResponse(
            _construir_calendario_mes(db, agencia_id, anio, mes, sucursal_activa.id)
        )
    finally:
        db.close()


@router.get("/{agencia_id}/citas/dia")
async def citas_por_dia(
    request: Request,
    agencia_id: int,
    fecha: str,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal_activa = _resolver_sucursal_navegacion(request, db, agencia_id, sucursal)
        try:
            dia = datetime.date.fromisoformat(fecha)
        except ValueError:
            return JSONResponse({"error": "Fecha inválida"}, status_code=400)
        mapa = _mapa_sucursales(db, agencia_id)
        mapa_vend = _mapa_vendedores(db, agencia_id)
        filas = _citas_del_dia(db, agencia_id, dia, sucursal_activa.id)
        citas = [_serializar_cita(c, l, mapa, mapa_vend) for c, l in filas]
        return JSONResponse({
            "fecha": dia.isoformat(),
            "fecha_label": dia.strftime("%d/%m/%Y"),
            "total": len(citas),
            "citas": citas,
        })
    finally:
        db.close()


@router.get("/{agencia_id}/citas/buscar")
async def buscar_citas(
    agencia_id: int,
    telefono: str | None = None,
    nombre: str | None = None,
    apellido: str | None = None,
    fecha: str | None = None,
    sucursal: int | None = None,
    vendedor: int | None = None,
):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        mapa = _mapa_sucursales(db, agencia_id)
        mapa_vend = _mapa_vendedores(db, agencia_id)
        fecha_filtro = None
        if fecha:
            try:
                fecha_filtro = datetime.date.fromisoformat(fecha)
            except ValueError:
                fecha_filtro = None
        resultados = _buscar_citas(
            db,
            agencia_id,
            telefono,
            nombre,
            apellido,
            fecha=fecha_filtro,
            sucursal_id=sucursal,
            vendedor_id=vendedor,
        )
        return JSONResponse({
            "total": len(resultados),
            "citas": [_serializar_cita(c, l, mapa, mapa_vend) for c, l in resultados],
        })
    finally:
        db.close()


@router.get("/{agencia_id}/citas/{cita_id}/historial")
async def historial_conversacion_cita(agencia_id: int, cita_id: int):
    db = SessionLocal()
    try:
        resultado = (
            db.query(Cita, ProspectoLead)
            .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
            .options(joinedload(ProspectoLead.auto))
            .filter(
                Cita.id == cita_id,
                ProspectoLead.agencia_id == agencia_id,
            )
            .first()
        )
        if not resultado:
            raise HTTPException(status_code=404, detail="Cita no encontrada")

        cita, lead = resultado
        nombre = " ".join(
            p for p in [lead.nombre_cliente, lead.apellido_cliente] if p and str(p).strip()
        ).strip() or "Cliente"

        mensajes = obtener_historial(
            agencia_id=agencia_id,
            telefono=lead.telefono_cliente,
            lead_id=lead.id,
        )
        resumen = resumen_comercial_lead(lead, cita)

        vend_nombre = None
        if getattr(cita, "vendedor_id", None):
            v = db.query(Vendedor).filter(Vendedor.id == cita.vendedor_id).first()
            vend_nombre = v.nombre if v else None

        return JSONResponse({
            "cita_id": cita.id,
            "cliente": nombre,
            "telefono": lead.telefono_cliente,
            "hora_cita": cita.hora_cita,
            "fecha_cita": cita.fecha_cita.strftime("%d/%m/%Y"),
            "auto_interes": cita.auto_interes,
            "patente_unidad": resumen.get("patente_unidad"),
            "estado": normalizar_estado_cita(cita.estado),
            "estado_label": etiqueta_estado_cita(cita.estado),
            "vendedor": vend_nombre,
            "resumen": resumen,
            "mensajes": mensajes,
        })
    finally:
        db.close()


@router.post("/{agencia_id}/citas/{cita_id}/estado")
async def actualizar_estado_cita(
    agencia_id: int,
    cita_id: int,
    estado: str = Form(...),
):
    nuevo = (estado or "").strip().lower()
    if nuevo not in ESTADOS_VALIDOS:
        return JSONResponse({"ok": False, "error": "estado_invalido"}, status_code=400)
    db = SessionLocal()
    try:
        cita = (
            db.query(Cita)
            .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
            .filter(Cita.id == cita_id, ProspectoLead.agencia_id == agencia_id)
            .first()
        )
        if not cita:
            return JSONResponse({"ok": False, "error": "no_encontrada"}, status_code=404)
        cita.estado = nuevo
        db.commit()
        return JSONResponse({
            "ok": True,
            "estado": nuevo,
            "estado_label": etiqueta_estado_cita(nuevo),
        })
    finally:
        db.close()


@router.get("/{agencia_id}/inventario/nuevo", response_class=HTMLResponse)
async def formulario_nuevo_auto(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_dashboard(request, db, agencia, "inventario", sucursal)
        ctx.update({"auto": None, "fotos": []})
        return templates.TemplateResponse(request=request, name="dashboard/auto_form.html", context=ctx)
    finally:
        db.close()


@router.post("/{agencia_id}/inventario/nuevo")
async def crear_auto(
    request: Request,
    agencia_id: int,
    sucursal_id: int = Form(...),
    marca: str = Form(...),
    modelo: str = Form(...),
    version: str = Form(""),
    ano: int = Form(...),
    tipo: str = Form("Sedan"),
    patente: str = Form(""),
    precio: float = Form(...),
    kilometros: int | None = Form(None),
    estado: str = Form("Disponible"),
):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal = _validar_sucursal(db, agencia_id, sucursal_id)
        auto = Auto(
            agencia_id=agencia_id,
            sucursal_id=sucursal.id,
            marca=marca.strip(),
            modelo=modelo.strip(),
            version=version.strip() or modelo.strip(),
            ano=ano,
            tipo=tipo.strip(),
            patente=patente.strip() or f"NUE{ano}",
            precio_referencia_ars=precio,
            kilometros=kilometros,
            estado=estado,
            foto_principal_url=None,
        )
        db.add(auto)
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario/{auto.id}/editar?ok=creado",
            status_code=303,
        )
    finally:
        db.close()


@router.get("/{agencia_id}/inventario/{auto_id}/editar", response_class=HTMLResponse)
async def formulario_editar_auto(request: Request, agencia_id: int, auto_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        auto = (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
        if not auto:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        fotos = sincronizar_fotos_auto(auto, _static_base())
        db.commit()
        ctx = _contexto_dashboard(request, db, agencia, "inventario")
        ctx.update({
            "auto": auto,
            "fotos": fotos,
            "foto_portada": obtener_portada_auto(auto),
        })
        return templates.TemplateResponse(request=request, name="dashboard/auto_form.html", context=ctx)
    finally:
        db.close()


@router.post("/{agencia_id}/inventario/{auto_id}/editar")
async def actualizar_auto(
    agencia_id: int,
    auto_id: int,
    sucursal_id: int = Form(...),
    marca: str = Form(...),
    modelo: str = Form(...),
    version: str = Form(""),
    ano: int = Form(...),
    tipo: str = Form("Sedan"),
    patente: str = Form(...),
    precio: float = Form(...),
    kilometros: int | None = Form(None),
    estado: str = Form("Disponible"),
):
    db = SessionLocal()
    try:
        auto = (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
        if not auto:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        sucursal = _validar_sucursal(db, agencia_id, sucursal_id)
        auto.sucursal_id = sucursal.id
        auto.marca = marca.strip()
        auto.modelo = modelo.strip()
        auto.version = version.strip() or modelo.strip()
        auto.ano = ano
        auto.tipo = tipo.strip()
        auto.patente = patente.strip()
        auto.precio_referencia_ars = precio
        auto.kilometros = kilometros
        auto.estado = estado
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario/{auto_id}/editar?ok=guardado",
            status_code=303,
        )
    finally:
        db.close()


@router.post("/{agencia_id}/inventario/{auto_id}/eliminar")
async def eliminar_auto(agencia_id: int, auto_id: int):
    db = SessionLocal()
    try:
        auto = (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
        if auto:
            db.delete(auto)
            db.commit()
        return RedirectResponse(url=f"/dashboard/{agencia_id}/inventario?ok=eliminado", status_code=303)
    finally:
        db.close()


@router.post("/{agencia_id}/inventario/{auto_id}/fotos/upload")
async def subir_fotos(
    request: Request,
    agencia_id: int,
    auto_id: int,
    archivos: list[UploadFile] = File(...),
):
    db = SessionLocal()
    try:
        auto = (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
        if not auto:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")

        if not archivos:
            raise HTTPException(status_code=400, detail="No se recibieron archivos")

        destino = directorio_upload(agencia_id, auto_id, _static_base())
        subidas = 0
        errores: list[str] = []

        for archivo in archivos:
            if not archivo.filename:
                continue
            extension = Path(archivo.filename).suffix.lower()
            if extension not in EXTENSIONES_IMAGEN:
                errores.append(f"{archivo.filename}: formato no soportado")
                continue

            nombre = f"{uuid.uuid4().hex}{extension}"
            ruta = destino / nombre
            ruta.write_bytes(await archivo.read())
            url = url_publica_upload(agencia_id, auto_id, nombre)
            agregar_foto_a_auto(auto, url)
            subidas += 1

        if subidas == 0:
            detalle = errores[0] if errores else "Ningún archivo válido"
            if request.headers.get("X-Upload-Async") == "1":
                return JSONResponse(
                    {"ok": False, "error": detalle},
                    status_code=400,
                )
            raise HTTPException(status_code=400, detail=detalle)

        db.commit()
        if request.headers.get("X-Upload-Async") == "1":
            return JSONResponse({
                "ok": True,
                "subidas": subidas,
                "fotos": obtener_fotos_auto(auto),
                "portada": obtener_portada_auto(auto),
                "errores": errores,
            })
        params = f"?ok=fotos&n={subidas}"
        if errores:
            params += f"&omitidos={len(errores)}"
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario/{auto_id}/editar{params}",
            status_code=303,
        )
    finally:
        db.close()


@router.post("/{agencia_id}/inventario/{auto_id}/fotos/portada")
async def definir_portada(
    agencia_id: int,
    auto_id: int,
    foto_url: str = Form(...),
):
    db = SessionLocal()
    try:
        auto = (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
        if not auto:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        if not definir_portada_auto(auto, foto_url):
            raise HTTPException(status_code=404, detail="Foto no encontrada")
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario/{auto_id}/editar?ok=portada",
            status_code=303,
        )
    finally:
        db.close()


@router.post("/{agencia_id}/inventario/{auto_id}/fotos/eliminar")
async def eliminar_foto(
    agencia_id: int,
    auto_id: int,
    foto_url: str = Form(...),
):
    db = SessionLocal()
    try:
        auto = (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
        if not auto:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
        if not eliminar_foto_de_auto(auto, foto_url):
            raise HTTPException(status_code=404, detail="Foto no encontrada")
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario/{auto_id}/editar?ok=foto_eliminada",
            status_code=303,
        )
    finally:
        db.close()


@router.get("/{agencia_id}/importar")
async def redirigir_importar(agencia_id: int):
    return RedirectResponse(url=f"/dashboard/{agencia_id}/inventario", status_code=302)


@router.post("/{agencia_id}/inventario/importar")
async def importar_stock_inventario(
    agencia_id: int,
    archivo: UploadFile = File(...),
):
    contenido_bytes = await archivo.read()
    nombre = (archivo.filename or "").lower()

    if not (nombre.endswith(".csv") or nombre.endswith(".txt") or "csv" in (archivo.content_type or "")):
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario?error=formato",
            status_code=303,
        )

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = contenido_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            texto = None
    if texto is None:
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario?error=codificacion",
            status_code=303,
        )

    resultado = importar_csv(agencia_id, texto)

    if resultado.total == 0:
        detalle = resultado.errores[0] if resultado.errores else "sin_vehiculos"
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/inventario?error=import&msg={detalle[:80]}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/dashboard/{agencia_id}/inventario?ok=import&total={resultado.total}",
        status_code=303,
    )


@router.get("/{agencia_id}/configuracion", response_class=HTMLResponse)
async def pagina_configuracion(
    request: Request,
    agencia_id: int,
    sucursal: int | None = None,
):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_configuracion(db, request, agencia, sucursal)
        vendedor_query = _vendedor_desde_query(request)
        if ctx.get("vendedor_activo") and vendedor_query is None:
            v = ctx["vendedor_activo"]
            suc = ctx["sucursal_activa"]
            return RedirectResponse(
                url=f"/dashboard/{agencia_id}/configuracion?sucursal={suc.id}&vendedor={v.id}",
                status_code=302,
            )
        return templates.TemplateResponse(
            request=request,
            name="dashboard/configuracion.html",
            context=ctx,
        )
    finally:
        db.close()


@router.get("/{agencia_id}/marca", response_class=HTMLResponse)
async def pagina_marca_legacy(agencia_id: int, sucursal: int | None = None):
    url = f"/dashboard/{agencia_id}/configuracion"
    if sucursal:
        url += f"?sucursal={sucursal}"
    return RedirectResponse(url=url, status_code=301)


@router.post("/{agencia_id}/configuracion")
async def guardar_configuracion(
    agencia_id: int,
    sucursal_id: int = Form(...),
    nombre: str = Form(...),
    direccion: str = Form(""),
):
    """Guarda los datos de la SUCURSAL (nombre comercial y dirección)."""
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        sucursal = _validar_sucursal(db, agencia_id, sucursal_id)

        sucursal.nombre_comercial = nombre.strip() or None
        sucursal.direccion = direccion.strip() or None
        # La dirección oficial del bot vive en la agencia; solo rellenarla si falta.
        if sucursal.es_principal and sucursal.direccion and not agencia.direccion:
            agencia.direccion = sucursal.direccion

        db.commit()
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/configuracion?sucursal={sucursal.id}&ok=guardado",
            status_code=303,
        )
    finally:
        db.close()


@router.post("/{agencia_id}/configuracion/agencia")
async def guardar_configuracion_agencia(
    agencia_id: int,
    nombre_agencia: str = Form(...),
    direccion_agencia: str = Form(""),
    whatsapp_phone_number_id: str = Form(...),
    telefono_contacto: str = Form(""),
    nombre_bot: str = Form(""),
    color_primario: str = Form("#3B82F6"),
    modo_respuesta: str = Form("texto"),
    sucursal_id: int = Form(...),
):
    """Guarda la línea del bot y la identidad de la agencia."""
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        linea_bot = _normalizar_telefono(whatsapp_phone_number_id)
        if not linea_bot:
            return RedirectResponse(
                url=(
                    f"/dashboard/{agencia_id}/configuracion"
                    f"?sucursal={sucursal_id}&error=linea_bot_vacia"
                ),
                status_code=303,
            )
        if not es_phone_number_id_meta(linea_bot) and not linea_bot.startswith("reg_"):
            return RedirectResponse(
                url=(
                    f"/dashboard/{agencia_id}/configuracion"
                    f"?sucursal={sucursal_id}&error=linea_bot_invalida"
                ),
                status_code=303,
            )

        otra = (
            db.query(Agencia)
            .filter(
                Agencia.id != agencia_id,
                Agencia.whatsapp_phone_number_id == linea_bot,
            )
            .first()
        )
        if otra:
            return RedirectResponse(
                url=(
                    f"/dashboard/{agencia_id}/configuracion"
                    f"?sucursal={sucursal_id}&error=linea_bot_duplicada"
                ),
                status_code=303,
            )

        _liberar_linea_bot_en_equipo(db, agencia_id, linea_bot)

        nombre_ok = nombre_agencia.strip() or agencia.nombre
        agencia.nombre = nombre_ok
        agencia.nombre_agencia = nombre_ok
        agencia.direccion = direccion_agencia.strip() or None
        agencia.whatsapp_phone_number_id = linea_bot

        contacto = _normalizar_telefono(telefono_contacto)
        if contacto and (
            es_phone_number_id_meta(contacto)
            or _normalizar_telefono(contacto) == linea_bot
        ):
            return RedirectResponse(
                url=(
                    f"/dashboard/{agencia_id}/configuracion"
                    f"?sucursal={sucursal_id}&error=contacto_es_linea_bot"
                ),
                status_code=303,
            )
        agencia.telefono_contacto = contacto or None
        agencia.nombre_bot = nombre_bot.strip() or None
        agencia.color_primario = color_primario.strip() or "#3B82F6"
        agencia.modo_respuesta = normalizar_modo_respuesta(modo_respuesta)

        # La identidad del bot vive en la agencia; la sucursal principal solo
        # hereda dirección si está vacía (no pisa nombre comercial del bot).
        sucursal_principal = _resolver_sucursal_activa(db, agencia_id)
        if sucursal_principal and agencia.direccion and not sucursal_principal.direccion:
            sucursal_principal.direccion = agencia.direccion

        db.commit()
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/configuracion?sucursal={sucursal_id}&ok=agencia",
            status_code=303,
        )
    finally:
        db.close()


@router.post("/{agencia_id}/configuracion/sucursales")
async def crear_sucursal(agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        sucursales = _listar_sucursales(db, agencia_id)
        siguiente = (max(s.numero for s in sucursales) if sucursales else 0) + 1
        principal = _resolver_sucursal_activa(db, agencia_id)
        sucursal = Sucursal(
            agencia_id=agencia_id,
            numero=siguiente,
            nombre=f"Sucursal {siguiente}",
            nombre_comercial=obtener_nombre_agencia_bot(agencia, principal),
            asesor_virtual_nombre=obtener_nombre_bot(agencia, principal),
            color_primario=obtener_color_primario(agencia, principal),
            telefono_whatsapp="",
            es_principal=False,
        )
        db.add(sucursal)
        db.flush()
        db.add(
            Vendedor(
                agencia_id=agencia_id,
                sucursal_id=sucursal.id,
                nombre="Vendedor Principal",
                asesor_virtual_nombre=None,
                nombre_comercial=None,
                color_primario=None,
                logo_url=None,
                telefono_whatsapp=f"sin-linea-suc-{sucursal.id}",
                es_principal=True,
                activo=True,
            )
        )
        db.commit()
        db.refresh(sucursal)
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/configuracion?sucursal={sucursal.id}&ok=sucursal",
            status_code=303,
        )
    finally:
        db.close()


def _telefono_en_uso(db, agencia_id: int, telefono: str, excluir_id: int | None) -> bool:
    if not telefono:
        return False
    q = db.query(Vendedor).filter(Vendedor.telefono_whatsapp == telefono)
    if excluir_id:
        q = q.filter(Vendedor.id != excluir_id)
    if db.query(q.exists()).scalar():
        return True
    agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
    if agencia and _normalizar_telefono(agencia.whatsapp_phone_number_id) == _normalizar_telefono(
        telefono
    ):
        return True
    return False


@router.post("/{agencia_id}/configuracion/vendedores")
async def crear_vendedor(agencia_id: int, sucursal_id: int = Form(...)):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal = _validar_sucursal(db, agencia_id, sucursal_id)
        existentes = _listar_vendedores(db, sucursal.id)
        es_primero = not existentes
        vendedor = Vendedor(
            agencia_id=agencia_id,
            sucursal_id=sucursal.id,
            nombre="Vendedor Principal" if es_primero else f"Vendedor {len(existentes) + 1}",
            asesor_virtual_nombre=None,
            nombre_comercial=None,
            color_primario=None,
            logo_url=None,
            telefono_whatsapp=f"sin-linea-{uuid.uuid4().hex[:10]}",
            es_principal=not existentes,
            activo=True,
        )
        db.add(vendedor)
        db.commit()
        db.refresh(vendedor)
        return RedirectResponse(
            url=(
                f"/dashboard/{agencia_id}/configuracion"
                f"?sucursal={sucursal.id}&vendedor={vendedor.id}&ok=vendedor"
            ),
            status_code=303,
        )
    finally:
        db.close()


@router.post("/{agencia_id}/configuracion/vendedores/{vendedor_id}")
async def guardar_vendedor(
    agencia_id: int,
    vendedor_id: int,
    sucursal_id: int = Form(...),
    nombre: str = Form(""),
    telefono_whatsapp: str = Form(""),
):
    """Guarda datos humanos del vendedor (nombre + celular personal)."""
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        sucursal = _validar_sucursal(db, agencia_id, sucursal_id)
        vendedor = _validar_vendedor(db, agencia_id, sucursal.id, vendedor_id)

        tel = _normalizar_telefono(telefono_whatsapp)
        if tel:
            if es_phone_number_id_meta(tel) or _normalizar_telefono(
                agencia.whatsapp_phone_number_id
            ) == tel:
                return RedirectResponse(
                    url=(
                        f"/dashboard/{agencia_id}/configuracion"
                        f"?sucursal={sucursal.id}&vendedor={vendedor.id}"
                        f"&error=telefono_es_linea_bot"
                    ),
                    status_code=303,
                )
            if not parece_celular_argentino(tel) and len(re.sub(r"\D", "", tel)) < 8:
                return RedirectResponse(
                    url=(
                        f"/dashboard/{agencia_id}/configuracion"
                        f"?sucursal={sucursal.id}&vendedor={vendedor.id}"
                        f"&error=telefono_invalido"
                    ),
                    status_code=303,
                )
            if _telefono_en_uso(db, agencia_id, tel, vendedor.id):
                return RedirectResponse(
                    url=(
                        f"/dashboard/{agencia_id}/configuracion"
                        f"?sucursal={sucursal.id}&vendedor={vendedor.id}&error=telefono_duplicado"
                    ),
                    status_code=303,
                )
            vendedor.telefono_whatsapp = tel
        else:
            vendedor.telefono_whatsapp = f"sin-linea-{vendedor.id}"

        vendedor.nombre = nombre.strip() or vendedor.nombre

        db.commit()
        return RedirectResponse(
            url=(
                f"/dashboard/{agencia_id}/configuracion"
                f"?sucursal={sucursal.id}&vendedor={vendedor.id}&ok=guardado"
            ),
            status_code=303,
        )
    finally:
        db.close()


@router.post("/{agencia_id}/configuracion/vendedores/{vendedor_id}/eliminar")
async def eliminar_vendedor(agencia_id: int, vendedor_id: int, sucursal_id: int = Form(...)):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        sucursal = _validar_sucursal(db, agencia_id, sucursal_id)
        vendedor = _validar_vendedor(db, agencia_id, sucursal.id, vendedor_id)

        restantes = _listar_vendedores(db, sucursal.id)
        if len(restantes) <= 1:
            return RedirectResponse(
                url=(
                    f"/dashboard/{agencia_id}/configuracion"
                    f"?sucursal={sucursal.id}&error=ultimo_vendedor"
                ),
                status_code=303,
            )

        era_principal = vendedor.es_principal
        db.delete(vendedor)
        db.flush()
        if era_principal:
            nuevo = (
                db.query(Vendedor)
                .filter(Vendedor.sucursal_id == sucursal.id)
                .order_by(Vendedor.id)
                .first()
            )
            if nuevo:
                nuevo.es_principal = True
        db.commit()
        return RedirectResponse(
            url=f"/dashboard/{agencia_id}/configuracion?sucursal={sucursal.id}&ok=vendedor_eliminado",
            status_code=303,
        )
    finally:
        db.close()


async def _guardar_logo_vendedor(
    agencia_id: int, vendedor: Vendedor, archivo_logo: UploadFile
) -> str | None:
    if not archivo_logo or not archivo_logo.filename:
        return None
    extension = Path(archivo_logo.filename).suffix.lower()
    if extension not in EXTENSIONES_IMAGEN:
        return None
    destino = _static_base() / "uploads" / f"agencia_{agencia_id}"
    destino.mkdir(parents=True, exist_ok=True)
    nombre_archivo = f"vendedor_{vendedor.id}{extension}"
    ruta = destino / nombre_archivo
    ruta.write_bytes(await archivo_logo.read())
    return f"/static/uploads/agencia_{agencia_id}/{nombre_archivo}"


@router.post("/{agencia_id}/configuracion/vendedores/{vendedor_id}/logo")
async def subir_logo_vendedor(
    agencia_id: int,
    vendedor_id: int,
    archivo_logo: UploadFile = File(...),
):
    db = SessionLocal()
    try:
        vendedor = (
            db.query(Vendedor)
            .filter(Vendedor.id == vendedor_id, Vendedor.agencia_id == agencia_id)
            .first()
        )
        if not vendedor:
            return JSONResponse({"ok": False, "error": "vendedor"}, status_code=404)
        logo_url = await _guardar_logo_vendedor(agencia_id, vendedor, archivo_logo)
        if not logo_url:
            return JSONResponse({"ok": False, "error": "formato_invalido"}, status_code=400)
        vendedor.logo_url = logo_url
        db.commit()
        return JSONResponse({"ok": True, "logo_url": logo_url})
    finally:
        db.close()


@router.post("/{agencia_id}/configuracion/logo")
async def subir_logo_configuracion(agencia_id: int, archivo_logo: UploadFile = File(...)):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        logo_url = await _guardar_logo_agencia(agencia, archivo_logo)
        if not logo_url:
            return JSONResponse({"ok": False, "error": "formato_invalido"}, status_code=400)
        agencia.logo_url = logo_url
        db.commit()
        return JSONResponse({"ok": True, "logo_url": logo_url})
    finally:
        db.close()


@router.post("/{agencia_id}/marca")
async def guardar_marca_legacy(
    agencia_id: int,
    nombre: str = Form(...),
    nombre_bot: str = Form(""),
    color_primario: str = Form("#3B82F6"),
    modo_respuesta: str = Form("texto"),
    archivo_logo: UploadFile | None = File(None),
):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        agencia.nombre = nombre.strip()
        agencia.nombre_bot = nombre_bot.strip() or None
        agencia.color_primario = color_primario.strip()
        agencia.modo_respuesta = normalizar_modo_respuesta(modo_respuesta)

        logo_url = await _guardar_logo_agencia(agencia, archivo_logo)
        if logo_url:
            agencia.logo_url = logo_url

        db.commit()
        return RedirectResponse(url=f"/dashboard/{agencia_id}/configuracion?ok=guardado", status_code=303)
    finally:
        db.close()


@router.post("/{agencia_id}/marca/logo")
async def subir_logo_marca_legacy(agencia_id: int, archivo_logo: UploadFile = File(...)):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        logo_url = await _guardar_logo_agencia(agencia, archivo_logo)
        if not logo_url:
            return JSONResponse({"ok": False, "error": "formato_invalido"}, status_code=400)
        agencia.logo_url = logo_url
        db.commit()
        return JSONResponse({"ok": True, "logo_url": logo_url})
    finally:
        db.close()


@router.post("/{agencia_id}/suscripcion/renovacion-automatica")
async def activar_renovacion_automatica(
    agencia_id: int,
    payer_email: str = Form(...),
):
    """
    Crea una preapproval en Mercado Pago y redirige al checkout (init_point).
    El cliente autoriza el débito mensual; los cobros renovarán vía webhook.
    """
    if not mercadopago_configurado():
        raise HTTPException(
            status_code=503,
            detail="Mercado Pago no está configurado. Contactá al soporte.",
        )

    email = payer_email.strip()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Ingresá un email válido.")

    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        if agencia.mp_renovacion_automatica and agencia.mp_preapproval_id:
            return RedirectResponse(
                url=f"/dashboard/{agencia_id}?suscripcion=ya_activa",
                status_code=303,
            )

        try:
            respuesta = crear_suscripcion_recurrente(agencia, email)
        except MercadoPagoError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        init_point = respuesta.get("init_point") or respuesta.get("sandbox_init_point")
        if not init_point:
            raise HTTPException(
                status_code=502,
                detail="Mercado Pago no devolvió URL de checkout.",
            )

        preapproval_id = respuesta.get("id")
        if preapproval_id:
            agencia.mp_preapproval_id = str(preapproval_id)
            db.commit()

        return RedirectResponse(url=init_point, status_code=303)
    finally:
        db.close()


@router.post("/{agencia_id}/suscripcion/pago-unico")
async def pagar_mes_actual(
    agencia_id: int,
    payer_email: str = Form(...),
):
    """Genera preferencia de pago único y redirige al checkout de Mercado Pago."""
    if not mercadopago_configurado():
        raise HTTPException(
            status_code=503,
            detail="Mercado Pago no está configurado. Contactá al soporte.",
        )

    email = payer_email.strip()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Ingresá un email válido.")

    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        try:
            respuesta = crear_preferencia_pago_unico(agencia, email)
        except MercadoPagoError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        init_point = respuesta.get("init_point") or respuesta.get("sandbox_init_point")
        if not init_point:
            raise HTTPException(
                status_code=502,
                detail="Mercado Pago no devolvió URL de checkout.",
            )

        return RedirectResponse(url=init_point, status_code=303)
    finally:
        db.close()
