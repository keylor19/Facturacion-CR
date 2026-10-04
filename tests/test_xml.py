from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from lxml import etree
from pydantic import ValidationError

from api.models.schemas import FacturaRequest, MensajeReceptorRequest
from api.services.xml_generator import generar_xml, generar_mensaje_receptor, XMLValidacionError
from api.services.xml_seguro import parsear
from tests.conftest import factura_payload, persona_emisor_prueba

CONSECUTIVO = "00100001010000000001"
CLAVE = "506" + "250826" + "003101123456" + CONSECUTIVO + "1" + "12345678"
FECHA = datetime(2026, 8, 25, 21, 30, tzinfo=ZoneInfo("America/Costa_Rica"))


def _generar(**cambios):
    datos = FacturaRequest(**factura_payload(**cambios))
    xml, lineas, totales = generar_xml(CLAVE, CONSECUTIVO, FECHA, persona_emisor_prueba(), datos)
    return parsear(xml), lineas, totales


def _texto(root, ruta):
    """_texto(root, "Emisor/Nombre") ignorando el namespace."""
    el = root.find("/".join("{*}" + parte for parte in ruta.split("/")))
    return el.text if el is not None else None


def _hijos(el):
    return [etree.QName(h).localname for h in el]


def _d(root, ruta):
    return Decimal(_texto(root, ruta))


def test_orden_de_encabezado_v44():
    root, _, _ = _generar()
    assert etree.QName(root).localname == "FacturaElectronica"
    assert etree.QName(root).namespace.endswith("/v4.4/facturaElectronica")
    assert _hijos(root) == [
        "Clave", "ProveedorSistemas", "CodigoActividadEmisor", "NumeroConsecutivo",
        "FechaEmision", "Emisor", "Receptor", "CondicionVenta", "DetalleServicio", "ResumenFactura",
    ]


def test_fecha_con_zona_de_costa_rica():
    root, _, _ = _generar()
    assert _texto(root, "FechaEmision") == "2026-08-25T21:30:00-06:00"


def test_emisor_completo():
    root, _, _ = _generar()
    assert _hijos(root.find("{*}Emisor")) == ["Nombre", "Identificacion", "Ubicacion", "CorreoElectronico"]
    assert _texto(root, "Emisor/Ubicacion/OtrasSenas") == "Frente al parque"
    assert _texto(root, "CodigoActividadEmisor") == "620100"


def test_actividad_alternativa_del_emisor():
    root, _, _ = _generar(codigo_actividad_emisor="749001")
    assert _texto(root, "CodigoActividadEmisor") == "749001"


def test_lineas_y_totales():
    root, lineas, t = _generar()
    l1, l2 = root.findall("{*}DetalleServicio/{*}LineaDetalle")

    assert _hijos(l1) == [
        "NumeroLinea", "CodigoCABYS", "Cantidad", "UnidadMedida", "Detalle", "PrecioUnitario",
        "MontoTotal", "Descuento", "SubTotal", "BaseImponible", "Impuesto",
        "ImpuestoAsumidoEmisorFabrica", "ImpuestoNeto", "MontoTotalLinea",
    ]
    # Línea 1: 2 x 50 000 - 10 000 de descuento = 90 000; IVA 13% = 11 700
    assert Decimal(l1.find("{*}SubTotal").text) == Decimal("90000")
    assert l1.find("{*}Impuesto/{*}CodigoTarifaIVA").text == "08"
    assert Decimal(l1.find("{*}Impuesto/{*}Monto").text) == Decimal("11700")
    assert Decimal(l1.find("{*}MontoTotalLinea").text) == Decimal("101700")
    assert Decimal(l2.find("{*}Impuesto/{*}Monto").text) == 0

    assert t.serv_gravados == Decimal("100000")
    assert t.merc_exentas == Decimal("15000")
    assert t.venta == Decimal("115000")
    assert t.descuentos == Decimal("10000")
    assert t.venta_neta == Decimal("105000")
    assert t.impuesto == Decimal("11700")
    assert t.comprobante == Decimal("116700")

    resumen = root.find("{*}ResumenFactura")
    assert _d(root, "ResumenFactura/TotalComprobante") == Decimal("116700")
    assert _texto(root, "ResumenFactura/MedioPago/TipoMedioPago") == "01"
    assert _d(root, "ResumenFactura/MedioPago/TotalMedioPago") == Decimal("116700")
    assert _hijos(resumen)[-1] == "TotalComprobante"
    assert root.find("{*}MedioPago") is None  # en v4.4 va dentro del resumen
    desglose = {d.find("{*}CodigoTarifaIVA").text: Decimal(d.find("{*}TotalMontoImpuesto").text)
                for d in resumen.findall("{*}TotalDesgloseImpuesto")}
    assert desglose == {"08": Decimal("11700"), "10": Decimal("0")}


