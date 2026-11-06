// Consultas a Hacienda: ficha completa por cédula (situación, actividades, exoneraciones, MAG/INCOPESCA),
// CABYS, exoneraciones por número de autorización, productores y tipo de cambio.
import { api } from '../api.js';
import { h, vaciar, tabla, conBoton, campo, aviso, fecha, modal, avisoRespaldo, limpiarIdentificacion } from '../dom.js';

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

// Ficha completa de una cédula: situación tributaria, actividades, registro como
// productor (MAG / INCOPESCA) y exoneraciones. Hacienda no busca exoneraciones por
// cédula: se listan las ya consultadas y se puede verificar un número nuevo.
function consultaContribuyente() {
  return formulario('Identificación', 'Cédula física o jurídica, sin guiones', async (id) => {
    const cedula = limpiarIdentificacion(id);
    const f = await api(`/hacienda/ficha/${encodeURIComponent(cedula)}`, { conEmisor: false });
    const c = f.contribuyente;
    const s = c?.situacion || {};
    const contenedor = h('div');
    vaciar(contenedor,
      h('h2', {}, c?.nombre || `Identificación ${cedula}`),
      c ? avisoRespaldo(c) : null,
      f.errores.contribuyente ? aviso(`No se pudo consultar la situación tributaria: ${f.errores.contribuyente}`, 'error')
        : !c ? aviso(`La identificación ${cedula} no aparece en Hacienda como contribuyente. Se le puede facturar igual con su cédula.`, 'info')
          : f.inscrito ? aviso('INSCRITO en Hacienda: puede recibir facturas electrónicas a su nombre.', 'ok')
            : aviso(`No está inscrito como contribuyente (estado en Hacienda: ${s.estado || 'desconocido'}). Se le puede facturar igual con su cédula.`, 'info'),
      s.moroso === 'SI' || s.omiso === 'SI' ? aviso('Tiene obligaciones pendientes con Hacienda (moroso u omiso).', 'alerta') : null,
      c ? h('dl', { class: 'datos' },
        h('dt', {}, 'Tipo de identificación'), h('dd', {}, TIPO_ID[c.tipoIdentificacion] || c.tipoIdentificacion || '—'),
        h('dt', {}, 'Régimen'), h('dd', {}, c.regimen?.descripcion || '—'),
        h('dt', {}, 'Estado'), h('dd', {}, s.estado || '—'),
        h('dt', {}, 'Moroso'), h('dd', {}, s.moroso || '—'),
        h('dt', {}, 'Omiso'), h('dd', {}, s.omiso || '—'),
        h('dt', {}, 'Administración'), h('dd', {}, s.administracionTributaria || '—')) : null,
      c ? seccionActividades(c.actividades || []) : null,
      seccionExoneraciones(cedula, f.exoneraciones),
      seccionProductor(f.productor, f.errores.productor));
    return contenedor;
  });
}

const TIPO_ID = { '01': 'Cédula física', '02': 'Cédula jurídica', '03': 'DIMEX', '04': 'NITE' };

function seccionActividades(actividades) {
  return [
    h('h3', {}, 'Actividades económicas'),
    actividades.length
      ? tabla([
        { titulo: 'Código', valor: (a) => a.codigo },
        { titulo: 'Descripción', valor: (a) => a.descripcion },
        { titulo: 'Tipo', valor: (a) => (a.tipo === 'P' ? 'Principal' : a.tipo === 'S' ? 'Secundaria' : a.tipo) },
        { titulo: 'Estado', valor: (a) => (a.estado === 'A' ? 'Activa' : a.estado) },
        { titulo: 'CABYS', valor: (a) => h('button', { type: 'button', onclick: () => cabysDeActividad(a) }, 'Ver CABYS sugeridos') },
      ], actividades)
      : h('p', { class: 'suave' }, 'No tiene actividades económicas registradas.'),
  ];
}

