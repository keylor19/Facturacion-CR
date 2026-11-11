# Manual del cliente — Sistema en línea

Guía para las personas que facturan desde el navegador: cómo entrar, emitir
facturas y tiquetes, corregir una factura, responder las facturas de sus
proveedores, llevar clientes, productos e inventario, y sacar los reportes
para el contador.

No necesita instalar nada: solo una computadora, tableta o celular con
internet y un navegador actualizado (Chrome, Edge, Firefox o Safari).

---

## 1. Antes de empezar

Su proveedor le entrega:

| Dato | Ejemplo |
|---|---|
| **Dirección del sistema** | `https://<su-proveedor>/panel/` |
| **Usuario** | Su correo, p. ej. `ventas@miempresa.cr` |
| **Contraseña inicial** | Se la envían por un canal seguro. Cámbiela la primera vez que entre |

Su empresa ya queda lista por parte del proveedor: registrada en Hacienda,
con su certificado digital, sus credenciales y su paquete de documentos.
Usted solo factura.

### Qué es un "documento"

Usted compra un **paquete de documentos** (por ejemplo, 500). Cada
comprobante que se envía a Hacienda gasta uno:

| Gasta 1 documento | No gasta |
|---|---|
| Factura, tiquete, nota de crédito, nota de débito, factura de compra, factura de exportación y recibo de pago | Ver, imprimir o reenviar un comprobante |
| Cada respuesta (aceptar o rechazar) a una factura de un proveedor | Reportes, consultas a Hacienda y descargas |
| | Proformas y facturas guardadas sin enviar |

Un comprobante que Hacienda **rechaza también gasta** su documento, porque
sí se firmó y se envió. Revise bien los datos antes de enviar.

---

## 2. Crear su cuenta y entrar

**La primera vez** toque **Créela gratis** en la página de entrada:

1. Elija **Voy a facturar** y acepte los términos.
2. Toque **Continuar con Google** o **Continuar con Microsoft**, o escriba su nombre, correo y una
   contraseña (le llega un correo con el enlace para activar la cuenta).
3. **Inscriba su empresa:** escriba la cédula y toque **Buscar en Hacienda** (se llenan el nombre y
   sus actividades). Complete el nombre comercial, el correo, el teléfono y la dirección y toque
   **Inscribir mi empresa**. La empresa debe estar inscrita en Hacienda.
4. Queda como **dueño**, con documentos y días del sistema en línea de prueba. Siga los
   **Primeros pasos** (sección 4).

**Las siguientes veces**:

1. Abra la dirección del servicio.
2. Toque **Continuar con Google / Microsoft**, o escriba su **correo** y su **contraseña** y presione **Ingresar**.
3. Si activó la verificación en dos pasos, escriba el código de 6 dígitos
   que muestra la aplicación de su teléfono.

### Cambiar la contraseña

Menú con su nombre (arriba a la derecha) → **Mi usuario** → **Cambiar
contraseña**. Escriba la actual y la nueva dos veces (mínimo 10 caracteres).
Al cambiarla se cierran las demás sesiones abiertas y debe ingresar de nuevo.

### Verificación en dos pasos (recomendada)

Protege su cuenta aunque alguien conozca su contraseña.

1. **Mi usuario → Activar verificación en dos pasos**.
2. Escanee el código QR con Google Authenticator, Microsoft Authenticator o Authy.
3. Escriba el código de 6 dígitos que muestra la aplicación → **Activar**.

Desde ese momento, cada ingreso pide el código. Si pierde el teléfono, pida
a su proveedor que la reinicie.

### Salir

Botón **Salir**, arriba a la derecha. Hágalo siempre en computadoras compartidas.

---

## 3. La pantalla principal

Arriba está el **menú**. En el celular se abre con el botón de tres rayas.

