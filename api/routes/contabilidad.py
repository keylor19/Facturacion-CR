"""
Módulo de contabilidad: solo para usuarios contadores (ni las empresas cliente ni los
administradores del servicio entran aquí). Trabaja sobre la empresa elegida (X-Emisor-Id)
entre las que el contador tiene a cargo.
"""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.database import (
    Asiento, AsientoLinea, CuentaContable, Emisor, PeriodoCerrado, Usuario, UsuarioEmpresa, get_db,
)
from api.models.schemas import PATRON_ACTIVIDAD, TipoIdentificacion
from api.security import Principal, contabilidad_habilitada, emisor_actual, permiso
from api.services import auditoria, contabilidad as conta, correo, importacion_xml
from api.services.fechas import ahora_cr
from api.services.reportes import _celda_segura

router = APIRouter(prefix="/api/v1/contabilidad", tags=["contabilidad (contadores)"],
                   dependencies=[Depends(contabilidad_habilitada)])

TipoCuenta = Literal["activo", "pasivo", "patrimonio", "ingreso", "costo", "gasto"]


# --- Esquemas --------------------------------------------------------------------------------

class EmpresaPropiaRequest(BaseModel):
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str = Field(pattern=r"^\d{9,12}$")
    nombre: str = Field(min_length=2, max_length=100)
    nombre_comercial: Optional[str] = Field(default=None, max_length=80)
    codigo_actividad: str = Field(pattern=PATRON_ACTIVIDAD)
    correo: EmailStr
    telefono: Optional[str] = Field(default=None, pattern=r"^\d{8,20}$")
    provincia: str = Field(pattern=r"^[1-7]$")
    canton: str = Field(pattern=r"^\d{2}$")
    distrito: str = Field(pattern=r"^\d{2}$")
    otras_senas: str = Field(min_length=3, max_length=250)
    crear_catalogo: bool = True


class CuentaRequest(BaseModel):
    codigo: str = Field(pattern=r"^\d+(\.\d+)*$", max_length=30, description="Con puntos: 1.1.07")
    nombre: str = Field(min_length=2, max_length=150)
    tipo: TipoCuenta
    acepta_movimientos: bool = True
    activa: bool = True


class LineaRequest(BaseModel):
    cuenta_id: str
    debe: Decimal = Field(default=Decimal("0"), ge=0)
    haber: Decimal = Field(default=Decimal("0"), ge=0)
    detalle: Optional[str] = Field(default=None, max_length=200)


class AsientoRequest(BaseModel):
    fecha: date
    descripcion: str = Field(min_length=3, max_length=300)
    lineas: list[LineaRequest] = Field(min_length=2, max_length=200)


class MesRequest(BaseModel):
    anio: int = Field(ge=2018, le=2100)
    mes: int = Field(ge=1, le=12)


def _error(exc: conta.ContabilidadError):
    return HTTPException(status_code=exc.status_code, detail=exc.detalle)


def _rango(desde: Optional[date], hasta: Optional[date]) -> tuple[date, date]:
    hoy = ahora_cr().date()
    desde = desde or hoy.replace(day=1)
    hasta = hasta or hoy
    if hasta < desde:
        raise HTTPException(status_code=422, detail="La fecha final es anterior a la inicial")
    return desde, hasta


