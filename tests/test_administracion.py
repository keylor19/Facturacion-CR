"""Panel del administrador: comprobante de cada venta, diagnóstico de empresas y tablero."""
from datetime import timedelta
from decimal import Decimal

from api.models.database import EstadoFactura, Factura, FacturaEvento, Paquete, utcnow
from tests.conftest import crear_emisor

CABYS = "8314100000000"


def _plataforma_y_cliente(db, admin, **ajustes):
    plataforma = crear_emisor(db, numero="3101000001", nombre="Plataforma S.A.")
    cliente = crear_emisor(db, numero="3101000002", nombre="Cliente Comprador S.A.")
    r = admin.put("/api/v1/admin/ajustes", json={"emisor_ventas_id": plataforma.id, "codigo_cabys": CABYS, **ajustes})
    assert r.status_code == 200, r.text
    return plataforma, cliente


def test_venta_de_paquete_emite_factura_al_cliente(db, admin, cola):
    plataforma, cliente = _plataforma_y_cliente(db, admin)
    r = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes",
                   json={"documentos": 500, "precio": "11300", "referencia_pago": "SINPE 123", "medio_pago": "06"})
    assert r.status_code == 201, r.text
    comp = r.json()["comprobante"]
    assert comp["tipo_documento"] == "01" and comp["emisor_id"] == plataforma.id

    f = db.get(Factura, comp["factura_id"])
    assert f.receptor_identificacion == cliente.numero_identificacion and f.receptor_correo == cliente.correo
    # El precio del plan incluye IVA: 10 000 + 1 300
    assert f.monto_total == Decimal("11300") and f.monto_impuesto == Decimal("1300")
    assert f.json_original["medios_pago"][0]["tipo"] == "06"
    assert "500 documentos" in f.detalles[0].descripcion
    assert ("enviar_documento", ("factura", f.id)) in cola

    # Reintentar no duplica (referencia externa por venta)
    paquete_id = r.json()["paquete"]["id"]
    r = admin.post(f"/api/v1/admin/ventas/paquete/{paquete_id}/comprobante", json={})
    assert r.status_code == 200 and r.json()["factura_id"] == f.id
    assert db.query(Factura).filter_by(emisor_id=plataforma.id).count() == 1

    compras = admin.get(f"/api/v1/admin/emisores/{cliente.id}/compras").json()
    assert compras[0]["clase"] == "paquete" and compras[0]["comprobante"]["factura_id"] == f.id


def test_tiquete_precio_sin_iva_y_mensualidad(db, admin):
    plataforma, cliente = _plataforma_y_cliente(db, admin, precio_incluye_iva=False, tipo_comprobante="04")
    r = admin.post(f"/api/v1/emisores/{cliente.id}/suscripciones",
                   json={"servicio": "facturacion_web", "meses": 3, "precio": "10000"})
    assert r.status_code == 201, r.text
    f = db.get(Factura, r.json()["comprobante"]["factura_id"])
    assert f.tipo_documento == "04" and f.monto_total == Decimal("11300")
    assert "3 mes(es)" in f.detalles[0].descripcion


def test_sin_comprobante_cortesia_o_sin_configurar(db, admin):
    cliente = crear_emisor(db, numero="3101000002", nombre="Cliente S.A.")
    # Cortesía (precio 0): nunca se factura
    r = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 10, "precio": "0"})
    assert r.json()["comprobante"] is None
    # Sin configurar quién factura: la venta se registra y se informa el motivo
    r = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 10, "precio": "5000"})
    assert r.status_code == 201 and "Configure" in r.json()["comprobante"]["error"]
    # Venta marcada "sin comprobante"
    r = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 10, "precio": "5000", "comprobante": "ninguno"})
    assert r.json()["comprobante"] is None


def test_comprobante_falla_si_la_plataforma_no_tiene_certificado(db, admin):
    plataforma = crear_emisor(db, numero="3101000001", nombre="Plataforma S.A.", con_certificado=False)
    cliente = crear_emisor(db, numero="3101000002", nombre="Cliente S.A.")
    admin.put("/api/v1/admin/ajustes", json={"emisor_ventas_id": plataforma.id, "codigo_cabys": CABYS})
    r = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 10, "precio": "5000", "comprobante": "01"})
    assert r.status_code == 201
    assert "certificado" in r.json()["comprobante"]["error"]
    assert db.get(Paquete, r.json()["paquete"]["id"]).comprobante_error


def test_ajustes_validan(db, admin):
    e = crear_emisor(db)
    assert admin.put("/api/v1/admin/ajustes", json={"emisor_ventas_id": e.id}).status_code == 422   # falta CABYS
    assert admin.put("/api/v1/admin/ajustes", json={"emisor_ventas_id": None}).status_code == 200
    assert admin.get("/api/v1/admin/ajustes").json()["emisor_ventas_id"] is None


