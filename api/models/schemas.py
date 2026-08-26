"""
Esquemas Pydantic: definen y validan lo que tu API recibe/devuelve.
Esto es lo que tus clientes (frontend, otros sistemas) van a consumir.
"""
import re
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, EmailStr, field_validator


class ProductoRequest(BaseModel):
    codigo_producto: Optional[str] = None
    descripcion: str
    cantidad: Decimal
    precio_unitario: Decimal
    impuesto_porcentaje: Decimal = Decimal("13.00")  # IVA general en CR

    @field_validator("cantidad", "precio_unitario")
    @classmethod
    def positivo(cls, v):
        if v <= 0:
            raise ValueError("Debe ser mayor a cero")
        return v


class ReceptorRequest(BaseModel):
    nombre: str
    tipo_identificacion: str  # 01 Física, 02 Jurídica, 03 DIMEX, 04 NITE
    numero_identificacion: str
    correo: Optional[EmailStr] = None

    @field_validator("numero_identificacion")
    @classmethod
    def validar_cedula(cls, v):
        if not v.isdigit():
            raise ValueError("La identificación debe contener solo dígitos")
        if not (9 <= len(v) <= 12):
            raise ValueError("Longitud de identificación inválida")
        return v


class FacturaRequest(BaseModel):
    receptor: ReceptorRequest
    productos: List[ProductoRequest]
    moneda: str = "CRC"
    tipo_cambio: Optional[Decimal] = None
    condicion_venta: str = "01"  # 01 Contado, 02 Crédito, etc.
    medio_pago: str = "01"       # 01 Efectivo, 02 Tarjeta, etc.
    notas: Optional[str] = None

    @field_validator("productos")
    @classmethod
    def al_menos_un_producto(cls, v):
        if not v:
            raise ValueError("Debe incluir al menos un producto o servicio")
        return v


class FacturaResponse(BaseModel):
    factura_id: str
    clave: str
    estado: str
    message: str


class FacturaDetalleResponse(BaseModel):
    factura_id: str
    clave: str
    numero_consecutivo: str
    estado: str
    estado_hacienda: Optional[str]
    mensaje_hacienda: Optional[str]
    monto_total: Decimal
    fecha_emision: datetime

    class Config:
        from_attributes = True


class CallbackHaciendaPayload(BaseModel):
    """Lo que Hacienda envía a nuestro callbackUrl cuando termina de procesar."""
    clave: str
    estado: str  # aceptado / rechazado
    respuestaXml: Optional[str] = None
    fecha: Optional[str] = None
