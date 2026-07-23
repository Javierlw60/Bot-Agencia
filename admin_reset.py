"""Reset de datos multi-tenant (agencias y todo lo asociado).

Protegido por ADMIN_RESET_TOKEN. Útil para limpiar registros a medias
(email nunca verificado, Phone Number ID mal asignado, etc.).

Uso HTTP (tras deploy):
  POST /admin/reset-agencias?token=TU_TOKEN&confirm=BORRAR_TODO

Uso CLI:
  ADMIN_RESET_TOKEN=... DATABASE_URL=... python admin_reset.py --yes
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from models.database import (
    Agencia,
    Auto,
    Cita,
    HistorialConversacion,
    MensajeConversacion,
    PagoMercadoPago,
    ProspectoLead,
    SessionLocal,
    Sucursal,
    TokenVerificacion,
    Usuario,
    Vendedor,
)

router = APIRouter(tags=["admin"])


def _token_esperado() -> str:
    return (os.getenv("ADMIN_RESET_TOKEN") or "").strip()


def listar_agencias_resumen() -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        filas = []
        for ag in db.query(Agencia).order_by(Agencia.id).all():
            usuarios = (
                db.query(Usuario).filter(Usuario.agencia_id == ag.id).all()
            )
            filas.append(
                {
                    "id": ag.id,
                    "nombre": ag.nombre,
                    "whatsapp_phone_number_id": ag.whatsapp_phone_number_id,
                    "usuarios": [
                        {
                            "email": u.email,
                            "email_verificado": bool(u.email_verificado),
                            "activo": bool(u.activo),
                        }
                        for u in usuarios
                    ],
                }
            )
        return filas
    finally:
        db.close()


def borrar_todas_las_agencias() -> dict[str, int]:
    """Borra todas las agencias y datos relacionados. Irreversible."""
    db = SessionLocal()
    contadores: dict[str, int] = {}
    try:
        # Orden por dependencias de FKs (hijos → padres).
        pasos: list[tuple[str, Any]] = [
            ("tokens_verificacion", db.query(TokenVerificacion)),
            ("citas", db.query(Cita)),
            ("mensajes_conversacion", db.query(MensajeConversacion)),
            ("historial_conversaciones", db.query(HistorialConversacion)),
            ("prospectos_leads", db.query(ProspectoLead)),
            ("autos", db.query(Auto)),
            ("pagos_mercadopago", db.query(PagoMercadoPago)),
            ("vendedores", db.query(Vendedor)),
            ("usuarios", db.query(Usuario)),
            ("sucursales", db.query(Sucursal)),
            ("agencias", db.query(Agencia)),
        ]
        for nombre, consulta in pasos:
            contadores[nombre] = consulta.delete(synchronize_session=False)

        # Por si quedaron secuencias raras en Postgres (opcional / best-effort).
        try:
            db.execute(text("SELECT 1"))
        except Exception:
            pass

        db.commit()
        print(f"[ADMIN RESET] Borrado completo: {contadores}")
        return contadores
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get("/admin/agencias")
def admin_listar_agencias(token: str = Query(...)):
    """Lista agencias (requiere ADMIN_RESET_TOKEN)."""
    esperado = _token_esperado()
    if not esperado or token != esperado:
        raise HTTPException(status_code=403, detail="Token inválido")
    return {"agencias": listar_agencias_resumen()}


@router.post("/admin/reset-agencias")
def admin_reset_agencias(
    token: str = Query(...),
    confirm: str = Query(..., description="Debe ser exactamente BORRAR_TODO"),
):
    """Borra TODAS las agencias y datos. Irreversible."""
    esperado = _token_esperado()
    if not esperado or token != esperado:
        raise HTTPException(status_code=403, detail="Token inválido")
    if confirm != "BORRAR_TODO":
        raise HTTPException(
            status_code=400,
            detail="Pasá confirm=BORRAR_TODO para ejecutar el borrado",
        )
    antes = listar_agencias_resumen()
    contadores = borrar_todas_las_agencias()
    return {
        "ok": True,
        "borrado": contadores,
        "agencias_antes": antes,
        "mensaje": "Listo. Registrá de nuevo tu agencia y verificá el email.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Borra todas las agencias de la BD")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirma el borrado sin preguntar",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Solo lista agencias, no borra",
    )
    args = parser.parse_args()

    resumen = listar_agencias_resumen()
    print(f"Agencias encontradas: {len(resumen)}")
    for ag in resumen:
        print(
            f"  id={ag['id']} nombre={ag['nombre']!r} "
            f"wa={ag['whatsapp_phone_number_id']!r} usuarios={ag['usuarios']}"
        )

    if args.list:
        return
    if not args.yes:
        print("Re-ejecutá con --yes para borrar todo.")
        return
    print(borrar_todas_las_agencias())


if __name__ == "__main__":
    main()