def test_diagnostico_explica_los_problemas(db, admin):
    sin_nada = crear_emisor(db, numero="3101000003", nombre="Sin Certificado S.A.", con_certificado=False, documentos=0)
    titulos = [a["titulo"] for a in admin.get(f"/api/v1/admin/emisores/{sin_nada.id}/diagnostico").json()]
    assert "Sin certificado digital" in titulos and "Sin credenciales del API de Hacienda" in titulos
    assert "Sin documentos" in titulos

    ok = crear_emisor(db, numero="3101000004", nombre="Rechazos S.A.")
    rechazada = Factura(emisor_id=ok.id, clave="5" * 50, numero_consecutivo="00100001010000000001", tipo_documento="01",
                        fecha_emision=utcnow(), moneda="CRC", monto_total=1000, estado=EstadoFactura.RECHAZADO,
                        mensaje_hacienda="El receptor no está inscrito en el Registro Único Tributario")
    atascada = Factura(emisor_id=ok.id, clave="6" * 50, numero_consecutivo="00100001010000000002", tipo_documento="01",
                       fecha_emision=utcnow(), moneda="CRC", monto_total=1000, estado=EstadoFactura.ERROR_COMUNICACION,
                       created_at=utcnow() - timedelta(hours=2))
    db.add_all([rechazada, atascada])
    db.flush()
    db.add(FacturaEvento(factura_id=atascada.id, evento="ERROR_ENVIO", detalle="401 Unauthorized: credenciales inválidas"))
    db.commit()
    alertas = admin.get(f"/api/v1/admin/emisores/{ok.id}/diagnostico").json()
    rech = next(a for a in alertas if "rechazado" in a["titulo"])
    assert rech["nivel"] == "error" and "Registro Único Tributario" in rech["detalle"]
    sin_conf = next(a for a in alertas if "sin confirmar" in a["titulo"])
    assert "401 Unauthorized" in sin_conf["detalle"]
    assert alertas[0]["nivel"] == "error"   # ordenadas de más grave a más leve


def test_tablero(db, admin):
    plataforma, cliente = _plataforma_y_cliente(db, admin)
    admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 100, "precio": "11300", "dias_vigencia": 5})
    t = admin.get("/api/v1/admin/tablero").json()
    assert t["empresas_activas"] == 2
    assert Decimal(t["ventas_mes"]["CRC"]) == Decimal("11300") and t["documentos_vendidos_mes"] == 100
    assert len(t["ventas_por_mes"]) == 6 and t["ventas_por_mes"][-1]["CRC"] == "11300.00"
    assert any(v["tipo"] == "Paquete" and v["empresa"] == cliente.nombre for v in t["vencimientos"])
    assert t["ultimas_ventas"][0]["comprobante"]["factura_id"]
    assert t["mejores_clientes"][0]["empresa"] == cliente.nombre


def test_solo_administradores(client):
    for ruta in ("/api/v1/admin/tablero", "/api/v1/admin/ajustes", "/api/v1/admin/diagnosticos"):
        assert client.get(ruta).status_code == 403, ruta


# --- Panel web opcional, regalía, avisos comerciales y contabilidad ---------------------

def test_empresa_nueva_nace_sin_panel_web(admin):
    datos = {"tipo_identificacion": "02", "numero_identificacion": "3101000009", "nombre": "Solo API S.A.",
             "codigo_actividad": "620100", "correo": "api@ejemplo.cr", "provincia": "1", "canton": "01",
             "distrito": "01", "otras_senas": "Centro"}
    r = admin.post("/api/v1/emisores", json=datos)
    assert r.status_code == 201, r.text
    assert r.json()["facturacion_web"] is False and r.json()["acceso_api"] is True


def test_panel_en_regalia(db, admin, monkeypatch):
    from config.settings import get_settings
    from api.services import suscripciones
    monkeypatch.setattr(get_settings(), "CONTROL_SUSCRIPCIONES", True)
    plataforma, cliente = _plataforma_y_cliente(db, admin)
    assert not suscripciones.activo(db, cliente, "facturacion_web")
    r = admin.post(f"/api/v1/emisores/{cliente.id}/suscripciones",
                   json={"servicio": "facturacion_web", "regalia": True, "precio": "50000"})
    assert r.status_code == 201, r.text
    assert r.json()["suscripcion"]["regalia"] is True and Decimal(r.json()["suscripcion"]["precio"]) == 0
    assert r.json()["servicio"]["regalia"] is True and r.json()["servicio"]["vence"] is None
    assert r.json()["comprobante"] is None   # una regalía no se factura
    db.expire_all()
    assert suscripciones.activo(db, cliente, "facturacion_web")
    # No aparece como "por vencer" en el tablero
    assert not any(v["tipo"] == "Mensualidad" for v in admin.get("/api/v1/admin/tablero").json()["vencimientos"])


