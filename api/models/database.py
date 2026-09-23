"""
Modelos de base de datos (SQLAlchemy).
Refleja el ciclo de vida completo de cada comprobante para poder auditar todo.

Los cambios de esquema se aplican con Alembic (carpeta migrations/).
"""
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, String, DateTime, Numeric, Integer, BigInteger, Text, ForeignKey, Enum,
    LargeBinary, PrimaryKeyConstraint, UniqueConstraint, create_engine, select,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, insert as pg_insert
from sqlalchemy.orm import relationship, declarative_base, sessionmaker, Session

from config.settings import get_settings

settings = get_settings()

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class EstadoFactura(str, enum.Enum):
    PENDIENTE = "PENDIENTE"          # Creado en tu sistema, aún no enviado
    ENVIADO = "ENVIADO"              # Enviado a Hacienda, esperando respuesta
    ACEPTADO = "ACEPTADO"            # Hacienda lo aceptó
    RECHAZADO = "RECHAZADO"          # Hacienda lo rechazó
    ERROR_COMUNICACION = "ERROR_COMUNICACION"  # Fallo de red/timeout/credenciales
    CONTINGENCIA = "CONTINGENCIA"    # Hacienda caída, pendiente de reintento


# Estados desde los que se permite (re)enviar un documento
ESTADOS_REENVIABLES = (
    EstadoFactura.PENDIENTE,
    EstadoFactura.ERROR_COMUNICACION,
    EstadoFactura.CONTINGENCIA,
)
ESTADOS_FINALES = (EstadoFactura.ACEPTADO, EstadoFactura.RECHAZADO)


