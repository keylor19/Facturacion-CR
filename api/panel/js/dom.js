// Utilidades de interfaz. Todo el texto se inserta con textContent (nunca
// innerHTML) para evitar inyección de HTML con datos de la API.

const PROPIEDADES = new Set(['value', 'checked', 'disabled', 'selected', 'hidden', 'multiple', 'required', 'readOnly']);

export function h(tag, attrs = {}, ...hijos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (PROPIEDADES.has(k)) el[k] = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  agregar(el, hijos);
  return el;
}

export function agregar(el, hijos) {
  for (const c of [hijos].flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function vaciar(el, ...hijos) {
  el.replaceChildren();
  return agregar(el, hijos);
}

// ---------- Formato ----------

const SIMBOLOS = { CRC: '₡', USD: '$', EUR: '€' };

export function dinero(valor, moneda = 'CRC') {
  const n = Number(valor || 0);
  const txt = n.toLocaleString('es-CR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${SIMBOLOS[moneda] || moneda + ' '}${txt}`;
}

export function fecha(iso, conHora = true) {
  if (!iso) return '';
  const d = new Date(iso);
  const opciones = { timeZone: 'America/Costa_Rica', year: 'numeric', month: '2-digit', day: '2-digit' };
  if (conHora) Object.assign(opciones, { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleString('es-CR', opciones);
}

export function badge(estado, texto) {
  const clase = estado || 'SIN_RESPONDER';
  return h('span', { class: `badge ${clase}` }, texto || ESTADOS[clase] || clase);
}

export const ESTADOS = {
  PENDIENTE: 'Pendiente',
  ENVIADO: 'Enviado',
  ACEPTADO: 'Aceptado',
  RECHAZADO: 'Rechazado',
  ERROR_COMUNICACION: 'Error de comunicación',
  CONTINGENCIA: 'Contingencia',
  SIN_RESPONDER: 'Sin responder',
};

export const TIPOS = {
  '01': 'Factura', '02': 'Nota de débito', '03': 'Nota de crédito', '04': 'Tiquete',
  '08': 'Factura de compra', '09': 'Factura de exportación', '10': 'Recibo de pago',
};

export function mesActual() {
  const partes = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Costa_Rica', year: 'numeric', month: '2-digit' })
    .formatToParts(new Date());
  return {
    anio: Number(partes.find((p) => p.type === 'year').value),
    mes: Number(partes.find((p) => p.type === 'month').value),
  };
}

export function selectorMes(valor, alCambiar) {
  const meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre'];
  const selMes = h('select', { 'aria-label': 'Mes' }, meses.map((m, i) => h('option', { value: String(i + 1), selected: i + 1 === valor.mes }, m)));
  const anioActual = mesActual().anio;
  const selAnio = h('select', { 'aria-label': 'Año' },
    Array.from({ length: 6 }, (_, i) => anioActual - i).map((a) => h('option', { value: String(a), selected: a === valor.anio }, a)));
  const cambio = () => alCambiar({ anio: Number(selAnio.value), mes: Number(selMes.value) });
  selMes.addEventListener('change', cambio);
  selAnio.addEventListener('change', cambio);
  return h('div', { class: 'acciones' }, selMes, selAnio);
}

// ---------- Avisos ----------

export function toast(mensaje, tipo = '') {
  const t = h('div', { class: `toast ${tipo}`, role: 'status' }, mensaje);
  document.getElementById('toasts').append(t);
  setTimeout(() => t.remove(), tipo === 'error' ? 8000 : 4000);
}

export function aviso(mensaje, tipo = 'info') {
  return h('div', { class: `aviso ${tipo}` }, mensaje);
}

// ---------- Modal ----------

export function modal(titulo, contenido, { acciones = [], ancho = false } = {}) {
  const cerrar = () => { fondo.remove(); document.removeEventListener('keydown', esc); };
  const esc = (e) => { if (e.key === 'Escape') cerrar(); };
  const pie = h('footer', {}, h('button', { type: 'button', onclick: cerrar }, 'Cerrar'), acciones);
  const caja = h('div', { class: `modal ${ancho ? 'ancho' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': titulo },
    h('header', {}, h('h2', {}, titulo), h('button', { type: 'button', 'aria-label': 'Cerrar', onclick: cerrar }, '✕')),
    h('div', { class: 'cuerpo' }, contenido),
    pie);
  const fondo = h('div', { class: 'fondo-modal', onclick: (e) => { if (e.target === fondo) cerrar(); } }, caja);
  document.body.append(fondo);
  document.addEventListener('keydown', esc);
  const primero = caja.querySelector('input, select, textarea');
  if (primero) primero.focus();
  return { cerrar, caja };
}

// Ejecuta una acción asíncrona deshabilitando el botón y mostrando errores.
export async function conBoton(boton, accion) {
  const texto = boton.textContent;
  boton.disabled = true;
  boton.textContent = 'Procesando…';
  try {
    return await accion();
  } catch (e) {
    toast(e.message, 'error');
    return undefined;
  } finally {
    boton.disabled = false;
    boton.textContent = texto;
  }
}

// Llama a consultar(cedula, vigente) cuando la identificación queda completa según
// el tipo (o al salir del campo), una vez por número. vigente() indica si el número
// sigue siendo el mismo al llegar la respuesta. Devuelve la función para forzar la consulta.
const LONGITUD_ID = { '01': [9, 10, 11, 12], '02': [10], '03': [11, 12], '04': [10] };
export function alCompletarCedula(numero, tipo, consultar) {
  let ultima = '';
  let espera;
  const actual = () => numero.value.replace(/\D/g, '');
  const lanzar = async (forzar = false) => {
    const cedula = actual();
    if (cedula.length < 9 || (!forzar && cedula === ultima)) return;
    ultima = cedula;
    try {
      await consultar(cedula, () => cedula === actual());
    } catch (e) {
      ultima = '';
      toast(e.message, 'error');
    }
  };
  numero.addEventListener('input', () => {
    clearTimeout(espera);
    if ((LONGITUD_ID[tipo.value] || [9, 10, 11, 12]).includes(actual().length)) espera = setTimeout(lanzar, 500);
  });
  numero.addEventListener('change', () => { clearTimeout(espera); lanzar(); });
  tipo.addEventListener('change', () => lanzar());
  return () => lanzar(true);
}

// Hacienda no respondió y se usaron los datos guardados en el sistema.
export function avisoRespaldo(datos) {
  const r = datos && datos._respaldo_local;
  if (!r) return null;
  return aviso(`Hacienda no responde en este momento: se muestran los datos guardados${r.actualizado_en ? ` el ${fecha(r.actualizado_en)}` : ' en el sistema'}.`, 'alerta');
}

// Aviso con el estado del contribuyente en Hacienda (inscrito, moroso, omiso).
export function avisoContribuyente(c, activas) {
  const s = c.situacion || {};
  const inscrito = (s.estado || '').toLowerCase() === 'inscrito';
  return [
    avisoRespaldo(c),
    inscrito
      ? aviso(`INSCRITO · ${c.nombre} · ${c.regimen?.descripcion || ''} · ${activas.length} actividad(es) activa(s)`, 'ok')
      : aviso(`NO INSCRITO como contribuyente (estado en Hacienda: ${s.estado || 'desconocido'}).`, 'error'),
    s.moroso === 'SI' || s.omiso === 'SI' ? aviso('Tiene obligaciones pendientes con Hacienda (moroso u omiso).', 'alerta') : null,
  ];
}

export const avisoNoInscrito = (cedula) => aviso(`NO INSCRITO: la identificación ${cedula} no aparece registrada en Hacienda.`, 'error');

export function campo(etiqueta, control) {
  return h('label', {}, etiqueta, control);
}

export function opciones(mapa, seleccionado, conVacio = false) {
  const lista = Object.entries(mapa).map(([v, t]) => h('option', { value: v, selected: v === seleccionado }, `${v} · ${t}`));
  return conVacio ? [h('option', { value: '' }, '—'), ...lista] : lista;
}

export function tabla(columnas, filas, alClic) {
  const cuerpo = filas.length
    ? filas.map((f) => h('tr', { class: alClic ? 'clic' : '', onclick: alClic ? () => alClic(f) : null },
      columnas.map((c) => h('td', { class: c.num ? 'num' : '' }, c.valor(f)))))
    : [h('tr', {}, h('td', { colspan: String(columnas.length), class: 'suave' }, 'Sin resultados'))];
  return h('div', { class: 'tabla' }, h('table', {},
    h('thead', {}, h('tr', {}, columnas.map((c) => h('th', { class: c.num ? 'num' : '' }, c.titulo)))),
    h('tbody', {}, cuerpo)));
}
