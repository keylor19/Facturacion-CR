Coloque aquí los XSD oficiales v4.4 descargados de ATV ("Anexos y Estructuras"):

- FacturaElectronica_V4.4.xsd
- TiqueteElectronico_V4.4.xsd
- NotaCreditoElectronica_V4.4.xsd
- NotaDebitoElectronica_V4.4.xsd
- FacturaElectronicaCompra_V4.4.xsd
- FacturaElectronicaExportacion_V4.4.xsd
- MensajeReceptor_V4.4.xsd
- xmldsig-core-schema.xsd (esquema de firma que importan los anteriores)

Si los XSD importan xmldsig desde una URL, cambie el schemaLocation para que
apunte al archivo local: la validación no accede a la red.

Actualización de Hacienda del 22-04-2026 (obligatoria desde el 01-11-2026)
---------------------------------------------------------------------------
Si sus XSD son anteriores a esa fecha, descargue los nuevos desde OVi/TRIBU-CR
("Anexos y Estructuras"). Los cambios que trae la nueva versión, y que se
aplicaron a mano a los XSD de este equipo mientras se descargan los oficiales:

- CodigoReferenciaType (nota 9): códigos 13, 14, 15, 16 y 17.
- TipoDocReferenciaType (nota 10): tipos 19 (factura de exportación) y 20 (recibo de pago).
- Clave: [a-zA-Z0-9]{50,50} (cédulas jurídicas alfanuméricas).
- NumTelefono: mínimo 100 (teléfonos especiales como 911).
- ds:Signature: hasta 5 firmas (salvo MensajeHacienda).