def gen_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Emisor(Base):
    """Empresa o persona que emite comprobantes (cliente del contador)."""
    __tablename__ = "emisores"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tipo_identificacion = Column(String(2), nullable=False)
    numero_identificacion = Column(String(12), nullable=False, unique=True)
    nombre = Column(String(100), nullable=False)
    nombre_comercial = Column(String(80), nullable=True)
    codigo_actividad = Column(String(6), nullable=False)
    correo = Column(String(160), nullable=False)
    telefono_codigo_pais = Column(String(3), nullable=True)
    telefono = Column(String(20), nullable=True)
    provincia = Column(String(1), nullable=False)
    canton = Column(String(2), nullable=False)
    distrito = Column(String(2), nullable=False)
    barrio = Column(String(50), nullable=True)
    otras_senas = Column(String(250), nullable=False)
    proveedor_sistemas = Column(String(20), nullable=True)
    # Registro de bebidas alcohólicas (Ley 8707), obligatorio si factura esos CABYS
    registro_fiscal_8707 = Column(String(12), nullable=True)

    ambiente = Column(String(4), nullable=False, default="stag")  # stag | prod
    hacienda_usuario = Column(String(100), nullable=True)
    hacienda_password_cifrado = Column(LargeBinary, nullable=True)
    cert_p12_cifrado = Column(LargeBinary, nullable=True)
    cert_password_cifrado = Column(LargeBinary, nullable=True)
    cert_sujeto = Column(String(300), nullable=True)
    cert_vence = Column(DateTime(timezone=True), nullable=True)

    webhook_url = Column(String(500), nullable=True)
    webhook_secret_cifrado = Column(LargeBinary, nullable=True)

    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ApiKey(Base):
    """
    Llaves de acceso de los sistemas cliente. Solo se guarda el hash SHA-256;
    la llave en claro se muestra una única vez al crearla.
    emisor_id NULL + es_admin = acceso a todos los emisores y a la administración.
    """
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    nombre = Column(String(100), nullable=False)
    prefijo = Column(String(12), nullable=False)
    hash = Column(String(64), nullable=False, unique=True)
    es_admin = Column(Boolean, nullable=False, default=False)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=True, index=True)
    activa = Column(Boolean, nullable=False, default=True)
    ultimo_uso = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Usuario(Base):
    """
    Persona que usa el panel web (contador, asistente, cliente). Admin = todas
    las empresas; si no, queda restringido a emisor_id.
    """
    __tablename__ = "usuarios"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String(160), nullable=False, unique=True)
    nombre = Column(String(100), nullable=False)
    password_hash = Column(String(300), nullable=False)
    es_admin = Column(Boolean, nullable=False, default=False)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=True, index=True)
    activo = Column(Boolean, nullable=False, default=True)
    intentos_fallidos = Column(Integer, nullable=False, default=0)
    bloqueado_hasta = Column(DateTime(timezone=True), nullable=True)
    ultimo_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Sesion(Base):
    """Sesión del panel. Solo se guarda el hash del token."""
    __tablename__ = "sesiones"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    usuario_id = Column(UUID(as_uuid=False), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expira = Column(DateTime(timezone=True), nullable=False)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    usuario = relationship("Usuario")


class Factura(Base):
    """Comprobante emitido (factura, tiquete, notas, compra, exportación, recibo de pago)."""
    __tablename__ = "facturas"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id"), nullable=False, index=True)
    clave = Column(String(50), unique=True, nullable=False, index=True)
    numero_consecutivo = Column(String(20), nullable=False)
    tipo_documento = Column(String(2), nullable=False, default="01")
    # 1 normal, 2 contingencia (sustituye comprobante provisional), 3 sin internet
    situacion = Column(String(1), nullable=False, default="1")
    fecha_emision = Column(DateTime(timezone=True), nullable=False, index=True)
    # ID del documento en el sistema cliente (idempotencia, única por emisor)
    referencia_externa = Column(String(100), nullable=True)
    # Documento que esta nota anula/corrige (si se generó con /anular)
    factura_origen_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id"), nullable=True)

    # Contraparte: receptor (o proveedor en la factura de compra 08)
    receptor_nombre = Column(String(200), nullable=True)
    receptor_identificacion = Column(String(20), nullable=True)
    receptor_tipo_identificacion = Column(String(2), nullable=True)
    receptor_correo = Column(String(160), nullable=True)

    # Totales (en la moneda del comprobante)
    condicion_venta = Column(String(2), nullable=True)
    moneda = Column(String(3), nullable=False, default="CRC")
    tipo_cambio = Column(Numeric(18, 5), nullable=True)
    total_venta = Column(Numeric(18, 5), nullable=False, default=0)
    total_descuentos = Column(Numeric(18, 5), nullable=False, default=0)
    total_gravado = Column(Numeric(18, 5), nullable=False, default=0)
    total_exento = Column(Numeric(18, 5), nullable=False, default=0)
    total_exonerado = Column(Numeric(18, 5), nullable=False, default=0)
    total_no_sujeto = Column(Numeric(18, 5), nullable=False, default=0)
    total_otros_cargos = Column(Numeric(18, 5), nullable=False, default=0)
    total_iva_devuelto = Column(Numeric(18, 5), nullable=False, default=0)
    monto_impuesto = Column(Numeric(18, 5), nullable=False, default=0)
    monto_total = Column(Numeric(18, 5), nullable=False)       # TotalComprobante

    # Envío a Hacienda
    estado = Column(Enum(EstadoFactura), nullable=False, default=EstadoFactura.PENDIENTE, index=True)
    estado_hacienda = Column(String(100), nullable=True)
    mensaje_hacienda = Column(Text, nullable=True)
    envio_json = Column(JSONB, nullable=True)      # cuerpo del POST /recepcion (sin el XML)
    clave_consulta = Column(String(71), nullable=True)  # ruta para GET /recepcion/{...}
    intentos_envio = Column(Integer, nullable=False, default=0)
    ultimo_envio = Column(DateTime(timezone=True), nullable=True)
    correo_enviado = Column(Boolean, nullable=False, default=False)

    # Documentos
    xml_firmado = Column(Text, nullable=True)
    xml_respuesta = Column(Text, nullable=True)
    json_original = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    emisor = relationship("Emisor")
    detalles = relationship("FacturaDetalle", back_populates="factura", cascade="all, delete-orphan",
                            order_by="FacturaDetalle.linea_numero")
    eventos = relationship("FacturaEvento", back_populates="factura", cascade="all, delete-orphan",
                           order_by="FacturaEvento.created_at")

    __table_args__ = (UniqueConstraint("emisor_id", "referencia_externa", name="uq_factura_referencia_externa"),)


class FacturaDetalle(Base):
    __tablename__ = "facturas_detalles"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="CASCADE"), index=True)
    linea_numero = Column(Integer, nullable=False)
    codigo_cabys = Column(String(13), nullable=True)
    codigo_producto = Column(String(50), nullable=True)
    descripcion = Column(String(500), nullable=False)
    unidad_medida = Column(String(15), nullable=True)
    es_servicio = Column(Boolean, nullable=False, default=False)
    cantidad = Column(Numeric(18, 6), nullable=False)
    precio_unitario = Column(Numeric(18, 6), nullable=False)
    descuento = Column(Numeric(18, 5), nullable=False, default=0)
    subtotal = Column(Numeric(18, 5), nullable=False, default=0)
    base_imponible = Column(Numeric(18, 5), nullable=False, default=0)
    codigo_tarifa_iva = Column(String(2), nullable=True)
    impuesto_porcentaje = Column(Numeric(5, 2), nullable=True)
    impuesto_monto = Column(Numeric(18, 5), nullable=True)      # impuesto bruto (todos)
    monto_exonerado = Column(Numeric(18, 5), nullable=False, default=0)
    impuesto_asumido = Column(Numeric(18, 5), nullable=False, default=0)
    impuesto_neto = Column(Numeric(18, 5), nullable=False, default=0)
    monto_total = Column(Numeric(18, 5), nullable=False)        # MontoTotalLinea

    factura = relationship("Factura", back_populates="detalles")


