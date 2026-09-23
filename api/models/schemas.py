"""
Esquemas Pydantic: definen y validan lo que tu API recibe/devuelve.
Esto es lo que tus clientes (frontend, POS, ERP, otros sistemas) van a consumir.

⚠️ Las tablas de códigos siguen los anexos v4.4; confirmalas contra la
versión vigente publicada por Hacienda.
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator

# CodigoTarifaIVA (v4.4) -> tarifa en %
TARIFAS_IVA = {
    "01": Decimal("0"),    # Tarifa 0% (exento con derecho a crédito, Art. 32)
    "02": Decimal("1"),    # Tarifa reducida 1%
    "03": Decimal("2"),    # Tarifa reducida 2%
    "04": Decimal("4"),    # Tarifa reducida 4%
    "05": Decimal("0"),    # Transitorio 0%
    "06": Decimal("4"),    # Transitorio 4%
    "07": Decimal("8"),    # Transitorio 8%
    "08": Decimal("13"),   # Tarifa general 13%
    "09": Decimal("0.5"),  # Tarifa reducida 0.5%
    "10": Decimal("0"),    # Tarifa exenta
    "11": Decimal("0"),    # Tarifa 0% sin derecho a crédito
}

# Códigos de impuesto que son IVA (usan CodigoTarifaIVA)
CODIGOS_IVA = {"01", "07", "08"}
# Impuestos específicos no tarifarios (requieren DatosImpuestoEspecifico)
CODIGOS_ESPECIFICOS = {"03", "04", "05", "06"}
# Impuestos que forman parte de la base imponible del IVA (según el XSD oficial)
CODIGOS_EN_BASE_IVA = {"02", "04", "05", "12"}

# Unidades de medida que corresponden a servicios (el resto se trata como mercancía)
UNIDADES_SERVICIO = {"Sp", "Spe", "St", "Os", "Al", "Alc", "Cm", "I", "h"}

TipoIdentificacion = Literal["01", "02", "03", "04", "05", "06"]
Ambiente = Literal["stag", "prod"]

# tipo_documento de la API -> descripción
TIPOS_COMPROBANTE = {
    "01": "Factura electrónica",
    "02": "Nota de débito electrónica",
    "03": "Nota de crédito electrónica",
    "04": "Tiquete electrónico",
    "08": "Factura electrónica de compra",
    "09": "Factura electrónica de exportación",
    "10": "Recibo electrónico de pago",
}

# Longitudes válidas del número de identificación por tipo
_LONGITUD_IDENTIFICACION = {
    "01": (9, 9),     # Cédula física
    "02": (10, 10),   # Cédula jurídica
    "03": (11, 12),   # DIMEX
    "04": (10, 10),   # NITE
}

Cod2 = r"^\d{2}$"


def validar_numero_identificacion(tipo: str, numero: str) -> str:
    numero = numero.strip()
    rango = _LONGITUD_IDENTIFICACION.get(tipo)
    if rango:
        if not numero.isdigit():
            raise ValueError("La identificación debe contener solo dígitos")
        if not rango[0] <= len(numero) <= rango[1]:
            largo = str(rango[0]) if rango[0] == rango[1] else f"{rango[0]}-{rango[1]}"
            raise ValueError(f"Una identificación tipo {tipo} debe tener {largo} dígitos")
    elif not numero.isalnum():
        raise ValueError("La identificación solo puede contener letras y dígitos")
    return numero


# --------------------------------------------------------------------------
# Personas (receptor / proveedor)
# --------------------------------------------------------------------------

class UbicacionRequest(BaseModel):
    provincia: str = Field(pattern=r"^[1-7]$")
    canton: str = Field(pattern=r"^\d{2}$")
    distrito: str = Field(pattern=r"^\d{2}$")
    barrio: Optional[str] = Field(default=None, max_length=50)
    otras_senas: str = Field(min_length=1, max_length=250)


class PersonaRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    tipo_identificacion: Optional[TipoIdentificacion] = None
    numero_identificacion: Optional[str] = Field(default=None, min_length=1, max_length=20)
    identificacion_extranjero: Optional[str] = Field(default=None, max_length=20)
    nombre_comercial: Optional[str] = Field(default=None, max_length=80)
    ubicacion: Optional[UbicacionRequest] = None
    otras_senas_extranjero: Optional[str] = Field(default=None, max_length=300)
    telefono_codigo_pais: str = Field(default="506", pattern=r"^\d{1,3}$")
    telefono: Optional[str] = Field(default=None, pattern=r"^\d{8,20}$")
    correo: Optional[EmailStr] = None
    codigo_actividad: Optional[str] = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def validar_identificacion(self):
        if not self.numero_identificacion and self.identificacion_extranjero:
            # En v4.4 los extranjeros se identifican con tipo 05 (Extranjero No Domiciliado)
            self.tipo_identificacion = "05"
            self.numero_identificacion = self.identificacion_extranjero
        if self.numero_identificacion:
            if not self.tipo_identificacion:
                raise ValueError("tipo_identificacion es obligatorio cuando se indica numero_identificacion")
            self.numero_identificacion = validar_numero_identificacion(
                self.tipo_identificacion, self.numero_identificacion
            )
        else:
            raise ValueError("Indique numero_identificacion o identificacion_extranjero")
        return self

    @property
    def identificado_en_cr(self) -> bool:
        return bool(self.numero_identificacion) and self.tipo_identificacion in ("01", "02", "03", "04")


# Compatibilidad: el receptor es una persona
ReceptorRequest = PersonaRequest


# --------------------------------------------------------------------------
# Líneas, impuestos, exoneraciones
# --------------------------------------------------------------------------

class ExoneracionRequest(BaseModel):
    tipo_documento: str = Field(pattern=Cod2, description="Tipo de documento de exoneración (TipoDocumentoEX1)")
    tipo_documento_otro: Optional[str] = Field(default=None, max_length=100)
    numero_documento: str = Field(min_length=1, max_length=40, description="Número de autorización, p. ej. AL-00000000-24")
    articulo: Optional[int] = Field(default=None, ge=0, le=999999)
    inciso: Optional[int] = Field(default=None, ge=0, le=999999)
    nombre_institucion: str = Field(pattern=Cod2, description="Código de la institución que emite la exoneración")
    nombre_institucion_otros: Optional[str] = Field(default=None, max_length=160)
    fecha_emision: datetime
    tarifa_exonerada: Decimal = Field(gt=0, le=13, description="Puntos porcentuales de IVA exonerados (13 = total)")


class DatosImpuestoEspecificoRequest(BaseModel):
    """Datos para impuestos específicos no tarifarios (códigos 03, 04, 05 y 06)."""
    cantidad_unidad_medida: Optional[Decimal] = Field(default=None, ge=0)
    porcentaje: Optional[Decimal] = Field(default=None, ge=0, le=100, description="Obligatorio con código 04")
    proporcion: Optional[Decimal] = Field(default=None, ge=0, description="Obligatorio con código 04")
    volumen_unidad_consumo: Optional[Decimal] = Field(default=None, ge=0, description="Obligatorio con código 05")
    impuesto_unidad: Decimal = Field(ge=0)


class ImpuestoRequest(BaseModel):
    """Impuesto de una línea. Si la línea no trae 'impuestos', se usa IVA con codigo_tarifa_iva."""
    codigo: str = Field(pattern=Cod2, description=(
        "01 IVA, 02 Selectivo de consumo, 03 Combustibles, 04 Bebidas alcohólicas, 05 Bebidas envasadas "
        "y jabones, 06 Tabaco, 07 IVA cálculo especial, 08 IVA bienes usados (factor), 12 Cemento, 99 Otros"))
    codigo_impuesto_otro: Optional[str] = Field(default=None, max_length=100)
    codigo_tarifa_iva: Optional[str] = None
    tarifa: Optional[Decimal] = Field(default=None, ge=0, le=100)
    factor_calculo_iva: Optional[Decimal] = Field(default=None, gt=0, le=1,
                                                  description="Obligatorio con código 08 (factor definido por Hacienda)")
    datos_especificos: Optional[DatosImpuestoEspecificoRequest] = None
    monto: Optional[Decimal] = Field(default=None, ge=0, description="Monto fijo (impuestos específicos)")

    @model_validator(mode="after")
    def validar(self):
        if self.codigo in CODIGOS_IVA:
            if self.codigo_tarifa_iva not in TARIFAS_IVA:
                raise ValueError(f"codigo_tarifa_iva inválido para IVA; valores válidos: {sorted(TARIFAS_IVA)}")
            if self.codigo == "08" and self.factor_calculo_iva is None:
                raise ValueError("El IVA de bienes usados (código 08) requiere factor_calculo_iva")
        elif self.codigo in CODIGOS_ESPECIFICOS:
            if self.datos_especificos is None or self.monto is None:
                raise ValueError(f"El impuesto específico {self.codigo} requiere datos_especificos y monto")
            if self.codigo == "04" and (self.datos_especificos.porcentaje is None or self.datos_especificos.proporcion is None):
                raise ValueError("El impuesto a bebidas alcohólicas (04) requiere porcentaje y proporcion")
            if self.codigo == "05" and self.datos_especificos.volumen_unidad_consumo is None:
                raise ValueError("El impuesto a bebidas envasadas (05) requiere volumen_unidad_consumo")
        elif self.tarifa is None and self.monto is None:
            raise ValueError("Los impuestos distintos de IVA requieren 'tarifa' o 'monto'")
        if self.codigo == "99" and not self.codigo_impuesto_otro:
            raise ValueError("codigo_impuesto_otro es obligatorio con codigo 99")
        return self


class LineaRequest(BaseModel):
    codigo_cabys: str = Field(pattern=r"^\d{13}$", description="Código CABYS de 13 dígitos")
    codigo_comercial: Optional[str] = Field(default=None, max_length=20)
    partida_arancelaria: Optional[str] = Field(default=None, pattern=r"^\d{12}$",
                                               description="Obligatoria para mercancías en exportación (09)")
    descripcion: str = Field(min_length=1, max_length=200)
    cantidad: Decimal = Field(gt=0, max_digits=16, decimal_places=3)
    unidad_medida: str = Field(default="Unid", max_length=15)
    unidad_medida_comercial: Optional[str] = Field(default=None, max_length=20)
    tipo_transaccion: Optional[str] = Field(default=None, pattern=Cod2)
    es_servicio: Optional[bool] = Field(default=None, description="Si se omite se deduce de la unidad de medida")
    precio_unitario: Decimal = Field(ge=0, max_digits=18, decimal_places=5)
    descuento: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=5)
    codigo_descuento: Optional[str] = Field(default=None, pattern=Cod2)
    codigo_descuento_otro: Optional[str] = Field(default=None, max_length=100)
    naturaleza_descuento: Optional[str] = Field(default=None, max_length=80)
    codigo_tarifa_iva: str = Field(default="08", description="08 = tarifa general 13%")
    impuestos: Optional[List[ImpuestoRequest]] = Field(default=None, max_length=10)
    exoneracion: Optional[ExoneracionRequest] = None
    iva_cobrado_fabrica: Optional[Literal["01", "02"]] = Field(
        default=None,
        description="01 IVA cobrado a nivel de fábrica (el emisor no lo vuelve a cobrar), "
                    "02 venta exenta según el sistema especial de fábrica (sin IVA)",
    )
    impuesto_asumido_emisor: bool = Field(default=False, description="El emisor asume el impuesto (no se cobra al cliente)")
    no_sujeto: bool = Field(default=False, description="Bien o servicio no sujeto a IVA")

    @field_validator("codigo_tarifa_iva")
    @classmethod
    def tarifa_conocida(cls, v):
        if v not in TARIFAS_IVA:
            raise ValueError(f"codigo_tarifa_iva inválido; valores válidos: {sorted(TARIFAS_IVA)}")
        return v

    @model_validator(mode="after")
    def validar(self):
        sin_iva = self.no_sujeto or self.iva_cobrado_fabrica == "02"
        if sin_iva and self.impuestos and any(i.codigo in CODIGOS_IVA for i in self.impuestos):
            raise ValueError("Una línea no sujeta o exenta por sistema de fábrica no lleva IVA")
        if sin_iva and self.exoneracion:
            raise ValueError("Una línea sin IVA no puede llevar exoneración")
        if self.no_sujeto and self.iva_cobrado_fabrica:
            raise ValueError("no_sujeto e iva_cobrado_fabrica son excluyentes")
        if self.descuento > 0:
            if not self.codigo_descuento:
                raise ValueError("codigo_descuento es obligatorio cuando hay descuento")
            if self.codigo_descuento == "99" and not self.codigo_descuento_otro:
                raise ValueError("codigo_descuento_otro es obligatorio con codigo_descuento 99")
            if self.descuento > self.cantidad * self.precio_unitario:
                raise ValueError("El descuento no puede ser mayor al monto de la línea")
        if self.exoneracion:
            ivas = [i for i in self.impuestos_efectivos if i.codigo == "01"]
            if not ivas:
                raise ValueError("La exoneración aplica sobre el IVA (código 01) y la línea no lo tiene")
            if self.exoneracion.tarifa_exonerada > TARIFAS_IVA[ivas[0].codigo_tarifa_iva]:
                raise ValueError("tarifa_exonerada no puede ser mayor que la tarifa de IVA de la línea")
        return self

    @property
    def servicio(self) -> bool:
        if self.es_servicio is not None:
            return self.es_servicio
        return self.unidad_medida in UNIDADES_SERVICIO

    @property
    def impuestos_efectivos(self) -> List[ImpuestoRequest]:
        if self.impuestos:
            return self.impuestos
        if self.no_sujeto or self.iva_cobrado_fabrica == "02":
            return []
        return [ImpuestoRequest(codigo="01", codigo_tarifa_iva=self.codigo_tarifa_iva)]

    @property
    def tarifa_iva_principal(self) -> Optional[str]:
        for imp in self.impuestos_efectivos:
            if imp.codigo in CODIGOS_IVA:
                return imp.codigo_tarifa_iva
        return None


class OtroCargoRequest(BaseModel):
    tipo_documento: str = Field(pattern=Cod2, description="06 = impuesto de servicio 10%, 99 = otros...")
    tipo_documento_otros: Optional[str] = Field(default=None, max_length=100)
    tercero_tipo_identificacion: Optional[TipoIdentificacion] = None
    tercero_identificacion: Optional[str] = Field(default=None, max_length=20)
    tercero_nombre: Optional[str] = Field(default=None, max_length=100)
    detalle: str = Field(min_length=1, max_length=160)
    porcentaje: Optional[Decimal] = Field(default=None, gt=0, le=100)
    monto: Optional[Decimal] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validar(self):
        if self.monto is None and self.porcentaje is None:
            raise ValueError("Indique 'monto' o 'porcentaje' del cargo")
        if self.tipo_documento == "99" and not self.tipo_documento_otros:
            raise ValueError("tipo_documento_otros es obligatorio con tipo_documento 99")
        return self


class MedioPagoRequest(BaseModel):
    tipo: str = Field(default="01", pattern=Cod2,
                      description="01 Efectivo, 02 Tarjeta, 03 Cheque, 04 Transferencia, 05 Recaudado por terceros, 06 SINPE Móvil, 07 Plataforma digital, 99 Otros")
    tipo_otros: Optional[str] = Field(default=None, max_length=100)
    monto: Optional[Decimal] = Field(default=None, gt=0)


class ReferenciaRequest(BaseModel):
    """Documento al que hace referencia una nota de crédito/débito u otro comprobante."""
    tipo_documento: str = Field(pattern=Cod2)
    tipo_documento_otro: Optional[str] = Field(default=None, max_length=100)
    numero: Optional[str] = Field(default=None, min_length=1, max_length=50, description="Clave de 50 dígitos del documento referido")
    fecha_emision: datetime
    codigo: Optional[str] = Field(default=None, pattern=Cod2, description="01 Anula, 02 Corrige texto, 04 Referencia, 06 Devolución...")
    codigo_otro: Optional[str] = Field(default=None, max_length=100)
    razon: Optional[str] = Field(default=None, max_length=180)


class FacturaRequest(BaseModel):
    tipo_documento: Literal["01", "02", "03", "04", "08", "09"] = Field(
        default="01", description=", ".join(f"{k} {v}" for k, v in TIPOS_COMPROBANTE.items())
    )
    sucursal: int = Field(default=1, ge=1, le=999)
    terminal: int = Field(default=1, ge=1, le=99_999)
    referencia_externa: Optional[str] = Field(
        default=None, max_length=100,
        description="ID del documento en tu sistema. Si se repite, se devuelve el comprobante ya creado (idempotencia).",
    )
    codigo_actividad_emisor: Optional[str] = Field(
        default=None, pattern=r"^\d{6}$", description="Si el emisor tiene varias actividades; por defecto la registrada"
    )
    receptor: Optional[PersonaRequest] = None
    proveedor: Optional[PersonaRequest] = Field(default=None, description="Vendedor (solo factura de compra 08)")
    codigo_actividad_receptor: Optional[str] = Field(default=None, pattern=r"^\d{6}$")
    productos: List[LineaRequest] = Field(min_length=1, max_length=1000)
    otros_cargos: List[OtroCargoRequest] = Field(default_factory=list, max_length=15)
    moneda: str = Field(default="CRC", pattern=r"^[A-Z]{3}$")
    tipo_cambio: Optional[Decimal] = Field(default=None, gt=0, description="Si se omite en USD/EUR se consulta a Hacienda")
    condicion_venta: str = Field(default="01", pattern=Cod2)
    condicion_venta_otros: Optional[str] = Field(default=None, max_length=100)
    plazo_credito: Optional[int] = Field(default=None, ge=1, le=99_999)
    medios_pago: List[MedioPagoRequest] = Field(default_factory=lambda: [MedioPagoRequest()], min_length=1, max_length=4)
    referencia: Optional[ReferenciaRequest] = None
    referencias: List[ReferenciaRequest] = Field(default_factory=list, max_length=10)
    notas: Optional[str] = Field(default=None, max_length=1000)
    iva_devuelto: Optional[Decimal] = Field(
        default=None, gt=0, description="IVA devuelto (servicios de salud pagados con tarjeta)")
    situacion: Literal["1", "2", "3"] = Field(
        default="1",
        description="1 Normal, 2 Contingencia (sustituye un comprobante provisional en papel), "
                    "3 Sin internet (emitido cuando no había conexión)",
    )
    fecha_emision: Optional[datetime] = Field(
        default=None, description="Solo en situación 2/3: fecha y hora reales de la venta (hora de Costa Rica si no trae zona)")

    @model_validator(mode="after")
    def reglas_de_negocio(self):
        if self.referencia:
            self.referencias = [self.referencia, *self.referencias]
            self.referencia = None

        if self.situacion == "1" and self.fecha_emision is not None:
            raise ValueError("fecha_emision solo se indica en situación 2 (contingencia) o 3 (sin internet)")
        if self.situacion in ("2", "3") and self.fecha_emision is None:
            raise ValueError("En contingencia o sin internet indique fecha_emision (fecha real de la venta)")
        if self.situacion == "2" and not any(r.tipo_documento == "08" and r.codigo == "05" for r in self.referencias):
            raise ValueError(
                "En contingencia (situación 2) incluya una referencia al comprobante provisional: "
                "tipo_documento 08 y codigo 05 (sustituye comprobante provisional por contingencia)"
            )
        if self.iva_devuelto is not None and self.tipo_documento not in ("01", "04"):
            raise ValueError("iva_devuelto solo aplica a factura (01) o tiquete (04)")

        t = self.tipo_documento
        if t in ("01", "09") and self.receptor is None:
            raise ValueError("Este comprobante requiere receptor (use tipo_documento 04 para tiquete)")
        if t == "08":
            if self.proveedor is None:
                raise ValueError("La factura de compra (08) requiere 'proveedor'")
            if not self.referencias:
                raise ValueError(
                    "La factura de compra (08) requiere 'referencia' (p. ej. tipo_documento 14 régimen especial "
                    "o 16 proveedor no domiciliado)"
                )
        elif self.proveedor is not None:
            raise ValueError("'proveedor' solo aplica a la factura de compra (08)")
        if t in ("02", "03") and not self.referencias:
            raise ValueError("Las notas de crédito/débito requieren 'referencia' al documento original")
        if t == "09":
            for i, p in enumerate(self.productos, start=1):
                if not p.servicio and not p.partida_arancelaria:
                    raise ValueError(f"Línea {i}: partida_arancelaria es obligatoria en exportación de mercancías")
                if p.exoneracion:
                    raise ValueError(f"Línea {i}: la factura de exportación no admite exoneraciones")
        if self.condicion_venta == "02" and not self.plazo_credito:
            raise ValueError("plazo_credito es obligatorio para ventas a crédito (condicion_venta 02)")
        if self.condicion_venta == "99" and not self.condicion_venta_otros:
            raise ValueError("condicion_venta_otros es obligatorio con condicion_venta 99")
        if len(self.medios_pago) > 1 and any(m.monto is None for m in self.medios_pago):
            raise ValueError("Con varios medios de pago cada uno debe indicar su monto")
        if any(m.tipo == "99" and not m.tipo_otros for m in self.medios_pago):
            raise ValueError("tipo_otros es obligatorio con medio de pago 99")
        return self


class ReciboPagoRequest(BaseModel):
    """Pago (total o parcial) de una factura a crédito con condición 08 o 10."""
    monto: Decimal = Field(gt=0, description="Monto pagado, IVA incluido, en la moneda de la factura")
    medios_pago: List[MedioPagoRequest] = Field(default_factory=lambda: [MedioPagoRequest(tipo="04")], min_length=1, max_length=4)
    referencia_externa: Optional[str] = Field(default=None, max_length=100)
    sucursal: Optional[int] = Field(default=None, ge=1, le=999, description="Por defecto la de la factura")
    terminal: Optional[int] = Field(default=None, ge=1, le=99_999, description="Por defecto la de la factura")

    @model_validator(mode="after")
    def validar(self):
        if len(self.medios_pago) > 1 and any(m.monto is None for m in self.medios_pago):
            raise ValueError("Con varios medios de pago cada uno debe indicar su monto")
        return self


class AnularRequest(BaseModel):
    razon: str = Field(min_length=1, max_length=180)
    referencia_externa: Optional[str] = Field(default=None, max_length=100)


class CorreoRequest(BaseModel):
    destinatarios: Optional[List[EmailStr]] = Field(default=None, max_length=10)


class FacturaResponse(BaseModel):
    factura_id: str
    clave: str
    estado: str
    message: str


class FacturaDetalleResponse(BaseModel):
    factura_id: str
    emisor_id: str
    referencia_externa: Optional[str]
    tipo_documento: str
    clave: str
    numero_consecutivo: str
    estado: str
    estado_hacienda: Optional[str]
    mensaje_hacienda: Optional[str]
    receptor_nombre: Optional[str]
    receptor_identificacion: Optional[str]
    moneda: str
    tipo_cambio: Optional[Decimal]
    total_venta: Decimal
    total_descuentos: Decimal
    total_otros_cargos: Decimal
    monto_impuesto: Decimal
    monto_total: Decimal
    fecha_emision: datetime
    correo_enviado: bool
    situacion: str = "1"
    total_exento: Decimal = Decimal("0")
    total_exonerado: Decimal = Decimal("0")
    total_no_sujeto: Decimal = Decimal("0")
    total_iva_devuelto: Decimal = Decimal("0")
    condicion_venta: Optional[str] = None
    factura_origen_id: Optional[str] = None


class EventoResponse(BaseModel):
    evento: str
    detalle: Optional[str]
    fecha: datetime


# --------------------------------------------------------------------------
# Emisores y API keys (administración)
# --------------------------------------------------------------------------

class EmisorBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    nombre_comercial: Optional[str] = Field(default=None, max_length=80)
    codigo_actividad: str = Field(pattern=r"^\d{6}$")
    correo: EmailStr
    telefono_codigo_pais: Optional[str] = Field(default="506", pattern=r"^\d{1,3}$")
    telefono: Optional[str] = Field(default=None, pattern=r"^\d{8,20}$")
    provincia: str = Field(pattern=r"^[1-7]$")
    canton: str = Field(pattern=r"^\d{2}$")
    distrito: str = Field(pattern=r"^\d{2}$")
    barrio: Optional[str] = Field(default=None, max_length=50)
    otras_senas: str = Field(min_length=1, max_length=250)
    proveedor_sistemas: Optional[str] = Field(default=None, pattern=r"^\d{9,12}$")
    registro_fiscal_8707: Optional[str] = Field(default=None, pattern=r"^\d{1,12}$",
                                                description="Registro de bebidas alcohólicas (Ley 8707)")
    ambiente: Ambiente = "stag"


class EmisorCrear(EmisorBase):
    tipo_identificacion: Literal["01", "02", "03", "04"]
    numero_identificacion: str

    @model_validator(mode="after")
    def validar_identificacion(self):
        self.numero_identificacion = validar_numero_identificacion(
            self.tipo_identificacion, self.numero_identificacion
        )
        return self


class EmisorActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    nombre_comercial: Optional[str] = Field(default=None, max_length=80)
    codigo_actividad: Optional[str] = Field(default=None, pattern=r"^\d{6}$")
    correo: Optional[EmailStr] = None
    telefono_codigo_pais: Optional[str] = Field(default=None, pattern=r"^\d{1,3}$")
    telefono: Optional[str] = Field(default=None, pattern=r"^\d{8,20}$")
    provincia: Optional[str] = Field(default=None, pattern=r"^[1-7]$")
    canton: Optional[str] = Field(default=None, pattern=r"^\d{2}$")
    distrito: Optional[str] = Field(default=None, pattern=r"^\d{2}$")
    barrio: Optional[str] = Field(default=None, max_length=50)
    otras_senas: Optional[str] = Field(default=None, min_length=1, max_length=250)
    proveedor_sistemas: Optional[str] = Field(default=None, pattern=r"^\d{9,12}$")
    registro_fiscal_8707: Optional[str] = Field(default=None, pattern=r"^\d{1,12}$",
                                                description="Registro de bebidas alcohólicas (Ley 8707)")
    ambiente: Optional[Ambiente] = None
    activo: Optional[bool] = None


class EmisorResponse(EmisorBase):
    id: str
    tipo_identificacion: str
    numero_identificacion: str
    activo: bool
    tiene_credenciales_hacienda: bool
    hacienda_usuario: Optional[str]
    tiene_certificado: bool
    cert_sujeto: Optional[str]
    cert_vence: Optional[datetime]
    webhook_url: Optional[str]
    saldo_documentos: Optional[int] = None


class CredencialesHaciendaRequest(BaseModel):
    usuario: str = Field(min_length=5, max_length=100, description="Usuario del API de comprobantes (cpf-/cpj-...@...comprobanteselectronicos.go.cr)")
    password: str = Field(min_length=1, max_length=200)


class WebhookRequest(BaseModel):
    url: Optional[HttpUrl] = Field(default=None, description="null para desactivar")


class ApiKeyCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    emisor_id: Optional[str] = Field(default=None, description="Emisor al que queda restringida la llave")
    es_admin: bool = False

    @model_validator(mode="after")
    def validar(self):
        if self.es_admin == bool(self.emisor_id):
            raise ValueError("Una llave es de administrador (es_admin=true) o de un emisor (emisor_id), no ambas ni ninguna")
        return self


class ApiKeyResponse(BaseModel):
    id: str
    nombre: str
    prefijo: str
    es_admin: bool
    emisor_id: Optional[str]
    activa: bool
    ultimo_uso: Optional[datetime]
    created_at: datetime
    api_key: Optional[str] = Field(default=None, description="Solo se muestra al crearla")


# --------------------------------------------------------------------------
# Documentos recibidos / Mensaje Receptor
# --------------------------------------------------------------------------

class DocumentoRecibidoRequest(BaseModel):
    xml_base64: str = Field(min_length=10, description="XML del comprobante del proveedor en base64")
    respuesta_hacienda_base64: Optional[str] = Field(default=None, description="MensajeHacienda que envió el proveedor (opcional)")


class MensajeReceptorRequest(BaseModel):
    mensaje: Literal["1", "2", "3"] = Field(description="1 Aceptado, 2 Aceptado parcialmente, 3 Rechazado")
    detalle_mensaje: Optional[str] = Field(default=None, max_length=160)
    codigo_actividad: Optional[str] = Field(default=None, pattern=r"^\d{6}$")
    condicion_impuesto: Optional[str] = Field(
        default=None, pattern=Cod2,
        description="01 Crédito IVA general, 02 Crédito parcial, 03 Bienes de capital, 04 Gasto corriente sin crédito, 05 Proporcionalidad",
    )
    monto_impuesto_acreditar: Optional[Decimal] = Field(default=None, ge=0)
    monto_gasto_aplicable: Optional[Decimal] = Field(default=None, ge=0)
    sucursal: int = Field(default=1, ge=1, le=999)
    terminal: int = Field(default=1, ge=1, le=99_999)

    @model_validator(mode="after")
    def validar(self):
        if self.mensaje in ("2", "3") and not self.detalle_mensaje:
            raise ValueError("detalle_mensaje es obligatorio para aceptación parcial o rechazo")
        return self


class DocumentoRecibidoResponse(BaseModel):
    id: str
    emisor_id: str
    clave: str
    tipo_documento: Optional[str]
    fecha_emision: Optional[datetime]
    proveedor_identificacion: str
    proveedor_nombre: Optional[str]
    moneda: str
    total_impuesto: Decimal
    total_comprobante: Decimal
    firma_valida: Optional[bool]
    mensaje: Optional[str]
    condicion_impuesto: Optional[str]
    monto_impuesto_acreditar: Optional[Decimal]
    consecutivo_receptor: Optional[str]
    estado: Optional[str]
    estado_hacienda: Optional[str]
    mensaje_hacienda: Optional[str]


# --------------------------------------------------------------------------
# Usuarios del panel web
# --------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UsuarioResponse(BaseModel):
    id: str
    email: str
    nombre: str
    es_admin: bool
    emisor_id: Optional[str]
    activo: bool
    ultimo_login: Optional[datetime]


class LoginResponse(BaseModel):
    token: str
    expira: datetime
    usuario: UsuarioResponse


class UsuarioCrear(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10, max_length=200, description="Mínimo 10 caracteres")
    es_admin: bool = False
    emisor_id: Optional[str] = None

    @model_validator(mode="after")
    def validar(self):
        if self.es_admin == bool(self.emisor_id):
            raise ValueError("Un usuario es administrador (todas las empresas) o de una empresa (emisor_id)")
        return self


class UsuarioActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    password: Optional[str] = Field(default=None, min_length=10, max_length=200)
    activo: Optional[bool] = None


class CambioPasswordRequest(BaseModel):
    actual: str = Field(min_length=1, max_length=200)
    nueva: str = Field(min_length=10, max_length=200)


# --------------------------------------------------------------------------
# Venta por consumo: planes y paquetes de documentos
# --------------------------------------------------------------------------

class PlanCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=300)
    documentos: int = Field(gt=0, le=10_000_000)
    precio: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    moneda: Literal["CRC", "USD"] = "CRC"
    dias_vigencia: Optional[int] = Field(default=None, gt=0, le=3650, description="Vacío = no vence")


class PlanActualizar(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=80)
    descripcion: Optional[str] = Field(default=None, max_length=300)
    precio: Optional[Decimal] = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    dias_vigencia: Optional[int] = Field(default=None, gt=0, le=3650)
    activo: Optional[bool] = None


class PlanResponse(PlanCrear):
    id: str
    activo: bool


class AcreditarRequest(BaseModel):
    """Acredita un paquete a una empresa: desde un plan o con cantidad libre (p. ej. cortesía)."""
    plan_id: Optional[str] = None
    documentos: Optional[int] = Field(default=None, gt=0, le=10_000_000)
    precio: Optional[Decimal] = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    moneda: Optional[Literal["CRC", "USD"]] = None
    dias_vigencia: Optional[int] = Field(default=None, gt=0, le=3650)
    nombre: Optional[str] = Field(default=None, max_length=80)
    referencia_pago: Optional[str] = Field(default=None, max_length=100, description="Comprobante SINPE, transferencia…")
    notas: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validar(self):
        if not self.plan_id and not self.documentos:
            raise ValueError("Indique plan_id o la cantidad de documentos")
        return self
