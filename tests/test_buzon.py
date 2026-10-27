"""Recepción automática de facturas de proveedores por correo (IMAP simulado)."""
import imaplib
import io
import zipfile
from email.message import EmailMessage

import pytest

from api.models.database import BuzonCorreo
from api.services import buzon
from tests.test_recepcion import CLAVE_PROVEEDOR, xml_de_proveedor

URL = "/api/v1/buzon-correo"
CONFIG = {"servidor": "imap.ejemplo.com", "puerto": 993, "usuario": "facturas@pruebas.cr", "password": "clave-app"}


def _clave(n: int) -> str:
    return CLAVE_PROVEEDOR[:-9] + str(n).rjust(9, "0")


def _respuesta_hacienda(clave: str) -> bytes:
    return (f'<?xml version="1.0" encoding="UTF-8"?><MensajeHacienda xmlns="https://cdn.comprobanteselectronicos.go.cr/'
            f'xml-schemas/v4.4/mensajeHacienda"><Clave>{clave}</Clave><Mensaje>1</Mensaje></MensajeHacienda>').encode()


def _correo(*adjuntos: tuple[str, bytes]) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Factura electrónica"
    msg["From"] = "proveedor@ejemplo.com"
    msg.set_content("Adjunto la factura")
    for nombre, datos in adjuntos:
        tipo = ("application", "zip") if nombre.endswith(".zip") else ("application", "xml")
        msg.add_attachment(datos, maintype=tipo[0], subtype=tipo[1], filename=nombre)
    return msg.as_bytes()


def _zip(**archivos: bytes) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as z:
        for nombre, datos in archivos.items():
            z.writestr(nombre, datos)
    return salida.getvalue()


class ImapFalso:
    """Servidor IMAP en memoria: correos[uid] = bytes."""
    correos: dict[int, bytes] = {}
    password = "clave-app"
    marcados_leidos = False

    def __init__(self, servidor, puerto, ssl_context=None, timeout=None):
        pass

    def login(self, usuario, password):
        if password != self.password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, carpeta, readonly=False):
        if not readonly:
            ImapFalso.marcados_leidos = True
        return ("OK", [str(len(self.correos)).encode()]) if carpeta == '"INBOX"' else ("NO", [b"no existe"])

    def response(self, codigo):
        return ("OK", [b"7"])

    def uid(self, comando, *args):
        if comando == "SEARCH":
            criterio = args[-1]
            if criterio.startswith("UID "):
                desde = int(criterio.split()[1].split(":")[0])
                uids = [u for u in self.correos if u >= desde] or [max(self.correos)]
            else:
                uids = list(self.correos)
            return "OK", [" ".join(str(u) for u in sorted(uids)).encode()]
        uid = int(args[0])
        if "RFC822.SIZE" in args[1]:
            return "OK", [f"1 (UID {uid} RFC822.SIZE {len(self.correos[uid])})".encode()]
        return "OK", [(f"1 (UID {uid} BODY[] {{{len(self.correos[uid])}}}".encode(), self.correos[uid]), b")"]

    def logout(self):
        pass


@pytest.fixture
def imap(monkeypatch):
    monkeypatch.setattr(buzon, "validar_servidor", lambda servidor: None)
    monkeypatch.setattr(buzon.imaplib, "IMAP4_SSL", ImapFalso)
    ImapFalso.marcados_leidos = False
    ImapFalso.correos = {
        1: _correo(("factura.xml", xml_de_proveedor(clave=_clave(1))), ("respuesta.xml", _respuesta_hacienda(_clave(1)))),
        2: _correo(("comprobantes.zip", _zip(**{"f2.xml": xml_de_proveedor(clave=_clave(2)), "leeme.txt": b"hola"}))),
        3: _correo(("otra.xml", xml_de_proveedor(clave=_clave(3), receptor_numero="3101555555"))),   # no es para nosotros
        4: _correo(("factura.xml", xml_de_proveedor(clave=_clave(1)))),                              # repetida
    }
    return ImapFalso


def test_conectar_y_revisar(client, db, imap):
    r = client.put(URL, json=CONFIG)
    assert r.status_code == 200, r.text
    assert "password" not in r.json() and client.get(URL).json()["usuario"] == CONFIG["usuario"]

    r = client.post(f"{URL}/revisar")
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["correos"], res["importados"], res["repetidos"], res["ignorados"]) == (4, 2, 1, 1)
    assert res["buzon"]["documentos_importados"] == 2 and res["buzon"]["ultimo_error"] is None
    assert not imap.marcados_leidos   # el buzón se abre en solo lectura

    docs = {d["clave"]: d for d in client.get("/api/v1/recepcion").json()}
    assert set(docs) == {_clave(1), _clave(2)}
    assert all(d["origen"] == "correo" for d in docs.values())

    # Solo procesa lo nuevo
    assert client.post(f"{URL}/revisar").json()["correos"] == 0
    imap.correos[5] = _correo(("f5.xml", xml_de_proveedor(clave=_clave(5))))
    res = client.post(f"{URL}/revisar").json()
    assert (res["correos"], res["importados"]) == (1, 1)


def test_respuesta_de_hacienda_en_otro_correo(client, db, imap):
    from api.models.database import DocumentoRecibido
    imap.correos = {1: _correo(("f.xml", xml_de_proveedor(clave=_clave(8))))}
    client.put(URL, json=CONFIG)
    client.post(f"{URL}/revisar")
    imap.correos[2] = _correo(("respuesta.xml", _respuesta_hacienda(_clave(8))))
    client.post(f"{URL}/revisar")
    db.expire_all()
    doc = db.query(DocumentoRecibido).filter_by(clave=_clave(8)).one()
    assert "MensajeHacienda" in doc.xml_respuesta_proveedor


def test_password_incorrecta_y_carpeta_inexistente(client, imap):
    r = client.put(URL, json={**CONFIG, "password": "otra"})
    assert r.status_code == 422 and "contraseña de aplicación" in r.json()["detail"]
    r = client.put(URL, json={**CONFIG, "carpeta": "Facturas"})
    assert r.status_code == 422 and "carpeta" in r.json()["detail"]
    assert client.get(URL).json() is None
    # Editar sin contraseña conserva la guardada
    assert client.put(URL, json=CONFIG).status_code == 200
    assert client.put(URL, json={**CONFIG, "password": None, "activo": False}).json()["activo"] is False


def test_error_queda_registrado_en_el_buzon(client, db, imap):
    from workers.tasks import revisar_buzones
    client.put(URL, json=CONFIG)
    imap.password = "cambiada-en-el-proveedor"
    try:
        resultado = revisar_buzones()
    finally:
        imap.password = "clave-app"
    assert list(resultado.values())[0]["error"]
    db.expire_all()
    assert "contraseña" in db.query(BuzonCorreo).one().ultimo_error


@pytest.mark.parametrize("servidor", ["127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254"])
def test_no_permite_servidores_internos(servidor):
    with pytest.raises(buzon.BuzonError):
        buzon.validar_servidor(servidor)
