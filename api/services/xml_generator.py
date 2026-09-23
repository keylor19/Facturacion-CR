"""
Genera los XML v4.4 de Hacienda:
  01 Factura, 02 Nota de débito, 03 Nota de crédito, 04 Tiquete,
  08 Factura de compra, 09 Factura de exportación y
  05/06/07 Mensaje Receptor (aceptación / aceptación parcial / rechazo).

Incluye IVA con todas las tarifas, otros impuestos, exoneraciones,
descuentos, otros cargos, varios medios de pago y referencias.

⚠️ Configurá XSD_DIR con los XSD oficiales de ATV: cada XML firmado se
valida contra ellos antes de guardarse (ver validar_xsd).
"""
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from lxml import etree

from api.models.schemas import (
    FacturaRequest, LineaRequest, PersonaRequest, TARIFAS_IVA, CODIGOS_IVA, CODIGOS_EN_BASE_IVA,
)
from api.services.fechas import a_iso_cr, zona_cr
from api.services.xml_seguro import parser_seguro
from config.settings import get_settings

NS_BASE = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/"

# tipo_documento -> (elemento raíz, sufijo del namespace, archivo XSD)
DOCUMENTOS = {
    "01": ("FacturaElectronica", "facturaElectronica", "FacturaElectronica_V4.4.xsd"),
    "02": ("NotaDebitoElectronica", "notaDebitoElectronica", "NotaDebitoElectronica_V4.4.xsd"),
    "03": ("NotaCreditoElectronica", "notaCreditoElectronica", "NotaCreditoElectronica_V4.4.xsd"),
    "04": ("TiqueteElectronico", "tiqueteElectronico", "TiqueteElectronico_V4.4.xsd"),
    "05": ("MensajeReceptor", "mensajeReceptor", "MensajeReceptor_V4.4.xsd"),
    "06": ("MensajeReceptor", "mensajeReceptor", "MensajeReceptor_V4.4.xsd"),
    "07": ("MensajeReceptor", "mensajeReceptor", "MensajeReceptor_V4.4.xsd"),
    "08": ("FacturaElectronicaCompra", "facturaElectronicaCompra", "FacturaElectronicaCompra_V4.4.xsd"),
    "09": ("FacturaElectronicaExportacion", "facturaElectronicaExportacion", "FacturaElectronicaExportacion_V4.4.xsd"),
    "10": ("ReciboElectronicoPago", "reciboElectronicoPago", "ReciboElectronicoPago_V4.4.xsd"),
}

# Diferencias de estructura por tipo de documento (según los XSD oficiales v4.4)
PERFILES = {
    # Factura de compra: la línea no lleva ImpuestoAsumidoEmisorFabrica
    "08": {"linea_omite": {"ImpuestoAsumidoEmisorFabrica", "IVACobradoFabrica", "DatosImpuestoEspecifico"}},
    # Exportación: sin BaseImponible/ImpuestoNeto en la línea, sin exoneraciones
    # en el resumen y el receptor no lleva Ubicacion
    "09": {
        "linea_omite": {"BaseImponible", "ImpuestoAsumidoEmisorFabrica", "ImpuestoNeto",
                        "IVACobradoFabrica", "DatosImpuestoEspecifico"},
        "resumen_sin_exonerado": True,
        "receptor_sin_ubicacion": True,
    },
}

# Mensaje del receptor -> tipo de documento del consecutivo
TIPO_DOC_MENSAJE_RECEPTOR = {"1": "05", "2": "06", "3": "07"}

CODIGO_IMPUESTO_IVA = "01"
CODIGO_TARIFA_EXENTA = "10"

Q5 = Decimal("0.00001")
CERO = Decimal("0")


class XMLValidacionError(ValueError):
    pass


