"""Envío del comprobante (XML firmado, respuesta de Hacienda y PDF) por correo."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from api.models.database import Factura
from api.models.schemas import TIPOS_COMPROBANTE
from api.services.pdf import generar_pdf
from config.settings import get_settings


class CorreoError(Exception):
    pass


def construir_mensaje(factura: Factura, destinatarios: list[str]) -> EmailMessage:
    s = get_settings()
    emisor = factura.emisor
    tipo = TIPOS_COMPROBANTE.get(factura.tipo_documento, "Comprobante electrónico")

    msg = EmailMessage()
    msg["Subject"] = f"{tipo} {factura.numero_consecutivo} - {emisor.nombre}"
    msg["From"] = formataddr((emisor.nombre_comercial or emisor.nombre, s.SMTP_FROM))
    msg["To"] = ", ".join(destinatarios)
    msg["Reply-To"] = emisor.correo
    msg["Message-ID"] = make_msgid(domain=s.SMTP_FROM.split("@")[-1] if "@" in s.SMTP_FROM else None)
    msg.set_content(
        f"Estimado cliente:\n\n"
        f"Adjuntamos su {tipo.lower()} número {factura.numero_consecutivo} emitida por {emisor.nombre}.\n\n"
        f"Clave numérica: {factura.clave}\n"
        f"Total: {factura.moneda} {factura.monto_total:,.2f}\n"
        f"Estado ante Hacienda: {factura.estado.value}\n\n"
        f"Se adjuntan el XML firmado, la respuesta de Hacienda y la representación en PDF.\n"
    )

    msg.add_attachment(factura.xml_firmado.encode("utf-8"), maintype="application", subtype="xml",
                       filename=f"{factura.clave}.xml")
    if factura.xml_respuesta:
        msg.add_attachment(factura.xml_respuesta.encode("utf-8"), maintype="application", subtype="xml",
                           filename=f"{factura.clave}-respuesta.xml")
    msg.add_attachment(generar_pdf(factura), maintype="application", subtype="pdf",
                       filename=f"{factura.clave}.pdf")
    return msg


def mensaje_simple(destinatario: str, asunto: str, cuerpo: str) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = s.SMTP_FROM
    msg["To"] = destinatario
    msg.set_content(cuerpo)
    return msg


def enviar(msg: EmailMessage) -> None:
    s = get_settings()
    if not s.smtp_configurado:
        raise CorreoError("SMTP no está configurado (SMTP_HOST / SMTP_FROM)")
    contexto = ssl.create_default_context()
    try:
        if s.SMTP_SSL:
            servidor = smtplib.SMTP_SSL(s.SMTP_HOST, s.SMTP_PORT, context=contexto, timeout=30)
        else:
            servidor = smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=30)
        with servidor:
            if s.SMTP_STARTTLS and not s.SMTP_SSL:
                servidor.starttls(context=contexto)
            if s.SMTP_USER:
                servidor.login(s.SMTP_USER, s.SMTP_PASSWORD)
            servidor.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise CorreoError(f"No se pudo enviar el correo: {exc}") from exc
