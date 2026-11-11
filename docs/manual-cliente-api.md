# Manual de conexión por API

Guía para las empresas que facturan desde **su propio sistema** (punto de
venta, ERP, tienda en línea, aplicación o automatización como n8n) y para el
programador que hace la conexión.

Con la API su sistema envía cada venta y la plataforma hace todo lo demás:
arma el comprobante electrónico v4.4, lo firma con el certificado de su
empresa, lo envía a Hacienda, le avisa el resultado y le envía el PDF y el XML
a su cliente.

> **Importante:** la API no se "instala". El **programador o proveedor de su
> sistema** debe programar la conexión siguiendo este manual. Si no tiene
> quien lo haga, pregunte por el **sistema en línea**, que funciona desde el navegador.

---

## 1. Cómo funciona el servicio

1. Usted **compra un paquete de documentos** (por ejemplo, 500).
2. Su proveedor da de alta su empresa y le entrega una **API key**.
3. Su sistema envía cada venta a la API. **Cada comprobante enviado a
   Hacienda gasta 1 documento.**
4. Cuando se le acaban, compra otro paquete. La conexión por API **no tiene
   mensualidad**: solo paga los documentos.

| Gasta 1 documento | No gasta |
|---|---|
| Factura, tiquete, nota de crédito, nota de débito, factura de compra, factura de exportación, recibo electrónico de pago | Reintentos y reenvíos del mismo comprobante |
| Aceptar, aceptar parcialmente o rechazar una factura de un proveedor | Consultas de estado, PDF, XML, reportes y consultas a Hacienda |
| | Solicitudes con datos inválidos (error `422`): no se firman |

Un comprobante que **Hacienda rechaza sí gasta** el documento: se firmó y se envió.

---

## 2. Lo que usted debe entregar a su proveedor

Entréguelo por un canal seguro (no por WhatsApp ni por un correo abierto). La
plataforma guarda el certificado y las contraseñas **cifrados**.

| Dato | Dónde lo obtiene | Para qué |
|---|---|---|
| **Cédula** física o jurídica de la empresa | — | Identifica la empresa ante Hacienda |
| **Correo** para facturas | — | Copia de lo que emite y avisos de saldo |
| **Provincia, cantón, distrito y dirección**, tal como están en Hacienda | ATV → Registro Único Tributario | Van en cada comprobante |
| **Certificado digital** (archivo `.p12`) y su **PIN** de 4 dígitos | ATV → Comprobantes electrónicos → *Generar llave criptográfica* | Firmar cada comprobante |
| **Usuario y contraseña del API de Hacienda** | ATV → Comprobantes electrónicos → *Generar contraseña* | Enviar los comprobantes a Hacienda |
| **Nombre de cada sistema o sucursal** que se va a conectar (p. ej. "POS central", "Tienda en línea") | — | Se crea una API key para cada uno |
| **Contacto de su programador** | — | Para enviarle los datos de conexión |
| **URL de su webhook** (opcional) | La define su programador | Para que su sistema reciba los avisos de aceptado o rechazado (sección 9) |
| **Comprobante del pago** del paquete de documentos | SINPE o transferencia | Para acreditarle los documentos |

**Pruebas y producción:** Hacienda tiene dos ambientes, y para cada uno se
genera un certificado y un usuario distintos. Primero se entrega el de
**pruebas** (el usuario termina en `@stag.comprobanteselectronicos.go.cr`).
Cuando su sistema funcione bien, se entrega el de **producción** (termina en
`@prod.comprobanteselectronicos.go.cr`).

---

## 3. Lo que su proveedor le entrega

| Dato | Ejemplo |
|---|---|
| **URL base** | `https://<servidor>/api/v1` |
| **API key** | `fcr_…` (una por sistema o sucursal) |
| **Documentación interactiva** | `https://<servidor>/docs` |
| **Secreto del webhook** (si pidió webhook) | Para verificar que los avisos vienen de la plataforma |
| **Ambiente** | Pruebas o Producción |

