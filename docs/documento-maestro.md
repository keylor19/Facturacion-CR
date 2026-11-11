# Documento maestro del proyecto

Sistema de facturación electrónica para Costa Rica (Hacienda, comprobantes v4.4) con
contabilidad, vendido por autoservicio y cobrado por servicio.

Este documento reúne en un solo lugar qué es el sistema, cómo se cobra, quién lo usa, qué
hace cada módulo, cómo está construido, cómo se instala y opera, y qué falta para salir a
producción. Los detalles de uso están en los manuales de cada tipo de usuario (sección 13).

## Índice

1. Resumen
2. Modelo de negocio y cobro
3. Tipos de usuario y permisos
4. Recorrido de un cliente nuevo (autoservicio)
5. Módulos del sistema
6. Cumplimiento con Hacienda
7. Contabilidad
8. Integraciones
9. Arquitectura técnica
10. Seguridad
11. Instalación, configuración y operación
12. Calidad y pruebas
13. Documentación disponible
14. Estado del proyecto y pendientes
15. Glosario

---

## 1. Resumen

| Tema | Descripción |
|---|---|
| **Qué es** | Plataforma en la nube para emitir, recibir y guardar comprobantes electrónicos ante el Ministerio de Hacienda de Costa Rica, con sistema de ventas en línea, contabilidad y conexión por API. |
| **Para quién** | Empresas y personas que facturan (desde su propio sistema o desde el navegador), y contadores que llevan la contabilidad de sus clientes. |
| **Cómo se vende** | Autoservicio: el cliente crea su cuenta, inscribe su empresa, compra documentos y activa los servicios que necesita. El administrador solo supervisa y confirma pagos. |
| **Cómo se cobra** | Cada servicio por aparte: documentos por paquete (prepago) y mensualidades por el sistema en línea, la contabilidad y la cuenta de contador, en una factura el día 1 de cada mes. |
| **Diferenciadores** | Pago por documento sin mensualidad obligatoria; API completo con webhooks y n8n; contabilidad integrada con asientos automáticos; al día con los cambios de Hacienda de noviembre de 2026. |

---

## 2. Modelo de negocio y cobro

### 2.1 Servicios y quién los paga

| Servicio | Quién lo paga | Cómo se cobra |
|---|---|---|
| **Documentos facturables** | La empresa | Paquetes prepago. Cada comprobante firmado y enviado a Hacienda gasta 1 documento (los reintentos no). Se recargan cuando quiera. |
| **Conexión por API** | La empresa | Sin mensualidad: solo gasta documentos. |
| **Sistema en línea** | La empresa que factura desde el navegador | Mensualidad. Se activa al inscribir la empresa, con días de prueba gratis. |
| **Contabilidad de la empresa** | La empresa, solo si el dueño la lleva él mismo | Mensualidad. |
| **Cuenta de contador** | El contador | Mensualidad que cubre todas las empresas que lleva (ellas no pagan contabilidad). |

### 2.2 Cómo funcionan las mensualidades

1. Al pedir un servicio, el sistema le muestra el precio y queda activo de inmediato. La
   primera vez tiene los días de prueba gratis. El precio queda fijo para ese cliente.
2. El **día 1** de cada mes se emite **una factura electrónica** por cliente con los
   servicios del mes anterior, **proporcional a los días** usados, a crédito por el plazo para
   pagar (10 días por defecto). Se le manda el detalle por correo.
3. Tres días antes del vencimiento llega un recordatorio. Si vence sin pagar, las
   **mensualidades se suspenden solas**; los documentos ya pagados siguen sirviendo por API.
4. El cliente paga por SINPE Móvil o transferencia y lo **reporta**; mientras el administrador
   lo confirma, no se suspende. Al confirmarlo, el pago queda como abono en la cuenta por
   cobrar de la empresa de la plataforma.

### 2.3 Precios (los fija el administrador)

En *Ventas → Facturación y avisos* y *Planes y ventas*:

- Planes de documentos (cantidad, precio, vigencia). Vienen siete planes creados, inactivos y en 0.
- Precio por mes del sistema en línea, de la contabilidad y de la cuenta de contador.
- Moneda de las mensualidades, días para pagar, documentos y días de prueba gratis.
- Un precio vacío significa que ese servicio no se cobra.

### 2.4 Pagos

- **Paquetes de documentos:** el cliente paga por SINPE o transferencia y reporta el pago
  (con foto opcional). El administrador lo aprueba y se acredita, con su factura.
- **Mensualidades:** como en 2.2.
- **Tarjeta:** pendiente. Requiere una cuenta de pasarela (Tilopay, ONVO o similar); con ella
  los pagos se acreditan solos.

