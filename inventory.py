import re

from sqlalchemy import func

from dashboard.media import obtener_fotos_auto
from models.database import Agencia, Auto, ProspectoLead, SessionLocal, Sucursal, Vendedor

MARCA_ALIASES = {
    "vw": "volkswagen",
    "volks": "volkswagen",
    "volkswagen": "volkswagen",
    "fiat": "fiat",
}


def _expandir_aliases_marca(texto: str) -> str:
    resultado = texto.lower()
    for alias, marca in MARCA_ALIASES.items():
        resultado = re.sub(rf"\b{re.escape(alias)}\b", marca, resultado)
    return resultado


def _normalizar_linea_whatsapp(valor: str | None) -> str:
    if not valor:
        return ""
    return re.sub(r"\D", "", str(valor).strip())


def _texto_linea(valor: str | None) -> str:
    return str(valor).strip() if valor is not None else ""


def _lineas_whatsapp_coinciden(guardado: str | None, buscado: str | None) -> bool:
    """Compara Phone Number ID exacto o solo-dígitos (tolerante a basura)."""
    a = _texto_linea(guardado)
    b = _texto_linea(buscado)
    if not a or not b:
        return False
    if a == b:
        return True
    na, nb = _normalizar_linea_whatsapp(a), _normalizar_linea_whatsapp(b)
    return bool(na and nb and na == nb)


def _es_placeholder_linea_bot(valor: str | None) -> bool:
    texto = _texto_linea(valor)
    if not texto:
        return True
    return texto.startswith("reg_") or texto.startswith("sin-linea")


def _mapa_nombres_sucursales(db, agencia_id: int) -> dict[int, str]:
    sucursales = (
        db.query(Sucursal)
        .filter(Sucursal.agencia_id == agencia_id)
        .order_by(Sucursal.numero)
        .all()
    )
    return {s.id: s.nombre for s in sucursales}


def obtener_nombre_sucursal(agencia_id: int, sucursal_id: int | None) -> str:
    if not sucursal_id:
        return "Sucursal principal"
    db = SessionLocal()
    try:
        suc = (
            db.query(Sucursal)
            .filter(Sucursal.id == sucursal_id, Sucursal.agencia_id == agencia_id)
            .first()
        )
        return suc.nombre if suc else "Sucursal"
    finally:
        db.close()


def _vendedor_principal_de_sucursal(db, sucursal: Sucursal | None) -> Vendedor | None:
    if not sucursal:
        return None
    principal = (
        db.query(Vendedor)
        .filter(
            Vendedor.sucursal_id == sucursal.id,
            Vendedor.es_principal.is_(True),
        )
        .order_by(Vendedor.id)
        .first()
    )
    if principal:
        return principal
    return (
        db.query(Vendedor)
        .filter(Vendedor.sucursal_id == sucursal.id)
        .order_by(Vendedor.id)
        .first()
    )


def _buscar_agencia_por_phone_id(db, phone_number_id: str) -> Agencia | None:
    buscado = _texto_linea(phone_number_id)
    if not buscado:
        return None

    exacta = (
        db.query(Agencia)
        .filter(Agencia.whatsapp_phone_number_id == buscado)
        .first()
    )
    if exacta:
        return exacta

    for candidata in db.query(Agencia).order_by(Agencia.id).all():
        if _lineas_whatsapp_coinciden(candidata.whatsapp_phone_number_id, buscado):
            return candidata
    return None


def _liberar_phone_id_en_equipo(db, agencia_id: int, phone_number_id: str) -> None:
    """Saca el Phone Number ID de Meta de vendedores/sucursales de esa agencia."""
    for vend in db.query(Vendedor).filter(Vendedor.agencia_id == agencia_id).all():
        if _lineas_whatsapp_coinciden(vend.telefono_whatsapp, phone_number_id):
            vend.telefono_whatsapp = f"sin-linea-{vend.id}"
    for suc in db.query(Sucursal).filter(Sucursal.agencia_id == agencia_id).all():
        if _lineas_whatsapp_coinciden(suc.telefono_whatsapp, phone_number_id):
            suc.telefono_whatsapp = ""


