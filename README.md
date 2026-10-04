# API de Facturación Electrónica — Costa Rica (Hacienda v4.4)

Plataforma para **contadores y sistemas de facturación**: emite y recibe
comprobantes electrónicos v4.4 ante el Ministerio de Hacienda para **varias
empresas** (emisores), cada una con su propio certificado y credenciales.

Cualquier sistema (POS, ERP, e-commerce, hoja de cálculo con scripts) se
integra enviando JSON por HTTPS; la plataforma genera el XML, lo firma
(XAdES-EPES), lo valida contra los XSD oficiales, lo envía, da seguimiento
al estado y notifica.

## Qué incluye

| Área | Funcionalidad |
|---|---|
| **Comprobantes** | Factura (01), Nota de débito (02), Nota de crédito (03), Tiquete (04), Factura de compra (08), Factura de exportación (09), **Recibo electrónico de pago (10)** |
| **Contingencia** | Situación 2 (sustituye comprobante provisional en papel) y 3 (emitido sin internet) con la fecha real de la venta |
| **Impuestos** | IVA con todas las tarifas (01–11), exentos, no sujetos, **exoneraciones** (parciales o totales), IVA de bienes usados (factor), IVA cobrado en fábrica, impuesto asumido por el emisor, IVA devuelto, selectivo de consumo e impuestos específicos (combustibles, bebidas, tabaco, cemento), descuentos, **otros cargos** (p. ej. 10 % de servicio) |
| **Recepción** | Registro de facturas de proveedores (XML), verificación de firma y **Mensaje Receptor**: aceptación, aceptación parcial o rechazo con condición del IVA (crédito fiscal) |
| **Hacienda** | Envío y consulta de estado, listado de comprobantes en Hacienda, callback, **consulta de contribuyentes y actividades**, **exoneraciones**, **CABYS** y **tipo de cambio** (automático para USD/EUR) |
| **Documentos** | XML firmado, respuesta de Hacienda y **PDF** con QR; **envío por correo** automático al aceptarse |
| **Contabilidad** | **Resumen de IVA mensual** (insumo D-104), **libros de ventas y compras** en CSV (Excel) |
| **Operación** | Anulación con nota de crédito en un paso, reintentos automáticos, consulta periódica de estados, alerta de certificados por vencer, **webhooks** firmados, bitácora de auditoría |
| **Panel web** | Para contadores: tablero, emisión con búsqueda en Hacienda y CABYS, comprobantes, facturas de proveedores, reportes, consultas, empresas y usuarios (`/panel/`) |
| **Seguridad** | Usuarios con contraseña (scrypt) y bloqueo por intentos, API keys hasheadas por emisor o de administrador, aislamiento entre empresas, certificados y contraseñas **cifrados**, callback con token y verificación contra Hacienda, parser XML sin XXE, sin root en Docker |

## Stack
FastAPI + PostgreSQL + Redis + Celery (worker + beat) + Alembic, con Docker Compose.

## 1. Requisitos (por cada empresa)
1. Inscripción en ATV con Comprobantes Electrónicos activo.
2. **Certificado digital** (.p12) y su PIN.
3. **Usuario y contraseña del API** de comprobantes (distintos en pruebas y producción).
4. Código de actividad económica y códigos **CABYS** de sus productos.

## 2. Instalación
```bash
cp .env.example .env
docker compose run --rm --no-deps api python -m api.cli generar-master-key   # -> MASTER_KEY en .env
python -c "import secrets; print(secrets.token_urlsafe(32))"      # -> API_KEYS y CALLBACK_TOKEN
docker compose run --rm --no-deps --user root api python -m api.cli descargar-xsd   # XSD oficiales en xsd/
docker compose up -d --build                                      # aplica migraciones y arranca
```
- `.env`, certificados y XSD están en `.gitignore`: **nunca** los suba a git.
- **Respalde `MASTER_KEY`**: sin ella no se pueden leer los certificados guardados.
- Con `AMBIENTE=prod` la aplicación no arranca si la configuración es insegura.
- En producción exponga la API con NGINX/Caddy + HTTPS (`client_max_body_size 5m`).

Documentación interactiva (solo en stag): `http://localhost:8000/docs`

