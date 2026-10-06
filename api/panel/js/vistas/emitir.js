import { api } from '../api.js';
import { h, vaciar, dinero, modal, conBoton, toast, campo, opciones, tabla, aviso, alCompletarCedula, avisoContribuyente, avisoNoInscrito, avisoRespaldo } from '../dom.js';
import {
  TIPOS_DOCUMENTO, TIPOS_IDENTIFICACION, CONDICIONES_VENTA, MEDIOS_PAGO, TARIFAS_IVA, DESCUENTOS, UNIDADES,
  INSTITUCIONES_EXONERACION, TIPOS_DOC_REFERENCIA, CODIGOS_REFERENCIA, SITUACIONES,
} from '../catalogos.js';

const TARIFA_POR_PORCENTAJE = { 13: '08', 8: '07', 4: '04', 2: '03', 1: '02', 0.5: '09' };
const tarifasOpciones = (sel) => Object.entries(TARIFAS_IVA).map(([k, [t]]) => h('option', { value: k, selected: k === sel }, t));

// ---------------------------------------------------------------------------
// Persona (receptor o proveedor) con búsqueda en Hacienda
// ---------------------------------------------------------------------------
function dialogoElegirCliente(alElegir) {
  const q = h('input', { type: 'search', placeholder: 'Nombre o identificación' });
  const resultados = h('div');
  const buscar = async () => {
    const lista = await api(`/catalogo/clientes?limite=50${q.value.trim() ? `&q=${encodeURIComponent(q.value.trim())}` : ''}`);
    vaciar(resultados, lista.length ? tabla([
      { titulo: 'Nombre', valor: (c) => c.nombre },
      { titulo: 'Identificación', valor: (c) => h('span', { class: 'mono' }, c.numero_identificacion) },
      { titulo: 'Correo', valor: (c) => c.correo || '' },
    ], lista, (c) => { alElegir(c); m.cerrar(); })
      : aviso('No hay clientes que coincidan. Puede registrarlos en Clientes o marcar "Guardar en mis clientes frecuentes" al facturar.', 'info'));
  };
  const form = h('form', { class: 'fila', onsubmit: (e) => { e.preventDefault(); buscar().catch((err) => toast(err.message, 'error')); } },
    q, h('button', { type: 'submit', class: 'primario' }, 'Buscar'));
  const m = modal('Elegir cliente', [form, resultados], { ancho: true });
  buscar().catch((err) => toast(err.message, 'error'));
}

function dialogoElegirProducto(alElegir) {
  const q = h('input', { type: 'search', placeholder: 'Código, descripción o CABYS' });
  const resultados = h('div');
  const cant = (v) => Number(v).toLocaleString('es-CR', { maximumFractionDigits: 3 });
  const buscar = async () => {
    const lista = await api(`/catalogo/productos?limite=100${q.value.trim() ? `&q=${encodeURIComponent(q.value.trim())}` : ''}`);
    vaciar(resultados, lista.length ? tabla([
      { titulo: 'Código', valor: (p) => h('span', { class: 'mono' }, p.codigo) },
      { titulo: 'Descripción', valor: (p) => p.descripcion },
      { titulo: 'Precio sin IVA', num: true, valor: (p) => dinero(p.precio_unitario, 'CRC') },
      { titulo: 'Existencia', num: true, valor: (p) => (p.controla_inventario
        ? h('span', { class: `badge ${Number(p.existencia) <= 0 ? 'RECHAZADO' : p.bajo_minimo ? 'CONTINGENCIA' : 'ACEPTADO'}` }, cant(p.existencia))
        : '—') },
    ], lista, (p) => { alElegir(p); m.cerrar(); })
      : aviso('No hay productos que coincidan. Regístrelos en Productos.', 'info'));
  };
  const form = h('form', { class: 'fila', onsubmit: (e) => { e.preventDefault(); buscar().catch((err) => toast(err.message, 'error')); } },
    q, h('button', { type: 'submit', class: 'primario' }, 'Buscar'));
  const m = modal('Agregar del catálogo', [form, resultados], { ancho: true });
  buscar().catch((err) => toast(err.message, 'error'));
}