| Menú | Para qué |
|---|---|
| **Inicio** (casita) | Resumen: comprobantes por estado, por tipo y los últimos emitidos |
| **Facturar** | Hacer facturas, tiquetes, notas de crédito y débito, proformas, punto de venta |
| **Documentos** | Ver lo que vendió y lo que compró, cobros y descargas |
| **Clientes y productos** | Sus clientes, productos, inventario, descuentos y combos |
| **Reportes** | Reporte de IVA, libros para el contador y consultas a Hacienda |
| **Configuración** | Datos de su empresa, actividad económica y saldo de documentos |

Arriba también se ve cuántos **documentos** le quedan. Si se pone amarillo
o rojo, le quedan pocos: contacte a su proveedor para comprar más.

---

## 4. Primeros pasos (una sola vez)

*Configuración → Primeros pasos* le muestra una lista con lo que falta y se marca sola
(también le muestra **Agregar usuarios** para quienes facturan con usted y **Comprar documentos**):

- **Llave criptográfica (.p12) y su PIN**, y **usuario y contraseña de Hacienda**.
  Se sacan en TRIBU-CR, en *Comprobantes electrónicos → Generar llave criptográfica*.
  Súbalos ahí mismo (solo el dueño) y toque **Probar conexión con Hacienda**.
- Datos de la empresa, logo, productos y la primera factura.

Si se inscribió solo desde la página de entrada (**Pruébelo gratis**), empieza con
documentos y días del sistema en línea de regalo, en el ambiente de pruebas.

Además:

1. **Revise los datos de su empresa:** *Configuración → Datos de la empresa*.
   Debe decir que el certificado está **Cargado** y mostrar el ambiente
   (**Pruebas** al inicio, **Producción** cuando ya factura de verdad).
2. **Revise su actividad económica:** *Configuración → Actividad económica*.
   Se usa en cada factura. Si tiene varias inscritas, elija con **Cambiar actividad**.
3. **Registre sus productos:** *Clientes y productos → Mis productos* (sección 9).
   No es obligatorio, pero facturar es mucho más rápido.
4. **Registre sus clientes frecuentes:** *Clientes y productos → Mis clientes*.
   También se guardan solos al facturar.

> **Mientras esté en Pruebas**, las facturas van al ambiente de pruebas de
> Hacienda y **no tienen validez fiscal**. Su proveedor le avisa cuando pasa
> a Producción. No tiene que cambiar nada de su lado.

---

## 5. Facturar

### 5.1 ¿Qué documento uso?

| Situación | Documento | Dónde |
|---|---|---|
| Venta de contado, rápida, en mostrador | **Factura rápida** | *Facturar → Factura rápida* |
| El cliente da su cédula, compra a crédito o tiene exoneración | **Factura electrónica** | *Facturar → Factura electrónica* |
| Cliente que no da cédula (consumidor final) | **Tiquete electrónico** | *Facturar → Tiquete electrónico* |
| Tienda o restaurante con caja y cierre diario | **Punto de venta** | *Facturar → Punto de venta* |
| Cotización que todavía no es venta | **Proforma** | *Facturar → Proforma o cotización* |
| Anular o rebajar una factura ya enviada | **Nota de crédito** | *Facturar → Nota de crédito* |
| Cobrar algo más de una factura ya enviada | **Nota de débito** | *Facturar → Nota de débito* |
| Compra a alguien que no factura (p. ej. un agricultor) | **Factura de compra** | *Facturar → Factura de compra* |
| Venta a un cliente en el extranjero | **Factura de exportación** | *Facturar → Factura de exportación* |

### 5.2 Factura rápida

Para la venta de todos los días, en pocos pasos:

1. *Facturar → Factura rápida*.
2. **Producto:** escriba o escanee el código, la descripción o el CABYS y
   elíjalo. Ajuste la **cantidad**. Repita para cada producto.
3. **Cliente** (opcional):
   - Sin cliente se emite un **tiquete** (consumidor final).
   - Con **Elegir de mis clientes (factura)** se emite una **factura** a su nombre.
