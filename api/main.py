from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import facturas, callback, health
from api.models.database import init_db

app = FastAPI(
    title="API de Facturación Electrónica CR",
    description="API RESTful propia que orquesta la emisión de comprobantes "
                 "electrónicos ante el Ministerio de Hacienda de Costa Rica.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ restringir a tus dominios reales en producción
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(facturas.router)
app.include_router(callback.router)
app.include_router(health.router)


@app.on_event("startup")
def on_startup():
    # En producción usar Alembic para migraciones en vez de create_all.
    init_db()