class DocumentoRecibido(Base):
    """
    Comprobante electrónico recibido de un proveedor. El emisor (nuestro
    cliente) lo acepta, acepta parcialmente o rechaza con un Mensaje Receptor.
    """
    __tablename__ = "documentos_recibidos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id"), nullable=False, index=True)
    clave = Column(String(50), nullable=False, index=True)
    tipo_documento = Column(String(2), nullable=True)
    fecha_emision = Column(DateTime(timezone=True), nullable=True, index=True)
    proveedor_tipo_identificacion = Column(String(2), nullable=True)
    proveedor_identificacion = Column(String(20), nullable=False)
    proveedor_nombre = Column(String(200), nullable=True)
    moneda = Column(String(3), nullable=False, default="CRC")
    tipo_cambio = Column(Numeric(18, 5), nullable=True)
    total_impuesto = Column(Numeric(18, 5), nullable=False, default=0)
    total_comprobante = Column(Numeric(18, 5), nullable=False, default=0)
    firma_valida = Column(Boolean, nullable=True)
    xml_original = Column(Text, nullable=False)
    xml_respuesta_proveedor = Column(Text, nullable=True)  # MensajeHacienda que envió el proveedor

    # Mensaje Receptor
    mensaje = Column(String(1), nullable=True)             # 1 aceptado, 2 parcial, 3 rechazado
    detalle_mensaje = Column(String(160), nullable=True)
    codigo_actividad = Column(String(6), nullable=True)
    condicion_impuesto = Column(String(2), nullable=True)
    monto_impuesto_acreditar = Column(Numeric(18, 5), nullable=True)
    monto_gasto_aplicable = Column(Numeric(18, 5), nullable=True)
    consecutivo_receptor = Column(String(20), nullable=True)
    fecha_mensaje = Column(DateTime(timezone=True), nullable=True)
    xml_firmado = Column(Text, nullable=True)              # MensajeReceptor firmado

    # Envío del Mensaje Receptor a Hacienda (NULL = aún sin responder)
    estado = Column(Enum(EstadoFactura), nullable=True, index=True)
    estado_hacienda = Column(String(100), nullable=True)
    mensaje_hacienda = Column(Text, nullable=True)
    envio_json = Column(JSONB, nullable=True)
    clave_consulta = Column(String(71), nullable=True, index=True)
    intentos_envio = Column(Integer, nullable=False, default=0)
    ultimo_envio = Column(DateTime(timezone=True), nullable=True)
    xml_respuesta = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    emisor = relationship("Emisor")
    eventos = relationship("FacturaEvento", back_populates="documento_recibido", cascade="all, delete-orphan",
                           order_by="FacturaEvento.created_at")

    __table_args__ = (UniqueConstraint("emisor_id", "clave", name="uq_recibido_emisor_clave"),)


