"""Estados del ciclo de vida de una cita y utilidades de conversión.

Embudo: Pendiente → En curso → (Venta concretada | Venta perdida).
Solo "concretada" cuenta como venta para las estadísticas de conversión.
"""

ESTADO_PENDIENTE = "pendiente"
ESTADO_EN_CURSO = "en_curso"
ESTADO_CONCRETADA = "concretada"
ESTADO_PERDIDA = "perdida"

ESTADO_VENTA = ESTADO_CONCRETADA
ESTADO_DEFAULT = ESTADO_PENDIENTE

# Orden de presentación en selectores y leyendas.
ESTADOS_CITA: list[tuple[str, str]] = [
    (ESTADO_PENDIENTE, "Pendiente"),
    (ESTADO_EN_CURSO, "En curso"),
    (ESTADO_CONCRETADA, "Venta concretada"),
    (ESTADO_PERDIDA, "Venta perdida"),
]

ETIQUETAS_ESTADO_CITA: dict[str, str] = dict(ESTADOS_CITA)
ESTADOS_VALIDOS: set[str] = set(ETIQUETAS_ESTADO_CITA)

# Mapeo de valores antiguos (free-text legacy) a estados canónicos.
_ALIAS_LEGACY = {
    "confirmada": ESTADO_PENDIENTE,
    "confirmado": ESTADO_PENDIENTE,
    "agendada": ESTADO_PENDIENTE,
    "pendiente": ESTADO_PENDIENTE,
    "en curso": ESTADO_EN_CURSO,
    "en_curso": ESTADO_EN_CURSO,
    "concretada": ESTADO_CONCRETADA,
    "vendida": ESTADO_CONCRETADA,
    "venta concretada": ESTADO_CONCRETADA,
    "perdida": ESTADO_PERDIDA,
    "venta perdida": ESTADO_PERDIDA,
    "cancelada": ESTADO_PERDIDA,
}


def normalizar_estado_cita(valor: str | None) -> str:
    """Devuelve un estado canónico válido a partir de cualquier valor."""
    clave = (valor or "").strip().lower()
    if clave in ESTADOS_VALIDOS:
        return clave
    return _ALIAS_LEGACY.get(clave, ESTADO_DEFAULT)


def etiqueta_estado_cita(valor: str | None) -> str:
    return ETIQUETAS_ESTADO_CITA[normalizar_estado_cita(valor)]


def es_venta(valor: str | None) -> bool:
    return normalizar_estado_cita(valor) == ESTADO_VENTA
