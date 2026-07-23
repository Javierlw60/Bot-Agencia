"""Resolución del Phone Number ID de Meta para envío por Graph API."""

import re

from models.database import Agencia, Sucursal, Vendedor
from whatsapp_config import whatsapp_phone_number_id


def _solo_digitos(valor: str | None) -> str:
    if not valor:
        return ""
    return re.sub(r"\D", "", str(valor).strip())


def parece_celular_argentino(valor: str | None) -> bool:
    """True si el valor parece un móvil 549… y no un Phone Number ID de Meta."""
    norm = _solo_digitos(valor)
    return norm.startswith("54") and len(norm) >= 11


def es_phone_number_id_meta(valor: str | None) -> bool:
    """Heurística: Phone Number ID de Meta (largo, solo dígitos, no celular AR)."""
    norm = _solo_digitos(valor)
    # Meta Phone Number IDs suelen tener 14–18 dígitos. Un celular AR local
    # (ej. 1123014256) tiene ~10 y no debe confundirse con la línea del bot.
    if not norm or len(norm) < 14:
        return False
    return not parece_celular_argentino(norm)


def normalizar_celular_destino_wa(telefono: str | None) -> str:
    """Normaliza destino E.164 para Graph API (prioriza Argentina 549…)."""
    digits = _solo_digitos(telefono)
    if not digits:
        return ""
    # Ya viene internacional AR
    if digits.startswith("549") and len(digits) >= 12:
        return digits
    if digits.startswith("54") and not digits.startswith("549") and len(digits) >= 12:
        # 54 + área + número → insertar 9 móvil si parece fijo/móvil sin 9
        resto = digits[2:]
        if resto.startswith("9"):
            return digits
        return "549" + resto
    # Local CABA/GBA: 11 + 8 dígitos
    if digits.startswith("11") and len(digits) == 10:
        return "549" + digits
    # 15XXXXXXXX (móvil local viejo) → asumir área 11
    if digits.startswith("15") and len(digits) == 10:
        return "54911" + digits[2:]
    return digits


def linea_envio_whatsapp_api(
    agencia: Agencia,
    *,
    phone_number_id_receptor: str | None = None,
    sucursal: Sucursal | None = None,
    vendedor: Vendedor | None = None,
) -> str:
    """
    Devuelve el Phone Number ID correcto para POST …/{id}/messages.

    Prioridad:
      1. ID del webhook Meta (metadata.phone_number_id) — siempre válido para enviar.
      2. agencias.whatsapp_phone_number_id (línea oficial del bot)
      3. WHATSAPP_PHONE_NUMBER_ID del .env

    Los celulares de vendedor/sucursal no se usan para enviar por Graph API.
    """
    del sucursal, vendedor  # compatibilidad de firma; no rutean el envío

    candidatos: list[str] = []

    if phone_number_id_receptor:
        candidatos.append(phone_number_id_receptor.strip())

    if agencia.whatsapp_phone_number_id:
        candidatos.append(agencia.whatsapp_phone_number_id.strip())

    env_id = whatsapp_phone_number_id()
    if env_id:
        candidatos.append(env_id)

    for valor in candidatos:
        if es_phone_number_id_meta(valor):
            return valor.strip()

    for valor in candidatos:
        if valor and not parece_celular_argentino(valor):
            return valor.strip()

    return ""
