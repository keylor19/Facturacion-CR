# Guía de integración — API de Facturación Electrónica CR

Esta guía es para el equipo técnico que conecta un sistema (POS, ERP,
e-commerce, app) a la API para emitir comprobantes electrónicos ante
Hacienda (v4.4). La API genera el XML, lo firma con el certificado de su
empresa, lo envía a Hacienda y le avisa del resultado.

## 1. Acceso

| Dato | Valor |
|---|---|
| URL base | `https://<servidor>/api/v1` |
| Autenticación | Header `X-API-Key: fcr_...` (se la entrega su proveedor) |
| Formato | JSON UTF-8. Montos como texto decimal (`"1500.50"`) |
| Documentación interactiva | `https://<servidor>/docs` (si su proveedor la tiene publicada) |

La llave está ligada a **su empresa**: solo ve y emite documentos de ella.
Guárdela como un secreto (variable de entorno o gestor de secretos). Nunca
la incluya en una app móvil ni en código de navegador.

## 2. Saldo de documentos

Su empresa compra **paquetes de documentos**. Cada documento que se firma y
se envía a Hacienda consume 1:

| Consume | No consume |
|---|---|
| Factura, tiquete, notas de crédito/débito, factura de compra, factura de exportación, recibo electrónico de pago | Reintentos y reenvíos del mismo documento |
| Aceptación, aceptación parcial o rechazo de facturas de proveedores (mensaje receptor) | Consultas de estado, PDF, XML, reportes |
| | Registrar una factura de proveedor (solo responderla consume) |
| | Solicitudes con errores de validación (422) |

Un documento **rechazado por Hacienda sí consume** (se firmó y se procesó).

- Cada emisión devuelve el header **`X-Documentos-Disponibles`** con el saldo restante.
- `GET /saldo` → disponible, consumo del mes, paquetes y vencimientos.
- `GET /saldo/movimientos?desde=2026-09-01&hasta=2026-09-30` → cada documento que consumió saldo.
- Sin saldo, la emisión responde **`402 Payment Required`**. Adquiera un paquete con su proveedor.
- Además de los documentos, la llave requiere el servicio **Conexión por API** vigente; si no está
  contratado o venció responde **`403`** con el motivo ("no tiene contratado el servicio…").
- Los paquetes pueden tener fecha de vencimiento; se consume primero el que vence antes.

## 3. Emitir un comprobante

```http
POST /api/v1/facturas
X-API-Key: fcr_...
Content-Type: application/json

{
  "tipo_documento": "01",
  "sucursal": 1,
  "terminal": 1,
  "referencia_externa": "VENTA-000123",
  "receptor": {
    "nombre": "Juan Pérez", "tipo_identificacion": "01",
    "numero_identificacion": "112345678", "correo": "juan@example.com"
  },
  "productos": [
    {
      "codigo_cabys": "8314100000000", "descripcion": "Consultoría",
      "cantidad": "1", "unidad_medida": "Sp", "precio_unitario": "50000",
      "codigo_tarifa_iva": "08"
    }
  ],
  "medios_pago": [{ "tipo": "06" }]
}
```

Respuesta `202 Accepted`:
```json
{ "factura_id": "8f1c…", "clave": "50623092600…", "estado": "PENDIENTE",
  "message": "Comprobante generado, firmado y encolado para envío a Hacienda." }
```

`tipo_documento`: `01` factura, `04` tiquete (receptor opcional), `02` nota
de débito, `03` nota de crédito (requieren `referencia`), `08` factura de
compra (requiere `proveedor`), `09` exportación.

### Referencias y códigos de Hacienda (obligatorios desde el 1-11-2026)
Las notas, y cualquier comprobante que reemplace a otro, llevan `referencia`:

```json
"referencia": { "tipo_documento": "01", "numero": "<clave de 50>", "fecha_emision": "2026-10-15T10:00:00",
                "codigo": "13", "razon": "Factura hecha al cliente equivocado" }
```

