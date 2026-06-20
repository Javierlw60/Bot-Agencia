import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from recordatorios import procesar_recordatorios_pendientes
from suscripcion_agencias import procesar_vencimientos_vencidos

_scheduler: BackgroundScheduler | None = None


def _ejecutar_recordatorios() -> None:
    try:
        procesar_recordatorios_pendientes()
    except Exception as exc:
        print(f"[RECORDATORIOS] Error: {exc}")


def _ejecutar_vencimientos() -> None:
    try:
        total = procesar_vencimientos_vencidos()
        if total:
            print(f"[SUSCRIPCIÓN] Cron diario: {total} agencia(s) bloqueada(s).")
    except Exception as exc:
        print(f"[SUSCRIPCIÓN] Error en cron de vencimientos: {exc}")


def iniciar_schedulers() -> BackgroundScheduler | None:
    global _scheduler

    recordatorios_on = os.getenv("RECORDATORIOS_ACTIVOS", "true").lower() not in {
        "0", "false", "no",
    }
    vencimientos_on = os.getenv("VENCIMIENTOS_CRON_ACTIVO", "true").lower() not in {
        "0", "false", "no",
    }

    if not recordatorios_on and not vencimientos_on:
        print("[SCHEDULER] Todas las tareas de fondo están desactivadas.")
        return None

    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler()

    if recordatorios_on:
        intervalo = int(os.getenv("RECORDATORIOS_INTERVALO_MIN", "15"))
        _scheduler.add_job(
            _ejecutar_recordatorios,
            trigger=IntervalTrigger(minutes=intervalo),
            id="recordatorios_citas",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        print(f"[RECORDATORIOS] Activo — cada {intervalo} min.")

    if vencimientos_on:
        hora = int(os.getenv("VENCIMIENTOS_CRON_HORA", "6"))
        minuto = int(os.getenv("VENCIMIENTOS_CRON_MINUTO", "0"))
        _scheduler.add_job(
            _ejecutar_vencimientos,
            trigger=CronTrigger(hour=hora, minute=minuto),
            id="vencimientos_agencias",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        print(f"[SUSCRIPCIÓN] Cron diario de vencimientos — {hora:02d}:{minuto:02d} hs.")

        _ejecutar_vencimientos()

    _scheduler.start()
    return _scheduler


def detener_schedulers() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        print("[SCHEDULER] Detenido.")
    _scheduler = None


# Compatibilidad con imports anteriores
iniciar_scheduler_recordatorios = iniciar_schedulers
detener_scheduler_recordatorios = detener_schedulers
