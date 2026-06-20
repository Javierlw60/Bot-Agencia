MODO_RESPUESTA_TEXTO = "texto"
MODO_RESPUESTA_VOZ = "voz"
MODO_RESPUESTA_AMBAS = "ambas"

MODOS_RESPUESTA_VALIDOS = {
    MODO_RESPUESTA_TEXTO,
    MODO_RESPUESTA_VOZ,
    MODO_RESPUESTA_AMBAS,
}

ETIQUETAS_MODO_RESPUESTA = {
    MODO_RESPUESTA_TEXTO: "Solo texto",
    MODO_RESPUESTA_VOZ: "Solo voz",
    MODO_RESPUESTA_AMBAS: "Texto y voz",
}


def normalizar_modo_respuesta(valor: str | None) -> str:
    modo = (valor or MODO_RESPUESTA_TEXTO).strip().lower()
    if modo not in MODOS_RESPUESTA_VALIDOS:
        return MODO_RESPUESTA_TEXTO
    return modo


def debe_enviar_texto(modo: str) -> bool:
    return modo in {MODO_RESPUESTA_TEXTO, MODO_RESPUESTA_AMBAS}


def debe_enviar_voz(modo: str) -> bool:
    return modo in {MODO_RESPUESTA_VOZ, MODO_RESPUESTA_AMBAS}
