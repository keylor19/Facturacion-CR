"""
Workers asíncronos: envían a Hacienda los comprobantes emitidos y los
mensajes receptor, consultan su estado, envían correos y webhooks.
Nunca se hace esto en el request HTTP original.

`tipo` identifica la tabla: "factura" (comprobantes emitidos) o
"recibido" (mensaje receptor de un documento recibido).
"""
from datetime import timedelta

import requests
from celery.utils.log import get_task_logger
from sqlalchemy import func, select

from workers.celery_app import celery_app
from api.models.database import (
    SessionLocal, BuzonCorreo, Emisor, Factura, DocumentoRecibido, FacturaEvento, EstadoFactura, Paquete,
    ESTADOS_REENVIABLES, ESTADOS_FINALES, utcnow,
)
from api.services import (
    administracion, buzon, catalogo_cabys, cobros, correo, emisores, hacienda_client, hacienda_publico, inventario,
    mensualidades, recurrentes, suscripciones, webhooks,
)
from api.services.fechas import zona_cr
from api.services.hacienda_auth import HaciendaAuthError
from config.settings import get_settings

logger = get_task_logger(__name__)
settings = get_settings()

MODELOS = {"factura": Factura, "recibido": DocumentoRecibido}
ESTADOS_EN_PROCESO = ("recibido", "procesando")


def _modelo(tipo: str):
    if tipo not in MODELOS:
        raise ValueError(f"Tipo de documento desconocido: {tipo}")
    return MODELOS[tipo]


def _registrar_evento(db, doc, evento, detalle=""):
    campo = "factura_id" if isinstance(doc, Factura) else "documento_recibido_id"
    db.add(FacturaEvento(**{campo: doc.id}, evento=evento, detalle=(detalle or "")[:4000]))


def _backoff(reintentos: int) -> int:
    """60s, 120s, 240s... con tope de 1 hora."""
    return min(60 * (2 ** reintentos), 3600)


def _tipo_de(doc) -> str:
    return "factura" if isinstance(doc, Factura) else "recibido"


def _al_cambiar_estado(doc) -> None:
    """Acciones posteriores a un cambio de estado: webhook y correo."""
    tipo = _tipo_de(doc)
    if doc.estado in ESTADOS_FINALES or doc.estado == EstadoFactura.ERROR_COMUNICACION:
        evento = ("comprobante." if tipo == "factura" else "mensaje_receptor.") + doc.estado.value.lower()
        _encolar(notificar_webhook, tipo, str(doc.id), evento)
    if tipo == "factura" and doc.estado == EstadoFactura.ACEPTADO and doc.receptor_correo and not doc.correo_enviado:
        _encolar(enviar_correo, str(doc.id))


def _revertir_inventario(db, doc) -> None:
    """Comprobante rechazado: la venta/compra no existe, se devuelven las existencias."""
    if isinstance(doc, Factura):
        n = inventario.revertir_documento(db, doc)
        if n:
            _registrar_evento(db, doc, "INVENTARIO_REVERTIDO", f"{n} producto(s)")


def _encolar(tarea, *args, **kwargs):
    try:
        tarea.apply_async(args=args, kwargs=kwargs)
    except Exception:
        logger.exception("No se pudo encolar %s%s", tarea.name, args)


def aplicar_respuesta_hacienda(db, doc, data: dict, evento: str) -> str:
    """Actualiza el documento con la respuesta (consulta de estado) de Hacienda."""
    r = hacienda_client.interpretar_respuesta(data)
    estado = r["estado"]
    anterior = doc.estado

    doc.estado_hacienda = estado[:100] or None
    if r["xml"]:
        doc.xml_respuesta = r["xml"]
    if r["mensaje"]:
        doc.mensaje_hacienda = r["mensaje"][:4000]

    if estado == "aceptado":
        doc.estado = EstadoFactura.ACEPTADO
    elif estado == "rechazado":
        doc.estado = EstadoFactura.RECHAZADO
        _revertir_inventario(db, doc)
    elif estado == "error":
        # Hacienda no pudo procesarlo: queda para revisión/reenvío (acotado por MAX_INTENTOS_ENVIO)
        doc.estado = EstadoFactura.ERROR_COMUNICACION

    _registrar_evento(db, doc, evento, f"ind-estado={estado or '?'}")
    db.commit()
    if doc.estado != anterior:
        _al_cambiar_estado(doc)
    return estado


