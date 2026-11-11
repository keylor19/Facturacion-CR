"""
Configuración de Celery: el worker procesa en segundo plano los envíos a
Hacienda, las consultas de estado, los correos y los webhooks; beat programa
las tareas periódicas (reintentos, consulta de enviados, buzones de correo,
paquetes y suscripciones por vencer, certificados y datos públicos de
Hacienda). Las tareas están en workers/tasks.py.
"""
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
        # Importa las facturas de proveedores que llegaron a los buzones de correo
        "revisar-buzones": {
            "task": "workers.tasks.revisar_buzones",
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
        # Emite las facturas recurrentes del día (alquileres, mensualidades) (diaria, 7:00)
        "emitir-recurrentes": {
            "task": "workers.tasks.emitir_recurrentes",
            "schedule": crontab(hour=7, minute=0),
        },
        # Factura mensual de los servicios del mes anterior (día 1, 6:30)
        "facturar-mensualidades": {
            "task": "workers.tasks.facturar_mensualidades",
            "schedule": crontab(day_of_month=1, hour=6, minute=30),
        },
        # Recordatorio de mensualidades por vencer y aviso de suspensión (diaria, 9:00)
        "recordar-mensualidades": {
            "task": "workers.tasks.recordar_mensualidades",
            "schedule": crontab(hour=9, minute=0),
        },
        # Recordatorio por correo a clientes con facturas a crédito vencidas (diaria, 8:00)
        "recordar-cobros": {
            "task": "workers.tasks.recordar_cobros",
            "schedule": crontab(hour=8, minute=0),
        },
        # Refresca los datos públicos de Hacienda guardados (contribuyentes,
        # exoneraciones, CABYS...), tipo de cambio del día y versión nueva del catálogo CABYS (3:00)
        "actualizar-datos-hacienda": {
            "task": "workers.tasks.actualizar_datos_hacienda",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
