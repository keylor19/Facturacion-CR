"""Administración de emisores, certificados, credenciales y API keys."""
from api.models.database import Emisor
from api.services import emisores
from tests.conftest import crear_p12, CERT_PASSWORD, factura_payload

EMISOR = {
    "tipo_identificacion": "02", "numero_identificacion": "3101555555", "nombre": "Nueva S.A.",
    "codigo_actividad": "620100", "correo": "info@nueva.cr", "provincia": "1", "canton": "01",
    "distrito": "01", "otras_senas": "San José",
}


def test_flujo_completo_de_alta(admin, db, cola):
    r = admin.post("/api/v1/emisores", json=EMISOR)
    assert r.status_code == 201, r.text
    emisor_id = r.json()["id"]
    assert r.json()["tiene_certificado"] is False
    assert admin.post("/api/v1/emisores", json=EMISOR).status_code == 409  # duplicado

    r = admin.put(
        f"/api/v1/emisores/{emisor_id}/certificado",
        files={"archivo": ("cert.p12", crear_p12("3101555555"), "application/x-pkcs12")},
        data={"password": CERT_PASSWORD},
    )
    assert r.status_code == 200, r.text
    assert r.json()["advertencias"] == []

    r = admin.put(f"/api/v1/emisores/{emisor_id}/credenciales-hacienda",
                  json={"usuario": "cpj-3-101-555555@stag.comprobanteselectronicos.go.cr", "password": "x"})
    assert r.status_code == 200

    # Los secretos quedan cifrados en la base de datos
    e = db.get(Emisor, emisor_id)
    p12_claro, _ = emisores.certificado(e)
    assert e.cert_p12_cifrado != p12_claro and p12_claro not in e.cert_p12_cifrado
    assert e.hacienda_password_cifrado != b"x"
    assert emisores.credenciales(e)[1] == "x"

    r = admin.post("/api/v1/api-keys", json={"nombre": "POS", "emisor_id": emisor_id})
    assert r.status_code == 201
    llave = r.json()["api_key"]
    assert llave.startswith("fcr_")

    # Sin paquete de documentos no puede facturar; se le vende uno
    assert admin.post("/api/v1/facturas", json=factura_payload(), headers={"X-API-Key": llave}).status_code == 402
    assert admin.post(f"/api/v1/emisores/{emisor_id}/paquetes",
                      json={"documentos": 100, "precio": "5000", "referencia_pago": "SINPE 1"}).status_code == 201
    r = admin.post("/api/v1/facturas", json=factura_payload(), headers={"X-API-Key": llave})
    assert r.status_code == 202, r.text
    assert r.headers["X-Documentos-Disponibles"] == "99"

    # La llave no se vuelve a mostrar y se puede revocar
    listado = admin.get(f"/api/v1/api-keys?emisor_id={emisor_id}").json()
    assert listado[0]["api_key"] is None
    assert admin.delete(f"/api/v1/api-keys/{listado[0]['id']}").status_code == 204
    assert admin.get("/api/v1/facturas", headers={"X-API-Key": llave}).status_code == 401


def test_certificado_invalido_o_contrasena_incorrecta(admin):
    emisor_id = admin.post("/api/v1/emisores", json=EMISOR).json()["id"]
    r = admin.put(f"/api/v1/emisores/{emisor_id}/certificado",
                  files={"archivo": ("c.p12", crear_p12("3101555555"), "application/x-pkcs12")},
                  data={"password": "mala"})
    assert r.status_code == 422
    r = admin.put(f"/api/v1/emisores/{emisor_id}/certificado",
                  files={"archivo": ("c.p12", b"no es un p12", "application/x-pkcs12")},
                  data={"password": CERT_PASSWORD})
    assert r.status_code == 422


def test_advierte_si_el_certificado_es_de_otra_persona(admin):
    emisor_id = admin.post("/api/v1/emisores", json=EMISOR).json()["id"]
    r = admin.put(f"/api/v1/emisores/{emisor_id}/certificado",
                  files={"archivo": ("c.p12", crear_p12("3101999999"), "application/x-pkcs12")},
                  data={"password": CERT_PASSWORD})
    assert r.status_code == 200
    assert r.json()["advertencias"]


def test_webhook_solo_https_y_devuelve_secreto(admin):
    emisor_id = admin.post("/api/v1/emisores", json=EMISOR).json()["id"]
    assert admin.put(f"/api/v1/emisores/{emisor_id}/webhook", json={"url": "http://x.com/h"}).status_code == 422
    r = admin.put(f"/api/v1/emisores/{emisor_id}/webhook", json={"url": "https://erp.example.com/hook"})
    assert r.json()["secreto"].startswith("whsec_")


def test_actualizar_y_desactivar_emisor(admin, client, emisor):
    r = admin.patch(f"/api/v1/emisores/{emisor.id}", json={"nombre_comercial": "Pruebitas", "activo": False})
    assert r.json()["nombre_comercial"] == "Pruebitas"
    assert client.post("/api/v1/facturas", json=factura_payload()).status_code == 403


def test_health_detalle_lista_certificados(admin, emisor):
    r = admin.get("/api/v1/health/detalle")
    assert r.json()["certificados"][0]["estado"] == "ok"