def test_aviso_de_saldo_invita_a_comprar_y_copia_al_administrador(db, admin, monkeypatch):
    from config.settings import get_settings
    from workers import tasks
    cliente = crear_emisor(db, numero="3101000002", nombre="Cliente S.A.")
    admin.post("/api/v1/planes", json={"nombre": "Básico", "documentos": 500, "precio": "15000", "moneda": "CRC"})
    admin.put("/api/v1/admin/ajustes", json={"emisor_ventas_id": None, "instrucciones_pago": "SINPE Móvil 8888-8888",
                                           "contacto_ventas": "WhatsApp 8888-8888", "correo_avisos": "ventas@plataforma.cr"})
    monkeypatch.setattr(type(get_settings()), "smtp_configurado", property(lambda s: True))
    enviados = []
    monkeypatch.setattr(tasks.correo, "enviar", lambda msg: enviados.append(msg))
    r = tasks.notificar_saldo.run(cliente.id, "saldo.bajo", {"disponible": 20})
    assert "correo" in r["canales"] and "copia al administrador" in r["canales"]
    al_cliente, copia = enviados
    cuerpo = al_cliente.get_content()
    assert al_cliente["To"] == cliente.correo and al_cliente["Reply-To"] == "ventas@plataforma.cr"
    assert "quedan 20 documentos" in cuerpo and "Básico: 500 documentos" in cuerpo
    assert "SINPE Móvil 8888-8888" in cuerpo and "WhatsApp 8888-8888" in cuerpo
    assert copia["To"] == "ventas@plataforma.cr" and cliente.correo in copia.get_content()


def test_contabilidad_concilia_ventas_y_comprobantes(db, admin):
    plataforma, cliente = _plataforma_y_cliente(db, admin)
    admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 100, "precio": "11300"})
    admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 100, "precio": "5650", "comprobante": "ninguno"})
    admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 10, "precio": "0"})   # cortesía: no cuenta
    from api.services.fechas import ahora_cr
    hoy = ahora_cr()
    c = admin.get("/api/v1/admin/contabilidad", params={"anio": hoy.year, "mes": hoy.month}).json()
    assert c["emisor_ventas_id"] == plataforma.id and len(c["ventas"]) == 2
    assert Decimal(c["vendido"]["CRC"]) == Decimal("16950")
    assert c["en_proceso"] == 1 and c["sin_comprobante"] == 1 and c["aceptados"] == 0


# --- Correcciones de la revisión de noviembre 2026 ---

def test_venta_facturada_no_se_duplica_al_cambiar_quien_factura(db, admin):
    plataforma, cliente = _plataforma_y_cliente(db, admin)
    paquete_id = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes",
                            json={"documentos": 100, "precio": "5650"}).json()["paquete"]["id"]
    otra = crear_emisor(db, numero="3101000003", nombre="Otra Plataforma S.A.")
    admin.put("/api/v1/admin/ajustes", json={"emisor_ventas_id": otra.id, "codigo_cabys": CABYS})
    r = admin.post(f"/api/v1/admin/ventas/paquete/{paquete_id}/comprobante", json={})
    assert r.status_code == 200 and r.json()["emisor_id"] == plataforma.id
    assert db.query(Factura).filter(Factura.emisor_id == otra.id).count() == 0


def test_comprobante_rechazado_se_sustituye_con_codigo_16(db, admin):
    plataforma, cliente = _plataforma_y_cliente(db, admin)
    r = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 100, "precio": "5650"})
    rechazada = db.get(Factura, r.json()["comprobante"]["factura_id"])
    rechazada.estado = EstadoFactura.RECHAZADO
    db.commit()
    r = admin.post(f"/api/v1/admin/ventas/paquete/{r.json()['paquete']['id']}/comprobante", json={})
    assert r.status_code == 200, r.text
    nueva = db.get(Factura, r.json()["factura_id"])
    assert nueva.id != rechazada.id and nueva.codigo_referencia == "16" and nueva.referencia_clave == rechazada.clave
    assert "<TipoDocIR>10</TipoDocIR>" in nueva.xml_firmado


def test_anular_venta_con_comprobante_aceptado_avisa(db, admin):
    plataforma, cliente = _plataforma_y_cliente(db, admin)
    r = admin.post(f"/api/v1/emisores/{cliente.id}/paquetes", json={"documentos": 100, "precio": "5650"})
    f = db.get(Factura, r.json()["comprobante"]["factura_id"])
    f.estado = EstadoFactura.ACEPTADO
    db.commit()
    anulado = admin.post(f"/api/v1/paquetes/{r.json()['paquete']['id']}/anular").json()
    assert anulado["aviso_comprobante"]["factura_id"] == f.id
    hoy = utcnow()
    c = admin.get("/api/v1/admin/contabilidad", params={"anio": hoy.year, "mes": hoy.month}).json()
    fila = next(v for v in c["ventas"] if v["id"] == r.json()["paquete"]["id"])
    assert fila["anulada"] and fila["nota_credito_pendiente"]["consecutivo"] == f.numero_consecutivo
    assert c["vendido"] == {}


def test_meses_pagados_no_empiezan_despues_de_una_regalia(db, admin):
    cliente = crear_emisor(db, numero="3101000002", nombre="Cliente S.A.")
    admin.post(f"/api/v1/emisores/{cliente.id}/suscripciones", json={"servicio": "facturacion_web", "regalia": True})
    r = admin.post(f"/api/v1/emisores/{cliente.id}/suscripciones",
                   json={"servicio": "facturacion_web", "meses": 1, "precio": "0"})
    pagada = r.json()["suscripcion"]
    assert pagada["desde"][:4] == str(utcnow().year)
