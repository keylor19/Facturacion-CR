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
