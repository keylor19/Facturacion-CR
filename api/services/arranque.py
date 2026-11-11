"""
Primeros pasos de una empresa: qué le falta para facturar (certificado, usuario de
Hacienda, datos, logo, productos, primera factura) y la prueba de conexión.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.database import Emisor, Factura, Paquete, Producto, Suscripcion, Usuario
from api.services import emisores
from api.services.cifrado import CifradoError
from api.services.firma import FirmaError, inspeccionar_certificado
from api.services.hacienda_auth import HaciendaAuthError, obtener_token


def probar_conexion(emisor: Emisor) -> dict:
    """Verifica el usuario de Hacienda (pide un token) y el certificado."""
    resultado = {"ambiente": emisor.ambiente}
    try:
        obtener_token(emisor, forzar=True)
        resultado["hacienda"] = "ok"
    except HaciendaAuthError as exc:
        resultado["hacienda"] = f"error: {exc}"
    try:
        p12, password = emisores.certificado(emisor)
        info = inspeccionar_certificado(p12, password)
        resultado["certificado"] = "ok" if info["dias_para_vencer"] >= 0 else "vencido"
        resultado["certificado_dias_para_vencer"] = info["dias_para_vencer"]
    except (emisores.EmisorIncompletoError, FirmaError, CifradoError) as exc:
        resultado["certificado"] = f"error: {exc}"
    resultado["ok"] = resultado.get("hacienda") == "ok" and resultado.get("certificado") == "ok"
    return resultado


def pasos(db: Session, emisor: Emisor) -> dict:
    productos = db.scalar(select(func.count()).select_from(Producto).where(Producto.emisor_id == emisor.id))
    facturas = db.scalar(select(func.count()).select_from(Factura).where(Factura.emisor_id == emisor.id))
    usuarios = db.scalar(select(func.count()).select_from(Usuario).where(Usuario.emisor_id == emisor.id))
    compro = (db.scalar(select(func.count()).select_from(Paquete).where(Paquete.emisor_id == emisor.id, Paquete.precio > 0))
              or db.scalar(select(func.count()).select_from(Suscripcion).where(Suscripcion.emisor_id == emisor.id,
                                                                               Suscripcion.precio > 0)))
    lista = [
        {"clave": "certificado", "titulo": "Subir la llave criptográfica (.p12)", "obligatorio": True,
         "hecho": emisor.cert_p12_cifrado is not None,
         "detalle": f"Vence el {emisor.cert_vence:%d/%m/%Y}" if emisor.cert_vence else
         "Se descarga en TRIBU-CR (Comprobantes electrónicos → Generar llave criptográfica) junto con su PIN."},
        {"clave": "credenciales", "titulo": "Usuario y contraseña de Hacienda para comprobantes", "obligatorio": True,
         "hecho": bool(emisor.hacienda_usuario and emisor.hacienda_password_cifrado),
         "detalle": "Se generan en el mismo lugar que la llave. El usuario se parece a "
                    "cpf-01-0123-0456@stag.comprobanteselectronicos.go.cr"},
        {"clave": "datos", "titulo": "Revisar los datos de la empresa", "obligatorio": False,
         "hecho": bool(emisor.correo and emisor.codigo_actividad and emisor.provincia),
         "detalle": "Correo, teléfono, dirección y actividad económica: salen en cada factura."},
        {"clave": "logo", "titulo": "Agregar el logo (opcional)", "obligatorio": False, "hecho": emisor.logo is not None,
         "detalle": "Aparece en el PDF y en el tiquete."},
        {"clave": "productos", "titulo": "Registrar sus productos o servicios", "obligatorio": False, "hecho": productos > 0,
         "detalle": "Con su código CABYS e IVA: después solo los elige al facturar."},
        {"clave": "usuarios", "titulo": "Agregar a quienes facturan con usted (opcional)", "obligatorio": False,
         "hecho": usuarios > 1, "detalle": "Cajeros o personal administrativo, cada uno con su usuario. Ninguno ve la contabilidad."},
        {"clave": "compra", "titulo": "Comprar su paquete de documentos y el sistema en línea", "obligatorio": False,
         "hecho": bool(compro),
         "detalle": "Al terminar la prueba gratis. Paga por SINPE Móvil o transferencia y se acredita al confirmarse el pago."},
        {"clave": "factura", "titulo": "Emitir la primera factura", "obligatorio": False, "hecho": facturas > 0,
         "detalle": "En el ambiente de pruebas no tiene validez fiscal: sirve para practicar."},
    ]
    hechos = sum(p["hecho"] for p in lista)
    return {
        "pasos": lista, "hechos": hechos, "total": len(lista), "ambiente": emisor.ambiente,
        "listo_para_facturar": all(p["hecho"] for p in lista if p["obligatorio"]),
        "completo": hechos == len(lista),
    }
