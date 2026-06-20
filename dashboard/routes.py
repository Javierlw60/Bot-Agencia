import datetime
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from dashboard.import_stock import importar_csv
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
from mercadopago_config import mercadopago_configurado, obtener_config_mercadopago
from mercadopago_servicio import (
    MercadoPagoError,
    crear_preferencia_pago_unico,
    crear_suscripcion_recurrente,
)
from models.database import Agencia, Auto, Cita, ProspectoLead, SessionLocal
from modo_respuesta import (
    ETIQUETAS_MODO_RESPUESTA,
    MODOS_RESPUESTA_VALIDOS,
    normalizar_modo_respuesta,
)
from personalizacion_bot import (
    NOMBRE_AGENCIA_DEFAULT,
    NOMBRE_BOT_DEFAULT,
    mensaje_bienvenida_agencia,
)
from suscripcion_agencias import ESTADO_ACTIVO, ESTADO_BLOQUEADO, agencia_vence_pronto

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _obtener_agencia(db, agencia_id: int) -> Agencia:
    agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
    if not agencia:
        raise HTTPException(status_code=404, detail="Agencia no encontrada")
    return agencia


def _contexto_base(request: Request, agencia: Agencia, pagina: str) -> dict:
    return {
        "request": request,
        "agencia": agencia,
        "pagina_activa": pagina,
        "color_primario": agencia.color_primario or "#3B82F6",
    }


def _ordenar_autos(query):
    return query.order_by(func.lower(Auto.marca), func.lower(Auto.modelo))


def _query_autos_agencia(db, agencia_id: int):
    return db.query(Auto).filter(Auto.agencia_id == agencia_id)


def _metricas_agencia(db, agencia_id: int) -> dict:
    """Conteos reales desde la BD; única fuente de verdad para el dashboard."""
    hoy = obtener_fecha_hoy_argentina()
    autos = _query_autos_agencia(db, agencia_id)
    return {
        "total_autos": autos.count(),
        "disponibles": autos.filter(func.lower(Auto.estado) == "disponible").count(),
        "total_leads": (
            db.query(ProspectoLead)
            .filter(ProspectoLead.agencia_id == agencia_id)
            .count()
        ),
        "citas_hoy": len(_citas_del_dia(db, agencia_id, hoy)),
    }


def _citas_del_dia(db, agencia_id: int, fecha: datetime.date) -> list[tuple[Cita, ProspectoLead]]:
    return (
        db.query(Cita, ProspectoLead)
        .join(ProspectoLead, Cita.cliente_id == ProspectoLead.id)
        .filter(
            ProspectoLead.agencia_id == agencia_id,
            Cita.fecha_cita == fecha,
        )
        .order_by(Cita.hora_cita)
        .all()
    )


def _nombre_cliente_lead(lead: ProspectoLead) -> str:
    partes = [lead.nombre_cliente, lead.apellido_cliente]
    nombre = " ".join(p for p in partes if p and str(p).strip()).strip()
    return nombre or "Sin nombre"


def _serializar_cita(cita: Cita, lead: ProspectoLead) -> dict:
    return {
        "id": cita.id,
        "hora": cita.hora_cita,
        "cliente": _nombre_cliente_lead(lead),
        "telefono": lead.telefono_cliente,
        "auto": cita.auto_interes or "Sin auto especificado",
        "estado": cita.estado or "confirmada",
        "recordatorio_enviado": bool(cita.recordatorio_enviado),
    }


def _construir_feed_citas(db, agencia_id: int) -> dict:
    hoy = obtener_fecha_hoy_argentina()
    manana = hoy + datetime.timedelta(days=1)
    citas_hoy = _citas_del_dia(db, agencia_id, hoy)
    citas_manana = _citas_del_dia(db, agencia_id, manana)
    return {
        "fecha_hoy": hoy.strftime("%d/%m/%Y"),
        "fecha_manana": manana.strftime("%d/%m/%Y"),
        "citas_hoy": [_serializar_cita(c, l) for c, l in citas_hoy],
        "citas_manana": [_serializar_cita(c, l) for c, l in citas_manana],
    }


