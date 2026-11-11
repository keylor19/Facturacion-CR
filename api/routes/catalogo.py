"""
Facturación en línea: catálogo de clientes y productos, inventario y logo de
la empresa. Disponible para el panel y para los sistemas integrados por API.
"""
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models.database import Categoria, Cliente, Descuento, Emisor, MovimientoInventario, Producto, get_db
from api.models.schemas import (
    CategoriaRequest, ClienteDatos, ClienteResponse, DescuentoRequest, MovimientoRequest, ProductoActualizar,
    ProductoCrear, ProductoResponse,
)
from api.security import Principal, autenticar, emisor_actual, emisor_facturacion_web, permiso
from api.services import auditoria, inventario
from api.services.fechas import ahora_cr, zona_cr
from api.services.reportes import _csv

router = APIRouter(prefix="/api/v1", tags=["facturación en línea: catálogos e inventario"])

MAX_BYTES_LOGO = 300_000


def _buscar_texto(columnas, q: str):
    q = q.strip().lower()
    return or_(*[func.lower(c).contains(q, autoescape=True) for c in columnas])


def _quien(db: Session, principal: Principal) -> str:
    return auditoria.nombre_actor(db, principal)


# --- Clientes -------------------------------------------------------------------

def _cliente_respuesta(c: Cliente) -> ClienteResponse:
    return ClienteResponse(
        id=str(c.id), activo=c.activo, tipo_identificacion=c.tipo_identificacion,
        numero_identificacion=c.numero_identificacion, nombre=c.nombre, nombre_comercial=c.nombre_comercial,
        correo=c.correo, telefono=c.telefono, codigo_actividad=c.codigo_actividad, provincia=c.provincia,
        canton=c.canton, distrito=c.distrito, otras_senas=c.otras_senas, notas=c.notas,
    )


def _cliente(db: Session, emisor: Emisor, cliente_id: UUID) -> Cliente:
    c = db.scalar(select(Cliente).where(Cliente.id == str(cliente_id), Cliente.emisor_id == emisor.id))
    if c is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return c


@router.get("/catalogo/clientes", response_model=list[ClienteResponse])
def listar_clientes(
    q: str | None = Query(default=None, max_length=100, description="Nombre o identificación"),
    incluir_inactivos: bool = False, limite: int = Query(default=200, ge=1, le=1000),
    emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db),
):
    query = select(Cliente).where(Cliente.emisor_id == emisor.id).order_by(Cliente.nombre).limit(limite)
    if not incluir_inactivos:
        query = query.where(Cliente.activo.is_(True))
    if q:
        query = query.where(_buscar_texto([Cliente.nombre, Cliente.numero_identificacion, Cliente.nombre_comercial], q))
    return [_cliente_respuesta(c) for c in db.scalars(query)]


