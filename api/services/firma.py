"""
Firma digital del XML según el estándar XAdES-EPES que exige Hacienda
Costa Rica (XML-DSig enveloped + propiedades firmadas XAdES v1.3.2:
momento de firma, certificado firmante y política de firma).

Estructura generada:

  <ds:Signature Id="Signature-...">
    <ds:SignedInfo>
      Reference URI=""                 -> el comprobante (enveloped)
      Reference URI="#KeyInfoId-..."   -> el certificado
      Reference URI="#SignedProperties-..." Type=...#SignedProperties
    </ds:SignedInfo>
    <ds:SignatureValue/>
    <ds:KeyInfo/>
    <ds:Object><xades:QualifyingProperties>...</xades:QualifyingProperties></ds:Object>
  </ds:Signature>

Todas las referencias se canonicalizan con C14N 1.0 inclusivo EN EL
CONTEXTO del documento (heredando los namespaces de los ancestros), que es
como las verifica Hacienda.

⚠️ Antes de producción: enviar comprobantes al ambiente stag de Hacienda y
confirmar que la firma es aceptada.
"""
import base64
import copy
import hashlib
import logging
import threading
import uuid
from datetime import datetime, timezone

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from api.services.fechas import a_iso_cr
from api.services.xml_seguro import parsear
from config.settings import get_settings

logger = logging.getLogger(__name__)

DS = "http://www.w3.org/2000/09/xmldsig#"
XADES = "http://uri.etsi.org/01903/v1.3.2#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
TIPO_SIGNED_PROPERTIES = "http://uri.etsi.org/01903#SignedProperties"


class FirmaError(Exception):
    pass


_lock = threading.Lock()
_cache_cert: dict = {}
_cache_policy_digest: dict = {}
_MAX_CACHE_CERT = 64


def _cargar_certificado(p12: bytes, password: str | None):
    """Carga (y cachea por contenido + contraseña) la llave y el certificado de un .p12."""
    llave_cache = hashlib.sha256(p12 + b"\0" + (password or "").encode()).hexdigest()
    with _lock:
        if llave_cache in _cache_cert:
            return _cache_cert[llave_cache]

        try:
            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                p12, password.encode("utf-8") if password else None
            )
        except ValueError as exc:
            raise FirmaError("No se pudo abrir el .p12 (¿archivo inválido o contraseña incorrecta?)") from exc

        if private_key is None or certificate is None:
            raise FirmaError("No se pudo extraer la llave privada o el certificado del .p12")
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise FirmaError("El certificado debe tener una llave RSA")

        if len(_cache_cert) >= _MAX_CACHE_CERT:
            _cache_cert.clear()
        _cache_cert[llave_cache] = (private_key, certificate)
        return private_key, certificate


def inspeccionar_certificado(p12: bytes, password: str | None) -> dict:
    """Datos del certificado (sujeto, vencimiento) para validarlo al cargarlo y para monitoreo."""
    _, cert = _cargar_certificado(p12, password)
    vence = cert.not_valid_after_utc
    return {
        "sujeto": cert.subject.rfc4514_string(),
        "vence": vence,
        "dias_para_vencer": (vence - datetime.now(timezone.utc)).days,
    }