async def _guardar_logo_agencia(agencia: Agencia, archivo_logo: UploadFile) -> str | None:
    if not archivo_logo or not archivo_logo.filename:
        return None
    extension = Path(archivo_logo.filename).suffix.lower()
    if extension not in EXTENSIONES_IMAGEN:
        return None
    destino = BASE_DIR / "static" / "uploads" / f"agencia_{agencia.id}"
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
async def panel_principal(request: Request, agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_base(request, agencia, "inicio")
        ctx.update(_metricas_agencia(db, agencia_id))
        return templates.TemplateResponse(request=request, name="dashboard/index.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/inventario", response_class=HTMLResponse)
async def listar_inventario(request: Request, agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        autos = _ordenar_autos(_query_autos_agencia(db, agencia_id)).all()
        metricas = _metricas_agencia(db, agencia_id)
        ctx = _contexto_base(request, agencia, "inventario")
        ctx.update({
            "autos": autos,
            "total_stock": metricas["total_autos"],
            "disponibles": metricas["disponibles"],
        })
        return templates.TemplateResponse(request=request, name="dashboard/inventario.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/leads", response_class=HTMLResponse)
async def listar_leads(request: Request, agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        leads = (
            db.query(ProspectoLead)
            .filter(ProspectoLead.agencia_id == agencia_id)
            .order_by(ProspectoLead.fecha_creacion.desc())
            .all()
        )
        ctx = _contexto_base(request, agencia, "leads")
        metricas = _metricas_agencia(db, agencia_id)
        ctx.update({"leads": leads, "total_leads": metricas["total_leads"]})
        return templates.TemplateResponse(request=request, name="dashboard/leads.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/citas", response_class=HTMLResponse)
async def listar_citas(request: Request, agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_base(request, agencia, "citas")
        ctx.update({
            "feed_inicial": _construir_feed_citas(db, agencia_id),
        })
        return templates.TemplateResponse(request=request, name="dashboard/citas.html", context=ctx)
    finally:
        db.close()


@router.get("/{agencia_id}/citas/feed")
async def feed_citas(agencia_id: int):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        return JSONResponse(_construir_feed_citas(db, agencia_id))
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
        resumen = resumen_comercial_lead(lead)

        return JSONResponse({
            "cita_id": cita.id,
            "cliente": nombre,
            "telefono": lead.telefono_cliente,
            "hora_cita": cita.hora_cita,
            "fecha_cita": cita.fecha_cita.strftime("%d/%m/%Y"),
            "auto_interes": cita.auto_interes,
            "resumen": resumen,
            "mensajes": mensajes,
        })
    finally:
        db.close()


@router.get("/{agencia_id}/inventario/nuevo", response_class=HTMLResponse)
async def formulario_nuevo_auto(request: Request, agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_base(request, agencia, "inventario")
        ctx.update({"auto": None, "fotos": []})
        return templates.TemplateResponse(request=request, name="dashboard/auto_form.html", context=ctx)
    finally:
        db.close()


@router.post("/{agencia_id}/inventario/nuevo")
async def crear_auto(
    request: Request,
    agencia_id: int,
    marca: str = Form(...),
    modelo: str = Form(...),
    version: str = Form(""),
    ano: int = Form(...),
    tipo: str = Form("Sedan"),
    patente: str = Form(""),
    precio: float = Form(...),
    estado: str = Form("Disponible"),
):
    db = SessionLocal()
    try:
        _obtener_agencia(db, agencia_id)
        auto = Auto(
            agencia_id=agencia_id,
            marca=marca.strip(),
            modelo=modelo.strip(),
            version=version.strip() or modelo.strip(),
            ano=ano,
            tipo=tipo.strip(),
            patente=patente.strip() or f"NUE{ano}",
            precio_referencia_ars=precio,
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
        fotos = sincronizar_fotos_auto(auto, BASE_DIR / "static")
        db.commit()
        ctx = _contexto_base(request, agencia, "inventario")
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
    marca: str = Form(...),
    modelo: str = Form(...),
    version: str = Form(""),
    ano: int = Form(...),
    tipo: str = Form("Sedan"),
    patente: str = Form(...),
    precio: float = Form(...),
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
        auto.marca = marca.strip()
        auto.modelo = modelo.strip()
        auto.version = version.strip() or modelo.strip()
        auto.ano = ano
        auto.tipo = tipo.strip()
        auto.patente = patente.strip()
        auto.precio_referencia_ars = precio
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

        destino = directorio_upload(agencia_id, auto_id, BASE_DIR / "static")
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


@router.get("/{agencia_id}/marca", response_class=HTMLResponse)
async def pagina_marca(request: Request, agencia_id: int):
    db = SessionLocal()
    try:
        agencia = _obtener_agencia(db, agencia_id)
        ctx = _contexto_base(request, agencia, "marca")
        ctx["modos_respuesta"] = [
            (modo, ETIQUETAS_MODO_RESPUESTA[modo]) for modo in sorted(MODOS_RESPUESTA_VALIDOS)
        ]
        ctx["modo_respuesta_actual"] = normalizar_modo_respuesta(agencia.modo_respuesta)
        ctx.update(
            {
                "mensaje_bienvenida": mensaje_bienvenida_agencia(agencia),
                "nombre_bot_default": NOMBRE_BOT_DEFAULT,
                "nombre_agencia_default": NOMBRE_AGENCIA_DEFAULT,
            }
        )
        return templates.TemplateResponse(request=request, name="dashboard/marca.html", context=ctx)
    finally:
        db.close()


@router.post("/{agencia_id}/marca")
async def guardar_marca(
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
        return RedirectResponse(url=f"/dashboard/{agencia_id}/marca?ok=guardado", status_code=303)
    finally:
        db.close()


@router.post("/{agencia_id}/marca/logo")
async def subir_logo_marca(agencia_id: int, archivo_logo: UploadFile = File(...)):
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
