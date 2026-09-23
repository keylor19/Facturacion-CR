"""
Saldo de documentos por empresa (venta por consumo).

- Cada documento firmado y enviado a Hacienda (comprobantes, recibos de pago
  y mensajes receptor) descuenta 1 documento.
- El descuento ocurre en la MISMA transacción que crea el documento: si la
  emisión falla, no se cobra. La referencia (clave) es única: los reintentos
  y reenvíos nunca cobran dos veces. Los rechazos de Hacienda no se devuelven.
- Se consume primero el paquete que vence antes; los vencidos o anulados no cuentan.
- `acreditar` es el único punto de entrada para sumar saldo: lo usa el
  administrador (pago manual) y lo usará una pasarela de pago en el futuro.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.models.database import Consumo, DocumentoRecibido, Emisor, Factura, Paquete, Plan, utcnow
from config.settings import get_settings

logger = logging.getLogger(__name__)


class SaldoAgotadoError(Exception):
    pass


def control_activo() -> bool:
    return get_settings().CONTROL_SALDO


def _vigentes(emisor_id: str):
    ahora = utcnow()
    return (
        Paquete.emisor_id == emisor_id,
        Paquete.anulado.is_(False),
        Paquete.usados < Paquete.documentos,
        or_(Paquete.vence.is_(None), Paquete.vence > ahora),
    )


def disponible(db: Session, emisor_id: str) -> int:
    total = db.scalar(select(func.coalesce(func.sum(Paquete.documentos - Paquete.usados), 0))
                      .where(*_vigentes(emisor_id)))
    return int(total or 0)


def disponibles_por_emisor(db: Session, emisor_ids: list[str]) -> dict[str, int]:
    if not emisor_ids:
        return {}
    ahora = utcnow()
    filas = db.execute(
        select(Paquete.emisor_id, func.sum(Paquete.documentos - Paquete.usados))
        .where(Paquete.emisor_id.in_(emisor_ids), Paquete.anulado.is_(False),
               Paquete.usados < Paquete.documentos, or_(Paquete.vence.is_(None), Paquete.vence > ahora))
        .group_by(Paquete.emisor_id)
    ).all()
    resultado = {e: 0 for e in emisor_ids}
    resultado.update({e: int(n) for e, n in filas})
    return resultado


def verificar(db: Session, emisor: Emisor) -> None:
    """Chequeo rápido (sin bloqueo) antes de hacer el trabajo de firma."""
    if control_activo() and disponible(db, emisor.id) <= 0:
        raise SaldoAgotadoError(
            "Saldo de documentos agotado. Adquiera un paquete de documentos para seguir emitiendo."
        )


def consumir(
    db: Session, emisor: Emisor, referencia: str, tipo_documento: str,
    factura: Factura | None = None, recibido: DocumentoRecibido | None = None,
) -> int | None:
    """
    Descuenta 1 documento. Debe llamarse dentro de la transacción que crea el
    documento (antes del commit). Devuelve el saldo restante o None si el
    control de saldo está desactivado.
    """
    if not control_activo():
        return None

    # Se bloquean TODOS los paquetes vigentes de la empresa: dos emisiones
    # simultáneas nunca pueden usar el mismo crédito.
    paquetes = db.scalars(
        select(Paquete).where(*_vigentes(emisor.id))
        .order_by(Paquete.vence.asc().nulls_last(), Paquete.created_at.asc())
        .with_for_update()
    ).all()
    paquete = next((p for p in paquetes if p.disponibles > 0), None)
    if paquete is None:
        raise SaldoAgotadoError(
            "Saldo de documentos agotado. Adquiera un paquete de documentos para seguir emitiendo."
        )

    paquete.usados += 1
    db.add(Consumo(
        emisor_id=emisor.id, paquete_id=paquete.id, referencia=referencia, tipo_documento=tipo_documento,
        factura=factura, documento_recibido=recibido,
    ))
    db.flush()
    return sum(p.disponibles for p in paquetes)


def despues_de_consumir(emisor: Emisor, restante: int | None) -> None:
    """Avisa (webhook + correo) al llegar al umbral de alerta o a cero. Llamar después del commit."""
    if restante is None:
        return
    umbral = get_settings().SALDO_ALERTA_DOCUMENTOS
    evento = "saldo.agotado" if restante == 0 else "saldo.bajo" if restante == umbral else None
    if evento:
        from workers.tasks import notificar_saldo  # import diferido (evita ciclo)
        try:
            notificar_saldo.delay(str(emisor.id), evento, {"disponible": restante})
        except Exception:
            logger.exception("No se pudo encolar el aviso de saldo de %s", emisor.id)


def acreditar(
    db: Session, emisor: Emisor, *, plan: Plan | None = None, documentos: int | None = None,
    precio: Decimal | None = None, moneda: str | None = None, dias_vigencia: int | None = None,
    nombre: str | None = None, referencia_pago: str | None = None, notas: str | None = None,
    creado_por: str | None = None,
) -> Paquete:
    """Suma un paquete al saldo de la empresa (compra, cortesía o pago en línea)."""
    if plan is not None:
        documentos = documentos or plan.documentos
        precio = plan.precio if precio is None else precio
        moneda = moneda or plan.moneda
        dias_vigencia = plan.dias_vigencia if dias_vigencia is None else dias_vigencia
        nombre = nombre or plan.nombre
    if not documentos or documentos <= 0:
        raise ValueError("La cantidad de documentos debe ser mayor a cero")

    paquete = Paquete(
        emisor_id=emisor.id,
        plan_id=plan.id if plan else None,
        nombre=(nombre or f"{documentos} documentos")[:80],
        documentos=documentos,
        precio=precio or Decimal("0"),
        moneda=moneda or "CRC",
        vence=utcnow() + timedelta(days=dias_vigencia) if dias_vigencia else None,
        referencia_pago=referencia_pago,
        notas=notas,
        creado_por=creado_por,
    )
    db.add(paquete)
    db.commit()
    return paquete


def resumen(db: Session, emisor: Emisor) -> dict:
    ahora = utcnow()
    alerta_venc = ahora + timedelta(days=get_settings().DIAS_ALERTA_VENCIMIENTO_PAQUETE)
    paquetes = db.scalars(select(Paquete).where(Paquete.emisor_id == emisor.id)
                          .order_by(Paquete.created_at.desc())).all()
    inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usados_mes = db.scalar(select(func.count()).select_from(Consumo).where(
        Consumo.emisor_id == emisor.id, Consumo.created_at >= inicio_mes)) or 0
    disp = disponible(db, emisor.id)
    return {
        "control_activo": control_activo(),
        "disponible": disp,
        "alerta": disp <= get_settings().SALDO_ALERTA_DOCUMENTOS,
        "usados_este_mes": usados_mes,
        "por_vencer": sum(p.disponibles for p in paquetes
                          if not p.anulado and p.vence and ahora < p.vence <= alerta_venc),
        "paquetes": [paquete_a_dict(p) for p in paquetes],
    }


def paquete_a_dict(p: Paquete) -> dict:
    ahora = utcnow()
    if p.anulado:
        estado = "ANULADO"
    elif p.vence and p.vence <= ahora:
        estado = "VENCIDO"
    elif p.disponibles <= 0:
        estado = "AGOTADO"
    else:
        estado = "VIGENTE"
    return {
        "id": str(p.id), "nombre": p.nombre, "documentos": p.documentos, "usados": p.usados,
        "disponibles": max(p.disponibles, 0) if estado == "VIGENTE" else 0,
        "precio": p.precio, "moneda": p.moneda, "referencia_pago": p.referencia_pago, "notas": p.notas,
        "vence": p.vence, "estado": estado, "creado_por": p.creado_por, "fecha": p.created_at,
    }