4. **Pago:** elija el medio de pago. En efectivo, escriba el **monto
   recibido** y el sistema le muestra el **vuelto**.
5. **Emitir**. Luego puede **Ver comprobante e imprimir PDF**.

Si necesita algo que no está aquí (crédito, exoneración, varias formas de
pago), use **Formulario completo**.

### 5.3 Factura electrónica (formulario completo)

*Facturar → Factura electrónica*. El formulario tiene 3 pasos.

**Paso 1. ¿A quién le factura?**

- Escriba la **cédula** del cliente **sin guiones**. El sistema consulta
  Hacienda y llena solo el **nombre** y la **actividad económica**.
- O use **Elegir de mis clientes** para traer uno que ya tiene guardado.
- **Correo:** si lo escribe, al cliente le llegan el PDF y el XML cuando
  Hacienda acepte la factura. Si no lo escribe, la factura se emite igual.
- **Sin nombre:** si el cliente no quiere dar su nombre, déjelo vacío y la
  factura sale a nombre de **"Consumidor final"**.
- **¿El cliente tiene exoneración de impuestos?** Escriba el número de
  autorización (p. ej. `AL-00000000-24`). El sistema lo consulta en Hacienda
  y aplica la exoneración a los productos que cubre. Si ya le facturó antes
  con una exoneración, el sistema se la sugiere al escribir la cédula.
- **Guardar en mis clientes frecuentes:** márquelo para no volver a escribirlo.

**Paso 2. ¿Qué vende?**

- **+ Agregar de mis productos:** busca en su catálogo (código, descripción o CABYS).
- **+ Escribir otra línea:** para algo que no está en el catálogo. Debe
  indicar la **descripción**, el **código CABYS** (use **Buscar CABYS**), la
  **cantidad**, el **precio** y el **IVA**.
- En cada línea puede poner un **descuento**. En *Código comercial,
  exoneración de la línea, IVA especial…* están las opciones menos comunes.
- **Cobrar 10 % de servicio:** para restaurantes.

**Paso 3. ¿Cómo le pagan?**

- **Condición de venta:** contado o crédito (con el plazo en días).
- **Forma de pago:** efectivo, tarjeta, transferencia, SINPE Móvil…
- **+ Pagó con dos o más formas:** si pagó una parte en efectivo y otra con tarjeta.
- El **Resumen** muestra subtotal, descuentos, IVA y total.

**Al final, elija:**

| Botón | Qué hace |
|---|---|
| **Firmar y enviar a Hacienda** | Emite la factura. Gasta 1 documento |
| **Guardar como preliminar** | La guarda sin enviar, para terminarla luego (*Documentos → Facturas sin enviar*) |
| **Guardar como proforma** | La guarda como cotización (sección 5.6) |

### 5.4 Tiquete electrónico

Para el consumidor final. Puede dejar al cliente vacío (sale «Consumidor final»)
o escribir **solo su nombre**, sin cédula. Si el cliente pide factura a su nombre
para deducir el gasto, use factura electrónica con su cédula.

### 5.4.1 Facturas que se repiten (alquileres, mensualidades)

Llene la factura una vez y toque **Repetir automáticamente**: póngale un nombre,
la frecuencia (cada semana, 15 días, mes o año), la primera fecha y, si quiere,
la última. El sistema la emite sola a las 7:00 a. m. de cada fecha y al cliente le
llega por correo. Las ve en *Facturar → Facturas recurrentes*: ahí puede pausarlas,
emitir una hoy o borrarlas.

Es igual a la factura, pero el cliente es opcional. Úselo cuando la persona
no da su cédula. Hacienda no le permite al cliente usar un tiquete como gasto
deducible: si lo pide para su empresa, hágale **factura**.

### 5.5 Punto de venta (caja)

Para negocios con caja y cierre de turno:

1. *Facturar → Punto de venta*. Elija la caja o abra una.
2. **Abrir caja:** escriba el **fondo de caja** (el efectivo con que empieza).
3. Venda como en la factura rápida. Cada venta queda en el turno.
4. **Entrada de efectivo / Salida de efectivo:** registre el efectivo que
   entra o sale sin ser venta (p. ej. *Pago a proveedor de hielo*).
5. **Cerrar caja:** cuente el efectivo y escríbalo en **Efectivo contado**.
   El sistema compara con el **efectivo esperado** y le muestra si hay
   **sobrante** o **faltante**. Puede **Imprimir** el cierre.

Los cierres anteriores están en *Documentos → Cierres de caja*.

### 5.6 Proformas o cotizaciones

1. *Facturar → Proforma o cotización*. Llénela como una factura y presione
   **Guardar como proforma**. **No** va a Hacienda ni gasta documentos.
2. Puede imprimirla o enviarla al cliente.
3. Cuando el cliente confirme: *Documentos → Proformas*, ábrala y presione
   **Convertir en comprobante y enviar**.

### 5.7 Factura de compra y de exportación

- **Factura de compra:** cuando le compra a alguien que no está obligado a
  facturar (p. ej. un productor agropecuario). Usted la emite a nombre del
  **proveedor**.
- **Factura de exportación:** venta a un cliente fuera de Costa Rica. Se
  llena con los datos del cliente extranjero.

---

## 6. Después de facturar

### 6.1 Estados de un comprobante

*Documentos → Documentos emitidos* muestra cada comprobante con su estado:

| Estado | Qué significa | Qué hacer |
|---|---|---|
| **Pendiente** | Se firmó y va camino a Hacienda | Esperar unos segundos |
| **Enviado** | Hacienda lo recibió y lo está revisando | Esperar |
| **Aceptado** | Hacienda lo aprobó. Ya es válido | Nada. Al cliente le llega por correo |
| **Rechazado** | Hacienda encontró un error | Abrirlo, leer el **Mensaje de Hacienda**, corregir y emitir de nuevo |
| **Error de comunicación** | Hacienda no respondió | Nada: el sistema reintenta solo |
| **Contingencia** | Se emitió para respaldar una venta hecha sin sistema | Nada |

### 6.2 Qué puede hacer con un comprobante

Toque el comprobante en la lista para abrirlo:

- **PDF:** para imprimir o enviarlo en hoja carta.
- **Imprimir tiquete:** en rollo de impresora térmica de **80 mm** o **58 mm** (elija el ancho una vez; el navegador lo recuerda).
- **Enviar por WhatsApp:** escriba el celular del cliente y se abre WhatsApp con un mensaje y un enlace para que
  descargue su factura sin usuario. También puede **copiar el enlace** y pegarlo en cualquier chat.
- **Enviar por correo:** lo reenvía al cliente (o a otro correo).
- **Consultar estado:** pregunta de nuevo a Hacienda.
- **Anular con nota de crédito:** sección 7.
- **Emitir recibo de pago:** en ventas a crédito al Estado o con IVA a 90 días (sección 8).
- **Bitácora:** el historial del comprobante.

---

## 7. Corregir una factura ya enviada

Una factura **aceptada no se borra ni se edita**: se corrige con una nota.

### 7.1 Anular una factura completa

1. *Documentos → Documentos emitidos* → abra la factura.
2. **Anular con nota de crédito**.
3. Elija el motivo:

| Motivo | Cuándo | En qué mes cuenta para el IVA |
|---|---|---|
| **Anulación normal** | Devolución, acuerdo con el cliente, la venta no se concretó | El mes de la nota |
| **Error material** | La hizo al cliente equivocado, la duplicó o la hizo mal | **El mes de la factura original** |

4. Escriba la razón y confirme. Se emite la nota de crédito (gasta 1 documento).

> Si anula por **error material** una factura de un mes que ya declaró, el
> **Reporte de IVA** le avisa qué mes hay que **rectificar** ante Hacienda.

