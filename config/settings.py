"""
Configuración central del proyecto.
Todo lo sensible viene de variables de entorno (.env), nunca hardcodeado.
"""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Ambiente ---
    # "stag" = pruebas de Hacienda, "prod" = producción real
    AMBIENTE: str = "stag"

    # --- Base de datos ---
    DATABASE_URL: str = "postgresql+psycopg2://facturacion:facturacion@db:5432/facturacion"

    # --- Redis (cache de token + cola Celery) ---
    REDIS_URL: str = "redis://redis:6379/0"

    # --- Credenciales OIDC de Hacienda ---
    # Formato de usuario: cpf-01-1234-5678@comprobanteselectronicos.go.cr (persona física)
    #                  o: cpj-02-3101123456@comprobanteselectronicos.go.cr (persona jurídica)
    HACIENDA_USERNAME: str = ""
    HACIENDA_PASSWORD: str = ""

    # URLs oficiales de Hacienda (NO cambian entre ambientes, el ambiente se
    # define en el "sub" del JSON que se envía, ver services/hacienda_client.py)
    HACIENDA_TOKEN_URL: str = (
        "https://idp.comprobanteselectronicos.go.cr/auth/realms/rut/protocol/openid-connect/token"
    )
    HACIENDA_API_BASE: str = "https://api.comprobanteselectronicos.go.cr/recepcion/v1"

    # --- Certificado digital ---
    CERT_P12_PATH: str = "/app/certs/certificado.p12"
    CERT_P12_PASSWORD: str = ""

    # --- Emisor (tu empresa) ---
    EMISOR_TIPO_IDENTIFICACION: str = "02"  # 01=Física, 02=Jurídica, 03=DIMEX, 04=NITE
    EMISOR_NUMERO_IDENTIFICACION: str = ""
    EMISOR_NOMBRE: str = ""
    EMISOR_PROVINCIA: str = ""
    EMISOR_CANTON: str = ""
    EMISOR_DISTRITO: str = ""

    # --- Callback público (Hacienda debe poder alcanzar esta URL por HTTPS) ---
    CALLBACK_BASE_URL: str = "https://tu-dominio.com"

    # --- Seguridad de tu propia API ---
    JWT_SECRET: str = "cambiar-esto-por-un-secreto-largo-y-aleatorio"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
