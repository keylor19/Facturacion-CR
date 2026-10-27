// Proformas (cotizaciones con PDF) y documentos preliminares (borradores sin emitir).
import { abrir, api } from '../api.js';
import { h, vaciar, dinero, fecha, tabla, conBoton, toast } from '../dom.js';
import { TIPOS_DOCUMENTO } from '../catalogos.js';

const ESTADOS = {
  ABIERTO: ['ACEPTADO', 'Vigente'], VENCIDO: ['CONTINGENCIA', 'Vencida'],
  FACTURADO: ['prod', 'Facturada'], ANULADO: ['RECHAZADO', 'Anulada'],
};
const numero = (b) => `PF-${String(b.numero).padStart(6, '0')}`;

function lista(cont, { clase, titulo, nuevo, ayuda, columnas, acciones, filtroEstado }) {
  const q = h('input', { type: 'search', placeholder: clase === 'proforma' ? 'Cliente, identificación o número' : 'Cliente o identificación' });
  const estado = filtroEstado ? h('select', { 'aria-label': 'Estado' },
    [['', 'Todas'], ['ABIERTO', 'Vigentes'], ['VENCIDO', 'Vencidas'], ['FACTURADO', 'Facturadas'], ['ANULADO', 'Anuladas']]
      .map(([v, t]) => h('option', { value: v, selected: v === 'ABIERTO' }, t))) : null;
  const resultados = h('div');

  async function cargar() {
    const params = new URLSearchParams({ clase });
    if (q.value.trim()) params.set('q', q.value.trim());
    if (estado?.value) params.set('estado', estado.value);
    if (!filtroEstado) params.set('estado', 'ABIERTO');
    const datos = await api(`/borradores?${params}`);
    vaciar(resultados, tabla([...columnas, { titulo: '', valor: (b) => acciones(b, recargar) }], datos,
      (b) => { location.hash = b.estado === 'FACTURADO' ? `#/comprobantes/${b.factura_id}` : `#/emitir/borrador/${b.id}`; }));
  }
  const recargar = () => cargar().catch((e) => toast(e.message, 'error'));
  estado?.addEventListener('change', recargar);

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, titulo), h('a', { href: nuevo[0], class: 'boton primario' }, nuevo[1])),
    h('form', { class: 'fila', onsubmit: (e) => { e.preventDefault(); recargar(); } }, q, estado, h('button', { type: 'submit' }, 'Buscar')),
    h('section', { class: 'tarjeta' }, resultados),
    h('p', { class: 'suave' }, ayuda));
  return cargar();
}

const quitar = (b, texto, confirmar, alTerminar) => h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => {
  ev.stopPropagation();
  conBoton(ev.target, async () => {
    if (!window.confirm(confirmar)) return;
    await api(`/borradores/${b.id}`, { method: 'DELETE' });
    alTerminar();
  });
} }, texto);

export function vistaProformas(cont) {
  return lista(cont, {
    clase: 'proforma',
    titulo: 'Documentos proforma',
    nuevo: ['#/proforma/nueva', '+ Nueva proforma'],
    filtroEstado: true,
    ayuda: 'La proforma es una cotización sin valor fiscal: no se envía a Hacienda ni consume documentos. '
      + 'Cuando el cliente confirme, ábrala y use "Convertir en comprobante y enviar".',
    columnas: [
      { titulo: 'Número', valor: (b) => h('span', { class: 'mono' }, numero(b)) },
      { titulo: 'Fecha', valor: (b) => fecha(b.created_at, false) },
      { titulo: 'Cliente', valor: (b) => [b.receptor_nombre || 'Sin cliente', h('div', { class: 'suave' }, b.receptor_identificacion || '')] },
      { titulo: 'Vence', valor: (b) => (b.vence ? fecha(`${b.vence}T12:00:00`, false) : '') },
      { titulo: 'Total', num: true, valor: (b) => (b.monto_total === null ? '—' : dinero(b.monto_total, b.moneda)) },
      { titulo: 'Estado', valor: (b) => h('span', { class: `badge ${ESTADOS[b.estado][0]}` }, ESTADOS[b.estado][1]) },
    ],
    acciones: (b, recargar) => h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'chico', onclick: (ev) => { ev.stopPropagation(); conBoton(ev.target, () => abrir(`/borradores/${b.id}/pdf`)); } }, 'PDF'),
      ['ABIERTO', 'VENCIDO'].includes(b.estado) ? quitar(b, 'Anular', `¿Anular la proforma ${numero(b)}? Conserva su número.`, recargar) : null),
  });
}

export function vistaPreliminares(cont) {
  return lista(cont, {
    clase: 'preliminar',
    titulo: 'Documentos preliminares',
    nuevo: ['#/emitir/01', '+ Nuevo comprobante'],
    filtroEstado: false,
    ayuda: 'Comprobantes guardados para terminar después ("Guardar como preliminar" en el formulario). '
      + 'Ábralo, complete lo que falte y use "Firmar y enviar".',
    columnas: [
      { titulo: 'Guardado', valor: (b) => fecha(b.updated_at) },
      { titulo: 'Tipo', valor: (b) => TIPOS_DOCUMENTO[b.tipo_documento] || b.tipo_documento },
      { titulo: 'Cliente', valor: (b) => b.receptor_nombre || h('span', { class: 'suave' }, 'Sin cliente') },
      { titulo: 'Total', num: true, valor: (b) => (b.monto_total === null ? '—' : dinero(b.monto_total, b.moneda)) },
      { titulo: 'Listo para emitir', valor: (b) => (b.errores
        ? h('span', { class: 'badge CONTINGENCIA', title: b.errores }, 'Faltan datos')
        : h('span', { class: 'badge ACEPTADO' }, 'Sí')) },
      { titulo: 'Usuario', valor: (b) => b.creado_por || '' },
    ],
    acciones: (b, recargar) => quitar(b, 'Eliminar', '¿Eliminar este documento preliminar?', recargar),
  });
}