def _equipo_tiene_phone_id(db, agencia_id: int, phone_number_id: str) -> bool:
    for vend in db.query(Vendedor).filter(Vendedor.agencia_id == agencia_id).all():
        if _lineas_whatsapp_coinciden(vend.telefono_whatsapp, phone_number_id):
            return True
    for suc in db.query(Sucursal).filter(Sucursal.agencia_id == agencia_id).all():
        if _lineas_whatsapp_coinciden(suc.telefono_whatsapp, phone_number_id):
            return True
    return False


def _asignar_linea_bot_a_agencia(db, agencia: Agencia, phone_number_id: str) -> Agencia:
    """Garantiza que la línea Meta quede en la agencia y no en el equipo."""
    linea = _texto_linea(phone_number_id)
    otra = (
        db.query(Agencia)
        .filter(
            Agencia.id != agencia.id,
            Agencia.whatsapp_phone_number_id == linea,
        )
        .first()
    )
    if otra:
        # Otra agencia ya es dueña de este Phone Number ID.
        _liberar_phone_id_en_equipo(db, agencia.id, linea)
        db.commit()
        return otra

    if _texto_linea(agencia.whatsapp_phone_number_id) != linea:
        agencia.whatsapp_phone_number_id = linea
    _liberar_phone_id_en_equipo(db, agencia.id, linea)
    db.commit()
    db.refresh(agencia)
    return agencia


def _autofix_linea_bot_desde_equipo(db, phone_number_id: str) -> Agencia | None:
    """
    Si el Phone Number ID de Meta quedó pegado en un vendedor/sucursal (modelo viejo),
    lo mueve a esa agencia para que el webhook vuelva a ruteuar.
    """
    buscado = _texto_linea(phone_number_id)
    if not buscado:
        return None

    for vend in db.query(Vendedor).order_by(Vendedor.id).all():
        if not _lineas_whatsapp_coinciden(vend.telefono_whatsapp, buscado):
            continue
        agencia = db.query(Agencia).filter(Agencia.id == vend.agencia_id).first()
        if not agencia:
            continue
        print(
            f"[WEBHOOK WA] Auto-fix: Phone Number ID {buscado!r} estaba en "
            f"vendedor id={vend.id}; se asigna a agencia id={agencia.id} "
            f"({agencia.nombre!r})."
        )
        return _asignar_linea_bot_a_agencia(db, agencia, buscado)

    for suc in db.query(Sucursal).order_by(Sucursal.id).all():
        if not _lineas_whatsapp_coinciden(suc.telefono_whatsapp, buscado):
            continue
        agencia = db.query(Agencia).filter(Agencia.id == suc.agencia_id).first()
        if not agencia:
            continue
        print(
            f"[WEBHOOK WA] Auto-fix: Phone Number ID {buscado!r} estaba en "
            f"sucursal id={suc.id}; se asigna a agencia id={agencia.id} "
            f"({agencia.nombre!r})."
        )
        return _asignar_linea_bot_a_agencia(db, agencia, buscado)

    return None


def migrar_lineas_bot_desde_equipo() -> int:
    """Migración al arrancar: mueve IDs de Meta pegados en equipo → agencia."""
    from whatsapp_linea import es_phone_number_id_meta

    db = SessionLocal()
    reparadas = 0
    try:
        vistos: set[str] = set()
        candidatos: list[tuple[int, str]] = []
        for vend in db.query(Vendedor).order_by(Vendedor.id).all():
            tel = _texto_linea(vend.telefono_whatsapp)
            if tel and es_phone_number_id_meta(tel) and tel not in vistos:
                candidatos.append((vend.agencia_id, tel))
                vistos.add(tel)
        for suc in db.query(Sucursal).order_by(Sucursal.id).all():
            tel = _texto_linea(suc.telefono_whatsapp)
            if tel and es_phone_number_id_meta(tel) and tel not in vistos:
                candidatos.append((suc.agencia_id, tel))
                vistos.add(tel)

        for agencia_id, linea in candidatos:
            agencia = db.query(Agencia).filter(Agencia.id == agencia_id).first()
            if not agencia:
                continue
            actual = _texto_linea(agencia.whatsapp_phone_number_id)
            if _lineas_whatsapp_coinciden(actual, linea):
                _liberar_phone_id_en_equipo(db, agencia.id, linea)
                reparadas += 1
                continue
            if _es_placeholder_linea_bot(actual):
                _asignar_linea_bot_a_agencia(db, agencia, linea)
                reparadas += 1
        if reparadas:
            db.commit()
        return reparadas
    finally:
        db.close()