Después de anular por error, emita la factura correcta normalmente.

### 7.2 Rebajar una parte o devolver mercadería

*Facturar → Nota de crédito*:

1. **¿Qué documento?** Indique la factura que corrige (su clave de 50
   caracteres, o elíjala de la lista).
2. **¿Qué se hace?** Elija el motivo: devolución de mercadería, corrige
   monto, error material, etc. Cada motivo trae una explicación de su efecto.
3. Agregue solo lo que se devuelve o el monto que se rebaja.
4. **Firmar y enviar a Hacienda**.

Las notas de crédito de una factura **no pueden sumar más** que la factura
(más sus notas de débito): el sistema no lo permite.

### 7.3 Cobrar algo adicional

*Facturar → Nota de débito*, indicando la factura original y lo que se
agrega (por ejemplo, un cargo que se olvidó).

### 7.4 Si Hacienda rechazó la factura

Una factura **rechazada no tiene validez**, así que no hay que anularla:

1. Abra la factura y lea el **Mensaje de Hacienda**.
2. Corrija la causa (por lo general el código CABYS, la cédula o la ubicación del cliente).
3. Emita una factura nueva con los datos correctos.

---

## 8. Ventas a crédito y cobros

*Documentos → Cuentas por cobrar*

- Arriba ve cuánto le deben, cuánto está **vencido** y la **antigüedad**:
  al día, 1 a 30, 31 a 60, 61 a 90 y más de 90 días.
- **Por cliente:** toque un cliente para ver su **estado de cuenta** (facturas,
  pagos y saldo) e **imprimirlo o guardarlo en PDF** para mandárselo.
- **Registrar pago:** en cada factura pendiente.
  - **Crédito comercial (condición 02):** se anota el abono (monto, fecha,
    SINPE, transferencia…). Hacienda no pide comprobante para estos cobros y
    no gasta documentos. Si se equivocó, el dueño puede anular el abono.
  - **Crédito al Estado e IVA hasta 90 días:** el sistema emite el **Recibo
    Electrónico de Pago** ante Hacienda con el IVA de ese pago (gasta 1 documento).
- **Recordatorios automáticos:** active la casilla y el sistema le escribe al
  cliente a los 1, 8, 15, 30 y 60 días de atraso. Las respuestas le llegan a su correo.
- Si anula una factura a crédito con nota de crédito, su saldo queda en cero.

Los recibos emitidos están en *Documentos → Recibos de pago*.

---

## 9. Facturas de sus proveedores

Hacienda exige **aceptar o rechazar** las facturas electrónicas que le
hacen sus proveedores. Así el IVA que pagó cuenta como **crédito fiscal**.

### 9.1 Recibirlas solas desde su correo (recomendado)

1. *Documentos → Facturas de proveedores → Conectar correo*.
2. Escriba el correo donde sus proveedores le envían las facturas, la
   **contraseña de aplicación** de ese correo y el **servidor IMAP**:
   - Gmail: `imap.gmail.com`. La contraseña de aplicación se genera en su
     cuenta de Google → Seguridad → Contraseñas de aplicaciones (necesita la
     verificación en dos pasos de Google activada).
   - Outlook / Microsoft 365: `outlook.office365.com`.
3. **Conectar**. La primera vez trae las facturas de los últimos 30 días.
   Después revisa el correo **cada 5 minutos**.

### 9.2 Responderlas

Las facturas nuevas aparecen en **Solo por responder**. Abra cada una y elija:

| Respuesta | Cuándo |
|---|---|
| **Aceptar** | Todo está bien |
| **Aceptación parcial** | Acepta solo una parte (indique el motivo) |
| **Rechazar** | No corresponde, el monto está mal, no lo pidió… El motivo es obligatorio y lo ve el proveedor |

