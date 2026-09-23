import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.models.database import Emisor, get_db, utcnow
from api.security import require_admin
from api.services.cache import redis_client
from config.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def _chequeos(db: Session) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.exception("Health: base de datos no disponible")
        db_ok = False

    try:
        redis_ok = bool(redis_client().ping())
    except Exception:
        logger.exception("Health: Redis no disponible")
        redis_ok = False

    return {"database": db_ok, "redis": redis_ok}


@router.get("/api/v1/health")
def health(response: Response, db: Session = Depends(get_db)):
    """Chequeo público (para el balanceador): no expone detalles."""
    chequeos = _chequeos(db)
    ok = all(chequeos.values())
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", **chequeos}


@router.get("/api/v1/health/detalle", dependencies=[Depends(require_admin)])
def health_detalle(response: Response, db: Session = Depends(get_db)):
    """Chequeo completo: servicios, SMTP y estado de los certificados de cada emisor."""
    s = get_settings()
    chequeos = _chequeos(db)
    limite = utcnow() + timedelta(days=s.DIAS_ALERTA_CERTIFICADO)
    certificados = []
    for e in db.scalars(select(Emisor).where(Emisor.activo.is_(True)).order_by(Emisor.nombre)):
        if e.cert_vence is None:
            estado = "sin_certificado"
        elif e.cert_vence < utcnow():
            estado = "vencido"
        elif e.cert_vence < limite:
            estado = "por_vencer"
        else:
            estado = "ok"
        certificados.append({
            "emisor_id": str(e.id), "nombre": e.nombre, "ambiente": e.ambiente,
            "estado": estado, "vence": e.cert_vence,
        })

    ok = all(chequeos.values())
    if not ok:
        response.status_code = 503
    return {
        "status": "ok" if ok else "degraded",
        "ambiente": s.AMBIENTE,
        **chequeos,
        "smtp_configurado": s.smtp_configurado,
        "callback_configurado": bool(s.CALLBACK_TOKEN),
        "xsd_configurado": bool(s.XSD_DIR),
        "certificados": certificados,
    }
