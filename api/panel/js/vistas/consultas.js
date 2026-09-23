import { api } from '../api.js';
import { h, vaciar, tabla, conBoton, campo, aviso, fecha } from '../dom.js';

export async function vistaConsultas(cont) {
  const panel = h('div');
  const pestanas = {
    'Contribuyentes': consultaContribuyente,
    'CABYS': consultaCabys,
    'Exoneraciones': consultaExoneracion,
    'Tipo de cambio': consultaTipoCambio,
  };
  const botones = Object.keys(pestanas).map((nombre) => h('button', {
    type: 'button',
    onclick: (e) => {
      botones.forEach((b) => b.classList.remove('activo'));
      e.target.classList.add('activo');
      vaciar(panel, pestanas[nombre]());
    },
  }, nombre));
  botones[0].classList.add('activo');
  vaciar(cont, h('h1', {}, 'Consultas a Hacienda'), h('div', { class: 'pestanas' }, botones), panel);
  vaciar(panel, consultaContribuyente());
}

function formulario(etiqueta, placeholder, alBuscar) {
  const entrada = h('input', { type: 'search', placeholder });
  const resultado = h('div');
  const boton = h('button', { type: 'submit', class: 'primario' }, 'Consultar');
  const form = h('form', { class: 'fila', onsubmit: (e) => {
    e.preventDefault();
    conBoton(boton, async () => vaciar(resultado, await alBuscar(entrada.value.trim())));
  } }, campo(etiqueta, entrada), boton);
  return h('section', { class: 'tarjeta' }, form, h('div', { class: 'cuerpo' }, resultado));
}

function consultaContribuyente() {
  return formulario('Identificación', 'Cédula sin guiones', async (id) => {
    const c = await api(`/hacienda/contribuyentes/${encodeURIComponent(id.replace(/\D/g, ''))}`, { conEmisor: false });
    const s = c.situacion || {};
    return [
      h('h2', {}, c.nombre),
      h('dl', { class: 'datos' },
        h('dt', {}, 'Tipo de identificación'), h('dd', {}, c.tipoIdentificacion),
        h('dt', {}, 'Régimen'), h('dd', {}, c.regimen?.descripcion || '—'),
        h('dt', {}, 'Estado'), h('dd', {}, s.estado || '—'),
        h('dt', {}, 'Moroso'), h('dd', {}, s.moroso || '—'),
        h('dt', {}, 'Omiso'), h('dd', {}, s.omiso || '—'),
        h('dt', {}, 'Administración'), h('dd', {}, s.administracionTributaria || '—')),
      s.moroso === 'SI' || s.omiso === 'SI' ? aviso('El contribuyente tiene obligaciones pendientes con Hacienda.', 'alerta') : null,
      h('h3', {}, 'Actividades económicas'),
      tabla([
        { titulo: 'Código', valor: (a) => a.codigo },
        { titulo: 'Descripción', valor: (a) => a.descripcion },
        { titulo: 'Tipo', valor: (a) => (a.tipo === 'P' ? 'Principal' : a.tipo === 'S' ? 'Secundaria' : a.tipo) },
        { titulo: 'Estado', valor: (a) => (a.estado === 'A' ? 'Activa' : a.estado) },
      ], c.actividades || []),
    ];
  });
}

function consultaCabys() {
  return formulario('Buscar producto o servicio', 'Ej.: café, asesoría contable…', async (q) => {
    const r = await api(`/hacienda/cabys?q=${encodeURIComponent(q)}&top=50`, { conEmisor: false });
    const lista = Array.isArray(r) ? r : (r.cabys || []);
    return [
      h('p', { class: 'suave' }, `${r.total ?? lista.length} resultados`),
      tabla([
        { titulo: 'Código', valor: (x) => h('span', { class: 'mono' }, x.codigo) },
        { titulo: 'Descripción', valor: (x) => x.descripcion },
        { titulo: 'IVA', num: true, valor: (x) => (x.impuesto !== undefined ? `${x.impuesto}%` : '') },
      ], lista),
    ];
  });
}

function consultaExoneracion() {
  return formulario('Número de autorización', 'AL-00000000-24', async (aut) => {
    const ex = await api(`/hacienda/exoneraciones/${encodeURIComponent(aut)}`, { conEmisor: false });
    const filas = Object.entries(ex).filter(([, v]) => typeof v !== 'object' || v === null);
    return [
      h('dl', { class: 'datos' }, filas.map(([k, v]) => [h('dt', {}, k), h('dd', {}, String(v ?? ''))]),
        ex.tipoDocumento ? [h('dt', {}, 'tipoDocumento'), h('dd', {}, `${ex.tipoDocumento.codigo} · ${ex.tipoDocumento.descripcion}`)] : null),
      Array.isArray(ex.cabys) && ex.cabys.length ? [h('h3', {}, 'CABYS autorizados'), h('p', { class: 'mono' }, ex.cabys.join(', '))] : null,
    ];
  });
}

function consultaTipoCambio() {
  const resultado = h('div', { class: 'kpis' });
  const cargar = async () => {
    const [usd, eur] = await Promise.all([
      api('/hacienda/tipo-cambio/USD', { conEmisor: false }), api('/hacienda/tipo-cambio/EUR', { conEmisor: false }),
    ]);
    vaciar(resultado,
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Dólar (venta)'), h('div', { class: 'valor' }, `₡${usd.tipo_cambio}`)),
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Euro'), h('div', { class: 'valor' }, `₡${eur.tipo_cambio}`)));
  };
  cargar().catch((e) => vaciar(resultado, aviso(e.message, 'error')));
  return h('section', { class: 'tarjeta' }, h('p', { class: 'suave' }, `Tipo de cambio de referencia publicado por Hacienda · ${fecha(new Date().toISOString(), false)}`), resultado);
}
