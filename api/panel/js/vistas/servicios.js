// Mis servicios: cada servicio con su precio mensual, activarlo o cancelarlo, y las facturas mensuales.
// Para el dueño de la empresa y para el contador. El administrador supervisa en «Mensualidades».
import { api } from '../api.js';
import { h, vaciar, dinero, tabla, modal, conBoton, toast, campo, aviso, mesActual, selectorMes } from '../dom.js';

const fechaCorta = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('es-CR') : '');
const mesTexto = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('es-CR', { month: 'long', year: 'numeric' });
const ESTADO = { PENDIENTE: ['Por pagar', 'CONTINGENCIA'], REPORTADO: ['Pago reportado', 'ENVIADO'], PAGADO: ['Pagada', 'ACEPTADO'], ANULADO: ['Anulada', ''] };
const err = (e) => toast(e.message, 'error');

function estadoServicio(s) {
  if (!s.se_cobra) return h('span', { class: 'badge ACEPTADO' }, 'Incluido sin costo');
  if (s.suspendido) return h('span', { class: 'badge RECHAZADO' }, 'Suspendido por falta de pago');
  if (!s.contrato && s.pagado_hasta) {
    return h('span', { class: 'badge ACEPTADO' }, s.pagado_hasta === 'regalia' ? 'Activo (cortesía)' : `Activo, pagado hasta el ${fechaCorta(s.pagado_hasta)}`);
  }
  if (!s.contrato) return h('span', { class: 'badge' }, 'No activo');
  const gratis = s.contrato.gratis_hasta && s.contrato.gratis_hasta >= new Date().toLocaleDateString('en-CA');
  return h('span', { class: 'badge ACEPTADO' }, gratis ? `Prueba gratis hasta el ${fechaCorta(s.contrato.gratis_hasta)}` : `Activo desde el ${fechaCorta(s.contrato.desde)}`);
}

function dialogoPago(f, alTerminar) {
  const referencia = h('input', { type: 'text', maxlength: '100', placeholder: 'Número del comprobante del SINPE o la transferencia' });
  const enviar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(enviar, async () => {
    await api(`/servicios/facturas/${f.id}/pago`, { method: 'POST', conEmisor: false, body: { referencia: referencia.value.trim() } });
    m.cerrar();
    toast('Pago reportado. Sus servicios siguen activos mientras lo confirmamos.', 'ok');
    alTerminar();
  }) }, 'Reportar pago');
  const m = modal(`Pago de ${mesTexto(f.periodo)}`, [
    h('p', {}, `Total: ${dinero(f.total, f.moneda)} · vence el ${fechaCorta(f.vence)}`),
    campo('Referencia del pago', referencia),
  ], { acciones: [enviar] });
}

export async function vistaServicios(cont) {
  const refrescar = () => vistaServicios(cont).catch(err);
  const [r, facturas] = await Promise.all([api('/servicios', { conEmisor: true }), api('/servicios/facturas')]);
  const activar = (s) => h('button', { type: 'button', class: 'primario', onclick: (e) => conBoton(e.target, async () => {
    const prueba = r.prueba_dias ? ` Si es la primera vez, los primeros ${r.prueba_dias} días son gratis.` : '';
    if (!window.confirm(`Activar «${s.nombre}» por ${dinero(s.precio, s.moneda)} al mes${r.precio_incluye_iva ? ' (IVA incluido)' : ' más IVA'}.`
      + ` Se cobra en su factura de cada mes, proporcional a los días que lo use.${prueba}`)) return;
    await api(`/servicios/${s.servicio}/contratar`, { method: 'POST' });
    toast(`«${s.nombre}» activado`, 'ok');
    refrescar();
  }) }, `Activar por ${dinero(s.precio, s.moneda)} al mes`);
  const cancelar = (s) => h('button', { type: 'button', class: 'chico peligro', onclick: (e) => conBoton(e.target, async () => {
    if (!window.confirm(`¿Dejar de usar «${s.nombre}» desde hoy? Este mes se cobra solo por los días que lo usó.`)) return;
    await api(`/servicios/${s.servicio}/cancelar`, { method: 'POST' });
    refrescar();
  }) }, 'Cancelar');
  const debe = facturas.filter((f) => ['PENDIENTE', 'REPORTADO'].includes(f.estado));

  vaciar(cont,
    h('h1', {}, 'Mis servicios'),
    h('p', { class: 'suave' }, `Cada servicio se cobra por aparte. Los documentos se compran por paquete en Mi saldo; las mensualidades `
      + `se cobran en una factura el día 1 de cada mes (proporcional a los días usados) y se pagan en ${r.dias_para_pagar} días.`),
    debe.some((f) => f.vencido) ? aviso('Tiene una factura vencida: sus mensualidades están suspendidas hasta que la pague y la reporte.', 'error') : null,
    h('div', { class: 'tarjetas-servicio' }, r.servicios.map((s) => h('section', { class: 'tarjeta' },
      h('h2', {}, s.nombre),
      h('p', { class: 'suave' }, s.detalle),
      h('p', {}, s.precio ? h('strong', {}, `${dinero(s.precio, s.moneda)} al mes`) : 'Sin costo'),
      estadoServicio(s),
      h('div', { class: 'acciones' }, s.se_cobra && !s.contrato && !s.pagado_hasta ? activar(s) : null, s.contrato && !s.contrato.hasta ? cancelar(s) : null)))),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Facturas mensuales'),
      facturas.length ? tabla([
        { titulo: 'Mes', valor: (f) => mesTexto(f.periodo) },
        { titulo: 'Detalle', valor: (f) => f.lineas.map((ln) => h('div', {}, `${ln.concepto}: ${dinero(ln.monto, ln.moneda)}`)) },
        { titulo: 'Total', num: true, valor: (f) => h('strong', {}, dinero(f.total, f.moneda)) },
        { titulo: 'Vence', valor: (f) => fechaCorta(f.vence) },
        { titulo: 'Estado', valor: (f) => h('span', { class: `badge ${f.vencido ? 'RECHAZADO' : ESTADO[f.estado][1]}` }, f.vencido ? 'Vencida' : ESTADO[f.estado][0]) },
        { titulo: '', valor: (f) => (f.estado === 'PENDIENTE' ? h('button', { type: 'button', class: 'chico primario', onclick: () => dialogoPago(f, refrescar) }, 'Reportar pago')
          : f.factura_id ? h('span', { class: 'suave' }, 'Factura electrónica enviada a su correo') : null) },
      ], facturas) : h('p', { class: 'suave' }, 'Todavía no tiene facturas mensuales.'),
      r.instrucciones_pago ? h('div', { class: 'aviso info instrucciones-pago' }, h('strong', {}, 'Cómo pagar: '), r.instrucciones_pago) : null));
}