En **Condición del IVA** indique si el IVA es acreditable, un gasto
aplicable, etc. Por defecto se usa la opción más común. Cada respuesta gasta 1 documento.

Si el sistema avisa **Firma no válida**, el XML pudo ser alterado:
considere rechazarlo.

### 9.3 Cargar una factura a mano

Si una factura no llegó al correo conectado, súbala con el archivo XML que
le envió el proveedor (*Para facturas que no llegaron al correo conectado*).

---

## 10. Clientes, productos e inventario

### 10.1 Clientes

*Clientes y productos → Mis clientes → + Nuevo cliente*

- Escriba la identificación y presione **Buscar en Hacienda**: el nombre y
  la actividad se llenan solos.
- El **correo** es donde le llegan las facturas.
- **Importar clientes:** cargue muchos a la vez desde Excel guardado como
  CSV. Descargue primero la plantilla. Los que ya existen se reportan y no se modifican.

### 10.2 Productos y servicios

*Clientes y productos → Mis productos → + Nuevo producto*

| Campo | Qué poner |
|---|---|
| **Código** | Su código interno (p. ej. `MART-01`) o el código de barras |
| **Descripción** | Como quiere que salga en la factura |
| **Código CABYS** | Obligatorio para Hacienda: use **Buscar CABYS** |
| **Precio sin IVA** y **tarifa de IVA** | El precio de venta y el impuesto que le corresponde |
| **Es un servicio** | Márquelo si no es mercadería |
| **Controlar inventario** | Descuenta existencias al vender |
| **Existencia inicial** y **existencia mínima** | Con cuánto empieza y cuándo avisarle que se está acabando |
| **Categoría** | Para ordenar los productos |

**Importar productos:** igual que los clientes, desde Excel (CSV).

### 10.3 Inventario

*Clientes y productos → Inventario*

- Muestra la **existencia** de cada producto, su **valor al costo** y cuáles
  están **por reabastecer** (bajo el mínimo).
- **Registrar entrada:** cuando llega mercadería (compra o producción).
- **Ajuste por conteo físico:** escriba la existencia contada y el sistema
  hace el ajuste.
- Cada venta descuenta sola. Una nota de crédito que anula o devuelve
  regresa la mercadería. Si Hacienda rechaza una factura, su movimiento se revierte solo.
- **Descargar existencias (CSV)** para Excel.

### 10.4 Descuentos y combos

- **Descuentos:** promociones que se aplican solas al facturar. Pueden ser
  para todos los productos, una categoría o un producto; por porcentaje o
  por monto; desde una cantidad mínima (descuento por volumen); y siempre o
  solo entre ciertas fechas.
