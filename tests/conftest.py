"""
Configuración de pruebas. Las variables de entorno se fijan ANTES de importar
el proyecto porque get_settings() se cachea.

Las pruebas que usan base de datos requieren PostgreSQL (TEST_DATABASE_URL);
se omiten si no está disponible. Forma recomendada de correrlas:

    docker compose run --rm api sh -c "pip install -q --user -r requirements-dev.txt && python -m pytest -q"
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

CERT_PASSWORD = "1234"
ADMIN_KEY = "a" * 40
CALLBACK_TOKEN = "t" * 40
_TMP = tempfile.mkdtemp(prefix="facturacion-tests-")


def crear_p12(cedula: str = "3101123456", dias_validez: int = 365, inicio_offset_dias: int = -1) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Pruebas S.A."),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CPJ-{cedula}"),
        x509.NameAttribute(NameOID.COMMON_NAME, "EMISOR DE PRUEBA"),
    ])
    inicio = datetime.now(timezone.utc) + timedelta(days=inicio_offset_dias)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(inicio + timedelta(days=dias_validez))
        .sign(key, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"prueba", key, cert, None, BestAvailableEncryption(CERT_PASSWORD.encode())
    )


P12 = crear_p12()

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql+psycopg2://facturacion:facturacion@localhost:5432/facturacion")
    .rsplit("/", 1)[0] + "/facturacion_test",
)

os.environ.update({
    "AMBIENTE": "stag",
    "DATABASE_URL": TEST_DATABASE_URL,
    "REDIS_URL": "redis://127.0.0.1:6399/0",   # inexistente: la app debe tolerarlo
    "MASTER_KEY": Fernet.generate_key().decode(),
    "FIRMA_POLICY_DIGEST": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "XSD_DIR": "",
    "API_KEYS": ADMIN_KEY,
    "CALLBACK_TOKEN": CALLBACK_TOKEN,
    "CALLBACK_BASE_URL": "https://facturas.example.com",
    "CORS_ORIGINS": "",
    "SMTP_HOST": "",
    "SMTP_FROM": "",
})


def persona_emisor_prueba(**cambios) -> dict:
    datos = {
        "nombre": "Pruebas S.A.",
        "tipo_identificacion": "02",
        "numero_identificacion": "3101123456",
        "nombre_comercial": None,
        "ubicacion": {"provincia": "1", "canton": "01", "distrito": "01", "barrio": None,
                      "otras_senas": "Frente al parque"},
        "telefono_codigo_pais": "506",
        "telefono": None,
        "correo": "facturas@example.com",
        "codigo_actividad": "620100",
        "proveedor_sistemas": "3101123456",
    }
    datos.update(cambios)
    return datos


def _crear_base_de_pruebas() -> bool:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(TEST_DATABASE_URL)
    try:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            existe = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}).scalar()
            if not existe:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        admin.dispose()
        return True
    except Exception:
        return False


DB_DISPONIBLE = _crear_base_de_pruebas()


@pytest.fixture
def db():
    if not DB_DISPONIBLE:
        pytest.skip("PostgreSQL de pruebas no disponible")
    from api.models.database import Base, engine, SessionLocal

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()


def crear_emisor(db, numero="3101123456", nombre="Pruebas S.A.", con_certificado=True, documentos=100_000):
    from api.models.database import Emisor
    from api.services import emisores

    emisor = Emisor(
        tipo_identificacion="02", numero_identificacion=numero, nombre=nombre, codigo_actividad="620100",
        correo="facturas@example.com", provincia="1", canton="01", distrito="01",
        otras_senas="Frente al parque", ambiente="stag",
    )
    if con_certificado:
        emisores.guardar_certificado(emisor, crear_p12(numero), CERT_PASSWORD)
        emisores.guardar_credenciales(emisor, f"cpj-02-{numero}@stag.comprobanteselectronicos.go.cr", "secreto")
    db.add(emisor)
    db.commit()
    if documentos:
        from api.services import saldo
        saldo.acreditar(db, emisor, documentos=documentos, nombre="Paquete de pruebas")
    return emisor


@pytest.fixture
def emisor(db):
    return crear_emisor(db)


@pytest.fixture
def api_key(db, emisor):
    from api.security import crear_api_key
    _, llave = crear_api_key(db, "POS de prueba", False, emisor.id)
    return llave


@pytest.fixture
def cola(monkeypatch):
    """Intercepta los encolados de Celery (no se necesita Redis)."""
    from workers import tasks

    llamadas = []
    for nombre in ("enviar_documento", "consultar_documento", "enviar_correo", "notificar_webhook", "notificar_saldo"):
        tarea = getattr(tasks, nombre)
        monkeypatch.setattr(tarea, "delay", lambda *a, _n=nombre, **k: llamadas.append((_n, a)))
        monkeypatch.setattr(
            tarea, "apply_async",
            lambda args=(), kwargs=None, _n=nombre, **k: llamadas.append((_n, tuple(args or ()))),
        )
    return llamadas


@pytest.fixture
def app_client(db, cola):
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(app_client, api_key):
    app_client.headers["X-API-Key"] = api_key
    return app_client


@pytest.fixture
def admin(db, cola):
    from fastapi.testclient import TestClient
    from api.main import app

    with TestClient(app) as c:
        c.headers["X-API-Key"] = ADMIN_KEY
        yield c


def factura_payload(**cambios) -> dict:
    payload = {
        "receptor": {
            "nombre": "Juan Pérez",
            "tipo_identificacion": "01",
            "numero_identificacion": "112345678",
            "correo": "juan@example.com",
        },
        "productos": [
            {
                "codigo_cabys": "8314100000000",
                "descripcion": "Servicio de consultoría",
                "cantidad": "2",
                "unidad_medida": "Sp",
                "precio_unitario": "50000",
                "descuento": "10000",
                "codigo_descuento": "07",
                "codigo_tarifa_iva": "08",
            },
            {
                "codigo_cabys": "2399999009900",
                "descripcion": "Libro",
                "cantidad": "1",
                "unidad_medida": "Unid",
                "precio_unitario": "15000",
                "codigo_tarifa_iva": "10",
            },
        ],
    }
    payload.update(cambios)
    return payload
