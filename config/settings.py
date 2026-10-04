"""
Configuración central del proyecto.
Todo lo sensible viene de variables de entorno (.env), nunca hardcodeado.

Los datos de cada empresa emisora (certificado, credenciales de Hacienda,
dirección, etc.) NO van aquí: se registran por API en la tabla `emisores`
y los secretos se guardan cifrados con MASTER_KEY.
"""
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Endpoints oficiales de Hacienda por ambiente. "stag" usa un realm y un
# host distintos a producción: mezclarlos significa enviar comprobantes de
# prueba a producción (o no poder autenticarse).
HACIENDA_ENDPOINTS = {
    "stag": {
        "token_url": "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut-stag/protocol/openid-connect/token",
        "api_base": "https://api-sandbox.comprobanteselectronicos.go.cr/recepcion/v1",
        "client_id": "api-stag",
    },
    "prod": {
        "token_url": "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token",
        "api_base": "https://api.comprobanteselectronicos.go.cr/recepcion/v1",
        "client_id": "api-prod",
    },
}

Ambiente = Literal["stag", "prod"]


class Settings(BaseSettings):
    # hide_input_in_errors: que un error de configuración no imprima secretos en los logs
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    # --- Ambiente de la aplicación ---
    # "stag" = pruebas, "prod" = producción. Cada emisor tiene además su propio
    # ambiente de Hacienda (un emisor puede estar en pruebas mientras otro ya factura).
    AMBIENTE: Ambiente = "stag"
    TIMEZONE: str = "America/Costa_Rica"

    # --- Base de datos / Redis ---
    DATABASE_URL: str = "postgresql+psycopg2://facturacion:facturacion@db:5432/facturacion"
    REDIS_URL: str = "redis://redis:6379/0"

    # --- Cifrado de secretos de los emisores (certificados, contraseñas) ---
    # Clave Fernet. Generar con: python -m api.cli generar-master-key
    # ⚠️ Si se pierde, los certificados y contraseñas guardados no se pueden recuperar.
    MASTER_KEY: str = ""

    # --- Hacienda ---
    HACIENDA_PUBLIC_API: str = "https://api.hacienda.go.cr"

    # --- Política de firma XAdES-EPES ---
    FIRMA_POLICY_URL: str = (
        "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/"
        "Resoluci%C3%B3n_General_sobre_disposiciones_t%C3%A9cnicas_comprobantes_electr%C3%B3nicos_para_efectos_tributarios.pdf"
    )
    # Digest SHA-256 (base64) del documento de política (calculado sobre el PDF
    # publicado en FIRMA_POLICY_URL el 2026-09-23). Si Hacienda publica una nueva
    # política, actualizar ambos valores; vacío = se calcula descargando la URL.
    FIRMA_POLICY_DIGEST: str = "DWxin1xWOeI8OuWQXazh4VjLWAaCLAA954em7DMh0h8="

    # --- Validación XSD (muy recomendado) ---
    XSD_DIR: str = ""
    # Verificar que cada código CABYS exista en el catálogo de Hacienda antes de firmar
    # (consulta cacheada 24 h; si el servicio de Hacienda no responde, no se bloquea la emisión)
    VALIDAR_CABYS: bool = True

    # --- Callback público (Hacienda debe poder alcanzar esta URL por HTTPS) ---
    CALLBACK_BASE_URL: str = "https://tu-dominio.com"
    CALLBACK_TOKEN: str = ""

    # --- Seguridad de la API ---
    # API keys de ADMINISTRADOR (arranque). Las llaves de los sistemas cliente
    # se crean por API y se guardan (hasheadas) en la base de datos.
    API_KEYS: str = ""
    CORS_ORIGINS: str = ""

    # --- Correo (envío de comprobantes al receptor) ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_STARTTLS: bool = True
    SMTP_SSL: bool = False

    # --- Envío ---
    MAX_INTENTOS_ENVIO: int = 10
    DIAS_ALERTA_CERTIFICADO: int = 30
    # Antigüedad máxima (días) de la fecha de un comprobante en contingencia / sin internet
    DIAS_MAX_CONTINGENCIA: int = 30

    # --- Panel web ---
    SESION_HORAS: int = 8
    MAX_INTENTOS_LOGIN: int = 5
    MINUTOS_BLOQUEO_LOGIN: int = 15

    # --- Venta por consumo (paquetes de documentos) ---
    # Si está activo, cada documento firmado y enviado descuenta 1 del saldo de la empresa.
    CONTROL_SALDO: bool = True
    SALDO_ALERTA_DOCUMENTOS: int = 20      # avisar cuando queden estos documentos
    DIAS_ALERTA_VENCIMIENTO_PAQUETE: int = 7

    # --- Límites de uso (por llave / usuario) ---
    LIMITE_SOLICITUDES_MINUTO: int = 300
    LIMITE_LOGIN_MINUTO: int = 20          # por IP
    LIMITE_FALLOS_AUTH_MINUTO: int = 30    # llaves/sesiones inválidas por IP
    # Publicar /docs (OpenAPI) también en producción para los integradores
    DOCS_PUBLICAS: bool = False
    # Verificación en dos pasos obligatoria para administradores del panel.
    # Sin definir: obligatoria en producción y opcional en pruebas.
    EXIGIR_2FA_ADMIN: bool | None = None

    @property
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.API_KEYS.split(",") if k.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @field_validator("EXIGIR_2FA_ADMIN", mode="before")
    @classmethod
    def _vacio_es_por_defecto(cls, valor):
        return None if isinstance(valor, str) and not valor.strip() else valor

    @property
    def exige_2fa_admin(self) -> bool:
        return self.AMBIENTE == "prod" if self.EXIGIR_2FA_ADMIN is None else self.EXIGIR_2FA_ADMIN

    @property
    def smtp_configurado(self) -> bool:
        return bool(self.SMTP_HOST and self.SMTP_FROM)

    @model_validator(mode="after")
    def _validar_produccion(self):
        """En producción nos negamos a arrancar con configuración insegura o incompleta."""
        if self.AMBIENTE != "prod":
            return self

        errores = []
        if not self.MASTER_KEY:
            errores.append("MASTER_KEY es obligatorio")
        else:
            try:
                from cryptography.fernet import Fernet
                Fernet(self.MASTER_KEY.encode())
            except (ValueError, TypeError):
                errores.append("MASTER_KEY no es una clave válida (genérela con: python -m api.cli generar-master-key)")
        clave_db = urlparse(self.DATABASE_URL).password or ""
        if clave_db in ("", "facturacion", "cambia-esta-contrasena") or len(clave_db) < 16:
            errores.append("La contraseña de la base de datos (DATABASE_URL) es débil o es la del ejemplo; use 16+ caracteres")
        if urlparse(self.CALLBACK_BASE_URL).scheme != "https" or "tu-dominio" in self.CALLBACK_BASE_URL:
            errores.append("CALLBACK_BASE_URL debe ser una URL https real")
        if len(self.CALLBACK_TOKEN) < 32:
            errores.append("CALLBACK_TOKEN debe tener al menos 32 caracteres")
        if any(len(k) < 32 for k in self.api_keys):
            errores.append("Las API_KEYS deben tener al menos 32 caracteres")
        if "*" in self.cors_origins:
            errores.append("CORS_ORIGINS no puede ser '*' en producción")

        if errores:
            raise ValueError("Configuración inválida para producción: " + "; ".join(errores))
        return self


def endpoints_hacienda(ambiente: str) -> dict:
    return HACIENDA_ENDPOINTS[ambiente]


@lru_cache
def get_settings() -> Settings:
    return Settings()