def _agencia_con_email_verificado(db, agencia_id: int) -> bool:
    from models.database import Usuario

    return (
        db.query(Usuario)
        .filter(
            Usuario.agencia_id == agencia_id,
            Usuario.email_verificado.is_(True),
            Usuario.activo.is_(True),
        )
        .first()
        is not None
    )


def _elegir_agencia_placeholder(db, placeholders: list[Agencia]) -> Agencia | None:
    """Prioriza agencias con al menos un usuario de email verificado."""
    if not placeholders:
        return None
    verificadas = [a for a in placeholders if _agencia_con_email_verificado(db, a.id)]
    if verificadas:
        return verificadas[0]
    # Sin cuentas verificadas: no adivinar (evita dar la línea a registros a medias).
    print(
        "[WEBHOOK WA] Hay agencias con reg_… pero ninguna con email verificado. "
        "No se auto-asigna el Phone Number ID."
    )
    return None


def _liberar_linea_en_agencias_sin_verificar(db, phone_number_id: str) -> None:
    """Si una agencia sin email verificado se quedó con el ID de Meta, lo libera."""
    import secrets

    buscado = _texto_linea(phone_number_id)
    if not buscado:
        return
    for ag in db.query(Agencia).order_by(Agencia.id).all():
        if not _lineas_whatsapp_coinciden(ag.whatsapp_phone_number_id, buscado):
            continue
        if _agencia_con_email_verificado(db, ag.id):
            continue
        nuevo = f"reg_{secrets.token_hex(8)}"
        print(
            f"[WEBHOOK WA] Liberando Phone Number ID {buscado!r} de agencia "
            f"id={ag.id} ({ag.nombre!r}) sin email verificado → {nuevo}"
        )
        ag.whatsapp_phone_number_id = nuevo
    db.commit()


def _autofix_linea_bot_desde_env(db, phone_number_id: str) -> Agencia | None:
    """
    Si Meta manda un Phone Number ID que coincide con WHATSAPP_PHONE_NUMBER_ID
    del .env y ninguna agencia verificada lo tiene, se asigna a una agencia
    pendiente (reg_…) con email verificado.
    """
    from whatsapp_config import whatsapp_phone_number_id
    from whatsapp_linea import es_phone_number_id_meta

    buscado = _texto_linea(phone_number_id)
    env_id = _texto_linea(whatsapp_phone_number_id())
    if not buscado or not env_id:
        return None
    if not _lineas_whatsapp_coinciden(buscado, env_id):
        return None
    if not es_phone_number_id_meta(buscado):
        return None

    # Si una agencia fantasma (sin verificar) se quedó con el ID, liberarlo.
    _liberar_linea_en_agencias_sin_verificar(db, buscado)

    ya = _buscar_agencia_por_phone_id(db, buscado)
    if ya:
        if _agencia_con_email_verificado(db, ya.id):
            return ya
        _liberar_linea_en_agencias_sin_verificar(db, buscado)
        ya = _buscar_agencia_por_phone_id(db, buscado)
        if ya:
            return ya

    placeholders = [
        a
        for a in db.query(Agencia).order_by(Agencia.id).all()
        if _es_placeholder_linea_bot(a.whatsapp_phone_number_id)
    ]
    agencia = _elegir_agencia_placeholder(db, placeholders)
    if not agencia:
        if placeholders:
            print(
                f"[WEBHOOK WA] .env={env_id!r} coincide, pero no hay agencia "
                "verificada para asignar la línea. Verificá el email o borrá "
                "registros basura con /admin/reset-agencias."
            )
        else:
            print(
                f"[WEBHOOK WA] .env={env_id!r} coincide con el webhook pero ninguna "
                "agencia tiene línea pendiente (reg_…). Cargá el Phone Number ID en "
                "Configuración → Datos de la agencia."
            )
        return None

    print(
        f"[WEBHOOK WA] Auto-fix desde .env: se asigna Phone Number ID {buscado!r} "
        f"a agencia verificada id={agencia.id} ({agencia.nombre!r})."
    )
    return _asignar_linea_bot_a_agencia(db, agencia, buscado)


