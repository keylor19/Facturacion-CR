"""
Modelos de base de datos (SQLAlchemy).
Refleja el ciclo de vida completo de cada comprobante para poder auditar todo.

Los cambios de esquema se aplican con Alembic (carpeta migrations/).
"""
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, String, Date, DateTime, Numeric, Integer, BigInteger, Text, ForeignKey, Enum, Index,
    LargeBinary, PrimaryKeyConstraint, UniqueConstraint, create_engine, select, text,
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

    # Panel web para los usuarios de la empresa: servicio adicional y opcional (se cobra
    # aparte o se da como regalía). El producto principal es la conexión por API.
    facturacion_web = Column(Boolean, nullable=False, default=False, server_default="false")
    # Recordatorios automáticos por correo a clientes con facturas a crédito vencidas
    recordar_cobros = Column(Boolean, nullable=False, default=False, server_default="false")
    # Conexión por API (el sistema de facturación del cliente se integra con llaves de API).
    acceso_api = Column(Boolean, nullable=False, default=True, server_default="true")
    # Empresa que un contador agregó solo para llevarle la contabilidad (no factura aquí)
    solo_contabilidad = Column(Boolean, nullable=False, default=False, server_default="false")
    contador_id = Column(UUID(as_uuid=False), ForeignKey("usuarios.id", ondelete="SET NULL", use_alter=True,
                                                         name="fk_emisores_contador"), nullable=True)
    logo = Column(LargeBinary, nullable=True)            # PNG o JPEG para el PDF
    logo_tipo = Column(String(20), nullable=True)

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
    rol = Column(String(20), nullable=False, default="dueno", server_default="dueno")  # dueno, contador o cajero
    # Contador externo: lleva la contabilidad de las empresas que le asigna el administrador
    # (usuario_empresas) y de las que él mismo agrega. No factura ni ve el resto del panel.
    es_contador = Column(Boolean, nullable=False, default=False, server_default="false")
    # Cuenta creada con Google o Microsoft (además o en vez de contraseña)
    oauth_proveedor = Column(String(20), nullable=True)
    oauth_sub = Column(String(255), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    intentos_fallidos = Column(Integer, nullable=False, default=0)
    bloqueado_hasta = Column(DateTime(timezone=True), nullable=True)
    ultimo_login = Column(DateTime(timezone=True), nullable=True)
    # Verificación en dos pasos (TOTP). El secreto se guarda cifrado con MASTER_KEY.
    totp_secreto_cifrado = Column(LargeBinary, nullable=True)
    totp_activo = Column(Boolean, nullable=False, default=False, server_default="false")
    totp_ultimo_paso = Column(BigInteger, nullable=True)   # evita reutilizar un mismo código
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Auditoria(Base):
    """Bitácora de acciones sensibles: quién hizo qué, cuándo y desde dónde."""
    __tablename__ = "auditoria"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    fecha = Column(DateTime(timezone=True), default=utcnow, index=True)
    actor = Column(String(200), nullable=False)          # correo del usuario o nombre de la llave
    accion = Column(String(60), nullable=False, index=True)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="SET NULL"), nullable=True, index=True)
    detalle = Column(Text, nullable=True)
    ip = Column(String(64), nullable=True)


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
    # Turno de caja del punto de venta en que se cobró (null = emitido fuera del POS)
    caja_id = Column(UUID(as_uuid=False), ForeignKey("cajas.id"), nullable=True, index=True)
    # Primera referencia (InformacionReferencia): código de la nota 9 y clave del documento citado
    codigo_referencia = Column(String(2), nullable=True)
    referencia_clave = Column(String(50), nullable=True, index=True)
    # Mes (día 1) al que va el efecto contable: el de emisión, salvo notas con código 13/14,
    # que van al mes del comprobante que modifican (Anexos y Estructuras 4.4, nota 9)
    periodo_fiscal = Column(Date, nullable=True, index=True)

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
    # Comprobante emitido en otro sistema y cargado por el contador (su XML): no se envía a Hacienda
    importada = Column(Boolean, nullable=False, default=False, server_default="false")

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
    origen = Column(String(10), nullable=False, default="manual")   # manual | correo | api
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


