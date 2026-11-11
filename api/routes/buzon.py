"""Buzón de correo de la empresa para recibir automáticamente las facturas de proveedores."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import BuzonCorreo, Emisor, get_db
from api.models.schemas import BuzonCorreoRequest
from api.security import emisor_actual, permiso
from api.services import buzon

router = APIRouter(prefix="/api/v1/buzon-correo", tags=["comprobantes recibidos"], dependencies=[Depends(permiso("recepcion"))])


def _buzon(db: Session, emisor: Emisor) -> BuzonCorreo | None:
    return db.scalar(select(BuzonCorreo).where(BuzonCorreo.emisor_id == emisor.id))


@router.get("")
def obtener(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Configuración y estado del buzón (null si no se ha conectado). Nunca devuelve la contraseña."""
    return buzon.a_dict(_buzon(db, emisor))


@router.put("")
def guardar(payload: BuzonCorreoRequest, emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Conecta o actualiza el buzón. Antes de guardar se prueba la conexión."""
    try:
        return buzon.a_dict(buzon.guardar(db, emisor, payload))
    except buzon.BuzonError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("", status_code=204)
def desconectar(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    b = _buzon(db, emisor)
    if b:
        db.delete(b)
        db.commit()


@router.post("/revisar")
def revisar_ahora(emisor: Emisor = Depends(emisor_actual), db: Session = Depends(get_db)):
    """Revisa el buzón en este momento (además de la revisión automática cada 5 minutos)."""
    b = _buzon(db, emisor)
    if b is None:
        raise HTTPException(status_code=404, detail="Primero conecte el correo de la empresa")
    resultado = buzon.revisar_seguro(db, b)
    if "error" in resultado:
        raise HTTPException(status_code=422, detail=resultado["error"])
    return {**resultado, "buzon": buzon.a_dict(b)}