---

## 3. Tipos de usuario y permisos

| Usuario | Qué ve y hace |
|---|---|
| **Administrador del servicio** | Supervisa: tablero, empresas, pagos por confirmar, mensualidades, ventas, bitácora. Puede dar de alta una empresa si un cliente lo pide. **No entra a la contabilidad.** Usa contraseña y verificación en dos pasos (no Google ni Microsoft). |
| **Dueño de la empresa** | Todo lo de su empresa: facturar, anular, precios, inventario, configuración, sus usuarios, sus servicios y pagos, y **la contabilidad de su empresa**. |
| **Administrativo** | Facturas, notas y anulaciones, cobros y facturas de proveedores. No cambia precios, no usa la caja, no ve la contabilidad. |
| **Cajero** | Vende (factura, tiquete, punto de venta) y cobra. No anula ni ve reportes ni contabilidad. |
| **Contador** | Usuario aparte. Escoge las empresas que lleva (por cédula; la empresa recibe aviso y su dueño puede quitarle el acceso) o inscribe las que no facturan aquí y carga sus XML. Solo ve la contabilidad: no factura ni ve el resto. |
| **API key** | Sistema de la empresa conectado por API: factura y consulta, sin contabilidad. |

El permiso se revisa en el servidor en cada solicitud; el menú del panel solo muestra lo
que cada uno puede usar.

---

## 4. Recorrido de un cliente nuevo (autoservicio)

1. **Crear la cuenta** en la página de entrada, con una de tres opciones:
   **Continuar con Google**, **Continuar con Microsoft** o **correo y contraseña** (se
   confirma con un enlace al correo). Elige *Voy a facturar* o *Soy contador*.
2. **Inscribir la empresa** (quien factura): cédula → *Buscar en Hacienda* llena el nombre y
   las actividades; completa nombre comercial, correo, teléfono y dirección. Se exige que esté
   inscrita en Hacienda con actividad activa. Queda como **dueño**, con documentos y días del
   sistema en línea de prueba.
3. **Primeros pasos** (lista que se marca sola): subir la llave criptográfica (.p12) y su PIN,
   usuario y contraseña de Hacienda (con *Probar conexión*), datos de la empresa, logo,
   productos, **usuarios de quienes facturan con él**, **compra de documentos y servicios**, y
   la primera factura.
4. **Facturar**, cobrar, recibir facturas de proveedores y, si lo activa, llevar la contabilidad.
5. **El contador** crea su cuenta como *Soy contador*, activa su mensualidad y escoge o inscribe
   sus empresas.

El administrador puede cerrar la inscripción en línea y ayudar a dar de alta una empresa.

---

## 5. Módulos del sistema

### 5.1 Facturación

- **Comprobantes:** factura (01), nota de débito (02), nota de crédito (03), tiquete (04),
  factura de compra (08), factura de exportación (09) y recibo electrónico de pago (10).
- **Formas de facturar:** factura rápida, formulario completo en 3 pasos, punto de venta con
  apertura y cierre de caja, proformas que se convierten en factura, preliminares.
- **Tiquete con solo el nombre** del cliente (sin cédula); la factura exige la cédula.
- **Facturas recurrentes:** alquileres o mensualidades que se emiten solas cada semana,
  quincena, mes o año (7:00 a. m.), sin duplicar.
- **Anulación** con nota de crédito en un paso; códigos 01 (normal) y 13 (error material, con
  efecto en el mes original).
- **Contingencia** (sin internet) y reintentos automáticos si Hacienda no responde.
- **Exoneraciones** validadas en Hacienda; IVA en todas sus tarifas, otros cargos (10 % de
  servicio), IVA devuelto, selectivo de consumo e impuestos específicos.

### 5.2 Entrega del comprobante

- PDF en **hoja carta** o **tiquete para impresora térmica** de 80 mm o 58 mm.
- **Correo** automático al aceptarlo Hacienda (XML, respuesta y PDF).
- **WhatsApp:** enlace de descarga firmado, sin usuario, con el mensaje listo.

### 5.3 Clientes, productos e inventario

- Catálogo de clientes (formulario corto para cliente común; datos de contribuyente si está
  inscrito), productos con CABYS e IVA, categorías, descuentos automáticos y combos.
- Inventario con kárdex y costo promedio; importación desde Excel.

### 5.4 Cobros