function bloquePersona(titulo, { conUbicacion = false, conCatalogo = false } = {}) {
  const tipo = h('select', {}, opciones(TIPOS_IDENTIFICACION, '01'));
  const numero = h('input', { type: 'text', maxlength: '20', placeholder: 'Sin guiones' });
  const nombre = h('input', { type: 'text', maxlength: '100' });
  const correo = h('input', { type: 'email' });
  const actividad = h('select', {}, h('option', { value: '' }, '— (opcional)'));
  const info = h('div');
  const ubic = {
    provincia: h('input', { type: 'text', maxlength: '1', placeholder: '1' }),
    canton: h('input', { type: 'text', maxlength: '2', placeholder: '01' }),
    distrito: h('input', { type: 'text', maxlength: '2', placeholder: '01' }),
    otras_senas: h('input', { type: 'text', maxlength: '250' }),
  };

  // Catálogo de clientes frecuentes
  const guardarCliente = h('input', { type: 'checkbox' });
  let clienteId = null;
  const cargarCliente = (cl) => {
    clienteId = cl.id;
    tipo.value = cl.tipo_identificacion;
    numero.value = cl.numero_identificacion;
    nombre.value = cl.nombre;
    correo.value = cl.correo || '';
    if (cl.codigo_actividad) {
      vaciar(actividad, h('option', { value: '' }, '— (opcional)'),
        h('option', { value: cl.codigo_actividad, selected: true }, cl.codigo_actividad));
    }
    if (conUbicacion) for (const k of Object.keys(ubic)) ubic[k].value = cl[k] || '';
    guardarCliente.checked = false;
    vaciar(info, aviso(`Cliente del catálogo: ${cl.nombre}`, 'ok'));
  };

  // Al escribir la identificación se llena todo: primero desde Mis clientes
  // (correo, ubicación) y luego con los datos de Hacienda (nombre, estado, actividades).
  const consultar = alCompletarCedula(numero, tipo, async (id, vigente) => {
    let delCatalogo = null;
    if (conCatalogo) {
      try {
        const lista = await api(`/catalogo/clientes?q=${encodeURIComponent(id)}`);
        delCatalogo = lista.find((cl) => cl.numero_identificacion === id) || null;
      } catch { /* sin acceso al catálogo: solo Hacienda */ }
      if (!vigente()) return;
      if (delCatalogo) cargarCliente(delCatalogo);
    }
    if (!delCatalogo) vaciar(info, h('p', { class: 'suave' }, 'Consultando Hacienda…'));
    let c;
    try {
      c = await api(`/hacienda/contribuyentes/${id}`);
    } catch (e) {
      if (vigente() && !delCatalogo) vaciar(info, e.status === 404 ? avisoNoInscrito(id) : aviso(e.message, 'error'));
      return;
    }
    if (!vigente()) return;
    nombre.value = c.nombre || nombre.value;
    if (c.tipoIdentificacion) tipo.value = c.tipoIdentificacion;
    const activas = (c.actividades || []).filter((a) => a.estado === 'A' || !a.estado);
    const elegida = delCatalogo?.codigo_actividad
      || String((activas.find((a) => a.tipo === 'P') || activas[0] || {}).codigo || '').padStart(6, '0');
    vaciar(actividad, h('option', { value: '' }, '— (opcional)'),
      activas.map((a) => {
        const cod = String(a.codigo).padStart(6, '0');
        return h('option', { value: cod, selected: cod === elegida }, `${a.codigo} · ${a.descripcion}`);
      }),
      elegida && !activas.some((a) => String(a.codigo).padStart(6, '0') === elegida)
        ? h('option', { value: elegida, selected: true }, elegida) : null);
    vaciar(info, delCatalogo ? aviso(`Cliente del catálogo: ${delCatalogo.nombre}`, 'ok') : null, avisoContribuyente(c, activas));
  });
  const buscar = h('button', { type: 'button', onclick: () => conBoton(buscar, consultar) }, 'Volver a consultar');
  const elegir = conCatalogo ? h('button', { type: 'button', class: 'primario', onclick: () => dialogoElegirCliente(cargarCliente) }, 'Elegir cliente') : null;
  [numero, nombre].forEach((el) => el.addEventListener('input', () => { clienteId = null; }));

  const seccion = h('section', { class: 'tarjeta' },
    h('div', { class: 'encabezado' }, h('h2', {}, titulo), elegir),
    h('div', { class: 'campos' },
      campo('Tipo de identificación', tipo),
      h('div', { class: 'fila doble' }, campo('Identificación', numero), buscar),
      campo('Nombre', nombre), campo('Correo', correo), campo('Actividad económica', actividad)),
    conUbicacion ? h('div', { class: 'campos' }, campo('Provincia', ubic.provincia), campo('Cantón', ubic.canton),
      campo('Distrito', ubic.distrito), campo('Otras señas', ubic.otras_senas)) : null,
    conCatalogo ? h('label', { class: 'check' }, guardarCliente, 'Guardar en mis clientes frecuentes') : null,
    info);

  return {
    seccion,
    // Guarda el receptor en el catálogo si se marcó la casilla (no bloquea la emisión)
    async guardarEnCatalogo() {
      if (!conCatalogo || !guardarCliente.checked || clienteId || !numero.value.trim()) return;
      const cuerpo = { tipo_identificacion: tipo.value, numero_identificacion: numero.value.trim(), nombre: nombre.value.trim() };
      if (correo.value.trim()) cuerpo.correo = correo.value.trim();
      if (actividad.value) cuerpo.codigo_actividad = actividad.value;
      try { await api('/catalogo/clientes', { method: 'POST', body: cuerpo }); } catch { /* ya existía o datos incompletos */ }
    },
    valor() {
      if (!numero.value.trim() && !nombre.value.trim()) return null;
      const p = { nombre: nombre.value.trim(), tipo_identificacion: tipo.value, numero_identificacion: numero.value.trim() };
      if (correo.value.trim()) p.correo = correo.value.trim();
      if (actividad.value) p.codigo_actividad = actividad.value;
      if (conUbicacion && ubic.provincia.value) {
        p.ubicacion = Object.fromEntries(Object.entries(ubic).map(([k, v]) => [k, v.value.trim()]));
      }
      return p;
    },
    actividad: () => actividad.value || null,
    identificacion: () => numero.value.replace(/\D/g, ''),
  };
}