class BuzonCorreo(Base):
    """
    Buzón IMAP donde la empresa recibe las facturas de sus proveedores. Se revisa
    periódicamente y los XML adjuntos se registran como documentos recibidos.
    Se recuerda el último UID leído para no volver a procesar los mismos correos.
    """
    __tablename__ = "buzones_correo"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, unique=True)
    servidor = Column(String(200), nullable=False)
    puerto = Column(Integer, nullable=False, default=993)
    usuario = Column(String(200), nullable=False)
    password_cifrado = Column(LargeBinary, nullable=False)
    carpeta = Column(String(200), nullable=False, default="INBOX")
    activo = Column(Boolean, nullable=False, default=True)
    uid_validity = Column(BigInteger, nullable=True)
    ultimo_uid = Column(BigInteger, nullable=True)
    ultima_revision = Column(DateTime(timezone=True), nullable=True)
    ultimo_error = Column(Text, nullable=True)
    documentos_importados = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


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
    # Comprobante que la plataforma le emitió al cliente por esta venta
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="SET NULL"), nullable=True)
    comprobante_error = Column(Text, nullable=True)

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


class Suscripcion(Base):
    """
    Alquiler de un servicio por un período (mensualidad), aparte de los
    documentos. servicio: "api" (conexión por API) o "facturacion_web".
    """
    __tablename__ = "suscripciones"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    servicio = Column(String(20), nullable=False)
    desde = Column(DateTime(timezone=True), nullable=False)
    hasta = Column(DateTime(timezone=True), nullable=False, index=True)
    meses = Column(Integer, nullable=False)
    precio = Column(Numeric(18, 2), nullable=False, default=0)
    moneda = Column(String(3), nullable=False, default="CRC")
    referencia_pago = Column(String(100), nullable=True)
    notas = Column(Text, nullable=True)
    anulada = Column(Boolean, nullable=False, default=False)
    creado_por = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="SET NULL"), nullable=True)
    comprobante_error = Column(Text, nullable=True)


class AjustesVentas(Base):
    """
    Una sola fila: cómo factura la plataforma sus ventas (paquetes y mensualidades)
    a las empresas cliente. emisor_ventas es la empresa del dueño de la plataforma.
    """
    __tablename__ = "ajustes_ventas"

    id = Column(Integer, primary_key=True, default=1)
    emisor_ventas_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="SET NULL"), nullable=True)
    codigo_cabys = Column(String(13), nullable=True)
    codigo_tarifa_iva = Column(String(2), nullable=False, default="08")
    precio_incluye_iva = Column(Boolean, nullable=False, default=True)
    tipo_comprobante = Column(String(2), nullable=False, default="01")   # 01 factura | 04 tiquete
    medio_pago = Column(String(2), nullable=False, default="04")         # transferencia
    # Avisos comerciales al cliente (pocos documentos, servicio por vencer)
    instrucciones_pago = Column(Text, nullable=True)     # cuentas IBAN, SINPE Móvil…
    contacto_ventas = Column(String(200), nullable=True) # teléfono / WhatsApp / correo para comprar
    correo_avisos = Column(String(160), nullable=True)   # copia de cada aviso al administrador
    # Inscripción propia desde la página de entrada, con prueba gratis
    autoregistro = Column(Boolean, nullable=False, default=True, server_default="true")
    prueba_documentos = Column(Integer, nullable=False, default=20, server_default="20")
    prueba_dias = Column(Integer, nullable=False, default=15, server_default="15")   # días del sistema web gratis
    # Precio por mes del sistema web cuando el cliente lo compra solo (vacío = no se ofrece)
    precio_web_mensual = Column(Numeric(18, 2), nullable=True)
    moneda_web = Column(String(3), nullable=False, default="CRC", server_default="CRC")
    # Mensualidades (vacío = ese servicio no se cobra)
    precio_contabilidad_mensual = Column(Numeric(18, 2), nullable=True)   # el dueño lleva su propia contabilidad
    precio_contador_mensual = Column(Numeric(18, 2), nullable=True)       # cuenta de contador
    dias_para_pagar = Column(Integer, nullable=False, default=10, server_default="10")
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Cliente(Base):
    """Cliente frecuente de una empresa (catálogo para no digitarlo en cada factura)."""
    __tablename__ = "clientes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo_identificacion = Column(String(2), nullable=False)
    numero_identificacion = Column(String(20), nullable=False)
    nombre = Column(String(100), nullable=False)
    nombre_comercial = Column(String(80), nullable=True)
    correo = Column(String(160), nullable=True)
    telefono = Column(String(20), nullable=True)
    codigo_actividad = Column(String(6), nullable=True)
    provincia = Column(String(1), nullable=True)
    canton = Column(String(2), nullable=True)
    distrito = Column(String(2), nullable=True)
    otras_senas = Column(String(250), nullable=True)
    notas = Column(Text, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("emisor_id", "numero_identificacion", name="uq_cliente_emisor_identificacion"),)


