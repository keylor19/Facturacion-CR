import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.routes import auth, callback, emisores, facturas, hacienda, health, recepcion, reportes, saldo
from config.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()

es_prod = settings.AMBIENTE == "prod"
ocultar_docs = es_prod and not settings.DOCS_PUBLICAS
PANEL_DIR = Path(__file__).parent / "panel"

app = FastAPI(
    title="API de Facturación Electrónica CR",
    description="Emisión y recepción de comprobantes electrónicos v4.4 ante el Ministerio de "
                "Hacienda de Costa Rica, para varios emisores. Panel web en /panel/.",
    version="3.0.0",
    # En producción la documentación solo se publica si DOCS_PUBLICAS=true
    docs_url=None if ocultar_docs else "/docs",
    redoc_url=None if ocultar_docs else "/redoc",
    openapi_url=None if ocultar_docs else "/openapi.json",
)

# Política de contenido del panel: solo recursos propios, sin scripts inline.
CSP_PANEL = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/panel"):
        response.headers["Content-Security-Policy"] = CSP_PANEL
        response.headers["Cache-Control"] = "no-cache"
    elif request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if es_prod:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key", "X-Emisor-Id", "Authorization"],
        expose_headers=["X-Documentos-Disponibles", "Retry-After"],
    )

app.include_router(auth.router)
app.include_router(facturas.router)
app.include_router(recepcion.router)
app.include_router(reportes.router)
app.include_router(saldo.router)
app.include_router(saldo.admin)
app.include_router(hacienda.router)
app.include_router(emisores.router)
app.include_router(callback.router)
app.include_router(health.router)

app.mount("/panel", StaticFiles(directory=PANEL_DIR, html=True), name="panel")


@app.get("/", include_in_schema=False)
def inicio():
    return RedirectResponse("/panel/")
