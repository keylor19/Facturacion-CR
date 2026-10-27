// Punto de venta con caja: apertura con fondo, ventas del turno, entradas y
// salidas de efectivo y cierre con arqueo. Historial de cierres en #/cajas.
import { api } from '../api.js';
import { h, vaciar, dinero, fecha, tabla, modal, conBoton, toast, campo, aviso, badge, TIPOS } from '../dom.js';
import { MEDIOS_PAGO } from '../catalogos.js';
import { crearVenta } from './facturaRapida.js';

// Caja elegida en este navegador (comodidad por usuario; si se pierde se vuelve a elegir)
const recordar = {
  get() { try { return sessionStorage.getItem('cajaId'); } catch { return null; } },
  set(v) { try { if (v) sessionStorage.setItem('cajaId', v); else sessionStorage.removeItem('cajaId'); } catch { /* sin almacenamiento */ } },
};
const nombreCaja = (c) => `Sucursal ${c.sucursal} · Terminal ${c.terminal}`;
const kpi = (etiqueta, valor, clase = '') => h('div', { class: `kpi ${clase}` },
  h('div', { class: 'etiqueta' }, etiqueta), h('div', { class: 'valor' }, valor));

export async function vistaPuntoVenta(cont) {
  const abiertas = await api('/cajas?estado=ABIERTA');
  const elegida = abiertas.find((c) => c.id === recordar.get()) || (abiertas.length === 1 ? abiertas[0] : null);
  if (elegida) { recordar.set(elegida.id); await pantallaCaja(cont, elegida); return; }
  recordar.set(null);
  pantallaApertura(cont, abiertas);
}

function pantallaApertura(cont, abiertas) {
  const sucursal = h('input', { type: 'number', min: '1', max: '999', value: '1' });
  const terminal = h('input', { type: 'number', min: '1', max: '99999', value: String(Math.max(0, ...abiertas.map((c) => c.terminal)) + 1) });
  const fondo = h('input', { type: 'number', step: '0.01', min: '0', value: '0' });
  const notas = h('input', { type: 'text', maxlength: '500', placeholder: 'Opcional' });
  const abrir = h('button', { type: 'submit', class: 'primario' }, 'Abrir caja');
  const form = h('form', { class: 'tarjeta', onsubmit: (e) => {
    e.preventDefault();
    conBoton(abrir, async () => {
      const c = await api('/cajas', { method: 'POST', body: {
        sucursal: Number(sucursal.value), terminal: Number(terminal.value), monto_apertura: fondo.value || '0', notas: notas.value.trim() || null,
      } });
      recordar.set(c.id);
      toast('Caja abierta', 'ok');
      await pantallaCaja(cont, c);
    });
  } },
  h('h2', {}, 'Abrir caja'),
  h('p', { class: 'suave' }, 'Cuente el efectivo con que inicia el turno (fondo de caja). Al cerrar se compara con lo vendido.'),
  h('div', { class: 'campos' }, campo('Sucursal', sucursal), campo('Terminal', terminal),
    campo('Fondo de caja (₡)', fondo), campo('Notas', notas)),
  h('div', { class: 'acciones' }, abrir));

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Punto de venta'), h('a', { href: '#/cajas', class: 'boton' }, 'Cierres de caja')),
    abiertas.length ? h('section', { class: 'tarjeta' }, h('h2', {}, 'Cajas abiertas'),
      h('p', { class: 'suave' }, 'Elija la caja en la que va a vender o abra otra terminal.'),
      tabla([
        { titulo: 'Caja', valor: nombreCaja },
        { titulo: 'Abierta', valor: (c) => fecha(c.abierta_en) },
        { titulo: 'Por', valor: (c) => c.abierta_por || '' },
        { titulo: 'Ventas', num: true, valor: (c) => c.resumen.documentos },
      ], abiertas, (c) => { recordar.set(c.id); pantallaCaja(cont, c).catch((e) => toast(e.message, 'error')); })) : null,
    form);
}

