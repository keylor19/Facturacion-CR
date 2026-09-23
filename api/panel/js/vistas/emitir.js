import { api } from '../api.js';
import { h, vaciar, dinero, modal, conBoton, toast, campo, opciones, tabla, aviso } from '../dom.js';
import {
  TIPOS_DOCUMENTO, TIPOS_IDENTIFICACION, CONDICIONES_VENTA, MEDIOS_PAGO, TARIFAS_IVA, DESCUENTOS, UNIDADES,
  INSTITUCIONES_EXONERACION, TIPOS_DOC_REFERENCIA, CODIGOS_REFERENCIA, SITUACIONES,
} from '../catalogos.js';

const TARIFA_POR_PORCENTAJE = { 13: '08', 8: '07', 4: '04', 2: '03', 1: '02', 0.5: '09' };
const tarifasOpciones = (sel) => Object.entries(TARIFAS_IVA).map(([k, [t]]) => h('option', { value: k, selected: k === sel }, t));

// ---------------------------------------------------------------------------
// Persona (receptor o proveedor) con búsqueda en Hacienda
// ---------------------------------------------------------------------------
function bloquePersona(titulo, { conUbicacion = false } = {}) {
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

  const buscar = h('button', { type: 'button', onclick: () => conBoton(buscar, async () => {
    const id = numero.value.replace(/\D/g, '');
    if (!id) { toast('Indique la identificación', 'error'); return; }
    const c = await api(`/hacienda/contribuyentes/${id}`);
    nombre.value = c.nombre || '';
    if (c.tipoIdentificacion) tipo.value = c.tipoIdentificacion;
    numero.value = id;
    vaciar(actividad, h('option', { value: '' }, '— (opcional)'),
      (c.actividades || []).filter((a) => a.estado === 'A' || !a.estado)
        .map((a) => h('option', { value: String(a.codigo).padStart(6, '0') }, `${a.codigo} · ${a.descripcion}`)));
    const s = c.situacion || {};
    const alertas = [];
    if (s.moroso === 'SI') alertas.push('moroso');
    if (s.omiso === 'SI') alertas.push('omiso');
    if (s.estado && s.estado !== 'Inscrito') alertas.push(`estado: ${s.estado}`);
    vaciar(info, alertas.length
      ? aviso(`Atención: el contribuyente aparece ${alertas.join(', ')} en Hacienda.`, 'alerta')
      : aviso(`${c.nombre} · ${c.regimen?.descripcion || ''} · ${s.estado || ''}`, 'ok'));
  }) }, 'Buscar en Hacienda');

  const seccion = h('section', { class: 'tarjeta' }, h('h2', {}, titulo),
    h('div', { class: 'campos' },
      campo('Tipo de identificación', tipo),
      h('div', { class: 'fila doble' }, campo('Identificación', numero), buscar),
      campo('Nombre', nombre), campo('Correo', correo), campo('Actividad económica', actividad)),
    conUbicacion ? h('div', { class: 'campos' }, campo('Provincia', ubic.provincia), campo('Cantón', ubic.canton),
      campo('Distrito', ubic.distrito), campo('Otras señas', ubic.otras_senas)) : null,
    info);

  return {
    seccion,
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
  };
}