@router.get("/catalogo/clientes/{cliente_id}", response_model=ClienteResponse)
def obtener_cliente(cliente_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    return _cliente_respuesta(_cliente(db, emisor, cliente_id))


@router.post("/catalogo/clientes", response_model=ClienteResponse, status_code=201, dependencies=[Depends(permiso("clientes"))])
def crear_cliente(payload: ClienteDatos, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    existente = db.scalar(select(Cliente).where(
        Cliente.emisor_id == emisor.id, Cliente.numero_identificacion == payload.numero_identificacion))
    if existente is not None and existente.activo:
        raise HTTPException(status_code=409, detail=f"Ya existe el cliente {existente.nombre} con esa identificación")
    if existente is not None:
        # Se había eliminado: se reactiva con los datos nuevos
        for campo, valor in payload.model_dump().items():
            setattr(existente, campo, valor)
        existente.activo = True
        c = existente
    else:
        c = Cliente(emisor_id=emisor.id, activo=True, **payload.model_dump())
        db.add(c)
    db.commit()
    return _cliente_respuesta(c)


@router.put("/catalogo/clientes/{cliente_id}", response_model=ClienteResponse, dependencies=[Depends(permiso("clientes"))])
def actualizar_cliente(cliente_id: UUID, payload: ClienteDatos,
                       emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    c = _cliente(db, emisor, cliente_id)
    for campo, valor in payload.model_dump().items():
        setattr(c, campo, valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe otro cliente con esa identificación")
    return _cliente_respuesta(c)


@router.delete("/catalogo/clientes/{cliente_id}", status_code=204, dependencies=[Depends(permiso("clientes"))])
def eliminar_cliente(cliente_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """Lo quita del catálogo (sus facturas no se afectan)."""
    _cliente(db, emisor, cliente_id).activo = False
    db.commit()


# --- Productos ------------------------------------------------------------------

def _producto(db: Session, emisor: Emisor, producto_id: UUID) -> Producto:
    p = db.scalar(select(Producto).where(Producto.id == str(producto_id), Producto.emisor_id == emisor.id))
    if p is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return p


@router.get("/catalogo/productos", response_model=list[ProductoResponse])
def listar_productos(
    q: str | None = Query(default=None, max_length=100, description="Código, descripción o CABYS"),
    incluir_inactivos: bool = False,
    solo_inventario: bool = Query(default=False, description="Solo los que controlan inventario"),
    bajo_minimo: bool = Query(default=False, description="Solo los que están en o por debajo del mínimo"),
    limite: int = Query(default=500, ge=1, le=2000),
    categoria_id: UUID | None = Query(default=None),
    solo_combos: bool = False,
    emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db),
):
    query = select(Producto).where(Producto.emisor_id == emisor.id).order_by(Producto.descripcion).limit(limite)
    if not incluir_inactivos:
        query = query.where(Producto.activo.is_(True))
    if categoria_id:
        query = query.where(Producto.categoria_id == str(categoria_id))
    if solo_combos:
        query = query.where(Producto.es_combo.is_(True))
    if solo_inventario or bajo_minimo:
        query = query.where(Producto.controla_inventario.is_(True))
    if bajo_minimo:
        query = query.where(Producto.existencia_minima.is_not(None), Producto.existencia <= Producto.existencia_minima)
    if q:
        query = query.where(_buscar_texto([Producto.codigo, Producto.descripcion, Producto.codigo_cabys], q))
    return [inventario.a_respuesta(p) for p in db.scalars(query)]


@router.get("/catalogo/productos/{producto_id}", response_model=ProductoResponse)
def obtener_producto(producto_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    return inventario.a_respuesta(_producto(db, emisor, producto_id))


@router.post("/catalogo/productos", response_model=ProductoResponse, status_code=201, dependencies=[Depends(permiso("catalogo"))])
def crear_producto(payload: ProductoCrear, principal: Principal = Depends(autenticar),
                   emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    try:
        p = inventario.crear_producto(db, emisor.id, payload, _quien(db, principal))
    except inventario.InventarioError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un producto con ese código")
    return inventario.a_respuesta(p)


@router.patch("/catalogo/productos/{producto_id}", response_model=ProductoResponse, dependencies=[Depends(permiso("catalogo"))])
def actualizar_producto(producto_id: UUID, payload: ProductoActualizar,
                        emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """La existencia no se edita aquí: use /inventario/movimientos (entrada, salida o ajuste)."""
    p = _producto(db, emisor, producto_id)
    for campo, valor in payload.model_dump(exclude_unset=True, exclude={"categoria_id", "componentes"}).items():
        if valor is None and campo not in ("costo_unitario", "existencia_minima"):
            continue
        setattr(p, campo, valor)
    try:
        if "categoria_id" in payload.model_fields_set:
            inventario.fijar_categoria(db, emisor.id, p, payload.categoria_id)
        if payload.componentes is not None:
            if payload.componentes and p.controla_inventario and p.existencia:
                raise inventario.InventarioError("El producto tiene existencia: ajústela a cero antes de convertirlo en combo")
            inventario.fijar_componentes(db, emisor.id, p, payload.componentes)
        if p.es_combo:
            p.controla_inventario = False
    except inventario.InventarioError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un producto con ese código")
    return inventario.a_respuesta(p)


@router.delete("/catalogo/productos/{producto_id}", status_code=204, dependencies=[Depends(permiso("catalogo"))])
def eliminar_producto(producto_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """Lo quita del catálogo; su historial de inventario se conserva."""
    _producto(db, emisor, producto_id).activo = False
    db.commit()


# --- Categorías -----------------------------------------------------------------

def _categoria(db: Session, emisor: Emisor, categoria_id: UUID) -> Categoria:
    c = db.get(Categoria, str(categoria_id))
    if c is None or c.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    return c


def _categoria_respuesta(db: Session, c: Categoria) -> dict:
    productos = db.scalar(select(func.count()).where(Producto.categoria_id == c.id, Producto.activo.is_(True)))
    return {"id": str(c.id), "nombre": c.nombre, "productos": productos}


@router.get("/catalogo/categorias")
def listar_categorias(emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    lista = db.scalars(select(Categoria).where(Categoria.emisor_id == emisor.id).order_by(Categoria.nombre))
    return [_categoria_respuesta(db, c) for c in lista]


@router.post("/catalogo/categorias", status_code=201, dependencies=[Depends(permiso("catalogo"))])
def crear_categoria(payload: CategoriaRequest, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    c = Categoria(emisor_id=emisor.id, nombre=payload.nombre.strip())
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre")
    return _categoria_respuesta(db, c)


@router.put("/catalogo/categorias/{categoria_id}", dependencies=[Depends(permiso("catalogo"))])
def renombrar_categoria(categoria_id: UUID, payload: CategoriaRequest,
                        emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    c = _categoria(db, emisor, categoria_id)
    c.nombre = payload.nombre.strip()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una categoría con ese nombre")
    return _categoria_respuesta(db, c)


@router.delete("/catalogo/categorias/{categoria_id}", status_code=204, dependencies=[Depends(permiso("catalogo"))])
def eliminar_categoria(categoria_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """Los productos quedan sin categoría; los descuentos de la categoría se eliminan."""
    db.delete(_categoria(db, emisor, categoria_id))
    db.commit()


# --- Descuentos -----------------------------------------------------------------

def _descuento_respuesta(d: Descuento) -> dict:
    return {
        "id": str(d.id), "nombre": d.nombre, "tipo": d.tipo, "valor": d.valor, "alcance": d.alcance,
        "categoria_id": str(d.categoria_id) if d.categoria_id else None, "categoria": d.categoria.nombre if d.categoria else None,
        "producto_id": str(d.producto_id) if d.producto_id else None,
        "producto": f"{d.producto.codigo} · {d.producto.descripcion}" if d.producto else None,
        "cantidad_minima": d.cantidad_minima, "codigo_descuento": d.codigo_descuento,
        "desde": d.desde, "hasta": d.hasta, "activo": d.activo,
    }


def _validar_descuento(db: Session, emisor: Emisor, payload: DescuentoRequest) -> dict:
    """Verifica que la categoría o el producto sean de la empresa y limpia el que no aplica."""
    datos = payload.model_dump()
    if payload.alcance == "categoria":
        _categoria(db, emisor, UUID(payload.categoria_id))
    else:
        datos["categoria_id"] = None
    if payload.alcance == "producto":
        _producto(db, emisor, UUID(payload.producto_id))
    else:
        datos["producto_id"] = None
    return datos


@router.get("/catalogo/descuentos")
def listar_descuentos(vigentes: bool = Query(default=False, description="Solo activos y dentro de su vigencia hoy"),
                      emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    query = select(Descuento).where(Descuento.emisor_id == emisor.id).order_by(Descuento.nombre)
    if vigentes:
        hoy = ahora_cr().date()
        query = query.where(Descuento.activo.is_(True), or_(Descuento.desde.is_(None), Descuento.desde <= hoy),
                            or_(Descuento.hasta.is_(None), Descuento.hasta >= hoy))
    return [_descuento_respuesta(d) for d in db.scalars(query)]


@router.post("/catalogo/descuentos", status_code=201, dependencies=[Depends(permiso("catalogo"))])
def crear_descuento(payload: DescuentoRequest, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    d = Descuento(emisor_id=emisor.id, **_validar_descuento(db, emisor, payload))
    db.add(d)
    db.commit()
    return _descuento_respuesta(d)


@router.put("/catalogo/descuentos/{descuento_id}", dependencies=[Depends(permiso("catalogo"))])
def actualizar_descuento(descuento_id: UUID, payload: DescuentoRequest,
                         emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    d = db.get(Descuento, str(descuento_id))
    if d is None or d.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    for campo, valor in _validar_descuento(db, emisor, payload).items():
        setattr(d, campo, valor)
    db.commit()
    return _descuento_respuesta(d)


@router.delete("/catalogo/descuentos/{descuento_id}", status_code=204, dependencies=[Depends(permiso("catalogo"))])
def eliminar_descuento(descuento_id: UUID, emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    d = db.get(Descuento, str(descuento_id))
    if d is None or d.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    db.delete(d)
    db.commit()


# --- Inventario -----------------------------------------------------------------

@router.get("/inventario/movimientos")
def listar_movimientos(
    producto_id: UUID | None = None,
    desde: date | None = None, hasta: date | None = None,
    limite: int = Query(default=300, ge=1, le=2000),
    emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db),
):
    """Kárdex: movimientos más recientes primero."""
    query = (select(MovimientoInventario).where(MovimientoInventario.emisor_id == emisor.id)
             .order_by(MovimientoInventario.fecha.desc()).limit(limite))
    if producto_id:
        query = query.where(MovimientoInventario.producto_id == str(producto_id))
    if desde:
        query = query.where(MovimientoInventario.fecha >= datetime.combine(desde, time.min, tzinfo=zona_cr()))
    if hasta:
        query = query.where(MovimientoInventario.fecha <= datetime.combine(hasta, time.max, tzinfo=zona_cr()))
    return [inventario.movimiento_a_dict(m) for m in db.scalars(query)]


@router.post("/inventario/movimientos", status_code=201, dependencies=[Depends(permiso("catalogo"))])
def registrar_movimiento(payload: MovimientoRequest, principal: Principal = Depends(autenticar),
                         emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    """Entrada de mercadería, salida (merma, uso interno) o ajuste por conteo físico."""
    try:
        mov = inventario.registrar_movimiento(db, emisor.id, payload, _quien(db, principal))
    except inventario.InventarioError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return inventario.movimiento_a_dict(mov)


@router.get("/inventario/resumen")
def resumen_inventario(emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    productos = list(db.scalars(select(Producto).where(
        Producto.emisor_id == emisor.id, Producto.activo.is_(True), Producto.controla_inventario.is_(True))))
    valor = sum(((p.existencia or 0) * (p.costo_unitario or 0) for p in productos), Decimal("0"))
    bajos = [p for p in productos if inventario.bajo_minimo(p)]
    return {
        "productos_con_inventario": len(productos),
        "unidades": str(sum((p.existencia or 0 for p in productos), Decimal("0"))),
        "valor_al_costo": str(round(valor, 2)),
        "bajo_minimo": [inventario.a_respuesta(p) for p in bajos],
    }


@router.get("/inventario/existencias.csv")
def existencias_csv(emisor: Emisor = Depends(emisor_facturacion_web), db: Session = Depends(get_db)):
    productos = db.scalars(select(Producto).where(
        Producto.emisor_id == emisor.id, Producto.activo.is_(True), Producto.controla_inventario.is_(True),
    ).order_by(Producto.descripcion))
    filas = [[p.codigo, p.descripcion, p.codigo_cabys, p.unidad_medida, p.existencia, p.existencia_minima or "",
              p.costo_unitario or "", round((p.existencia or 0) * (p.costo_unitario or 0), 2)] for p in productos]
    contenido = _csv(["Código", "Descripción", "CABYS", "Unidad", "Existencia", "Mínimo", "Costo unitario",
                      "Valor al costo"], filas)
    return Response(contenido, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="existencias.csv"'})


# --- Logo de la empresa (sale en el PDF) -----------------------------------------

def _tipo_imagen(datos: bytes) -> str | None:
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if datos.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


@router.put("/empresa/logo", status_code=204, dependencies=[Depends(permiso("configuracion"))])
def cargar_logo(request: Request, archivo: UploadFile = File(..., description="PNG o JPEG, máximo 300 KB"),
                principal: Principal = Depends(autenticar),
                emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    datos = archivo.file.read(MAX_BYTES_LOGO + 1)
    if len(datos) > MAX_BYTES_LOGO:
        raise HTTPException(status_code=413, detail="El logo debe pesar menos de 300 KB")
    tipo = _tipo_imagen(datos)
    if tipo is None:
        raise HTTPException(status_code=422, detail="El logo debe ser una imagen PNG o JPEG")
    try:
        from io import BytesIO
        from reportlab.lib.utils import ImageReader
        ancho, alto = ImageReader(BytesIO(datos)).getSize()
    except Exception:
        raise HTTPException(status_code=422, detail="No se pudo leer la imagen")
    if not (0 < ancho <= 4000 and 0 < alto <= 4000):
        raise HTTPException(status_code=422, detail="La imagen es demasiado grande (máximo 4000 × 4000 píxeles)")
    emisor.logo, emisor.logo_tipo = datos, tipo
    db.commit()
    auditoria.registrar(db, "emisor.logo", principal=principal, request=request, emisor_id=emisor.id)


@router.get("/empresa/logo")
def obtener_logo(emisor: Emisor = Depends(emisor_actual)):
    if emisor.logo is None:
        raise HTTPException(status_code=404, detail="La empresa no tiene logo")
    return Response(bytes(emisor.logo), media_type=emisor.logo_tipo or "image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/empresa/logo", status_code=204, dependencies=[Depends(permiso("configuracion"))])
def eliminar_logo(request: Request, principal: Principal = Depends(autenticar),
                  emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    emisor.logo, emisor.logo_tipo = None, None
    db.commit()
    auditoria.registrar(db, "emisor.logo", principal=principal, request=request, emisor_id=emisor.id,
                        detalle="eliminado")
