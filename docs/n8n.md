# Conexión con n8n — autollenado y emisión de facturas

Guía para quien arma la automatización en n8n. El objetivo: mientras el agente
escribe (cédula, producto), n8n consulta el servicio y devuelve los datos para
llenar la factura; al final la emite y recibe el aviso de Hacienda.

Incluye un flujo listo para importar: [`n8n/flujo-facturacion-cr.json`](n8n/flujo-facturacion-cr.json).

## 1. Lo que le entrega el proveedor

| Dato | Ejemplo |
|---|---|
| URL base | `https://<dominio>/api/v1` |
| API key de la empresa | `fcr_...` (va en el header `X-API-Key`) |
| Documentación interactiva | `https://<dominio>/docs` · especificación `https://<dominio>/openapi.json` |
| Secreto del webhook (opcional) | Para validar los avisos que envía el servicio |

La API key es como una contraseña: guárdela solo en las credenciales de n8n,
nunca en un nodo de código ni en un mensaje.

## 2. Importar el flujo

1. n8n → **Credentials → New → Header Auth**. Nombre: `Facturación CR`.
   *Name* = `X-API-Key`, *Value* = la API key.
2. **Workflows → Import from File** → `flujo-facturacion-cr.json`.
3. En los 5 nodos HTTP reemplace `SU-DOMINIO` por el dominio del servicio y
   elija la credencial `Facturación CR`.
4. (Avisos) En el nodo **Verificar firma** pegue el secreto del webhook y
   agregue `NODE_FUNCTION_ALLOW_BUILTIN=crypto` a las variables de entorno de n8n.
5. **Proteja los webhooks de n8n:** en cada nodo *Webhook* (cliente, producto y
   emitir) active *Authentication → Header Auth* con una clave propia que solo
   conozca el sistema del agente. Si no, cualquiera con la URL podría consultar
   o emitir.
6. Active el flujo.

El flujo publica estas URLs para el agente (o su interfaz):

| URL de n8n | Para qué |
|---|---|
| `GET /webhook/facturacion/cliente?cedula=3101005744` | Autollenar el cliente |
| `GET /webhook/facturacion/producto?q=martillo` | Sugerir productos y CABYS |
| `POST /webhook/facturacion/emitir` | Emitir la factura |
| `POST /webhook/facturacion/avisos` | Recibir avisos del servicio (se configura en el servicio, no la llama el agente) |

## 3. Autollenado mientras escribe

**No consulte en cada tecla.**
- Cédula: consulte solo cuando tenga entre 9 y 12 dígitos.
- Producto: consulte después de 3 letras y medio segundo sin escribir.

Cada API key admite 300 solicitudes por minuto. Las respuestas salen de los
datos guardados del servicio, así que son rápidas y no saturan a Hacienda.

### Cliente — `GET /webhook/facturacion/cliente?cedula=…`

Por dentro llama a `GET /hacienda/contribuyentes/{cedula}` (datos de Hacienda)
y a `GET /catalogo/clientes?q={cedula}` (correo y datos guardados). Respuesta:

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

- `inscrito: false` + `mensaje: "No está inscrito en Hacienda"` → avise al agente.
- `correo: null` → pídale el correo (Hacienda no lo publica). Si el cliente ya
  está guardado en la empresa, viene lleno.
- `datos_guardados_por_falla_de_hacienda: true` → Hacienda no respondió; los
  datos son los últimos guardados (sirven para facturar).

### Producto — `GET /webhook/facturacion/producto?q=…`

Llama a `GET /catalogo/productos?q=` (productos de la empresa) y
`GET /hacienda/cabys?q=` (catálogo oficial CABYS, ~20 500 códigos). Respuesta:

```json
{
  "q": "servicios contables",
  "productos": [{ "origen": "mis_productos", "producto_id": "…", "codigo": "CONS-01",
                  "descripcion": "Consultoría", "codigo_cabys": "8222100000000",
                  "unidad_medida": "Sp", "precio_unitario": "50000.00000",
                  "codigo_tarifa_iva": "08", "existencia": null }],
  "cabys": [{ "origen": "cabys", "codigo_cabys": "8222100000000",
              "descripcion": "Servicios de contabilidad", "impuesto": 13, "codigo_tarifa_iva": "08" }]
}
```