- **Combos:** varios productos que se venden juntos a un precio (p. ej. "Combo
  desayuno"). Al vender el combo se descuenta el inventario de cada producto.

---

## 11. Reportes y contabilidad

### 11.1 Contabilidad e impuestos (solo el dueño)

El menú **Contabilidad** lo ve **solo el dueño** de la empresa; los usuarios
administrativos y cajeros no. Ahí está todo: comprobantes del mes y su contabilización
automática (con el costo de ventas desde el inventario), libro diario, catálogo de cuentas,
balance general, estado de resultados, cierre de meses y del año, **reporte de IVA**,
**borrador de la D-104** y libros de ventas y compras. El *Manual del contador* lo explica
paso a paso.

Puede llevar su contabilidad usted mismo o con un **contador**: él entra con su propio
usuario de contador, busca su empresa por la cédula y le llega a usted un correo de aviso.
Ve la contabilidad pero no puede facturar ni cambiar nada. Usted ve quiénes tienen acceso en
*Configuración → Usuarios → Contadores con acceso* y les puede quitar el acceso.

### 11.2 Otros reportes

- **Reporte de clientes:** cuánto le compró cada cliente.
- **Reporte de productos:** cuánto vendió de cada producto.
- **Descargar XML y PDF** (*Documentos*): todos los comprobantes de un mes
  en un archivo ZIP. Hacienda exige **guardar los XML por 5 años**: descárguelos cada mes.

### 11.3 Consultas a Hacienda

*Reportes → Consultas a Hacienda*: con solo la cédula ve la situación del
contribuyente, sus actividades económicas y si es productor MAG o INCOPESCA.
También puede buscar códigos **CABYS**, verificar una **exoneración** y ver
el **tipo de cambio** del día.

---

## 12. Su saldo de documentos

*Configuración → Saldo de documentos*

- **Documentos disponibles**, **usados este mes** y **por vencer pronto**.
- Los paquetes que ha comprado, cuándo vencen y cuántos lleva usados.
- **Servicios contratados:** hasta cuándo está pagado el sistema en línea.

Cuando le quedan pocos documentos, o se le está por vencer el sistema en
línea, le llega un correo con las formas de pago y el contacto de su
proveedor. **Sin documentos no puede emitir.**

**Comprar en línea:** en esta misma pantalla toque **Comprar documentos**, elija el
paquete (y, si quiere, meses del sistema en línea), pague por SINPE Móvil o
transferencia con los datos que aparecen, y escriba el número del comprobante
(puede adjuntar la foto). Al confirmar su proveedor el pago, se acredita y le llega
un correo.

### Mis servicios y facturas

*Configuración → Mis servicios y facturas* (solo el dueño). Cada servicio se cobra por aparte:

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

Para activar un servicio toque **Activar por ₡X al mes**; para dejarlo, **Cancelar** (ese mes se
cobra solo por los días que lo usó). Abajo ve sus **facturas mensuales**; al pagar toque
**Reportar pago** y escriba el número del comprobante.

---

## 12.1 Usuarios y permisos

*Configuración → Usuarios* (solo el dueño de la empresa):

| Rol | Puede |
|---|---|
| **Dueño** | Todo lo de la empresa: vender, anular, precios, configuración, usuarios y la contabilidad. |
| **Administrativo** | Facturas, notas y anulaciones, cobros y facturas de proveedores. No cambia precios ni usa la caja. |
| **Cajero** | Vender (factura, tiquete, punto de venta) y cobrar. No anula. |

Cada persona entra con su propio usuario y el menú le muestra solo lo que puede usar.

**Su contador** no es un usuario de su empresa: tiene un usuario de contador y escoge su
empresa por la cédula (sección 11.1). Usted lo ve en *Contadores con acceso* y le puede
quitar el acceso.

---

## 13. Preguntas frecuentes

| Pregunta | Respuesta |
|---|---|
| El cliente no recibió la factura por correo | Abra la factura → **Enviar por correo** y revise que el correo esté bien escrito. Pídale revisar el correo no deseado |
| ¿Puedo borrar una factura? | No. Si ya se envió, anúlela con nota de crédito (sección 7) |
| Me equivoqué de cliente | Anule por **Error material** y emita la factura correcta |
| Hacienda rechazó una factura | Lea el *Mensaje de Hacienda*, corrija y emita otra. La rechazada no tiene validez |
| La factura está "Enviado" hace rato | Hacienda está lento. El sistema sigue consultando solo; puede usar **Consultar estado** |
| "Saldo de documentos agotado" | Contacte a su proveedor para comprar otro paquete |
| "Su empresa no tiene el panel web" | El servicio en línea está vencido o suspendido. Contacte a su proveedor |
| No me deja entrar | Revise mayúsculas y minúsculas. Tras varios intentos fallidos la cuenta se bloquea unos minutos. Su proveedor puede cambiarle la contraseña |
| Perdí el teléfono de la verificación en dos pasos | Su proveedor se la reinicia |
| ¿Dónde busco el código CABYS? | En el botón **Buscar CABYS** o en *Reportes → Consultas a Hacienda* |
| ¿Se pierden mis datos si cambia algo? | No. Todo queda guardado aunque cambie de plan o renueve |