def migrar_linea_bot_desde_env() -> bool:
    """Al arrancar: libera ID de agencias sin verificar y asigna a una verificada."""
    from whatsapp_config import whatsapp_phone_number_id
    from whatsapp_linea import es_phone_number_id_meta

    env_id = _texto_linea(whatsapp_phone_number_id())
    if not env_id or not es_phone_number_id_meta(env_id):
        return False

    db = SessionLocal()
    try:
        _liberar_linea_en_agencias_sin_verificar(db, env_id)
        if _buscar_agencia_por_phone_id(db, env_id):
            return False
        placeholders = [
            a
            for a in db.query(Agencia).order_by(Agencia.id).all()
            if _es_placeholder_linea_bot(a.whatsapp_phone_number_id)
        ]
        agencia = _elegir_agencia_placeholder(db, placeholders)
        if not agencia:
            return False
        _asignar_linea_bot_a_agencia(db, agencia, env_id)
        print(
            f"[DB] Línea del bot tomada de .env → agencia id={agencia.id} "
            f"({agencia.nombre!r}) = {env_id}"
        )
        return True
    finally:
        db.close()


def asegurar_linea_bot_para_agencia(db, agencia: Agencia) -> bool:
    """
    Al abrir Configuración: si esta agencia todavía tiene reg_… y el .env tiene
    un Phone Number ID libre (o atrapado en una agencia sin verificar), se lo
    asigna a ESTA agencia (la que el usuario está editando), solo si está verificada.
    """
    from whatsapp_config import whatsapp_phone_number_id
    from whatsapp_linea import es_phone_number_id_meta

    if not _agencia_con_email_verificado(db, agencia.id):
        return False
    if not _es_placeholder_linea_bot(agencia.whatsapp_phone_number_id):
        return False
    env_id = _texto_linea(whatsapp_phone_number_id())
    if not env_id or not es_phone_number_id_meta(env_id):
        return False
    _liberar_linea_en_agencias_sin_verificar(db, env_id)
    otra = _buscar_agencia_por_phone_id(db, env_id)
    if otra and otra.id != agencia.id:
        return False
    _asignar_linea_bot_a_agencia(db, agencia, env_id)
    return True


def promover_phone_id_a_agencia(db, agencia: Agencia, phone_number_id: str) -> Agencia:
    """API pública: guarda el Phone Number ID de Meta en la agencia y limpia el equipo."""
    return _asignar_linea_bot_a_agencia(db, agencia, phone_number_id)


def agencia_tiene_linea_placeholder(agencia: Agencia) -> bool:
    return _es_placeholder_linea_bot(agencia.whatsapp_phone_number_id)


def _sucursal_y_vendedor_de_agencia(
    db, agencia: Agencia
) -> tuple[Sucursal | None, Vendedor | None]:
    suc = (
        db.query(Sucursal)
        .filter(Sucursal.agencia_id == agencia.id, Sucursal.es_principal.is_(True))
        .order_by(Sucursal.numero)
        .first()
    )
    if not suc:
        suc = (
            db.query(Sucursal)
            .filter(Sucursal.agencia_id == agencia.id)
            .order_by(Sucursal.numero)
            .first()
        )
    return suc, _vendedor_principal_de_sucursal(db, suc)


def resolver_destino_por_receptor_whatsapp(
    phone_number_id: str,
) -> tuple[Agencia | None, Sucursal | None, Vendedor | None]:
    """
    Identifica AGENCIA → SUCURSAL principal → VENDEDOR principal.

    Orden de resolución:
      1) agencias.whatsapp_phone_number_id
      2) auto-fix desde vendedor/sucursal (modelo viejo)
      3) auto-fix desde .env WHATSAPP_PHONE_NUMBER_ID
    """
    buscado = _texto_linea(phone_number_id)
    if not buscado:
        return None, None, None

    db = SessionLocal()
    try:
        agencia = _buscar_agencia_por_phone_id(db, buscado)
        # Si el ID quedó en una agencia sin email verificado (registro a medias),
        # liberarlo para poder asignarlo a una cuenta usable.
        if agencia and not _agencia_con_email_verificado(db, agencia.id):
            from whatsapp_config import whatsapp_phone_number_id

            env_id = _texto_linea(whatsapp_phone_number_id())
            if env_id and _lineas_whatsapp_coinciden(buscado, env_id):
                _liberar_linea_en_agencias_sin_verificar(db, buscado)
                agencia = _buscar_agencia_por_phone_id(db, buscado)

        if not agencia:
            agencia = _autofix_linea_bot_desde_equipo(db, buscado)
        if not agencia:
            agencia = _autofix_linea_bot_desde_env(db, buscado)
        elif _equipo_tiene_phone_id(db, agencia.id, buscado):
            _liberar_phone_id_en_equipo(db, agencia.id, buscado)
            db.commit()
            db.refresh(agencia)

        if not agencia:
            return None, None, None

        _ = (
            agencia.id,
            agencia.nombre,
            agencia.whatsapp_phone_number_id,
            agencia.modo_respuesta,
            agencia.nombre_bot,
            agencia.nombre_agencia,
        )
        suc, vend = _sucursal_y_vendedor_de_agencia(db, agencia)
        if suc:
            _ = (suc.id, suc.nombre, suc.telefono_whatsapp, suc.direccion)
        if vend:
            _ = (vend.id, vend.nombre, vend.telefono_whatsapp)
        db.expunge_all()
        return agencia, suc, vend
    finally:
        db.close()


