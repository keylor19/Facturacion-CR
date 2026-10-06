"""
Catálogo de productos e inventario (kárdex).

Movimientos automáticos al emitir (solo líneas con producto_id de un producto
que controla inventario):
- Factura (01), tiquete (04) y exportación (09): salida por venta.
- Nota de crédito (03) que anula (01) o devuelve (06): entrada por devolución.
- Factura de compra (08): entrada por compra.
Si Hacienda rechaza el comprobante, se registra un movimiento de reverso.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import Factura, MovimientoInventario, Producto
from api.models.schemas import FacturaRequest, MovimientoRequest, ProductoResponse, TIPOS_COMPROBANTE

# tipo de comprobante -> (signo, tipo de movimiento)
EFECTO_DOCUMENTO = {"01": (-1, "venta"), "04": (-1, "venta"), "09": (-1, "venta"),
                    "03": (1, "devolucion"), "08": (1, "compra")}
# Códigos de referencia de una nota de crédito que devuelven mercadería
REFERENCIAS_DEVOLUCION = {"01", "06"}
MOVIMIENTOS_DE_DOCUMENTO = ("venta", "devolucion", "compra")


class InventarioError(Exception):
    pass


def _n(valor: Decimal) -> str:
    """5.000 -> '5', 2.500 -> '2.5'"""
    return f"{Decimal(valor).normalize():f}"


def bajo_minimo(p: Producto) -> bool:
    return bool(p.controla_inventario and p.existencia_minima is not None and p.existencia <= p.existencia_minima)


def a_respuesta(p: Producto) -> ProductoResponse:
    return ProductoResponse(
        id=str(p.id), codigo=p.codigo, codigo_cabys=p.codigo_cabys, descripcion=p.descripcion,
        unidad_medida=p.unidad_medida, es_servicio=p.es_servicio, precio_unitario=p.precio_unitario,
        codigo_tarifa_iva=p.codigo_tarifa_iva, costo_unitario=p.costo_unitario,
        controla_inventario=p.controla_inventario, existencia=p.existencia or Decimal("0"),
        existencia_minima=p.existencia_minima, bajo_minimo=bajo_minimo(p), activo=p.activo,
    )


def _bloquear(db: Session, emisor_id: str, ids) -> dict[str, Producto]:
    """Bloquea las filas (en orden fijo para evitar interbloqueos) durante la transacción."""
    filas = db.scalars(select(Producto).where(Producto.emisor_id == emisor_id, Producto.id.in_(list(ids)))
                       .order_by(Producto.id).with_for_update())
    return {p.id: p for p in filas}


def _mover(db: Session, producto: Producto, cantidad: Decimal, tipo: str, *, factura: Factura | None = None,
           nota: str | None = None, usuario: str | None = None, costo: Decimal | None = None) -> MovimientoInventario:
    producto.existencia = (producto.existencia or Decimal("0")) + cantidad
    mov = MovimientoInventario(
        emisor_id=producto.emisor_id, producto=producto, tipo=tipo, cantidad=cantidad,
        existencia_resultante=producto.existencia, costo_unitario=costo,
        nota=(nota or "")[:300] or None, usuario=(usuario or "")[:200] or None,
    )
    if factura is not None:
        mov.factura = factura
    db.add(mov)
    return mov


def aplicar_documento(db: Session, emisor_id: str, factura: Factura, datos: FacturaRequest) -> None:
    """Registra la salida/entrada de inventario del comprobante (misma transacción que la emisión)."""
    ids = {ln.producto_id for ln in datos.productos if ln.producto_id}
    if not ids:
        return
    productos = _bloquear(db, emisor_id, ids)
    if len(productos) != len(ids):
        raise InventarioError("Hay líneas con un producto_id que no existe en el catálogo de esta empresa")

    efecto = EFECTO_DOCUMENTO.get(datos.tipo_documento)
    if efecto is None:
        return
    if datos.tipo_documento == "03" and not any(r.codigo in REFERENCIAS_DEVOLUCION for r in datos.referencias):
        return   # nota de crédito por descuento o corrección: no mueve mercadería
    signo, tipo = efecto

    totales: dict[str, Decimal] = defaultdict(Decimal)
    for ln in datos.productos:
        if ln.producto_id:
            totales[ln.producto_id] += ln.cantidad

    if signo < 0:
        faltantes = [
            f"{p.codigo} {p.descripcion} (hay {_n(p.existencia)}, se requieren {_n(c)})"
            for pid, c in totales.items()
            if (p := productos[pid]).controla_inventario and p.existencia < c
        ]
        if faltantes:
            raise InventarioError("Existencia insuficiente: " + "; ".join(faltantes)
                                  + ". Registre la entrada de mercadería o un ajuste de inventario.")

    nota = f"{TIPOS_COMPROBANTE.get(datos.tipo_documento, 'Comprobante')} {factura.numero_consecutivo}"
    for pid, cantidad in totales.items():
        p = productos[pid]
        if p.controla_inventario:
            _mover(db, p, signo * cantidad, tipo, factura=factura, nota=nota, costo=p.costo_unitario)


def revertir_documento(db: Session, factura: Factura) -> int:
    """Hacienda rechazó el comprobante: deshace sus movimientos. Devuelve cuántos revirtió."""
    movimientos = list(db.scalars(select(MovimientoInventario).where(MovimientoInventario.factura_id == factura.id)))
    if not movimientos or any(m.tipo == "reverso" for m in movimientos):
        return 0
    aplicables = [m for m in movimientos if m.tipo in MOVIMIENTOS_DE_DOCUMENTO]
    productos = _bloquear(db, factura.emisor_id, {m.producto_id for m in aplicables})
    for m in aplicables:
        _mover(db, productos[m.producto_id], -m.cantidad, "reverso", factura=factura,
               nota=f"Rechazado por Hacienda: {factura.numero_consecutivo}", costo=m.costo_unitario)
    return len(aplicables)


def crear_producto(db: Session, emisor_id: str, datos, usuario: str | None) -> Producto:
    campos = datos.model_dump(exclude={"existencia_inicial", "activo"}, exclude_none=True)
    p = Producto(emisor_id=emisor_id, existencia=Decimal("0"), activo=True, **campos)
    if p.es_servicio is None:
        p.es_servicio = False
    if p.controla_inventario is None:
        p.controla_inventario = False
    db.add(p)
    if p.controla_inventario and datos.existencia_inicial > 0:
        _mover(db, p, datos.existencia_inicial, "entrada", nota="Existencia inicial", usuario=usuario,
               costo=p.costo_unitario)
    return p


def registrar_movimiento(db: Session, emisor_id: str, req: MovimientoRequest, usuario: str | None) -> MovimientoInventario:
    p = _bloquear(db, emisor_id, {req.producto_id}).get(req.producto_id)
    if p is None:
        raise InventarioError("Producto no encontrado")
    if not p.controla_inventario:
        raise InventarioError("Este producto no controla inventario; actívelo en el catálogo")

    existencia = p.existencia or Decimal("0")
    if req.tipo == "entrada":
        cantidad = req.cantidad
        if req.costo_unitario is not None:
            # Costo promedio ponderado
            anterior = p.costo_unitario if p.costo_unitario is not None else req.costo_unitario
            base = max(existencia, Decimal("0"))
            p.costo_unitario = ((base * anterior + cantidad * req.costo_unitario) / (base + cantidad)).quantize(Decimal("0.00001"))
    elif req.tipo == "salida":
        if req.cantidad > existencia:
            raise InventarioError(f"Existencia insuficiente: hay {_n(existencia)}")
        cantidad = -req.cantidad
    else:   # ajuste: la cantidad es la existencia contada
        cantidad = req.cantidad - existencia
        if cantidad == 0:
            raise InventarioError("La existencia contada es igual a la registrada; no hay nada que ajustar")
    return _mover(db, p, cantidad, req.tipo, nota=req.nota, usuario=usuario,
                  costo=req.costo_unitario if req.tipo == "entrada" else p.costo_unitario)


def movimiento_a_dict(m: MovimientoInventario) -> dict:
    return {
        "id": str(m.id), "fecha": m.fecha, "producto_id": str(m.producto_id),
        "producto_codigo": m.producto.codigo if m.producto else None,
        "producto_descripcion": m.producto.descripcion if m.producto else None,
        # Decimales como texto (igual que en productos): sin errores de redondeo de float
        "tipo": m.tipo, "cantidad": str(m.cantidad), "existencia_resultante": str(m.existencia_resultante),
        "costo_unitario": str(m.costo_unitario) if m.costo_unitario is not None else None, "factura_id": str(m.factura_id) if m.factura_id else None,
        "nota": m.nota, "usuario": m.usuario,
    }