def test_exoneracion_parcial():
    payload = factura_payload()
    payload["productos"][0]["exoneracion"] = {
        "tipo_documento": "04", "numero_documento": "AL-00012345-24", "nombre_institucion": "01",
        "fecha_emision": "2026-01-10T08:00:00", "tarifa_exonerada": "6.5",
    }
    datos = FacturaRequest(**payload)
    xml, lineas, t = generar_xml(CLAVE, CONSECUTIVO, FECHA, persona_emisor_prueba(), datos)
    root = parsear(xml)
    linea = root.find("{*}DetalleServicio/{*}LineaDetalle")
    exo = linea.find("{*}Impuesto/{*}Exoneracion")
    assert _hijos(exo) == ["TipoDocumentoEX1", "NumeroDocumento", "NombreInstitucion", "FechaEmisionEX",
                           "TarifaExonerada", "MontoExoneracion"]
    # Base 90 000: IVA 11 700, exonerado 6.5% = 5 850, neto 5 850
    assert Decimal(exo.find("{*}MontoExoneracion").text) == Decimal("5850")
    assert Decimal(linea.find("{*}ImpuestoNeto").text) == Decimal("5850")
    # La mitad de la venta (6.5/13) queda exonerada
    assert t.serv_exonerado == Decimal("50000")
    assert t.serv_gravados == Decimal("50000")
    assert t.impuesto == Decimal("5850")
    assert t.comprobante == Decimal("110850")


def test_exoneracion_mayor_a_la_tarifa_falla():
    payload = factura_payload()
    payload["productos"][0]["codigo_tarifa_iva"] = "04"
    payload["productos"][0]["exoneracion"] = {
        "tipo_documento": "04", "numero_documento": "AL-1", "nombre_institucion": "01",
        "fecha_emision": "2026-01-10T08:00:00", "tarifa_exonerada": "13",
    }
    with pytest.raises(ValidationError):
        FacturaRequest(**payload)


def test_impuesto_selectivo_forma_parte_de_la_base_del_iva():
    payload = factura_payload()
    payload["productos"] = [{
        "codigo_cabys": "2211000000100", "descripcion": "Bebida", "cantidad": "1", "precio_unitario": "1000",
        "impuestos": [
            {"codigo": "02", "tarifa": "10"},
            {"codigo": "01", "codigo_tarifa_iva": "08"},
        ],
    }]
    root, lineas, t = _generar(productos=payload["productos"])
    linea = root.find("{*}DetalleServicio/{*}LineaDetalle")
    assert Decimal(linea.find("{*}BaseImponible").text) == Decimal("1100")  # 1000 + selectivo 100
    montos = [Decimal(i.find("{*}Monto").text) for i in linea.findall("{*}Impuesto")]
    assert montos == [Decimal("100"), Decimal("143")]
    assert t.impuesto == Decimal("243")
    assert t.comprobante == Decimal("1243")


def test_otros_cargos_por_porcentaje():
    root, _, t = _generar(otros_cargos=[{"tipo_documento": "06", "detalle": "Impuesto de servicio 10%", "porcentaje": "10"}])
    assert t.otros_cargos == Decimal("10500")  # 10% de 105 000
    assert _hijos(root)[-2:] == ["OtrosCargos", "ResumenFactura"]
    assert _d(root, "OtrosCargos/MontoCargo") == Decimal("10500")
    assert _d(root, "ResumenFactura/TotalOtrosCargos") == Decimal("10500")
    assert _d(root, "ResumenFactura/TotalComprobante") == Decimal("127200")