| `codigo` | Motivo | Dónde se usa | Mes en que cuenta |
|---|---|---|---|
| `01` | Anula documento | Nota de crédito | El de la nota |
| `02` | Corrige monto | Nota de crédito o débito | El de la nota |
| `06` | Devolución de mercancía | Nota de crédito | El de la nota |
| `12` | Crédito por exoneración aprobada después de facturar | Nota de crédito | El de la nota |
| `13` | Anula por error material (cliente equivocado, duplicada, hecha mal) | Nota de crédito | **El de la factura original** |
| `14` | Corrige monto por error material | Nota de crédito o débito | **El de la factura original** |
| `15` | Sustituye comprobante anulado por error material | La factura nueva que reemplaza | El suyo |
| `16` | Sustituye comprobante rechazado por Hacienda | El comprobante nuevo | El suyo |
| `17` | Pago a comprobante | Solo recibo de pago (lo pone la API) | El suyo |
| `04` `05` `07` `08` `09` `10` `11` `99` | Otros motivos de la nota 9 (`99` exige `codigo_otro`) | | |

`tipo_documento` de la referencia (nota 10): `01` factura, `02` ND, `03` NC, `04` tiquete,
`19` factura de exportación, `20` recibo de pago, `17`/`18` NC/ND a factura de compra y los demás
de la nota 10 (`99` exige `tipo_documento_otro`). Con los tipos que citan un comprobante
electrónico, `numero` es su clave de 50 caracteres.

La API rechaza (`422`) un código fuera de lugar (por ejemplo `13` en una factura o `15` en una
nota) y una nota de crédito que, sumada a las anteriores, supere el comprobante más sus notas de
débito. Cada comprobante devuelve `codigo_referencia`, `referencia_clave` y `periodo_fiscal` (mes
al que va su efecto contable). El resumen de IVA (`GET /reportes/resumen-iva`) cuenta cada nota en
su período fiscal y lista en `rectificaciones_pendientes` los meses cuya declaración hay que
rectificar.

### Idempotencia: `referencia_externa`
Envíe siempre el ID de la venta en su sistema. Si la red falla y reintenta
con la misma `referencia_externa`, la API devuelve el comprobante ya creado
(`200`) **sin emitir otro ni cobrar otro documento**. Así nunca se duplica
una factura.

### Ciclo de estados
`PENDIENTE → ENVIADO → ACEPTADO | RECHAZADO`

`ERROR_COMUNICACION` significa que Hacienda no respondió; la API reintenta
sola. Consulte el estado con `GET /facturas/{factura_id}` o reciba un
webhook (sección 6).

### Otras operaciones
| Operación | Endpoint |
|---|---|
| Consultar | `GET /facturas/{id}` · `GET /facturas?estado=&desde=&hasta=&referencia_externa=` |
| PDF para el cliente | `GET /facturas/{id}/pdf` |
| XML firmado / respuesta de Hacienda | `GET /facturas/{id}/xml?tipo=firmado` · `?tipo=respuesta` |
| Anular (nota de crédito total) | `POST /facturas/{id}/anular` `{"razon": "...", "codigo": "01"}` · `"codigo": "13"` si es error material |
| Recibo de pago (ventas a crédito 08/10) | `POST /facturas/{id}/recibo-pago` `{"monto": "58350"}` |
| Enviar por correo | `POST /facturas/{id}/correo` |
| Facturas de proveedores | `POST /recepcion` (XML en base64) · `POST /recepcion/{id}/mensaje` |
| Consultas a Hacienda | `GET /hacienda/ficha/{cedula}` (todo en una: situación, actividades, MAG / INCOPESCA y las exoneraciones que su empresa ya usó con esa cédula) · `/hacienda/exoneraciones?identificacion={cedula}` (ídem; Hacienda no busca exoneraciones por cédula, por eso no se comparten las de otras empresas) · `/hacienda/contribuyentes/{cedula}` · `/hacienda/exoneraciones/{AL-XXXXXXXX-XX}` · `/hacienda/cabys?q=` · `/hacienda/productores/{cedula}` (MAG / INCOPESCA) · `/hacienda/tipo-cambio` · `/hacienda/tipo-cambio/USD/historico?desde=&hasta=` |
| Logo de la empresa (sale en el PDF) | `PUT /empresa/logo` (PNG/JPEG, máx. 300 KB, campo `archivo`) · `DELETE /empresa/logo` |

### Catálogo e inventario (opcional)
Si su sistema no lleva inventario, puede usar el del servicio. Registre los
productos y envíe `producto_id` en cada línea: la venta descuenta la
existencia y, si no alcanza, la emisión se rechaza con `422`.