def resolver_sucursal_por_receptor_whatsapp(
    phone_number_id: str,
) -> tuple[Agencia | None, Sucursal | None]:
    """Compatibilidad: devuelve solo (agencia, sucursal)."""
    agencia, sucursal, _ = resolver_destino_por_receptor_whatsapp(phone_number_id)
    return agencia, sucursal


def resolver_sucursal_id_cita(
    agencia_id: int,
    sucursal_origen_id: int | None,
    auto_interes_id: int | None,
) -> int | None:
    """Sede de la cita: por defecto origen; si el auto está en otra sede, esa sede."""
    if auto_interes_id:
        auto = obtener_auto_por_id(agencia_id, auto_interes_id)
        if auto and auto.sucursal_id:
            if sucursal_origen_id and auto.sucursal_id == sucursal_origen_id:
                return sucursal_origen_id
            return auto.sucursal_id
    return sucursal_origen_id


def obtener_inventario_agencia(agencia_id: int) -> str:
    db = SessionLocal()
    try:
        mapa = _mapa_nombres_sucursales(db, agencia_id)
        autos = (
            db.query(Auto)
            .filter(Auto.agencia_id == agencia_id, func.lower(Auto.estado) == "disponible")
            .order_by(Auto.sucursal_id, Auto.marca, Auto.modelo)
            .all()
        )
        if not autos:
            return "Sin stock disponible."

        lines = []
        for auto in autos:
            fotos = obtener_fotos_auto(auto)
            foto_hint = f" | Fotos: {len(fotos)}" if fotos else ""
            sucursal = mapa.get(auto.sucursal_id, "Sin sucursal")
            km = f" | {auto.kilometros:,} km".replace(",", ".") if auto.kilometros else ""
            lines.append(
                f"- ID: {auto.id} | [{sucursal}] | {auto.marca} {auto.modelo} ({auto.version}) | "
                f"Año: {auto.ano}{km} | Tipo: {auto.tipo} | Patente: {auto.patente} | "
                f"Precio ref.: ${auto.precio_referencia_ars:,.0f}{foto_hint}"
            )
        return "\n".join(lines)
    finally:
        db.close()


def formatear_opciones_stock_cruzado(
    autos: list[Auto],
    agencia_id: int,
    sucursal_origen_id: int | None = None,
) -> str:
    if not autos:
        return ""

    db = SessionLocal()
    try:
        mapa = _mapa_nombres_sucursales(db, agencia_id)
    finally:
        db.close()

    origen = mapa.get(sucursal_origen_id, "la sucursal por la que te contactó")
    lineas = [
        "STOCK CRUZADO (todas las sedes de la agencia):",
        f"El cliente escribió por la línea de {origen}. Proponé agendar la visita allí por defecto.",
        "Si elige un auto que está en otra sede, ofrecé también coordinar turno en esa sede.",
        "Opciones encontradas:",
    ]
    for indice, auto in enumerate(autos, start=1):
        sucursal = mapa.get(auto.sucursal_id, "Sin sucursal")
        km = f" · {auto.kilometros:,} km".replace(",", ".") if auto.kilometros else ""
        lineas.append(
            f"{indice}. [{sucursal}] {auto.marca} {auto.modelo} {auto.ano} — "
            f"{auto.version}{km} — ${auto.precio_referencia_ars:,.0f} — ID {auto.id}"
        )
    return "\n".join(lineas)


