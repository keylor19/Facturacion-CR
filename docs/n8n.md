# Conexión con n8n

Guía para quien arma la automatización. El servicio es un **API de facturación
electrónica** (Hacienda v4.4): su sistema, un chatbot, una tienda en línea o un
ERP emiten por medio de n8n sin tocar XML, firmas ni Hacienda.

Incluye un flujo listo para importar, probado contra el servicio:
[`n8n/flujo-facturacion-cr.json`](n8n/flujo-facturacion-cr.json).

| Sección del flujo | URL en n8n | Para qué |
|---|---|---|
| 1 | `GET /webhook/facturacion/cliente?cedula=…` | Autollenar el cliente con datos de Hacienda |
| 2 | `GET /webhook/facturacion/producto?q=…` | Buscar productos de la empresa y códigos CABYS |
| 3 | `POST /webhook/facturacion/emitir` | Emitir factura, tiquete o nota |
| 4 | `GET /webhook/facturacion/factura?id=…` o `?referencia=…` | Estado de un comprobante |
| 4 | `GET /webhook/facturacion/pdf?id=…` | PDF (para adjuntar en WhatsApp o correo) |
| 5 | `POST /webhook/facturacion/accion` | Anular, reenviar, pagos, proformas, facturas de proveedores |
| 6 | `GET /webhook/facturacion/recibidas` | Facturas de proveedores por aceptar o rechazar |
| 6 | `GET /webhook/facturacion/saldo` | Documentos disponibles y servicios |
| 7 | (automático, día 1 a las 7:00) | Respaldo de los XML del mes en un ZIP |
| 8 | `POST /webhook/facturacion/avisos` | Recibir los avisos del servicio (lo llama el servicio) |

## 1. Lo que entrega el proveedor

| Dato | Ejemplo |
|---|---|
| Dominio del servicio | `facturas.proveedor.com` |
| API key de la empresa | `fcr_...` (header `X-API-Key`) |
| Secreto del webhook (para la sección 8) | Se genera al configurar el webhook de la empresa |
| Documentación interactiva | `https://<dominio>/docs` · `https://<dominio>/openapi.json` |

La API key es como una contraseña: guárdela solo en las credenciales de n8n.

## 2. Instalar el flujo (5 minutos)

1. Abra `flujo-facturacion-cr.json` con un editor de texto y **reemplace
   `SU-DOMINIO` por el dominio del servicio** (un solo "Reemplazar todo").
2. En n8n cree dos credenciales de tipo **Header Auth** con estos nombres
   exactos, para que el flujo las tome solo al importarlo:

   | Nombre de la credencial | Name | Value |
   |---|---|---|
   | `Facturación CR (API key)` | `X-API-Key` | la API key de la empresa |
   | `Facturación CR (clave de mis webhooks)` | `X-Clave` | una clave larga inventada por usted |

   La segunda protege las URLs del flujo: su sistema debe enviar el header
   `X-Clave` en cada llamada; sin él n8n responde 403.
3. **Workflows → Import from File** → `flujo-facturacion-cr.json`. Si algún
   nodo muestra la credencial en rojo, ábralo y elija la credencial correcta.
4. Para los avisos (sección 8): en el nodo **Verificar firma** pegue el secreto
   del webhook y agregue `NODE_FUNCTION_ALLOW_BUILTIN=crypto` a las variables de
   entorno de n8n.
5. Active el flujo.

Probado con n8n 2.x. Cada API key admite 300 solicitudes por minuto.

## 3. Respuestas: siempre el mismo formato

Todas las URLs responden JSON con `ok` y, si algo falla, `error` en español
y el código HTTP del servicio:

| Código | Qué pasó | Qué hacer |
|---|---|---|
| 401 | API key inválida o revocada | Revisar la credencial |
| 402 | Sin documentos disponibles | Comprar un paquete al proveedor |
| 403 | La conexión por API no está activa o venció, o falta `X-Clave` | Revisar la clave / contactar al proveedor |
| 404 | No existe (factura, proforma, documento) | Revisar el id |
| 409 | Ya se hizo (p. ej. factura ya respondida, proforma anulada) | Nada que repetir |
| 422 | Datos incompletos o inválidos (`error` dice cuál) | Corregir y reenviar |
| 429 | Demasiadas solicitudes | Esperar los segundos del header `Retry-After` |
| 503 | El servicio no tiene correo configurado (solo `reenviar_correo`) | Avisar al proveedor |

## 4. Autollenado mientras se escribe

