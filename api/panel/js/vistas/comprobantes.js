import { api, abrir, descargar } from '../api.js';
import {
  h, vaciar, dinero, fecha, badge, tabla, modal, conBoton, toast, campo, opciones, TIPOS, ESTADOS,
} from '../dom.js';
import { MEDIOS_PAGO, CONDICIONES_VENTA, SITUACIONES } from '../catalogos.js';

const POR_PAGINA = 50;
const ANULABLES = ['01', '02', '04', '09'];
const REENVIABLES = ['PENDIENTE', 'ERROR_COMUNICACION', 'CONTINGENCIA', 'ENVIADO'];

export async function vistaComprobantes(cont) {
  const f = {
    estado: h('select', {}, h('option', { value: '' }, 'Todos'), Object.entries(ESTADOS).filter(([k]) => k !== 'SIN_RESPONDER')
      .map(([k, v]) => h('option', { value: k }, v))),
    tipo: h('select', {}, h('option', { value: '' }, 'Todos'), Object.entries(TIPOS).map(([k, v]) => h('option', { value: k }, v))),
    desde: h('input', { type: 'date' }),
    hasta: h('input', { type: 'date' }),
    receptor: h('input', { type: 'search', placeholder: 'Identificación' }),
  };
  let offset = 0;
  const resultados = h('div');
  const paginacion = h('div', { class: 'acciones' });

  async function cargar() {
    const params = new URLSearchParams({ limit: String(POR_PAGINA), offset: String(offset) });
    if (f.estado.value) params.set('estado', f.estado.value);
    if (f.tipo.value) params.set('tipo_documento', f.tipo.value);
    if (f.desde.value) params.set('desde', f.desde.value);
    if (f.hasta.value) params.set('hasta', f.hasta.value);
    if (f.receptor.value.trim()) params.set('receptor', f.receptor.value.trim());
    vaciar(resultados, h('p', { class: 'cargando' }, 'Cargando…'));
    const lista = await api(`/facturas?${params}`);
    vaciar(resultados, tabla([
      { titulo: 'Fecha', valor: (x) => fecha(x.fecha_emision) },
      { titulo: 'Tipo', valor: (x) => TIPOS[x.tipo_documento] },
      { titulo: 'Consecutivo', valor: (x) => x.numero_consecutivo },
      { titulo: 'Cliente / proveedor', valor: (x) => x.receptor_nombre || 'Consumidor final' },
      { titulo: 'Impuesto', num: true, valor: (x) => dinero(x.monto_impuesto, x.moneda) },
      { titulo: 'Total', num: true, valor: (x) => dinero(x.monto_total, x.moneda) },
      { titulo: 'Estado', valor: (x) => badge(x.estado) },
    ], lista, (x) => { location.hash = `#/comprobantes/${x.factura_id}`; }));
    vaciar(paginacion,
      h('button', { type: 'button', disabled: offset === 0, onclick: () => { offset -= POR_PAGINA; cargar().catch(err); } }, '← Anterior'),
      h('span', { class: 'suave' }, `Página ${offset / POR_PAGINA + 1}`),
      h('button', { type: 'button', disabled: lista.length < POR_PAGINA, onclick: () => { offset += POR_PAGINA; cargar().catch(err); } }, 'Siguiente →'));
  }
  const buscar = () => { offset = 0; cargar().catch(err); };
  Object.values(f).forEach((c) => c.addEventListener('change', buscar));

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Comprobantes emitidos'),
      h('a', { href: '#/emitir', class: 'boton' }, '+ Nuevo comprobante')),
    h('section', { class: 'tarjeta' },
      h('div', { class: 'campos' },
        campo('Estado', f.estado), campo('Tipo', f.tipo), campo('Desde', f.desde), campo('Hasta', f.hasta),
        campo('Receptor', f.receptor))),
    h('section', { class: 'tarjeta' }, resultados, paginacion));
  await cargar();
}

function err(e) { toast(e.message, 'error'); }

