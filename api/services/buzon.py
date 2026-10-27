"""
Recepción automática de facturas de proveedores por correo (IMAP).

Cada empresa conecta el buzón donde sus proveedores le envían los comprobantes.
Periódicamente se leen los correos nuevos (solo lectura: no se marcan como leídos
ni se borran), se toman los XML adjuntos (también dentro de ZIP), se empareja
cada comprobante con su respuesta de Hacienda y se registran. Lo repetido o lo
que no está dirigido a la empresa se ignora sin error.
"""
import email
import imaplib
import io
import ipaddress
import re
import socket
import ssl
import zipfile
from datetime import timedelta
from email import policy

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.database import BuzonCorreo, DocumentoRecibido, Emisor, utcnow
from api.services.cifrado import cifrar, descifrar_texto
from api.services.emision import EmisionError
from api.services.recepcion import MAX_BYTES_XML, RAICES_ACEPTABLES, _texto, registrar_documento
from api.services.xml_seguro import parsear

MAX_MENSAJES_POR_REVISION = 100
MAX_BYTES_CORREO = 15_000_000
MAX_BYTES_ZIP = 20_000_000          # descomprimido, por adjunto
DIAS_PRIMERA_REVISION = 30           # al conectar el buzón se importan los últimos 30 días
TIEMPO_ESPERA = 30
MESES_IMAP = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class BuzonError(Exception):
    pass


def validar_servidor(servidor: str) -> None:
    """Solo servidores públicos: evita que el buzón se use para sondear la red interna."""
    try:
        direcciones = {info[4][0] for info in socket.getaddrinfo(servidor, None)}
    except socket.gaierror:
        raise BuzonError(f"No se encontró el servidor de correo {servidor}")
    for d in direcciones:
        if not ipaddress.ip_address(d.split("%")[0]).is_global:
            raise BuzonError(f"El servidor {servidor} no es una dirección pública de Internet")


def conectar(servidor: str, puerto: int, usuario: str, password: str) -> imaplib.IMAP4_SSL:
    validar_servidor(servidor)
    try:
        imap = imaplib.IMAP4_SSL(servidor, puerto, ssl_context=ssl.create_default_context(), timeout=TIEMPO_ESPERA)
    except (OSError, ssl.SSLError) as exc:
        raise BuzonError(f"No se pudo conectar con {servidor}:{puerto} por SSL ({exc})")
    try:
        imap.login(usuario, password)
    except imaplib.IMAP4.error:
        _cerrar(imap)
        raise BuzonError("El servidor rechazó el usuario o la contraseña. En Gmail y Outlook use una "
                         "contraseña de aplicación y verifique que IMAP esté activado.")
    return imap


def _cerrar(imap) -> None:
    try:
        imap.logout()
    except Exception:
        pass


def _seleccionar(imap, carpeta: str) -> int | None:
    """Abre la carpeta en solo lectura y devuelve su UIDVALIDITY."""
    estado, _ = imap.select(f'"{carpeta}"', readonly=True)
    if estado != "OK":
        raise BuzonError(f'No existe la carpeta "{carpeta}" en el buzón')
    _, valores = imap.response("UIDVALIDITY")
    try:
        return int(valores[0]) if valores and valores[0] else None
    except (TypeError, ValueError):
        return None


def probar(servidor: str, puerto: int, usuario: str, password: str, carpeta: str) -> None:
    imap = conectar(servidor, puerto, usuario, password)
    try:
        _seleccionar(imap, carpeta)
    finally:
        _cerrar(imap)


# --- Lectura de adjuntos ------------------------------------------------------------

def _xml_de_zip(datos: bytes):
    try:
        z = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile:
        return
    total = 0
    for info in z.infolist():
        if not info.filename.lower().endswith(".xml") or info.file_size > MAX_BYTES_XML:
            continue
        total += info.file_size
        if total > MAX_BYTES_ZIP:
            return
        with z.open(info) as f:
            contenido = f.read(MAX_BYTES_XML + 1)   # el tamaño declarado en el ZIP puede mentir
        if len(contenido) <= MAX_BYTES_XML:
            yield contenido


def adjuntos_xml(msg) -> list[bytes]:
    xmls = []
    for parte in msg.walk():
        if parte.is_multipart():
            continue
        nombre = (parte.get_filename() or "").lower()
        tipo = parte.get_content_type()
        datos = parte.get_payload(decode=True) or b""
        if nombre.endswith(".xml") or tipo in ("text/xml", "application/xml"):
            if len(datos) <= MAX_BYTES_XML:
                xmls.append(datos)
        elif nombre.endswith(".zip") or tipo in ("application/zip", "application/x-zip-compressed"):
            xmls.extend(_xml_de_zip(datos))
    return xmls


def clasificar(xmls: list[bytes]) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """({clave: comprobante}, {clave: respuesta de Hacienda})"""
    comprobantes, respuestas = {}, {}
    for x in xmls:
        try:
            root = parsear(x)
        except etree.XMLSyntaxError:
            continue
        clave = _texto(root, "Clave")
        if not clave:
            continue
        raiz = etree.QName(root).localname
        if raiz == "MensajeHacienda":
            respuestas[clave] = x
        elif raiz in RAICES_ACEPTABLES:
            comprobantes[clave] = x
    return comprobantes, respuestas


