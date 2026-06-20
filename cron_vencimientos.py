"""Ejecutar manualmente o desde cron externo del sistema operativo."""

from models.database import inicializar_base_de_datos
from suscripcion_agencias import procesar_vencimientos_vencidos

if __name__ == "__main__":
    inicializar_base_de_datos()
    total = procesar_vencimientos_vencidos()
    print(f"[CRON] Agencias bloqueadas por vencimiento: {total}")