No consulte en cada tecla: la cédula cuando tenga entre 9 y 12 dígitos; el
producto después de 3 letras y medio segundo sin escribir.

**Cliente** — `GET /webhook/facturacion/cliente?cedula=3101005744`

```json
{
  "encontrado": true, "inscrito": true, "moroso": false, "omiso": false,
  "receptor": { "nombre": "PURDY MOTOR SOCIEDAD ANONIMA", "tipo_identificacion": "02",
                "numero_identificacion": "3101005744", "correo": null },
  "codigo_actividad": "4520.0",
  "actividades": [{ "codigo": "4520.0", "descripcion": "Mantenimiento y reparación de vehículos automotores", "principal": true }],
  "cliente_id": null, "datos_guardados_por_falla_de_hacienda": false, "mensaje": null
}
```

- `inscrito: false` → avise (Hacienda puede rechazar la factura).
- `correo: null` → pídalo (Hacienda no lo publica); si el cliente ya está guardado en la empresa, viene lleno.
- `datos_guardados_por_falla_de_hacienda: true` → Hacienda no respondió y se usan los últimos datos guardados (sirven para facturar).

**Producto** — `GET /webhook/facturacion/producto?q=contabilidad`

```json
{
  "q": "contabilidad",
  "productos": [{ "origen": "mis_productos", "producto_id": "…", "codigo": "CONT-01", "descripcion": "Contabilidad mensual",
                  "categoria": "Servicios", "codigo_cabys": "8222100000000", "unidad_medida": "Sp",
                  "precio_unitario": "50000.00000", "codigo_tarifa_iva": "08", "es_combo": false, "existencia": null }],
  "cabys": [{ "origen": "cabys", "codigo_cabys": "8222100000000", "descripcion": "Servicios de contabilidad",
              "impuesto": 13, "codigo_tarifa_iva": "08" }]
}
```

Prefiera `productos` (ya traen precio). Si eligen uno, envíe su `producto_id`
en la línea: el servicio descuenta el inventario (y en un combo, el de sus
componentes). De `cabys` solo salen el código y el IVA; el precio lo pone usted.

## 5. Emitir — `POST /webhook/facturacion/emitir`

Envíe el comprobante tal cual lo recibe el servicio (`POST /facturas`):

```json
{
  "tipo_documento": "01",
  "referencia_externa": "PEDIDO-20261027-0001",
  "receptor": { "nombre": "PURDY MOTOR SOCIEDAD ANONIMA", "tipo_identificacion": "02",
                "numero_identificacion": "3101005744", "correo": "facturas@cliente.com" },
  "codigo_actividad_receptor": "4520.0",
  "productos": [
    { "codigo_cabys": "8222100000000", "descripcion": "Servicios de contabilidad", "cantidad": "1",
      "unidad_medida": "Sp", "precio_unitario": "50000", "codigo_tarifa_iva": "08" }
  ],
  "condicion_venta": "01",
  "medios_pago": [{ "tipo": "06" }]
}
```

Respuesta:

```json
{ "ok": true, "status": 202, "factura_id": "d2fb…", "clave": "506…", "estado": "PENDIENTE",
  "documentos_disponibles": "493", "error": null }
```

- **`referencia_externa` única por venta** (ID del pedido o de la conversación).
  Si n8n reintenta, el servicio devuelve **la misma factura** y no cobra otro documento.
- `tipo_documento`: `01` factura (cliente con cédula), `04` tiquete (sin receptor),
  `03` nota de crédito, `02` nota de débito, `09` exportación.
- `medios_pago.tipo`: `01` efectivo, `02` tarjeta, `04` transferencia, `06` SINPE Móvil.
  Con varios medios, cada uno lleva su `monto`.
- Montos y cantidades como texto (`"50000"`). El precio es **sin IVA**.
- `PENDIENTE` = firmada y en cola para Hacienda. El resultado llega por el aviso
  (sección 8) o consultando (sección 6). Cuando Hacienda acepta, el servicio le
  envía el PDF y el XML al correo del cliente.
- Campos completos: [guía de integración](integracion.md) y `/docs`.

## 6. Consultar y descargar

- `GET /webhook/facturacion/factura?id=<factura_id>` o `?referencia=PEDIDO-…`
  → `estado`, `aceptado`, `rechazado`, `mensaje_hacienda`, totales y consecutivo.
- `GET /webhook/facturacion/pdf?id=<factura_id>` → el PDF (archivo). Úselo para
  enviarlo por WhatsApp o adjuntarlo en un correo.