class FacturaEvento(Base):
    """Bitácora de auditoría: cada cosa que le pasa a un documento queda registrada."""
    __tablename__ = "facturas_eventos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="CASCADE"), nullable=True, index=True)
    documento_recibido_id = Column(
        UUID(as_uuid=False), ForeignKey("documentos_recibidos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    evento = Column(String(50), nullable=False)
    detalle = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    factura = relationship("Factura", back_populates="eventos")
    documento_recibido = relationship("DocumentoRecibido", back_populates="eventos")


class Plan(Base):
    """Paquete de documentos que se ofrece a la venta (catálogo)."""
    __tablename__ = "planes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    nombre = Column(String(80), nullable=False)
    descripcion = Column(String(300), nullable=True)
    documentos = Column(Integer, nullable=False)
    precio = Column(Numeric(18, 2), nullable=False)
    moneda = Column(String(3), nullable=False, default="CRC")
    dias_vigencia = Column(Integer, nullable=True)       # NULL = no vence
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Paquete(Base):
    """Bolsa de documentos adquirida por una empresa. Se consume en orden de vencimiento."""
    __tablename__ = "paquetes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id = Column(UUID(as_uuid=False), ForeignKey("planes.id"), nullable=True)
    nombre = Column(String(80), nullable=False)
    documentos = Column(Integer, nullable=False)
    usados = Column(Integer, nullable=False, default=0)
    precio = Column(Numeric(18, 2), nullable=False, default=0)
    moneda = Column(String(3), nullable=False, default="CRC")
    referencia_pago = Column(String(100), nullable=True)   # comprobante SINPE, transferencia, id de pasarela
    notas = Column(Text, nullable=True)
    vence = Column(DateTime(timezone=True), nullable=True)
    anulado = Column(Boolean, nullable=False, default=False)
    creado_por = Column(String(160), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

    plan = relationship("Plan")

    @property
    def disponibles(self) -> int:
        return self.documentos - self.usados


class Consumo(Base):
    """Un documento firmado y enviado que descontó saldo (bitácora de consumo)."""
    __tablename__ = "consumos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    paquete_id = Column(UUID(as_uuid=False), ForeignKey("paquetes.id"), nullable=False, index=True)
    # Clave del comprobante o clave-consecutivo del mensaje receptor: nunca se cobra dos veces
    referencia = Column(String(71), nullable=False, unique=True)
    tipo_documento = Column(String(2), nullable=False)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="SET NULL"), nullable=True)
    documento_recibido_id = Column(UUID(as_uuid=False), ForeignKey("documentos_recibidos.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)

    paquete = relationship("Paquete")
    factura = relationship("Factura")
    documento_recibido = relationship("DocumentoRecibido")


class ConsecutivoContador(Base):
    """
    Último número consecutivo usado por emisor + sucursal + terminal + tipo de
    documento. Se incrementa con SELECT ... FOR UPDATE dentro de la misma
    transacción que inserta el documento: si algo falla antes del commit, el
    número no se consume y no quedan huecos ni duplicados.
    """
    __tablename__ = "consecutivos"

    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False)
    sucursal = Column(Integer, nullable=False)
    terminal = Column(Integer, nullable=False)
    tipo_documento = Column(String(2), nullable=False)
    ultimo = Column(BigInteger, nullable=False, default=0)

    __table_args__ = (PrimaryKeyConstraint("emisor_id", "sucursal", "terminal", "tipo_documento"),)


def siguiente_consecutivo(db: Session, emisor_id: str, sucursal: int, terminal: int, tipo_documento: str) -> int:
    """Reserva el siguiente consecutivo. Debe llamarse dentro de la transacción del documento."""
    llave = dict(emisor_id=emisor_id, sucursal=sucursal, terminal=terminal, tipo_documento=tipo_documento)
    db.execute(pg_insert(ConsecutivoContador).values(**llave, ultimo=0).on_conflict_do_nothing())
    contador = db.execute(select(ConsecutivoContador).filter_by(**llave).with_for_update()).scalar_one()
    contador.ultimo += 1
    db.flush()
    return contador.ultimo


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