// ---------------------------------------------------------------------------
// Línea de detalle
// ---------------------------------------------------------------------------
function crearLinea(alCambiar, alQuitar, { receptorId = () => null, exoneracion = () => null } = {}) {
  const c = {
    cabys: h('input', { type: 'text', maxlength: '13', placeholder: '13 dígitos', size: '14' }),
    descripcion: h('input', { type: 'text', maxlength: '200' }),
    cantidad: h('input', { type: 'number', step: '0.001', min: '0', value: '1' }),
    unidad: h('select', {}, Object.entries(UNIDADES).map(([k, v]) => h('option', { value: k, title: v }, k))),
    precio: h('input', { type: 'number', step: '0.01', min: '0' }),
    descuento: h('input', { type: 'number', step: '0.01', min: '0', value: '0' }),
    tarifa: h('select', {}, tarifasOpciones('08')),
    // opciones avanzadas
    codigoComercial: h('input', { type: 'text', maxlength: '20' }),
    codigoDescuento: h('select', {}, opciones(DESCUENTOS, '07')),
    partida: h('input', { type: 'text', maxlength: '12', placeholder: '12 dígitos' }),
    noSujeto: h('input', { type: 'checkbox' }),
    fabrica: h('select', {}, h('option', { value: '' }, '—'), h('option', { value: '01' }, '01 · IVA cobrado en fábrica'),
      h('option', { value: '02' }, '02 · Exenta por sistema de fábrica')),
    asumido: h('input', { type: 'checkbox' }),
    factor: h('input', { type: 'number', step: '0.0001', min: '0', max: '1', placeholder: 'Solo bienes usados' }),
    exoAut: h('input', { type: 'text', maxlength: '40', placeholder: 'AL-00000000-24' }),
    exoTipo: h('input', { type: 'text', maxlength: '2', placeholder: '04' }),
    exoInst: h('select', {}, opciones(INSTITUCIONES_EXONERACION, '01')),
    exoFecha: h('input', { type: 'date' }),
    exoTarifa: h('input', { type: 'number', step: '0.01', min: '0', max: '13', placeholder: 'Puntos de IVA' }),
  };
  const total = h('span');
  const exoInfo = h('div');
  // Producto del catálogo (descuenta inventario si lo controla)
  let productoId = null;
  const infoProducto = h('div', { class: 'suave' });

  // Exoneraciones de Hacienda (AL-XXXXXXXX-XX): al escribir el número se validan y
  // se llenan solos el tipo, la institución, la fecha y la tarifa. Otros documentos se digitan.
  let exoConsultada = '';
  const consultarExo = async (forzar = false) => {
    const aut = c.exoAut.value.trim().toUpperCase();
    if (!/^AL-\d{8}-\d{2}$/.test(aut)) {
      if (forzar) toast('Solo las autorizaciones AL-XXXXXXXX-XX se validan en Hacienda; complete los datos a mano', 'error');
      return;
    }
    if (!forzar && aut === exoConsultada) return;
    exoConsultada = aut;
    c.exoAut.value = aut;
    vaciar(exoInfo, h('p', { class: 'suave' }, 'Validando en Hacienda…'));
    let ex;
    try {
      ex = await api(`/hacienda/exoneraciones/${encodeURIComponent(aut)}`);
    } catch (e) {
      exoConsultada = '';
      vaciar(exoInfo, aviso(e.status === 404 ? `La autorización ${aut} no existe en Hacienda.` : e.message, 'error'));
      return;
    }
    if (ex.tipoDocumento?.codigo) c.exoTipo.value = String(ex.tipoDocumento.codigo).padStart(2, '0');
    if (ex.CodigoInstitucion && INSTITUCIONES_EXONERACION[String(ex.CodigoInstitucion).padStart(2, '0')]) {
      c.exoInst.value = String(ex.CodigoInstitucion).padStart(2, '0');
    }
    if (ex.fechaEmision) c.exoFecha.value = String(ex.fechaEmision).slice(0, 10);
    const pct = Number(ex.porcentajeExoneracion ?? ex.tarifaExonerada);
    if (!Number.isNaN(pct) && pct > 0) c.exoTarifa.value = String(pct > 13 ? 13 * pct / 100 : pct);
    alCambiar();
    const vence = String(ex.fechaVencimiento || '').slice(0, 10);
    const problemas = [];
    if (vence && vence < new Date().toISOString().slice(0, 10)) problemas.push(`está vencida desde ${vence}`);
    const rid = receptorId();
    if (rid && ex.identificacion && String(ex.identificacion) !== rid) problemas.push(`pertenece a la identificación ${ex.identificacion}, no al cliente`);
    const cab = c.cabys.value.trim();
    if (ex.poseeCabys && cab && Array.isArray(ex.cabys) && !ex.cabys.includes(cab)) problemas.push(`no autoriza el CABYS ${cab}`);
    vaciar(exoInfo, problemas.length
      ? aviso(`Atención: la exoneración ${problemas.join('; ')}.`, 'error')
      : aviso(`${ex.nombreInstitucion || ''} · ${ex.porcentajeExoneracion ?? ''}% · vence ${vence} · identificación ${ex.identificacion || ''}`, 'ok'));
  };
  c.exoAut.addEventListener('input', () => { if (/^AL-\d{8}-\d{2}$/i.test(c.exoAut.value.trim())) consultarExo(); });
  c.exoAut.addEventListener('change', () => consultarExo());
  const validarExo = h('button', { type: 'button', class: 'chico', onclick: () => conBoton(validarExo, () => consultarExo(true)) }, 'Volver a validar');

  // Exoneración del cliente (para toda la factura): se aplica sola si el CABYS de la
  // línea está en la lista autorizada; si no, se avisa que no está contemplado.
  const estadoExo = h('div');
  let exoAutomatica = false;
  const quitarExoAutomatica = () => {
    if (!exoAutomatica) return;
    c.exoAut.value = ''; c.exoTipo.value = ''; c.exoFecha.value = ''; c.exoTarifa.value = '';
    exoAutomatica = false;
  };
  const aplicarExoneracion = (avisar = false) => {
    const ex = exoneracion();
    const cab = c.cabys.value.trim();
    if (!ex || !/^\d{13}$/.test(cab)) {
      quitarExoAutomatica();
      vaciar(estadoExo);
      alCambiar();
      return;
    }
    if (ex.cubre(cab)) {
      c.exoAut.value = ex.autorizacion;
      c.exoTipo.value = ex.tipo; c.exoInst.value = ex.institucion; c.exoFecha.value = ex.fecha; c.exoTarifa.value = ex.tarifa;
      exoAutomatica = true;
      vaciar(estadoExo, h('span', { class: 'badge ACEPTADO' }, `Exonerado ${ex.tarifa} pts · ${ex.autorizacion}`));
    } else {
      quitarExoAutomatica();
      vaciar(estadoExo, h('span', { class: 'badge CONTINGENCIA', title: 'Esta línea se factura con IVA completo' },
        `No contemplado en la exoneración ${ex.autorizacion}`));
      if (avisar) toast(`El CABYS ${cab} no está contemplado en la exoneración ${ex.autorizacion}: se facturará con IVA.`, 'error');
    }
    alCambiar();
  };
  c.cabys.addEventListener('change', () => aplicarExoneracion(true));
  c.cabys.addEventListener('input', () => { if (/^\d{13}$/.test(c.cabys.value.trim())) aplicarExoneracion(true); });

  const buscarCabys = h('button', { type: 'button', class: 'chico', title: 'Buscar CABYS', onclick: () => dialogoCabys((item) => {
    c.cabys.value = item.codigo;
    if (!c.descripcion.value) c.descripcion.value = String(item.descripcion).slice(0, 200);
    const t = TARIFA_POR_PORCENTAJE[Number(item.impuesto)];
    if (t) c.tarifa.value = t;
    aplicarExoneracion(true);
  }) }, '🔍');

  const extra = h('tr', { class: 'extra oculto' }, h('td', { colspan: '10' },
    h('div', { class: 'campos' },
      campo('Código comercial', c.codigoComercial), campo('Código de descuento', c.codigoDescuento),
      campo('Partida arancelaria (exportación)', c.partida), campo('IVA a nivel de fábrica', c.fabrica),
      campo('Factor IVA bienes usados', c.factor),
      h('label', { class: 'check' }, c.noSujeto, 'No sujeto a IVA'),
      h('label', { class: 'check' }, c.asumido, 'Impuesto asumido por el emisor')),
    h('h3', {}, 'Exoneración solo de esta línea (otro documento)'),
    h('div', { class: 'campos' },
      h('div', { class: 'fila' }, campo('Autorización', c.exoAut), validarExo),
      campo('Tipo de documento', c.exoTipo), campo('Institución', c.exoInst), campo('Fecha de emisión', c.exoFecha),
      campo('Tarifa exonerada (puntos)', c.exoTarifa)),
    exoInfo));

  const fila = h('tr', {},
    h('td', {}, h('div', { class: 'fila' }, c.cabys, buscarCabys)),
    h('td', {}, c.descripcion, infoProducto, estadoExo), h('td', {}, c.cantidad), h('td', {}, c.unidad), h('td', {}, c.precio),
    h('td', {}, c.descuento), h('td', {}, c.tarifa), h('td', { class: 'num' }, total),
    h('td', {}, h('button', { type: 'button', class: 'chico', title: 'Opciones', onclick: () => extra.classList.toggle('oculto') }, '⚙')),
    h('td', {}, h('button', { type: 'button', class: 'chico peligro', title: 'Quitar', onclick: () => { fila.remove(); extra.remove(); alQuitar(linea); } }, '✕')));

  [c.cantidad, c.precio, c.descuento, c.tarifa, c.noSujeto, c.fabrica, c.asumido, c.exoTarifa, c.factor]
    .forEach((el) => el.addEventListener('input', alCambiar));

  const linea = {
    filas: [fila, extra],
    vacia: () => !c.cabys.value.trim() && !c.descripcion.value.trim(),
    tarifa: () => c.tarifa.value,
    cargarProducto(p) {
      productoId = p.id;
      c.cabys.value = p.codigo_cabys;
      c.descripcion.value = p.descripcion;
      c.codigoComercial.value = p.codigo;
      if (UNIDADES[p.unidad_medida]) c.unidad.value = p.unidad_medida;
      c.precio.value = Number(p.precio_unitario);
      c.tarifa.value = p.codigo_tarifa_iva;
      infoProducto.textContent = p.controla_inventario
        ? `${p.codigo} · existencia ${Number(p.existencia).toLocaleString('es-CR', { maximumFractionDigits: 3 })}`
        : p.codigo;
      aplicarExoneracion(true);
      c.cantidad.focus();
      c.cantidad.select();
    },
    // Línea desde la lista de CABYS autorizados de la exoneración
    cargarCabys(item) {
      c.cabys.value = item.codigo;
      if (item.descripcion) c.descripcion.value = String(item.descripcion).slice(0, 200);
      const t = TARIFA_POR_PORCENTAJE[Number(item.impuesto)];
      if (t) c.tarifa.value = t;
      aplicarExoneracion();
      (c.descripcion.value ? c.precio : c.descripcion).focus();
    },
    aplicarExoneracion: () => aplicarExoneracion(false),
    calculo() {
      const bruto = Number(c.cantidad.value || 0) * Number(c.precio.value || 0);
      const subtotal = bruto - Number(c.descuento.value || 0);
      let iva = 0;
      if (!c.noSujeto.checked && c.fabrica.value !== '02') {
        const tarifa = TARIFAS_IVA[c.tarifa.value][1];
        iva = c.factor.value ? subtotal * Number(c.factor.value) : subtotal * tarifa / 100;
        if (c.exoTarifa.value && c.exoAut.value) iva -= subtotal * Math.min(Number(c.exoTarifa.value), tarifa) / 100;
        if (c.asumido.checked || c.fabrica.value === '01') iva = 0;
      }
      total.textContent = dinero(subtotal + iva, '');
      return { subtotal, iva, descuento: Number(c.descuento.value || 0) };
    },
    valor() {
      const p = {
        codigo_cabys: c.cabys.value.trim(), descripcion: c.descripcion.value.trim(), cantidad: c.cantidad.value,
        unidad_medida: c.unidad.value, precio_unitario: c.precio.value || '0', codigo_tarifa_iva: c.tarifa.value,
      };
      if (Number(c.descuento.value) > 0) { p.descuento = c.descuento.value; p.codigo_descuento = c.codigoDescuento.value; }
      if (c.codigoComercial.value.trim()) p.codigo_comercial = c.codigoComercial.value.trim();
      if (productoId) p.producto_id = productoId;
      if (c.partida.value.trim()) p.partida_arancelaria = c.partida.value.trim();
      if (c.noSujeto.checked) p.no_sujeto = true;
      if (c.asumido.checked) p.impuesto_asumido_emisor = true;
      if (c.fabrica.value) p.iva_cobrado_fabrica = c.fabrica.value;
      if (c.factor.value) p.impuestos = [{ codigo: '08', codigo_tarifa_iva: c.tarifa.value, factor_calculo_iva: c.factor.value }];
      if (c.exoAut.value.trim()) {
        p.exoneracion = {
          tipo_documento: c.exoTipo.value.trim().padStart(2, '0'), numero_documento: c.exoAut.value.trim(),
          nombre_institucion: c.exoInst.value, fecha_emision: `${c.exoFecha.value}T00:00:00`, tarifa_exonerada: c.exoTarifa.value,
        };
      }
      return p;
    },
  };
  return linea;
}