class Producto(Base):
    """Producto o servicio del catálogo de una empresa, con control de inventario opcional."""
    __tablename__ = "productos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    codigo = Column(String(20), nullable=False)               # código interno (va como CodigoComercial)
    codigo_cabys = Column(String(13), nullable=False)
    descripcion = Column(String(200), nullable=False)
    unidad_medida = Column(String(15), nullable=False, default="Unid")
    es_servicio = Column(Boolean, nullable=False, default=False)
    precio_unitario = Column(Numeric(18, 5), nullable=False, default=0)   # sin IVA, en colones
    codigo_tarifa_iva = Column(String(2), nullable=False, default="08")
    costo_unitario = Column(Numeric(18, 5), nullable=True)                # para valorar el inventario
    controla_inventario = Column(Boolean, nullable=False, default=False)
    existencia = Column(Numeric(18, 3), nullable=False, default=0)
    existencia_minima = Column(Numeric(18, 3), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    categoria_id = Column(UUID(as_uuid=False), ForeignKey("categorias.id", ondelete="SET NULL"), nullable=True, index=True)
    # Combo: se vende como una línea y descuenta las existencias de sus componentes
    es_combo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    categoria = relationship("Categoria", lazy="joined")
    componentes = relationship("ComboComponente", foreign_keys="ComboComponente.combo_id", cascade="all, delete-orphan",
                               lazy="selectin", order_by="ComboComponente.id")

    __table_args__ = (UniqueConstraint("emisor_id", "codigo", name="uq_producto_emisor_codigo"),)


class Categoria(Base):
    """Agrupa productos para buscarlos, reportarlos y aplicarles descuentos."""
    __tablename__ = "categorias"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(60), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("emisor_id", "nombre", name="uq_categoria_emisor_nombre"),)


class ComboComponente(Base):
    """Producto y cantidad que lleva un combo."""
    __tablename__ = "combo_componentes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    combo_id = Column(UUID(as_uuid=False), ForeignKey("productos.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(UUID(as_uuid=False), ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Numeric(18, 3), nullable=False)

    producto = relationship("Producto", foreign_keys=[producto_id], lazy="joined")