### Panel web para contadores
```bash
docker compose run --rm api python -m api.cli crear-usuario --email contador@firma.cr --nombre "Ana" --admin
```
Ingrese en `http://localhost:8000/panel/` (en producción, por HTTPS). Desde el panel:
- **Empresas**: alta (con datos traídos de Hacienda), certificado .p12, credenciales del API, prueba de conexión, API keys y webhook.
- **Usuarios**: administradores (todas las empresas) o usuarios de una sola empresa (p. ej. el cliente del contador).
- **Nuevo comprobante**: cliente buscado en Hacienda (avisa si está moroso u omiso), buscador CABYS, exoneraciones validadas en Hacienda, tipo de cambio, contingencia.
- **Comprobantes**: PDF, XML, estado, reenvío, anulación, recibo de pago, correo.
- **Facturas de proveedores**: subir XML y aceptar / aceptar parcialmente / rechazar.
- **Reportes** (resumen de IVA y libros en Excel) y **Consultas Hacienda**.

Las sesiones duran `SESION_HORAS`; tras `MAX_INTENTOS_LOGIN` intentos fallidos el usuario se bloquea `MINUTOS_BLOQUEO_LOGIN` minutos.

### Venta por consumo (paquetes de documentos)
Cada empresa compra **paquetes de documentos**; cada documento firmado y
enviado a Hacienda (comprobantes, recibos de pago y mensajes receptor)
descuenta 1. Sin saldo la emisión responde `402`.
- **Planes y ventas** (panel) o `POST /api/v1/planes`: catálogo con cantidad, precio y vigencia.
- **Empresas → Vender paquete** (panel) o `POST /api/v1/emisores/{id}/paquetes`
  (`plan_id` o `documentos`/`precio`, `referencia_pago`): se registra tras confirmar el pago (SINPE, transferencia).
- `GET /api/v1/admin/ventas?anio=&mes=`: ingresos, paquetes vendidos y consumo por empresa.
- El cliente ve su saldo en **Mi saldo**, en `GET /api/v1/saldo` y en el header `X-Documentos-Disponibles`.
- Avisos (webhook y correo) de saldo bajo (`SALDO_ALERTA_DOCUMENTOS`), agotado y paquetes por vencer.
- El cobro no se duplica: reintentos, reenvíos y `referencia_externa` repetida no consumen.
  Los rechazos de Hacienda **no** devuelven el crédito; una emisión que falla antes de firmarse no cobra.
- `CONTROL_SALDO=false` desactiva el control (uso interno sin venta).
- Pasarela de pago: el punto de integración es `api.services.saldo.acreditar(...)`.
- ⚠️ Al actualizar un sistema que ya factura, acredite paquetes a las empresas existentes
  **antes** de desplegar (o despliegue con `CONTROL_SALDO=false`), o no podrán emitir.

Límite de uso: `LIMITE_SOLICITUDES_MINUTO` por llave/usuario (429 + `Retry-After`) y
`LIMITE_LOGIN_MINUTO` por IP en el inicio de sesión.

**Documentación:**
- [docs/despliegue.md](docs/despliegue.md): poner el servicio en línea (dominio, HTTPS, respaldos).
- [docs/manual-administrador.md](docs/manual-administrador.md): alta de cada cliente, conexión con Hacienda y venta de documentos.
- [docs/integracion.md](docs/integracion.md): guía para los programadores de los sistemas de sus clientes.
Para publicar la documentación interactiva en producción: `DOCS_PUBLICAS=true`.