export function dialogoCabys(alElegir) {
  const q = h('input', { type: 'search', placeholder: 'Ej.: café, consultoría, repuestos…' });
  const resultados = h('div');
  const buscar = h('button', { type: 'submit', class: 'primario' }, 'Buscar');
  const form = h('form', { class: 'fila', onsubmit: (e) => {
    e.preventDefault();
    conBoton(buscar, async () => {
      const r = await api(`/hacienda/cabys?q=${encodeURIComponent(q.value)}&top=30`);
      const lista = Array.isArray(r) ? r : (r.cabys || []);
      vaciar(resultados, tabla([
        { titulo: 'Código', valor: (x) => h('span', { class: 'mono' }, x.codigo) },
        { titulo: 'Descripción', valor: (x) => x.descripcion },
        { titulo: 'IVA', num: true, valor: (x) => (x.impuesto !== undefined ? `${x.impuesto}%` : '') },
      ], lista, (x) => { alElegir(x); m.cerrar(); }));
    });
  } }, q, buscar);
  const m = modal('Buscar código CABYS', [form, resultados], { ancho: true });
}

// ---------------------------------------------------------------------------
// Formulario
// ---------------------------------------------------------------------------
export async function vistaEmitir(cont) {
  const tipo = h('select', {}, opciones(TIPOS_DOCUMENTO, '01'));
  const sucursal = h('input', { type: 'number', min: '1', max: '999', value: '1' });
  const terminal = h('input', { type: 'number', min: '1', max: '99999', value: '1' });
  const situacion = h('select', {}, Object.entries(SITUACIONES).map(([k, v]) => h('option', { value: k }, `${k} · ${v}`)));
  const fechaEmision = h('input', { type: 'datetime-local' });
  const refExterna = h('input', { type: 'text', maxlength: '100', placeholder: 'Opcional: ID en su sistema' });
  const condicion = h('select', {}, opciones(CONDICIONES_VENTA, '01'));
  const plazo = h('input', { type: 'number', min: '1', placeholder: 'Días' });
  const moneda = h('select', {}, ['CRC', 'USD', 'EUR'].map((m) => h('option', { value: m }, m)));
  const tipoCambio = h('input', { type: 'number', step: '0.00001', min: '0', placeholder: 'Automático' });
  const servicio10 = h('input', { type: 'checkbox' });
  const ivaDevuelto = h('input', { type: 'number', step: '0.01', min: '0', placeholder: 'Servicios de salud con tarjeta' });
  const notas = h('textarea', { rows: '2', maxlength: '1000' });

  const receptor = bloquePersona('Cliente (receptor)', { conCatalogo: true });
  const proveedor = bloquePersona('Proveedor (factura de compra)', { conUbicacion: true });

  // Exoneración del cliente para toda la factura: al escribir la autorización se
  // cargan de Hacienda los productos y servicios (CABYS) que cubre.
  let exoCliente = null;
  const exoAut = h('input', { type: 'text', maxlength: '14', placeholder: 'AL-00000000-24' });
  const exoInfo = h('div');
  const exoLista = h('div');
  let exoConsultada = '';
  const reaplicarExo = () => lineas.forEach((l) => l.aplicarExoneracion());
  const consultarExoCliente = async (forzar = false) => {
    const aut = exoAut.value.trim().toUpperCase();
    if (!aut) { exoConsultada = ''; exoCliente = null; vaciar(exoInfo); vaciar(exoLista); reaplicarExo(); return; }
    if (!/^AL-\d{8}-\d{2}$/.test(aut)) {
      if (forzar) vaciar(exoInfo, aviso('Formato: AL-XXXXXXXX-XX. Otros documentos de exoneración se indican en cada línea (⚙).', 'error'));
      return;
    }
    if (!forzar && aut === exoConsultada) return;
    exoConsultada = aut;
    exoAut.value = aut;
    exoCliente = null;
    vaciar(exoLista);
    vaciar(exoInfo, h('p', { class: 'suave' }, 'Consultando la exoneración y sus productos en Hacienda…'));
    let ex;
    try {
      ex = await api(`/hacienda/exoneraciones/${encodeURIComponent(aut)}?detalle=true`);
    } catch (e) {
      exoConsultada = '';
      vaciar(exoInfo, aviso(e.status === 404 ? `La autorización ${aut} no existe en Hacienda.` : e.message, 'error'));
      reaplicarExo();
      return;
    }
    if (aut !== exoAut.value.trim().toUpperCase()) return;
    const hoy = new Date().toISOString().slice(0, 10);
    const vence = String(ex.fechaVencimiento || '').slice(0, 10);
    const rid = receptor.identificacion();
    const pct = Number(ex.porcentajeExoneracion ?? ex.tarifaExonerada);
    const inst = String(ex.CodigoInstitucion || '').padStart(2, '0');
    const autorizados = new Set((ex.cabys_detalle || []).map((x) => x.codigo));
    const problemas = [];
    if (vence && vence < hoy) problemas.push(`está vencida desde ${vence}`);
    if (rid && ex.identificacion && String(ex.identificacion) !== rid) problemas.push(`pertenece a la identificación ${ex.identificacion}, no a este cliente`);
    if (problemas.length) {
      vaciar(exoInfo, aviso(`No se puede aplicar: la exoneración ${problemas.join(' y ')}.`, 'error'));
      reaplicarExo();
      return;
    }
    exoCliente = {
      autorizacion: aut,
      tipo: String(ex.tipoDocumento?.codigo || '').padStart(2, '0'),
      institucion: INSTITUCIONES_EXONERACION[inst] ? inst : '01',
      fecha: String(ex.fechaEmision || '').slice(0, 10),
      tarifa: String(!Number.isNaN(pct) && pct > 0 ? (pct > 13 ? 13 * pct / 100 : pct) : 13),
      identificacion: String(ex.identificacion || ''),
      cubre: (cabys) => ex.aplica_a_todo || autorizados.has(cabys),
    };
    vaciar(exoInfo, avisoRespaldo(ex), aviso(
      `${ex.nombreInstitucion || ''} · ${ex.porcentajeExoneracion ?? ''}% · vence ${vence || '—'} · identificación ${ex.identificacion || ''} · `
      + (ex.aplica_a_todo ? 'aplica a todos los productos y servicios.' : `${autorizados.size} producto(s)/servicio(s) autorizado(s).`), 'ok'));
    if (!ex.aplica_a_todo) {
      vaciar(exoLista,
        h('p', { class: 'suave' }, 'Productos y servicios que cubre (clic para agregarlo a la factura). Las líneas con otros CABYS se facturan con IVA.'),
        tabla([
          { titulo: 'CABYS', valor: (x) => h('span', { class: 'mono' }, x.codigo) },
          { titulo: 'Descripción', valor: (x) => x.descripcion || h('span', { class: 'suave' }, '(sin descripción)') },
          { titulo: 'IVA', num: true, valor: (x) => (x.impuesto !== null && x.impuesto !== undefined ? `${x.impuesto}%` : '') },
        ], ex.cabys_detalle, (x) => {
          const ultima = lineas[lineas.length - 1];
          (ultima && ultima.vacia() ? ultima : agregarLinea()).cargarCabys(x);
        }));
    }
    reaplicarExo();
  };
  exoAut.addEventListener('input', () => {
    const v = exoAut.value.trim();
    if (!v || /^AL-\d{8}-\d{2}$/i.test(v)) consultarExoCliente();
  });
  exoAut.addEventListener('change', () => consultarExoCliente());
  const revalidarExo = h('button', { type: 'button', onclick: () => conBoton(revalidarExo, () => consultarExoCliente(true)) }, 'Volver a consultar');
  const seccionExo = h('section', { class: 'tarjeta' },
    h('h2', {}, 'Exoneración del cliente (opcional)'),
    h('div', { class: 'fila' }, campo('Número de autorización', exoAut), revalidarExo),
    exoInfo, exoLista);

  const ref = {
    tipo: h('select', {}, opciones(TIPOS_DOC_REFERENCIA, '01')),
    numero: h('input', { type: 'text', maxlength: '50', placeholder: 'Clave de 50 dígitos' }),
    fecha: h('input', { type: 'datetime-local' }),
    codigo: h('select', {}, opciones(CODIGOS_REFERENCIA, '01')),
    razon: h('input', { type: 'text', maxlength: '180' }),
  };
  const seccionRef = h('section', { class: 'tarjeta' }, h('h2', {}, 'Documento de referencia'),
    h('div', { class: 'campos' }, campo('Tipo', ref.tipo), campo('Número / clave', ref.numero),
      campo('Fecha', ref.fecha), campo('Código', ref.codigo), campo('Razón', ref.razon)));

  // Medios de pago
  const medios = h('div', { class: 'campos' });
  const medioFilas = [];
  const agregarMedio = () => {
    if (medioFilas.length >= 4) return;
    const t = h('select', {}, opciones(MEDIOS_PAGO, medioFilas.length ? '02' : '01'));
    const m = h('input', { type: 'number', step: '0.01', min: '0', placeholder: 'Monto (si hay varios)' });
    medioFilas.push({ t, m });
    medios.append(h('div', { class: 'fila' }, t, m));
  };
  agregarMedio();

  // Líneas
  const cuerpoLineas = h('tbody');
  const lineas = [];
  const resumen = h('table', { class: 'totales' });

  // Tarifa reducida 1%: si son insumos agropecuarios o de pesca, el cliente debe estar
  // registrado en el MAG o INCOPESCA. Se consulta solo si el usuario lo pide.
  const resultadoAgro = h('div');
  const verificarAgro = h('button', { type: 'button', class: 'chico', onclick: () => conBoton(verificarAgro, async () => {
    const id = receptor.identificacion();
    if (id.length < 9) { vaciar(resultadoAgro, aviso('Indique primero la identificación del cliente', 'error')); return; }
    const r = await api(`/hacienda/productores/${id}`);
    const registros = [r.agropecuario ? 'MAG (agropecuario)' : null, r.pesca ? 'INCOPESCA (pesca)' : null].filter(Boolean);
    vaciar(resultadoAgro, r.registrado
      ? aviso(`El cliente está registrado en ${registros.join(' y ')}: aplica la tarifa reducida de insumos.`, 'ok')
      : aviso('El cliente NO está registrado en el MAG ni en INCOPESCA: los insumos agropecuarios o de pesca no pueden facturarse con la tarifa reducida.', 'error'));
  }) }, 'Verificar cliente en MAG / INCOPESCA');
  const avisoAgro = h('div', { class: 'oculto' },
    aviso('Hay líneas con tarifa 1%. Si son insumos agropecuarios o de pesca, verifique que el cliente esté registrado como productor.', 'info'),
    verificarAgro, resultadoAgro);

  const recalcular = () => {
    avisoAgro.classList.toggle('oculto', tipo.value === '08' || !lineas.some((l) => l.tarifa() === '02'));
    let sub = 0; let iva = 0; let desc = 0;
    lineas.forEach((l) => { const r = l.calculo(); sub += r.subtotal; iva += r.iva; desc += r.descuento; });
    const cargo = servicio10.checked ? sub * 0.10 : 0;
    const dev = Number(ivaDevuelto.value || 0);
    const mon = moneda.value;
    vaciar(resumen, h('tbody', {},
      h('tr', {}, h('td', {}, 'Descuentos'), h('td', { class: 'num' }, dinero(desc, mon))),
      h('tr', {}, h('td', {}, 'Subtotal'), h('td', { class: 'num' }, dinero(sub, mon))),
      h('tr', {}, h('td', {}, 'Impuestos'), h('td', { class: 'num' }, dinero(iva, mon))),
      cargo ? h('tr', {}, h('td', {}, 'Servicio 10%'), h('td', { class: 'num' }, dinero(cargo, mon))) : null,
      dev ? h('tr', {}, h('td', {}, 'IVA devuelto'), h('td', { class: 'num' }, dinero(-dev, mon))) : null,
      h('tr', { class: 'total' }, h('td', {}, 'Total estimado'), h('td', { class: 'num' }, dinero(sub + iva + cargo - dev, mon)))));
  };
  const agregarLinea = () => {
    const l = crearLinea(recalcular, (x) => { lineas.splice(lineas.indexOf(x), 1); recalcular(); },
      { receptorId: receptor.identificacion, exoneracion: () => exoCliente });
    lineas.push(l);
    cuerpoLineas.append(...l.filas);
    recalcular();
    return l;
  };
  const agregarDelCatalogo = () => dialogoElegirProducto((p) => {
    const ultima = lineas[lineas.length - 1];
    (ultima && ultima.vacia() ? ultima : agregarLinea()).cargarProducto(p);
  });
  agregarLinea();
  [servicio10, ivaDevuelto, moneda].forEach((el) => el.addEventListener('input', recalcular));
  tipo.addEventListener('change', recalcular);

  // El tipo de cambio de Hacienda se llena solo al elegir USD o EUR (se puede corregir a mano)
  const cargarTc = async () => {
    if (moneda.value === 'CRC') { tipoCambio.value = ''; return; }
    const r = await api(`/hacienda/tipo-cambio/${moneda.value}`);
    tipoCambio.value = r.tipo_cambio;
  };
  moneda.addEventListener('change', () => cargarTc().catch((e) => toast(e.message, 'error')));
  const consultarTc = h('button', { type: 'button', onclick: () => conBoton(consultarTc, cargarTc) }, 'Actualizar');

  const campoFecha = campo('Fecha real de la venta', fechaEmision);
  const campoPlazo = campo('Plazo de crédito', plazo);
  const campoDevuelto = campo('IVA devuelto', ivaDevuelto);
  const mensaje = h('div');

  const actualizarVisibilidad = () => {
    const t = tipo.value;
    receptor.seccion.classList.toggle('oculto', t === '08');
    seccionExo.classList.toggle('oculto', t === '08');
    proveedor.seccion.classList.toggle('oculto', t !== '08');
    seccionRef.classList.toggle('oculto', !(['02', '03', '08'].includes(t) || situacion.value === '2'));
    campoFecha.classList.toggle('oculto', situacion.value === '1');
    campoPlazo.classList.toggle('oculto', !['02', '08', '10'].includes(condicion.value));
    campoDevuelto.classList.toggle('oculto', !['01', '04'].includes(t));
    if (situacion.value === '2') { ref.tipo.value = '08'; ref.codigo.value = '05'; }
    if (t === '08') { ref.tipo.value = ref.tipo.value === '01' ? '14' : ref.tipo.value; ref.codigo.value = '04'; }
  };
  [tipo, situacion, condicion].forEach((el) => el.addEventListener('change', actualizarVisibilidad));
  actualizarVisibilidad();

  const emitir = h('button', { type: 'submit', class: 'primario' }, 'Firmar y enviar a Hacienda');
  const form = h('form', { onsubmit: (e) => {
    e.preventDefault();
    vaciar(mensaje);
    conBoton(emitir, async () => {
      const t = tipo.value;
      if (t !== '08' && exoCliente?.identificacion && receptor.identificacion() !== exoCliente.identificacion) {
        vaciar(mensaje, aviso(`La exoneración ${exoCliente.autorizacion} es de la identificación ${exoCliente.identificacion}; cambie el cliente o quite la exoneración.`, 'error'));
        return;
      }
      const datos = {
        tipo_documento: t, sucursal: Number(sucursal.value), terminal: Number(terminal.value),
        condicion_venta: condicion.value, moneda: moneda.value,
        productos: lineas.map((l) => l.valor()),
        medios_pago: medioFilas.map(({ t: tp, m }) => (m.value ? { tipo: tp.value, monto: m.value } : { tipo: tp.value })),
        situacion: situacion.value,
      };
      if (refExterna.value.trim()) datos.referencia_externa = refExterna.value.trim();
      if (plazo.value && !campoPlazo.classList.contains('oculto')) datos.plazo_credito = Number(plazo.value);
      if (tipoCambio.value && moneda.value !== 'CRC') datos.tipo_cambio = tipoCambio.value;
      if (situacion.value !== '1') datos.fecha_emision = fechaEmision.value ? `${fechaEmision.value}:00` : null;
      if (notas.value.trim()) datos.notas = notas.value.trim();
      if (ivaDevuelto.value && !campoDevuelto.classList.contains('oculto')) datos.iva_devuelto = ivaDevuelto.value;
      if (servicio10.checked) datos.otros_cargos = [{ tipo_documento: '06', detalle: 'Impuesto de servicio 10%', porcentaje: '10' }];
      if (t === '08') {
        datos.proveedor = proveedor.valor();
      } else {
        datos.receptor = receptor.valor();
        if (receptor.actividad()) datos.codigo_actividad_receptor = receptor.actividad();
      }
      if (!seccionRef.classList.contains('oculto')) {
        datos.referencia = {
          tipo_documento: ref.tipo.value, numero: ref.numero.value.trim() || null,
          fecha_emision: ref.fecha.value ? `${ref.fecha.value}:00` : null, codigo: ref.codigo.value, razon: ref.razon.value.trim() || null,
        };
      }
      try {
        const r = await api('/facturas', { method: 'POST', body: datos });
        if (t !== '08') await receptor.guardarEnCatalogo();
        toast(r.message, 'ok');
        location.hash = `#/comprobantes/${r.factura_id}`;
      } catch (err) {
        vaciar(mensaje, h('div', { class: 'aviso error' }, err.message));
        mensaje.scrollIntoView({ behavior: 'smooth' });
      }
    });
  } },
  h('section', { class: 'tarjeta' }, h('h2', {}, 'Comprobante'),
    h('div', { class: 'campos' },
      campo('Tipo', tipo), campo('Sucursal', sucursal), campo('Terminal', terminal),
      campo('Situación', situacion), campoFecha, campo('Referencia interna', refExterna))),
  receptor.seccion,
  seccionExo,
  proveedor.seccion,
  h('section', { class: 'tarjeta' }, h('h2', {}, 'Detalle'),
    h('div', { class: 'tabla' }, h('table', { class: 'lineas' },
      h('thead', {}, h('tr', {}, ['CABYS', 'Descripción', 'Cantidad', 'Unidad', 'Precio unit.', 'Descuento', 'IVA', 'Total', '', '']
        .map((t) => h('th', {}, t)))),
      cuerpoLineas)),
    h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'primario', onclick: agregarDelCatalogo }, '+ Del catálogo'),
      h('button', { type: 'button', onclick: () => agregarLinea() }, '+ Línea manual'),
      h('label', { class: 'check' }, servicio10, 'Cobrar impuesto de servicio 10% (restaurantes)')),
    avisoAgro),
  h('div', { class: 'campos dos' },
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Condiciones y pago'),
      h('div', { class: 'campos' },
        campo('Condición de venta', condicion), campoPlazo,
        campo('Moneda', moneda), h('div', { class: 'fila' }, campo('Tipo de cambio', tipoCambio), consultarTc),
        campoDevuelto),
      h('h3', {}, 'Medios de pago'), medios,
      h('button', { type: 'button', class: 'chico', onclick: agregarMedio }, '+ Otro medio de pago'),
      campo('Notas', notas)),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Resumen'), resumen,
      h('p', { class: 'suave' }, 'Estimado; el cálculo oficial lo hace el sistema al firmar.'))),
  seccionRef,
  mensaje,
  h('div', { class: 'acciones' }, emitir));

  vaciar(cont, h('div', { class: 'encabezado' }, h('h1', {}, 'Nuevo comprobante')), form);
}