class Descuento(Base):
    """
    Promoción que el panel aplica sola al facturar: porcentaje o monto por
    unidad, para todo, una categoría o un producto, con vigencia y cantidad mínima.
    """
    __tablename__ = "descuentos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(100), nullable=False)
    tipo = Column(String(10), nullable=False)                 # porcentaje | monto (por unidad, sin IVA)
    valor = Column(Numeric(18, 5), nullable=False)
    alcance = Column(String(10), nullable=False)              # todos | categoria | producto
    categoria_id = Column(UUID(as_uuid=False), ForeignKey("categorias.id", ondelete="CASCADE"), nullable=True)
    producto_id = Column(UUID(as_uuid=False), ForeignKey("productos.id", ondelete="CASCADE"), nullable=True)
    cantidad_minima = Column(Numeric(18, 3), nullable=True)
    codigo_descuento = Column(String(2), nullable=False, default="06")   # código de Hacienda (06 promocional)
    desde = Column(Date, nullable=True)
    hasta = Column(Date, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    categoria = relationship("Categoria", lazy="joined")
    producto = relationship("Producto", lazy="joined")


class MovimientoInventario(Base):
    """
    Kárdex: cada cambio de existencia queda registrado. Las ventas, notas de
    crédito y compras se generan solas al emitir; si Hacienda rechaza el
    comprobante se agrega un movimiento de reverso.
    """
    __tablename__ = "movimientos_inventario"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(UUID(as_uuid=False), ForeignKey("productos.id", ondelete="CASCADE"), nullable=False, index=True)
    fecha = Column(DateTime(timezone=True), default=utcnow, index=True)
    # venta | devolucion | compra | reverso | entrada | salida | ajuste
    tipo = Column(String(12), nullable=False)
    cantidad = Column(Numeric(18, 3), nullable=False)          # positiva entra, negativa sale
    existencia_resultante = Column(Numeric(18, 3), nullable=False)
    costo_unitario = Column(Numeric(18, 5), nullable=True)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="SET NULL"), nullable=True, index=True)
    nota = Column(String(300), nullable=True)
    usuario = Column(String(200), nullable=True)

    producto = relationship("Producto")
    factura = relationship("Factura")


class RegistroHacienda(Base):
    """
    Datos públicos de Hacienda guardados localmente (compartidos por todas las
    empresas): contribuyentes, exoneraciones, productores MAG/INCOPESCA, CABYS y
    el último tipo de cambio. Se consultan primero aquí y se refrescan cada
    DIAS_ACTUALIZAR_HACIENDA; si Hacienda no responde se usa lo guardado.
    """
    __tablename__ = "registros_hacienda"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    tipo = Column(String(20), nullable=False)          # ae, ex, agropecuario, pesca, cabys, tc
    clave = Column(String(60), nullable=False)         # identificación, autorización, código...
    ruta = Column(String(80), nullable=False)          # servicio de Hacienda (para refrescarlo)
    parametros = Column(JSONB, nullable=False, default=dict)
    encontrado = Column(Boolean, nullable=False, default=True)
    datos = Column(JSONB, nullable=True)
    actualizado_en = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    usado_en = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (UniqueConstraint("tipo", "clave", name="uq_registro_hacienda"),)


class CodigoCabys(Base):
    """Catálogo CABYS completo (archivo oficial del BCCR) para buscar sin consultar a Hacienda."""
    __tablename__ = "cabys"

    codigo = Column(String(13), primary_key=True)
    descripcion = Column(Text, nullable=False)
    impuesto = Column(Numeric(5, 2), nullable=False)       # % de IVA (13, 4, 2, 1, 0.5, 0)
    categorias = Column(JSONB, nullable=False, default=list)
    busqueda = Column(Text, nullable=False)                 # descripción en minúscula y sin tildes
    busqueda_categorias = Column(Text, nullable=False)
    actualizado_en = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class TipoCambioDiario(Base):
    """Tipo de cambio publicado por Hacienda para cada día (histórico propio)."""
    __tablename__ = "tipos_cambio"

    fecha = Column(Date, primary_key=True)
    usd_compra = Column(Numeric(12, 4), nullable=True)
    usd_venta = Column(Numeric(12, 4), nullable=True)
    eur_colones = Column(Numeric(12, 4), nullable=True)
    eur_dolares = Column(Numeric(12, 6), nullable=True)
    actualizado_en = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Borrador(Base):
    """
    Comprobante aún sin emitir: proforma (cotización numerada, con PDF y vigencia)
    o documento preliminar (borrador que se retoma después). Guarda el mismo
    cuerpo de POST /facturas; al emitirlo queda enlazado a la factura generada.
    """
    __tablename__ = "borradores"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    clase = Column(String(10), nullable=False)                 # proforma | preliminar
    numero = Column(Integer, nullable=True)                    # solo proformas (consecutivo propio)
    tipo_documento = Column(String(2), nullable=False, default="01")
    receptor_nombre = Column(String(200), nullable=True)
    receptor_identificacion = Column(String(20), nullable=True)
    receptor_correo = Column(String(160), nullable=True)
    moneda = Column(String(3), nullable=False, default="CRC")
    monto_impuesto = Column(Numeric(18, 5), nullable=True)     # null si los datos aún no son válidos
    monto_total = Column(Numeric(18, 5), nullable=True)
    datos = Column(JSONB, nullable=False)
    vence = Column(Date, nullable=True)
    estado = Column(String(10), nullable=False, default="ABIERTO")  # ABIERTO | FACTURADO | ANULADO
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id"), nullable=True)
    creado_por = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("emisor_id", "clase", "numero", name="uq_borrador_numero"),)