async function pantallaCaja(cont, caja) {
  const indicadores = h('div', { class: 'kpis' });
  const pintarIndicadores = (c) => {
    const r = c.resumen;
    vaciar(indicadores,
      kpi('Ventas del turno', r.documentos),
      kpi('Total vendido', dinero(r.total_ventas)),
      kpi('Efectivo en caja (esperado)', dinero(r.efectivo_esperado)),
      r.rechazados.length ? kpi('Rechazados por Hacienda', r.rechazados.length, 'alerta') : null);
  };
  const refrescar = async () => { caja = await api(`/cajas/${caja.id}`); pintarIndicadores(caja); };
  pintarIndicadores(caja);

  const venta = crearVenta({
    enviar: (datos) => api(`/cajas/${caja.id}/ventas`, { method: 'POST', body: datos }),
    alEmitir: () => refrescar().catch((e) => toast(e.message, 'error')),
  });

  vaciar(cont,
    h('div', { class: 'encabezado' },
      h('div', {}, h('h1', {}, 'Punto de venta'),
        h('p', { class: 'suave' }, `${nombreCaja(caja)} · abierta ${fecha(caja.abierta_en)} por ${caja.abierta_por || '—'}`)),
      h('div', { class: 'acciones' },
        h('button', { type: 'button', onclick: () => dialogoMovimiento(caja, 'entrada', refrescar) }, 'Entrada de efectivo'),
        h('button', { type: 'button', onclick: () => dialogoMovimiento(caja, 'salida', refrescar) }, 'Salida de efectivo'),
        h('button', { type: 'button', onclick: () => { recordar.set(null); vistaPuntoVenta(cont).catch((e) => toast(e.message, 'error')); } }, 'Cambiar caja'),
        h('button', { type: 'button', class: 'peligro', onclick: () => refrescar().then(() => dialogoCierre(caja)).catch((e) => toast(e.message, 'error')) }, 'Cerrar caja'))),
    indicadores,
    venta.nodo);
  venta.enfocar();
}

function dialogoMovimiento(caja, tipo, alTerminar) {
  const monto = h('input', { type: 'number', step: '0.01', min: '0.01' });
  const motivo = h('input', { type: 'text', maxlength: '200', placeholder: tipo === 'entrada' ? 'Ej.: Cambio adicional' : 'Ej.: Pago a proveedor de hielo' });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    await api(`/cajas/${caja.id}/movimientos`, { method: 'POST', body: { tipo, monto: monto.value, motivo: motivo.value.trim() } });
    m.cerrar();
    toast(tipo === 'entrada' ? 'Entrada registrada' : 'Salida registrada', 'ok');
    await alTerminar();
  }) }, 'Registrar');
  const m = modal(tipo === 'entrada' ? 'Entrada de efectivo' : 'Salida de efectivo',
    [h('div', { class: 'campos' }, campo('Monto (₡)', monto), campo('Motivo', motivo))], { acciones: [guardar] });
}

function dialogoCierre(caja) {
  const r = caja.resumen;
  const contado = h('input', { type: 'number', step: '0.01', min: '0' });
  const notas = h('input', { type: 'text', maxlength: '500', placeholder: 'Opcional' });
  const diferencia = h('strong');
  const actualizar = () => {
    if (contado.value === '') { diferencia.textContent = '—'; diferencia.className = ''; return; }
    const d = Number(contado.value) - Number(r.efectivo_esperado);
    diferencia.textContent = `${d > 0 ? 'Sobrante' : d < 0 ? 'Faltante' : 'Cuadra'} ${dinero(Math.abs(d))}`;
    diferencia.className = d < 0 ? 'negativo' : '';
  };
  contado.addEventListener('input', actualizar);
  actualizar();
  const cerrar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(cerrar, async () => {
    if (contado.value === '') { toast('Indique el efectivo contado', 'error'); return; }
    await api(`/cajas/${caja.id}/cerrar`, { method: 'POST', body: { monto_contado: contado.value, notas: notas.value.trim() || null } });
    recordar.set(null);
    m.cerrar();
    toast('Caja cerrada', 'ok');
    location.hash = `#/cajas/${caja.id}`;
  }) }, 'Cerrar caja');
  const m = modal(`Cerrar caja · ${nombreCaja(caja)}`, [
    tablaResumen(r),
    h('div', { class: 'campos' }, campo('Efectivo contado (₡)', contado), campo('Notas', notas)),
    h('p', {}, 'Diferencia: ', diferencia),
  ], { acciones: [cerrar] });
}

function tablaResumen(r) {
  const fila = (t, v, clase = '') => h('tr', { class: clase }, h('td', {}, t), h('td', { class: 'num' }, v));
  return h('table', { class: 'totales' }, h('tbody', {},
    fila('Fondo de apertura', dinero(r.monto_apertura)),
    Object.entries(r.por_medio).map(([k, v]) => fila(`Ventas · ${MEDIOS_PAGO[k] || k}`, dinero(v))),
    fila('Entradas de efectivo', dinero(r.entradas)),
    fila('Salidas de efectivo', dinero(-r.salidas)),
    fila('Efectivo esperado', dinero(r.efectivo_esperado), 'total'),
    r.monto_contado !== undefined ? fila('Efectivo contado', dinero(r.monto_contado)) : null,
    r.diferencia !== undefined ? fila(Number(r.diferencia) < 0 ? 'Faltante' : 'Sobrante', dinero(Math.abs(r.diferencia)), 'total') : null));
}