export async function vistaDetalleComprobante(cont, id) {
  const [c, eventos] = await Promise.all([api(`/facturas/${id}`), api(`/facturas/${id}/eventos`)]);
  const refrescar = () => vistaDetalleComprobante(cont, id).catch(err);

  const acciones = [
    h('button', { type: 'button', onclick: (e) => conBoton(e.target, () => abrir(`/facturas/${id}/pdf`)) }, 'Ver PDF'),
    h('button', { type: 'button', onclick: (e) => conBoton(e.target, () => descargar(`/facturas/${id}/xml?tipo=firmado`, `${c.clave}.xml`)) }, 'XML firmado'),
  ];
  if (['ACEPTADO', 'RECHAZADO'].includes(c.estado)) {
    acciones.push(h('button', { type: 'button', onclick: (e) => conBoton(e.target, () => descargar(`/facturas/${id}/xml?tipo=respuesta`, `${c.clave}-respuesta.xml`)) }, 'Respuesta de Hacienda'));
  }
  if (c.estado !== 'ACEPTADO' && c.estado !== 'RECHAZADO') {
    acciones.push(h('button', { type: 'button', onclick: (e) => conBoton(e.target, async () => {
      await api(`/facturas/${id}/consultar`, { method: 'POST' });
      toast('Consulta a Hacienda encolada; actualice en unos segundos', 'ok');
    }) }, 'Consultar estado'));
  }
  if (REENVIABLES.includes(c.estado)) {
    acciones.push(h('button', { type: 'button', onclick: (e) => conBoton(e.target, async () => {
      const r = await api(`/facturas/${id}/reenviar`, { method: 'POST' });
      toast(r.message, 'ok');
    }) }, 'Reenviar'));
  }
  if (c.estado === 'ACEPTADO') {
    acciones.push(h('button', { type: 'button', onclick: () => dialogoCorreo(id) }, 'Enviar por correo'));
    if (ANULABLES.includes(c.tipo_documento)) {
      acciones.push(h('button', { type: 'button', class: 'peligro', onclick: () => dialogoAnular(id) }, 'Anular con nota de crédito'));
    }
  }

  const bloquePagos = h('div');
  if (c.tipo_documento === '01' && ['08', '10'].includes(c.condicion_venta)) {
    const pagos = await api(`/facturas/${id}/pagos`);
    vaciar(bloquePagos, h('section', { class: 'tarjeta' },
      h('div', { class: 'encabezado' }, h('h2', {}, 'Pagos (recibos electrónicos)'),
        c.estado === 'ACEPTADO' && Number(pagos.saldo_pendiente) > 0
          ? h('button', { type: 'button', class: 'primario', onclick: () => dialogoPago(id, c, pagos.saldo_pendiente, refrescar) }, 'Registrar pago')
          : null),
      h('p', {}, 'Saldo pendiente: ', h('strong', {}, dinero(pagos.saldo_pendiente, c.moneda))),
      tabla([
        { titulo: 'Fecha', valor: (r) => fecha(r.fecha_emision) },
        { titulo: 'Consecutivo', valor: (r) => r.numero_consecutivo },
        { titulo: 'Monto', num: true, valor: (r) => dinero(r.monto_total, r.moneda) },
        { titulo: 'Estado', valor: (r) => badge(r.estado) },
      ], pagos.recibos, (r) => { location.hash = `#/comprobantes/${r.factura_id}`; })));
  }

  const mensaje = c.mensaje_hacienda
    ? h('div', { class: `aviso ${c.estado === 'RECHAZADO' ? 'error' : c.estado === 'ACEPTADO' ? 'ok' : 'alerta'}` },
      h('strong', {}, 'Mensaje de Hacienda: '), c.mensaje_hacienda)
    : null;

  vaciar(cont,
    h('div', { class: 'encabezado' },
      h('div', {}, h('a', { href: '#/comprobantes' }, '← Comprobantes'),
        h('h1', {}, `${TIPOS[c.tipo_documento]} ${c.numero_consecutivo} `, badge(c.estado))),
      h('div', { class: 'acciones' }, acciones, h('button', { type: 'button', onclick: refrescar }, '↻ Actualizar'))),
    mensaje,
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Datos'),
        h('dl', { class: 'datos' },
          h('dt', {}, 'Clave'), h('dd', { class: 'mono' }, c.clave),
          h('dt', {}, 'Fecha'), h('dd', {}, fecha(c.fecha_emision)),
          h('dt', {}, c.tipo_documento === '08' ? 'Proveedor' : 'Cliente'), h('dd', {}, c.receptor_nombre || 'Consumidor final'),
          h('dt', {}, 'Identificación'), h('dd', {}, c.receptor_identificacion || '—'),
          h('dt', {}, 'Condición de venta'), h('dd', {}, CONDICIONES_VENTA[c.condicion_venta] || c.condicion_venta || '—'),
          h('dt', {}, 'Situación'), h('dd', {}, SITUACIONES[c.situacion] || c.situacion),
          h('dt', {}, 'Referencia externa'), h('dd', {}, c.referencia_externa || '—'),
          h('dt', {}, 'Correo enviado'), h('dd', {}, c.correo_enviado ? 'Sí' : 'No'),
          c.factura_origen_id ? [h('dt', {}, 'Documento de origen'), h('dd', {}, h('a', { href: `#/comprobantes/${c.factura_origen_id}` }, 'Ver'))] : null)),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Totales'),
        h('table', { class: 'totales' }, h('tbody', {},
          filaTotal('Total venta', c.total_venta, c.moneda),
          filaTotal('Descuentos', c.total_descuentos, c.moneda),
          filaTotal('Exento', c.total_exento, c.moneda),
          filaTotal('Exonerado', c.total_exonerado, c.moneda),
          Number(c.total_no_sujeto) ? filaTotal('No sujeto', c.total_no_sujeto, c.moneda) : null,
          filaTotal('Impuesto', c.monto_impuesto, c.moneda),
          Number(c.total_otros_cargos) ? filaTotal('Otros cargos', c.total_otros_cargos, c.moneda) : null,
          Number(c.total_iva_devuelto) ? filaTotal('IVA devuelto', -c.total_iva_devuelto, c.moneda) : null,
          h('tr', { class: 'total' }, h('td', {}, 'Total'), h('td', { class: 'num' }, dinero(c.monto_total, c.moneda))))),
        c.tipo_cambio && c.moneda !== 'CRC' ? h('p', { class: 'suave' }, `Tipo de cambio: ${c.tipo_cambio}`) : null)),
    bloquePagos,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Bitácora'),
      tabla([
        { titulo: 'Fecha', valor: (e) => fecha(e.fecha) },
        { titulo: 'Evento', valor: (e) => e.evento },
        { titulo: 'Detalle', valor: (e) => h('span', { class: 'mono' }, e.detalle || '') },
      ], eventos)));
}

