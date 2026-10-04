"""Bitácora de acciones sensibles (alta de empresas, certificados, llaves, ventas, accesos…)."""
import logging

from fastapi import Request
from sqlalchemy.orm import Session

from api.models.database import ApiKey, Auditoria, Usuario

logger = logging.getLogger(__name__)


def nombre_actor(db: Session, principal) -> str:
    if principal is None:
        return "sistema"
    if principal.usuario_id:
        u = db.get(Usuario, principal.usuario_id)
        return f"usuario:{u.email}" if u else f"usuario:{principal.usuario_id}"
    if principal.api_key_id:
        k = db.get(ApiKey, principal.api_key_id)
        return f"llave:{k.nombre} ({k.prefijo}…)" if k else f"llave:{principal.api_key_id}"
    return "llave de administrador (.env)"


def ip_de(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host[:64]


def registrar(db: Session, accion: str, *, principal=None, actor: str | None = None,
              request: Request | None = None, emisor_id: str | None = None, detalle: str | None = None) -> None:
    """Agrega una entrada a la bitácora. Nunca debe impedir la operación principal."""
    try:
        db.add(Auditoria(
            actor=(actor or nombre_actor(db, principal))[:200], accion=accion[:60],
            emisor_id=emisor_id, detalle=(detalle or "")[:2000] or None, ip=ip_de(request),
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("No se pudo registrar la acción %s en la bitácora", accion)
