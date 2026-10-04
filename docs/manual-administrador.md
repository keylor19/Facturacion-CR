# Manual del administrador — alta y gestión de clientes

Cómo dar de alta a un cliente que le compró documentos, conectarlo con
Hacienda y entregarle lo necesario para que su sistema facture.
Todo se hace desde el panel: `https://<su-dominio>/panel/`.

## Resumen del proceso

```
1. Recibir del cliente sus datos y credenciales de Hacienda
2. Crear la empresa en el panel (Empresas → + Nueva empresa)
3. Cargar certificado y credenciales → "Probar conexión"
4. Venderle el paquete de documentos (la cantidad que compró)
5. Entregarle la conexión: API key (su sistema) y/o usuario del panel
6. Primera factura de prueba → pasar a Producción
```

## 1. Lo que le pide a cada cliente

| Dato | Dónde lo obtiene el cliente |
|---|---|
| Cédula, nombre o razón social, correo para facturas | — |
| Provincia, cantón, distrito y dirección **tal como están registrados en Hacienda** | ATV → Registro Único Tributario. Si no coinciden, Hacienda acepta pero con advertencia. |
| **Certificado digital** (`.p12`) y su **PIN** de 4 dígitos | ATV → Comprobantes electrónicos → "Generar llave criptográfica" |
| **Usuario y contraseña del API** | ATV → Comprobantes electrónicos → "Generar contraseña" (formato `cpj-…@prod.comprobanteselectronicos.go.cr` o `cpf-…`) |
| Códigos CABYS de lo que vende | Se buscan en el panel: Consultas Hacienda → CABYS |

Hay **un juego para pruebas** (sandbox) y **otro para producción**: se
generan por separado en ATV. Pida primero los de pruebas.

> Pida estos datos por un canal seguro (no por WhatsApp ni correo sin
> cifrar). En el sistema se guardan **cifrados** y nadie puede volver a verlos.

## 2. Crear la empresa

**Empresas → + Nueva empresa**

1. Escriba la cédula y presione **"Datos de Hacienda"**: trae el nombre y la
   actividad económica principal registrada.
2. Complete correo, provincia, cantón, distrito y otras señas.
3. **Proveedor de sistemas**: su propia cédula (usted es el proveedor del software).
4. **Ambiente de Hacienda**: *Pruebas (stag)* al inicio.
5. **Crear empresa**.

## 3. Conectarla con Hacienda

En la ficha de la empresa:

1. **Certificado digital** → seleccione el `.p12`, escriba el PIN → **Cargar certificado**.
   El sistema verifica el PIN, la vigencia y que el certificado corresponda a
   esa cédula (si no, muestra una advertencia).
2. **Credenciales del API de Hacienda** → usuario y contraseña → **Guardar credenciales**.
3. **Probar conexión con Hacienda** → debe decir `Hacienda: ok` y `Certificado: ok`.

| Resultado de la prueba | Causa probable |
|---|---|
| `invalid_grant` / credenciales inválidas | Usuario o contraseña incorrectos, o son de otro ambiente (pruebas vs. producción) |
| Certificado vencido | Generar uno nuevo en ATV y cargarlo |
| Error de conexión | Hacienda caído temporalmente; reintente más tarde |

Cada empresa tiene **sus propias** credenciales y certificado: nunca se mezclan
entre clientes, y cada una puede estar en pruebas o producción por separado.

## 4. Asignar los documentos que compró

**Ficha de la empresa → Documentos (saldo) → + Vender paquete**

- **Con un plan del catálogo** (Planes y ventas): elija el plan; la cantidad,
  el precio y la vigencia vienen del plan.
- **Con cantidad libre** (cualquier cantidad que haya negociado): elija
  "Cantidad libre", escriba los **documentos**, el **precio** (0 = cortesía)
  y la **vigencia en días** (vacío = no vence).
- **Referencia del pago**: número de comprobante SINPE o transferencia.

El saldo se suma a lo que ya tuviera. Cuando el cliente vuelva a comprar,
repita este paso. Si un pago se revierte, use **Anular** en el paquete.