- **Cuentas por cobrar:** abonos del crédito comercial, recibos de pago (condiciones 08 y 10),
  antigüedad de saldos (al día, 1-30, 31-60, 61-90, más de 90), estado de cuenta imprimible por
  cliente y **recordatorios automáticos** por correo a los 1, 8, 15, 30 y 60 días de atraso.

### 5.5 Facturas de proveedores

- Recepción automática desde un buzón de correo (IMAP) o carga manual del XML.
- Verificación de firma y respuesta a Hacienda (aceptar, aceptar parcial, rechazar).

### 5.6 Reportes

- Tablero del mes, reportes por cliente y por producto, descarga mensual de XML y PDF (ZIP).
- Reporte de IVA, borrador D-104 y libros de ventas y compras: dentro de **Contabilidad**.

### 5.7 Administración del servicio

- Tablero con: compras y mensualidades por confirmar, inscripciones de la semana, cuentas
  sin empresa, empresas con problemas, ventas del mes.
- Empresas (ficha, certificado, credenciales, alertas), usuarios, planes y ventas, pagos por
  revisar, mensualidades, contabilidad de la plataforma, ajustes y bitácora.

---

## 6. Cumplimiento con Hacienda

- Comprobantes **versión 4.4** firmados (XAdES) con la llave criptográfica de cada empresa.
- **Validación contra los XSD oficiales** antes de enviar (opcional, `XSD_DIR`).
- Códigos de la actualización del 22-04-2026 (obligatorios desde el 01-11-2026): 13, 14, 15,
  16 y 17 de referencia, y período fiscal de las notas por error material.
- Consulta de contribuyentes, actividades, exoneraciones, CABYS y tipo de cambio, con caché
  local para cuando Hacienda no responde.
- Callback de Hacienda y consultas periódicas del estado de lo enviado.
- Ambientes de **pruebas (stag)** y **producción** por empresa.

---

## 7. Contabilidad

Módulo para el **dueño de la empresa** (la suya, con mensualidad) y el **contador** (todas las
que lleva, con su mensualidad). Ni los demás usuarios ni el administrador lo ven.

| Parte | Qué hace |
|---|---|
| **Catálogo de cuentas** | Base NIIF para PYMES creada con un clic; editable. Cuentas de grupo y de movimiento. |
| **Asientos automáticos** | *Contabilizar el mes* crea el asiento de cada venta, nota, recibo, compra y abono, y el **costo de ventas desde el inventario** (costo promedio). No duplica. |
| **Asientos manuales** | No se guardan si no cuadran; los automáticos se pueden corregir (quedan marcados). |
| **Libros** | Libro diario y libro mayor. |
| **Estados financieros** | Balance general, estado de resultados, balance de comprobación (Excel, imprimir o PDF). |
| **Cierres** | Cierre de meses (bloquea cambios) y **asiento de cierre anual** con su archivo digital en Excel para guardarlo o copiarlo a otro sistema. |
| **Impuestos** | Reporte de IVA, borrador D-104 para copiar a TRIBU-CR, libros de ventas y compras. |
| **Empresas que no facturan aquí** | El contador las inscribe y carga sus XML de Hacienda (ventas y compras se distinguen solas, sin duplicar). |

Todo se lleva en colones: los comprobantes en otra moneda se convierten con su tipo de cambio.

---

## 8. Integraciones

| Integración | Qué permite |
|---|---|
| **API REST** (`/api/v1`) | Emitir, consultar, anular, PDF, cobros, recurrentes, catálogo, recepción y más, con API key. Documentación interactiva en `/docs`. |
| **Webhooks firmados** (HMAC) | Avisos al sistema del cliente: comprobante aceptado o rechazado, saldo bajo, servicios por vencer, certificado por vencer. |
| **n8n** | Flujo listo para importar (`docs/n8n/`): cliente por cédula, productos, emitir, consultar, acciones, avisos y respaldo mensual de XML. |
| **WooCommerce** | Complemento (`integraciones/woocommerce/`): factura sola cada pedido (factura con cédula, tiquete sin ella). |
| **Google y Microsoft** | Crear cuenta y entrar (OpenID Connect). |
| **Correo** | SMTP de salida (comprobantes, avisos, activación) e IMAP para las facturas de proveedores. |

---

## 9. Arquitectura técnica

### 9.1 Componentes

| Componente | Tecnología | Función |
|---|---|---|
| `api` | Python 3.12, FastAPI, SQLAlchemy, Alembic | API REST y panel web (archivos estáticos) |
| `worker` | Celery | Envía a Hacienda, consulta estados, correos y webhooks |
| `beat` | Celery beat | Tareas programadas (9.3) |
| `db` | PostgreSQL 16 | Base de datos |
| `redis` | Redis | Cola de trabajos, caché y límites de uso |
| `caddy` | Caddy 2 (producción) | HTTPS automático con Let's Encrypt |
| `respaldo` | pg_dump (producción) | Respaldo diario verificado |