def obtener_autos_disponibles(agencia_id: int) -> list[Auto]:
    db = SessionLocal()
    try:
        return (
            db.query(Auto)
            .filter(Auto.agencia_id == agencia_id, func.lower(Auto.estado) == "disponible")
            .all()
        )
    finally:
        db.close()


def buscar_autos_por_texto(agencia_id: int, texto: str) -> list[Auto]:
    texto_lower = _expandir_aliases_marca(texto.strip())
    coincidencias: list[Auto] = []

    for auto in obtener_autos_disponibles(agencia_id):
        candidatos = [
            auto.marca.lower(),
            auto.modelo.lower(),
            f"{auto.marca} {auto.modelo}".lower(),
            auto.patente.lower(),
        ]
        if any(c in texto_lower for c in candidatos):
            coincidencias.append(auto)

    return coincidencias


def obtener_auto_por_id(agencia_id: int, auto_id: int) -> Auto | None:
    db = SessionLocal()
    try:
        return (
            db.query(Auto)
            .filter(Auto.id == auto_id, Auto.agencia_id == agencia_id)
            .first()
        )
    finally:
        db.close()


# Pedido EXPLÍCITO de fotos (no confundir con "quiero ver el auto" / "mandame turno").
_PATRON_PEDIDO_FOTOS = re.compile(
    r"(?:"
    r"\b(foto|fotos|fotito|fotitos|imagen|imagenes|imágenes)\b"
    r"|"
    r"\b(mostrame|mostrá|mostras|mostrás|mandame|mandá|enviame|enviá|pasame|pasá)\b"
    r".{0,48}\b(foto|fotos|fotito|fotitos|imagen|imagenes|imágenes)\b"
    r"|"
    r"\b(foto|fotos|fotito|fotitos|imagen|imagenes|imágenes)\b"
    r".{0,48}\b(mostrame|mostrá|mostras|mostrás|mandame|mandá|enviame|enviá|pasame|pasá)\b"
    r")",
    re.IGNORECASE,
)

_PATRON_MAS_FOTOS = re.compile(
    r"\b(mas|más|otras?|nuevas?|siguen|seguime|todas)\b.{0,24}\b(foto|fotos|fotito|fotitos)\b"
    r"|"
    r"\b(foto|fotos)\b.{0,24}\b(mas|más|otras?|nuevas?)\b",
    re.IGNORECASE,
)

_PATRON_CIERRE_SIN_FOTOS = re.compile(
    r"\b("
    r"me\s+gusta|me\s+interesa|lo\s+quiero|la\s+quiero|"
    r"agendar|agenda(r|me)?|turno|cita|visita|"
    r"pasame\s+la\s+direcci[oó]n|direcci[oó]n|"
    r"quiero\s+(ir|pasar|reservar|agendar)|"
    r"voy\s+(a\s+)?(ver|pasar|ir)|"
    r"cerramos|se[ñn]a|seña|reserva"
    r")\b",
    re.IGNORECASE,
)


def cliente_pide_fotos(texto: str) -> bool:
    """True solo si pide fotos de forma explícita."""
    return bool(_PATRON_PEDIDO_FOTOS.search(texto or ""))


def cliente_pide_mas_fotos(texto: str) -> bool:
    """True si pide otra tanda / más fotos (después de ya haber recibido)."""
    return bool(_PATRON_MAS_FOTOS.search(texto or ""))


def cliente_en_cierre_sin_fotos(texto: str) -> bool:
    """True si el mensaje apunta a gustar/agendar/visitar: no reenviar álbum."""
    return bool(_PATRON_CIERRE_SIN_FOTOS.search(texto or ""))


_MAX_FOTOS_WHATSAPP = 8
_PATRON_PLACEHOLDER_IMAGEN = re.compile(
    r"\[?\s*IMAGEN\s*\d*[^\]\n]*\]?",
    re.IGNORECASE,
)
_PATRON_LINEA_URL_FOTO = re.compile(
    r"^(?:📷\s*)?(?:Fotos\s*[—\-].*)?https?://\S+$|^/static/\S+$",
    re.IGNORECASE,
)


def listar_origenes_fotos_auto(auto: Auto, base_url: str = "") -> list[str]:
    """Orígenes para envío WA: paths /static/... (subida local) o URLs http(s)."""
    del base_url  # se usa en el fallback de envío, no acá
    fotos = obtener_fotos_auto(auto)
    return [f for f in fotos[:_MAX_FOTOS_WHATSAPP] if f]


