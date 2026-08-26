"""
Worker asíncrono: toma una factura ya generada/firmada en BD y la envía a
Hacienda. Nunca se hace esto en el request HTTP original — el usuario no
debe esperar a Hacienda en tiempo real.
"""
from datetime import datetime

from workers.celery_app import celery_app
from api.models.database import SessionLocal, Factura, FacturaEvento, EstadoFactura
from api.services import hacienda_client


def _registrar_evento(db, factura_id, evento, detalle=""):
    db.add(FacturaEvento(factura_id=factura_id, evento=evento, detalle=detalle))
    db.commit()


@celery_app.task(bind=True, max_retries=5, default_retry_delay=60)
def enviar_a_hacienda(self, factura_id: str):
    db = SessionLocal()
    try:
        factura = db.query(Factura).filter(Factura.id == factura_id).first()
        if not factura:
            return {"error": "factura no encontrada"}

        factura.intentos_envio += 1
        factura.ultimo_envio = datetime.utcnow()
        factura.estado = EstadoFactura.ENVIADO
        db.commit()

        try:
            resp = hacienda_client.enviar_comprobante(
                clave=factura.clave,
                fecha_iso=factura.fecha_emision.strftime("%Y-%m-%dT%H:%M:%S-06:00"),
                emisor_tipo_identificacion=factura.emisor_tipo_identificacion,
                emisor_numero_identificacion=factura.emisor_identificacion,
                receptor_tipo_identificacion=factura.receptor_tipo_identificacion,
                receptor_numero_identificacion=factura.receptor_identificacion,
                xml_firmado=factura.xml_firmado,
            )
        except Exception as exc:
            _registrar_evento(db, factura.id, "ERROR_RED", str(exc))
            factura.estado = EstadoFactura.ERROR_COMUNICACION
            db.commit()
            # Backoff exponencial simple: 60s, 120s, 240s...
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))

        if resp.status_code in (200, 201, 202):
            # Recepción confirmada por Hacienda. La aceptación/rechazo FISCAL
            # llega después por el callback (ver routes/callback.py) o se
            # puede consultar con consultar_estado_task más abajo.
            _registrar_evento(db, factura.id, "ENVIO_OK", f"HTTP {resp.status_code}")
            db.commit()
            return {"status": "enviado", "http_status": resp.status_code}

        elif resp.status_code == 409:
            # Clave duplicada: ya fue recibida antes. No reintentar, solo
            # consultar el estado real.
            _registrar_evento(db, factura.id, "CLAVE_DUPLICADA", resp.text)
            consultar_estado_task.delay(factura_id)
            return {"status": "duplicado"}

        elif 400 <= resp.status_code < 500:
            # Error de estructura/firma: reintentar NO va a arreglar esto.
            factura.estado = EstadoFactura.RECHAZADO
            factura.mensaje_hacienda = resp.text[:2000]
            _registrar_evento(db, factura.id, "RECHAZO_ESTRUCTURA", resp.text[:2000])
            db.commit()
            return {"status": "rechazado", "detalle": resp.text}

        else:
            # 5xx de Hacienda: sí vale la pena reintentar.
            _registrar_evento(db, factura.id, "ERROR_5XX_HACIENDA", f"HTTP {resp.status_code}")
            raise self.retry(countdown=60 * (2 ** self.request.retries))

    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def consultar_estado_task(self, factura_id: str):
    """Consulta activa del estado (fallback si el callback nunca llegó)."""
    db = SessionLocal()
    try:
        factura = db.query(Factura).filter(Factura.id == factura_id).first()
        if not factura:
            return {"error": "factura no encontrada"}

        data = hacienda_client.consultar_estado(factura.clave)
        estado_hacienda = data.get("ind-estado", data.get("estado", ""))

        factura.estado_hacienda = estado_hacienda
        if estado_hacienda in ("aceptado",):
            factura.estado = EstadoFactura.ACEPTADO
        elif estado_hacienda in ("rechazado",):
            factura.estado = EstadoFactura.RECHAZADO

        _registrar_evento(db, factura.id, "CONSULTA_ESTADO", str(data))
        db.commit()
        return {"status": estado_hacienda}
    finally:
        db.close()


@celery_app.task
def reintentar_contingencia():
    """
    Tarea periódica (configurar con Celery Beat cada 5-10 min) que reenvía
    todas las facturas atascadas en estado CONTINGENCIA o ERROR_COMUNICACION.
    """
    db = SessionLocal()
    try:
        pendientes = db.query(Factura).filter(
            Factura.estado.in_([EstadoFactura.CONTINGENCIA, EstadoFactura.ERROR_COMUNICACION]),
            Factura.intentos_envio < 10,
        ).all()
        for factura in pendientes:
            enviar_a_hacienda.delay(str(factura.id))
        return {"reencolados": len(pendientes)}
    finally:
        db.close()
