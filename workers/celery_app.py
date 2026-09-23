from celery import Celery
from config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "facturacion",
    broker=settings.REDIS_URL,
    include=["workers.tasks"],  # sin esto el worker no registra las tareas
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    timezone="America/Costa_Rica",
    enable_utc=True,
    task_acks_late=True,           # si el worker muere a medio envío, se reintenta
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # evita que un worker acapare varias facturas
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Reenvía lo que quedó PENDIENTE / ERROR_COMUNICACION / CONTINGENCIA
        "reintentar-pendientes": {
            "task": "workers.tasks.reintentar_pendientes",
            "schedule": 300.0,
        },
        # Consulta el estado de lo ENVIADO cuyo callback nunca llegó
        "consultar-enviados": {
            "task": "workers.tasks.consultar_enviados",
            "schedule": 600.0,
        },
        # Alerta de certificados digitales vencidos o por vencer (diaria)
        "revisar-certificados": {
            "task": "workers.tasks.revisar_certificados",
            "schedule": 86400.0,
        },
        # Aviso de paquetes de documentos por vencer (diaria)
        "revisar-paquetes": {
            "task": "workers.tasks.revisar_paquetes",
            "schedule": 86400.0,
        },
    },
)