class Caja(Base):
    """
    Turno de caja del punto de venta: se abre con un fondo, registra las ventas
    y los movimientos de efectivo, y se cierra con el arqueo (monto contado).
    Solo puede haber una caja abierta por sucursal y terminal.
    """
    __tablename__ = "cajas"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    sucursal = Column(Integer, nullable=False, default=1)
    terminal = Column(Integer, nullable=False, default=1)
    estado = Column(String(10), nullable=False, default="ABIERTA")   # ABIERTA | CERRADA
    monto_apertura = Column(Numeric(18, 2), nullable=False, default=0)
    abierta_por = Column(String(200), nullable=True)
    abierta_en = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    monto_contado = Column(Numeric(18, 2), nullable=True)
    cerrada_por = Column(String(200), nullable=True)
    cerrada_en = Column(DateTime(timezone=True), nullable=True)
    notas = Column(Text, nullable=True)
    resumen = Column(JSONB, nullable=True)        # arqueo calculado al cerrar (no cambia después)

    movimientos = relationship("MovimientoCaja", back_populates="caja", cascade="all, delete-orphan",
                               order_by="MovimientoCaja.fecha")

    __table_args__ = (
        Index("uq_caja_abierta", "emisor_id", "sucursal", "terminal", unique=True,
              postgresql_where=text("estado = 'ABIERTA'")),
    )


