from celery import Celery
from config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "facturacion",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Costa_Rica",
    enable_utc=True,
    task_acks_late=True,          # si el worker muere a medio envío, se reintenta
    worker_prefetch_multiplier=1,  # evita que un worker acapare varias facturas
)