Prefiera `productos` (ya tienen precio). Si eligen uno, envíe su `producto_id`
en la línea: el servicio descuenta el inventario. De `cabys` solo salen el
código y el IVA; el precio lo indica el agente.

### Otras consultas útiles (directo al servicio, con la misma credencial)

| Consulta | Endpoint |
|---|---|
| Exoneración del cliente y productos que cubre | `GET /hacienda/exoneraciones/AL-00000000-24?detalle=true` |
| Tipo de cambio del día | `GET /hacienda/tipo-cambio` |
| ¿El cliente es productor agropecuario o de pesca? (tarifa 1 % de insumos) | `GET /hacienda/productores/{cedula}` |
| Documentos disponibles | `GET /saldo` |

## 4. Emitir — `POST /webhook/facturacion/emitir`

Envíe el JSON de la factura tal cual lo recibe el servicio (`POST /facturas`):

```json
{
  "tipo_documento": "01",
  "referencia_externa": "CHAT-20261006-0001",
  "receptor": { "nombre": "PURDY MOTOR SOCIEDAD ANONIMA", "tipo_identificacion": "02",
                "numero_identificacion": "3101005744", "correo": "facturas@cliente.com" },
  "codigo_actividad_receptor": "4520.0",
  "productos": [
    { "codigo_cabys": "8222100000000", "descripcion": "Servicios de contabilidad", "cantidad": "1",
      "unidad_medida": "Sp", "precio_unitario": "50000", "codigo_tarifa_iva": "08" }
  ],
  "condicion_venta": "01",
  "medios_pago": [{ "tipo": "04" }]
}
```

- **`referencia_externa` única por venta** (ID de la conversación o del pedido).
  Si n8n reintenta, el servicio devuelve la misma factura y no cobra otro documento.
- `tipo_documento`: `01` factura, `04` tiquete (sin receptor), `03` nota de crédito.
- `medios_pago.tipo`: `01` efectivo, `02` tarjeta, `04` transferencia, `06` SINPE Móvil.
- Montos y cantidades como texto (`"50000"`). El precio es **sin IVA**.
- Detalle completo de campos: [guía de integración](integracion.md) y `/docs`.

Respuesta del flujo:

```json
{ "ok": true, "status": 202, "factura_id": "8f1c…", "clave": "506…", "estado": "PENDIENTE",
  "documentos_disponibles": "1234", "error": null }
```

`PENDIENTE` significa que la factura ya está firmada y en cola para Hacienda. El
resultado final llega por el aviso (sección 5) o con `GET /facturas/{factura_id}`.
El PDF se descarga con `GET /facturas/{factura_id}/pdf`. Cuando Hacienda acepta,
el servicio le envía el PDF y el XML al correo del cliente.

| `status` | Qué pasó | Qué hacer |
|---|---|---|
| 401 | API key inválida | Revisar la credencial |
| 402 | Sin documentos disponibles | Comprar un paquete al proveedor |
| 403 | La conexión por API de la empresa no está activa o venció | Contactar al proveedor |
| 422 | Datos incompletos o inválidos (`error` dice cuál) | Corregir y reenviar |
| 429 | Demasiadas solicitudes | Esperar los segundos del header `Retry-After` |

## 5. Avisos del servicio — `POST /webhook/facturacion/avisos`

El proveedor configura en la ficha de la empresa la URL **de producción** de este
webhook de n8n (debe ser HTTPS pública) y le entrega el secreto. Eventos:
`comprobante.aceptado`, `comprobante.rechazado`, `comprobante.error_comunicacion`,
`saldo.bajo`, `saldo.agotado`, `paquete.por_vencer`, `certificado.por_vencer`.

El nodo **Verificar firma** comprueba el header `X-Facturacion-Firma`
(`sha256=` + HMAC del cuerpo con el secreto). Continúe solo si `valida` es
`true`. Luego conecte lo que necesite: mensaje de WhatsApp al cliente, correo,
actualizar un CRM, etc.

## 6. Pruebas

Empiece en el **ambiente de pruebas** (las facturas van al sandbox de Hacienda y
no tienen validez fiscal). Cédulas para probar el autollenado:

| Cédula | Resultado esperado |
|---|---|
| `3101005744` | Inscrito, 8 actividades |
| `206500188` | Persona física inscrita |
| `399999999999` | No inscrito |
| `3101` | "La cédula debe tener entre 9 y 12 dígitos" |
