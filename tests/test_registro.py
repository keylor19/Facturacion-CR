"""Autoservicio: cuenta (correo, Google, Microsoft), inscripción de la empresa y compras reportadas por el cliente."""
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from api.models.database import Emisor, Plan, Usuario
from api.services import administracion, correo, hacienda_publico, oauth, saldo, suscripciones, usuarios

PASSWORD = "Clave-Segura-2026"
CONTRIBUYENTE = {
    "nombre": "PANADERÍA LA ESPIGA S.A.", "tipoIdentificacion": "02",
    "situacion": {"estado": "Inscrito"}, "actividades": [{"codigo": 107101, "tipo": "P", "estado": "A"}],
}


@pytest.fixture
def correos(monkeypatch):
    from config.settings import get_settings
    enviados = []
    monkeypatch.setattr(get_settings(), "SMTP_HOST", "smtp.prueba.cr")
    monkeypatch.setattr(get_settings(), "SMTP_FROM", "facturas@prueba.cr")
    monkeypatch.setattr(correo, "enviar", lambda msg: enviados.append(msg))
    monkeypatch.setattr(hacienda_publico, "contribuyente", lambda ced: CONTRIBUYENTE)
    return enviados


def _abrir_inscripcion(db, documentos=20, dias=15, abierta=True):
    a = administracion.ajustes(db)
    a.autoregistro, a.prueba_documentos, a.prueba_dias = abierta, documentos, dias
    db.commit()


def _cuenta(**cambios):
    return {"tipo": "empresa", "nombre": "Ana Mora", "correo": "ana@espiga.cr", "password": PASSWORD,
            "acepto_terminos": True, **cambios}


def _empresa(**cambios):
    return {"tipo_identificacion": "02", "numero_identificacion": "3-101-777777", "nombre": "La Espiga",
            "codigo_actividad": "107101", "correo": "info@espiga.cr", "telefono": "88887777",
            "provincia": "1", "canton": "01", "distrito": "01", "otras_senas": "Del parque 100 m norte", **cambios}


def _entrar(app_client, email):
    token = app_client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _confirmar(app_client, correos):
    token = re.search(r"#/confirmar/([\w-]+)", correos[-1].get_content()).group(1)
    return app_client.post("/api/v1/registro/confirmar", json={"token": token})


def test_inscripcion_cerrada(db, app_client, correos):
    _abrir_inscripcion(db, abierta=False)
    assert app_client.get("/api/v1/registro").json()["disponible"] is False
    assert app_client.post("/api/v1/registro", json=_cuenta()).status_code == 403


def test_cuenta_y_luego_la_empresa_con_su_prueba(db, app_client, correos):
    _abrir_inscripcion(db)
    assert app_client.post("/api/v1/registro", json=_cuenta()).status_code == 201
    # Antes de confirmar el correo no puede entrar
    assert app_client.post("/api/v1/auth/login", json={"email": "ana@espiga.cr", "password": PASSWORD}).status_code == 401
    assert _confirmar(app_client, correos).status_code == 200
    assert _confirmar(app_client, correos).status_code == 404   # el enlace sirve una vez

    h = _entrar(app_client, "ana@espiga.cr")
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert yo["falta_empresa"] is True and yo["empresas"] == []
    # Actividad que no tiene en Hacienda: no
    assert app_client.post("/api/v1/registro/empresa", headers=h, json=_empresa(codigo_actividad="620100")).status_code == 422
    r = app_client.post("/api/v1/registro/empresa", headers=h, json=_empresa())
    assert r.status_code == 201, r.text
    emisor = db.query(Emisor).filter_by(numero_identificacion="3101777777").one()
    assert emisor.nombre == "PANADERÍA LA ESPIGA S.A." and emisor.activo and saldo.disponible(db, emisor.id) == 20
    assert suscripciones.activo(db, emisor, "facturacion_web")
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert yo["falta_empresa"] is False and yo["rol"] == "dueno" and yo["empresas"][0]["id"] == emisor.id
    assert app_client.post("/api/v1/registro/empresa", headers=h, json=_empresa()).status_code == 409   # ya tiene

    # El dueño inscribe a quien factura con él
    r = app_client.post("/api/v1/usuarios", headers=h, json={"email": "caja@espiga.cr", "nombre": "Caja",
                                                            "password": PASSWORD, "rol": "cajero"})
    assert r.status_code == 201 and r.json()["emisor_id"] == emisor.id


def test_cuenta_de_contador(db, app_client, correos):
    _abrir_inscripcion(db)
    app_client.post("/api/v1/registro", json=_cuenta(tipo="contador", correo="conta@despacho.cr"))
    _confirmar(app_client, correos)
    h = _entrar(app_client, "conta@despacho.cr")
    yo = app_client.get("/api/v1/auth/yo", headers=h).json()
    assert yo["es_contador"] is True and yo["falta_empresa"] is False
    assert app_client.post("/api/v1/registro/empresa", headers=h, json=_empresa()).status_code == 403


def test_inscripcion_rechaza_duplicados_y_no_inscritos(db, app_client, correos, emisor, monkeypatch):
    _abrir_inscripcion(db)
    assert app_client.post("/api/v1/registro", json=_cuenta()).status_code == 201
    assert app_client.post("/api/v1/registro", json=_cuenta()).status_code == 409   # mismo correo
    _confirmar(app_client, correos)
    h = _entrar(app_client, "ana@espiga.cr")
    # Una empresa ya inscrita no se vuelve a inscribir
    r = app_client.post("/api/v1/registro/empresa", headers=h, json=_empresa(numero_identificacion=emisor.numero_identificacion))
    assert r.status_code == 409
    monkeypatch.setattr(hacienda_publico, "contribuyente", lambda c: {**CONTRIBUYENTE, "situacion": {"estado": "No inscrito"}})
    r = app_client.post("/api/v1/registro/empresa", headers=h, json=_empresa())
    assert r.status_code == 422 and "inscrita" in r.json()["detail"]
    # Campo trampa lleno: responde igual pero no crea nada
    assert app_client.post("/api/v1/registro", json=_cuenta(correo="robot@x.cr", sitio_web="spam")).status_code == 201
    assert db.query(Usuario).filter_by(email="robot@x.cr").count() == 0


