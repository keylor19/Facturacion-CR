# Complemento de WooCommerce: Facturación Electrónica CR

Emite automáticamente la factura o el tiquete electrónico de cada pedido de la tienda.

## Instalar

1. Comprima la carpeta `facturacion-cr` en un `.zip`.
2. En WordPress: **Plugins → Añadir nuevo → Subir plugin** y elija el `.zip`. Actívelo.
3. En **WooCommerce → Facturación CR** llene:
   - **Dirección del servicio**: `https://SU-DOMINIO/api/v1`
   - **API key**: la llave de la empresa (empieza con `fcr_`).
   - **CABYS e IVA por defecto**, para los productos que no tengan uno propio.
   - **CABYS del envío**, si cobra envío y quiere facturarlo.
   - **Emitir cuando el pedido pase a**: *Completado* (recomendado) o *Procesando*.
4. En cada producto, pestaña **Facturación CR**, ponga su código CABYS y su IVA si son distintos de los de por defecto.

## Qué hace

| En la tienda | En Hacienda |
|---|---|
| El cliente escribe su cédula en el pago | Factura electrónica (01) a su nombre, le llega por correo |
| El cliente no escribe cédula | Tiquete electrónico (04) con su nombre |
| Cupón o descuento | Descuento en la línea (código 07) |
| Envío cobrado | Línea «Envío» con el CABYS configurado |

- Cada pedido se emite con la referencia `WC-<número de pedido>`: si se reintenta, el servicio devuelve el mismo
  comprobante y **no se cobra dos veces**.
- El resultado queda en las **notas del pedido**. Si algo falla (sin conexión, CABYS inválido, sin saldo), la nota dice
  por qué y en la caja **Facturación CR** del pedido hay un botón **Emitir ahora** para reintentar.
- Medio de pago: contra entrega = efectivo, transferencia bancaria = transferencia, cheque = cheque, cualquier pasarela = tarjeta.

## Requisitos

WordPress 6+, WooCommerce 7+ y PHP 7.4+. Compatible con el almacenamiento de pedidos de alto rendimiento (HPOS).