// --- Administrador: supervisar mensualidades y confirmar pagos ----------------------------------

export async function vistaMensualidades(cont, estado = 'REPORTADO') {
  const refrescar = () => vistaMensualidades(cont, estado).catch(err);
  const [lista, estimado] = await Promise.all([
    api(`/admin/mensualidades${estado ? `?estado=${estado}` : ''}`, { conEmisor: false }),
    api('/admin/mensualidades/estimado', { conEmisor: false }),
  ]);
  const filtro = h('select', { onchange: (e) => vistaMensualidades(cont, e.target.value).catch(err) },
    [['REPORTADO', 'Pago reportado (por confirmar)'], ['PENDIENTE', 'Por pagar'], ['PAGADO', 'Pagadas'], ['', 'Todas']]
      .map(([v, t]) => h('option', { value: v, selected: v === estado }, t)));
  let periodo = mesActual();
  const generar = h('button', { type: 'button', onclick: () => conBoton(generar, async () => {
    const r = await api('/admin/mensualidades/generar', { method: 'POST', conEmisor: false, body: { anio: periodo.anio, mes: periodo.mes } });
    toast(`${r.creadas} factura(s) generadas`, 'ok');
    refrescar();
  }) }, 'Generar ese mes');
  const confirmar = (f) => h('button', { type: 'button', class: 'chico primario', onclick: (e) => conBoton(e.target, async () => {
    if (!window.confirm(`¿Confirmar que llegó el pago de ${f.cliente} por ${dinero(f.total, f.moneda)}?`)) return;
    await api(`/admin/mensualidades/${f.id}/confirmar`, { method: 'POST', conEmisor: false, body: {} });
    refrescar();
  }) }, 'Confirmar pago');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Mensualidades'), filtro),
    h('p', { class: 'suave' }, 'El día 1 el sistema emite a cada cliente la factura de sus servicios del mes anterior y le avisa. '
      + 'Usted solo confirma los pagos que los clientes reportan. Si una factura vence sin pagar, sus mensualidades se suspenden solas.'),
    h('div', { class: 'kpis' },
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Clientes con mensualidad este mes'), h('div', { class: 'valor' }, estimado.clientes)),
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Estimado a facturar este mes'), h('div', { class: 'valor' }, dinero(estimado.estimado_mes)))),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Cliente', valor: (f) => f.cliente },
      { titulo: 'Mes', valor: (f) => mesTexto(f.periodo) },
      { titulo: 'Total', num: true, valor: (f) => dinero(f.total, f.moneda) },
      { titulo: 'Vence', valor: (f) => fechaCorta(f.vence) },
      { titulo: 'Estado', valor: (f) => [h('span', { class: `badge ${f.vencido ? 'RECHAZADO' : ESTADO[f.estado][1]}` }, f.vencido ? 'Vencida' : ESTADO[f.estado][0]),
        f.referencia_pago ? h('div', { class: 'suave' }, `Ref. ${f.referencia_pago}`) : null,
        f.comprobante_error ? h('div', { class: 'suave' }, `Sin factura electrónica: ${f.comprobante_error}`) : null] },
      { titulo: '', valor: (f) => (['PENDIENTE', 'REPORTADO'].includes(f.estado) ? confirmar(f) : null) },
    ], lista)),
    h('details', { class: 'tarjeta opcional' }, h('summary', {}, 'Generar a mano las facturas de un mes (si el sistema no lo hizo)'),
      h('div', { class: 'fila' }, selectorMes(periodo, (p) => { periodo = p; }), generar)));
}
