# Qué entregarle a cada cliente

Hay dos servicios y se venden por separado. Cada uno se activa en
**Empresas → ficha → Datos de la empresa**:

| Servicio | Casilla | Para quién |
|---|---|---|
| **Conexión por API** | *Conexión por API (su sistema de facturación)* | Ya tiene un sistema (POS, ERP, sistema a la medida) y quiere que ese sistema facture electrónicamente. |
| **Facturación en línea** | *Facturación en línea (panel…)* | No tiene sistema: factura desde el navegador, con clientes, productos e inventario. |

Puede activar uno, el otro o los dos. Los documentos (saldo) se descuentan
igual sin importar por dónde se emitan.

## Qué se cobra (todo por aparte)

| Cobro | Dónde se registra | Qué pasa si no paga |
|---|---|---|
| **Documentos** (paquetes) | Ficha → *Documentos (saldo)* → **+ Vender paquete** | Al agotarse no puede emitir (`402`) |
| **Mensualidad de conexión por API** | Ficha → *Servicios alquilados* → **Cobrar / Renovar** | Al vencer (más los días de gracia) sus llaves dejan de funcionar |
| **Mensualidad de facturación en línea** | Ficha → *Servicios alquilados* → **Cobrar / Renovar** | Al vencer (más los días de gracia) deja de ver Nuevo comprobante, Clientes, Productos e Inventario |

- La mensualidad se cobra por 1, 3, 6 o 12 meses con el precio que usted
  defina (0 = cortesía). Si renueva antes de vencer, el período nuevo empieza
  cuando termina el actual: no pierde días.
- El cliente recibe un aviso por correo (y webhook) `DIAS_ALERTA_SUSCRIPCION`
  días antes de vencer y el día que vence. Tiene `DIAS_GRACIA_SUSCRIPCION`
  días de gracia antes del corte.
- En *Planes y ventas* ve los ingresos del mes separados: documentos y servicios.
- Cada cobro o anulación queda en la *Bitácora*.
- Si prefiere no cobrar mensualidad (solo documentos), ponga
  `CONTROL_SUSCRIPCIONES=false` en `.env`: los servicios quedan controlados
  solo por las casillas.

> **Importante para la conexión por API:** el API no se "instala" en el
> sistema del cliente. El **programador o proveedor del sistema del cliente**
> tiene que programar la conexión (enviar las ventas al API) siguiendo la
> guía. Si el cliente no tiene quien le programe, ofrézcale la facturación
> en línea.

Antes de entregar cualquiera de los dos, la empresa debe estar lista: creada,
con certificado, credenciales de Hacienda, *Probar conexión* en ok, con
paquete de documentos **y con la mensualidad del servicio cobrada** (ver el
[manual del administrador](manual-administrador.md)).

---

## A) Conexión por API: qué entregar

1. En la ficha de la empresa → **Integración con otros sistemas → Nueva llave**
   (un nombre por sistema o sucursal) → **Crear API key** →
   **Copiar datos de conexión**.
2. Envíe al programador del cliente, **por un canal seguro** (la API key es
   como una contraseña: no la mande por WhatsApp ni en un correo sin cifrar):
   - Los **datos de conexión** que copió (URL base + API key + ejemplo).
   - La **[guía de integración](integracion.md)** (convertida a PDF o como enlace).
   - La documentación interactiva: `https://<su-dominio>/docs` (active
     `DOCS_PUBLICAS=true` en `.env` para que puedan verla).
3. Opcional: si su sistema quiere avisos automáticos de aceptado/rechazado,
   configure el **Webhook** y entréguele el secreto.

### Plantilla de mensaje

> Hola, [nombre]:
>
> Su empresa **[razón social]** ya está habilitada para facturar
> electrónicamente por medio de nuestro API. Por favor entregue esta
> información a quien programa su sistema de facturación:
>
> - **URL base:** `https://[su-dominio]/api/v1`
> - **API key:** se la enviamos por [canal seguro]. Debe enviarse en el
>   encabezado `X-API-Key` de cada solicitud. Guárdela como una contraseña.
> - **Guía de integración:** [adjunta / enlace]
> - **Documentación interactiva:** `https://[su-dominio]/docs`
>
> Empezamos en **ambiente de pruebas**: las facturas van al sandbox de
> Hacienda y no tienen validez fiscal. Cuando su programador confirme que todo
> funciona, pasamos a producción sin que tenga que cambiar nada en su sistema.
>
> Documentos disponibles: **[cantidad]**. Le avisaremos cuando queden pocos.

---

## B) Facturación en línea: qué entregar

1. **Usuarios → + Nuevo usuario** → correo del cliente, nombre, contraseña
   inicial y acceso **"Solo [empresa]"**.
2. Opcional: cargue su **logo** en la ficha de la empresa (sale en el PDF).
3. Envíele:

### Plantilla de mensaje

> Hola, [nombre]:
>
> Ya puede facturar electrónicamente desde el navegador:
>
> - **Dirección:** `https://[su-dominio]/panel/`
> - **Usuario:** [correo]
> - **Contraseña inicial:** se la enviamos por [canal seguro]. Cámbiela al
>   ingresar en *Mi cuenta*.
>
> Primeros pasos:
> 1. **Productos:** registre lo que vende (código CABYS, precio e IVA). Si
>    quiere llevar inventario, marque *Controlar inventario*.
> 2. **Clientes:** registre sus clientes frecuentes (o guárdelos al facturar).
> 3. **Nuevo comprobante:** *Elegir cliente*, *+ Del catálogo*, y
>    **Firmar y enviar a Hacienda**. El PDF y el XML le llegan al cliente por
>    correo cuando Hacienda acepta la factura.
>
> Recomendamos activar la **verificación en dos pasos** en *Mi cuenta*.
>
> Documentos disponibles: **[cantidad]**.

---

## Si deja de pagar un servicio

Si no renueva la mensualidad, el servicio **se corta solo** al terminar los
días de gracia. Para cortarlo de inmediato (o suspenderlo aunque esté pagado),
desmarque la casilla correspondiente y **Guardar cambios**:

- **Conexión por API desactivada:** las llaves de esa empresa reciben
  `403 La conexión por API no está activa`. No se pueden crear llaves nuevas.
- **Facturación en línea desactivada:** sus usuarios del panel ya no ven
  Nuevo comprobante, Clientes, Productos ni Inventario (sí sus comprobantes y
  reportes).
- **Sin saldo:** no puede emitir por ningún medio (`402`) hasta que le venda
  otro paquete.

Al volver a marcarla, todo funciona de nuevo: no se pierde nada.