def _fallo_comunicacion(task, db, doc, evento: str, detalle: str):
    """Marca el error y reintenta con backoff; si se agotan los reintentos lo retoma beat."""
    doc.estado = EstadoFactura.ERROR_COMUNICACION
    doc.mensaje_hacienda = detalle[:4000]
    _registrar_evento(db, doc, evento, detalle)
    db.commit()
    logger.warning("%s %s: %s (%s)", _tipo_de(doc), doc.id, evento, detalle[:200])

    if task.request.retries >= task.max_retries:
        _al_cambiar_estado(doc)
        return {"status": "error_comunicacion", "detalle": detalle[:200]}
    raise task.retry(countdown=_backoff(task.request.retries))


@celery_app.task(bind=True, max_retries=5)
def enviar_documento(self, tipo: str, doc_id: str):
    modelo = _modelo(tipo)
    db = SessionLocal()
    try:
        # Bloqueo de la fila: evita que dos workers (reenvío manual + beat)
        # envíen el mismo documento al mismo tiempo.
        doc = db.execute(
            select(modelo).where(modelo.id == doc_id).with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if doc is None:
            return {"status": "omitido", "motivo": "no encontrado o en proceso por otro worker"}
        if doc.estado not in ESTADOS_REENVIABLES:
            return {"status": "omitido", "motivo": f"estado {doc.estado.value if doc.estado else None}"}

        doc.intentos_envio += 1
        doc.ultimo_envio = utcnow()
        doc.estado = EstadoFactura.ENVIADO
        db.commit()  # libera el lock; otros envíos verán ENVIADO y no reenviarán

        try:
            resp = hacienda_client.enviar(doc.emisor, doc.envio_json, doc.xml_firmado)
        except HaciendaAuthError as exc:
            # Credenciales inválidas o faltantes: reintentar no lo arregla (beat lo
            # retomará cuando se corrijan las credenciales).
            doc.estado = EstadoFactura.ERROR_COMUNICACION
            doc.mensaje_hacienda = str(exc)[:4000]
            _registrar_evento(db, doc, "ERROR_AUTENTICACION", str(exc))
            db.commit()
            _al_cambiar_estado(doc)
            return {"status": "error_autenticacion"}
        except requests.RequestException as exc:
            return _fallo_comunicacion(self, db, doc, "ERROR_RED", str(exc))

        causa = hacienda_client.error_cause(resp)

        if resp.status_code in (200, 201, 202):
            # Recepción confirmada. La aceptación/rechazo FISCAL llega luego
            # por callback; igual programamos una consulta por si no llega.
            _registrar_evento(db, doc, "ENVIO_OK", f"HTTP {resp.status_code}")
            db.commit()
            _encolar_consulta(tipo, doc_id, countdown=60)
            return {"status": "enviado", "http_status": resp.status_code}

        if resp.status_code == 409 or (resp.status_code == 400 and "ya fue recibido" in causa.lower()):
            # Ya recibido antes: no reenviar, solo consultar el estado real.
            _registrar_evento(db, doc, "CLAVE_DUPLICADA", causa)
            db.commit()
            _encolar_consulta(tipo, doc_id)
            return {"status": "duplicado"}

        if resp.status_code in (401, 403):
            # Credenciales/permisos: no es un rechazo del documento.
            doc.estado = EstadoFactura.ERROR_COMUNICACION
            doc.mensaje_hacienda = f"Error de autenticación con Hacienda (HTTP {resp.status_code})"
            _registrar_evento(db, doc, "ERROR_AUTENTICACION", causa)
            db.commit()
            logger.error("Hacienda respondió %s para el emisor %s: revisar credenciales/ambiente",
                         resp.status_code, doc.emisor_id)
            _al_cambiar_estado(doc)
            return {"status": "error_autenticacion"}

        if resp.status_code == 429 or resp.status_code >= 500:
            return _fallo_comunicacion(self, db, doc, "ERROR_HACIENDA", f"HTTP {resp.status_code}: {causa}")

        # Resto de 4xx: error de estructura/firma. Reintentar NO lo va a arreglar.
        doc.estado = EstadoFactura.RECHAZADO
        _revertir_inventario(db, doc)
        doc.mensaje_hacienda = causa[:4000]
        _registrar_evento(db, doc, "RECHAZO_RECEPCION", f"HTTP {resp.status_code}: {causa}")
        db.commit()
        _al_cambiar_estado(doc)
        return {"status": "rechazado", "detalle": causa[:500]}

    finally:
        db.close()


def _encolar_consulta(tipo: str, doc_id: str, countdown: int | None = None):
    try:
        consultar_documento.apply_async(args=(tipo, doc_id), countdown=countdown)
    except Exception:
        logger.exception("No se pudo encolar la consulta de %s %s", tipo, doc_id)


@celery_app.task(bind=True, max_retries=8)
def consultar_documento(self, tipo: str, doc_id: str):
    """Consulta activa del estado (fallback si el callback nunca llegó, o verificación de un callback)."""
    db = SessionLocal()
    try:
        doc = db.get(_modelo(tipo), doc_id)
        if doc is None:
            return {"error": "documento no encontrado"}
        if doc.estado in ESTADOS_FINALES or doc.estado is None:
            return {"status": doc.estado.value if doc.estado else None}

        try:
            data = hacienda_client.consultar_estado(doc.emisor, doc.clave_consulta)
        except hacienda_client.HaciendaClientError as exc:
            if exc.status_code == 404:
                # Hacienda nunca lo recibió: queda para reenvío.
                anterior = doc.estado
                doc.estado = EstadoFactura.ERROR_COMUNICACION
                _registrar_evento(db, doc, "NO_REGISTRADO_EN_HACIENDA", str(exc))
                db.commit()
                if anterior != doc.estado:
                    _al_cambiar_estado(doc)
                return {"status": "no_registrado"}
            if self.request.retries >= self.max_retries:
                raise
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))
        except (requests.RequestException, HaciendaAuthError) as exc:
            if self.request.retries >= self.max_retries:
                raise
            raise self.retry(exc=exc, countdown=_backoff(self.request.retries))

        estado = aplicar_respuesta_hacienda(db, doc, data, "CONSULTA_ESTADO")
        if estado in ESTADOS_EN_PROCESO and self.request.retries < self.max_retries:
            raise self.retry(countdown=_backoff(self.request.retries))
        return {"status": estado}
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=5)
def enviar_correo(self, factura_id: str, destinatarios: list[str] | None = None):
    """Envía XML firmado + respuesta de Hacienda + PDF al receptor."""
    if not settings.smtp_configurado:
        return {"status": "omitido", "motivo": "SMTP no configurado"}
    db = SessionLocal()
    try:
        factura = db.get(Factura, factura_id)
        if factura is None:
            return {"error": "factura no encontrada"}
        destinos = destinatarios or ([factura.receptor_correo] if factura.receptor_correo else [])
        if not destinos:
            return {"status": "omitido", "motivo": "sin destinatarios"}
        try:
            correo.enviar(correo.construir_mensaje(factura, destinos))
        except correo.CorreoError as exc:
            _registrar_evento(db, factura, "ERROR_CORREO", str(exc))
            db.commit()
            if self.request.retries >= self.max_retries:
                return {"status": "error", "detalle": str(exc)}
            raise self.retry(countdown=_backoff(self.request.retries))
        factura.correo_enviado = True
        _registrar_evento(db, factura, "CORREO_ENVIADO", ", ".join(destinos))
        db.commit()
        return {"status": "enviado"}
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=6)
def notificar_webhook(self, tipo: str, doc_id: str, evento: str):
    db = SessionLocal()
    try:
        doc = db.get(_modelo(tipo), doc_id)
        if doc is None or not doc.emisor.webhook_url:
            return {"status": "omitido"}
        payload = webhooks.payload_factura(doc, evento) if tipo == "factura" else webhooks.payload_recibido(doc, evento)
        try:
            webhooks.enviar(doc.emisor.webhook_url, emisores.webhook_secret(doc.emisor), payload)
        except webhooks.WebhookError as exc:
            if self.request.retries >= self.max_retries:
                _registrar_evento(db, doc, "ERROR_WEBHOOK", f"{evento}: {exc}")
                db.commit()
                return {"status": "error", "detalle": str(exc)}
            raise self.retry(countdown=_backoff(self.request.retries))
        return {"status": "enviado"}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tareas periódicas (Celery Beat)
