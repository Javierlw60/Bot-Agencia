import csv
import io
import re
from dataclasses import dataclass, field

from models.database import Auto, SessionLocal

MARCAS_CONOCIDAS = {
    "volkswagen", "vw", "ford", "chevrolet", "chevy", "fiat", "renault", "peugeot",
    "citroen", "citroën", "toyota", "honda", "nissan", "hyundai", "kia", "bmw",
    "mercedes", "mercedes-benz", "audi", "jeep", "ram", "dodge", "volvo", "suzuki",
    "mitsubishi", "subaru", "mazda", "chery", "geely", "byd", "jac", "ds", "mini",
    "land rover", "range rover", "porsche", "seat", "skoda", "ssangyong", "great wall",
    "haval", "baic", "foton", "iveco", "scania", "alfa romeo", "ferrari", "lexus",
    "infiniti", "acura", "cadillac", "chrysler", "gmc", "lincoln", "tesla", "smart",
}

TIPOS_CONOCIDOS = {
    "sedan", "sedán", "hatch", "hatchback", "suv", "pickup", "pick-up", "pick up",
    "coupe", "coupé", "convertible", "van", "utilitario", "familiar", "wagon",
    "station wagon", "4x4", "camioneta",
}

ESTADOS_CONOCIDOS = {"disponible", "reservado", "vendido"}

ORDEN_ESTANDAR = [
    "marca", "modelo", "ano", "precio_referencia_ars", "estado",
    "patente", "version", "tipo", "kilometros", "foto_principal_url",
]

MAPEO_ENCABEZADOS = {
    "marca": "marca", "brand": "marca", "make": "marca",
    "modelo": "modelo", "model": "modelo",
    "version": "version", "versión": "version", "trim": "version",
    "año": "ano", "ano": "ano", "anio": "ano", "year": "ano",
    "tipo": "tipo", "body": "tipo", "carroceria": "tipo", "carrocería": "tipo",
    "patente": "patente", "dominio": "patente", "plate": "patente",
    "precio": "precio_referencia_ars", "price": "precio_referencia_ars",
    "valor": "precio_referencia_ars", "importe": "precio_referencia_ars",
    "precio_referencia": "precio_referencia_ars", "precio_referencia_ars": "precio_referencia_ars",
    "estado": "estado", "status": "estado", "situacion": "estado", "situación": "estado",
    "km": "kilometros", "kms": "kilometros", "kilometros": "kilometros",
    "kilómetros": "kilometros", "kilometraje": "kilometros", "odometro": "kilometros",
    "odómetro": "kilometros",
    "foto": "foto_principal_url", "foto_url": "foto_principal_url",
    "foto_principal": "foto_principal_url", "imagen": "foto_principal_url", "url": "foto_principal_url",
}

PATRON_PATENTE = re.compile(
    r"^\s*([A-Za-z]{2,3}\s?\d{3}\s?[A-Za-z]{0,2}|[A-Za-z]{2}\s?\d{3}\s?[A-Za-z]{2})\s*$",
    re.IGNORECASE,
)


@dataclass
class ResultadoImportacion:
    creados: int = 0
    actualizados: int = 0
    errores: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.creados + self.actualizados


def _normalizar_encabezado(texto: str) -> str:
    return texto.strip().lower().replace(" ", "_")


def _detectar_delimitador(contenido: str) -> str:
    muestra = contenido[:4096]
    try:
        dialect = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        if ";" in muestra.split("\n", 1)[0]:
            return ";"
        return ","


def _leer_filas(contenido: str) -> tuple[list[str], list[list[str]]]:
    delim = _detectar_delimitador(contenido)
    reader = csv.reader(io.StringIO(contenido), delimiter=delim)
    filas = [f for f in reader if any(celda.strip() for celda in f)]
    if not filas:
        return [], []

    primera = [c.strip() for c in filas[0]]
    if _parece_encabezado(primera):
        return primera, [[c.strip() for c in f] for f in filas[1:]]

    return [f"col_{i}" for i in range(len(primera))], [[c.strip() for c in f] for f in filas]