def importar_correo(db: Session, emisor: Emisor, crudo: bytes) -> dict:
    resultado = {"importados": 0, "repetidos": 0, "ignorados": 0}
    msg = email.message_from_bytes(crudo, policy=policy.default)
    comprobantes, respuestas = clasificar(adjuntos_xml(msg))
    for clave, xml in comprobantes.items():
        try:
            registrar_documento(db, emisor, xml, respuestas.get(clave), origen="correo")
            resultado["importados"] += 1
        except EmisionError as exc:
            db.rollback()
            resultado["repetidos" if exc.status_code == 409 else "ignorados"] += 1
    # Respuesta de Hacienda que el proveedor envió después, en otro correo
    for clave, respuesta in respuestas.items():
        if clave in comprobantes:
            continue
        doc = db.scalar(select(DocumentoRecibido).where(
            DocumentoRecibido.emisor_id == emisor.id, DocumentoRecibido.clave == clave,
            DocumentoRecibido.xml_respuesta_proveedor.is_(None)))
        if doc:
            doc.xml_respuesta_proveedor = respuesta.decode("utf-8", errors="replace")
            db.commit()
    return resultado


# --- Revisión del buzón -------------------------------------------------------------

def _tamano(imap, uid: int) -> int:
    _, datos = imap.uid("FETCH", str(uid), "(RFC822.SIZE)")
    m = re.search(rb"RFC822\.SIZE (\d+)", datos[0] if datos and isinstance(datos[0], bytes) else b"")
    return int(m.group(1)) if m else 0


def revisar(db: Session, buzon: BuzonCorreo) -> dict:
    """Importa los correos nuevos. Guarda el avance correo por correo."""
    emisor = db.get(Emisor, buzon.emisor_id)
    resultado = {"correos": 0, "importados": 0, "repetidos": 0, "ignorados": 0}
    imap = conectar(buzon.servidor, buzon.puerto, buzon.usuario, descifrar_texto(buzon.password_cifrado))
    try:
        validez = _seleccionar(imap, buzon.carpeta)
        if validez != buzon.uid_validity:   # la carpeta se renumeró: se vuelve a leer por fecha
            buzon.uid_validity, buzon.ultimo_uid = validez, None
        if buzon.ultimo_uid:
            _, datos = imap.uid("SEARCH", None, f"UID {buzon.ultimo_uid + 1}:*")
        else:
            desde = (utcnow() - timedelta(days=DIAS_PRIMERA_REVISION)).date()
            _, datos = imap.uid("SEARCH", None, f"SINCE {desde.day}-{MESES_IMAP[desde.month - 1]}-{desde.year}")
        # "n:*" devuelve el último correo aunque sea menor que n
        uids = sorted(u for u in (int(x) for x in (datos[0] or b"").split()) if u > (buzon.ultimo_uid or 0))
        for uid in uids[:MAX_MENSAJES_POR_REVISION]:
            if _tamano(imap, uid) <= MAX_BYTES_CORREO:
                _, partes = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
                crudo = next((p[1] for p in partes if isinstance(p, tuple)), None)
                if crudo:
                    for k, v in importar_correo(db, emisor, crudo).items():
                        resultado[k] += v
            resultado["correos"] += 1
            buzon.ultimo_uid = uid
            db.commit()
    finally:
        _cerrar(imap)
    buzon.documentos_importados += resultado["importados"]
    buzon.ultima_revision = utcnow()
    buzon.ultimo_error = None
    db.commit()
    return resultado


def revisar_seguro(db: Session, buzon: BuzonCorreo) -> dict:
    """Como revisar(), pero deja el error guardado en el buzón en vez de propagarlo."""
    try:
        return revisar(db, buzon)
    except Exception as exc:  # un buzón con problemas no debe detener a los demás
        db.rollback()
        buzon.ultima_revision = utcnow()
        buzon.ultimo_error = str(exc)[:1000] if isinstance(exc, (BuzonError, imaplib.IMAP4.error)) \
            else f"Error inesperado al leer el correo: {exc}"[:1000]
        db.commit()
        return {"error": buzon.ultimo_error}


def guardar(db: Session, emisor: Emisor, datos) -> BuzonCorreo:
    """Crea o actualiza el buzón. Si cambian la conexión o la contraseña, primero se prueba."""
    buzon = db.scalar(select(BuzonCorreo).where(BuzonCorreo.emisor_id == emisor.id))
    if buzon is None and not datos.password:
        raise BuzonError("Indique la contraseña del correo")
    password = datos.password or descifrar_texto(buzon.password_cifrado)
    servidor, usuario, carpeta = datos.servidor.strip().lower(), datos.usuario.strip(), datos.carpeta.strip()
    nueva = (servidor, datos.puerto, usuario, carpeta)
    if buzon is None or datos.password or nueva != (buzon.servidor, buzon.puerto, buzon.usuario, buzon.carpeta):
        probar(servidor, datos.puerto, usuario, password, carpeta)
    if buzon is None:
        buzon = BuzonCorreo(emisor_id=emisor.id, documentos_importados=0)
        db.add(buzon)
    if (buzon.servidor, buzon.usuario, buzon.carpeta) != (servidor, usuario, carpeta):
        buzon.uid_validity = buzon.ultimo_uid = None   # otro buzón: se empieza de nuevo
    buzon.servidor, buzon.puerto, buzon.usuario, buzon.carpeta = nueva
    buzon.activo = datos.activo
    buzon.password_cifrado = cifrar(password)
    buzon.ultimo_error = None
    db.commit()
    return buzon


def a_dict(b: BuzonCorreo | None) -> dict | None:
    if b is None:
        return None
    return {
        "servidor": b.servidor, "puerto": b.puerto, "usuario": b.usuario, "carpeta": b.carpeta, "activo": b.activo,
        "ultima_revision": b.ultima_revision, "ultimo_error": b.ultimo_error,
        "documentos_importados": b.documentos_importados,
    }