# ---------------------------------------------------------------------------

@celery_app.task
def reintentar_pendientes():
    """Reencola lo PENDIENTE (p. ej. Redis caído al crearlo), en CONTINGENCIA o ERROR_COMUNICACION."""
    limite = utcnow() - timedelta(minutes=2)
    total = 0
    db = SessionLocal()
    try:
        for tipo, modelo in MODELOS.items():
            ids = db.scalars(
                select(modelo.id).where(
                    modelo.estado.in_(ESTADOS_REENVIABLES),
                    modelo.intentos_envio < settings.MAX_INTENTOS_ENVIO,
                    func.coalesce(modelo.ultimo_envio, modelo.created_at) < limite,
                ).limit(500)
            ).all()
            for doc_id in ids:
                enviar_documento.delay(tipo, str(doc_id))
            total += len(ids)
    finally:
        db.close()
    return {"reencolados": total}


@celery_app.task
def consultar_enviados():
    """Consulta el estado de lo ENVIADO hace más de 5 minutos."""
    limite = utcnow() - timedelta(minutes=5)
    total = 0
    db = SessionLocal()
    try:
        for tipo, modelo in MODELOS.items():
            ids = db.scalars(
                select(modelo.id).where(modelo.estado == EstadoFactura.ENVIADO, modelo.ultimo_envio < limite).limit(500)
            ).all()
            for doc_id in ids:
                consultar_documento.delay(tipo, str(doc_id))
            total += len(ids)
    finally:
        db.close()
    return {"consultados": total}