def q(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(Q5, rounding=ROUND_HALF_UP)


def _fmt(valor) -> str:
    if isinstance(valor, Decimal):
        return format(q(valor), "f")
    return str(valor)


def _fmt_pct(valor: Decimal) -> str:
    return format(Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _sub(parent, tag, text=None):
    el = etree.SubElement(parent, f"{{{parent.nsmap[None]}}}{tag}")
    if text is not None:
        el.text = _fmt(text)
    return el


def _opt(parent, tag, text):
    """Agrega el elemento solo si hay valor."""
    if text not in (None, ""):
        _sub(parent, tag, text)


def _iso(fecha: datetime) -> str:
    if fecha.tzinfo is None:  # sin zona: se asume hora de Costa Rica
        fecha = fecha.replace(tzinfo=zona_cr())
    return a_iso_cr(fecha)


# ==========================================================================
# Motor de cálculo
# ==========================================================================

@dataclass
class ImpuestoCalculado:
    codigo: str
    codigo_impuesto_otro: str | None
    codigo_tarifa_iva: str | None
    tarifa: Decimal | None
    factor_calculo_iva: Decimal | None
    monto: Decimal
    exoneracion: object = None          # ExoneracionRequest
    monto_exoneracion: Decimal = CERO
    tarifa_exonerada: Decimal = CERO
    datos_especificos: object = None    # DatosImpuestoEspecificoRequest

    @property
    def neto(self) -> Decimal:
        return self.monto - self.monto_exoneracion


@dataclass
class LineaCalculada:
    numero: int
    producto: LineaRequest
    monto_total: Decimal
    descuento: Decimal
    subtotal: Decimal
    base_imponible: Decimal
    impuestos: list[ImpuestoCalculado]
    categoria: str               # gravado | exento | exonerado | no_sujeto (parcial se reparte)
    parte_gravada: Decimal
    parte_exenta: Decimal
    parte_exonerada: Decimal
    parte_no_sujeta: Decimal = CERO
    impuesto_asumido: Decimal = CERO   # asumido por el emisor o cobrado a nivel de fábrica

    @property
    def impuesto_bruto(self) -> Decimal:
        return sum((i.monto for i in self.impuestos), CERO)

    @property
    def monto_exonerado(self) -> Decimal:
        return sum((i.monto_exoneracion for i in self.impuestos), CERO)

    @property
    def impuesto_neto(self) -> Decimal:
        # "Monto del impuesto" menos lo exonerado o lo asumido / cobrado en fábrica
        return self.impuesto_bruto - self.monto_exonerado - self.impuesto_asumido

    @property
    def monto_total_linea(self) -> Decimal:
        return self.subtotal + self.impuesto_neto

    @property
    def tarifa_iva(self) -> Decimal | None:
        for i in self.impuestos:
            if i.codigo in CODIGOS_IVA:
                return i.tarifa
        return None


@dataclass
class Totales:
    serv_gravados: Decimal = CERO
    serv_exentos: Decimal = CERO
    serv_exonerado: Decimal = CERO
    serv_no_sujeto: Decimal = CERO
    merc_gravadas: Decimal = CERO
    merc_exentas: Decimal = CERO
    merc_exonerada: Decimal = CERO
    merc_no_sujeta: Decimal = CERO
    descuentos: Decimal = CERO
    impuesto: Decimal = CERO
    impuesto_asumido: Decimal = CERO
    otros_cargos: Decimal = CERO
    iva_devuelto: Decimal = CERO
    desglose: dict = field(default_factory=dict)   # (codigo, codigo_tarifa) -> monto
    cargos: list = field(default_factory=list)     # [(OtroCargoRequest, monto)]

    @property
    def gravado(self): return self.serv_gravados + self.merc_gravadas

    @property
    def exento(self): return self.serv_exentos + self.merc_exentas

    @property
    def exonerado(self): return self.serv_exonerado + self.merc_exonerada

    @property
    def no_sujeto(self): return self.serv_no_sujeto + self.merc_no_sujeta

    @property
    def venta(self): return self.gravado + self.exento + self.exonerado + self.no_sujeto

    @property
    def venta_neta(self): return self.venta - self.descuentos

    @property
    def comprobante(self):
        # Total venta neta + impuesto + otros cargos - IVA devuelto (XSD oficial)
        return self.venta_neta + self.impuesto + self.otros_cargos - self.iva_devuelto


def _calcular_linea(numero: int, p: LineaRequest) -> LineaCalculada:
    monto_total = q(p.cantidad * p.precio_unitario)
    descuento = q(p.descuento)
    subtotal = monto_total - descuento

    impuestos: list[ImpuestoCalculado] = []
    # 1) Impuestos distintos de IVA. Según el XSD oficial, solo el selectivo de
    #    consumo (02), bebidas alcohólicas (04), bebidas envasadas y jabones (05)
    #    y cemento (12) forman parte de la base imponible del IVA.
    en_base_iva = CERO
    for imp in p.impuestos_efectivos:
        if imp.codigo in CODIGOS_IVA:
            continue
        monto = q(imp.monto) if imp.monto is not None else q(subtotal * imp.tarifa / 100)
        impuestos.append(ImpuestoCalculado(
            codigo=imp.codigo, codigo_impuesto_otro=imp.codigo_impuesto_otro, codigo_tarifa_iva=None,
            tarifa=imp.tarifa, factor_calculo_iva=None, monto=monto, datos_especificos=imp.datos_especificos,
        ))
        if imp.codigo in CODIGOS_EN_BASE_IVA:
            en_base_iva += monto

    base_imponible = subtotal + en_base_iva

    # 2) IVA
    factor_exoneracion = CERO
    exento = p.iva_cobrado_fabrica == "02"
    iva_total = CERO
    for imp in p.impuestos_efectivos:
        if imp.codigo not in CODIGOS_IVA:
            continue
        tarifa = imp.tarifa if imp.tarifa is not None else TARIFAS_IVA[imp.codigo_tarifa_iva]
        if imp.factor_calculo_iva is not None:
            # IVA de bienes usados: factor establecido por Hacienda sobre la base
            monto = q(base_imponible * imp.factor_calculo_iva)
        else:
            monto = q(base_imponible * tarifa / 100)
        calc = ImpuestoCalculado(
            codigo=imp.codigo, codigo_impuesto_otro=None, codigo_tarifa_iva=imp.codigo_tarifa_iva,
            tarifa=tarifa, factor_calculo_iva=imp.factor_calculo_iva, monto=monto,
        )
        if imp.codigo_tarifa_iva == CODIGO_TARIFA_EXENTA:
            exento = True
        if p.exoneracion and imp.codigo == CODIGO_IMPUESTO_IVA and tarifa > 0:
            tarifa_exo = min(p.exoneracion.tarifa_exonerada, tarifa)
            calc.exoneracion = p.exoneracion
            calc.tarifa_exonerada = tarifa_exo
            calc.monto_exoneracion = min(q(base_imponible * tarifa_exo / 100), monto)
            factor_exoneracion = tarifa_exo / tarifa
        iva_total += calc.monto - calc.monto_exoneracion
        impuestos.append(calc)

    # El XSD exige al menos un nodo Impuesto por línea: las líneas no sujetas o
    # exentas por el sistema de fábrica llevan IVA con monto 0 (tarifa 0% de la
    # línea si indica una; si no, 10 = exenta). ⚠️ Confirmar criterio en stag.
    if (p.no_sujeto or p.iva_cobrado_fabrica == "02") and not any(i.codigo in CODIGOS_IVA for i in impuestos):
        codigo_cero = p.codigo_tarifa_iva if TARIFAS_IVA[p.codigo_tarifa_iva] == 0 else CODIGO_TARIFA_EXENTA
        impuestos.append(ImpuestoCalculado(
            codigo=CODIGO_IMPUESTO_IVA, codigo_impuesto_otro=None, codigo_tarifa_iva=codigo_cero,
            tarifa=CERO, factor_calculo_iva=None, monto=CERO,
        ))

    # 3) Impuesto asumido por el emisor o IVA cobrado a nivel de fábrica
    impuesto_asumido = CERO
    if p.impuesto_asumido_emisor:
        impuesto_asumido = sum((i.monto - i.monto_exoneracion for i in impuestos), CERO)
    elif p.iva_cobrado_fabrica == "01":
        impuesto_asumido = iva_total

    # 4) Clasificación de la venta para el resumen
    parte_no_sujeta = CERO
    if p.no_sujeto:
        parte_no_sujeta, parte_exenta, parte_exonerada, parte_gravada = monto_total, CERO, CERO, CERO
        categoria = "no_sujeto"
    elif exento:
        parte_exenta, parte_exonerada, parte_gravada = monto_total, CERO, CERO
        categoria = "exento"
    else:
        parte_exonerada = q(monto_total * factor_exoneracion)
        parte_gravada = monto_total - parte_exonerada
        parte_exenta = CERO
        categoria = "exonerado" if parte_exonerada == monto_total else "gravado"

    return LineaCalculada(
        numero=numero, producto=p, monto_total=monto_total, descuento=descuento, subtotal=subtotal,
        base_imponible=base_imponible, impuestos=impuestos, categoria=categoria,
        parte_gravada=parte_gravada, parte_exenta=parte_exenta, parte_exonerada=parte_exonerada,
        parte_no_sujeta=parte_no_sujeta, impuesto_asumido=impuesto_asumido,
    )


def calcular(datos: FacturaRequest) -> tuple[list[LineaCalculada], Totales]:
    """Calcula montos por línea y totales del resumen (fuente única de verdad)."""
    lineas = [_calcular_linea(i, p) for i, p in enumerate(datos.productos, start=1)]
    t = Totales()

    for ln in lineas:
        if ln.producto.servicio:
            t.serv_gravados += ln.parte_gravada
            t.serv_exentos += ln.parte_exenta
            t.serv_exonerado += ln.parte_exonerada
            t.serv_no_sujeto += ln.parte_no_sujeta
        else:
            t.merc_gravadas += ln.parte_gravada
            t.merc_exentas += ln.parte_exenta
            t.merc_exonerada += ln.parte_exonerada
            t.merc_no_sujeta += ln.parte_no_sujeta
        t.descuentos += ln.descuento
        t.impuesto += ln.impuesto_neto
        t.impuesto_asumido += ln.impuesto_asumido
        for imp in ln.impuestos:
            llave = (imp.codigo, imp.codigo_tarifa_iva)
            t.desglose[llave] = t.desglose.get(llave, CERO) + imp.neto
        if ln.impuesto_asumido:
            # Lo asumido/cobrado en fábrica no se cobra en este comprobante
            for imp in ln.impuestos:
                if ln.producto.impuesto_asumido_emisor or imp.codigo in CODIGOS_IVA:
                    llave = (imp.codigo, imp.codigo_tarifa_iva)
                    t.desglose[llave] -= imp.neto

    for cargo in datos.otros_cargos:
        monto = q(cargo.monto) if cargo.monto is not None else q(t.venta_neta * cargo.porcentaje / 100)
        t.cargos.append((cargo, monto))
        t.otros_cargos += monto

    if datos.iva_devuelto:
        t.iva_devuelto = q(datos.iva_devuelto)
        if t.iva_devuelto > t.impuesto:
            raise XMLValidacionError("iva_devuelto no puede ser mayor al impuesto del comprobante")

    return lineas, t


# ==========================================================================
# Construcción del XML
# ==========================================================================

def persona_desde_request(p: PersonaRequest) -> dict:
    return {
        "nombre": p.nombre,
        "tipo_identificacion": p.tipo_identificacion,
        "numero_identificacion": p.numero_identificacion,
        "identificacion_extranjero": p.identificacion_extranjero,
        "nombre_comercial": p.nombre_comercial,
        "ubicacion": p.ubicacion.model_dump() if p.ubicacion else None,
        "otras_senas_extranjero": p.otras_senas_extranjero,
        "telefono_codigo_pais": p.telefono_codigo_pais,
        "telefono": p.telefono,
        "correo": p.correo,
    }


def _nodo_persona(root, tag: str, persona: dict, con_ubicacion: bool = True):
    nodo = _sub(root, tag)
    _sub(nodo, "Nombre", persona["nombre"])
    if persona.get("numero_identificacion"):
        ident = _sub(nodo, "Identificacion")
        _sub(ident, "Tipo", persona["tipo_identificacion"])
        _sub(ident, "Numero", persona["numero_identificacion"])
    if tag == "Emisor":
        _opt(nodo, "Registrofiscal8707", persona.get("registro_fiscal_8707"))
    _opt(nodo, "NombreComercial", persona.get("nombre_comercial"))
    ubic = persona.get("ubicacion")
    if ubic and con_ubicacion:
        u = _sub(nodo, "Ubicacion")
        _sub(u, "Provincia", ubic["provincia"])
        _sub(u, "Canton", ubic["canton"])
        _sub(u, "Distrito", ubic["distrito"])
        _opt(u, "Barrio", ubic.get("barrio"))
        _sub(u, "OtrasSenas", ubic["otras_senas"])
    _opt(nodo, "OtrasSenasExtranjero", persona.get("otras_senas_extranjero"))
    if persona.get("telefono"):
        tel = _sub(nodo, "Telefono")
        _sub(tel, "CodigoPais", persona.get("telefono_codigo_pais") or "506")
        _sub(tel, "NumTelefono", persona["telefono"])
    _opt(nodo, "CorreoElectronico", persona.get("correo"))
    return nodo


def _nodo_linea(detalle, ln: LineaCalculada, omite: set = frozenset()):
    p = ln.producto
    linea = _sub(detalle, "LineaDetalle")

    def _campo(tag, valor):
        if tag not in omite:
            _sub(linea, tag, valor)

    _sub(linea, "NumeroLinea", ln.numero)
    _opt(linea, "PartidaArancelaria", p.partida_arancelaria)
    _sub(linea, "CodigoCABYS", p.codigo_cabys)
    if p.codigo_comercial:
        cc = _sub(linea, "CodigoComercial")
        _sub(cc, "Tipo", "04")  # 04 = código de uso interno
        _sub(cc, "Codigo", p.codigo_comercial)
    _sub(linea, "Cantidad", format(p.cantidad, "f"))
    _sub(linea, "UnidadMedida", p.unidad_medida)
    _opt(linea, "TipoTransaccion", p.tipo_transaccion)
    _opt(linea, "UnidadMedidaComercial", p.unidad_medida_comercial)
    _sub(linea, "Detalle", p.descripcion)
    _sub(linea, "PrecioUnitario", p.precio_unitario)
    _sub(linea, "MontoTotal", ln.monto_total)
    if ln.descuento > 0:
        desc = _sub(linea, "Descuento")
        _sub(desc, "MontoDescuento", ln.descuento)
        _sub(desc, "CodigoDescuento", p.codigo_descuento)
        _opt(desc, "CodigoDescuentoOTRO", p.codigo_descuento_otro)
        _opt(desc, "NaturalezaDescuento", p.naturaleza_descuento)
    _sub(linea, "SubTotal", ln.subtotal)
    if "IVACobradoFabrica" not in omite:
        _opt(linea, "IVACobradoFabrica", p.iva_cobrado_fabrica)
    _campo("BaseImponible", ln.base_imponible)

    for imp in ln.impuestos:
        ni = _sub(linea, "Impuesto")
        _sub(ni, "Codigo", imp.codigo)
        _opt(ni, "CodigoImpuestoOTRO", imp.codigo_impuesto_otro)
        _opt(ni, "CodigoTarifaIVA", imp.codigo_tarifa_iva)
        if imp.tarifa is not None:
            _sub(ni, "Tarifa", _fmt_pct(imp.tarifa))
        if imp.factor_calculo_iva is not None:
            _sub(ni, "FactorCalculoIVA", format(imp.factor_calculo_iva, "f"))
        if imp.datos_especificos is not None and "DatosImpuestoEspecifico" not in omite:
            de = imp.datos_especificos
            nd = _sub(ni, "DatosImpuestoEspecifico")
            _opt(nd, "CantidadUnidadMedida", de.cantidad_unidad_medida)
            _opt(nd, "Porcentaje", de.porcentaje)
            _opt(nd, "Proporcion", de.proporcion)
            _opt(nd, "VolumenUnidadConsumo", de.volumen_unidad_consumo)
            _sub(nd, "ImpuestoUnidad", de.impuesto_unidad)
        _sub(ni, "Monto", imp.monto)
        if imp.exoneracion is not None:
            ex = imp.exoneracion
            ne = _sub(ni, "Exoneracion")
            _sub(ne, "TipoDocumentoEX1", ex.tipo_documento)
            _opt(ne, "TipoDocumentoOTRO", ex.tipo_documento_otro)
            _sub(ne, "NumeroDocumento", ex.numero_documento)
            _opt(ne, "Articulo", ex.articulo)
            _opt(ne, "Inciso", ex.inciso)
            _sub(ne, "NombreInstitucion", ex.nombre_institucion)
            _opt(ne, "NombreInstitucionOtros", ex.nombre_institucion_otros)
            _sub(ne, "FechaEmisionEX", _iso(ex.fecha_emision))
            _sub(ne, "TarifaExonerada", _fmt_pct(imp.tarifa_exonerada))
            _sub(ne, "MontoExoneracion", imp.monto_exoneracion)

    _campo("ImpuestoAsumidoEmisorFabrica", ln.impuesto_asumido)
    _campo("ImpuestoNeto", ln.impuesto_neto)
    _sub(linea, "MontoTotalLinea", ln.monto_total_linea)


def _nodo_resumen(root, datos: FacturaRequest, t: Totales, con_exonerado: bool = True):
    resumen = _sub(root, "ResumenFactura")
    codmoneda = _sub(resumen, "CodigoTipoMoneda")
    _sub(codmoneda, "CodigoMoneda", datos.moneda)
    _sub(codmoneda, "TipoCambio", datos.tipo_cambio if datos.moneda != "CRC" else Decimal("1"))

    _sub(resumen, "TotalServGravados", t.serv_gravados)
    _sub(resumen, "TotalServExentos", t.serv_exentos)
    # Exportación no admite totales de exonerado ni de no sujeto
    if con_exonerado:
        _sub(resumen, "TotalServExonerado", t.serv_exonerado)
        if t.no_sujeto > 0:
            _sub(resumen, "TotalServNoSujeto", t.serv_no_sujeto)
    _sub(resumen, "TotalMercanciasGravadas", t.merc_gravadas)
    _sub(resumen, "TotalMercanciasExentas", t.merc_exentas)
    if con_exonerado:
        _sub(resumen, "TotalMercExonerada", t.merc_exonerada)
        if t.no_sujeto > 0:
            _sub(resumen, "TotalMercNoSujeta", t.merc_no_sujeta)
    _sub(resumen, "TotalGravado", t.gravado)
    _sub(resumen, "TotalExento", t.exento)
    if con_exonerado:
        _sub(resumen, "TotalExonerado", t.exonerado)
        if t.no_sujeto > 0:
            _sub(resumen, "TotalNoSujeto", t.no_sujeto)
    _sub(resumen, "TotalVenta", t.venta)
    _sub(resumen, "TotalDescuentos", t.descuentos)
    _sub(resumen, "TotalVentaNeta", t.venta_neta)
    for (codigo, codigo_tarifa), monto in sorted(t.desglose.items(), key=lambda x: (x[0][0], x[0][1] or "")):
        dg = _sub(resumen, "TotalDesgloseImpuesto")
        _sub(dg, "Codigo", codigo)
        _opt(dg, "CodigoTarifaIVA", codigo_tarifa)
        _sub(dg, "TotalMontoImpuesto", monto)
    _sub(resumen, "TotalImpuesto", t.impuesto)
    if t.impuesto_asumido > 0:
        _sub(resumen, "TotalImpAsumEmisorFabrica", t.impuesto_asumido)
    if t.iva_devuelto > 0:
        _sub(resumen, "TotalIVADevuelto", t.iva_devuelto)
    if t.otros_cargos > 0:
        _sub(resumen, "TotalOtrosCargos", t.otros_cargos)

    medios = datos.medios_pago
    if len(medios) > 1:
        suma = q(sum((m.monto for m in medios), CERO))
        if suma != q(t.comprobante):
            raise XMLValidacionError(
                f"La suma de los medios de pago ({suma}) no coincide con el total del comprobante ({q(t.comprobante)})"
            )
    for m in medios:
        mp = _sub(resumen, "MedioPago")
        _sub(mp, "TipoMedioPago", m.tipo)
        _opt(mp, "MedioPagoOtros", m.tipo_otros)
        _sub(mp, "TotalMedioPago", m.monto if m.monto is not None else t.comprobante)

    _sub(resumen, "TotalComprobante", t.comprobante)


def generar_xml(
    clave: str,
    numero_consecutivo: str,
    fecha_emision: datetime,
    emisor: dict,
    datos: FacturaRequest,
) -> tuple[str, list[LineaCalculada], Totales]:
    """
    Devuelve (xml_sin_firmar, lineas, totales). La firma se aplica después con services/firma.py.

    `emisor` es el contribuyente que emite el documento (el que firma). En la
    factura de compra (08) el nodo Emisor es el proveedor y el nodo Receptor
    es el contribuyente.
    """
    faltantes = [c for c in ("nombre", "numero_identificacion", "codigo_actividad", "correo",
                             "ubicacion", "proveedor_sistemas") if not emisor.get(c)]
    if faltantes:
        raise XMLValidacionError("Faltan datos del emisor: " + ", ".join(faltantes))

    raiz, ns_sufijo, _ = DOCUMENTOS[datos.tipo_documento]
    perfil = PERFILES.get(datos.tipo_documento, {})
    lineas, tot = calcular(datos)
    actividad_contribuyente = datos.codigo_actividad_emisor or emisor["codigo_actividad"]

    root = etree.Element(f"{{{NS_BASE}{ns_sufijo}}}{raiz}", nsmap={None: NS_BASE + ns_sufijo})

    _sub(root, "Clave", clave)
    _sub(root, "ProveedorSistemas", emisor["proveedor_sistemas"])
    if datos.tipo_documento == "08":
        # En la FEC el nodo Emisor es el proveedor (su actividad es opcional)
        # y el contribuyente que la emite es el Receptor.
        _opt(root, "CodigoActividadEmisor", datos.proveedor.codigo_actividad)
        _sub(root, "CodigoActividadReceptor", actividad_contribuyente)
    else:
        _sub(root, "CodigoActividadEmisor", actividad_contribuyente)
        if datos.tipo_documento != "09":
            _opt(root, "CodigoActividadReceptor", datos.codigo_actividad_receptor)
    _sub(root, "NumeroConsecutivo", numero_consecutivo)
    _sub(root, "FechaEmision", a_iso_cr(fecha_emision))

    if datos.tipo_documento == "08":
        _nodo_persona(root, "Emisor", persona_desde_request(datos.proveedor))
        _nodo_persona(root, "Receptor", emisor)
    else:
        _nodo_persona(root, "Emisor", emisor)
        if datos.receptor:
            _nodo_persona(root, "Receptor", persona_desde_request(datos.receptor),
                          con_ubicacion=not perfil.get("receptor_sin_ubicacion"))

    _sub(root, "CondicionVenta", datos.condicion_venta)
    _opt(root, "CondicionVentaOtros", datos.condicion_venta_otros)
    _opt(root, "PlazoCredito", datos.plazo_credito)

    detalle = _sub(root, "DetalleServicio")
    for ln in lineas:
        _nodo_linea(detalle, ln, omite=perfil.get("linea_omite", frozenset()))

    for cargo, monto in tot.cargos:
        oc = _sub(root, "OtrosCargos")
        _sub(oc, "TipoDocumentoOC", cargo.tipo_documento)
        _opt(oc, "TipoDocumentoOTROS", cargo.tipo_documento_otros)
        if cargo.tercero_identificacion:
            it = _sub(oc, "IdentificacionTercero")
            _sub(it, "Tipo", cargo.tercero_tipo_identificacion or "01")
            _sub(it, "Numero", cargo.tercero_identificacion)
        _opt(oc, "NombreTercero", cargo.tercero_nombre)
        _sub(oc, "Detalle", cargo.detalle)
        if cargo.porcentaje is not None:
            _sub(oc, "PorcentajeOC", _fmt_pct(cargo.porcentaje))
        _sub(oc, "MontoCargo", monto)

    _nodo_resumen(root, datos, tot, con_exonerado=not perfil.get("resumen_sin_exonerado"))

    for ref in datos.referencias:
        ir = _sub(root, "InformacionReferencia")
        _sub(ir, "TipoDocIR", ref.tipo_documento)
        _opt(ir, "TipoDocRefOTRO", ref.tipo_documento_otro)
        _opt(ir, "Numero", ref.numero)
        _sub(ir, "FechaEmisionIR", _iso(ref.fecha_emision))
        _opt(ir, "Codigo", ref.codigo)
        _opt(ir, "CodigoReferenciaOTRO", ref.codigo_otro)
        _opt(ir, "Razon", ref.razon)

    if datos.notas:
        otros = _sub(root, "Otros")
        _sub(otros, "OtroTexto", datos.notas)

    xml_str = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=False)
    return xml_str.decode("utf-8"), lineas, tot


def generar_mensaje_receptor(
    clave_documento: str,
    cedula_proveedor: str,
    fecha: datetime,
    mensaje: str,
    detalle_mensaje: str | None,
    monto_total_impuesto: Decimal | None,
    codigo_actividad: str | None,
    condicion_impuesto: str | None,
    monto_impuesto_acreditar: Decimal | None,
    monto_gasto_aplicable: Decimal | None,
    total_factura: Decimal,
    cedula_receptor: str,
    consecutivo_receptor: str,
) -> str:
    """XML MensajeReceptor v4.4 (aceptación/rechazo de un comprobante recibido), sin firmar."""
    ns = NS_BASE + "mensajeReceptor"
    root = etree.Element(f"{{{ns}}}MensajeReceptor", nsmap={None: ns})
    _sub(root, "Clave", clave_documento)
    _sub(root, "NumeroCedulaEmisor", cedula_proveedor)
    _sub(root, "FechaEmisionDoc", a_iso_cr(fecha))
    _sub(root, "Mensaje", mensaje)
    _opt(root, "DetalleMensaje", detalle_mensaje)
    if monto_total_impuesto is not None:
        _sub(root, "MontoTotalImpuesto", monto_total_impuesto)
    _opt(root, "CodigoActividad", codigo_actividad)
    _opt(root, "CondicionImpuesto", condicion_impuesto)
    if monto_impuesto_acreditar is not None:
        _sub(root, "MontoTotalImpuestoAcreditar", monto_impuesto_acreditar)
    if monto_gasto_aplicable is not None:
        _sub(root, "MontoTotalDeGastoAplicable", monto_gasto_aplicable)
    _sub(root, "TotalFactura", total_factura)
    _sub(root, "NumeroCedulaReceptor", cedula_receptor)
    _sub(root, "NumeroConsecutivoReceptor", consecutivo_receptor)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")


@dataclass
class LineaRecibo:
    """Porción de un pago correspondiente a una tarifa de IVA de la factura original."""
    detalle: str
    subtotal: Decimal
    codigo_tarifa_iva: str | None
    tarifa: Decimal | None
    impuesto: Decimal

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.impuesto


def generar_recibo_pago(
    clave: str,
    numero_consecutivo: str,
    fecha_emision: datetime,
    emisor: dict,
    receptor: dict,
    condicion_venta: str,
    moneda: str,
    tipo_cambio: Decimal | None,
    lineas: list[LineaRecibo],
    medios_pago: list,
    referencia: dict,
) -> str:
    """
    XML del Recibo Electrónico de Pago (10) v4.4: registra el pago de una
    factura a crédito (condición 08 → 09, o 10 → 11) y el IVA correspondiente.
    """
    ns = NS_BASE + "reciboElectronicoPago"
    root = etree.Element(f"{{{ns}}}ReciboElectronicoPago", nsmap={None: ns})
    _sub(root, "Clave", clave)
    _sub(root, "ProveedorSistemas", emisor["proveedor_sistemas"])
    _sub(root, "NumeroConsecutivo", numero_consecutivo)
    _sub(root, "FechaEmision", a_iso_cr(fecha_emision))

    em = _sub(root, "Emisor")
    _sub(em, "Nombre", emisor["nombre"])
    ident = _sub(em, "Identificacion")
    _sub(ident, "Tipo", emisor["tipo_identificacion"])
    _sub(ident, "Numero", emisor["numero_identificacion"])
    _sub(em, "CorreoElectronico", emisor["correo"])

    rec = _sub(root, "Receptor")
    _sub(rec, "Nombre", receptor["nombre"])
    rid = _sub(rec, "Identificacion")
    _sub(rid, "Tipo", receptor["tipo_identificacion"])
    _sub(rid, "Numero", receptor["numero_identificacion"])
    _opt(rec, "CorreoElectronico", receptor.get("correo"))

    _sub(root, "CondicionVenta", condicion_venta)

    detalle = _sub(root, "DetalleServicio")
    desglose: dict = {}
    total_venta = total_impuesto = CERO
    for i, ln in enumerate(lineas, start=1):
        nl = _sub(detalle, "LineaDetalle")
        _sub(nl, "NumeroLinea", i)
        _sub(nl, "Detalle", ln.detalle[:200])
        _sub(nl, "MontoTotal", ln.subtotal)
        _sub(nl, "SubTotal", ln.subtotal)   # en el REP corresponde al monto pagado sin impuesto
        if ln.codigo_tarifa_iva:
            imp = _sub(nl, "Impuesto")
            _sub(imp, "Codigo", CODIGO_IMPUESTO_IVA)
            _sub(imp, "CodigoTarifaIVA", ln.codigo_tarifa_iva)
            _sub(imp, "Tarifa", _fmt_pct(ln.tarifa or CERO))
            _sub(imp, "Monto", ln.impuesto)
            desglose[ln.codigo_tarifa_iva] = desglose.get(ln.codigo_tarifa_iva, CERO) + ln.impuesto
        _sub(nl, "ImpuestoNeto", ln.impuesto)
        _sub(nl, "MontoTotalLinea", ln.total)
        total_venta += ln.subtotal
        total_impuesto += ln.impuesto

    total = total_venta + total_impuesto
    resumen = _sub(root, "ResumenFactura")
    cm = _sub(resumen, "CodigoTipoMoneda")
    _sub(cm, "CodigoMoneda", moneda)
    _sub(cm, "TipoCambio", tipo_cambio if moneda != "CRC" and tipo_cambio else Decimal("1"))
    _sub(resumen, "TotalVenta", total_venta)
    _sub(resumen, "TotalVentaNeta", total_venta)
    for codigo_tarifa, monto in sorted(desglose.items()):
        dg = _sub(resumen, "TotalDesgloseImpuesto")
        _sub(dg, "Codigo", CODIGO_IMPUESTO_IVA)
        _sub(dg, "CodigoTarifaIVA", codigo_tarifa)
        _sub(dg, "TotalMontoImpuesto", monto)
    _sub(resumen, "TotalImpuesto", total_impuesto)
    if len(medios_pago) > 1 and q(sum((m.monto for m in medios_pago), CERO)) != q(total):
        raise XMLValidacionError("La suma de los medios de pago no coincide con el monto del pago")
    for m in medios_pago:
        mp = _sub(resumen, "MedioPago")
        _sub(mp, "TipoMedioPago", m.tipo)
        _opt(mp, "MedioPagoOtros", m.tipo_otros)
        _sub(mp, "TotalMedioPago", m.monto if m.monto is not None else total)
    _sub(resumen, "TotalComprobante", total)

    ir = _sub(root, "InformacionReferencia")
    _sub(ir, "TipoDocIR", referencia["tipo_documento"])
    _sub(ir, "Numero", referencia["numero"])
    _sub(ir, "FechaEmisionIR", _iso(referencia["fecha_emision"]))
    _opt(ir, "Codigo", referencia.get("codigo"))
    _opt(ir, "Razon", referencia.get("razon"))

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")


# ==========================================================================
# Validación XSD
# ==========================================================================

@lru_cache(maxsize=None)
def _cargar_xsd(ruta: str) -> etree.XMLSchema:
    # Los XSD son archivos locales de confianza; xmldsig-core-schema.xsd usa
    # entidades DTD internas, por eso aquí (y solo aquí) se resuelven. Nunca red.
    parser = etree.XMLParser(no_network=True, resolve_entities=True, load_dtd=True)
    with open(ruta, "rb") as f:
        return etree.XMLSchema(etree.parse(f, parser, base_url=ruta))


def validar_xsd(xml_firmado: str, tipo_documento: str) -> None:
    """
    Valida el XML firmado contra el XSD oficial (los XSD de Hacienda exigen
    ds:Signature, por eso se valida después de firmar). No hace nada si
    XSD_DIR no está configurado.
    """
    xsd_dir = get_settings().XSD_DIR
    if not xsd_dir:
        return
    ruta = os.path.join(xsd_dir, DOCUMENTOS[tipo_documento][2])
    if not os.path.isfile(ruta):
        raise XMLValidacionError(f"No se encontró el XSD {ruta}")

    schema = _cargar_xsd(ruta)
    doc = etree.fromstring(xml_firmado.encode("utf-8"), parser_seguro())
    if not schema.validate(doc):
        errores = "; ".join(f"línea {e.line}: {e.message}" for e in list(schema.error_log)[:10])
        raise XMLValidacionError(f"El XML no cumple el XSD oficial: {errores}")
