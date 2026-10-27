// Pagos: saldos de facturas a crédito y recibos electrónicos de pago emitidos.
import { api } from '../api.js';
import { h, vaciar, dinero, fecha, badge, tabla, toast, aviso } from '../dom.js';
import { CONDICIONES_VENTA } from '../catalogos.js';
import { dialogoPago } from './comprobantes.js';

// Condiciones de venta que se cobran con Recibo Electrónico de Pago (crédito al Estado / IVA a 90 días)
const CON_RECIBO = ['08', '10'];

export async function vistaPagos(cont) {
  const refrescar = () => vistaPagos(cont).catch((e) => toast(e.message, 'error'));
  const facturas = (await api('/facturas?tipo_documento=01&estado=ACEPTADO&limit=500'))
    .filter((f) => CON_RECIBO.includes(f.condicion_venta) || f.condicion_venta === '02');
  const conRecibo = facturas.filter((f) => CON_RECIBO.includes(f.condicion_venta));
  const pagos = await Promise.all(conRecibo.map((f) => api(`/facturas/${f.factura_id}/pagos`)));
  const filas = conRecibo.map((f, i) => ({ ...f, saldo: Number(pagos[i].saldo_pendiente), recibos: pagos[i].recibos.length }));
  const pendientes = filas.filter((f) => f.saldo > 0);
  const porCobrar = pendientes.reduce((s, f) => s + (f.moneda === 'CRC' ? f.saldo : 0), 0);
  const credito = facturas.filter((f) => f.condicion_venta === '02');

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Administrar pagos'),
      h('a', { href: '#/comprobantes-pago', class: 'boton' }, 'Comprobantes de pago')),
    h('div', { class: 'kpis' },
      h('div', { class: `kpi ${pendientes.length ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, 'Facturas con saldo pendiente'), h('div', { class: 'valor' }, pendientes.length)),
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Por cobrar (colones)'), h('div', { class: 'valor' }, dinero(porCobrar)))),
    h('section', { class: 'tarjeta' },
      h('h2', {}, 'Crédito al Estado e IVA hasta 90 días'),
      h('p', { class: 'suave' }, 'Al recibir un pago se emite un Recibo Electrónico de Pago con el IVA proporcional, como lo pide Hacienda.'),
      tabla([
        { titulo: 'Fecha', valor: (f) => fecha(f.fecha_emision, false) },
        { titulo: 'Consecutivo', valor: (f) => f.numero_consecutivo },
        { titulo: 'Cliente', valor: (f) => f.receptor_nombre || '' },
        { titulo: 'Condición', valor: (f) => CONDICIONES_VENTA[f.condicion_venta] || f.condicion_venta },
        { titulo: 'Total', num: true, valor: (f) => dinero(f.monto_total, f.moneda) },
        { titulo: 'Saldo', num: true, valor: (f) => h('strong', {}, dinero(f.saldo, f.moneda)) },
        { titulo: 'Estado', valor: (f) => (f.saldo > 0 ? h('span', { class: 'badge CONTINGENCIA' }, f.recibos ? 'Pago parcial' : 'Pendiente') : h('span', { class: 'badge ACEPTADO' }, 'Pagada')) },
        { titulo: '', valor: (f) => (f.saldo > 0 ? h('button', { type: 'button', class: 'chico primario', onclick: (e) => {
          e.stopPropagation();
          dialogoPago(f.factura_id, f, f.saldo, refrescar);
        } }, 'Registrar pago') : null) },
      ], filas, (f) => { location.hash = `#/comprobantes/${f.factura_id}`; })),
    credito.length ? h('section', { class: 'tarjeta' },
      h('h2', {}, 'Facturas a crédito'),
      aviso('Hacienda no usa recibo de pago para el crédito comercial (condición 02): el cobro se controla fuera del comprobante.', 'info'),
      tabla([
        { titulo: 'Fecha', valor: (f) => fecha(f.fecha_emision, false) },
        { titulo: 'Consecutivo', valor: (f) => f.numero_consecutivo },
        { titulo: 'Cliente', valor: (f) => f.receptor_nombre || '' },
        { titulo: 'Total', num: true, valor: (f) => dinero(f.monto_total, f.moneda) },
      ], credito, (f) => { location.hash = `#/comprobantes/${f.factura_id}`; })) : null);
}

export async function vistaComprobantesPago(cont) {
  const lista = await api('/facturas?tipo_documento=10&limit=500');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Comprobantes de pago'),
      h('a', { href: '#/pagos', class: 'boton' }, 'Administrar pagos')),
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
