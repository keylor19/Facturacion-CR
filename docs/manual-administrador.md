# Manual del administrador

Guía paso a paso para administrar la plataforma: cómo dar de alta una
empresa, qué pedirle, cómo venderle documentos y servicios, cómo activar o
desactivar lo que usa, y cómo revisar cada día que todo funcione.

Todo se hace desde el panel: `https://<su-dominio>/panel/`, entrando con su
usuario de **administrador**.

---

## Índice

1. [Cómo funciona el negocio](#1-cómo-funciona-el-negocio)
2. [Configuración inicial (una sola vez)](#2-configuración-inicial-una-sola-vez)
3. [Qué pedirle a cada cliente](#3-qué-pedirle-a-cada-cliente)
4. [Dar de alta la empresa](#4-dar-de-alta-la-empresa)
5. [Conectarla con Hacienda](#5-conectarla-con-hacienda)
6. [Cobrarle: documentos y servicios](#6-cobrarle-documentos-y-servicios)
7. [Activar y desactivar servicios](#7-activar-y-desactivar-servicios)
8. [Entregar al cliente que se conecta por API](#8-entregar-al-cliente-que-se-conecta-por-api)
9. [Entregar al cliente que usa el sistema en línea](#9-entregar-al-cliente-que-usa-el-sistema-en-línea)
10. [Pasar de pruebas a producción](#10-pasar-de-pruebas-a-producción)
11. [Revisión diaria: que todo vaya bien](#11-revisión-diaria-que-todo-vaya-bien)
12. [Cierre de cada mes](#12-cierre-de-cada-mes)
13. [Situaciones frecuentes](#13-situaciones-frecuentes)
14. [Anexos: seguridad, datos de Hacienda y rechazos comunes](#14-anexos)

---

## 0. Autoservicio: usted solo supervisa

Los clientes hacen todo solos; usted solo vigila que todo funcione y ayuda si se lo piden.

| Quién | Qué hace solo |
|---|---|
| **Quien va a facturar** | Crea su cuenta (Google, Microsoft o correo), **inscribe su empresa** con todos sus datos (se verifica en Hacienda), recibe la prueba gratis, sube su llave de Hacienda, **crea los usuarios de quienes facturan con él** y **compra** su paquete de documentos y el sistema en línea. |
| **Contador** | Crea su cuenta como *Soy contador* y escoge o inscribe las empresas a las que les lleva la contabilidad. |

### Cada servicio se cobra por aparte

| Servicio | Quién lo paga | Cómo se cobra |
|---|---|---|
| **Documentos facturables** | La empresa | Paquetes prepago: los compra y los recarga cuando quiera (Mi saldo → Comprar documentos). |
| **Sistema en línea** | La empresa que factura desde el navegador | Mensualidad. Se activa al inscribir la empresa, con días de prueba gratis. |
| **Contabilidad de la empresa** | La empresa, solo si el dueño la lleva él mismo | Mensualidad. Se activa en Mis servicios. |
| **Cuenta de contador** | El contador | Mensualidad. Cubre todas las empresas que lleva (ellas no pagan contabilidad). |

La conexión por API no tiene mensualidad: se paga solo con documentos.

**Cómo se cobran las mensualidades:**
1. Al pedir un servicio se le muestra el precio («₡X por mes») y queda activo de inmediato. La
   primera vez, con los días de prueba gratis. El precio queda fijo para ese cliente.
2. El **día 1** de cada mes el sistema emite **una factura electrónica** por cliente con los
   servicios del mes anterior, **proporcional a los días** que los tuvo (sin contar la prueba), a
   crédito por los días para pagar, y le manda el detalle por correo.
3. Tres días antes del vencimiento le llega un recordatorio. Si vence sin pagar, las
   **mensualidades se suspenden solas** (los documentos ya pagados siguen sirviendo por API) y se
   reactivan apenas reporta el pago.
4. El cliente paga por SINPE o transferencia y lo **reporta** en Mis servicios → Facturas.

**Lo que le queda a usted:**

- **Fijar los precios una vez** en *Ventas → Facturación y avisos*: planes de documentos, precio por
  mes del sistema en línea, de la contabilidad y de la cuenta de contador, y los días para pagar.
  Un precio vacío = ese servicio no se cobra.
- **Mensualidades** (*Ventas → Mensualidades*): confirmar los pagos que los clientes reportan.
  Ve el estimado del mes y puede generar a mano las facturas de un mes si el sistema no lo hizo.
- **Compras por revisar** (*Ventas → Pagos por revisar*): confirmar que el SINPE o la transferencia
  de un paquete de documentos llegó y aprobarlo. Es lo único que el sistema no puede verificar solo; con una pasarela de pago
  con tarjeta se podría automatizar.
- Mirar el **Tablero**: *Pagos por revisar*, *Inscripciones esta semana* (y cuántas cuentas no
  han inscrito su empresa), empresas con problemas.
- Ayudar a quien se lo pida: en **Empresas** puede seguir dando de alta una empresa (sección 4).
- Fijar precios una vez: planes y precio por mes del sistema en línea (secciones 2.2 y 2.3).

### 0.1 Activar «Continuar con Google» y «Continuar con Microsoft»

Los botones aparecen solos cuando el servidor tiene sus credenciales en el `.env`
(`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`).
Se necesita el dominio con HTTPS ya funcionando.

**Google** (console.cloud.google.com):
1. Cree un proyecto. En *APIs y servicios → Pantalla de consentimiento de OAuth* elija *Externo*,
   ponga el nombre del servicio, su correo y publíquela.
2. *Credenciales → Crear credenciales → ID de cliente de OAuth → Aplicación web*.
3. En *URI de redireccionamiento autorizados* ponga
   `https://SU-DOMINIO/api/v1/auth/oauth/google/callback`.
4. Copie el *ID de cliente* y el *Secreto* al `.env`.

**Microsoft** (portal.azure.com → Microsoft Entra ID → Registros de aplicaciones):
1. *Nuevo registro*. Tipos de cuenta: *Cuentas de cualquier directorio organizativo y cuentas
   personales de Microsoft*.
2. URI de redirección (Web): `https://SU-DOMINIO/api/v1/auth/oauth/microsoft/callback`.
3. *Certificados y secretos → Nuevo secreto de cliente*. Copie el *Id. de aplicación (cliente)*
   y el *valor* del secreto al `.env`.

Reinicie el API. Sin estas credenciales los clientes igual se inscriben con su correo (esto
necesita el correo de salida, SMTP). Los administradores del servicio no entran con Google ni
Microsoft: usan contraseña y verificación en dos pasos.

La inscripción en línea se puede cerrar en *Ventas → Facturación y avisos* (casilla
*Permitir que nuevas empresas se inscriban solas*).

## 1. Cómo funciona el negocio

La plataforma es un **API de consumo**: otros sistemas (puntos de venta,
ERP, tiendas en línea, automatizaciones como n8n) se conectan para emitir
facturas electrónicas ante Hacienda. **Quien se conecta primero compra y
luego factura.**

Hay dos tipos de cliente y dos tarifas:

| Tipo de cliente | Qué paga | Por qué |
|---|---|---|
| **Solo API** (se conecta con su POS, ERP, tienda en línea o n8n) | **Solo documentos** | Usa únicamente el servicio de emitir ante Hacienda |
| **Sistema en línea** (factura desde el navegador) | Documentos **más** la mensualidad del **panel web** | Se le agrega un servicio más: pantallas para facturar, clientes, productos, inventario, punto de venta y reportes |

| Qué se vende | ¿A quién? | Cómo se cobra |
|---|---|---|
| **Paquete de documentos** | A todos | Por cantidad (p. ej. 500 documentos). Cada comprobante enviado a Hacienda descuenta 1 |
| **Panel web** (sistema en línea) | Solo a quien lo quiere | Mensualidad (1, 3, 6 o 12 meses) o regalía |

La **conexión por API no tiene mensualidad**: basta con que la empresa tenga
documentos y su casilla *Conexión por API* esté marcada.

### Qué necesita una empresa para poder facturar

| Requisito | Si falta, el cliente ve… | Dónde se resuelve |
|---|---|---|
| Empresa **activa** | No puede emitir ni entrar | Ficha de la empresa → **Datos** |
| **Certificado** (.p12) vigente | Error al firmar | Ficha → **Hacienda y certificado** |
| **Credenciales del API** de Hacienda | No se envía nada a Hacienda | Ficha → **Hacienda y certificado** |
| **Documentos** disponibles | Error `402`: "Saldo de documentos agotado" | Ficha → **Compras** → **+ Vender paquete** |
| Casilla **Conexión por API** marcada (si factura por API) | Error `403`: "el servicio de conexión por API no está activo" | Ficha → **Datos** |
| **Panel web** marcado y con mensualidad vigente (si factura en línea) | Pantalla "su empresa no tiene el panel web" | Ficha → **Datos** y Ficha → **Compras** → **Cobrar panel web** |

### Qué consume un documento

| Consume 1 documento | No consume |
|---|---|
| Factura, tiquete, nota de crédito, nota de débito, factura de compra, factura de exportación, recibo de pago | Reintentos y reenvíos del mismo comprobante |
| Cada respuesta a una factura de proveedor (aceptar, aceptar parcial o rechazar) | Consultas, PDF, XML, reportes |
| | Recibir o registrar facturas de proveedores (solo responderlas consume) |
| | Solicitudes con datos inválidos (no se firman) |

> Un comprobante que **Hacienda rechaza sí consume**: se firmó y se envió.

---

## 2. Configuración inicial (una sola vez)

Antes de vender al primer cliente, deje lista su propia plataforma.

### 2.1 Su propia empresa (la que factura las ventas)

Cada venta de documentos o del panel web le genera al cliente su **factura
electrónica**, emitida desde **su** empresa. Para eso:

1. **Empresas → Empresas cliente → + Nueva empresa** y registre **su propia
   empresa** como cualquier otra (ver sección 4).
2. Cárguele su certificado y sus credenciales de Hacienda (sección 5).
3. Véndale un paquete de documentos **a sí misma** con precio 0: sus propias
   facturas de venta también consumen documentos.

> **No confunda la empresa que factura con el correo.** La *empresa que
> emite* es la que aparece como vendedor en la factura ante Hacienda (con su
> cédula, certificado y credenciales). El **correo** desde donde salen todas
> las facturas y avisos es uno solo para toda la plataforma y lo configura el
> técnico en el servidor (SMTP, sección 2.4). Cada correo sale con el nombre
> de la empresa que factura y, si el cliente responde, la respuesta le llega
> al correo de esa empresa.

### 2.2 Facturación de ventas y avisos

**Ventas → Facturación y avisos**

| Campo | Qué poner |
|---|---|
| **Empresa que emite** | Su propia empresa (la del paso anterior) |
| **CABYS del servicio que vende** | Use **Buscar CABYS** (p. ej. servicios de software o de procesamiento de datos) |
| **IVA** | Normalmente tarifa general 13 % |
| **Los precios de los planes ya incluyen el IVA** | Márquelo si sus precios son finales (el sistema separa el IVA) |
| **Comprobante por defecto** | *Factura electrónica* (recomendado: sus clientes son empresas) |
| **Medio de pago por defecto** | El que más use (SINPE Móvil, transferencia…) |

**Avisos al cliente** (se agregan al correo que el sistema envía cuando a una
empresa le quedan pocos documentos, se le agotan o se le vence el panel web):

| Campo | Ejemplo |
|---|---|
| **Formas de pago** | `SINPE Móvil 8888-8888 a nombre de …` y su IBAN |
| **Contacto para comprar** | `WhatsApp 8888-8888 · ventas@suempresa.com` |
| **Su correo** | Recibe copia de cada aviso; las respuestas del cliente le llegan a usted |

Si deja **Empresa que emite** vacía, las ventas se registran igual pero
**no** generan factura, y el sistema se lo recuerda en **Contabilidad**.

**Venta en línea** (misma pantalla):

| Campo | Qué hace |
|---|---|
| **Permitir que nuevas empresas se inscriban solas** | Muestra «Pruébelo gratis» en la página de entrada. La persona pone la cédula de la empresa (debe estar inscrita en Hacienda), su correo y dirección; le llega un enlace para activar la cuenta. Requiere el correo de salida (SMTP). Apagado por defecto. |
| **Documentos gratis / Días gratis** | Lo que recibe cada empresa al activar su cuenta (por ejemplo 20 documentos y 15 días del sistema en línea), en ambiente de pruebas. |
| **Precio por mes del sistema en línea** | Si lo llena, el cliente puede comprar meses del sistema web él solo. Vacío = solo los vende usted. |

Los clientes compran los **planes activos con precio** desde *Mi saldo → Comprar
documentos*: pagan por SINPE Móvil o transferencia y le avisan con el número del
comprobante (y la foto, si quieren). Usted lo revisa en **Ventas → Pagos por
revisar** (le llega un correo a *Su correo*):

- **Ver comprobante**, confirme que el dinero está en su cuenta y toque **Aprobar**:
  se acreditan los documentos y/o los meses, se emite la factura de la venta y al
  cliente le llega un correo.
- **Rechazar** con el motivo (por ejemplo «no aparece el depósito»): al cliente le
  llega el motivo por correo.

### 2.3 Catálogo de planes

La plataforma ya trae siete planes creados (50, 100, 250, 500, 1 000, 2 500
y 5 000 documentos, con vigencia de un año), **inactivos y con precio 0**
para que nadie los venda por error. Para usarlos: **Ventas → Planes y ventas
→ Editar**, ponga el **precio**, marque **Plan activo** y guarde. La tabla
muestra el precio por documento que resulta.

Para crear otro: **Ventas → Planes y ventas → + Nuevo plan**

| Campo | Ejemplo |
|---|---|
| Nombre | "Paquete 500" |
| Documentos | 500 |
| Precio y moneda | 15 000 CRC |
| Vigencia (días) | 365 (vacío = no vence) |
| Descripción | Lo que verá usted al vender |
| Plan activo | Marcado para que aparezca al vender |

Los planes son atajos: también puede vender **cualquier cantidad** a un
precio negociado sin crear un plan.

### 2.4 Requisitos del servidor

Para que todo funcione en producción, el técnico debe haber configurado en
el `.env` (ver la guía de despliegue del técnico):

- **Correo (SMTP):** sin él no salen las facturas por correo ni los avisos de saldo.
  Se necesita el servidor y puerto (Gmail/Workspace: `smtp.gmail.com` 587;
  Microsoft 365: `smtp.office365.com` 587), el usuario, la contraseña (en
  Gmail, una *contraseña de aplicación*) y el correo remitente, idealmente de
  su propio dominio (p. ej. `facturas@sudominio.cr`) para no caer en spam.
- **Dominio con HTTPS** (`CALLBACK_BASE_URL`): Hacienda avisa ahí el resultado de cada comprobante.
- **Validación oficial de los XML** (`XSD_DIR=/app/xsd`): revisa cada comprobante contra los esquemas de Hacienda antes de enviarlo.
- **Respaldos** automáticos de la base de datos.

---

## 3. Qué pedirle a cada cliente

Pida los datos por un canal seguro (no por WhatsApp ni correo abierto). En el
sistema se guardan **cifrados** y nadie puede volver a verlos.

### 3.1 A todos los clientes

| Dato | Dónde lo obtiene el cliente | Para qué |
|---|---|---|
| Cédula (física o jurídica) | — | Identifica la empresa ante Hacienda |
| Nombre o razón social | Se llena solo al buscar la cédula | Aparece en las facturas |
| Correo para facturas | — | Copia de lo que emite y avisos de saldo |
| Provincia, cantón, distrito y dirección **tal como están en Hacienda** | ATV → Registro Único Tributario | Si no coinciden, Hacienda acepta pero advierte |
| Actividad económica | Se llena sola al buscar la cédula | Va en cada factura |
| **Certificado digital** (`.p12`) y su **PIN** de 4 dígitos | ATV → Comprobantes electrónicos → *Generar llave criptográfica* | Firmar cada comprobante |
| **Usuario y contraseña del API** de Hacienda | ATV → Comprobantes electrónicos → *Generar contraseña* | Enviar a Hacienda |
| Qué va a comprar | — | Cantidad de documentos y servicios |
| Comprobante del pago | SINPE o transferencia | Registrar la venta |

Hay **un juego para pruebas** y **otro para producción** (certificado y
credenciales). Se generan por separado en ATV. Pida primero el de **pruebas**.

- Usuario de pruebas: `cpj-3-101-123456@stag.comprobanteselectronicos.go.cr` (o `cpf-…` si es persona física)
- Usuario de producción: `cpj-3-101-123456@prod.comprobanteselectronicos.go.cr`

### 3.2 Además, si se conecta por API

| Dato | Para qué |
|---|---|
| Nombre de cada sistema o sucursal que se conectará (p. ej. "POS central") | Se crea una API key por cada uno |
| Correo o contacto de su programador | Para enviarle los datos de conexión y la **Manual de conexión por API** |
| URL de su webhook (opcional) | Para avisarle a su sistema cuando Hacienda acepta o rechaza |

### 3.3 Además, si quiere el sistema en línea (panel web)

| Dato | Para qué |
|---|---|
| Nombre y correo de cada persona que va a entrar | Crearle su usuario |
| Logo en PNG o JPEG (máximo 300 KB, opcional) | Sale en el PDF de cada factura |
| Correo donde recibe las facturas de sus proveedores, con una **contraseña de aplicación** (opcional) | Que esas facturas se carguen solas para aceptarlas o rechazarlas |
| Su lista de clientes y productos en Excel (opcional) | Se importan desde el panel |

---

## 4. Dar de alta la empresa

**Empresas → Empresas cliente → + Nueva empresa**

1. **¿Cómo va a facturar esta empresa?** Elija una de las dos tarjetas:
   - **Solo conexión por API:** factura desde su POS, ERP, tienda en línea o
     n8n. Paga solo los documentos.
   - **API + sistema web:** además entra al panel a facturar. Paga los
     documentos más la mensualidad del sistema web (o se lo regala).
1. **Tipo:** cédula jurídica (la mayoría), física, DIMEX o NITE.
2. **Identificación:** escriba la cédula **sin guiones**. Al completarla, el
   sistema consulta Hacienda solo (o presione **Buscar en Hacienda**) y llena:
   - el **nombre**;
   - la **actividad económica principal** (si tiene varias, puede elegir otra);
   - el estado: debe decir **INSCRITO**. Si dice *No inscrito*, la empresa
     no puede emitir hasta inscribirse en Hacienda.
3. **Ambiente de Hacienda:** **Pruebas (stag)** al inicio.
4. Complete **correo**, **provincia**, **cantón**, **distrito** y **otras señas**.
5. **Registrar ahora lo que compra** (viene marcado). Si el cliente ya pagó,
   registre la venta en el mismo paso:
   - **Documentos:** elija un plan, o **Otra cantidad: precio por documento** y
     escriba la **cantidad** y el **precio por documento**. El sistema calcula
     el monto (por ejemplo, 500 × ₡30 = ₡15 000).
   - **Sistema web** (solo si eligió *API + sistema web*): **período** y
     **precio mensual**, o **Regalía**. Calcula el monto (por ejemplo,
     3 meses × ₡5 000 = ₡15 000).
   - **Total a pagar:** la suma de las dos cosas (en el ejemplo, ₡30 000). Si
     usó monedas distintas, muestra cada una por aparte.
   - **Referencia del pago** y el **comprobante** que se le emite al cliente.

   Si todavía no ha pagado, desmarque la casilla y registre la venta después
   en **Compras**.
6. **Crear empresa**. Se abre la ficha de la empresa.

### La ficha de la empresa

Cada empresa tiene una ficha con estas pestañas:

| Pestaña | Qué hay |
|---|---|
| **Resumen** | *Estado para facturar* (alertas con su solución), saldo, conexión con Hacienda y servicios contratados |
| **Compras** | Historial de compras, **+ Vender paquete**, **Cobrar panel web**, factura de cada venta y anulaciones |
| **Documentos** | Últimos comprobantes emitidos y facturas de proveedores, con el motivo de cada rechazo |
| **Hacienda y certificado** | Certificado `.p12`, credenciales del API y **Probar conexión con Hacienda** |
| **Datos** | Datos de la empresa, ambiente, **interruptores de servicios** y logo |
| **Integración** | API keys y webhook |
| **Usuarios** | Usuarios del panel de esta empresa |

---

## 5. Conectarla con Hacienda

**Ficha de la empresa → Hacienda y certificado**

1. **Certificado digital (.p12):** seleccione el archivo, escriba el PIN y
   presione **Cargar certificado**. El sistema revisa:
   - que el PIN sea correcto;
   - que el certificado esté vigente;
   - que pertenezca a esa cédula (si no, muestra una advertencia).
2. **Credenciales del API de Hacienda:** usuario y contraseña → **Guardar credenciales**.
3. **Probar conexión con Hacienda:** debe responder que Hacienda y el certificado están bien.

| Resultado de la prueba | Causa | Qué hacer |
|---|---|---|
| Credenciales inválidas (`invalid_grant`) | Usuario o contraseña mal escritos, o son del otro ambiente (pruebas vs. producción) | Pedir de nuevo los datos; revisar el ambiente en **Datos** |
| Certificado vencido | Se venció en ATV | El cliente genera uno nuevo y usted lo carga |
| El certificado no corresponde a la cédula | Le enviaron el de otra empresa | Pedir el correcto |
| Error de conexión | Hacienda caído temporalmente | Reintentar más tarde |

Cada empresa tiene **sus propias** credenciales y certificado: nunca se
mezclan, y cada una puede estar en pruebas o en producción por separado.

---

## 6. Cobrarle: documentos y servicios

Todo se registra en **Ficha de la empresa → Compras**, **después** de
confirmar el pago (SINPE o transferencia).

### 6.1 Vender un paquete de documentos

**+ Vender paquete**

| Opción | Cuándo |
|---|---|
| **Un plan del catálogo** | La cantidad, el precio y la vigencia vienen del plan |
| **Otra cantidad: precio por documento** | Escriba la **Cantidad de documentos** y el **Precio por documento** (0 = cortesía), la **Moneda** y la **Vigencia (días)** (vacío = no vence). El sistema muestra *cantidad × precio = total* y cobra ese total |

- **Referencia del pago:** el número del comprobante SINPE o de la transferencia.
- **Comprobante:** puede cambiar el tipo (factura o tiquete), el medio de pago
  o no emitirlo, solo para esta venta.

El saldo se **suma** a lo que ya tenía. Se consume primero el paquete que
vence antes; los vencidos o anulados no cuentan.

### 6.2 Cobrar el panel web (solo clientes del sistema en línea)

**Cobrar panel web** (dice **Renovar panel web** si ya lo tiene). La conexión
por API **no** se cobra aquí: se paga solo con documentos.

| Campo | Qué poner |
|---|---|
| **Período** | 1, 3, 6 o 12 meses |
| **Precio mensual** | Lo que cobra por mes (0 = cortesía). El sistema muestra *meses × precio mensual = total* y cobra ese total |
| **Moneda** | CRC o USD |
| **Referencia del pago** | Comprobante SINPE o transferencia |
| **Regalía (sin costo y sin vencimiento)** | Márquela para regalar el servicio. Típico para el panel web como cortesía |

- Si el servicio todavía está pagado, el nuevo período **empieza cuando
  termina el actual**: el cliente no pierde días por renovar antes.
- Un pago después de una regalía empieza de inmediato.

### 6.3 La factura de cada venta

Si configuró la sección 2.2, cada venta con precio genera **sola** la
factura al cliente desde su empresa, y se envía a Hacienda.

En el historial de compras, la columna **Comprobante** muestra su estado:

| Estado | Qué hacer |
|---|---|
| Aceptado | Nada. Botón **PDF** para verlo |
| En proceso | Esperar unos minutos |
| Rechazado | Corrija la causa y presione **Sustituir comprobante** (en Contabilidad): se emite uno nuevo que reemplaza al rechazado |
| No se emitió / Sin comprobante | Botón **Emitir** o **Reintentar** (pase el mouse para ver el motivo) |
| Cortesía | Las ventas con precio 0 no se facturan |

Reintentar **nunca duplica** la factura de una venta.

### 6.4 Anular una venta

Use **Anular** en la fila de la compra cuando un pago se revierte.

- **Paquete:** se anulan los documentos que le quedaban; lo ya consumido se conserva.
- **Mensualidad:** ese período deja de contar.
- **La factura de esa venta NO se anula sola.** Si ya estaba aceptada por
  Hacienda, el sistema le avisa y la venta aparece en **Contabilidad →
  Ventas anuladas con comprobante vigente**. Anúlela con una nota de crédito
  desde su empresa (*Documentos emitidos → la factura → Anular con nota de crédito*).

---

## 7. Activar y desactivar servicios

- **Conexión por API:** solo depende de su casilla en **Ficha → Datos** (y de tener documentos).
- **Panel web:** necesita las dos cosas: la casilla en **Ficha → Datos** y la
  mensualidad vigente (o regalía) en **Ficha → Compras**.

### 7.1 Los interruptores (Ficha → Datos)

| Casilla | Marcada | Desmarcada |
|---|---|---|
| **Empresa activa** | Funciona normalmente | No puede emitir, sus llaves no funcionan y sus usuarios no entran. Use esto para suspender a un cliente |
| **Panel web para los usuarios de la empresa** | Sus usuarios entran al sistema en línea (si tiene el panel pagado o en regalía) | Sus usuarios ven "su empresa no tiene el panel web". **No afecta** su conexión por API |
| **Conexión por API** | Sus API keys funcionan (mientras tenga documentos) | Todas sus llaves responden `403`. **No afecta** el panel web |

Después de cambiar algo, presione **Guardar cambios**.

### 7.2 Estados del panel web (Ficha → Resumen → Servicios alquilados)

La conexión por API aparece como **Activo** con la nota *"Sin mensualidad: se
paga con documentos"*, o como **Deshabilitado** si su casilla está desmarcada.
El panel web puede estar en cualquiera de estos estados:

| Estado | Qué significa | ¿Funciona? |
|---|---|---|
| **Activo** | Pagado | Sí |
| **Por vencer** | Faltan 7 días o menos | Sí. El cliente recibe aviso |
| **Vencido (días de gracia)** | Venció hace menos de 3 días | Sí, por cortesía. Cobre la renovación |
| **Vencido** | Pasaron los días de gracia | **No** |
| **Sin contratar** | Nunca se cobró | **No** |
| **Deshabilitado** | La casilla en Datos está desmarcada | **No** |
| **Regalía (no vence)** | Regalado | Sí |

### 7.3 Combinaciones típicas

| Cliente | Empresa activa | Conexión por API | Panel web | Qué cobrar |
|---|---|---|---|---|
| Solo su sistema (POS, ERP, n8n) | ✔ | ✔ | ✘ | Solo documentos |
| Solo el sistema en línea | ✔ | ✘ | ✔ + mensualidad o regalía | Documentos + panel web |
| Las dos cosas | ✔ | ✔ | ✔ + mensualidad o regalía | Documentos + panel web |
| Cliente moroso que se suspende | ✘ | — | — | — |

Para **reactivar**, vuelva a marcar la casilla (y, si es el panel web, cobre el período pendiente).

---

## 8. Entregar al cliente que se conecta por API

1. Confirme en **Resumen** que no hay alertas rojas, que tiene documentos y que
   la **Conexión por API** está activa.
2. **Ficha → Integración → Nueva llave:** escriba un nombre por sistema o
   sucursal (p. ej. "POS tienda central") → **Crear API key**.
3. Aparece un bloque con **todo lo que necesita el programador**: URL base,
   API key y un ejemplo listo. Presione **Copiar datos de conexión** y
   envíeselo por un canal seguro junto con la **Manual de conexión por API**
   (si usa n8n, también la guía de n8n).
4. **La llave se muestra una sola vez.** Si se pierde, **Revocar** y cree otra.
5. Opcional, **Webhook:** escriba la URL del sistema del cliente → **Guardar
   webhook**. Entregue el **secreto** que aparece (también se muestra una sola
   vez); con él su sistema verifica que los avisos vienen de la plataforma.

La columna **Último uso** de cada llave le indica si el cliente realmente se
está conectando.

**Qué respuestas puede recibir el sistema del cliente:**

| Código | Significa | Quién lo resuelve |
|---|---|---|
| `202` | Comprobante recibido y en camino a Hacienda | — |
| `402` | Sin documentos | Usted: venderle un paquete |
| `403` | Conexión por API desmarcada o empresa suspendida | Usted: reactivar en **Datos** |
| `422` | Datos inválidos (el mensaje dice cuál) | El programador del cliente |
| `429` | Demasiadas solicitudes por minuto | Esperar y reintentar |

Las plantillas del mensaje de entrega están en el **Manual de conexión por API** (sección *Qué le entrega su proveedor*) y en el **Manual del cliente — Sistema en línea**.

---

## 9. Entregar al cliente que usa el sistema en línea

### 9.1 Lo que hace usted

1. **Ficha → Datos:** marque **Panel web para los usuarios de la empresa** → **Guardar cambios**.
2. **Ficha → Compras → Cobrar panel web:** registre el pago o marque **Regalía**.
3. Opcional, **Ficha → Datos → Logo en las facturas:** cargue el PNG o JPEG.
4. **Ficha → Usuarios → Nuevo usuario para esta empresa:** correo, nombre y
   contraseña inicial (mínimo 10 caracteres) → **Crear usuario**. Ese usuario
   **solo ve esta empresa**.
5. Envíele al cliente la dirección `https://<su-dominio>/panel/`, su correo y
   la contraseña inicial, y pídale cambiarla al entrar (*Configuración → Mi usuario*).

Para quitarle el acceso a una persona: **Ficha → Usuarios → Desactivar**.

### 9.2 Lo que ve y hace el cliente

El cliente entra y ve el menú superior:

| Menú | Opciones |
|---|---|
| **Facturar** | *Vender:* Factura rápida, Factura electrónica, Tiquete, Punto de venta. *Corregir una factura ya enviada:* Nota de crédito, Nota de débito. *Otros:* Proforma o cotización, Factura de compra, Factura de exportación |
| **Documentos** | *Lo que vendí:* Documentos emitidos, Facturas sin enviar, Proformas, Cierres de caja. *Lo que compré:* Facturas de proveedores. *Cobros:* Facturas por cobrar, Recibos de pago. *Respaldo:* Descargar XML y PDF |
| **Clientes y productos** | Clientes, productos, inventario, categorías, descuentos, combos e importación desde Excel |
| **Reportes** | Ventas por cliente y por producto, Consultas a Hacienda (el IVA y la D-104 los ve solo el contador) |
| **Configuración** | Datos de la empresa, actividad económica, **Saldo de documentos**, Mi usuario |

Puntos que conviene explicarle:

- **Facturar** va en 3 pasos: *¿A quién le factura?* (escribe la cédula y los
  datos se llenan solos), *¿Qué vende?* y *¿Cómo le pagan?*. Con solo la
  cédula se factura; si el cliente no quiere su nombre, sale "Consumidor final".
- **Anular una factura:** *Documentos emitidos → la factura → Anular con nota
  de crédito*, eligiendo **Anulación normal** (devolución, acuerdo) o **Error
  material** (cliente equivocado, duplicada). El error material afecta el IVA
  del mes de la factura original y el **Reporte de IVA** le avisa qué mes rectificar.
- **Facturas de proveedores:** con **Conectar correo** (correo, contraseña de
  aplicación y servidor IMAP) las facturas que le llegan por correo se cargan
  solas. Él solo presiona **Aceptar** o **Rechazar** con un comentario.
- **Saldo de documentos:** ve cuántos le quedan. Recibe un correo cuando quedan
  pocos, con sus formas de pago y contacto (sección 2.2).

Guía completa para el cliente: **Manual del cliente — Sistema en línea**.

---

## 10. Pasar de pruebas a producción

1. En **Pruebas**, emita una factura (desde el panel, o que el cliente la emita
   desde su sistema) y verifique en **Ficha → Documentos** que quede **Aceptada**.
2. Pida al cliente el **certificado y las credenciales de producción**.
3. **Ficha → Hacienda y certificado:** cargue el certificado nuevo y las credenciales nuevas.
4. **Ficha → Datos:** cambie **Ambiente de Hacienda** a **Producción** → **Guardar cambios**.
5. **Probar conexión con Hacienda** y emita la primera factura real.

Las API keys, el webhook y los usuarios **no cambian**: el sistema del cliente
sigue funcionando igual.

---

## 10.1 Usuarios de cada empresa

El dueño de cada empresa maneja sus propios usuarios en *Configuración → Usuarios*
con tres roles: **Dueño** (todo), **Administrativo** (facturas, anulaciones, cobros y
proveedores) y **Cajero** (vender y cobrar). Usted, como administrador, puede seguir
creando usuarios en *Empresas → Usuarios*. Los contadores se manejan aparte (10.2).

Los dueños también pueden subir la llave criptográfica y el usuario de Hacienda
ellos mismos en *Configuración → Primeros pasos*.

## 10.2 Contadores (módulo de contabilidad)

La contabilidad es un módulo que ven **solo el dueño de cada empresa** (la de él) y los
**usuarios contadores** (las que llevan). Usted como administrador no entra a él, ni los
demás usuarios de las empresas.

1. **Empresas → Usuarios → + Nuevo usuario**, en *Acceso* elija **Contador**.
2. El contador entra y **escoge él mismo** sus empresas: busca por cédula las que ya
   facturan aquí (a la empresa le llega un aviso y su dueño puede quitarle el acceso en
   *Usuarios → Contadores con acceso*) o inscribe las que no facturan aquí y carga sus XML.
3. El contador solo ve su módulo: no puede facturar, ni ver saldos, usuarios o configuración
   de las empresas.

Las empresas que un contador inscribe él mismo no aparecen en su lista de Empresas ni
consumen documentos.

## 11. Revisión diaria: que todo vaya bien

### 11.1 Inicio (tablero del administrador)

Lo primero que ve al entrar:

| Sección | Qué revisar |
|---|---|
| **Ventas por mes** | Cómo van los ingresos (6 meses) |
| **Por vencer o renovar** | Paquetes, certificados y mensualidades que vencen en los próximos días, y empresas con poco saldo: **son ventas por hacer** |
| **Empresas con problemas para facturar** | Errores y alertas de cada empresa, con enlace a la solución |
| **Últimas ventas** | Lo último que registró y el estado de su factura |
| **Mejores clientes (12 meses)** | Quién compra más |

### 11.2 Empresas cliente (lista)

Filtro **Con problemas** para ver solo las que necesitan atención. La columna
**Documentos** se pinta en verde (bien), amarillo (quedan 20 o menos) o rojo (sin saldo).

### 11.3 Alertas de cada empresa (Ficha → Resumen → Estado para facturar)

Cada alerta trae **Ver y resolver →**, que lleva a la pestaña donde se arregla.

| Alerta | Gravedad | Qué hacer |
|---|---|---|
| Sin certificado digital | Error | Cargar el `.p12` y su PIN |
| Certificado vencido | Error | El cliente genera uno nuevo en ATV; cargarlo |
| Certificado por vencer | Alerta (30 días antes) | Pedir la renovación con tiempo |
| Sin credenciales del API de Hacienda | Error | Cargar usuario y contraseña de ATV |
| Sin documentos | Error | Venderle un paquete |
| Quedan N documentos | Alerta (20 o menos) | Ofrecerle otro paquete |
| N documentos por vencer | Alerta | Avisarle que los use o renueve |
| Panel web **vencido** | Error | Cobrar la renovación; mientras tanto sus usuarios no entran |
| … en días de gracia | Alerta | Cobrar antes de que se suspenda (3 días) |
| … por vencer | Info | Recordarle la renovación |
| N comprobantes rechazados por Hacienda | Error | Ver el motivo en **Documentos** (ver anexo de rechazos) |
| N comprobantes sin confirmar por Hacienda | Alerta | Suele ser Hacienda lento o caído; se reintenta solo cada 5 minutos |
| Respuestas a proveedores rechazadas | Alerta | Revisar en las facturas de proveedores del cliente |
| No se puede leer el correo de facturas | Alerta | La contraseña de aplicación del correo cambió; el cliente la vuelve a conectar |
| En ambiente de pruebas | Info | Recordatorio: pasar a producción cuando esté listo |
| Empresa inactiva | Info | Está suspendida a propósito |

### 11.4 Avisos automáticos

El sistema avisa solo, por correo al cliente con copia a usted:

- cuando quedan **20 documentos o menos** y cuando se agotan;
- cuando un paquete de documentos está por vencer;
- cuando la mensualidad del panel web está por vencer (7 días antes) o vence;
- cuando un certificado está por vencer (30 días antes).

Los avisos incluyen sus **formas de pago** y su **contacto** (sección 2.2):
son su principal herramienta de venta.

### 11.5 Bitácora

**Sistema → Bitácora:** quién creó empresas o llaves, cambió certificados o
credenciales, vendió o anuló paquetes y servicios, y cada inicio de sesión
con su IP. Úsela si algo cambió y no sabe quién lo hizo.

---

## 12. Cierre de cada mes

**Ventas → Contabilidad** (elija el mes)

1. **Ventas con comprobante aceptado:** deben ser todas. Revise las que
   digan *sin comprobante*, *en proceso* o *rechazado* y resuélvalas (sección 6.3).
2. **Ventas anuladas con comprobante vigente:** a cada una hágale su nota de
   crédito, o seguirá sumando en su declaración de IVA.
3. **Para el contador:** descargue el **Libro de ventas**, el **Libro de
   compras** y los **Comprobantes del mes (ZIP)** de su empresa, y envíeselos
   junto con el IVA estimado.

> Notas de crédito por **error material** (códigos 13 y 14): desde noviembre
> de 2026 su efecto va al mes de la factura original. El Reporte de IVA indica
> qué meses hay que **rectificar**.

---

## 13. Situaciones frecuentes

| Situación | Qué hacer |
|---|---|
| El cliente se quedó sin documentos | **Compras → + Vender paquete** tras confirmar el pago. Factura de inmediato, no hay que reiniciar nada |
| El pago de una venta se revirtió | **Compras → Anular** y luego la nota de crédito de su factura (sección 6.4) |
| El cliente quiere probar antes de comprar | Véndale un paquete pequeño con precio 0 (cortesía) en ambiente de **Pruebas** |
| Quiere regalarle el panel web | **Datos:** marque Panel web → **Compras → Cobrar panel web → Regalía** |
| Ya no quiere el panel web | **Datos:** desmarque Panel web. Sigue facturando por API |
| No pagó la mensualidad del panel web | Al vencer y pasar 3 días de gracia, sus usuarios dejan de entrar al panel (su API sigue funcionando). Al pagar, **Renovar panel web** |
| Un cliente de API quiere pasarse al sistema en línea | **Datos:** marque Panel web → **Compras → Cobrar panel web** → **Usuarios:** créele sus usuarios |
| Suspender a un cliente por completo | **Datos:** desmarque **Empresa activa** |
| El programador perdió la API key | **Integración:** **Revocar** la vieja y **Crear API key** nueva |
| Se filtró una API key | Revóquela de inmediato y cree otra |
| El cliente renovó su certificado | **Hacienda y certificado:** cargue el nuevo `.p12` con su PIN |
| El cliente cambió la contraseña del API en ATV | Cárguela de nuevo en **Credenciales del API** y pruebe la conexión |
| Hacienda rechazó un comprobante | **Documentos:** lea el motivo (anexo 14.3), corrija y emita de nuevo |
| Comprobantes atascados "sin confirmar" | Normalmente Hacienda caído; se reintentan solos cada 5 minutos |
| Un usuario del panel olvidó su contraseña | **Empresas → Usuarios → Cambiar contraseña** |
| Un usuario perdió el teléfono de la verificación en dos pasos | **Empresas → Usuarios → Reiniciar 2 pasos** |
| La factura de una venta salió rechazada | Corrija la causa (CABYS, datos del cliente) y **Contabilidad → Sustituir comprobante** |

---

## 14. Anexos

### 14.1 Verificación en dos pasos

En producción todo administrador debe activarla la primera vez que entra
(*Sistema → Mi usuario*: escanear el QR con Google Authenticator, Microsoft
Authenticator o Authy). Desde entonces cada ingreso pide el código de 6 dígitos.

- **Un usuario perdió el teléfono:** *Empresas → Usuarios → Reiniciar 2 pasos*.
  Se cierran sus sesiones y la configura de nuevo al entrar.
- **Usted perdió el suyo:** pida a otro administrador que lo reinicie o, en el servidor:
  `docker compose exec api python -m api.cli reiniciar-2fa --email usted@correo.cr`
  (queda en la bitácora). Conviene tener **dos** administradores.
- Los usuarios de las empresas pueden activarla de forma opcional.

### 14.2 Datos de Hacienda guardados

Lo que se consulta a Hacienda (cédulas, exoneraciones, productores MAG/INCOPESCA,
CABYS y tipo de cambio) se guarda en el sistema y solo se vuelve a preguntar
cuando tiene más de `DIAS_ACTUALIZAR_HACIENDA` días (15 por defecto). Una tarea
diaria lo actualiza sola. Si Hacienda está caída, el sistema sigue con lo guardado
y lo indica: *"Hacienda no responde: se muestran los datos guardados el …"*.

- Cada empresa solo ve las **exoneraciones** que ella misma usó con un cliente;
  usted, como administrador, ve todas las conocidas.
- **Catálogo CABYS:** el oficial completo del BCCR (~20 500 códigos) se guarda en
  el sistema y se actualiza solo cada día a las 3:00 a. m. Cada actualización
  queda en la Bitácora (filtro *Catálogo CABYS*). Importación manual, solo si el
  BCCR cambiara la forma de publicarlo:
  `docker compose run --rm api python -m api.cli cargar-cabys --url https://.../catalogo.xlsx`
- **Tipo de cambio:** se guarda cada día; las facturas en contingencia usan el de su fecha.
- Forzar una actualización: `docker compose run --rm api python -m api.cli actualizar-hacienda`

### 14.3 Rechazos de Hacienda más comunes

| Mensaje de Hacienda | Solución |
|---|---|
| Código CABYS no existe | Corregir el código (el sistema lo valida antes de enviar) |
| Provincia/cantón/distrito no concuerdan (`-37`) | Actualizar la ubicación en **Datos** con la registrada en Hacienda |
| Emisor no inscrito | La empresa no está inscrita en Hacienda; debe inscribirse en ATV |
| Envío extemporáneo (`-16`) | Comprobante en contingencia enviado tarde; se acepta, solo informa |
| Código de referencia inválido | Revisar el motivo de la nota (códigos vigentes desde noviembre 2026 en el **Manual de conexión por API**) |
| La nota de crédito supera el comprobante | La suma de notas de crédito no puede pasar el total de la factura más sus notas de débito |

### 14.4 Valores configurables

Los valores de este manual son los predeterminados y se ajustan en el `.env`:

| Variable | Valor | Qué controla |
|---|---|---|
| `SALDO_ALERTA_DOCUMENTOS` | 20 | Cuándo avisar que quedan pocos documentos |
| `DIAS_ALERTA_SUSCRIPCION` | 7 | Cuándo avisar que vence la mensualidad del panel web |
| `DIAS_GRACIA_SUSCRIPCION` | 3 | Días que el panel web sigue funcionando después de vencer |
| `DIAS_ALERTA_CERTIFICADO` | 30 | Cuándo avisar que vence un certificado |
| `CONTROL_SALDO` | true | `false` desactiva el cobro por documentos (solo para uso interno) |
| `CONTROL_SUSCRIPCIONES` | true | `false` desactiva el cobro de la mensualidad del panel web |
