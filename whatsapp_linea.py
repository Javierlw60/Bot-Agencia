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
    """Heurística: ID de Meta (dígitos, no formato celular AR)."""
    norm = _solo_digitos(valor)
    if not norm or len(norm) < 10:
        return False
    return not parece_celular_argentino(norm)


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
      2. agencias.whatsapp_phone_number_id
      3. vendedor/sucursal solo si no parecen celular 549…
      4. WHATSAPP_PHONE_NUMBER_ID del .env
    """
    candidatos: list[str] = []

    if phone_number_id_receptor:
        candidatos.append(phone_number_id_receptor.strip())

    if agencia.whatsapp_phone_number_id:
        candidatos.append(agencia.whatsapp_phone_number_id.strip())

    if vendedor and vendedor.telefono_whatsapp:
        candidatos.append(vendedor.telefono_whatsapp.strip())

    if sucursal and sucursal.telefono_whatsapp:
        candidatos.append(sucursal.telefono_whatsapp.strip())

    env_id = whatsapp_phone_number_id()
    if env_id:
        candidatos.append(env_id)

    for valor in candidatos:
        if es_phone_number_id_meta(valor):
            return valor.strip()

    for valor in candidatos:
        if valor:
            return valor.strip()

    return ""
