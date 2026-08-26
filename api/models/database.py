"""
Modelos de base de datos (SQLAlchemy).
Refleja el ciclo de vida completo del comprobante para poder auditar todo.
"""
import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Numeric, Integer, Text, ForeignKey, Enum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
from sqlalchemy import create_engine

from config.settings import get_settings

settings = get_settings()

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class EstadoFactura(str, enum.Enum):
    PENDIENTE = "PENDIENTE"          # Creada en tu sistema, aún no enviada
    ENVIADO = "ENVIADO"              # Enviada a Hacienda, esperando respuesta
    ACEPTADO = "ACEPTADO"            # Hacienda la aceptó
    RECHAZADO = "RECHAZADO"          # Hacienda la rechazó
    ERROR_COMUNICACION = "ERROR_COMUNICACION"  # Fallo de red/timeout
    CONTINGENCIA = "CONTINGENCIA"    # Hacienda caída, pendiente de reintento


def gen_uuid():
    return str(uuid.uuid4())


class Factura(Base):
    __tablename__ = "facturas"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    clave = Column(String(50), unique=True, nullable=False, index=True)
    numero_consecutivo = Column(String(20), nullable=False)
    fecha_emision = Column(DateTime(timezone=True), nullable=False)

    # Emisor
    emisor_nombre = Column(String(200), nullable=False)
    emisor_identificacion = Column(String(20), nullable=False)
    emisor_tipo_identificacion = Column(String(2), nullable=False)

    # Receptor
    receptor_nombre = Column(String(200), nullable=False)
    receptor_identificacion = Column(String(20), nullable=True)
    receptor_tipo_identificacion = Column(String(2), nullable=True)
    receptor_correo = Column(String(100), nullable=True)

    # Totales
    monto_total = Column(Numeric(18, 2), nullable=False)
    monto_impuesto = Column(Numeric(18, 2), nullable=False, default=0)
    moneda = Column(String(3), default="CRC")
    tipo_cambio = Column(Numeric(18, 6), nullable=True)

    # Estado
    estado = Column(Enum(EstadoFactura), nullable=False, default=EstadoFactura.PENDIENTE, index=True)
    estado_hacienda = Column(String(100), nullable=True)
    mensaje_hacienda = Column(Text, nullable=True)

    # Documentos
    xml_firmado = Column(Text, nullable=True)
    xml_respuesta = Column(Text, nullable=True)
    json_original = Column(JSONB, nullable=True)

    # Metadatos
    intentos_envio = Column(Integer, default=0)
    ultimo_envio = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    detalles = relationship("FacturaDetalle", back_populates="factura", cascade="all, delete-orphan")
    eventos = relationship("FacturaEvento", back_populates="factura", cascade="all, delete-orphan")


class FacturaDetalle(Base):
    __tablename__ = "facturas_detalles"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="CASCADE"))
    linea_numero = Column(Integer, nullable=False)
    codigo_producto = Column(String(50), nullable=True)
    descripcion = Column(String(500), nullable=False)
    cantidad = Column(Numeric(18, 6), nullable=False)
    precio_unitario = Column(Numeric(18, 6), nullable=False)
    monto_total = Column(Numeric(18, 6), nullable=False)
    impuesto_porcentaje = Column(Numeric(5, 2), nullable=True)
    impuesto_monto = Column(Numeric(18, 6), nullable=True)

    factura = relationship("Factura", back_populates="detalles")


class FacturaEvento(Base):
    """Bitácora de auditoría: cada cosa que le pasa a la factura queda registrada."""
    __tablename__ = "facturas_eventos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="CASCADE"))
    evento = Column(String(50), nullable=False)  # ENVIO, RECHAZO, ACEPTACION, REINTENTO, CALLBACK_RECIBIDO
    detalle = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    factura = relationship("Factura", back_populates="eventos")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Crea las tablas si no existen. En producción usar Alembic en su lugar."""
    Base.metadata.create_all(bind=engine)
