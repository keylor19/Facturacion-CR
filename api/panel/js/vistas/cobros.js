// Cuentas por cobrar: facturas a crédito con saldo, antigüedad, estado de cuenta por cliente,
// abonos (crédito comercial) y recibos de pago (crédito al Estado / IVA a 90 días).
import { api } from '../api.js';
import { h, vaciar, dinero, tabla, modal, conBoton, toast, campo, opciones, aviso } from '../dom.js';
import { MEDIOS_PAGO, CONDICIONES_VENTA } from '../catalogos.js';
import { dialogoPago } from './comprobantes.js';
import { puede } from '../app.js';

const TRAMOS = [
  ['al_dia', 'Al día', 'ACEPTADO'], ['1_30', '1 a 30 días', 'CONTINGENCIA'], ['31_60', '31 a 60 días', 'CONTINGENCIA'],
  ['61_90', '61 a 90 días', 'RECHAZADO'], ['mas_90', 'Más de 90 días', 'RECHAZADO'],
];
const NOMBRE_TRAMO = Object.fromEntries(TRAMOS.map(([k, t]) => [k, t]));
const CLASE_TRAMO = Object.fromEntries(TRAMOS.map(([k, , c]) => [k, c]));
const fechaCorta = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('es-CR') : '');

export function dialogoAbono(f, alTerminar) {
  const monto = h('input', { type: 'number', step: '0.01', min: '0.01', value: f.saldo });
  const fecha = h('input', { type: 'date', value: new Date().toLocaleDateString('en-CA') });
  const medio = h('select', {}, opciones(MEDIOS_PAGO, '04'));
  const referencia = h('input', { type: 'text', maxlength: '100', placeholder: 'N.º de transferencia, SINPE o cheque' });
  const nota = h('input', { type: 'text', maxlength: '250' });
  const boton = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(boton, async () => {
    const r = await api(`/cobros/facturas/${f.factura_id}/abonos`, {
      method: 'POST',
      body: { monto: monto.value, fecha: fecha.value, medio_pago: medio.value, referencia: referencia.value.trim() || null, nota: nota.value.trim() || null },
    });
    m.cerrar();
    toast(Number(r.saldo) > 0 ? `Pago registrado. Queda ${dinero(r.saldo, f.moneda)}` : 'Factura pagada por completo', 'ok');
    alTerminar();
  }) }, 'Registrar pago');
  const m = modal(`Pago de la factura ${f.consecutivo}`, [
    h('p', {}, `${f.cliente || 'Cliente'} · saldo ${dinero(f.saldo, f.moneda)}`),
    h('p', { class: 'suave' }, 'El crédito comercial no lleva comprobante electrónico de pago: el abono queda en su cuenta por cobrar.'),
    h('div', { class: 'campos' }, campo(`Monto (${f.moneda})`, monto), campo('Fecha del pago', fecha),
      campo('Medio de pago', medio), campo('Referencia', referencia), campo('Nota (opcional)', nota)),
  ], { acciones: [boton] });
}

const botonPago = (f, refrescar) => h('button', { type: 'button', class: 'chico primario', onclick: (e) => {
  e.stopPropagation();
  if (f.con_recibo) dialogoPago(f.factura_id, f, f.saldo, refrescar); else dialogoAbono(f, refrescar);
} }, 'Registrar pago');