> **La API key es como una contraseña.** Se muestra una sola vez. Guárdela en
> una variable de entorno o un gestor de secretos del servidor. **Nunca** la
> ponga en una app móvil, en el código de una página web ni en un repositorio.
> Si se pierde o se filtra, pida a su proveedor que la revoque y le cree otra.

La llave está ligada a **su empresa**: solo ve y emite los documentos de ella.

---

## 4. Conectarse: lo básico

| Dato | Valor |
|---|---|
| URL base | `https://<servidor>/api/v1` |
| Autenticación | Encabezado `X-API-Key: fcr_…` en **cada** solicitud |
| Formato | JSON en UTF-8. Los montos y cantidades van como **texto decimal**: `"1500.50"` |
| Fechas | ISO 8601: `"2026-11-07T10:30:00"` |

### Prueba de conexión

Pida su saldo. Si responde, la llave y la conexión funcionan:

```bash
curl https://<servidor>/api/v1/saldo -H "X-API-Key: fcr_SU_LLAVE"
```

---

## 5. Emitir un comprobante

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
      "codigo_cabys": "8312900000000", "descripcion": "Consultoría",
      "cantidad": "1", "unidad_medida": "Sp", "precio_unitario": "50000",
      "codigo_tarifa_iva": "08"
    }
  ],
  "medios_pago": [{ "tipo": "06" }]
}
```

Respuesta `202 Accepted`. El comprobante ya se firmó y va camino a Hacienda:

```json
{ "factura_id": "8f1c…", "clave": "50623092600…", "estado": "PENDIENTE",
  "message": "Comprobante generado, firmado y encolado para envío a Hacienda." }
```

Cada respuesta trae el encabezado **`X-Documentos-Disponibles`** con los
documentos que le quedan.

### 5.1 Campos principales

| Campo | Qué es |
|---|---|
| `tipo_documento` | `01` factura, `04` tiquete, `03` nota de crédito, `02` nota de débito, `08` factura de compra, `09` factura de exportación |
| `sucursal` / `terminal` | Número de sucursal y de caja (forman el consecutivo) |
| `referencia_externa` | **El número de la venta en su sistema.** Evita duplicados (sección 5.3) |
| `receptor` | El cliente. Opcional en el tiquete. Si se envía con cédula pero sin `nombre`, sale como "Consumidor final". Con `correo`, le llegan el PDF y el XML |
| `productos` | Las líneas: `codigo_cabys` (13 dígitos), `descripcion`, `cantidad`, `unidad_medida`, `precio_unitario` (sin IVA) y `codigo_tarifa_iva` (`08` = 13 %) |
| `medios_pago` | Forma de pago: `01` efectivo, `02` tarjeta, `04` transferencia, `06` SINPE Móvil… Puede enviar varias |
| `referencia` | Obligatoria en notas de crédito y débito (sección 6) |
| `proveedor` | Obligatorio en la factura de compra (`08`) |

La documentación interactiva (`/docs`) tiene todos los campos, con sus
valores permitidos y ejemplos que se pueden probar ahí mismo.

### 5.2 Ciclo de estados

`PENDIENTE → ENVIADO → ACEPTADO` o `RECHAZADO`

- `ERROR_COMUNICACION`: Hacienda no respondió. **La API reintenta sola.**
- Para saber el resultado, consulte `GET /facturas/{factura_id}` o reciba un
  **webhook** (sección 9), que es lo recomendado.
- Cuando el estado es `ACEPTADO`, la plataforma le envía al cliente el PDF y
  el XML por correo (si se indicó `receptor.correo`).

### 5.3 Evitar facturas duplicadas: `referencia_externa`

Envíe **siempre** el número de la venta de su sistema. Si la red falla y su
sistema reintenta con la misma `referencia_externa`, la API devuelve el
comprobante que ya se había creado (`200`) **sin emitir otro ni gastar otro
documento**.

### 5.4 Ventas hechas sin internet (contingencia)

Si su punto de venta estuvo sin conexión, envíe el comprobante cuando vuelva
el internet con `"situacion": "3"` y `"fecha_emision"` = la fecha y hora
reales de la venta (hasta 30 días atrás).

---

## 6. Notas de crédito, de débito y anulaciones

### 6.1 Anular una factura completa

```http
POST /api/v1/facturas/{factura_id}/anular
{ "razon": "Devolución total", "codigo": "01" }
```

Use `"codigo": "13"` si se anula por **error material** (cliente equivocado,
factura duplicada o mal hecha). En ese caso el efecto en el IVA va al mes de la factura original.

### 6.2 Notas con referencia

Las notas, y cualquier comprobante que reemplace a otro, llevan `referencia`:

```json
"referencia": { "tipo_documento": "01", "numero": "<clave de 50>", "fecha_emision": "2026-10-15T10:00:00",
                "codigo": "02", "razon": "Se rebaja el precio acordado" }