def _csv(filas: list[list], nombre: str) -> Response:
    salida = io.StringIO()
    salida.write("﻿")
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerows([_celda_segura(v) for v in fila] for fila in filas)
    return Response(salida.getvalue().encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# --- Empresas del contador ------------------------------------------------------------------------

def _solo_contador(principal: Principal) -> None:
    if not principal.es_contador:
        raise HTTPException(status_code=403, detail="Solo los usuarios contadores agregan empresas")


@router.get("/empresas")
def mis_empresas(principal: Principal = Depends(permiso("contabilidad")), db: Session = Depends(get_db)):
    """Empresas a cargo del contador (o la propia, para el dueño) y cómo va su contabilidad en el mes actual."""
    hoy = ahora_cr().date()
    inicio, fin = hoy.replace(day=1), hoy
    ids = list(principal.empresas) if principal.es_contador else [principal.emisor_id]
    filas = []
    for e in db.scalars(select(Emisor).where(Emisor.id.in_(ids)).order_by(Emisor.nombre)):
        facturas, recibidos, abonos = conta.documentos_del_mes(db, e.id, inicio, fin)
        refs = {f"factura:{x.id}" for x in facturas} | {f"recibido:{x.id}" for x in recibidos} | {f"abono:{x.id}" for x in abonos}
        hechos = set(db.scalars(select(Asiento.documento_ref).where(Asiento.emisor_id == e.id,
                                                                     Asiento.documento_ref.in_(refs)))) if refs else set()
        ultimo_cierre = db.scalar(select(func.max(PeriodoCerrado.mes)).where(PeriodoCerrado.emisor_id == e.id))
        filas.append({
            "id": e.id, "nombre": e.nombre, "identificacion": e.numero_identificacion,
            "propia": e.contador_id == principal.usuario_id, "factura_aqui": not e.solo_contabilidad,
            "tiene_catalogo": conta.tiene_catalogo(db, e.id),
            "documentos_mes": len(refs), "sin_contabilizar": len(refs - hechos),
            "ultimo_cierre": ultimo_cierre.isoformat() if ultimo_cierre else None,
        })
    return filas


@router.get("/buscar-empresa")
def buscar_empresa(cedula: str = Query(pattern=r"^\d{9,12}$"), principal: Principal = Depends(permiso("contabilidad")),
                   db: Session = Depends(get_db)):
    """
    Busca por cédula exacta una empresa ya inscrita en el sistema (no se muestra la lista de
    clientes del servicio). Si no existe, el contador puede inscribirla.
    """
    _solo_contador(principal)
    e = db.scalar(select(Emisor).where(Emisor.numero_identificacion == cedula, Emisor.activo.is_(True)))
    if e is None or (e.solo_contabilidad and e.contador_id != principal.usuario_id):
        raise HTTPException(status_code=404, detail="Esa empresa no está inscrita en el sistema: puede inscribirla usted")
    return {"id": e.id, "nombre": e.nombre, "identificacion": e.numero_identificacion,
            "ya_la_lleva": e.id in principal.empresas}


def _avisar_al_dueno(e: Emisor, contador: str, correo_contador: str) -> None:
    """La empresa se entera de quién empezó a ver su contabilidad (y puede quitarle el acceso)."""
    try:
        correo.enviar(correo.mensaje_simple(
            e.correo, f"Un contador ahora lleva la contabilidad de {e.nombre}",
            f"{contador} ({correo_contador}) empezó a llevar la contabilidad de {e.nombre} en el sistema de facturación "
            "electrónica: puede ver sus comprobantes, asientos e impuestos, pero no facturar ni cambiar nada.\n\n"
            "Si usted no lo autorizó, quítele el acceso en el panel: Configuración → Usuarios → Contadores con acceso."))
    except correo.CorreoError:
        pass


@router.post("/empresas/{emisor_id}/vincular", status_code=201)
def llevar_empresa(emisor_id: UUID, request: Request, principal: Principal = Depends(permiso("contabilidad")),
                   db: Session = Depends(get_db)):
    """El contador empieza a llevar la contabilidad de una empresa ya inscrita. Se le avisa a la empresa."""
    _solo_contador(principal)
    e = db.get(Emisor, str(emisor_id))
    if e is None or not e.activo or (e.solo_contabilidad and e.contador_id != principal.usuario_id):
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    if str(e.id) in principal.empresas:
        raise HTTPException(status_code=409, detail="Ya lleva la contabilidad de esa empresa")
    db.add(UsuarioEmpresa(usuario_id=principal.usuario_id, emisor_id=e.id, rol="contador_externo"))
    db.commit()
    contador = db.get(Usuario, principal.usuario_id)
    auditoria.registrar(db, "contabilidad.vincular", principal=principal, request=request, emisor_id=e.id,
                        detalle=f"{contador.email} lleva la contabilidad")
    _avisar_al_dueno(e, contador.nombre, contador.email)
    return {"id": e.id, "nombre": e.nombre, "identificacion": e.numero_identificacion}


@router.delete("/empresas/{emisor_id}/vincular", status_code=204)
def dejar_empresa(emisor_id: UUID, request: Request, principal: Principal = Depends(permiso("contabilidad")),
                  db: Session = Depends(get_db)):
    """El contador deja de llevar una empresa inscrita (sus asientos se conservan para el siguiente)."""
    _solo_contador(principal)
    acceso = db.get(UsuarioEmpresa, (principal.usuario_id, str(emisor_id)))
    if acceso is None:
        raise HTTPException(status_code=404, detail="No lleva esa empresa")
    db.delete(acceso)
    db.commit()
    auditoria.registrar(db, "contabilidad.desvincular", principal=principal, request=request, emisor_id=str(emisor_id))


@router.post("/empresas", status_code=201)
def agregar_empresa(payload: EmpresaPropiaRequest, request: Request, principal: Principal = Depends(permiso("contabilidad")),
                    db: Session = Depends(get_db)):
    """Inscribe una empresa que no factura en este sistema, solo para llevarle la contabilidad."""
    _solo_contador(principal)
    existente = db.scalar(select(Emisor).where(Emisor.numero_identificacion == payload.numero_identificacion))
    if existente is not None:
        raise HTTPException(status_code=409, detail="Esa empresa ya está inscrita en el sistema: búsquela con su cédula "
                                                    "en «Empresa ya inscrita» para llevarle la contabilidad")
    datos = payload.model_dump(exclude={"crear_catalogo"})
    e = Emisor(**datos, solo_contabilidad=True, contador_id=principal.usuario_id, facturacion_web=False,
               acceso_api=False, ambiente="prod", activo=True)
    db.add(e)
    db.commit()
    if payload.crear_catalogo:
        conta.crear_catalogo_base(db, e.id)
    auditoria.registrar(db, "contabilidad.empresa", principal=principal, request=request, emisor_id=e.id,
                        detalle=f"{e.numero_identificacion} {e.nombre}")
    return {"id": e.id, "nombre": e.nombre, "identificacion": e.numero_identificacion}


# --- Catálogo de cuentas -------------------------------------------------------------------

def _cuenta_dict(c: CuentaContable) -> dict:
    return {"id": c.id, "codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo, "nivel": c.codigo.count("."),
            "acepta_movimientos": c.acepta_movimientos, "clave_sistema": c.clave_sistema, "activa": c.activa}


@router.get("/cuentas")
def listar_cuentas(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    return [_cuenta_dict(c) for c in conta.ordenar(conta.cuentas(db, emisor.id))]


@router.post("/catalogo-base", status_code=201)
def catalogo_base(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Crea el catálogo base (NIIF para PYMES) para empezar; después se ajusta a la empresa."""
    try:
        return {"cuentas": conta.crear_catalogo_base(db, emisor.id)}
    except conta.ContabilidadError as exc:
        raise _error(exc)


def _validar_padre(db: Session, emisor_id: str, codigo: str, tipo: str) -> None:
    padre = conta.padre(codigo)
    if padre:
        p = db.scalar(select(CuentaContable).where(CuentaContable.emisor_id == emisor_id, CuentaContable.codigo == padre))
        if p is None:
            raise HTTPException(status_code=422, detail=f"No existe la cuenta de grupo {padre}")
        if p.tipo != tipo:
            raise HTTPException(status_code=422, detail=f"La cuenta debe ser del mismo tipo que su grupo {padre} ({p.tipo})")


@router.post("/cuentas", status_code=201)
def crear_cuenta(payload: CuentaRequest, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    _validar_padre(db, emisor.id, payload.codigo, payload.tipo)
    if db.scalar(select(CuentaContable).where(CuentaContable.emisor_id == emisor.id, CuentaContable.codigo == payload.codigo)):
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese código")
    c = CuentaContable(emisor_id=emisor.id, **payload.model_dump())
    db.add(c)
    db.commit()
    return _cuenta_dict(c)


@router.put("/cuentas/{cuenta_id}")
def actualizar_cuenta(cuenta_id: UUID, payload: CuentaRequest, emisor: Emisor = Depends(emisor_actual),
                      db: Session = Depends(get_db)):
    c = db.get(CuentaContable, str(cuenta_id))
    if c is None or c.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    con_movimientos = db.scalar(select(func.count()).select_from(AsientoLinea).where(AsientoLinea.cuenta_id == c.id))
    if con_movimientos and (payload.codigo != c.codigo or payload.tipo != c.tipo or not payload.acepta_movimientos):
        raise HTTPException(status_code=409, detail="La cuenta ya tiene movimientos: solo se puede cambiar el nombre o desactivar")
    if payload.codigo != c.codigo:
        _validar_padre(db, emisor.id, payload.codigo, payload.tipo)
    for campo, valor in payload.model_dump().items():
        setattr(c, campo, valor)
    db.commit()
    return _cuenta_dict(c)


# --- Asientos ---------------------------------------------------------------------------------

def _asiento(db: Session, emisor: Emisor, asiento_id: UUID) -> Asiento:
    a = db.get(Asiento, str(asiento_id))
    if a is None or a.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Asiento no encontrado")
    return a


@router.get("/asientos")
def listar_asientos(desde: Optional[date] = None, hasta: Optional[date] = None, q: Optional[str] = Query(default=None, max_length=100),
                    formato: Literal["json", "csv"] = "json",
                    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Libro diario."""
    desde, hasta = _rango(desde, hasta)
    lista = conta.diario(db, emisor.id, desde, hasta, (q or "").strip() or None)
    if formato == "csv":
        filas = [["Asiento", "Fecha", "Descripción", "Cuenta", "Nombre", "Detalle", "Debe", "Haber", "Estado"]]
        for a in lista:
            for ln in a["lineas"]:
                filas.append([a["numero"], a["fecha"], a["descripcion"], ln["codigo"], ln["nombre"], ln["detalle"] or "",
                              ln["debe"], ln["haber"], "Anulado" if a["anulado"] else ""])
        return _csv(filas, f"diario-{emisor.numero_identificacion}-{desde}-{hasta}.csv")
    return lista


@router.get("/asientos/{asiento_id}")
def obtener_asiento(asiento_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    return conta.asiento_a_dict(_asiento(db, emisor, asiento_id))


@router.post("/asientos", status_code=201)
def crear_asiento(payload: AsientoRequest, principal: Principal = Depends(permiso("contabilidad")),
                  emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    try:
        a = conta.crear_asiento(db, emisor.id, payload.fecha, payload.descripcion,
                                [ln.model_dump() for ln in payload.lineas], quien=auditoria.nombre_actor(db, principal))
    except conta.ContabilidadError as exc:
        raise _error(exc)
    return conta.asiento_a_dict(a)


@router.put("/asientos/{asiento_id}")
def actualizar_asiento(asiento_id: UUID, payload: AsientoRequest, emisor: Emisor = Depends(emisor_actual),
                       db: Session = Depends(get_db)):
    a = _asiento(db, emisor, asiento_id)
    try:
        conta.actualizar_asiento(db, a, payload.fecha, payload.descripcion, [ln.model_dump() for ln in payload.lineas])
    except conta.ContabilidadError as exc:
        raise _error(exc)
    return conta.asiento_a_dict(a)


@router.post("/asientos/{asiento_id}/anular")
def anular_asiento(asiento_id: UUID, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    a = _asiento(db, emisor, asiento_id)
    try:
        conta.anular_asiento(db, a)
    except conta.ContabilidadError as exc:
        raise _error(exc)
    return conta.asiento_a_dict(a)


@router.post("/contabilizar")
def contabilizar(payload: MesRequest, principal: Principal = Depends(permiso("contabilidad")),
                 emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Crea los asientos de los comprobantes del mes que todavía no tienen (ventas, compras, cobros)."""
    try:
        return conta.contabilizar(db, emisor.id, payload.anio, payload.mes, auditoria.nombre_actor(db, principal))
    except conta.ContabilidadError as exc:
        raise _error(exc)


# --- Cierre de meses ---------------------------------------------------------------------------

@router.get("/periodos")
def periodos(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    lista = db.scalars(select(PeriodoCerrado).where(PeriodoCerrado.emisor_id == emisor.id).order_by(PeriodoCerrado.mes.desc()))
    return [{"mes": p.mes.isoformat(), "cerrado_por": p.cerrado_por, "fecha": p.created_at} for p in lista]


@router.post("/periodos", status_code=201)
def cerrar_mes(payload: MesRequest, principal: Principal = Depends(permiso("contabilidad")),
               emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Cierra el mes: ya no se pueden crear, cambiar ni anular asientos con fecha de ese mes."""
    mes = date(payload.anio, payload.mes, 1)
    if db.get(PeriodoCerrado, (emisor.id, mes)):
        raise HTTPException(status_code=409, detail="Ese mes ya está cerrado")
    db.add(PeriodoCerrado(emisor_id=emisor.id, mes=mes, cerrado_por=auditoria.nombre_actor(db, principal)))
    db.commit()
    return {"mes": mes.isoformat()}


@router.delete("/periodos/{anio}/{mes}", status_code=204)
def abrir_mes(anio: int, mes: int, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    try:
        p = db.get(PeriodoCerrado, (emisor.id, date(anio, mes, 1)))
    except ValueError:
        raise HTTPException(status_code=422, detail="Mes inválido")
    if p is None:
        raise HTTPException(status_code=404, detail="Ese mes no está cerrado")
    db.delete(p)
    db.commit()


# --- Reportes contables --------------------------------------------------------------------------

@router.get("/reportes/comprobacion")
def balance_comprobacion(desde: Optional[date] = None, hasta: Optional[date] = None, formato: Literal["json", "csv"] = "json",
                         emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    desde, hasta = _rango(desde, hasta)
    r = conta.balance_comprobacion(db, emisor.id, desde, hasta)
    if formato == "csv":
        filas = [["Cuenta", "Nombre", "Saldo inicial", "Debe", "Haber", "Saldo deudor", "Saldo acreedor"]]
        filas += [[c["codigo"], c["nombre"], c["saldo_inicial"], c["debe"], c["haber"], c["saldo_deudor"], c["saldo_acreedor"]]
                  for c in r["cuentas"]]
        t = r["totales"]
        filas.append(["", "Totales", "", t.get("debe", "0"), t.get("haber", "0"), t.get("deudor", "0"), t.get("acreedor", "0")])
        return _csv(filas, f"comprobacion-{emisor.numero_identificacion}-{desde}-{hasta}.csv")
    return r


@router.get("/reportes/resultados")
def estado_resultados(desde: Optional[date] = None, hasta: Optional[date] = None, formato: Literal["json", "csv"] = "json",
                      emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    desde, hasta = _rango(desde, hasta)
    r = conta.estado_resultados(db, emisor.id, desde, hasta)
    if formato == "csv":
        filas = [["Cuenta", "Nombre", "Monto"]] + [[c["codigo"], c["nombre"], c["saldo"]] for c in r["cuentas"]]
        filas += [["", "Utilidad bruta", r["utilidad_bruta"]], ["", "Utilidad neta", r["utilidad_neta"]]]
        return _csv(filas, f"resultados-{emisor.numero_identificacion}-{desde}-{hasta}.csv")
    return r


@router.get("/reportes/balance")
def balance_general(fecha: Optional[date] = None, formato: Literal["json", "csv"] = "json",
                    emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    fecha = fecha or ahora_cr().date()
    r = conta.balance_general(db, emisor.id, fecha)
    if formato == "csv":
        filas = [["Cuenta", "Nombre", "Saldo"]]
        for seccion in ("activo", "pasivo", "patrimonio"):
            filas += [[c["codigo"], c["nombre"], c["saldo"]] for c in r[seccion]]
        filas += [["", "Resultado acumulado", r["resultado_acumulado"]],
                  ["", "Total activo", r["total_activo"]], ["", "Total pasivo y patrimonio", r["total_pasivo_patrimonio"]]]
        return _csv(filas, f"balance-{emisor.numero_identificacion}-{fecha}.csv")
    return r


@router.get("/reportes/mayor")
def libro_mayor(cuenta_id: UUID, desde: Optional[date] = None, hasta: Optional[date] = None,
                formato: Literal["json", "csv"] = "json",
                emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    c = db.get(CuentaContable, str(cuenta_id))
    if c is None or c.emisor_id != emisor.id:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    desde, hasta = _rango(desde, hasta)
    r = conta.mayor(db, emisor.id, c, desde, hasta)
    if formato == "csv":
        filas = [["Fecha", "Asiento", "Descripción", "Detalle", "Debe", "Haber", "Saldo"],
                 ["", "", "Saldo inicial", "", "", "", r["saldo_inicial"]]]
        filas += [[m["fecha"], m["numero"], m["descripcion"], m["detalle"] or "", m["debe"], m["haber"], m["saldo"]]
                  for m in r["movimientos"]]
        return _csv(filas, f"mayor-{c.codigo}-{desde}-{hasta}.csv")
    return r


# --- Comprobantes: los del sistema y los XML cargados ---------------------------------------------

@router.get("/documentos")
def documentos(anio: int = Query(ge=2018, le=2100), mes: int = Query(ge=1, le=12),
               emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Comprobantes aceptados del mes (ventas y compras) y el asiento de cada uno, si ya lo tiene."""
    desde = date(anio, mes, 1)
    hasta = (desde + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    facturas, recibidos, _ = conta.documentos_del_mes(db, emisor.id, desde, hasta)
    asientos = dict(db.execute(select(Asiento.documento_ref, Asiento.numero).where(
        Asiento.emisor_id == emisor.id, Asiento.documento_ref.is_not(None), Asiento.anulado.is_(False))).all())
    fx = lambda v, tc: str(conta.q(Decimal(v) * (Decimal(tc) if tc else 1)))   # noqa: E731
    return {
        "ventas": [{"id": f.id, "tipo_documento": f.tipo_documento, "consecutivo": f.numero_consecutivo,
                    "fecha": conta.fecha_cr(f.fecha_emision).isoformat(), "contraparte": f.receptor_nombre,
                    "moneda": f.moneda, "impuesto_crc": fx(f.monto_impuesto, f.tipo_cambio), "total_crc": fx(f.monto_total, f.tipo_cambio),
                    "importada": f.importada, "asiento": asientos.get(f"factura:{f.id}")} for f in facturas],
        "compras": [{"id": d.id, "tipo_documento": d.tipo_documento, "clave": d.clave,
                     "fecha": conta.fecha_cr(d.fecha_emision).isoformat(), "contraparte": d.proveedor_nombre,
                     "moneda": d.moneda, "impuesto_crc": fx(d.total_impuesto, d.tipo_cambio), "total_crc": fx(d.total_comprobante, d.tipo_cambio),
                     "importada": d.origen == "contable", "asiento": asientos.get(f"recibido:{d.id}")} for d in recibidos],
    }


@router.post("/importar")
def importar_xml(archivos: list[UploadFile] = File(..., description="XML de comprobantes (ventas y compras)"),
                 principal: Principal = Depends(permiso("contabilidad")),
                 emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """
    Carga los XML de Hacienda de una empresa que no factura en este sistema. Cada archivo
    se clasifica solo como venta o compra. Las empresas que facturan aquí ya tienen sus
    comprobantes y no usan esta carga.
    """
    if not emisor.solo_contabilidad:
        raise HTTPException(status_code=409, detail="Esta empresa factura en el sistema: sus comprobantes ya están aquí")
    if len(archivos) > 500:
        raise HTTPException(status_code=413, detail="Cargue como máximo 500 archivos a la vez")
    resultado = {"ventas": 0, "compras": 0, "errores": []}
    for archivo in archivos:
        contenido = archivo.file.read(5_000_001)
        try:
            tipo, _ = importacion_xml.importar(db, emisor, contenido)
            resultado["ventas" if tipo == "venta" else "compras"] += 1
        except importacion_xml.ImportacionError as exc:
            resultado["errores"].append({"archivo": archivo.filename, "error": str(exc)})
    auditoria.registrar(db, "contabilidad.importar", principal=principal, emisor_id=emisor.id,
                        detalle=f"{resultado['ventas']} ventas, {resultado['compras']} compras, {len(resultado['errores'])} errores")
    return resultado


# --- Asiento de cierre anual ------------------------------------------------------------------------

class AnioRequest(BaseModel):
    anio: int = Field(ge=2018, le=2100)


@router.get("/cierre-anual")
def cierre_anual(anio: int = Query(ge=2018, le=2100), formato: Literal["json", "csv"] = "json",
                 emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """
    Asiento de cierre del año: lleva a cero ingresos, costos y gastos contra utilidades
    acumuladas. Con formato=csv descarga el archivo digital (Excel) para guardarlo o, si el
    asiento se lleva en otro sistema, copiarlo a mano línea por línea.
    """
    p = conta.propuesta_cierre(db, emisor.id, anio)
    if formato == "csv":
        filas = [
            ["Asiento de cierre anual"], ["Empresa", emisor.nombre], ["Identificación", emisor.numero_identificacion],
            ["Año", anio], ["Fecha del asiento", p["fecha"]], ["Descripción", p["descripcion"]],
            ["Estado", f"Registrado como asiento N.º {p['registrado']['numero']}" if p["registrado"] else "Propuesta (sin registrar)"],
            [],
            ["Cuenta", "Nombre", "Debe", "Haber", "Detalle"],
            *[[ln["codigo"], ln["nombre"], ln["debe"], ln["haber"], ln.get("detalle") or ""] for ln in p["lineas"]],
            ["", "Totales", p["total"], p["total"], ""],
            [],
            ["Resultado del año", p["utilidad"]],
        ]
        return _csv(filas, f"cierre-{anio}-{emisor.numero_identificacion}.csv")
    return p


@router.post("/cierre-anual", status_code=201)
def registrar_cierre_anual(payload: AnioRequest, principal: Principal = Depends(permiso("contabilidad")),
                           emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Registra el asiento de cierre con fecha 31 de diciembre (una sola vez por año)."""
    try:
        a = conta.registrar_cierre(db, emisor.id, payload.anio, auditoria.nombre_actor(db, principal))
    except conta.ContabilidadError as exc:
        raise _error(exc)
    return conta.asiento_a_dict(a)