class MovimientoCaja(Base):
    """Entrada o salida de efectivo que no es una venta (fondo extra, pago a proveedor, retiro)."""
    __tablename__ = "movimientos_caja"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    caja_id = Column(UUID(as_uuid=False), ForeignKey("cajas.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = Column(String(10), nullable=False)      # entrada | salida
    monto = Column(Numeric(18, 2), nullable=False)
    motivo = Column(String(200), nullable=False)
    usuario = Column(String(200), nullable=True)
    fecha = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    caja = relationship("Caja", back_populates="movimientos")


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


class Abono(Base):
    """
    Pago recibido de una factura a crédito comercial (condición 02). Hacienda no pide
    comprobante para estos cobros (a diferencia del recibo de pago de las condiciones
    08 y 10), así que se registran aquí para llevar la cuenta por cobrar.
    """
    __tablename__ = "abonos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="CASCADE"), nullable=False, index=True)
    fecha = Column(Date, nullable=False)
    monto = Column(Numeric(18, 5), nullable=False)          # en la moneda de la factura
    medio_pago = Column(String(2), nullable=False, default="04")
    referencia = Column(String(100), nullable=True)         # número de transferencia, SINPE, cheque…
    nota = Column(String(250), nullable=True)
    registrado_por = Column(String(200), nullable=True)
    anulado = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class FacturaRecurrente(Base):
    """
    Plantilla de un comprobante que se emite solo cada cierto tiempo (alquiler,
    mensualidad, servicio profesional). 'datos' es el mismo cuerpo de POST /facturas.
    """
    __tablename__ = "facturas_recurrentes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(120), nullable=False)
    datos = Column(JSONB, nullable=False)
    frecuencia = Column(String(10), nullable=False, default="mensual")   # semanal | quincenal | mensual | anual
    proxima = Column(Date, nullable=False, index=True)                  # próxima fecha de emisión
    hasta = Column(Date, nullable=True)                                  # última fecha (null = sin fin)
    activa = Column(Boolean, nullable=False, default=True)
    emitidas = Column(Integer, nullable=False, default=0)
    ultima_factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="SET NULL"), nullable=True)
    ultimo_error = Column(Text, nullable=True)
    creada_por = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Registro(Base):
    """Inscripción propia pendiente de confirmar por correo (solo se guarda el hash del enlace)."""
    __tablename__ = "registros"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    token_hash = Column(String(64), nullable=False, unique=True)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=True)
    usuario_id = Column(UUID(as_uuid=False), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    expira = Column(DateTime(timezone=True), nullable=False)
    confirmado = Column(DateTime(timezone=True), nullable=True)
    ip = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class SolicitudCompra(Base):
    """
    El cliente pagó por SINPE Móvil o transferencia y lo reporta desde el panel; el
    administrador revisa el pago y la aprueba (se acredita) o la rechaza.
    """
    __tablename__ = "solicitudes_compra"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id = Column(UUID(as_uuid=False), ForeignKey("planes.id", ondelete="SET NULL"), nullable=True)
    documentos = Column(Integer, nullable=False, default=0)
    meses_web = Column(Integer, nullable=False, default=0)
    monto = Column(Numeric(18, 2), nullable=False)
    moneda = Column(String(3), nullable=False, default="CRC")
    medio_pago = Column(String(2), nullable=False, default="06")
    referencia = Column(String(100), nullable=False)
    comprobante = Column(LargeBinary, nullable=True)        # foto o PDF del comprobante de pago
    comprobante_tipo = Column(String(40), nullable=True)
    estado = Column(String(10), nullable=False, default="PENDIENTE", index=True)   # PENDIENTE | APROBADA | RECHAZADA
    motivo = Column(String(300), nullable=True)
    solicitada_por = Column(String(200), nullable=True)
    resuelta_por = Column(String(200), nullable=True)
    resuelta_en = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class UsuarioEmpresa(Base):
    """
    Acceso de un usuario a una empresa más (el contador que atiende a varios clientes).
    Esos usuarios tienen emisor_id NULL y eligen la empresa en el selector del panel.
    """
    __tablename__ = "usuario_empresas"

    usuario_id = Column(UUID(as_uuid=False), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    rol = Column(String(20), nullable=False, default="contador", server_default="contador")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (PrimaryKeyConstraint("usuario_id", "emisor_id"),)


class CuentaContable(Base):
    """
    Cuenta del catálogo de una empresa. El código con puntos da la jerarquía
    (1 Activo, 1.1 Activo corriente, 1.1.01 Caja y bancos…). Solo las cuentas que
    aceptan movimientos llevan asientos; las demás suman a sus hijas.
    clave_sistema marca las cuentas que usan los asientos automáticos (ventas, IVA…).
    """
    __tablename__ = "cuentas_contables"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    nombre = Column(String(150), nullable=False)
    tipo = Column(String(10), nullable=False)          # activo | pasivo | patrimonio | ingreso | costo | gasto
    acepta_movimientos = Column(Boolean, nullable=False, default=True)
    clave_sistema = Column(String(30), nullable=True)
    activa = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("emisor_id", "codigo", name="uq_cuenta_emisor_codigo"),)


class Asiento(Base):
    """Asiento contable. Los automáticos guardan el comprobante que los originó en documento_ref."""
    __tablename__ = "asientos"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False)
    numero = Column(Integer, nullable=False)
    fecha = Column(Date, nullable=False)
    descripcion = Column(String(300), nullable=False)
    origen = Column(String(15), nullable=False, default="manual")   # manual | venta | compra | cobro | apertura
    documento_ref = Column(String(80), nullable=True)               # p. ej. factura:<id>, recibido:<id>, abono:<id>
    editado = Column(Boolean, nullable=False, default=False)        # automático que el contador corrigió a mano
    anulado = Column(Boolean, nullable=False, default=False)
    creado_por = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    lineas = relationship("AsientoLinea", back_populates="asiento", cascade="all, delete-orphan",
                          order_by="AsientoLinea.haber, AsientoLinea.id")

    __table_args__ = (
        UniqueConstraint("emisor_id", "numero", name="uq_asiento_numero"),
        Index("ix_asientos_emisor_fecha", "emisor_id", "fecha"),
        Index("uq_asiento_documento", "emisor_id", "documento_ref", unique=True,
              postgresql_where=text("documento_ref IS NOT NULL")),
    )