// ---------------------------------------------------------------------------
// Línea de detalle
// ---------------------------------------------------------------------------
function crearLinea(alCambiar, alQuitar) {
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

  const validarExo = h('button', { type: 'button', class: 'chico', onclick: () => conBoton(validarExo, async () => {
    if (!c.exoAut.value.trim()) { toast('Indique el número de autorización', 'error'); return; }
    const ex = await api(`/hacienda/exoneraciones/${encodeURIComponent(c.exoAut.value.trim())}`);
    if (ex.tipoDocumento?.codigo) c.exoTipo.value = String(ex.tipoDocumento.codigo).padStart(2, '0');
    if (ex.fechaEmision) c.exoFecha.value = String(ex.fechaEmision).slice(0, 10);
    const pct = Number(ex.porcentajeExoneracion ?? ex.tarifaExonerada);
    if (!Number.isNaN(pct) && pct > 0) c.exoTarifa.value = String(pct > 13 ? 13 * pct / 100 : pct);
    vaciar(exoInfo, aviso(
      `${ex.nombreInstitucion || ''} · vence ${String(ex.fechaVencimiento || '').slice(0, 10)} · identificación ${ex.identificacion || ''}`,
      'ok'));
  }) }, 'Validar en Hacienda');

  const buscarCabys = h('button', { type: 'button', class: 'chico', title: 'Buscar CABYS', onclick: () => dialogoCabys((item) => {
    c.cabys.value = item.codigo;
    if (!c.descripcion.value) c.descripcion.value = String(item.descripcion).slice(0, 200);
    const t = TARIFA_POR_PORCENTAJE[Number(item.impuesto)];
    if (t) c.tarifa.value = t;
    alCambiar();
  }) }, '🔍');

  const extra = h('tr', { class: 'extra oculto' }, h('td', { colspan: '10' },
    h('div', { class: 'campos' },
      campo('Código comercial', c.codigoComercial), campo('Código de descuento', c.codigoDescuento),
      campo('Partida arancelaria (exportación)', c.partida), campo('IVA a nivel de fábrica', c.fabrica),
      campo('Factor IVA bienes usados', c.factor),
      h('label', { class: 'check' }, c.noSujeto, 'No sujeto a IVA'),
      h('label', { class: 'check' }, c.asumido, 'Impuesto asumido por el emisor')),
    h('h3', {}, 'Exoneración'),
    h('div', { class: 'campos' },
      h('div', { class: 'fila' }, campo('Autorización', c.exoAut), validarExo),
      campo('Tipo de documento', c.exoTipo), campo('Institución', c.exoInst), campo('Fecha de emisión', c.exoFecha),
      campo('Tarifa exonerada (puntos)', c.exoTarifa)),
    exoInfo));

  const fila = h('tr', {},
    h('td', {}, h('div', { class: 'fila' }, c.cabys, buscarCabys)),
    h('td', {}, c.descripcion), h('td', {}, c.cantidad), h('td', {}, c.unidad), h('td', {}, c.precio),
    h('td', {}, c.descuento), h('td', {}, c.tarifa), h('td', { class: 'num' }, total),
    h('td', {}, h('button', { type: 'button', class: 'chico', title: 'Opciones', onclick: () => extra.classList.toggle('oculto') }, '⚙')),
    h('td', {}, h('button', { type: 'button', class: 'chico peligro', title: 'Quitar', onclick: () => { fila.remove(); extra.remove(); alQuitar(linea); } }, '✕')));

  [c.cantidad, c.precio, c.descuento, c.tarifa, c.noSujeto, c.fabrica, c.asumido, c.exoTarifa, c.factor]
    .forEach((el) => el.addEventListener('input', alCambiar));

  const linea = {
    filas: [fila, extra],
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

function dialogoCabys(alElegir) {
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

  const receptor = bloquePersona('Cliente (receptor)');
  const proveedor = bloquePersona('Proveedor (factura de compra)', { conUbicacion: true });

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
  const recalcular = () => {
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
    const l = crearLinea(recalcular, (x) => { lineas.splice(lineas.indexOf(x), 1); recalcular(); });
    lineas.push(l);
    cuerpoLineas.append(...l.filas);
    recalcular();
  };
  agregarLinea();
  [servicio10, ivaDevuelto, moneda].forEach((el) => el.addEventListener('input', recalcular));

  const consultarTc = h('button', { type: 'button', onclick: () => conBoton(consultarTc, async () => {
    if (moneda.value === 'CRC') { tipoCambio.value = ''; return; }
    const r = await api(`/hacienda/tipo-cambio/${moneda.value}`);
    tipoCambio.value = r.tipo_cambio;
  }) }, 'Consultar');

  const campoFecha = campo('Fecha real de la venta', fechaEmision);
  const campoPlazo = campo('Plazo de crédito', plazo);
  const campoDevuelto = campo('IVA devuelto', ivaDevuelto);
  const mensaje = h('div');

  const actualizarVisibilidad = () => {
    const t = tipo.value;
    receptor.seccion.classList.toggle('oculto', t === '08');
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
  proveedor.seccion,
  h('section', { class: 'tarjeta' }, h('h2', {}, 'Detalle'),
    h('div', { class: 'tabla' }, h('table', { class: 'lineas' },
      h('thead', {}, h('tr', {}, ['CABYS', 'Descripción', 'Cantidad', 'Unidad', 'Precio unit.', 'Descuento', 'IVA', 'Total', '', '']
        .map((t) => h('th', {}, t)))),
      cuerpoLineas)),
    h('div', { class: 'acciones' }, h('button', { type: 'button', onclick: agregarLinea }, '+ Agregar línea'),
      h('label', { class: 'check' }, servicio10, 'Cobrar impuesto de servicio 10% (restaurantes)'))),
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