```

**Códigos de referencia de Hacienda** (obligatorios desde el 1 de noviembre de 2026):

| `codigo` | Motivo | Dónde se usa | Mes en que cuenta |
|---|---|---|---|
| `01` | Anula documento | Nota de crédito | El de la nota |
| `02` | Corrige monto | Nota de crédito o débito | El de la nota |
| `06` | Devolución de mercancía | Nota de crédito | El de la nota |
| `12` | Crédito por exoneración aprobada después de facturar | Nota de crédito | El de la nota |
| `13` | Anula por error material | Nota de crédito | **El de la factura original** |
| `14` | Corrige monto por error material | Nota de crédito o débito | **El de la factura original** |
| `15` | Sustituye comprobante anulado por error material | La factura nueva que reemplaza | El suyo |
| `16` | Sustituye comprobante rechazado por Hacienda | El comprobante nuevo | El suyo |
| `17` | Pago a comprobante | Solo recibo de pago (lo pone la API) | El suyo |
| `04` `05` `07` `08` `09` `10` `11` `99` | Otros motivos (`99` exige `codigo_otro`) | | |

`tipo_documento` de la referencia: `01` factura, `02` nota de débito, `03` nota de
crédito, `04` tiquete, `19` factura de exportación, `20` recibo de pago, y los
demás de Hacienda (`99` exige `tipo_documento_otro`). Cuando la referencia es
un comprobante electrónico, `numero` es su **clave de 50 caracteres**.

La API rechaza (`422`) un código usado donde no corresponde (por ejemplo `13`
en una factura) y una nota de crédito que, sumada a las anteriores, supere la
factura más sus notas de débito.

### 6.3 Recibo electrónico de pago

En ventas a crédito al Estado o con IVA hasta 90 días, cuando el cliente
paga, registre el pago y la API emite el recibo con el IVA proporcional:

```http
POST /api/v1/facturas/{factura_id}/recibo-pago
{ "monto": "58350" }
```

---

## 7. Otras operaciones

| Operación | Endpoint |
|---|---|
| Consultar un comprobante | `GET /facturas/{id}` |
| Buscar comprobantes | `GET /facturas?estado=&desde=&hasta=&referencia_externa=` |
| PDF para el cliente | `GET /facturas/{id}/pdf` (hoja carta) · `?formato=80mm` o `?formato=58mm` para impresora térmica |
| Enlace para WhatsApp | `GET /facturas/{id}/enlace?telefono=88887777`: devuelve el enlace de descarga sin usuario y el enlace `wa.me` con el mensaje listo |
| XML firmado / respuesta de Hacienda | `GET /facturas/{id}/xml?tipo=firmado` · `?tipo=respuesta` |
| Reenviar por correo | `POST /facturas/{id}/correo` |
| Saldo de documentos | `GET /saldo` |
| Movimientos del saldo | `GET /saldo/movimientos?desde=2026-11-01&hasta=2026-11-30` |
| Facturas de proveedores | `POST /recepcion` (XML en base64) · `POST /recepcion/{id}/mensaje` para aceptar o rechazar |
| Datos de un contribuyente | `GET /hacienda/ficha/{cedula}` (situación, actividades, MAG / INCOPESCA y las exoneraciones que su empresa ya usó con esa cédula) |
| Buscar código CABYS | `GET /hacienda/cabys?q=martillo` |
| Verificar una exoneración | `GET /hacienda/exoneraciones/{AL-XXXXXXXX-XX}` |
| Tipo de cambio | `GET /hacienda/tipo-cambio` |
| Logo de la empresa (sale en el PDF) | `PUT /empresa/logo` (PNG o JPEG, máximo 300 KB, campo `archivo`) |
| Respaldo de los XML de un mes (ZIP con índice en Excel) | `GET /reportes/documentos.zip?desde=2026-11-01&hasta=2026-11-30` |
| Primeros pasos de la empresa | `GET /empresa/arranque` · `PUT /empresa/certificado` · `PUT /empresa/credenciales-hacienda` · `POST /empresa/probar-conexion` |

### Cuentas por cobrar

Para ventas a crédito (`condicion_venta` 02 con `plazo_credito`). Los cobros del crédito comercial
no llevan comprobante electrónico: se registran como abonos. Las condiciones 08 y 10 se cobran con
recibo electrónico de pago (sección 6.3).

| Operación | Endpoint |
|---|---|
| Facturas con saldo, antigüedad (al día, 1-30, 31-60, 61-90, más de 90 días) y saldo por cliente | `GET /cobros/cartera` |
| Estado de cuenta de un cliente | `GET /cobros/estado-cuenta/{cedula}` |
| Saldo y abonos de una factura | `GET /cobros/facturas/{id}` |
| Registrar un pago | `POST /cobros/facturas/{id}/abonos` con `{"monto": "50000", "medio_pago": "06", "referencia": "SINPE 123"}` |
| Anular un abono registrado por error | `POST /cobros/abonos/{id}/anular` |
| Recordatorios automáticos por correo | `PUT /cobros/ajustes` con `{"recordar_cobros": true}` (a los 1, 8, 15, 30 y 60 días de atraso) |

### Facturas recurrentes

Alquileres, mensualidades o servicios fijos: se guarda el cuerpo de `POST /facturas` una vez y el
servicio lo emite solo cada semana, quincena, mes o año (a las 7:00 a. m.). Cada emisión lleva
`referencia_externa` `REC-<id>-<fecha>`, así que nunca se duplica.

| Operación | Endpoint |
|---|---|
| Crear | `POST /recurrentes` con `{"nombre": "Alquiler local 3", "datos": {…cuerpo de /facturas…}, "frecuencia": "mensual", "proxima": "2026-12-01", "hasta": null}` |
| Listar, ver, cambiar, borrar | `GET /recurrentes` · `GET/PUT/DELETE /recurrentes/{id}` (`activa: false` la pausa) |
| Emitir hoy (fuera de calendario) | `POST /recurrentes/{id}/emitir-ahora` |

### Catálogo e inventario (opcional)

Si su sistema no lleva inventario, puede usar el de la plataforma: registre
los productos y envíe `producto_id` en cada línea. La venta descuenta la
existencia y, si no alcanza, la emisión se rechaza con `422`.

| Operación | Endpoint |
|---|---|
| Productos | `GET/POST /catalogo/productos` · `PATCH/DELETE /catalogo/productos/{id}` |
| Clientes | `GET/POST /catalogo/clientes` · `PUT/DELETE /catalogo/clientes/{id}` |
| Movimientos de inventario | `POST /inventario/movimientos` con `tipo`: `entrada`, `salida` o `ajuste` |
| Existencias | `GET /inventario/resumen` · `GET /inventario/existencias.csv` |

---

## 8. Ejemplos en otros lenguajes

### Python

```python
import os, requests