class AsientoLinea(Base):
    __tablename__ = "asiento_lineas"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    asiento_id = Column(UUID(as_uuid=False), ForeignKey("asientos.id", ondelete="CASCADE"), nullable=False, index=True)
    cuenta_id = Column(UUID(as_uuid=False), ForeignKey("cuentas_contables.id"), nullable=False, index=True)
    debe = Column(Numeric(18, 2), nullable=False, default=0)
    haber = Column(Numeric(18, 2), nullable=False, default=0)
    detalle = Column(String(200), nullable=True)

    asiento = relationship("Asiento", back_populates="lineas")
    cuenta = relationship("CuentaContable")


class PeriodoCerrado(Base):
    """Mes cerrado por el contador: ya no se pueden crear, cambiar ni anular asientos de ese mes."""
    __tablename__ = "periodos_cerrados"

    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=False)
    mes = Column(Date, nullable=False)        # día 1 del mes
    cerrado_por = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (PrimaryKeyConstraint("emisor_id", "mes"),)


class Contratacion(Base):
    """
    Servicio mensual que pidió un cliente (empresa o contador) con el precio de ese momento.
    Queda activo al pedirlo y se cobra en la factura mensual; hasta = día en que lo canceló.
    """
    __tablename__ = "contrataciones"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    cliente = Column(String(40), nullable=False)           # e:<emisor_id> o u:<usuario_id>
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=True)
    usuario_id = Column(UUID(as_uuid=False), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True)
    servicio = Column(String(20), nullable=False)          # facturacion_web | contabilidad | contador
    precio = Column(Numeric(18, 2), nullable=False)        # por mes
    moneda = Column(String(3), nullable=False, default="CRC")
    desde = Column(Date, nullable=False)
    hasta = Column(Date, nullable=True)
    gratis_hasta = Column(Date, nullable=True)             # prueba gratis: no se cobra hasta esa fecha
    creado_por = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_contrataciones_cliente", "cliente", "servicio"),)


class CobroMensual(Base):
    """Factura mensual de un cliente por los servicios del mes (proporcional a los días usados)."""
    __tablename__ = "cobros_mensuales"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    cliente = Column(String(40), nullable=False)
    emisor_id = Column(UUID(as_uuid=False), ForeignKey("emisores.id", ondelete="CASCADE"), nullable=True)
    usuario_id = Column(UUID(as_uuid=False), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True)
    periodo = Column(Date, nullable=False)                  # día 1 del mes cobrado
    lineas = Column(JSONB, nullable=False)                  # [{servicio, concepto, dias, monto}]
    total = Column(Numeric(18, 2), nullable=False)
    moneda = Column(String(3), nullable=False, default="CRC")
    emitido = Column(Date, nullable=False)
    vence = Column(Date, nullable=False)
    estado = Column(String(10), nullable=False, default="PENDIENTE", index=True)   # PENDIENTE | REPORTADO | PAGADO | ANULADO
    referencia_pago = Column(String(100), nullable=True)
    reportado_en = Column(DateTime(timezone=True), nullable=True)
    pagado_en = Column(DateTime(timezone=True), nullable=True)
    confirmado_por = Column(String(200), nullable=True)
    factura_id = Column(UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="SET NULL"), nullable=True)
    comprobante_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("cliente", "periodo", name="uq_cobro_cliente_periodo"),)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