El cliente **no puede facturar sin saldo**: su sistema recibe el error
`402` y el panel muestra "Saldo agotado". Usted y el cliente reciben avisos
cuando quedan pocos documentos (`SALDO_ALERTA_DOCUMENTOS`).

Qué consume 1 documento: cada factura, tiquete, nota de crédito o débito,
factura de compra o exportación, recibo de pago y cada respuesta a un
proveedor. Los reintentos y reenvíos **no** consumen.

## 5. Entregarle la conexión

Según cómo vaya a trabajar el cliente:

### a) Su sistema de facturación se conecta por API
**Ficha de la empresa → Integración con otros sistemas → Nueva llave**
(un nombre por sistema o sucursal, p. ej. "POS central") → **Crear API key**.

El panel muestra un bloque con **todo lo que necesita su programador**:
URL base, API key y un ejemplo listo. Presione **Copiar datos de conexión**
y envíeselo por un canal seguro junto con la
[guía de integración](integracion.md). La llave no se vuelve a mostrar; si se
pierde, revóquela y cree otra.

Opcional: **Webhook** → la URL de su sistema que recibirá avisos de
aceptación, rechazo y saldo. Entréguele el secreto que aparece para que
valide la firma.

### b) Factura desde el panel web
**Usuarios → + Nuevo usuario** → acceso "Solo <empresa>". El cliente
ingresa a `https://<su-dominio>/panel/` y solo ve su empresa: emitir,
consultar, facturas de proveedores, reportes y su saldo.

Puede dar ambas cosas al mismo cliente.

## 6. Pasar a producción

1. Con el ambiente en *Pruebas*, emita una factura desde el panel (o que el
   cliente emita una desde su sistema) y verifique que quede **Aceptada**.
2. Pida al cliente el **certificado y las credenciales de producción**.
3. En la ficha: cargue el nuevo certificado y las nuevas credenciales,
   cambie **Ambiente de Hacienda** a *Producción* y **Guardar cambios**.
4. **Probar conexión** y emitir la primera factura real.

Las API keys y los usuarios siguen siendo los mismos: el sistema del
cliente no tiene que cambiar nada.

## 7. Seguimiento diario

| Dónde | Qué revisar |
|---|---|
| Empresas (lista) | Saldo de cada cliente (verde/amarillo/rojo), certificados por vencer, credenciales faltantes |
| Planes y ventas | Ingresos del mes, paquetes vendidos, consumo por cliente |
| Tablero (por empresa) | Comprobantes con error o rechazados |
| Comprobantes → detalle | Motivo exacto de un rechazo de Hacienda y bitácora |
| Bitácora | Quién creó empresas o llaves, cambió certificados o credenciales, vendió paquetes, y los inicios de sesión (con IP) |

### Verificación en dos pasos

En producción todo administrador del panel debe activarla la primera vez que
entra (Mi cuenta → escanear el QR con Google/Microsoft Authenticator o Authy).
Desde entonces cada ingreso pide el código de 6 dígitos del teléfono.

- **Un usuario perdió el teléfono:** Usuarios → *Reiniciar 2 pasos*. Se
  cierran sus sesiones y la configura de nuevo al ingresar.
- **Usted perdió el suyo:** pida a otro administrador que lo reinicie o, en el
  servidor:
  `docker compose exec api python -m api.cli reiniciar-2fa --email usted@correo.cr`
  (queda registrado en la bitácora). Conviene tener **dos** administradores.
- Los usuarios de una empresa (clientes) pueden activarla de forma opcional.

Los rechazos más comunes y su solución:

| Mensaje de Hacienda | Solución |
|---|---|
| Código CABYS no existe | Corregir el código (el sistema ya lo valida antes de enviar) |
| Provincia/cantón/distrito no concuerdan (`-37`) | Actualizar la ubicación de la empresa con la registrada en Hacienda |
| Emisor no inscrito | El proveedor o el emisor no está inscrito en Hacienda |
| Envío extemporáneo (`-16`) | Comprobante en contingencia enviado tarde; se acepta, solo informa |
