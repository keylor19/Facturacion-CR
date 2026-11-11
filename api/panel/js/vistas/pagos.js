// Recibos electrónicos de pago emitidos (los saldos por cobrar están en vistas/cobros.js).
import { api } from '../api.js';
import { h, vaciar, dinero, fecha, badge, tabla } from '../dom.js';

export async function vistaComprobantesPago(cont) {
  const lista = await api('/facturas?tipo_documento=10&limit=500');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Comprobantes de pago'),
      h('a', { href: '#/pagos', class: 'boton' }, 'Cuentas por cobrar')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Fecha', valor: (r) => fecha(r.fecha_emision) },
      { titulo: 'Consecutivo', valor: (r) => r.numero_consecutivo },
      { titulo: 'Cliente', valor: (r) => r.receptor_nombre || '' },
      { titulo: 'IVA', num: true, valor: (r) => dinero(r.monto_impuesto, r.moneda) },
      { titulo: 'Monto', num: true, valor: (r) => dinero(r.monto_total, r.moneda) },
      { titulo: 'Estado', valor: (r) => badge(r.estado) },
    ], lista, (r) => { location.hash = `#/comprobantes/${r.factura_id}`; })),
    h('p', { class: 'suave' }, 'Toque un recibo para ver el PDF, el XML o reenviarlo por correo.'));
}