## 3. Alta de una empresa (llave de administrador)
```bash
H="X-API-Key: $ADMIN_KEY"
# 1) Emisor
curl -X POST localhost:8000/api/v1/emisores -H "$H" -H "Content-Type: application/json" -d '{
  "tipo_identificacion": "02", "numero_identificacion": "3101123456", "nombre": "Mi Empresa S.A.",
  "codigo_actividad": "620100", "correo": "facturas@miempresa.cr",
  "provincia": "1", "canton": "01", "distrito": "01", "otras_senas": "Dirección exacta",
  "ambiente": "stag"}'
# 2) Certificado (.p12 + PIN) y credenciales de Hacienda
curl -X PUT localhost:8000/api/v1/emisores/$ID/certificado -H "$H" -F archivo=@certificado.p12 -F password=1234
curl -X PUT localhost:8000/api/v1/emisores/$ID/credenciales-hacienda -H "$H" -H "Content-Type: application/json" \
     -d '{"usuario": "cpj-3-101-123456@stag.comprobanteselectronicos.go.cr", "password": "..."}'
# 3) Verificar conexión con Hacienda y certificado
curl -X POST localhost:8000/api/v1/emisores/$ID/probar-conexion -H "$H"
# 4) Llave para el sistema de facturación de esa empresa (se muestra una sola vez)
curl -X POST localhost:8000/api/v1/api-keys -H "$H" -H "Content-Type: application/json" -d '{"nombre": "POS", "emisor_id": "'$ID'"}'
```
Con la llave de administrador se puede operar sobre cualquier empresa
enviando el header `X-Emisor-Id`. Cuando la empresa pase a producción:
`PATCH /api/v1/emisores/{id}` con `{"ambiente": "prod"}` y cargar las
credenciales de producción.

## 4. Emitir
```bash
curl -X POST localhost:8000/api/v1/facturas -H "X-API-Key: $LLAVE" -H "Content-Type: application/json" -d '{
  "tipo_documento": "01", "sucursal": 1, "terminal": 1, "referencia_externa": "POS1-000123",
  "receptor": {"nombre": "Juan Pérez", "tipo_identificacion": "01", "numero_identificacion": "112345678", "correo": "juan@example.com"},
  "productos": [{"codigo_cabys": "8314100000000", "descripcion": "Consultoría", "cantidad": 1,
                 "unidad_medida": "Sp", "precio_unitario": 50000, "codigo_tarifa_iva": "08"}],
  "medios_pago": [{"tipo": "06"}]}'
```
Estados: `PENDIENTE → ENVIADO → ACEPTADO | RECHAZADO` (o `ERROR_COMUNICACION`, que se reintenta solo).

Opciones del comprobante: `moneda`/`tipo_cambio` (automático para USD/EUR),
`condicion_venta`/`plazo_credito`, varios `medios_pago` con monto,
`otros_cargos`, `referencia` (NC/ND), `proveedor` (08),
`codigo_actividad_emisor` (si la empresa tiene varias actividades), `notas`.
Por línea: `descuento` + `codigo_descuento`, `exoneracion`, `impuestos`
(p. ej. selectivo + IVA), `partida_arancelaria` (09).

`referencia_externa` hace la llamada **idempotente**: si su sistema reintenta,
recibe el mismo comprobante en vez de uno duplicado.

**IVA especial por línea**: `no_sujeto`, `iva_cobrado_fabrica` (`01`/`02`),
`impuesto_asumido_emisor`, `impuestos` con código `08` + `factor_calculo_iva`
(bienes usados) o impuestos específicos (`03`–`06`) con `monto` y
`datos_especificos`. `iva_devuelto` a nivel de comprobante (01/04).

**Contingencia**: `"situacion": "3"` (sin internet) o `"2"` (sustituye un
comprobante provisional; requiere `referencia` tipo `08` código `05`) con
`"fecha_emision"` = fecha real de la venta (máximo `DIAS_MAX_CONTINGENCIA` días).

**Recibo electrónico de pago (10)**: para facturas a crédito con condición
`08` (Estado) o `10` (IVA hasta 90 días), una vez aceptadas:
`POST /api/v1/facturas/{id}/recibo-pago` con `{"monto": ...}` (IVA incluido).
El IVA se prorratea por tarifa y se controla el saldo (`GET /facturas/{id}/pagos`).

## 5. Referencia de la API

