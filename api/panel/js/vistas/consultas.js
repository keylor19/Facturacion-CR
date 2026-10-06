import { api } from '../api.js';
import { h, vaciar, tabla, conBoton, campo, aviso, fecha, modal, avisoRespaldo } from '../dom.js';

export async function vistaConsultas(cont) {
  const panel = h('div');
  const pestanas = {
    'Contribuyentes': consultaContribuyente,
    'CABYS': consultaCabys,
    'Exoneraciones': consultaExoneracion,
    'Agropecuario / Pesca': consultaProductor,
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
    const cedula = id.replace(/\D/g, '');
    let c;
    try {
      c = await api(`/hacienda/contribuyentes/${encodeURIComponent(cedula)}`, { conEmisor: false });
    } catch (e) {
      if (e.status === 404) return aviso(`NO INSCRITO: la identificación ${cedula} no aparece registrada en Hacienda.`, 'error');
      throw e;
    }
    const s = c.situacion || {};
    const inscrito = (s.estado || '').toLowerCase() === 'inscrito';
    return [
      h('h2', {}, c.nombre),
      avisoRespaldo(c),
      inscrito
        ? aviso('INSCRITO en Hacienda: puede recibir facturas electrónicas a su nombre.', 'ok')
        : aviso(`NO INSCRITO como contribuyente (estado en Hacienda: ${s.estado || 'desconocido'}).`, 'error'),
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
        { titulo: 'CABYS', valor: (a) => h('button', { type: 'button', onclick: () => cabysDeActividad(a) }, 'Ver CABYS sugeridos') },
      ], c.actividades || []),
      c.actividades?.length ? null : h('p', { class: 'suave' }, 'No tiene actividades económicas registradas.'),
    ];
  });
}

// Hacienda no publica una relación oficial actividad → CABYS: se buscan en el
// catálogo CABYS los bienes y servicios cuya descripción coincide con la actividad.
async function cabysDeActividad(a) {
  const cuerpo = h('div', {}, h('p', { class: 'suave' }, 'Cargando…'));
  modal(`CABYS sugeridos · ${a.codigo}`, cuerpo, { ancho: true });
  try {
    const r = await api(`/hacienda/cabys?q=${encodeURIComponent(a.descripcion)}&top=30`, { conEmisor: false });
    const lista = Array.isArray(r) ? r : (r.cabys || []);
    vaciar(cuerpo,
      h('p', {}, a.descripcion),
      aviso('Sugerencias por coincidencia de texto: Hacienda no asocia códigos CABYS a las actividades. Confirme el código correcto para cada producto o servicio.', 'info'),
      lista.length
        ? tabla([
          { titulo: 'Código', valor: (x) => h('span', { class: 'mono' }, x.codigo) },
          { titulo: 'Descripción', valor: (x) => x.descripcion },
          { titulo: 'IVA', num: true, valor: (x) => (x.impuesto !== undefined ? `${x.impuesto}%` : '') },
        ], lista)
        : h('p', { class: 'suave' }, 'No se encontraron CABYS con esa descripción; búsquelos en la pestaña CABYS.'));
  } catch (e) {
    vaciar(cuerpo, aviso(e.message, 'error'));
  }
}

function consultaCabys() {
  return formulario('Buscar producto o servicio', 'Ej.: café, asesoría contable…', async (q) => {
    const r = await api(`/hacienda/cabys?q=${encodeURIComponent(q)}&top=50`, { conEmisor: false });
    const lista = Array.isArray(r) ? r : (r.cabys || []);
    return [
      h('p', { class: 'suave' }, `${r.total ?? lista.length} resultados`),
      r.parcial ? aviso('Ningún código tiene todas las palabras: se muestran los más parecidos.', 'info') : null,
      avisoRespaldo(r),
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

function consultaProductor() {
  return formulario('Identificación', 'Cédula sin guiones', async (id) => {
    const r = await api(`/hacienda/productores/${encodeURIComponent(id.replace(/\D/g, ''))}`, { conEmisor: false });
    return [
      r.registrado
        ? aviso('REGISTRADO como productor: puede comprar insumos agropecuarios o de pesca con la tarifa reducida.', 'ok')
        : aviso('NO aparece registrado en el MAG ni en INCOPESCA: no aplica la tarifa reducida de insumos agropecuarios o de pesca.', 'error'),
      registroProductor('Productor agropecuario (MAG)', r.agropecuario),
      registroProductor('Pesca y acuicultura (INCOPESCA)', r.pesca),
    ];
  });
}

function registroProductor(titulo, datos) {
  if (!datos) return [h('h3', {}, titulo), h('p', { class: 'suave' }, 'No registrado.')];
  const filas = Object.entries(datos).filter(([, v]) => v === null || typeof v !== 'object');
  return [h('h3', {}, titulo), h('dl', { class: 'datos' }, filas.map(([k, v]) => [h('dt', {}, k), h('dd', {}, String(v ?? ''))]))];
}

function consultaTipoCambio() {
  const resultado = h('div', { class: 'kpis' });
  const kpi = (etiqueta, valor) => h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, etiqueta), h('div', { class: 'valor' }, valor));
  api('/hacienda/tipo-cambio', { conEmisor: false })
    .then((tc) => vaciar(resultado,
      kpi('Dólar · venta', `₡${tc.USD.venta}`), kpi('Dólar · compra', `₡${tc.USD.compra}`),
      kpi('Euro', `₡${tc.EUR.colones}`), kpi('Euro en dólares', `$${tc.EUR.dolares}`)))
    .catch((e) => vaciar(resultado, aviso(e.message, 'error')));

  // Histórico del dólar
  const hoy = new Date().toISOString().slice(0, 10);
  const desde = h('input', { type: 'date', max: hoy });
  const hasta = h('input', { type: 'date', max: hoy, value: hoy });
  const historico = h('div');
  const boton = h('button', { type: 'submit', class: 'primario' }, 'Consultar');
  const form = h('form', { class: 'fila', onsubmit: (e) => {
    e.preventDefault();
    if (!desde.value) { vaciar(historico, aviso('Indique la fecha inicial', 'error')); return; }
    conBoton(boton, async () => {
      const r = await api(`/hacienda/tipo-cambio/USD/historico?desde=${desde.value}&hasta=${hasta.value}`, { conEmisor: false });
      const lista = Array.isArray(r) ? r : (r.historico || r.datos || []);
      vaciar(historico, lista.length
        ? tabla([
          { titulo: 'Fecha', valor: (x) => String(x.fecha || '').slice(0, 10) },
          { titulo: 'Compra', num: true, valor: (x) => x.compra ?? '' },
          { titulo: 'Venta', num: true, valor: (x) => x.venta ?? '' },
        ], lista)
        : h('pre', { class: 'mono bloque' }, JSON.stringify(r, null, 2)));
    });
  } }, campo('Desde', desde), campo('Hasta', hasta), boton);

  return [
    h('section', { class: 'tarjeta' }, h('p', { class: 'suave' }, `Tipo de cambio de referencia publicado por Hacienda · ${fecha(new Date().toISOString(), false)}`), resultado),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Histórico del dólar'), form, h('div', { class: 'cuerpo' }, historico)),
  ];
}
