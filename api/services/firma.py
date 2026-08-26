"""
Firma digital del XML según el estándar XAdES-EPES que exige Hacienda
Costa Rica (no es una firma XML-DSig genérica: XAdES le agrega propiedades
firmadas adicionales como el momento de firma y la política de firma).

⚠️ ESTA ES LA PARTE MÁS DELICADA DE TODO EL PROYECTO.
Antes de confiar en esto en producción:
  1. Genera un comprobante de prueba y fírmalo con este módulo.
  2. Envíalo al ambiente de pruebas (stag) de Hacienda.
  3. Si Hacienda responde "firma inválida", casi siempre es un problema de
     canonicalización (C14N) o de que falta/sobra un elemento en
     SignedProperties. Compara byte a byte contra un XML firmado por una
     herramienta ya certificada (por ejemplo, exportando uno de tu
     proveedor de facturación actual) para depurar diferencias.

Se recomienda usar la librería `signxml` como base y extenderla, en vez de
construir todo el XML-DSig a mano.
"""
import base64
import hashlib
from datetime import datetime, timezone

from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from signxml import XMLSigner, XMLVerifier, SignatureMethod, DigestAlgorithm

from config.settings import get_settings

settings = get_settings()

DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
XADES_NS = "http://uri.etsi.org/01903/v1.3.2#"

# Política de firma que exige Hacienda (URL pública documentada en el Anexo 1)
POLICY_URI = "https://www.mh.go.cr/politicafirmadigital.pdf"


class FirmaError(Exception):
    pass


def _cargar_certificado(cert_path: str = None, password: str = None):
    cert_path = cert_path or settings.CERT_P12_PATH
    password = password or settings.CERT_P12_PASSWORD

    with open(cert_path, "rb") as f:
        p12_data = f.read()

    private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
        p12_data, password.encode("utf-8")
    )

    if private_key is None or certificate is None:
        raise FirmaError("No se pudo extraer la llave privada o el certificado del .p12")

    return private_key, certificate, additional_certs


def firmar_xml(xml_str: str, cert_path: str = None, password: str = None) -> str:
    """
    Recibe el XML sin firmar (string) y devuelve el XML con la firma
    XAdES-EPES insertada dentro del elemento raíz, tal como lo espera
    Hacienda.
    """
    private_key, certificate, _ = _cargar_certificado(cert_path, password)
    root = etree.fromstring(xml_str.encode("utf-8"))

    signer = XMLSigner(
        method=None,  # enveloped, se configura abajo con c14n_algorithm
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )

    # signxml firma "enveloped" por defecto cuando se le pasa el nodo raíz
    # como `data` y se configura correctamente. Para XAdES puro, muchos
    # integradores optan por post-procesar el resultado de signxml para
    # inyectar el bloque <xades:QualifyingProperties> con SignedProperties
    # (fecha de firma + política + digest del certificado), que es lo que
    # Hacienda valida además de la firma XML-DSig estándar.
    signed_root = signer.sign(
        root,
        key=private_key,
        cert=certificate.public_bytes(encoding=1),  # DER
    )

    xades_props = _construir_xades_qualifying_properties(certificate)
    signature_el = signed_root.find(f".//{{{DSIG_NS}}}Signature")
    if signature_el is None:
        raise FirmaError("signxml no generó el nodo <Signature> esperado")

    key_info = signature_el.find(f"{{{DSIG_NS}}}KeyInfo")
    signature_el.insert(list(signature_el).index(key_info) + 1, xades_props)

    return etree.tostring(signed_root, xml_declaration=True, encoding="UTF-8").decode("utf-8")


def _construir_xades_qualifying_properties(certificate) -> etree._Element:
    """
    Construye el bloque XAdES con las propiedades firmadas obligatorias:
    - Momento exacto de la firma (SigningTime)
    - Huella digital del certificado (CertDigest)
    - Referencia a la política de firma vigente de Hacienda
    """
    cert_der = certificate.public_bytes(encoding=1)
    cert_digest = base64.b64encode(hashlib.sha256(cert_der).digest()).decode()

    qp = etree.Element(f"{{{XADES_NS}}}QualifyingProperties", nsmap={"xades": XADES_NS})
    signed_props = etree.SubElement(qp, f"{{{XADES_NS}}}SignedProperties")
    signed_sig_props = etree.SubElement(signed_props, f"{{{XADES_NS}}}SignedSignatureProperties")

    signing_time = etree.SubElement(signed_sig_props, f"{{{XADES_NS}}}SigningTime")
    signing_time.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    signing_cert = etree.SubElement(signed_sig_props, f"{{{XADES_NS}}}SigningCertificate")
    cert_el = etree.SubElement(signing_cert, f"{{{XADES_NS}}}Cert")
    cert_digest_el = etree.SubElement(cert_el, f"{{{XADES_NS}}}CertDigest")
    digest_method = etree.SubElement(cert_digest_el, f"{{{DSIG_NS}}}DigestMethod")
    digest_method.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    digest_value = etree.SubElement(cert_digest_el, f"{{{DSIG_NS}}}DigestValue")
    digest_value.text = cert_digest

    policy = etree.SubElement(signed_sig_props, f"{{{XADES_NS}}}SignaturePolicyIdentifier")
    policy_id = etree.SubElement(policy, f"{{{XADES_NS}}}SignaturePolicyId")
    sig_policy_id = etree.SubElement(policy_id, f"{{{XADES_NS}}}SigPolicyId")
    identifier = etree.SubElement(sig_policy_id, f"{{{XADES_NS}}}Identifier")
    identifier.text = POLICY_URI

    return qp


def verificar_firma_local(xml_firmado: str) -> bool:
    """Verificación local rápida (no reemplaza la validación real de Hacienda)."""
    try:
        root = etree.fromstring(xml_firmado.encode("utf-8"))
        XMLVerifier().verify(root)
        return True
    except Exception:
        return False