def formatear_fotos_para_whatsapp(auto: Auto, base_url: str = "") -> str:
    """Texto de respaldo con URLs (solo si no se pueden enviar como media)."""
    fotos = obtener_fotos_auto(auto)
    if not fotos:
        return ""
    titulo = f"📷 Fotos — {auto.marca} {auto.modelo} {auto.ano}"
    urls = []
    for foto in fotos:
        if foto.startswith("/") and base_url:
            urls.append(base_url.rstrip("/") + foto)
        else:
            urls.append(foto)
    return titulo + "\n" + "\n".join(urls)


def limpiar_placeholders_imagen_en_texto(texto: str) -> str:
    """Saca inventos tipo [IMAGEN 1 del …] y líneas que solo son URLs de foto."""
    if not texto:
        return texto
    limpio = _PATRON_PLACEHOLDER_IMAGEN.sub("", texto)
    lineas: list[str] = []
    for linea in limpio.splitlines():
        t = linea.strip()
        if not t:
            lineas.append("")
            continue
        if t.startswith("📷 Fotos"):
            continue
        if t.startswith(("http://", "https://", "/static/")):
            continue
        if _PATRON_LINEA_URL_FOTO.match(t):
            continue
        lineas.append(linea)
    # Colapsar saltos múltiples
    resultado = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()
    return resultado


def buscar_auto_por_texto(agencia_id: int, texto: str) -> Auto | None:
    coincidencias = buscar_autos_por_texto(agencia_id, texto)
    if len(coincidencias) == 1:
        return coincidencias[0]
    return None


def guardar_lead_comercial(
    agencia_id: int,
    telefono: str,
    auto_id: int | None = None,
    presupuesto: float | None = None,
    nombre_cliente: str | None = None,
    apellido_cliente: str | None = None,
    usado_marca_modelo: str | None = None,
    usado_ano: int | None = None,
    usado_km: int | None = None,
    usado_patente: str | None = None,
    usado_estado: str | None = None,
    usado_vtv_vigente: str | None = None,
    usado_es_titular: str | None = None,
    lead_id: int | None = None,
    sucursal_id: int | None = None,
    vendedor_id: int | None = None,
) -> int:
    db = SessionLocal()
    try:
        if sucursal_id is None:
            principal = (
                db.query(Sucursal)
                .filter(Sucursal.agencia_id == agencia_id, Sucursal.es_principal.is_(True))
                .first()
            )
            if not principal:
                principal = (
                    db.query(Sucursal)
                    .filter(Sucursal.agencia_id == agencia_id)
                    .order_by(Sucursal.numero)
                    .first()
                )
            sucursal_id = principal.id if principal else None
        else:
            suc = (
                db.query(Sucursal)
                .filter(Sucursal.id == sucursal_id, Sucursal.agencia_id == agencia_id)
                .first()
            )
            if not suc:
                sucursal_id = None

        if lead_id:
            lead = db.query(ProspectoLead).filter(ProspectoLead.id == lead_id).first()
            if not lead:
                lead = ProspectoLead(
                    agencia_id=agencia_id,
                    telefono_cliente=telefono,
                    sucursal_id=sucursal_id,
                )
                db.add(lead)
        else:
            lead = ProspectoLead(
                agencia_id=agencia_id,
                telefono_cliente=telefono,
                sucursal_id=sucursal_id,
            )
            db.add(lead)

        if nombre_cliente:
            lead.nombre_cliente = nombre_cliente
        if apellido_cliente:
            lead.apellido_cliente = apellido_cliente
        if auto_id:
            lead.auto_interes_id = auto_id
        if presupuesto:
            lead.presupuesto_estimado = presupuesto
        if usado_marca_modelo:
            lead.usado_marca_modelo = usado_marca_modelo
        if usado_ano:
            lead.usado_ano = usado_ano
        if usado_km:
            lead.usado_km = usado_km
        if usado_patente:
            lead.usado_patente = usado_patente
        if usado_estado:
            lead.usado_estado = usado_estado
        if usado_vtv_vigente:
            lead.usado_vtv_vigente = usado_vtv_vigente
        if usado_es_titular:
            lead.usado_es_titular = usado_es_titular
        if vendedor_id and getattr(lead, "vendedor_id", None) is None:
            lead.vendedor_id = vendedor_id

        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()