export async function vistaCajas(cont) {
  const lista = await api('/cajas?limit=200');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Cierres de caja'), h('a', { href: '#/punto-venta', class: 'boton primario' }, 'Punto de venta')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Caja', valor: nombreCaja },
      { titulo: 'Apertura', valor: (c) => [fecha(c.abierta_en), h('div', { class: 'suave' }, c.abierta_por || '')] },
      { titulo: 'Cierre', valor: (c) => (c.cerrada_en ? [fecha(c.cerrada_en), h('div', { class: 'suave' }, c.cerrada_por || '')] : h('span', { class: 'badge ACEPTADO' }, 'Abierta')) },
      { titulo: 'Ventas', num: true, valor: (c) => c.resumen.documentos },
      { titulo: 'Total', num: true, valor: (c) => dinero(c.resumen.total_ventas) },
      { titulo: 'Diferencia', num: true, valor: (c) => (c.resumen.diferencia === undefined ? '—'
        : h('span', { class: Number(c.resumen.diferencia) < 0 ? 'negativo' : '' }, dinero(c.resumen.diferencia))) },
    ], lista, (c) => { location.hash = `#/cajas/${c.id}`; })));
}

export async function vistaDetalleCaja(cont, id) {
  const [c, ventas] = await Promise.all([api(`/cajas/${id}`), api(`/cajas/${id}/ventas`)]);
  const r = c.resumen;
  vaciar(cont,
    h('div', { class: 'encabezado' },
      h('div', {}, h('a', { href: '#/cajas', class: 'no-imprimir' }, '← Cierres de caja'),
        h('h1', {}, `${c.estado === 'CERRADA' ? 'Cierre de caja' : 'Caja abierta'} · ${nombreCaja(c)}`)),
      h('div', { class: 'acciones no-imprimir' }, h('button', { type: 'button', onclick: () => window.print() }, 'Imprimir'))),
    c.estado === 'ABIERTA' ? aviso('La caja sigue abierta: los montos cambian con cada venta.', 'info') : null,
    r.rechazados.length ? aviso(`Comprobantes rechazados por Hacienda: ${r.rechazados.join(', ')}. Revíselos y vuelva a emitirlos.`, 'alerta') : null,
    h('div', { class: 'kpis' },
      kpi('Ventas', r.documentos), kpi('Total vendido', dinero(r.total_ventas)), kpi('IVA', dinero(r.impuesto)),
      r.diferencia !== undefined ? kpi(Number(r.diferencia) < 0 ? 'Faltante' : 'Sobrante', dinero(Math.abs(r.diferencia)), Number(r.diferencia) < 0 ? 'alerta' : '') : null),
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Arqueo'), tablaResumen(r),
        h('dl', { class: 'datos' },
          h('dt', {}, 'Apertura'), h('dd', {}, `${fecha(c.abierta_en)} · ${c.abierta_por || ''}`),
          h('dt', {}, 'Cierre'), h('dd', {}, c.cerrada_en ? `${fecha(c.cerrada_en)} · ${c.cerrada_por || ''}` : '—'),
          c.notas ? [h('dt', {}, 'Notas'), h('dd', {}, c.notas)] : null)),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Movimientos de efectivo'), tabla([
        { titulo: 'Hora', valor: (m) => fecha(m.fecha) },
        { titulo: 'Tipo', valor: (m) => (m.tipo === 'entrada' ? 'Entrada' : 'Salida') },
        { titulo: 'Motivo', valor: (m) => m.motivo },
        { titulo: 'Monto', num: true, valor: (m) => dinero(m.tipo === 'salida' ? -m.monto : m.monto) },
      ], c.movimientos))),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Ventas del turno'), tabla([
      { titulo: 'Hora', valor: (f) => fecha(f.fecha_emision) },
      { titulo: 'Tipo', valor: (f) => TIPOS[f.tipo_documento] },
      { titulo: 'Consecutivo', valor: (f) => f.numero_consecutivo },
      { titulo: 'Cliente', valor: (f) => f.receptor_nombre || 'Consumidor final' },
      { titulo: 'Total', num: true, valor: (f) => dinero(f.monto_total, f.moneda) },
      { titulo: 'Estado', valor: (f) => badge(f.estado) },
    ], ventas, (f) => { location.hash = `#/comprobantes/${f.factura_id}`; })));
}