URL = "https://<servidor>/api/v1"
LLAVE = os.environ["FACTURACION_API_KEY"]   # nunca escrita en el código

venta = {
    "tipo_documento": "04",
    "referencia_externa": "VENTA-000124",
    "productos": [{"codigo_cabys": "4292199990200", "descripcion": "Martillo de uña 16 oz",
                   "cantidad": "2", "unidad_medida": "Unid", "precio_unitario": "5000",
                   "codigo_tarifa_iva": "08"}],
    "medios_pago": [{"tipo": "01"}],
}
r = requests.post(f"{URL}/facturas", json=venta, headers={"X-API-Key": LLAVE}, timeout=30)
if r.status_code in (200, 202):
    datos = r.json()
    print("Clave:", datos["clave"], "· Quedan:", r.headers.get("X-Documentos-Disponibles"))
elif r.status_code == 402:
    print("Sin documentos: compre otro paquete")
else:
    print("Error", r.status_code, r.json().get("detail"))
```

### JavaScript (Node.js 18 o superior)

```javascript
const URL = 'https://<servidor>/api/v1';
const LLAVE = process.env.FACTURACION_API_KEY;

const r = await fetch(`${URL}/facturas`, {
  method: 'POST',
  headers: { 'X-API-Key': LLAVE, 'Content-Type': 'application/json' },
  body: JSON.stringify({
    tipo_documento: '04',
    referencia_externa: 'VENTA-000125',
    productos: [{ codigo_cabys: '4292199990200', descripcion: 'Martillo de uña 16 oz', cantidad: '1',
                  unidad_medida: 'Unid', precio_unitario: '5000', codigo_tarifa_iva: '08' }],
    medios_pago: [{ tipo: '01' }],
  }),
});
const datos = await r.json();
if (!r.ok) throw new Error(`${r.status}: ${JSON.stringify(datos.detail)}`);
console.log('Clave', datos.clave, 'estado', datos.estado);
```

### PHP

```php
$url = 'https://<servidor>/api/v1/facturas';
$venta = [
  'tipo_documento' => '04',
  'referencia_externa' => 'VENTA-000126',
  'productos' => [[ 'codigo_cabys' => '4292199990200', 'descripcion' => 'Martillo de uña 16 oz',
                    'cantidad' => '1', 'unidad_medida' => 'Unid', 'precio_unitario' => '5000',
                    'codigo_tarifa_iva' => '08' ]],
  'medios_pago' => [[ 'tipo' => '01' ]],
];
$ch = curl_init($url);
curl_setopt_array($ch, [
  CURLOPT_POST => true,
  CURLOPT_RETURNTRANSFER => true,
  CURLOPT_HTTPHEADER => ['X-API-Key: ' . getenv('FACTURACION_API_KEY'), 'Content-Type: application/json'],
  CURLOPT_POSTFIELDS => json_encode($venta),
]);
$respuesta = json_decode(curl_exec($ch), true);
$codigo = curl_getinfo($ch, CURLINFO_HTTP_CODE);
echo $codigo . ' ' . ($respuesta['clave'] ?? json_encode($respuesta['detail'] ?? ''));
```

### n8n y otras herramientas sin programación

Si usa **n8n**, pida a su proveedor el flujo listo para importar: emite,
consulta y anula comprobantes sin escribir código. Cualquier herramienta que
pueda hacer solicitudes HTTP (Make, Zapier, Power Automate) sirve con los
mismos datos: URL, método, encabezado `X-API-Key` y el JSON.

### Tienda WooCommerce

Si su tienda en línea es WordPress con WooCommerce, pida a su proveedor el
complemento **Facturación Electrónica CR**: se instala como cualquier plugin,
se le pone la dirección del servicio y la API key, y factura solo cada pedido
(factura si el cliente escribe su cédula al pagar, tiquete si no).

---

## 9. Webhooks: avisos automáticos a su sistema

Si entregó la URL de su webhook, la plataforma le hace un `POST` con JSON cuando:

| Evento | Cuándo |
|---|---|
| `comprobante.aceptado` / `comprobante.rechazado` | Hacienda resolvió un comprobante |
| `comprobante.error_comunicacion` | No se pudo enviar después de varios intentos |
| `mensaje_receptor.aceptado` / `.rechazado` | Resultado de su respuesta a un proveedor |
| `saldo.bajo` / `saldo.agotado` | Quedan pocos documentos / se agotaron |
| `paquete.por_vencer` | Tiene documentos que vencen en los próximos días |
| `certificado.por_vencer` | Su certificado digital está por vencer |

Cada aviso trae los encabezados `X-Facturacion-Evento` y
`X-Facturacion-Firma: sha256=<hmac>`. **Verifique la firma** con el secreto que
le entregó su proveedor antes de confiar en el contenido:

```python
import hashlib, hmac

