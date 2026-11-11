# Manual del contador

Módulo de contabilidad del sistema de facturación electrónica. Lo usan el **contador** (para
todas las empresas que lleva) y el **dueño de cada empresa** (solo para la suya). Ni los demás
usuarios de la empresa ni el administrador del servicio lo ven. El contador no puede facturar ni
cambiar nada de las empresas.

## Índice

1. Cómo entrar y escoger sus empresas
2. Inscribir una empresa que no factura en el sistema
3. Primer paso con cada empresa: el catálogo de cuentas
4. Comprobantes del mes y contabilización automática
5. Asientos manuales (libro diario)
6. Estados financieros
7. Impuestos: IVA, D-104 y libros
8. Cierre de meses
9. Preguntas frecuentes

---

## 1. Cómo entrar y escoger sus empresas

**La primera vez**, en la página de entrada toque **Créela gratis**, elija **Soy contador** y
continúe con Google, Microsoft o su correo. **Las siguientes veces** entre de la misma forma. En **Mis empresas** usted
mismo escoge a qué empresas les lleva la contabilidad:

| Botón | Para qué |
|---|---|
| **Empresa ya inscrita** | La empresa ya factura en el sistema. Escriba su cédula, toque **Buscar** y **Llevar su contabilidad**. A la empresa le llega un correo avisándole; su dueño le puede quitar el acceso cuando quiera. Sus comprobantes emitidos, recibidos y cobros ya están aquí. |
| **+ Inscribir empresa nueva** | La empresa no factura aquí. Usted la inscribe y carga los XML de sus ventas y compras (sección 2). |

Por seguridad no se muestra la lista de empresas del sistema: se busca por la cédula exacta.

**Su mensualidad:** la cuenta de contador tiene un precio por mes que cubre todas las empresas que
lleva (ellas no pagan contabilidad). Actívela en **Mi mensualidad** (le muestra el precio; la
primera vez tiene días de prueba gratis). El día 1 de cada mes le llega la factura del mes
anterior; al pagar, repórtelo ahí mismo. Si vence sin pagar, el módulo se suspende hasta que pague.
Para dejar una empresa, toque **Dejar de llevarla** (sus asientos se conservan).

Elija la empresa tocándola en la lista o con el **selector de arriba**. Todo lo que
haga queda en esa empresa.

Para cada empresa la lista muestra si ya tiene catálogo de cuentas, cuántos
comprobantes tiene el mes y cuántos falta contabilizar, y el último mes cerrado.

## 2. Inscribir una empresa que no factura en el sistema

*Mis empresas → + Inscribir empresa nueva*. Escriba la cédula y toque **Buscar en Hacienda**:
se llenan el nombre y la actividad. Complete correo y dirección y toque **Agregar**.
La empresa queda con el **catálogo de cuentas base** creado.

Después, en *Comprobantes del mes → Cargar XML de Hacienda*, seleccione los XML (puede
elegir muchos a la vez):

- Los que la empresa **emitió** (facturas, tiquetes, notas, exportación) entran como **ventas**.
- Los que la empresa **recibió** de sus proveedores entran como **compras**, con el IVA
  como crédito fiscal (si no lo es, corríjalo en el asiento).
- El sistema distingue solo cuál es cuál, rechaza los que no son de la empresa y nunca
  carga dos veces el mismo comprobante. Al final le muestra los que no entraron y por qué.

Las respuestas de Hacienda y los mensajes receptor no se cargan: solo los comprobantes.

## 3. Primer paso con cada empresa: el catálogo de cuentas

*Contabilidad → Catálogo de cuentas*. Si la empresa no tiene catálogo, toque **Crear
catálogo base**: es un catálogo NIIF para PYMES con las cuentas usuales (caja y bancos,
clientes, IVA crédito y débito fiscal, proveedores, capital, ventas, costo de ventas,
gastos…).

- El código con puntos da la jerarquía: `1` Activo → `1.1` Activo corriente → `1.1.01` Caja y bancos.
- Las cuentas **de grupo** suman a sus hijas y no reciben asientos; las demás sí.
- Agregue las cuentas que la empresa necesite con **+ Nueva cuenta** (por ejemplo
  `1.1.01.01 Banco Nacional`). Una cuenta con movimientos solo se puede renombrar o desactivar.
- Algunas cuentas dicen **Automático: …**: son las que usan los asientos automáticos.

## 4. Comprobantes del mes y contabilización automática

*Contabilidad → Comprobantes del mes*. Elija el mes: verá las **ventas** y **compras**
aceptadas por Hacienda, con su IVA y total en colones, y si ya tienen asiento.

Toque **Contabilizar el mes**: el sistema crea un asiento por cada comprobante que todavía
no tenga. Puede tocarlo cuantas veces quiera: no duplica.

| Comprobante | Asiento |
|---|---|
| Factura, tiquete, exportación o nota de débito | Debe: caja y bancos (contado) o clientes (crédito) · Haber: ventas, IVA débito fiscal y otros cargos |
| Nota de crédito emitida | Al revés: devoluciones sobre ventas e IVA contra caja o clientes |
| Recibo electrónico de pago | Debe caja y bancos · Haber clientes |
| Abono de un cliente (crédito comercial) | Debe caja y bancos · Haber clientes |
| Factura de proveedor | Debe compras y gastos e IVA crédito fiscal · Haber proveedores |
| Nota de crédito de un proveedor | Al revés |
| Factura electrónica de compra (a no inscritos) | Debe compras y gastos e IVA crédito · Haber caja y bancos |
| **Costo de ventas** (productos con inventario) | Debe costo de ventas · Haber inventario, al costo promedio de cada producto |
| Devolución de mercadería (nota de crédito) | Al revés: vuelve al inventario |
| Entrada de mercadería al inventario con costo | Debe inventario · Haber compras y gastos (pasa la compra del gasto al inventario) |
| Existencia inicial de un producto | Debe inventario · Haber utilidades acumuladas (inventario con que empezó) |
| Salida o ajuste de inventario (mermas, faltantes, sobrantes) | Contra el costo de ventas |