function seccionExoneraciones(cedula, lista) {
  const numero = h('input', { type: 'search', placeholder: 'AL-00000000-24' });
  const resultado = h('div');
  const boton = h('button', { type: 'submit' }, 'Verificar');
  const form = h('form', { class: 'fila', onsubmit: (e) => {
    e.preventDefault();
    e.stopPropagation();
    conBoton(boton, async () => {
      vaciar(resultado);
      let ex;
      try {
        ex = await api(`/hacienda/exoneraciones/${encodeURIComponent(numero.value.trim())}`, { conEmisor: false });
      } catch (err) {
        vaciar(resultado, aviso(err.status === 404 ? 'Ese número de autorización no existe en Hacienda.' : err.message, 'error'));
        return;
      }
      if (String(ex.identificacion) !== cedula) {
        vaciar(resultado, aviso(`La exoneración ${ex.numeroDocumento} es de otra identificación (${ex.identificacion}): no se puede usar con esta cédula.`, 'error'));
        return;
      }
      const vence = String(ex.fechaVencimiento || '').slice(0, 10);
      const vencida = vence && vence < new Date().toISOString().slice(0, 10);
      vaciar(resultado, aviso(`${ex.numeroDocumento}: ${ex.porcentajeExoneracion ?? '?'}% · ${ex.nombreInstitucion || ''} · `
        + (vencida ? `VENCIDA el ${vence}` : `vigente hasta ${vence || 'sin vencimiento'}`)
        + ` · ${(ex.cabys || []).length || 'todos los'} CABYS`, vencida ? 'error' : 'ok'));
    });
  } }, campo('Verificar un número de autorización', numero), boton);
  return [
    h('h3', {}, 'Exoneraciones'),
    lista.length
      ? tabla([
        { titulo: 'Autorización', valor: (x) => h('span', { class: 'mono' }, x.autorizacion) },
        { titulo: 'Porcentaje', num: true, valor: (x) => (x.porcentaje != null ? `${x.porcentaje}%` : '—') },
        { titulo: 'Tipo', valor: (x) => x.tipo_documento || '—' },
        { titulo: 'Institución', valor: (x) => x.institucion || '—' },
        { titulo: 'Vence', valor: (x) => (x.vence ? fecha(x.vence, false) : 'No vence') },
        { titulo: 'Estado', valor: (x) => h('span', { class: `badge ${x.vigente ? 'ACEPTADO' : 'RECHAZADO'}` }, x.vigente ? 'Vigente' : 'Vencida') },
        { titulo: 'CABYS', num: true, valor: (x) => (x.cantidad_cabys ? x.cantidad_cabys.toLocaleString('es-CR') : 'Todos') },
      ], lista)
      : h('p', { class: 'suave' }, 'Su empresa no ha usado exoneraciones con esta cédula.'),
    h('p', { class: 'suave' }, 'Hacienda solo permite consultar exoneraciones por su número de autorización. La lista muestra las que su '
      + 'empresa ya aplicó a este cliente; para una nueva, pida el número al cliente y verifíquelo aquí.'),
    form, resultado,
  ];
}

function seccionProductor(r, error) {
  if (error) return [h('h3', {}, 'Productor agropecuario o de pesca'), aviso(`No se pudo consultar: ${error}`, 'error')];
  return [
    h('h3', {}, 'Productor agropecuario o de pesca'),
    r?.registrado
      ? aviso('REGISTRADO como productor: puede comprar insumos agropecuarios o de pesca con la tarifa reducida.', 'ok')
      : h('p', { class: 'suave' }, 'No aparece registrado en el MAG ni en INCOPESCA.'),
    r?.agropecuario ? registroProductor('Productor agropecuario (MAG)', r.agropecuario) : null,
    r?.pesca ? registroProductor('Pesca y acuicultura (INCOPESCA)', r.pesca) : null,
  ];
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
    const r = await api(`/hacienda/productores/${encodeURIComponent(limpiarIdentificacion(id))}`, { conEmisor: false });
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
