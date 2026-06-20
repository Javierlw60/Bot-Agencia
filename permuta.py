import re
import unicodedata

INSTRUCCIONES_PERMUTA = """
TASACIÓN DE USADO (PERMUTA) — FLUJO COMERCIAL ÁGIL:
- NUNCA pidas chasis ni número de motor.
- La permuta es el vehículo usado del cliente, no el auto del inventario que está mirando. NUNCA digas "entregarlo" refiriéndote al auto en venta.
- Si el cliente menciona que tiene un usado propio o quiere permuta, respondé de forma amigable y en UN mensaje simple pidiendo (si faltan):
  1) Marca y modelo de su vehículo usado.
  2) Año (modelo) y cantidad de kilómetros.
  3) Si recuerda la patente (dominio) de su usado.
  4) Estado general (si tuvo algún choque o detalles a tener en cuenta).
  5) Si tiene la Verificación Técnica Vehicular (VTV) vigente y si es titular de ese vehículo usado.
- Hacelo conversacional: aceptá respuestas parciales, en varios mensajes o todo junto. No uses formularios rígidos ni listas numeradas largas.
- Si el cliente no sabe algún dato (ej. patente), decile que no hay problema y seguí con el resto.
- Con los datos del usado, avanzá naturalmente hacia coordinar una visita presencial para ver el auto y cerrar la operación.
"""


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _tiene_marca_conocida(texto_norm: str) -> bool:
    marcas = [
        "fiat", "volkswagen", "vw", "ford", "chevrolet", "toyota", "renault",
        "peugeot", "citroen", "nissan", "honda", "hyundai", "jeep", "ram",
    ]
    return any(m in texto_norm for m in marcas)


def _parece_descripcion_usado(texto_norm: str) -> bool:
    tiene_ano = bool(re.search(r"\b(19\d{2}|20\d{2})\b", texto_norm))
    tiene_km = bool(
        re.search(r"\d[\d\.]*\s*(?:km|kilometros|kilómetros|k\b|mil\s*km)", texto_norm)
    )
    return _tiene_marca_conocida(texto_norm) and (tiene_ano or tiene_km)


def detectar_permuta(texto: str) -> bool:
    texto_norm = _normalizar(texto)
    claves = [
        "permuta",
        "usado",
        "parte de pago",
        "canje",
        "entregar mi",
        "dar mi",
        "quiero dar",
        "tomo usado",
        "tomás usado",
        "tengo un auto",
        "tengo un vehiculo",
        "mi auto",
        "mi vehiculo",
    ]
    return any(c in texto_norm for c in claves) or _parece_descripcion_usado(texto_norm)


def resumen_usado_sesion(sesion) -> str:
    campos = []
    if sesion.usado_marca_modelo:
        campos.append(f"Marca/Modelo: {sesion.usado_marca_modelo}")
    if sesion.usado_ano:
        campos.append(f"Año: {sesion.usado_ano}")
    if sesion.usado_km:
        campos.append(f"Km: {sesion.usado_km}")
    if sesion.usado_patente:
        campos.append(f"Patente: {sesion.usado_patente}")
    if sesion.usado_estado:
        campos.append(f"Estado: {sesion.usado_estado}")
    if sesion.usado_vtv_vigente:
        campos.append(f"VTV vigente: {sesion.usado_vtv_vigente}")
    if sesion.usado_es_titular:
        campos.append(f"Es titular: {sesion.usado_es_titular}")
    return " | ".join(campos) if campos else "Sin datos de usado cargados aún."


def extraer_datos_usado_en_segundo_plano(sesion, texto: str) -> None:
    if not detectar_permuta(texto) and not sesion.quiere_permuta:
        return

    sesion.quiere_permuta = True
    texto_norm = _normalizar(texto)
    texto_original = texto.strip()

    km_match = re.search(
        r"(\d[\d\.]*)\s*(?:km|kilometros|kilometros|kilómetros|k\b|mil\s*km|mil)",
        texto_norm,
    )
    if km_match:
        km_raw = km_match.group(1).replace(".", "")
        if "mil" in texto_norm and len(km_raw) <= 3:
            sesion.usado_km = int(km_raw) * 1000
        else:
            sesion.usado_km = int(km_raw)

    ano_match = re.search(r"(?:año|ano|modelo)\s*(\d{4})", texto_norm)
    if ano_match:
        sesion.usado_ano = int(ano_match.group(1))
    else:
        anos = re.findall(r"\b(19\d{2}|20\d{2})\b", texto_norm)
        if anos:
            sesion.usado_ano = int(anos[-1])

    patente_match = re.search(r"\b([A-Z]{2,3}\d{3}[A-Z]{0,2})\b", texto.upper())
    if patente_match:
        sesion.usado_patente = patente_match.group(1)

    if "vtv" in texto_norm:
        if any(x in texto_norm for x in ["vigente", "al dia", "al día", "si ", "sí ", "si,", "ok"]):
            sesion.usado_vtv_vigente = "Sí"
        elif "no" in texto_norm:
            sesion.usado_vtv_vigente = "No"
        elif any(x in texto_norm for x in ["vencida", "vencio", "venció"]):
            sesion.usado_vtv_vigente = "No"

    if any(x in texto_norm for x in ["titular", "a mi nombre", "a nombre"]):
        if any(
            x in texto_norm
            for x in ["soy titular", "si soy", "sí soy", "soy el titular", "a mi nombre", "si, soy", "sí, soy"]
        ):
            sesion.usado_es_titular = "Sí"
        elif "no soy" in texto_norm or "no es titular" in texto_norm:
            sesion.usado_es_titular = "No"

    if any(
        x in texto_norm
        for x in [
            "choque",
            "golpe",
            "rayon",
            "rayón",
            "sin choque",
            "impecable",
            "detalle",
            "pintura",
            "abolladura",
        ]
    ):
        sesion.usado_estado = texto_original[:300]

    if not sesion.usado_marca_modelo and _tiene_marca_conocida(texto_norm):
        sesion.usado_marca_modelo = texto_original[:120]