@celery_app.task
def revisar_certificados():
    """Avisa (log + webhook) de certificados vencidos o por vencer."""
    limite = utcnow() + timedelta(days=settings.DIAS_ALERTA_CERTIFICADO)
    db = SessionLocal()
    try:
        por_vencer = db.scalars(
            select(Emisor).where(Emisor.activo.is_(True), Emisor.cert_vence.is_not(None), Emisor.cert_vence < limite)
        ).all()
        for e in por_vencer:
            dias = (e.cert_vence - utcnow()).days
            logger.warning("El certificado del emisor %s (%s) vence en %s días", e.nombre, e.numero_identificacion, dias)
            if e.webhook_url:
                try:
                    webhooks.enviar(e.webhook_url, emisores.webhook_secret(e), {
                        "evento": "certificado.por_vencer", "emisor_id": str(e.id),
                        "vence": e.cert_vence.isoformat(), "dias": dias,
                    })
                except webhooks.WebhookError:
                    logger.warning("No se pudo notificar el vencimiento del certificado de %s", e.id)
        return {"por_vencer": len(por_vencer)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Saldo de documentos (venta por consumo)
# ---------------------------------------------------------------------------

MENSAJES_SALDO = {
    "saldo.bajo": ("Quedan pocos documentos", "A {nombre} le quedan {disponible} documentos disponibles para facturar."),
    "saldo.agotado": ("Se agotaron los documentos",
                      "{nombre} agotó su saldo de documentos: no podrá emitir hasta adquirir un nuevo paquete."),
    "paquete.por_vencer": ("Documentos por vencer",
                           "A {nombre} se le vencen {disponible} documentos el {vence}. Úselos antes de esa fecha."),
    "suscripcion.por_vencer": ("Su servicio vence pronto",
                               "El servicio de {servicio} de {nombre} vence el {vence}. Renuévelo para no interrumpir "
                               "la facturación."),
    "suscripcion.vencida": ("Su servicio venció",
                            "El servicio de {servicio} de {nombre} venció el {vence}. Se suspenderá en {gracia} día(s) "
                            "si no se renueva."),
}


@celery_app.task(bind=True, max_retries=5)
def notificar_saldo(self, emisor_id: str, evento: str, datos: dict):
    """Avisa a la empresa por webhook y por correo (si están configurados)."""
    db = SessionLocal()
    try:
        emisor = db.get(Emisor, emisor_id)
        if emisor is None:
            return {"status": "omitido"}
        payload = {"evento": evento, "emisor_id": emisor_id, **datos}
        enviados = []
        if emisor.webhook_url:
            try:
                webhooks.enviar(emisor.webhook_url, emisores.webhook_secret(emisor), payload)
                enviados.append("webhook")
            except webhooks.WebhookError:
                logger.warning("No se pudo notificar %s por webhook a %s", evento, emisor_id)
        if settings.smtp_configurado and evento in MENSAJES_SALDO:
            asunto, plantilla = MENSAJES_SALDO[evento]
            # Además del aviso, la invitación a comprar: planes, formas de pago y contacto
            cuerpo = f"{plantilla.format(nombre=emisor.nombre, **datos)}\n\n{administracion.texto_oferta(db, evento)}"
            ajustes = administracion.ajustes(db)
            msg = correo.mensaje_simple(emisor.correo, f"{asunto} - {emisor.nombre}", cuerpo)
            if ajustes.correo_avisos:
                msg["Reply-To"] = ajustes.correo_avisos   # la respuesta del cliente le llega al administrador
            try:
                correo.enviar(msg)
                enviados.append("correo")
            except correo.CorreoError:
                if self.request.retries < self.max_retries:
                    raise self.retry(countdown=_backoff(self.request.retries))
            if ajustes.correo_avisos and "correo" in enviados:
                try:
                    correo.enviar(correo.mensaje_simple(
                        ajustes.correo_avisos, f"[Aviso enviado] {asunto} - {emisor.nombre}",
                        f"Se le envió este aviso a {emisor.nombre} ({emisor.correo}):\n\n{cuerpo}"))
                    enviados.append("copia al administrador")
                except correo.CorreoError:
                    logger.warning("No se pudo enviar la copia del aviso %s de %s", evento, emisor_id)
        logger.info("Aviso %s para %s: %s", evento, emisor_id, enviados or "sin canales configurados")
        return {"status": "ok", "canales": enviados}
    finally:
        db.close()


@celery_app.task
def revisar_paquetes():
    """Diaria: avisa de documentos que vencen pronto."""
    ahora = utcnow()
    limite = ahora + timedelta(days=settings.DIAS_ALERTA_VENCIMIENTO_PAQUETE)
    db = SessionLocal()
    try:
        paquetes = db.scalars(select(Paquete).where(
            Paquete.anulado.is_(False), Paquete.usados < Paquete.documentos,
            Paquete.vence.is_not(None), Paquete.vence > ahora, Paquete.vence <= limite,
        )).all()
        for p in paquetes:
            notificar_saldo.delay(str(p.emisor_id), "paquete.por_vencer", {
                "disponible": p.disponibles, "vence": p.vence.astimezone(zona_cr()).strftime("%d/%m/%Y"),
            })
        return {"avisos": len(paquetes)}
    finally:
        db.close()


@celery_app.task
def revisar_suscripciones():
    """Diaria: avisa de servicios alquilados que vencen pronto o que acaban de vencer."""
    if not suscripciones.control_activo():
        return {"avisos": 0}
    ahora = utcnow()
    db = SessionLocal()
    try:
        avisos = 0
        for emisor in db.scalars(select(Emisor).where(Emisor.activo.is_(True), Emisor.solo_contabilidad.is_(False))).all():
            for est in suscripciones.estados(db, emisor):
                if not est["habilitado"] or est["vence"] is None:
                    continue
                if est["estado"] == "POR_VENCER":
                    evento = "suscripcion.por_vencer"
                elif est["vence"] < ahora and ahora - est["vence"] <= timedelta(days=1):
                    evento = "suscripcion.vencida"   # solo el primer día después del vencimiento
                else:
                    continue
                notificar_saldo.delay(str(emisor.id), evento, {
                    "servicio": suscripciones.minuscula_inicial(est["nombre"]), "vence": est["vence"].astimezone(zona_cr()).strftime("%d/%m/%Y"),
                    "gracia": settings.DIAS_GRACIA_SUSCRIPCION,
                })
                avisos += 1
        return {"avisos": avisos}
    finally:
        db.close()


@celery_app.task
def actualizar_datos_hacienda():
    """
    Diaria: guarda el tipo de cambio del día (histórico propio), importa el
    catálogo CABYS si el BCCR publicó una versión nueva (y verifica una muestra contra Hacienda),
    refresca los datos públicos de Hacienda con más de DIAS_ACTUALIZAR_HACIENDA días y precarga
    las cédulas de clientes y empresas.
    """
    resultado = {}
    try:
        resultado["tipo_cambio"] = hacienda_publico.tipos_de_cambio()["USD"]
    except hacienda_publico.HaciendaPublicoError as exc:
        resultado["tipo_cambio"] = f"sin actualizar: {exc}"
    # Catálogo CABYS: versión nueva publicada por el BCCR o archivo modificado -> se importa solo
    try:
        resultado["cabys"] = catalogo_cabys.actualizar_si_hay_version_nueva()
    except Exception as exc:  # un archivo dañado no debe detener el resto de la tarea
        logger.error("No se pudo actualizar el catálogo CABYS: %s", exc)
        resultado["cabys"] = str(exc)
    # Red de seguridad: una muestra del catálogo local se compara con Hacienda
    resultado["cabys_muestra"] = hacienda_publico.verificar_muestra_cabys()
    resultado["registros"] = hacienda_publico.actualizar_registros()
    logger.info("Datos de Hacienda actualizados: %s", resultado)
    return resultado


@celery_app.task
def revisar_buzones():
    """Cada 5 minutos: importa las facturas de proveedores que llegaron a los buzones de correo."""
    db = SessionLocal()
    try:
        ids = db.scalars(select(BuzonCorreo.id).join(Emisor, Emisor.id == BuzonCorreo.emisor_id)
                         .where(BuzonCorreo.activo.is_(True), Emisor.activo.is_(True))).all()
        resultado = {}
        for buzon_id in ids:
            b = db.get(BuzonCorreo, buzon_id)
            resultado[str(buzon_id)] = buzon.revisar_seguro(db, b)
            if resultado[str(buzon_id)].get("importados"):
                logger.info("Buzón %s: %s", buzon_id, resultado[str(buzon_id)])
        return resultado
    finally:
        db.close()


@celery_app.task
def emitir_recurrentes():
    """Emite las facturas recurrentes que tocan hoy y las encola para Hacienda."""
    db = SessionLocal()
    try:
        nuevos = recurrentes.emitir_pendientes(db)
    finally:
        db.close()
    for factura_id in nuevos:
        _encolar(enviar_documento, "factura", factura_id)
    logger.info("Facturas recurrentes emitidas: %s", len(nuevos))
    return {"emitidas": len(nuevos)}


def texto_recordatorio(emisor, fila: dict) -> tuple[str, str]:
    empresa = emisor.nombre_comercial or emisor.nombre
    asunto = f"Recordatorio de pago: factura {fila['consecutivo']} - {empresa}"
    cuerpo = (
        f"Estimado(a) {fila['cliente'] or 'cliente'}:\n\n"
        f"Le recordamos que la factura {fila['consecutivo']} del {fila['fecha']} venció el {fila['vence']} "
        f"({fila['dias_vencida']} día(s) de atraso).\n\n"
        f"Saldo pendiente: {fila['moneda']} {float(fila['saldo']):,.2f}\n\n"
        f"Si ya realizó el pago, por favor ignore este mensaje o responda con el comprobante para aplicarlo.\n\n"
        f"Muchas gracias,\n{empresa}\n{emisor.correo}" + (f" · Tel. {emisor.telefono}" if emisor.telefono else "")
    )
    return asunto, cuerpo


@celery_app.task
def recordar_cobros():
    """Correo a los clientes con facturas vencidas, a los 1, 8, 15, 30 y 60 días de atraso (una vez cada uno)."""
    if not settings.smtp_configurado:
        return {"status": "sin SMTP"}
    db = SessionLocal()
    enviados = 0
    try:
        for emisor in db.scalars(select(Emisor).where(Emisor.activo.is_(True), Emisor.recordar_cobros.is_(True))):
            for fila in cobros.cartera(db, emisor.id)["facturas"]:
                if fila["dias_vencida"] not in cobros.DIAS_RECORDATORIO or not fila["correo"]:
                    continue
                detalle = f"{fila['dias_vencida']} días"
                ya = db.scalar(select(func.count()).select_from(FacturaEvento).where(
                    FacturaEvento.factura_id == fila["factura_id"], FacturaEvento.evento == "RECORDATORIO_COBRO",
                    FacturaEvento.detalle == detalle))
                if ya:
                    continue
                asunto, cuerpo = texto_recordatorio(emisor, fila)
                msg = correo.mensaje_simple(fila["correo"], asunto, cuerpo)
                msg.replace_header("From", correo.remitente(emisor))
                msg["Reply-To"] = emisor.correo
                try:
                    correo.enviar(msg)
                except correo.CorreoError:
                    logger.warning("No se pudo enviar el recordatorio de %s", fila["consecutivo"])
                    continue
                db.add(FacturaEvento(factura_id=fila["factura_id"], evento="RECORDATORIO_COBRO", detalle=detalle))
                db.commit()
                enviados += 1
    finally:
        db.close()
    logger.info("Recordatorios de cobro enviados: %s", enviados)
    return {"enviados": enviados}


def _avisar_mensualidad(db, cobro, asunto: str, intro: str) -> bool:
    destino = mensualidades.correo_cliente(db, cobro)
    if not destino or not settings.smtp_configurado:
        return False
    a = administracion.ajustes(db)
    lineas = "\n".join(f"  • {x['concepto']}: {cobro.moneda} {float(x['monto']):,.2f}" for x in cobro.lineas)
    cuerpo = (f"{intro}\n\n{lineas}\n\nTotal: {cobro.moneda} {float(cobro.total):,.2f}\n"
              f"Vence: {cobro.vence:%d/%m/%Y}\n\n"
              + (f"Formas de pago:\n{a.instrucciones_pago.strip()}\n\n" if a.instrucciones_pago else "")
              + "Al pagar, repórtelo en el panel: Mis servicios → Facturas (número del comprobante).")
    msg = correo.mensaje_simple(destino, asunto, cuerpo)
    if a.correo_avisos:
        msg["Reply-To"] = a.correo_avisos
    try:
        correo.enviar(msg)
        return True
    except correo.CorreoError:
        return False


@celery_app.task
def facturar_mensualidades():
    """Día 1: factura de los servicios del mes anterior a cada cliente (proporcional a los días)."""
    from datetime import date as _date
    hoy = mensualidades.hoy()
    anterior = (hoy.replace(day=1) - timedelta(days=1)).replace(day=1)
    db = SessionLocal()
    try:
        creados = mensualidades.generar(db, _date(anterior.year, anterior.month, 1))
        for cobro in creados:
            factura = mensualidades.emitir_comprobante(db, cobro)
            if factura is not None:
                _encolar(enviar_documento, "factura", str(factura.id))
            _avisar_mensualidad(db, cobro, f"Factura de sus servicios de {cobro.periodo:%m/%Y}",
                                f"Le enviamos el detalle de sus servicios mensuales de {cobro.periodo:%m/%Y}. "
                                "La factura electrónica le llega en un correo aparte.")
    finally:
        db.close()
    logger.info("Facturas mensuales creadas: %s", len(creados))
    return {"creadas": len(creados)}


@celery_app.task
def recordar_mensualidades():
    """3 días antes del vencimiento, un recordatorio; el día después, el aviso de suspensión."""
    from api.models.database import CobroMensual
    hoy = mensualidades.hoy()
    db = SessionLocal()
    enviados = 0
    try:
        for cobro in db.scalars(select(CobroMensual).where(CobroMensual.estado == "PENDIENTE")):
            if cobro.vence - timedelta(days=3) == hoy:
                enviados += _avisar_mensualidad(db, cobro, f"Recordatorio: su factura de {cobro.periodo:%m/%Y} vence pronto",
                                                "Le recordamos que su factura de servicios mensuales vence en 3 días.")
            elif cobro.vence + timedelta(days=1) == hoy:
                enviados += _avisar_mensualidad(db, cobro, f"Servicios suspendidos: factura de {cobro.periodo:%m/%Y} vencida",
                                                "Su factura venció y los servicios mensuales (sistema en línea, contabilidad o "
                                                "cuenta de contador) quedaron suspendidos. Sus documentos ya pagados siguen "
                                                "disponibles para facturar por API. Al pagar y reportarlo se reactivan.")
    finally:
        db.close()
    return {"enviados": enviados}
