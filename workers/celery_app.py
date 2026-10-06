from celery import Celery
from celery.schedules import crontab
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
        # Tareas diarias a hora fija (hora de Costa Rica): no dependen de reinicios del contenedor
        # Alerta de certificados digitales vencidos o por vencer (diaria, 6:00)
        "revisar-certificados": {
            "task": "workers.tasks.revisar_certificados",
            "schedule": crontab(hour=6, minute=0),
        },
        # Aviso de paquetes de documentos por vencer (diaria, 6:10)
        "revisar-paquetes": {
            "task": "workers.tasks.revisar_paquetes",
            "schedule": crontab(hour=6, minute=10),
        },
        # Aviso de servicios alquilados por vencer o vencidos (diaria, 6:20)
        "revisar-suscripciones": {
            "task": "workers.tasks.revisar_suscripciones",
            "schedule": crontab(hour=6, minute=20),
        },
        # Refresca los datos públicos de Hacienda guardados (contribuyentes,
        # exoneraciones, CABYS...), tipo de cambio del día y versión nueva del catálogo CABYS (3:00)
        "actualizar-datos-hacienda": {
            "task": "workers.tasks.actualizar_datos_hacienda",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