| Método y ruta | Uso |
|---|---|
| `POST /api/v1/facturas` | Emitir comprobante |
| `GET /api/v1/facturas?estado=&tipo_documento=&desde=&hasta=&receptor=` | Buscar |
| `GET /api/v1/facturas/{id}` · `/eventos` · `/xml?tipo=firmado\|respuesta` · `/pdf` | Detalle, bitácora, XML, PDF |
| `POST /api/v1/facturas/{id}/anular` | Nota de crédito que anula el comprobante |
| `POST /api/v1/facturas/{id}/reenviar` · `/consultar` · `/correo` | Reenviar, consultar estado, reenviar correo |
| `POST /api/v1/recepcion` (base64) · `/recepcion/archivo` (archivo) | Registrar factura de proveedor |
| `GET /api/v1/recepcion?pendientes=true` | Facturas de proveedores sin responder |
| `POST /api/v1/recepcion/{id}/mensaje` | Aceptar (1) / aceptar parcial (2) / rechazar (3) |
| `GET /api/v1/reportes/resumen-iva?anio=&mes=` | Resumen de IVA del mes |
| `GET /api/v1/reportes/ventas.csv` · `/compras.csv` | Libros para Excel |
| `GET /api/v1/hacienda/contribuyentes/{id}` · `/exoneraciones/{aut}` · `/cabys?q=` · `/tipo-cambio/USD` | Consultas públicas |
| `GET /api/v1/hacienda/estado/{clave}` · `/comprobantes` · `/comprobantes/{clave}` | Consultas directas a Hacienda |
| `POST/GET/PATCH /api/v1/emisores…` · `/api-keys` | Administración |
| `GET /api/v1/health` · `/health/detalle` | Monitoreo (incluye vencimiento de certificados) |

**Webhooks** (`PUT /api/v1/emisores/{id}/webhook`): POST con
`X-Facturacion-Evento` (`comprobante.aceptado`, `comprobante.rechazado`,
`mensaje_receptor.aceptado`, `certificado.por_vencer`…) y
`X-Facturacion-Firma: sha256=HMAC(cuerpo, secreto)`; valide la firma.

## 6. Pruebas
```bash
docker compose run --rm api sh -c "pip install -q --user -r requirements-dev.txt && python -m pytest -q"
```
Incluyen la validación de **todos los comprobantes, el Mensaje Receptor, el
Recibo de Pago, los casos de IVA especial y la contingencia contra los XSD
oficiales** de Hacienda (si están en `xsd/`).

Con un certificado real (sandbox o producción) se prueba además la firma con
él, sin copiarlo al proyecto:
```bash
docker compose run --rm -v "/ruta/al/certificado:/cert:ro" -e TEST_P12_PATH=/cert/certificado.p12 \
  -e TEST_P12_PIN=1234 api sh -c "pip install -q --user -r requirements-dev.txt && python -m pytest -q"
```

## 7. Verificación con Hacienda (sandbox)
El 2026-10-02 se probó contra el **ambiente de pruebas real de Hacienda** con un
certificado y credenciales de sandbox. **19 de 19 documentos aceptados**:

| Documento | Resultado |
|---|---|
| Factura (servicio + mercancía, transferencia) | Aceptada |
| Factura con descuento, línea exenta y línea no sujeta | Aceptada |
| Factura en dólares (tipo de cambio automático) | Aceptada |
| Factura a crédito (condición 10) + recibo electrónico de pago del 50 % | Aceptadas |
| Factura sin internet (situación 3) | Aceptada (Hacienda advierte envío extemporáneo) |
| Restaurante: servicio 10 % + pago mixto efectivo/tarjeta | Aceptada |
| Tiquete (colones y dólares) | Aceptados |
| Nota de débito y nota de crédito de anulación | Aceptadas |
| Factura de compra (08) y de exportación (09) | Aceptadas |
| Mensaje receptor: aceptación, aceptación parcial y rechazo | Aceptados |

Reglas que aplica Hacienda y que el sistema ya valida o aplica:
- **CABYS**: debe existir en el catálogo; el sistema lo verifica antes de firmar (`VALIDAR_CABYS`).
- **Tarifas**: `10` cuenta como exenta; `01` y `11` cuentan siempre como **no sujetas**;
  `05` (transitorio 0 %) solo en notas de crédito y débito; en exportación lo exento va con `10`.
- **Factura de compra**: el proveedor debe tener identificación registrada en Hacienda y la
  referencia debe indicar `numero` (consecutivo de 20 dígitos o clave de 50).
- **Código de actividad**: se acepta tal como lo publica Hacienda (`7310.0`).
- **Ubicación del emisor**: si provincia/cantón/distrito no coinciden con el domicilio
  registrado en Hacienda, se acepta con la advertencia `-37`; registre la dirección real.

Antes de producción: cargue las credenciales y el certificado de **producción** de cada
empresa, cambie su ambiente a `prod` y emita un documento real de prueba.
El resumen de IVA es un insumo y no reemplaza la revisión de la D-104.