def test_moneda_extranjera_usa_tipo_de_cambio_real():
    root, _, _ = _generar(moneda="USD", tipo_cambio="512.35")
    assert _texto(root, "ResumenFactura/CodigoTipoMoneda/TipoCambio") == "512.35000"


def test_tiquete_sin_receptor():
    root, _, _ = _generar(tipo_documento="04", receptor=None)
    assert etree.QName(root).localname == "TiqueteElectronico"
    assert root.find("{*}Receptor") is None


def test_factura_requiere_receptor():
    with pytest.raises(ValidationError):
        FacturaRequest(**factura_payload(receptor=None))


def test_nota_credito_requiere_y_usa_referencia():
    with pytest.raises(ValidationError):
        FacturaRequest(**factura_payload(tipo_documento="03"))

    root, _, _ = _generar(tipo_documento="03", referencia={
        "tipo_documento": "01", "numero": "5" * 50, "fecha_emision": "2026-08-20T10:00:00",
        "codigo": "01", "razon": "Anula factura",
    })
    assert etree.QName(root).localname == "NotaCreditoElectronica"
    assert _texto(root, "InformacionReferencia/FechaEmisionIR") == "2026-08-20T10:00:00-06:00"


def test_factura_de_compra_invierte_emisor_y_receptor():
    proveedor = {"nombre": "Proveedor informal", "tipo_identificacion": "01", "numero_identificacion": "206540321",
                 "ubicacion": {"provincia": "2", "canton": "01", "distrito": "01", "otras_senas": "Alajuela"}}
    referencia = {"tipo_documento": "14", "numero": "00100001010000000001", "fecha_emision": "2026-08-20T10:00:00", "codigo": "04",
                  "razon": "Compra a contribuyente de régimen especial"}
    with pytest.raises(ValidationError):
        FacturaRequest(**factura_payload(tipo_documento="08", receptor=None))
    with pytest.raises(ValidationError, match="referencia"):
        FacturaRequest(**factura_payload(tipo_documento="08", receptor=None, proveedor=proveedor))

    root, _, _ = _generar(tipo_documento="08", receptor=None, proveedor=proveedor, referencia=referencia)
    assert etree.QName(root).localname == "FacturaElectronicaCompra"
    assert _texto(root, "Emisor/Identificacion/Numero") == "206540321"
    assert _texto(root, "Receptor/Identificacion/Numero") == "3101123456"
    assert _texto(root, "CodigoActividadReceptor") == "620100"
    assert root.find("{*}CodigoActividadEmisor") is None
    assert root.find(".//{*}ImpuestoAsumidoEmisorFabrica") is None


def test_factura_de_exportacion():
    receptor = {"nombre": "ACME Corp", "identificacion_extranjero": "US123456", "otras_senas_extranjero": "Miami, FL"}
    payload = factura_payload(tipo_documento="09", receptor=receptor, moneda="USD", tipo_cambio="510")
    with pytest.raises(ValidationError, match="partida_arancelaria"):
        FacturaRequest(**payload)

    payload["productos"][1]["partida_arancelaria"] = "490199000000"
    datos = FacturaRequest(**payload)
    root = parsear(generar_xml(CLAVE, CONSECUTIVO, FECHA, persona_emisor_prueba(), datos)[0])
    assert etree.QName(root).localname == "FacturaElectronicaExportacion"
    # En v4.4 el extranjero se identifica con tipo 05
    assert _texto(root, "Receptor/Identificacion/Tipo") == "05"
    assert _texto(root, "Receptor/Identificacion/Numero") == "US123456"
    assert root.find(".//{*}BaseImponible") is None
    assert root.find(".//{*}TotalExonerado") is None
    servicio, libro = root.findall("{*}DetalleServicio/{*}LineaDetalle")
    assert servicio.find("{*}PartidaArancelaria") is None
    assert _hijos(libro)[:3] == ["NumeroLinea", "PartidaArancelaria", "CodigoCABYS"]