function filaTotal(nombre, valor, moneda) {
  return h('tr', {}, h('td', {}, nombre), h('td', { class: 'num' }, dinero(valor, moneda)));
}

function dialogoAnular(id) {
  const razon = h('textarea', { rows: '3', maxlength: '180', required: true });
  const boton = h('button', { type: 'button', class: 'primario peligro', onclick: () => conBoton(boton, async () => {
    if (!razon.value.trim()) { toast('Indique la razón', 'error'); return; }
    const r = await api(`/facturas/${id}/anular`, { method: 'POST', body: { razon: razon.value.trim() } });
    m.cerrar();
    toast('Nota de crédito generada', 'ok');
    location.hash = `#/comprobantes/${r.factura_id}`;
  }) }, 'Emitir nota de crédito');
  const m = modal('Anular comprobante', [
    h('p', {}, 'Se emitirá una nota de crédito por el total del comprobante, referenciándolo con código 01 (anula documento).'),
    campo('Razón de la anulación', razon),
  ], { acciones: [boton] });
}

function dialogoPago(id, c, saldo, alTerminar) {
  const monto = h('input', { type: 'number', step: '0.01', min: '0.01', value: String(saldo) });
  const medio = h('select', {}, opciones(MEDIOS_PAGO, '04'));
  const boton = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(boton, async () => {
    await api(`/facturas/${id}/recibo-pago`, { method: 'POST', body: { monto: monto.value, medios_pago: [{ tipo: medio.value }] } });
    m.cerrar();
    toast('Recibo electrónico de pago generado', 'ok');
    alTerminar();
  }) }, 'Emitir recibo de pago');
  const m = modal('Registrar pago', [
    h('p', {}, `Saldo pendiente: ${dinero(saldo, c.moneda)}. Se emitirá un Recibo Electrónico de Pago con el IVA proporcional.`),
    h('div', { class: 'campos' }, campo(`Monto pagado (${c.moneda}, IVA incluido)`, monto), campo('Medio de pago', medio)),
  ], { acciones: [boton] });
}

function dialogoCorreo(id) {
  const destinos = h('input', { type: 'text', placeholder: 'correo1@x.com, correo2@y.com (vacío = correo del cliente)' });
  const boton = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(boton, async () => {
    const lista = destinos.value.split(',').map((s) => s.trim()).filter(Boolean);
    await api(`/facturas/${id}/correo`, { method: 'POST', body: { destinatarios: lista.length ? lista : null } });
    m.cerrar();
    toast('Envío de correo encolado', 'ok');
  }) }, 'Enviar');
  const m = modal('Enviar por correo', [campo('Destinatarios', destinos)], { acciones: [boton] });
}