- `GET /webhook/facturacion/saldo` → `disponible`, `alerta` (quedan pocos),
  `por_vencer` y el estado de los servicios contratados.
- `GET /webhook/facturacion/recibidas` → facturas de proveedores que faltan
  aceptar o rechazar (`documento_id`, proveedor, total, IVA, `firma_valida`).

## 7. Acciones — `POST /webhook/facturacion/accion`

Un solo punto de entrada; el campo `accion` dice qué hacer:

| `accion` | Campos | Qué hace |
|---|---|---|
| `anular` | `factura_id`, `razon`, `codigo` (opcional: `01` normal, `13` error material) | Nota de crédito por el total. Con `13` el ajuste va al mes de la factura original |
| `reenviar_correo` | `factura_id`, `destinatarios` (opcional, lista) | Reenvía PDF y XML |
| `consultar_hacienda` | `factura_id` | Pide a Hacienda el estado ahora |
| `reintentar` | `factura_id` | Reenvía lo que quedó con error de comunicación |
| `registrar_pago` | `factura_id`, `monto`, `medio_pago` | Recibo electrónico de pago (crédito al Estado o IVA a 90 días) |
| `crear_proforma` | `datos` (igual que emitir), `vence` (opcional) | Cotización numerada con PDF, sin enviar a Hacienda |
| `convertir_proforma` | `proforma_id` | La emite como factura (no se duplica si se repite) |
| `anular_proforma` | `proforma_id` | Anula la cotización |
| `registrar_recibida` | `xml_base64` | Registra el XML de un proveedor (si no llegó por el correo conectado) |
| `aceptar_recibida` | `documento_id`, `comentario` (opcional) | Acepta ante Hacienda y acredita el IVA |
| `rechazar_recibida` | `documento_id`, `comentario` (obligatorio) | Rechaza ante Hacienda; el comentario lo ve el proveedor |

Ejemplo: `{ "accion": "anular", "factura_id": "d2fb…", "razon": "Cliente equivocado", "codigo": "13" }`.
Respuesta: `{ "ok": true, "accion": "anular", "resultado": { … } }`.

## 8. Avisos del servicio — `POST /webhook/facturacion/avisos`

El proveedor configura en la ficha de la empresa (Integración → Webhook) la
URL **de producción** de este webhook (HTTPS pública) y le entrega el secreto.
El nodo **Verificar firma** comprueba el header `X-Facturacion-Firma`
(`sha256=` + HMAC del cuerpo con el secreto) y descarta lo que no esté firmado.
Luego el flujo separa los avisos en tres ramas para que conecte lo que necesite:

| Rama | Eventos | Idea |
|---|---|---|
| Aceptado | `comprobante.aceptado` | Enviar el PDF por WhatsApp, marcar el pedido como facturado |
| Rechazado | `comprobante.rechazado`, `mensaje_receptor.rechazado` | Avisar al encargado con `mensaje_hacienda` |
| Aviso del servicio | `saldo.bajo`, `saldo.agotado`, `paquete.por_vencer`, `suscripcion.por_vencer`, `suscripcion.vencida`, `certificado.por_vencer` | Avisar a quien compra los documentos o renueva el certificado |

Otros eventos (`comprobante.error_comunicacion`, `mensaje_receptor.aceptado`)
llegan a "Otros eventos": el servicio los reintenta solo.

## 9. Respaldo del mes (sección 7 del flujo)

Corre solo el día 1 a las 7:00: descarga en un ZIP los XML del mes anterior
(emitidos, recibidos y respuestas de Hacienda) con su índice en Excel. Cambie el
último nodo por **Google Drive**, **Dropbox** o **Gmail** para guardarlo o
mandárselo a su contador. El IVA, la D-104 y los libros contables los lleva su
contador en su propio módulo de contabilidad.

## 10. Pruebas

Empiece en el **ambiente de pruebas** (los comprobantes van al sandbox de
Hacienda y no tienen validez fiscal).

| Prueba | Resultado esperado |
|---|---|
| `cliente?cedula=3101005744` | Inscrito, varias actividades |
| `cliente?cedula=3101` | 422 "La cédula debe tener entre 9 y 12 dígitos" |
| `producto?q=contabilidad` | CABYS `8222100000000` |
| Emitir dos veces con la misma `referencia_externa` | La misma `factura_id` (no duplica) |
| `factura` sin `id` ni `referencia` | 422 "Indique ?id= o ?referencia=" |
| Cualquier URL sin el header `X-Clave` | 403 |