El panel web es JavaScript sin frameworks ni librerías externas, con una política de
seguridad de contenido (CSP) estricta. Firma XML con `signxml`/`cryptography`, PDF con
ReportLab y Excel con openpyxl.

### 9.2 Organización del código

| Carpeta | Contenido |
|---|---|
| `api/routes/` | Rutas del API: facturas, recepción, catálogo, cajas, borradores, cobros, recurrentes, contabilidad, reportes, saldo, compras, servicios, registro, empresa, emisores, administración, auth, Hacienda, públicas |
| `api/services/` | Lógica: emisión, firma, XML, Hacienda, inventario, cobros, contabilidad, mensualidades, registro, OAuth, permisos, PDF, correo, webhooks… |
| `api/models/` | Modelos de base de datos y esquemas de validación |
| `api/panel/` | Panel web (HTML, CSS, JavaScript) y páginas legales |
| `workers/` | Tareas de Celery y su programación |
| `migrations/` | 23 migraciones de base de datos (Alembic) |
| `tests/` | Pruebas automáticas |
| `docs/` | Manuales y guías; `docs/manuales/` en Word |
| `integraciones/` | Complemento de WooCommerce |
| `deploy/` | Caddyfile y script de respaldo |
| `xsd/` | Esquemas oficiales de Hacienda |

### 9.3 Tareas programadas (hora de Costa Rica)

| Cuándo | Tarea |
|---|---|
| Cada 5 min | Reenviar lo pendiente; revisar buzones de correo de proveedores |
| Cada 10 min | Consultar el estado de lo enviado sin respuesta |
| 3:00 | Actualizar datos de Hacienda guardados, tipo de cambio y CABYS |
| 6:00 / 6:10 / 6:20 | Avisos de certificados, paquetes y servicios por vencer |
| Día 1, 6:30 | Factura mensual de los servicios |
| 7:00 | Facturas recurrentes |
| 8:00 | Recordatorios de cobro a clientes de las empresas |
| 9:00 | Recordatorios y suspensión de mensualidades |

---

## 10. Seguridad

- **Datos sensibles cifrados** con `MASTER_KEY`: llaves criptográficas, PIN, contraseñas de
  Hacienda, secretos de webhooks y de verificación en dos pasos. Las API keys y los enlaces de
  activación se guardan solo como hash.
- **Contraseñas** con scrypt; bloqueo por intentos fallidos; **verificación en dos pasos**
  obligatoria para administradores.
- **Aislamiento entre empresas:** cada solicitud se limita a la empresa del usuario; el
  contador solo a las que tiene a cargo, y solo a las rutas de contabilidad.
- **Permisos por rol** revisados en el servidor; bitácora de cada acción.
- **Límites de uso** por IP, usuario y llave; campo trampa contra robots en la inscripción.
- **Google/Microsoft:** `state` firmado y cookie del mismo navegador (evita entrar con la
  cuenta de otro); los administradores no entran por ahí.
- **Enlaces de WhatsApp** firmados (no se pueden adivinar ni cambiar).
- **Webhooks** solo hacia direcciones públicas HTTPS (no a la red interna) y firmados.
- **XML externos** leídos con un analizador seguro (sin entidades externas).
- **HTTPS** obligatorio en producción; CSP estricta en el panel.

---

## 11. Instalación, configuración y operación

### 11.1 Requisitos

- Un servidor (VPS) con Docker y Docker Compose, y un **dominio con HTTPS**.
- Correo de salida (SMTP) para comprobantes, avisos y activación de cuentas.
- Credenciales de Google y Microsoft (opcionales) para sus botones de ingreso.

### 11.2 Variables principales (`.env`)

| Variable | Para qué |
|---|---|
| `AMBIENTE` | `stag` (pruebas) o `prod` |
| `DATABASE_URL`, `POSTGRES_PASSWORD`, `REDIS_URL` | Base de datos y cola |
| `MASTER_KEY` | Cifra los datos sensibles. **Guardar copia fuera del servidor**: sin ella no se recuperan las llaves de los clientes. |
| `JWT_SECRET`, `CALLBACK_TOKEN` | Sesiones y callback de Hacienda |
| `CALLBACK_BASE_URL`, `URL_PUBLICA` | Dirección pública del servicio |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Correo de salida |
| `GOOGLE_CLIENT_ID/SECRET`, `MICROSOFT_CLIENT_ID/SECRET` | Ingreso con Google y Microsoft |
| `XSD_DIR` | Validación con los XSD oficiales |
| `ALERTA_URL` | Aviso si falla el respaldo diario |