export async function vistaCuentasPorCobrar(cont) {
  const refrescar = () => vistaCuentasPorCobrar(cont).catch((e) => toast(e.message, 'error'));
  const c = await api('/cobros/cartera');
  const monedas = Object.keys(c.resumen);
  const crc = c.resumen.CRC || {};
  const vencido = ['1_30', '31_60', '61_90', 'mas_90'].reduce((s, t) => s + Number(crc[t] || 0), 0);

  const recordar = h('input', { type: 'checkbox', checked: c.recordar_cobros, onchange: async () => {
    recordar.disabled = true;
    try {
      await api('/cobros/ajustes', { method: 'PUT', body: { recordar_cobros: recordar.checked } });
      toast(recordar.checked ? 'Se enviarán recordatorios de cobro' : 'Recordatorios desactivados', 'ok');
    } catch (e) {
      recordar.checked = !recordar.checked;
      toast(e.message, 'error');
    } finally {
      recordar.disabled = false;
    }
  } });

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Cuentas por cobrar'),
      h('a', { href: '#/comprobantes-pago', class: 'boton' }, 'Recibos de pago emitidos')),
    h('div', { class: 'kpis' },
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Por cobrar (colones)'), h('div', { class: 'valor' }, dinero(crc.total || 0))),
      h('div', { class: `kpi ${vencido > 0 ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, 'Vencido (colones)'), h('div', { class: 'valor' }, dinero(vencido))),
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Facturas con saldo'), h('div', { class: 'valor' }, c.facturas.length)),
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Clientes que deben'), h('div', { class: 'valor' }, c.clientes.length))),
    monedas.length ? h('section', { class: 'tarjeta' }, h('h2', {}, 'Antigüedad de saldos'),
      tabla([
        { titulo: 'Moneda', valor: ([m]) => m },
        ...TRAMOS.map(([k, t]) => ({ titulo: t, num: true, valor: ([m, r]) => dinero(r[k], m) })),
        { titulo: 'Total', num: true, valor: ([m, r]) => h('strong', {}, dinero(r.total, m)) },
      ], Object.entries(c.resumen))) : null,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Por cliente'),
      h('p', { class: 'suave' }, 'Toque un cliente para ver e imprimir su estado de cuenta.'),
      tabla([
        { titulo: 'Cliente', valor: (x) => [x.cliente || '—', h('div', { class: 'suave mono' }, x.identificacion || '')] },
        { titulo: 'Facturas', num: true, valor: (x) => x.facturas },
        { titulo: 'Saldo', num: true, valor: (x) => dinero(x.saldo, x.moneda) },
        { titulo: 'Vencido', num: true, valor: (x) => (Number(x.vencido) > 0 ? h('strong', {}, dinero(x.vencido, x.moneda)) : '—') },
        { titulo: 'Más atrasada', valor: (x) => (x.mas_atraso ? `${x.mas_atraso} días` : 'Al día') },
      ], c.clientes, (x) => { if (x.identificacion) location.hash = `#/estado-cuenta/${encodeURIComponent(x.identificacion)}`; })),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Facturas pendientes'),
      tabla([
        { titulo: 'Factura', valor: (f) => [f.consecutivo, h('div', { class: 'suave' }, CONDICIONES_VENTA[f.condicion_venta] || '')] },
        { titulo: 'Cliente', valor: (f) => f.cliente || '' },
        { titulo: 'Fecha', valor: (f) => fechaCorta(f.fecha) },
        { titulo: 'Vence', valor: (f) => fechaCorta(f.vence) },
        { titulo: 'Atraso', valor: (f) => h('span', { class: `badge ${CLASE_TRAMO[f.tramo]}` }, f.dias_vencida ? `${f.dias_vencida} días` : 'Al día') },
        { titulo: 'Total', num: true, valor: (f) => dinero(f.total, f.moneda) },
        { titulo: 'Saldo', num: true, valor: (f) => h('strong', {}, dinero(f.saldo, f.moneda)) },
        { titulo: '', valor: (f) => (f.estado === 'ACEPTADO' || !f.con_recibo ? botonPago(f, refrescar) : null) },
      ], c.facturas, (f) => { location.hash = `#/comprobantes/${f.factura_id}`; })),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Recordatorios automáticos'),
      h('label', { class: 'check' }, recordar, 'Enviar por correo un recordatorio a los clientes con facturas vencidas'),
      h('p', { class: 'suave' }, `Se envía a los ${c.dias_recordatorio.join(', ')} días de atraso, una vez cada uno, al correo de la factura. `
        + 'Las respuestas del cliente le llegan a su correo.'),
      puede('configuracion') ? null : aviso('Solo el dueño de la empresa puede cambiar esta opción.', 'info')));
  if (!puede('configuracion')) recordar.disabled = true;
}

export async function vistaEstadoCuenta(cont, identificacion) {
  const ec = await api(`/cobros/estado-cuenta/${encodeURIComponent(decodeURIComponent(identificacion))}`);
  const refrescar = () => vistaEstadoCuenta(cont, identificacion).catch((e) => toast(e.message, 'error'));
  const filas = [];
  for (const f of ec.facturas) {
    filas.push({ ...f, tipo: 'factura' });
    for (const p of f.pagos) filas.push({ ...p, tipo: 'pago', moneda: f.moneda });
  }
  vaciar(cont,
    h('div', { class: 'encabezado no-imprimir' }, h('a', { href: '#/pagos' }, '← Cuentas por cobrar'),
      h('button', { type: 'button', class: 'primario', onclick: () => window.print() }, 'Imprimir o guardar PDF')),
    h('section', { class: 'tarjeta' },
      h('h1', {}, 'Estado de cuenta'),
      h('dl', { class: 'datos' },
        h('dt', {}, 'Empresa'), h('dd', {}, ec.empresa),
        h('dt', {}, 'Cliente'), h('dd', {}, ec.cliente || '—'),
        h('dt', {}, 'Identificación'), h('dd', { class: 'mono' }, ec.identificacion),
        h('dt', {}, 'Fecha'), h('dd', {}, fechaCorta(ec.fecha)),
        h('dt', {}, 'Saldo'), h('dd', {}, Object.entries(ec.saldo).map(([m, v]) => h('strong', {}, `${dinero(v, m)} `)))),
      tabla([
        { titulo: 'Fecha', valor: (x) => fechaCorta(x.fecha) },
        { titulo: 'Detalle', valor: (x) => (x.tipo === 'factura'
          ? [`Factura ${x.consecutivo}`, h('div', { class: 'suave' }, `Vence ${fechaCorta(x.vence)}${x.dias_vencida ? ` · ${x.dias_vencida} días de atraso` : ''}`)]
          : h('span', { class: 'suave' }, `Pago ${MEDIOS_PAGO[x.medio_pago] || ''} ${x.referencia || ''}`)) },
        { titulo: 'Cargo', num: true, valor: (x) => (x.tipo === 'factura' ? dinero(x.total, x.moneda) : '') },
        { titulo: 'Notas', num: true, valor: (x) => (x.tipo === 'factura' && Number(x.notas) ? dinero(x.notas, x.moneda) : '') },
        { titulo: 'Abono', num: true, valor: (x) => (x.tipo === 'pago' ? dinero(x.monto, x.moneda) : '') },
        { titulo: 'Saldo', num: true, valor: (x) => (x.tipo === 'factura' ? h('strong', {}, dinero(x.saldo, x.moneda)) : '') },
        { titulo: '', valor: (x) => (x.tipo === 'factura' && Number(x.saldo) > 0 ? h('span', { class: 'no-imprimir' }, botonPago(x, refrescar)) : null) },
      ], filas)));
}