# --- Google y Microsoft -------------------------------------------------------------------------

class _Respuesta:
    def __init__(self, datos):
        self.datos = datos

    def raise_for_status(self):
        pass

    def json(self):
        return self.datos


def test_entrar_con_google(db, app_client, monkeypatch):
    from config.settings import get_settings
    _abrir_inscripcion(db)
    monkeypatch.setattr(get_settings(), "GOOGLE_CLIENT_ID", "cliente")
    monkeypatch.setattr(get_settings(), "GOOGLE_CLIENT_SECRET", "secreto")
    persona = {"sub": "g-123", "email": "luis@gmail.com", "email_verified": True, "name": "Luis Rojas"}
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **k: _Respuesta({"access_token": "acceso"}))
    monkeypatch.setattr(oauth.requests, "get", lambda *a, **k: _Respuesta(persona))
    assert app_client.get("/api/v1/registro").json()["proveedores"] == ["google"]

    def iniciar(tipo="empresa"):
        r = app_client.get("/api/v1/auth/oauth/google/inicio", params={"tipo": tipo}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("https://accounts.google.com/")
        return parse_qs(urlparse(r.headers["location"]).query)["state"][0]

    def volver(state):
        return app_client.get("/api/v1/auth/oauth/google/callback", params={"code": "c", "state": state},
                              follow_redirects=False).headers["location"]

    destino = volver(iniciar())
    assert destino.startswith("/panel/#/oauth/ses_")
    token = destino.rsplit("/", 1)[1]
    yo = app_client.get("/api/v1/auth/yo", headers={"Authorization": f"Bearer {token}"}).json()
    assert yo["usuario"]["email"] == "luis@gmail.com" and yo["falta_empresa"] is True
    assert volver(iniciar()).startswith("/panel/#/oauth/ses_")   # la segunda vez entra a la misma cuenta
    assert db.query(Usuario).filter_by(email="luis@gmail.com").count() == 1

    # State alterado o sin la cookie del mismo navegador: no sirve (evita entrar con la cuenta de otro)
    state = iniciar()
    assert volver(state[:-4] + "0000") == "/panel/#/oauth-error/estado"
    state = iniciar()
    app_client.cookies.clear()
    assert volver(state) == "/panel/#/oauth-error/estado"

    # Un administrador no entra con Google
    usuarios.crear_usuario(db, "jefe@gmail.com", "Jefe", PASSWORD, True, None)
    persona.update(sub="g-999", email="jefe@gmail.com")
    assert volver(iniciar()) == "/panel/#/oauth-error/administrador"


# --- Compras reportadas por el cliente ----------------------------------------------------

def test_compra_reportada_y_aprobada(db, emisor, client, admin):
    plan = Plan(nombre="Pyme", documentos=500, precio=Decimal("15000"), moneda="CRC", dias_vigencia=365, activo=True)
    db.add(plan)
    a = administracion.ajustes(db)
    a.precio_web_mensual = Decimal("5000")
    db.commit()
    antes = saldo.disponible(db, emisor.id)

    ops = client.get("/api/v1/compras/opciones").json()
    assert [p["nombre"] for p in ops["planes"]] == ["Pyme"] and ops["precio_web_mensual"] == "5000.00"
    r = client.post("/api/v1/compras", data={"plan_id": plan.id, "meses_web": "3", "medio_pago": "06", "referencia": "SINPE 9876"},
                    files={"comprobante": ("pago.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
    assert r.status_code == 201, r.text
    sol = r.json()
    assert Decimal(sol["monto"]) == Decimal("30000") and sol["estado"] == "PENDIENTE"   # 15 000 + 3 x 5 000
    # El cliente no puede inventar montos ni comprar planes inactivos o sin precio
    assert client.post("/api/v1/compras", data={"meses_web": "5", "referencia": "x123"}).status_code == 422

    pendientes = admin.get("/api/v1/admin/solicitudes", params={"estado": "PENDIENTE"}).json()
    assert [p["id"] for p in pendientes] == [sol["id"]]
    assert admin.get(f"/api/v1/admin/solicitudes/{sol['id']}/comprobante").content.startswith(b"\x89PNG")
    r = admin.post(f"/api/v1/admin/solicitudes/{sol['id']}/aprobar", json={})
    assert r.status_code == 200, r.text
    assert saldo.disponible(db, emisor.id) == antes + 500
    assert admin.post(f"/api/v1/admin/solicitudes/{sol['id']}/aprobar", json={}).status_code == 409


def test_compra_rechazada(db, emisor, client, admin):
    plan = Plan(nombre="Inicio", documentos=50, precio=Decimal("2500"), moneda="CRC", activo=True)
    db.add(plan)
    db.commit()
    sol = client.post("/api/v1/compras", data={"plan_id": plan.id, "referencia": "TRF-1"}).json()
    r = admin.post(f"/api/v1/admin/solicitudes/{sol['id']}/rechazar", json={"motivo": "No aparece el depósito"})
    assert r.status_code == 200 and r.json()["estado"] == "RECHAZADA"
    assert client.get("/api/v1/compras").json()[0]["motivo"] == "No aparece el depósito"