### 11.3 Puesta en marcha

Pasos detallados en `docs/despliegue.md`: copiar el proyecto, crear `.env`, generar secretos,
descargar los XSD, `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`,
crear el usuario administrador (`python -m api.cli crear-usuario … --admin`) y configurar la
empresa que factura las ventas y los precios.

### 11.4 Operación diaria del administrador

1. Revisar el tablero: compras y mensualidades por confirmar, empresas con problemas.
2. Confirmar los pagos reportados.
3. Atender a quien pida ayuda.

### 11.5 Respaldos y monitoreo

- Respaldo diario de la base, **verificado** al crearlo, con retención configurable; aviso a
  `ALERTA_URL` si falla. Copiar los respaldos fuera del servidor.
- Monitor externo (p. ej. UptimeRobot) sobre `/api/v1/health`.

---

## 12. Calidad y pruebas

- **347 pruebas automáticas** (pytest) sobre PostgreSQL: emisión y XML (validado contra los XSD
  oficiales), firma, Hacienda, seguridad y permisos, cobros, recurrentes, contabilidad, cierre
  anual, costo de ventas, inscripción (incluido Google simulado), mensualidades y más.
- **Demo** con datos inventados en `http://localhost:8001/panel/` (base separada).

---

## 13. Documentación disponible

| Documento | Para quién |
|---|---|
| `docs/manuales/Manual del administrador.docx` | Usted: configuración, precios, supervisión, Google/Microsoft |
| `docs/manuales/Manual del cliente - Sistema en linea.docx` | Empresas que facturan desde el navegador |
| `docs/manuales/Manual de conexion por API.docx` | Programadores de los sistemas de los clientes |
| `docs/manuales/Manual del contador.docx` | Contadores y dueños que llevan su contabilidad |
| `docs/despliegue.md` | Instalación en el servidor |
| `docs/n8n.md` y `docs/n8n/` | Flujo de n8n |
| `integraciones/woocommerce/LEEME.md` | Complemento de WooCommerce |
| `api/panel/legal/` | Plantillas de términos del servicio y política de privacidad |
| `README.md` | Resumen técnico y lista de endpoints |

---

## 14. Estado del proyecto y pendientes

### 14.1 Listo

Todo lo descrito en las secciones 2 a 12 está construido, probado y funcionando en la demo.

### 14.2 Para salir a producción

| Pendiente | Responsable |
|---|---|
| Contratar el servidor (VPS) y el dominio; apuntar el DNS | Usted |
| Correo de salida (SMTP) | Usted (datos) → configuración |
| Pruebas en el ambiente de pruebas de Hacienda con una empresa real (contraseña y PIN de stag) | Usted (datos) → pruebas |
| Credenciales de Google y Microsoft con la dirección del dominio | Usted |
| Generar secretos de producción y guardar `MASTER_KEY` fuera del servidor | Ya generados en `Secretos-produccion.txt` |
| Fijar precios: planes, mensualidades, días para pagar, prueba gratis | Usted |
| Configurar la empresa que emite las facturas de las ventas y su CABYS | Usted |
| Completar las plantillas legales y que las revise un abogado | Usted |
| Inscribirse como proveedor de sistemas ante Hacienda | Usted |
| Guardar los cambios en git (commit) y pasarlos a la rama principal | Pendiente de su aprobación |

### 14.3 Mejoras futuras

- Pago con tarjeta en línea (pasarela) para que los pagos se acrediten solos.
- Complemento para Shopify.
- Punto de venta sin internet (modo fuera de línea).

---

## 15. Glosario

| Término | Significado |
|---|---|
| **Documento** | Unidad de cobro: cada comprobante firmado y enviado a Hacienda gasta uno. |
| **Llave criptográfica (.p12)** | Archivo con que la empresa firma sus comprobantes; se descarga en TRIBU-CR con su PIN. |
| **TRIBU-CR** | Sistema de Hacienda (antes ATV) donde se declaran los impuestos y se generan las llaves. |
| **CABYS** | Catálogo de bienes y servicios de Hacienda; cada línea de un comprobante lleva su código. |
| **D-104** | Declaración mensual del IVA. |
| **Mensualidad** | Servicio que se cobra cada mes en la factura del día 1. |
| **Contabilizar** | Crear los asientos contables de los comprobantes del mes. |
| **stag / prod** | Ambiente de pruebas / producción de Hacienda. |