def _digest_politica() -> str:
    settings = get_settings()
    if settings.FIRMA_POLICY_DIGEST:
        return settings.FIRMA_POLICY_DIGEST

    url = settings.FIRMA_POLICY_URL
    with _lock:
        if url not in _cache_policy_digest:
            try:
                resp = requests.get(url, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                raise FirmaError(
                    f"No se pudo descargar la política de firma ({url}). "
                    "Configure FIRMA_POLICY_DIGEST para no depender de la descarga."
                ) from exc
            _cache_policy_digest[url] = _b64(hashlib.sha256(resp.content).digest())
            logger.info("Digest de la política de firma calculado: %s", _cache_policy_digest[url])
        return _cache_policy_digest[url]


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _c14n_en_contexto(el: etree._Element) -> bytes:
    """
    C14N inclusivo de un elemento tal como se vería dentro del documento:
    declara en el elemento todos los namespaces que hereda de sus ancestros.
    """
    copia = etree.Element(el.tag, attrib=dict(el.attrib), nsmap=el.nsmap)
    copia.text = el.text
    for hijo in el:
        copia.append(copy.deepcopy(hijo))
    return etree.tostring(copia, method="c14n", exclusive=False, with_comments=False)


def _sha256_b64(data: bytes) -> str:
    return _b64(hashlib.sha256(data).digest())


def _ds(parent, tag, text=None, **attrs):
    el = etree.SubElement(parent, f"{{{DS}}}{tag}", **attrs)
    if text is not None:
        el.text = text
    return el


def _xades(parent, tag, text=None, **attrs):
    el = etree.SubElement(parent, f"{{{XADES}}}{tag}", **attrs)
    if text is not None:
        el.text = text
    return el


def _referencia(signed_info, uri: str, digest: str, ref_id: str | None = None,
                tipo: str | None = None, enveloped: bool = False):
    attrs = {"URI": uri}
    if ref_id:
        attrs["Id"] = ref_id
    if tipo:
        attrs["Type"] = tipo
    ref = _ds(signed_info, "Reference", **attrs)
    if enveloped:
        transforms = _ds(ref, "Transforms")
        _ds(transforms, "Transform", Algorithm=ENVELOPED)
    _ds(ref, "DigestMethod", Algorithm=SHA256)
    _ds(ref, "DigestValue", digest)
    return ref


def firmar_xml(xml_str: str, p12: bytes, password: str | None) -> str:
    """
    Recibe el XML sin firmar y el certificado .p12 del emisor, y devuelve el
    XML con la firma XAdES-EPES insertada como último hijo del elemento raíz.
    """
    private_key, certificate = _cargar_certificado(p12, password)

    ahora = datetime.now(timezone.utc)
    if certificate.not_valid_after_utc < ahora:
        raise FirmaError(f"El certificado venció el {certificate.not_valid_after_utc:%Y-%m-%d}")
    if certificate.not_valid_before_utc > ahora:
        raise FirmaError("El certificado aún no es válido")

    root = parsear(xml_str)
    if root.find(f".//{{{DS}}}Signature") is not None:
        raise FirmaError("El XML ya está firmado")

    # 1) Digest del comprobante (equivale a la transformación enveloped)
    digest_documento = _sha256_b64(etree.tostring(root, method="c14n", exclusive=False, with_comments=False))

    uid = uuid.uuid4().hex
    sig_id = f"Signature-{uid}"
    ref_doc_id = f"Reference-{uid}"
    signed_props_id = f"SignedProperties-{sig_id}"
    key_info_id = f"KeyInfoId-{sig_id}"

    cert_der = certificate.public_bytes(serialization.Encoding.DER)

    # 2) Esqueleto de la firma dentro del documento
    signature = etree.SubElement(root, f"{{{DS}}}Signature", nsmap={"ds": DS}, Id=sig_id)
    signed_info = _ds(signature, "SignedInfo")
    _ds(signed_info, "CanonicalizationMethod", Algorithm=C14N)
    _ds(signed_info, "SignatureMethod", Algorithm=RSA_SHA256)
    signature_value = _ds(signature, "SignatureValue", Id=f"SignatureValue-{uid}")

    key_info = _ds(signature, "KeyInfo", Id=key_info_id)
    x509_data = _ds(key_info, "X509Data")
    _ds(x509_data, "X509Certificate", _b64(cert_der))

    # 3) Propiedades XAdES
    ds_object = _ds(signature, "Object")
    qp = etree.SubElement(
        ds_object, f"{{{XADES}}}QualifyingProperties", nsmap={"xades": XADES}, Target=f"#{sig_id}"
    )
    signed_props = _xades(qp, "SignedProperties", Id=signed_props_id)
    ssp = _xades(signed_props, "SignedSignatureProperties")
    _xades(ssp, "SigningTime", a_iso_cr(ahora))

    cert_el = _xades(_xades(ssp, "SigningCertificate"), "Cert")
    cert_digest = _xades(cert_el, "CertDigest")
    _ds(cert_digest, "DigestMethod", Algorithm=SHA256)
    _ds(cert_digest, "DigestValue", _sha256_b64(cert_der))
    issuer_serial = _xades(cert_el, "IssuerSerial")
    _ds(issuer_serial, "X509IssuerName", certificate.issuer.rfc4514_string())
    _ds(issuer_serial, "X509SerialNumber", str(certificate.serial_number))

    policy_id = _xades(_xades(ssp, "SignaturePolicyIdentifier"), "SignaturePolicyId")
    _xades(_xades(policy_id, "SigPolicyId"), "Identifier", get_settings().FIRMA_POLICY_URL)
    policy_hash = _xades(policy_id, "SigPolicyHash")
    _ds(policy_hash, "DigestMethod", Algorithm=SHA256)
    _ds(policy_hash, "DigestValue", _digest_politica())

    data_format = _xades(
        _xades(signed_props, "SignedDataObjectProperties"), "DataObjectFormat",
        ObjectReference=f"#{ref_doc_id}",
    )
    _xades(data_format, "MimeType", "text/xml")
    _xades(data_format, "Encoding", "UTF-8")

    # 4) Referencias (se calculan con los elementos ya ubicados en el documento)
    _referencia(signed_info, "", digest_documento, ref_id=ref_doc_id, enveloped=True)
    _referencia(signed_info, f"#{key_info_id}", _sha256_b64(_c14n_en_contexto(key_info)))
    _referencia(signed_info, f"#{signed_props_id}", _sha256_b64(_c14n_en_contexto(signed_props)),
                tipo=TIPO_SIGNED_PROPERTIES)

    # 5) Firma de SignedInfo
    firma = private_key.sign(_c14n_en_contexto(signed_info), padding.PKCS1v15(), hashes.SHA256())
    signature_value.text = _b64(firma)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")


def verificar_firma_local(xml_firmado: str, externo: bool = False) -> bool:
    """
    Verificación criptográfica local de las referencias y la firma, usando
    el certificado embebido (no valida la cadena de confianza; eso lo hace
    Hacienda).

    externo=True: documentos de terceros (proveedores), que pueden usar otros
    algoritmos y cantidad de referencias.
    """
    from signxml import XMLVerifier, SignatureConfiguration, SignatureMethod, DigestAlgorithm

    try:
        root = parsear(xml_firmado)
        cert_b64 = root.find(f".//{{{DS}}}X509Certificate").text
        cert = x509.load_der_x509_certificate(base64.b64decode("".join(cert_b64.split())))
        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        if externo:
            config = SignatureConfiguration(
                expect_references=True,
                signature_methods=frozenset(SignatureMethod),
                digest_algorithms=frozenset(DigestAlgorithm),
            )
        else:
            config = SignatureConfiguration(expect_references=3)
        XMLVerifier().verify(root, x509_cert=cert_pem, expect_config=config)
        return True
    except Exception:
        logger.warning("La verificación local de la firma falló", exc_info=not externo)
        return False