El **costo de ventas** sale solo del inventario: cada venta de un producto que controla
inventario descuenta existencias a su costo promedio, y ese costo se contabiliza. Si un
producto no tiene costo, al contabilizar el sistema le muestra la lista para que se lo ponga
(en *Mis productos* de la empresa o con una entrada con costo) y vuelva a contabilizar.

Los montos en dólares u otra moneda se pasan a colones con el tipo de cambio del
comprobante. Los céntimos de redondeo van a otros ingresos u otros gastos.

Si un asiento automático no es como usted lo lleva (por ejemplo una compra que es
inventario o un activo), ábralo en el libro diario y cámbielo: queda marcado como
**corregido a mano**.

## 5. Asientos manuales (libro diario)

*Contabilidad → Libro diario*. Muestra los asientos entre dos fechas (busque por número
o descripción).

- **+ Nuevo asiento:** fecha, descripción y las líneas (cuenta, debe o haber, detalle).
  Abajo ve si **cuadra**; el sistema no guarda un asiento que no cuadre ni líneas en
  cuentas de grupo.
- Toque un asiento para **editarlo**; **Anular** lo deja sin efecto (no se borra).
- **Excel** descarga el diario con todas las líneas.

Ejemplos de asientos manuales: aporte de capital, planilla, cargas sociales, depreciación,
pagos a proveedores, préstamos, ajustes de inventario y costo de ventas.

## 6. Estados financieros

Menú **Estados financieros**. Todos se pueden descargar en Excel o imprimir (o guardar en PDF).

| Reporte | Qué muestra |
|---|---|
| **Balance general** | Activo, pasivo y patrimonio a una fecha, más el resultado acumulado. Avisa si no cuadra. |
| **Estado de resultados** | Ingresos, costos, gastos, utilidad bruta y neta de un período. |
| **Balance de comprobación** | Por cuenta: saldo inicial, debe, haber y saldo final; con totales que deben cuadrar. |
| **Libro mayor** | Los movimientos de una cuenta con su saldo después de cada uno. |

### Cierre del año

*Contabilidad → Cierre del año*. Elija el año y el sistema calcula el **asiento de cierre**:
lleva a cero todas las cuentas de ingresos, costos y gastos del año y pasa la utilidad (o
pérdida) a *Utilidades acumuladas*, con fecha 31 de diciembre.

1. Revise la propuesta en pantalla (cuentas, debe, haber y resultado del año).
2. **Descargar archivo (Excel)**: es el archivo digital del asiento, con la empresa, la fecha y
   todas sus líneas. Guárdelo como respaldo. Si lleva la contabilidad de esa empresa en otro
   sistema, cópielo de ahí línea por línea.
3. **Registrar el asiento de cierre**: queda en el libro diario como «Cierre del año». Se hace
   una sola vez por año; si necesita rehacerlo, anúlelo en el libro diario y regístrelo de nuevo.

Después del cierre, el estado de resultados del año sigue mostrando la utilidad (no cuenta el
asiento de cierre) y el balance general la muestra dentro de utilidades acumuladas.

## 7. Impuestos: IVA, D-104 y libros

Menú **Impuestos**:

- **Reporte de IVA:** ventas por tarifa, compras por condición, IVA débito y crédito,
  notas por error material que afectan otros meses, y los **libros de ventas y compras**
  en Excel.
- **Borrador D-104:** los montos ordenados como la declaración del IVA en TRIBU-CR, cada
  uno con su botón **Copiar**. No incluye prorrata, saldos a favor de meses anteriores ni
  retenciones.
- **Consultas a Hacienda:** cédulas, CABYS, exoneraciones y tipo de cambio.

## 8. Cierre de meses

*Contabilidad → Cierre de meses*. Cuando ya declaró un mes, **ciérrelo**: nadie puede crear,
cambiar ni anular asientos con fecha de ese mes, ni contabilizarlo de nuevo. Si necesita
corregir algo, ábralo con **Abrir**, haga el cambio y ciérrelo otra vez.

## 9. Preguntas frecuentes

**¿La empresa ve lo que hago?** Solo su dueño: él ve la contabilidad de su empresa en el mismo
módulo (por ejemplo para revisarla o llevarla él mismo). Los demás usuarios de la empresa y el
administrador del servicio no la ven.

**¿Puedo facturar por la empresa?** No. Su usuario es solo de contabilidad.

**Un comprobante no aparece en el mes.** Solo aparecen los aceptados por Hacienda. Los
pendientes o rechazados no se contabilizan.

**Cargué un XML y dice «no es de esta empresa».** La cédula del emisor o del receptor del
XML no coincide con la de la empresa elegida en el selector.

**Contabilicé y faltó la cuenta de algo.** El mensaje dice qué cuenta automática falta:
créela (o márquela) en el catálogo y vuelva a contabilizar.