def _parece_encabezado(celdas: list[str]) -> bool:
    if not celdas:
        return False
    pistas = sum(
        1 for c in celdas
        if _normalizar_encabezado(c) in MAPEO_ENCABEZADOS
        or c.lower() in MARCAS_CONOCIDAS
    )
    if pistas >= 2:
        return True
    tipos_fuertes = sum(
        1 for c in celdas
        if c and (_puntuacion_precio(c) >= 0.8 or _puntuacion_ano(c) >= 0.9 or _puntuacion_patente(c) >= 0.9)
    )
    return tipos_fuertes < max(1, len(celdas) // 3)


def _solo_digitos(valor: str) -> str:
    return re.sub(r"[^\d]", "", valor or "")


def _parsear_precio(valor: str) -> float:
    limpio = re.sub(r"[^\d,.]", "", (valor or "").strip())
    if not limpio:
        raise ValueError("precio vacío")
    if limpio.count(".") > 1:
        limpio = limpio.replace(".", "")
    elif limpio.count(",") > 1:
        limpio = limpio.replace(",", "")
    elif "," in limpio and "." in limpio:
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        parte = limpio.split(",")[-1]
        limpio = limpio.replace(",", ".") if len(parte) <= 2 else limpio.replace(",", "")
    return float(limpio)


def _parsear_km(valor: str) -> int:
    texto = (valor or "").strip().lower()
    nums = _solo_digitos(texto)
    if not nums:
        raise ValueError("km vacío")
    km = int(nums)
    if km < 0 or km > 2_000_000:
        raise ValueError("km fuera de rango")
    return km


def _puntuacion_precio(valor: str) -> float:
    if not valor or not str(valor).strip():
        return 0.0
    texto = str(valor).strip()
    if "$" in texto or "ars" in texto.lower():
        return 1.0
    nums = _solo_digitos(texto)
    if not nums:
        return 0.0
    try:
        n = float(nums) if len(nums) < 10 else float(_parsear_precio(texto))
        if n >= 500_000:
            return 1.0
        if n >= 100_000:
            return 0.7
    except ValueError:
        pass
    return 0.0


def _puntuacion_patente(valor: str) -> float:
    if not valor:
        return 0.0
    compacta = re.sub(r"\s+", "", str(valor).strip().upper())
    if PATRON_PATENTE.match(compacta) or PATRON_PATENTE.match(str(valor).strip()):
        return 1.0
    if re.match(r"^[A-Z]{2,3}\d{3}", compacta, re.I):
        return 0.85
    return 0.0


def _puntuacion_ano(valor: str) -> float:
    if not valor:
        return 0.0
    nums = _solo_digitos(str(valor))
    if len(nums) != 4:
        return 0.0
    ano = int(nums)
    if 1980 <= ano <= 2026:
        return 1.0
    return 0.0


def _puntuacion_km(valor: str) -> float:
    if not valor:
        return 0.0
    texto = str(valor).strip().lower()
    if "km" in texto or "kms" in texto:
        return 1.0
    nums = _solo_digitos(texto)
    if not nums:
        return 0.0
    n = int(nums)
    if 1_000 <= n <= 800_000:
        return 0.75
    return 0.0


def _puntuacion_marca(valor: str) -> float:
    if not valor:
        return 0.0
    texto = str(valor).strip().lower()
    if texto in MARCAS_CONOCIDAS:
        return 1.0
    for marca in MARCAS_CONOCIDAS:
        if texto.startswith(marca + " ") or texto == marca:
            return 0.9
    if re.match(r"^[A-Za-zÁÉÍÓÚáéíóúñ\s.-]{2,30}$", str(valor).strip()) and not _solo_digitos(texto):
        return 0.35
    return 0.0


def _puntuacion_estado(valor: str) -> float:
    if not valor:
        return 0.0
    return 1.0 if str(valor).strip().lower() in ESTADOS_CONOCIDOS else 0.0


def _puntuacion_tipo(valor: str) -> float:
    if not valor:
        return 0.0
    return 1.0 if str(valor).strip().lower() in TIPOS_CONOCIDOS else 0.2


def _puntuacion_url(valor: str) -> float:
    if not valor:
        return 0.0
    texto = str(valor).strip().lower()
    if texto.startswith("http://") or texto.startswith("https://"):
        return 1.0
    if texto.startswith("/static/") or texto.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return 0.9
    return 0.0


def _puntuacion_modelo(valor: str) -> float:
    if not valor or _puntuacion_precio(valor) >= 0.7 or _puntuacion_ano(valor) >= 0.9:
        return 0.0
    if _puntuacion_patente(valor) >= 0.85:
        return 0.0
    texto = str(valor).strip()
    if re.match(r"^[A-Za-zÁÉÍÓÚáéíóúñ0-9\s.+/-]{2,50}$", texto):
        return 0.5
    return 0.0


_PUNTUADORES = {
    "precio_referencia_ars": _puntuacion_precio,
    "patente": _puntuacion_patente,
    "ano": _puntuacion_ano,
    "kilometros": _puntuacion_km,
    "marca": _puntuacion_marca,
    "modelo": _puntuacion_modelo,
    "estado": _puntuacion_estado,
    "tipo": _puntuacion_tipo,
    "foto_principal_url": _puntuacion_url,
    "version": _puntuacion_modelo,
}


def _bonus_encabezado(encabezado: str, campo: str) -> float:
    mapeado = MAPEO_ENCABEZADOS.get(_normalizar_encabezado(encabezado))
    if mapeado == campo:
        return 2.0
    texto = encabezado.lower()
    if campo == "marca" and any(m in texto for m in ("marca", "brand", "make")):
        return 1.5
    if campo == "modelo" and "model" in texto:
        return 1.5
    return 0.0


def inferir_mapa_columnas(encabezados: list[str], muestra: list[list[str]]) -> dict[int, str]:
    if not muestra:
        return {}

    num_cols = max(len(encabezados), max(len(f) for f in muestra))
    filas_analisis = muestra[:3]
    puntajes: dict[tuple[int, str], float] = {}

    for col in range(num_cols):
        for campo, fn in _PUNTUADORES.items():
            score = 0.0
            for fila in filas_analisis:
                if col < len(fila) and fila[col].strip():
                    score += fn(fila[col])
            score /= max(1, len(filas_analisis))
            if col < len(encabezados):
                score += _bonus_encabezado(encabezados[col], campo)
            puntajes[(col, campo)] = score

    candidatos = sorted(
        ((col, campo, sc) for (col, campo), sc in puntajes.items()),
        key=lambda x: x[2],
        reverse=True,
    )

    mapa: dict[int, str] = {}
    campos_usados: set[str] = set()
    for col, campo, score in candidatos:
        if col in mapa or campo in campos_usados:
            continue
        if score >= 0.45:
            mapa[col] = campo
            campos_usados.add(campo)

    columnas_libres = [c for c in range(num_cols) if c not in mapa]
    for campo in ORDEN_ESTANDAR:
        if campo in campos_usados or not columnas_libres:
            continue
        if campo in ("marca", "modelo", "version", "tipo", "estado"):
            col = columnas_libres.pop(0)
            mapa[col] = campo
            campos_usados.add(campo)

    return mapa


def _aplicar_valor(datos: dict, campo: str, valor: str) -> None:
    if not valor or not str(valor).strip():
        return
    texto = str(valor).strip()
    if campo == "precio_referencia_ars":
        datos[campo] = _parsear_precio(texto)
    elif campo == "ano":
        datos[campo] = int(_solo_digitos(texto)[:4])
    elif campo == "kilometros":
        datos[campo] = _parsear_km(texto)
    elif campo == "patente":
        datos[campo] = re.sub(r"\s+", "", texto).upper()
    elif campo == "marca":
        datos[campo] = texto.title()
    elif campo == "estado":
        datos[campo] = texto.capitalize()
    elif campo == "tipo":
        datos[campo] = texto.title()
    else:
        datos[campo] = texto


def _fila_a_datos(agencia_id: int, fila: list[str], mapa: dict[int, str], numero_fila: int = 0) -> dict:
    datos: dict = {"agencia_id": agencia_id}
    for col, campo in mapa.items():
        if col < len(fila):
            _aplicar_valor(datos, campo, fila[col])

    if "marca" not in datos and "modelo" in datos:
        partes = str(datos["modelo"]).split(maxsplit=1)
        if partes[0].lower() in MARCAS_CONOCIDAS:
            datos["marca"] = partes[0].title()
            datos["modelo"] = partes[1] if len(partes) > 1 else "Base"

    if "marca" not in datos:
        datos["marca"] = "Sin marca"
    if "modelo" not in datos:
        datos["modelo"] = datos.get("version", "Sin modelo")
    if "version" not in datos:
        datos["version"] = str(datos["modelo"])
    if "tipo" not in datos:
        datos["tipo"] = "Sedan"
    if "ano" not in datos:
        datos["ano"] = 2015
    if "precio_referencia_ars" not in datos:
        datos["precio_referencia_ars"] = 0.0
    if "patente" not in datos:
        datos["patente"] = f"IMP{datos['ano']}{numero_fila:04d}"
    if "estado" not in datos:
        datos["estado"] = "Disponible"

    return datos


def _crear_auto_desde_datos(datos: dict) -> Auto:
    campos_auto = {
        k: v for k, v in datos.items()
        if k in {
            "agencia_id", "marca", "modelo", "version", "ano", "tipo", "patente",
            "precio_referencia_ars", "estado", "foto_principal_url", "kilometros",
        }
    }
    return Auto(**campos_auto)


def importar_csv(agencia_id: int, contenido: str, actualizar_por_patente: bool = True) -> ResultadoImportacion:
    resultado = ResultadoImportacion()
    encabezados, filas = _leer_filas(contenido)

    if not filas:
        resultado.errores.append("El archivo está vacío o no se pudieron leer filas de datos.")
        return resultado

    mapa = inferir_mapa_columnas(encabezados, filas)
    if not mapa:
        resultado.errores.append("No se pudieron detectar columnas en el archivo.")
        return resultado

    if "marca" not in mapa.values() and "modelo" not in mapa.values():
        resultado.errores.append("No se detectó marca ni modelo. Revisá el formato del archivo.")
        return resultado

    db = SessionLocal()
    try:
        for numero, fila in enumerate(filas, start=2):
            try:
                datos = _fila_a_datos(agencia_id, fila, mapa, numero_fila=numero)
                if not datos.get("marca") or datos.get("marca") == "Sin marca":
                    if all(not c.strip() for c in fila):
                        continue
                auto_nuevo = _crear_auto_desde_datos(datos)
                existente = None
                if actualizar_por_patente and auto_nuevo.patente and not auto_nuevo.patente.startswith("IMP"):
                    existente = (
                        db.query(Auto)
                        .filter(Auto.agencia_id == agencia_id, Auto.patente == auto_nuevo.patente)
                        .first()
                    )
                if existente:
                    for attr in (
                        "marca", "modelo", "version", "ano", "tipo",
                        "precio_referencia_ars", "estado", "kilometros",
                    ):
                        valor = getattr(auto_nuevo, attr, None)
                        if valor is not None:
                            setattr(existente, attr, valor)
                    if auto_nuevo.foto_principal_url:
                        existente.foto_principal_url = auto_nuevo.foto_principal_url
                    resultado.actualizados += 1
                else:
                    db.add(auto_nuevo)
                    resultado.creados += 1
            except Exception as exc:
                resultado.errores.append(f"Fila {numero}: {exc}")
        db.commit()
    finally:
        db.close()

    return resultado