def firma_valida(cuerpo: bytes, firma_header: str, secreto: str) -> bool:
    esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma_header)
```

Responda con un código `2xx` en menos de 10 segundos. Si no, la plataforma reintenta.

---

## 10. Errores

| Código | Significa | Qué hacer |
|---|---|---|
| `200` / `202` | Correcto (`200` también cuando la `referencia_externa` ya existía) | — |
| `401` | API key inválida o revocada | Verificar la llave |
| `402` | **Sin documentos** | Comprar un paquete a su proveedor y reintentar |
| `403` | La conexión por API está suspendida o la llave no tiene permiso | Leer `detail` y contactar a su proveedor |
| `404` | El comprobante no existe (o es de otra empresa) | — |
| `409` | Operación no permitida en ese estado (p. ej. anular algo no aceptado) | Leer el mensaje |
| `422` | Datos inválidos. `detail` dice el campo y el motivo | Corregir los datos. **No gasta documentos** |
| `429` | Demasiadas solicitudes | Esperar los segundos que indica `Retry-After` |
| `5xx` | Error del servicio | Reintentar con la **misma** `referencia_externa` |

**Límite de uso:** 300 solicitudes por minuto por llave. Para cargas grandes,
envíe los comprobantes en secuencia y respete `Retry-After`.

---

## 11. De pruebas a producción

1. Su proveedor activa la empresa en **Pruebas**. Su programador hace la
   conexión y emite comprobantes de prueba hasta que todos queden **ACEPTADOS**.
   En pruebas los comprobantes van al ambiente de pruebas de Hacienda y **no
   tienen validez fiscal**.
2. Usted genera en ATV el **certificado y el usuario de producción** y se los
   entrega a su proveedor.
3. Su proveedor cambia la empresa a **Producción**.
4. **Su sistema no cambia nada:** la misma URL, la misma API key y el mismo webhook.

---

## 12. Lista de revisión para el programador

- [ ] La API key se lee de una variable de entorno o gestor de secretos.
- [ ] Cada venta se envía con su `referencia_externa` única.
- [ ] Se guardan `factura_id` y `clave` en el sistema.
- [ ] Ante errores de red o `5xx` se reintenta con la misma `referencia_externa`.
- [ ] Se maneja el `402` (sin documentos) mostrando un aviso claro al usuario.
- [ ] Se consulta el estado final (webhook o `GET /facturas/{id}`) y se actúa ante un `RECHAZADO`.
- [ ] El webhook verifica la firma `X-Facturacion-Firma`.
- [ ] Se usan códigos CABYS correctos (`GET /hacienda/cabys?q=`).
- [ ] Las notas de crédito y débito llevan el `codigo` de referencia correcto.
- [ ] Se entrega al cliente el PDF y el XML cuando el estado es `ACEPTADO`.
- [ ] Se vigila `X-Documentos-Disponibles` para comprar a tiempo.

---

## 13. Qué le entrega su proveedor (plantilla)

> Hola, [nombre]:
>
> Su empresa **[razón social]** ya está habilitada para facturar
> electrónicamente por medio de nuestra API. Entregue esta información a
> quien programa su sistema:
>
> - **URL base:** `https://[servidor]/api/v1`
> - **API key:** se la enviamos por [canal seguro]. Va en el encabezado
>   `X-API-Key` de cada solicitud. Guárdela como una contraseña.
> - **Manual de conexión por API:** adjunto.
> - **Documentación interactiva:** `https://[servidor]/docs`
>
> Empezamos en **ambiente de pruebas**. Cuando su programador confirme que
> todo funciona, pasamos a producción sin que tenga que cambiar nada.
>
> Documentos disponibles: **[cantidad]**. Le avisaremos cuando queden pocos.