| Operación | Endpoint |
|---|---|
| Productos | `GET/POST /catalogo/productos` (`?q=`, `?bajo_minimo=true`) · `PATCH/DELETE /catalogo/productos/{id}` |
| Clientes | `GET/POST /catalogo/clientes` (`?q=`) · `PUT/DELETE /catalogo/clientes/{id}` |
| Movimientos | `POST /inventario/movimientos` `{"producto_id": "...", "tipo": "entrada", "cantidad": "10", "costo_unitario": "3000"}` · `tipo`: `entrada`, `salida` o `ajuste` (la cantidad es la existencia contada) |
| Kárdex y existencias | `GET /inventario/movimientos?producto_id=` · `GET /inventario/resumen` · `GET /inventario/existencias.csv` |

```json
{"codigo_cabys": "4299900000000", "descripcion": "Martillo de uña 16 oz", "cantidad": "3",
 "precio_unitario": "5000", "codigo_tarifa_iva": "08", "producto_id": "<id del catálogo>"}
```

Las notas de crédito que anulan (`codigo` 01) o devuelven (06) regresan la
mercadería; si Hacienda rechaza un comprobante, su movimiento se revierte solo.
Los montos y cantidades del inventario se devuelven como texto (`"10.000"`)
para no perder precisión.

### Sin internet o en contingencia
Si su punto de venta estuvo sin conexión, envíe el comprobante cuando se
recupere con `"situacion": "3"` y `"fecha_emision"` = fecha y hora reales
de la venta (máximo 30 días atrás).

## 4. Errores

| Código | Significado | Qué hacer |
|---|---|---|
| `400` | Falta un header (p. ej. `X-Emisor-Id` con llaves de administrador) | Corregir la solicitud |
| `401` | API key inválida o revocada | Verificar la llave |
| `402` | **Saldo de documentos agotado** | Comprar un paquete; luego reintentar |
| `403` | La llave no tiene permiso sobre ese recurso, o el servicio Conexión por API no está contratado o venció | Leer `detail`; renovar con su proveedor |
| `404` | Documento no encontrado (o de otra empresa) | — |
| `409` | Operación no permitida en el estado actual (p. ej. anular algo no aceptado) o empresa sin certificado | Revisar el mensaje |
| `422` | Datos inválidos; `detail` indica el campo y el motivo | Corregir los datos (no consume saldo) |
| `429` | Demasiadas solicitudes | Esperar lo que indica `Retry-After` (segundos) |
| `5xx` | Error del servicio | Reintentar con la **misma** `referencia_externa` |

## 5. Límites de uso
Por defecto, 300 solicitudes por minuto por llave. Si lo excede recibe
`429` con `Retry-After`. Para cargas masivas, envíe los documentos en
secuencia y respete ese header.

## 6. Webhooks (avisos automáticos)
Su proveedor puede configurar una URL HTTPS de su sistema. La API le hace
`POST` con JSON cuando:

| Evento | Cuándo |
|---|---|
| `comprobante.aceptado` / `comprobante.rechazado` | Hacienda resolvió un comprobante |
| `comprobante.error_comunicacion` | No se pudo enviar tras varios intentos |
| `mensaje_receptor.aceptado` / `.rechazado` | Resultado de su respuesta a un proveedor |
| `saldo.bajo` / `saldo.agotado` | Quedan pocos documentos / se agotaron |
| `paquete.por_vencer` | Documentos que vencen en los próximos días |
| `certificado.por_vencer` | Su certificado digital está por vencer |

Cada POST trae los headers `X-Facturacion-Evento` y
`X-Facturacion-Firma: sha256=<hmac>`. **Valide la firma** con el secreto
que le entregó su proveedor antes de confiar en el contenido:

```python
import hashlib, hmac

def firma_valida(cuerpo: bytes, firma_header: str, secreto: str) -> bool:
    esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma_header)
```

Responda `2xx` en menos de 10 segundos; si falla, la API reintenta.

## 7. Buenas prácticas
- Use siempre `referencia_externa` (idempotencia).
- Guarde `factura_id` y `clave` en su sistema.
- Entregue al cliente el PDF y el XML firmado cuando el estado sea `ACEPTADO`.
- Revise `X-Documentos-Disponibles` o `GET /saldo` para comprar a tiempo.
- Use los códigos CABYS correctos (`GET /hacienda/cabys?q=`).