def test_varios_medios_de_pago_deben_sumar_el_total():
    with pytest.raises(XMLValidacionError):
        _generar(medios_pago=[{"tipo": "01", "monto": "100"}, {"tipo": "02", "monto": "100"}])

    root, _, _ = _generar(medios_pago=[{"tipo": "01", "monto": "16700"}, {"tipo": "06", "monto": "100000"}])
    assert len(root.findall("{*}ResumenFactura/{*}MedioPago")) == 2


def test_emisor_incompleto_falla():
    datos = FacturaRequest(**factura_payload())
    with pytest.raises(XMLValidacionError, match="codigo_actividad"):
        generar_xml(CLAVE, CONSECUTIVO, FECHA, persona_emisor_prueba(codigo_actividad=""), datos)


@pytest.mark.parametrize("tipo,numero", [("01", "12345"), ("02", "12345678901"), ("01", "11234567A")])
def test_identificacion_receptor_invalida(tipo, numero):
    payload = factura_payload()
    payload["receptor"].update(tipo_identificacion=tipo, numero_identificacion=numero)
    with pytest.raises(ValidationError):
        FacturaRequest(**payload)


def test_mensaje_receptor():
    xml = generar_mensaje_receptor(
        clave_documento="5" * 50, cedula_proveedor="3101999999", fecha=FECHA, mensaje="1",
        detalle_mensaje=None, monto_total_impuesto=Decimal("130"), codigo_actividad="620100",
        condicion_impuesto="01", monto_impuesto_acreditar=Decimal("130"), monto_gasto_aplicable=None,
        total_factura=Decimal("1130"), cedula_receptor="3101123456", consecutivo_receptor="00100001050000000001",
    )
    root = parsear(xml)
    assert etree.QName(root).namespace.endswith("/v4.4/mensajeReceptor")
    assert _hijos(root) == [
        "Clave", "NumeroCedulaEmisor", "FechaEmisionDoc", "Mensaje", "MontoTotalImpuesto", "CodigoActividad",
        "CondicionImpuesto", "MontoTotalImpuestoAcreditar", "TotalFactura", "NumeroCedulaReceptor",
        "NumeroConsecutivoReceptor",
    ]


def test_rechazo_requiere_detalle():
    with pytest.raises(ValidationError):
        MensajeReceptorRequest(mensaje="3")


def test_parser_rechaza_entidades_externas():
    xxe = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'
    root = parsear(xxe)
    assert "root:" not in etree.tostring(root).decode()


# --- Cálculos especiales -------------------------------------------------------

def _una_linea(**extra):
    linea = {"codigo_cabys": "2399999009900", "descripcion": "X", "cantidad": "1", "precio_unitario": "1000"}
    linea.update(extra)
    return [linea]


def test_base_iva_solo_incluye_impuestos_indicados_por_hacienda():
    # Combustibles (03) y tabaco (06) NO forman parte de la base del IVA; selectivo (02) sí.
    _, lineas, _ = _generar(productos=_una_linea(impuestos=[
        {"codigo": "02", "tarifa": "10"},
        {"codigo": "06", "monto": "50", "datos_especificos": {"impuesto_unidad": "50"}},
        {"codigo": "01", "codigo_tarifa_iva": "08"},
    ]))
    assert lineas[0].base_imponible == Decimal("1100")          # 1000 + selectivo 100
    iva = [i for i in lineas[0].impuestos if i.codigo == "01"][0]
    assert iva.monto == Decimal("143")


def test_no_sujeto_va_a_totales_no_sujetos():
    root, _, t = _generar(productos=_una_linea(no_sujeto=True, es_servicio=True))
    assert t.serv_no_sujeto == Decimal("1000")
    assert t.impuesto == 0 and t.comprobante == Decimal("1000")
    assert _d(root, "ResumenFactura/TotalNoSujeto") == Decimal("1000")


def test_impuesto_asumido_por_el_emisor_no_se_cobra():
    root, lineas, t = _generar(productos=_una_linea(impuesto_asumido_emisor=True))
    assert lineas[0].impuesto_bruto == Decimal("130")
    assert lineas[0].impuesto_neto == 0
    assert t.comprobante == Decimal("1000")
    assert _d(root, "DetalleServicio/LineaDetalle/ImpuestoAsumidoEmisorFabrica") == Decimal("130")
    assert _d(root, "ResumenFactura/TotalImpAsumEmisorFabrica") == Decimal("130")


def test_iva_cobrado_en_fabrica():
    _, lineas, t = _generar(productos=_una_linea(iva_cobrado_fabrica="01"))
    assert lineas[0].impuesto_asumido == Decimal("130") and t.impuesto == 0
    _, lineas, t = _generar(productos=_una_linea(iva_cobrado_fabrica="02"))
    assert t.merc_exentas == Decimal("1000") and t.impuesto == 0


def test_bienes_usados_usa_factor():
    _, lineas, _ = _generar(productos=_una_linea(
        impuestos=[{"codigo": "08", "codigo_tarifa_iva": "08", "factor_calculo_iva": "0.0485"}]))
    assert lineas[0].impuesto_neto == Decimal("48.5")


def test_bienes_usados_sin_factor_falla():
    with pytest.raises(ValidationError, match="factor"):
        FacturaRequest(**factura_payload(productos=_una_linea(impuestos=[{"codigo": "08", "codigo_tarifa_iva": "08"}])))


def test_iva_devuelto_resta_del_total():
    _, _, t = _generar(tipo_documento="04", receptor=None, iva_devuelto="1000")
    assert t.comprobante == Decimal("116700") - Decimal("1000")


def test_contingencia_requiere_referencia_al_provisional():
    with pytest.raises(ValidationError, match="provisional"):
        FacturaRequest(**factura_payload(situacion="2", fecha_emision="2026-09-20T10:00:00"))
    with pytest.raises(ValidationError, match="fecha_emision"):
        FacturaRequest(**factura_payload(situacion="3"))
    with pytest.raises(ValidationError, match="fecha_emision"):
        FacturaRequest(**factura_payload(fecha_emision="2026-09-20T10:00:00"))


# --- Reglas verificadas contra el sandbox de Hacienda (2026-10-02) ------------

@pytest.mark.parametrize("codigo", ["01", "11"])
def test_tarifas_01_y_11_son_no_sujetas(codigo):
    # Hacienda clasifica estas tarifas como NO SUJETAS aunque la línea no lo indique
    root, _, t = _generar(productos=_una_linea(codigo_tarifa_iva=codigo, es_servicio=True))
    assert t.serv_no_sujeto == Decimal("1000") and t.serv_gravados == 0
    assert _d(root, "ResumenFactura/TotalNoSujeto") == Decimal("1000")


def test_no_sujeto_usa_tarifa_01_por_defecto():
    root, _, _ = _generar(productos=_una_linea(no_sujeto=True))
    assert _texto(root, "DetalleServicio/LineaDetalle/Impuesto/CodigoTarifaIVA") == "01"


def test_tarifa_05_solo_en_notas():
    with pytest.raises(ValidationError, match="transitorio"):
        FacturaRequest(**factura_payload(productos=_una_linea(codigo_tarifa_iva="05")))
    FacturaRequest(**factura_payload(tipo_documento="03", productos=_una_linea(codigo_tarifa_iva="05"), referencia={
        "tipo_documento": "01", "numero": "5" * 50, "fecha_emision": "2026-08-20T10:00:00", "codigo": "01", "razon": "x"}))


def test_exportacion_exige_tarifa_10_para_exentos():
    receptor = {"nombre": "ACME", "identificacion_extranjero": "US1"}
    with pytest.raises(ValidationError, match="tarifa 10"):
        FacturaRequest(**factura_payload(tipo_documento="09", receptor=receptor, moneda="USD", tipo_cambio="500",
                                         productos=_una_linea(codigo_tarifa_iva="01", es_servicio=True)))


def test_factura_de_compra_exige_numero_de_referencia():
    proveedor = {"nombre": "ICE", "tipo_identificacion": "02", "numero_identificacion": "4000042139"}
    with pytest.raises(ValidationError, match="numero"):
        FacturaRequest(**factura_payload(tipo_documento="08", receptor=None, proveedor=proveedor, referencia={
            "tipo_documento": "14", "fecha_emision": "2026-08-20T10:00:00", "codigo": "04"}))
