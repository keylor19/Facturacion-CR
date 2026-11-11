// Módulo de contabilidad: solo para usuarios contadores. Trabaja sobre la empresa elegida en el selector.
import { api, descargar, sesion } from '../api.js';
import { h, vaciar, dinero, tabla, modal, conBoton, toast, campo, aviso, opciones, mesActual, selectorMes } from '../dom.js';
import { TIPOS_IDENTIFICACION } from '../catalogos.js';
import { selectorUbicacion } from '../ubicacion.js';
import { contexto, empresaActual } from '../app.js';

const TIPOS_CUENTA = { activo: 'Activo', pasivo: 'Pasivo', patrimonio: 'Patrimonio', ingreso: 'Ingreso', costo: 'Costo', gasto: 'Gasto' };
const CLAVES = {
  caja_bancos: 'Cobros y pagos de contado', clientes: 'Ventas a crédito', iva_credito: 'IVA de compras',
  iva_debito: 'IVA de ventas', proveedores: 'Compras', ventas: 'Ventas', devoluciones_ventas: 'Notas de crédito',
  otros_ingresos: 'Otros cargos / redondeo', compras_gastos: 'Gasto de las compras', otros_gastos: 'Redondeo',
};
const ORIGEN = {
  manual: 'Manual', venta: 'Venta', compra: 'Compra', cobro: 'Cobro', apertura: 'Apertura',
  costo: 'Costo de ventas', inventario: 'Inventario', cierre: 'Cierre del año',
};
const TIPO_DOC = { '01': 'Factura', '02': 'Nota de débito', '03': 'Nota de crédito', '04': 'Tiquete', '08': 'Fact. compra', '09': 'Exportación', '10': 'Recibo de pago' };
const hoyIso = () => new Date().toLocaleDateString('en-CA');
const inicioMes = () => `${hoyIso().slice(0, 8)}01`;
const fechaCorta = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('es-CR') : '');
const sufijo = () => empresaActual()?.numero_identificacion || 'empresa';
const err = (e) => toast(e.message, 'error');

function rango(alCambiar, { desde = inicioMes(), hasta = hoyIso() } = {}) {
  const d = h('input', { type: 'date', value: desde });
  const a = h('input', { type: 'date', value: hasta });
  [d, a].forEach((el) => el.addEventListener('change', () => alCambiar(d.value, a.value)));
  return { nodo: h('div', { class: 'fila' }, campo('Desde', d), campo('Hasta', a)), valor: () => [d.value, a.value] };
}

const botonImprimir = () => h('button', { type: 'button', class: 'no-imprimir', onclick: () => window.print() }, 'Imprimir');

// --- Mis empresas ---------------------------------------------------------------------------------

function dialogoAgregarEmpresa(alTerminar) {
  const tipo = h('select', {}, opciones(TIPOS_IDENTIFICACION, '02'));
  const cedula = h('input', { type: 'text', inputmode: 'numeric', maxlength: '12', placeholder: 'Sin guiones' });
  const nombre = h('input', { type: 'text', maxlength: '100' });
  const actividad = h('input', { type: 'text', maxlength: '6', placeholder: '6 dígitos' });
  const correo = h('input', { type: 'email' });
  const telefono = h('input', { type: 'tel', maxlength: '20' });
  const lugar = selectorUbicacion();
  const senas = h('input', { type: 'text', maxlength: '250' });
  const buscar = h('button', { type: 'button', onclick: () => conBoton(buscar, async () => {
    const r = await api(`/hacienda/contribuyentes/${cedula.value.replace(/\D/g, '')}`);
    nombre.value = r.nombre || nombre.value;
    if (r.tipoIdentificacion) tipo.value = r.tipoIdentificacion;
    const act = (r.actividades || []).find((a) => a.tipo === 'P') || (r.actividades || [])[0];
    if (act) actividad.value = String(act.codigo).padStart(6, '0');
  }) }, 'Buscar en Hacienda');
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const e = await api('/contabilidad/empresas', { method: 'POST', body: {
      tipo_identificacion: tipo.value, numero_identificacion: cedula.value.replace(/\D/g, ''), nombre: nombre.value.trim(),
      codigo_actividad: actividad.value.trim(), correo: correo.value.trim(), telefono: telefono.value.replace(/\D/g, '') || null,
      provincia: lugar.provincia.value, canton: lugar.canton.value, distrito: lugar.distrito.value, otras_senas: senas.value.trim(),
    } });
    m.cerrar();
    toast('Empresa agregada con el catálogo de cuentas base', 'ok');
    sesion.emisorId = e.id;
    alTerminar();
  }) }, 'Agregar');
  const m = modal('Inscribir una empresa nueva', [
    h('p', { class: 'suave' }, 'Para llevarle la contabilidad a una empresa que no factura en este sistema: después carga sus XML de '
      + 'Hacienda (ventas y compras). Si la empresa ya factura aquí, use «Empresa ya inscrita».'),
    h('div', { class: 'campos' }, campo('Tipo', tipo), h('div', { class: 'fila doble' }, campo('Cédula', cedula), buscar),
      campo('Nombre o razón social', nombre), campo('Actividad económica', actividad), campo('Correo', correo), campo('Teléfono', telefono),
      campo('Provincia', lugar.provincia), campo('Cantón', lugar.canton), campo('Distrito', lugar.distrito), campo('Otras señas', senas)),
  ], { acciones: [guardar], ancho: true });
}

// La empresa ya factura en el sistema: se busca por cédula exacta y el contador empieza a llevarla
function dialogoEmpresaInscrita(alTerminar) {
  const cedula = h('input', { type: 'text', inputmode: 'numeric', maxlength: '12', placeholder: 'Cédula sin guiones' });
  const resultado = h('div');
  const buscar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(buscar, async () => {
    vaciar(resultado);
    let e;
    try {
      e = await api(`/contabilidad/buscar-empresa?cedula=${cedula.value.replace(/\D/g, '')}`, { conEmisor: false });
    } catch (ex) {
      vaciar(resultado, aviso(ex.status === 404 ? `${ex.message}. Use «Inscribir empresa nueva».` : ex.message, ex.status === 404 ? 'info' : 'error'));
      return;
    }
    if (e.ya_la_lleva) { vaciar(resultado, aviso(`Ya lleva la contabilidad de ${e.nombre}.`, 'info')); return; }
    const tomar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(tomar, async () => {
      await api(`/contabilidad/empresas/${e.id}/vincular`, { method: 'POST', conEmisor: false });
      m.cerrar();
      toast(`Ahora lleva la contabilidad de ${e.nombre}. Se le avisó a la empresa.`, 'ok');
      sesion.emisorId = e.id;
      alTerminar();
    }) }, 'Llevar su contabilidad');
    vaciar(resultado, h('div', { class: 'aviso ok' }, h('strong', {}, e.nombre), ` · ${e.identificacion} `), tomar);
  }) }, 'Buscar');
  const m = modal('Empresa ya inscrita', [
    h('p', { class: 'suave' }, 'Escriba la cédula de una empresa que ya factura en el sistema. Va a ver su contabilidad (no factura ni cambia nada) '
      + 'y a la empresa le llega un aviso: el dueño puede quitarle el acceso cuando quiera.'),
    h('div', { class: 'fila' }, campo('Cédula', cedula), buscar),
    resultado,
  ]);
}

export async function vistaContaInicio(cont) {
  if (!contexto.esContador) { location.hash = '#/conta/documentos'; return; }
  const refrescar = () => vistaContaInicio(cont).catch(err);
  const lista = await api('/contabilidad/empresas', { conEmisor: false });
  const abrir = (e, ruta = '#/conta/documentos') => { sesion.emisorId = e.id; location.hash = ruta; };
  const dejar = (e) => h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => {
    ev.stopPropagation();
    conBoton(ev.target, async () => {
      if (!window.confirm(`¿Dejar de llevar la contabilidad de ${e.nombre}? Sus asientos se conservan.`)) return;
      await api(`/contabilidad/empresas/${e.id}/vincular`, { method: 'DELETE', conEmisor: false });
      refrescar();
    });
  } }, 'Dejar de llevarla');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Mis empresas'),
      h('div', { class: 'acciones' },
        h('button', { type: 'button', onclick: () => dialogoEmpresaInscrita(refrescar) }, 'Empresa ya inscrita'),
        h('button', { type: 'button', class: 'primario', onclick: () => dialogoAgregarEmpresa(refrescar) }, '+ Inscribir empresa nueva'))),
    h('p', { class: 'suave' }, 'Escoja las empresas que ya facturan en el sistema (por su cédula) o inscriba las que no. Toque una para trabajar en ella.'),
    lista.length ? h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Empresa', valor: (e) => [e.nombre, h('div', { class: 'suave mono' }, e.identificacion)] },
      { titulo: 'Origen', valor: (e) => (e.factura_aqui ? 'Factura en el sistema' : 'Carga de XML') },
      { titulo: 'Catálogo', valor: (e) => (e.tiene_catalogo ? 'Listo' : h('span', { class: 'badge CONTINGENCIA' }, 'Falta')) },
      { titulo: 'Este mes', num: true, valor: (e) => [String(e.documentos_mes),
        e.sin_contabilizar ? h('div', {}, h('span', { class: 'badge CONTINGENCIA' }, `${e.sin_contabilizar} sin contabilizar`)) : null] },
      { titulo: 'Último cierre', valor: (e) => (e.ultimo_cierre ? fechaCorta(e.ultimo_cierre).slice(3) : '—') },
      { titulo: '', valor: (e) => (e.propia ? null : dejar(e)) },
    ], lista, (e) => abrir(e))) : aviso('Todavía no tiene empresas. Busque una ya inscrita por su cédula o inscriba una nueva.', 'info'));
}

// --- Catálogo de cuentas ---------------------------------------------------------------------

function dialogoCuenta(cuenta, alGuardar) {
  const c = cuenta || {};
  const codigo = h('input', { type: 'text', maxlength: '30', value: c.codigo || '', placeholder: '1.1.07' });
  const nombre = h('input', { type: 'text', maxlength: '150', value: c.nombre || '' });
  const tipo = h('select', {}, opciones(TIPOS_CUENTA, c.tipo || 'gasto'));
  const movimientos = h('input', { type: 'checkbox', checked: c.acepta_movimientos ?? true });
  const activa = h('input', { type: 'checkbox', checked: c.activa ?? true });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const body = { codigo: codigo.value.trim(), nombre: nombre.value.trim(), tipo: tipo.value,
      acepta_movimientos: movimientos.checked, activa: activa.checked };
    if (c.id) await api(`/contabilidad/cuentas/${c.id}`, { method: 'PUT', body });
    else await api('/contabilidad/cuentas', { method: 'POST', body });
    m.cerrar();
    alGuardar();
  }) }, 'Guardar');
  const m = modal(c.id ? `Cuenta ${c.codigo}` : 'Nueva cuenta', [
    h('div', { class: 'campos' }, campo('Código (con puntos)', codigo), campo('Nombre', nombre), campo('Tipo', tipo)),
    h('label', { class: 'check' }, movimientos, 'Acepta movimientos (si no, es una cuenta de grupo que suma a sus hijas)'),
    h('label', { class: 'check' }, activa, 'Activa'),
    c.clave_sistema ? aviso(`Los asientos automáticos la usan para: ${CLAVES[c.clave_sistema] || c.clave_sistema}.`, 'info') : null,
  ], { acciones: [guardar] });
}

export async function vistaContaCuentas(cont) {
  const refrescar = () => vistaContaCuentas(cont).catch(err);
  const lista = await api('/contabilidad/cuentas');
  const crearBase = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(crearBase, async () => {
    await api('/contabilidad/catalogo-base', { method: 'POST' });
    toast('Catálogo base creado', 'ok');
    refrescar();
  }) }, 'Crear catálogo base');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Catálogo de cuentas'),
      h('div', { class: 'acciones' }, lista.length ? null : crearBase,
        h('button', { type: 'button', onclick: () => dialogoCuenta(null, refrescar) }, '+ Nueva cuenta'))),
    lista.length ? null : aviso('Esta empresa no tiene catálogo. Cree el catálogo base (NIIF para PYMES) y ajústelo a la empresa.', 'info'),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Código', valor: (c) => h('span', { class: `mono nivel-${Math.min(c.nivel, 4)}` }, c.codigo) },
      { titulo: 'Cuenta', valor: (c) => [c.acepta_movimientos ? c.nombre : h('strong', {}, c.nombre),
        c.clave_sistema ? h('div', { class: 'suave' }, `Automático: ${CLAVES[c.clave_sistema] || c.clave_sistema}`) : null] },
      { titulo: 'Tipo', valor: (c) => TIPOS_CUENTA[c.tipo] },
      { titulo: 'Movimientos', valor: (c) => (c.acepta_movimientos ? 'Sí' : 'Grupo') },
      { titulo: 'Estado', valor: (c) => (c.activa ? 'Activa' : h('span', { class: 'badge' }, 'Inactiva')) },
    ], lista, (c) => dialogoCuenta(c, refrescar))));
}

// --- Asientos ------------------------------------------------------------------------------------

async function dialogoAsiento(existente, alGuardar) {
  const cuentas = (await api('/contabilidad/cuentas')).filter((c) => c.acepta_movimientos && c.activa);
  if (!cuentas.length) { toast('Primero cree el catálogo de cuentas', 'error'); return; }
  const a = existente || { fecha: hoyIso(), descripcion: '', lineas: [] };
  const fecha = h('input', { type: 'date', value: a.fecha });
  const descripcion = h('input', { type: 'text', maxlength: '300', value: a.descripcion, placeholder: 'Ej.: Pago de planilla de octubre' });
  const cuerpo = h('tbody');
  const totales = h('div', { class: 'total-venta' });
  const filas = [];
  const recalcular = () => {
    const d = filas.reduce((s, f) => s + Number(f.debe.value || 0), 0);
    const hb = filas.reduce((s, f) => s + Number(f.haber.value || 0), 0);
    const dif = Math.round((d - hb) * 100) / 100;
    totales.textContent = `Debe ${dinero(d)} · Haber ${dinero(hb)}${dif ? ` · Diferencia ${dinero(Math.abs(dif))}` : ' · Cuadra'}`;
    totales.classList.toggle('descuadre', dif !== 0);
  };
  const agregar = (ln = {}) => {
    const f = {
      cuenta: h('select', {}, h('option', { value: '' }, '— cuenta —'),
        cuentas.map((c) => h('option', { value: c.id, selected: c.id === ln.cuenta_id }, `${c.codigo} ${c.nombre}`))),
      debe: h('input', { type: 'number', step: '0.01', min: '0', value: Number(ln.debe) ? ln.debe : '' }),
      haber: h('input', { type: 'number', step: '0.01', min: '0', value: Number(ln.haber) ? ln.haber : '' }),
      detalle: h('input', { type: 'text', maxlength: '200', value: ln.detalle || '' }),
    };
    f.tr = h('tr', {}, h('td', {}, f.cuenta), h('td', {}, f.debe), h('td', {}, f.haber), h('td', {}, f.detalle),
      h('td', {}, h('button', { type: 'button', class: 'chico', onclick: () => { filas.splice(filas.indexOf(f), 1); f.tr.remove(); recalcular(); } }, '✕')));
    [f.debe, f.haber].forEach((el) => el.addEventListener('input', recalcular));
    filas.push(f);
    cuerpo.append(f.tr);
  };
  (a.lineas.length ? a.lineas : [{}, {}]).forEach(agregar);
  recalcular();
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const body = { fecha: fecha.value, descripcion: descripcion.value.trim(),
      lineas: filas.filter((f) => f.cuenta.value).map((f) => ({ cuenta_id: f.cuenta.value, debe: f.debe.value || '0',
        haber: f.haber.value || '0', detalle: f.detalle.value.trim() || null })) };
    if (a.id) await api(`/contabilidad/asientos/${a.id}`, { method: 'PUT', body });
    else await api('/contabilidad/asientos', { method: 'POST', body });
    m.cerrar();
    toast('Asiento guardado', 'ok');
    alGuardar();
  }) }, 'Guardar');
  const m = modal(a.id ? `Asiento ${a.numero}` : 'Nuevo asiento', [
    h('div', { class: 'campos' }, campo('Fecha', fecha), campo('Descripción', descripcion)),
    a.origen && a.origen !== 'manual' ? aviso('Asiento automático: si lo cambia queda marcado como corregido a mano.', 'info') : null,
    h('div', { class: 'tabla' }, h('table', { class: 'lineas-asiento' },
      h('thead', {}, h('tr', {}, ['Cuenta', 'Debe', 'Haber', 'Detalle', ''].map((t) => h('th', {}, t)))), cuerpo)),
    h('button', { type: 'button', class: 'chico', onclick: () => agregar() }, '+ Línea'),
    totales,
  ], { acciones: [guardar], ancho: true });
}

export async function vistaContaAsientos(cont) {
  const lista = h('div');
  const q = h('input', { type: 'search', placeholder: 'Número o descripción' });
  const r = rango(() => cargar().catch(err));
  async function cargar() {
    const [desde, hasta] = r.valor();
    const asientos = await api(`/contabilidad/asientos?desde=${desde}&hasta=${hasta}${q.value.trim() ? `&q=${encodeURIComponent(q.value.trim())}` : ''}`);
    const anular = (a) => h('button', { type: 'button', class: 'chico peligro', onclick: (e) => {
      e.stopPropagation();
      conBoton(e.target, async () => {
        if (!window.confirm(`¿Anular el asiento ${a.numero}?`)) return;
        await api(`/contabilidad/asientos/${a.id}/anular`, { method: 'POST' });
        cargar().catch(err);
      });
    } }, 'Anular');
    vaciar(lista, asientos.length ? asientos.map((a) => h('section', { class: `tarjeta asiento ${a.anulado ? 'anulado' : ''}`,
      onclick: () => { if (!a.anulado) dialogoAsiento(a, () => cargar().catch(err)).catch(err); } },
    h('div', { class: 'encabezado' }, h('div', {}, h('strong', {}, `N.º ${a.numero} · ${fechaCorta(a.fecha)}`), ` ${a.descripcion}`,
      h('div', { class: 'suave' }, `${ORIGEN[a.origen] || a.origen}${a.editado ? ' · corregido a mano' : ''}${a.anulado ? ' · ANULADO' : ''}`)),
    a.anulado ? null : h('span', { class: 'no-imprimir' }, anular(a))),
    tabla([
      { titulo: 'Cuenta', valor: (ln) => `${ln.codigo} ${ln.nombre}` },
      { titulo: 'Detalle', valor: (ln) => ln.detalle || '' },
      { titulo: 'Debe', num: true, valor: (ln) => (Number(ln.debe) ? dinero(ln.debe) : '') },
      { titulo: 'Haber', num: true, valor: (ln) => (Number(ln.haber) ? dinero(ln.haber) : '') },
    ], a.lineas))) : aviso('No hay asientos en esas fechas.', 'info'));
  }
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter') cargar().catch(err); });
  const csv = h('button', { type: 'button', onclick: () => conBoton(csv, () => {
    const [desde, hasta] = r.valor();
    return descargar(`/contabilidad/asientos?desde=${desde}&hasta=${hasta}&formato=csv`, `diario-${sufijo()}-${desde}-${hasta}.csv`);
  }) }, 'Excel');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Libro diario'),
      h('div', { class: 'acciones no-imprimir' }, csv, botonImprimir(),
        h('button', { type: 'button', class: 'primario', onclick: () => dialogoAsiento(null, () => cargar().catch(err)).catch(err) }, '+ Nuevo asiento'))),
    h('div', { class: 'fila no-imprimir' }, r.nodo, campo('Buscar', q)),
    lista);
  await cargar();
}

// --- Comprobantes del mes: contabilizar y cargar XML -----------------------------------------------

export async function vistaContaDocumentos(cont) {
  let periodo = mesActual();
  const cuerpo = h('div');
  const empresas = await api('/contabilidad/empresas', { conEmisor: false });
  const actual = empresas.find((e) => e.id === sesion.emisorId) || empresas[0];
  async function cargar() {
    const d = await api(`/contabilidad/documentos?anio=${periodo.anio}&mes=${periodo.mes}`);
    const pendientes = [...d.ventas, ...d.compras].filter((x) => !x.asiento).length;
    const contabilizar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(contabilizar, async () => {
      const r = await api('/contabilidad/contabilizar', { method: 'POST', body: { anio: periodo.anio, mes: periodo.mes } });
      toast(r.creados ? `${r.creados} asiento(s) creados` : 'No había comprobantes nuevos', 'ok');
      if (r.productos_sin_costo?.length) {
        modal('Productos sin costo', [aviso('Estos productos se movieron en el inventario sin costo, así que su costo de ventas no se calculó. '
          + 'Póngales el costo en Mis productos (o registre la entrada con costo) y vuelva a contabilizar.', 'alerta'),
        h('ul', {}, r.productos_sin_costo.map((p) => h('li', {}, p)))]);
      }
      cargar().catch(err);
    }) }, `Contabilizar el mes${pendientes ? ` (${pendientes} pendientes)` : ''}`);
    const columnas = (ventas) => [
      { titulo: 'Fecha', valor: (x) => fechaCorta(x.fecha) },
      { titulo: 'Documento', valor: (x) => [TIPO_DOC[x.tipo_documento] || x.tipo_documento, h('div', { class: 'suave mono' }, x.consecutivo || x.clave?.slice(21, 41) || '')] },
      { titulo: ventas ? 'Cliente' : 'Proveedor', valor: (x) => x.contraparte || '—' },
      { titulo: 'IVA (₡)', num: true, valor: (x) => dinero(x.impuesto_crc) },
      { titulo: 'Total (₡)', num: true, valor: (x) => dinero(x.total_crc) },
      { titulo: 'Asiento', valor: (x) => (x.asiento ? `N.º ${x.asiento}` : h('span', { class: 'badge CONTINGENCIA' }, 'Pendiente')) },
    ];
    vaciar(cuerpo,
      h('div', { class: 'acciones' }, contabilizar),
      h('p', { class: 'suave' }, 'Contabilizar crea el asiento de cada comprobante aceptado que todavía no lo tenga (ventas, notas, recibos, '
        + 'compras y abonos de clientes) y el costo de ventas desde el inventario. Puede correrlo cuantas veces quiera: no duplica.'),
      h('section', { class: 'tarjeta' }, h('h2', {}, `Ventas (${d.ventas.length})`), tabla(columnas(true), d.ventas)),
      h('section', { class: 'tarjeta' }, h('h2', {}, `Compras (${d.compras.length})`), tabla(columnas(false), d.compras)));
  }
  const archivos = h('input', { type: 'file', multiple: true, accept: '.xml,text/xml,application/xml' });
  const subir = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(subir, async () => {
    if (!archivos.files.length) { toast('Seleccione los XML', 'error'); return; }
    const form = new FormData();
    for (const f of archivos.files) form.append('archivos', f);
    const r = await api('/contabilidad/importar', { method: 'POST', form });
    archivos.value = '';
    toast(`${r.ventas} venta(s) y ${r.compras} compra(s) cargadas${r.errores.length ? `; ${r.errores.length} con error` : ''}`, r.errores.length ? '' : 'ok');
    if (r.errores.length) modal('Archivos que no se cargaron', [tabla([{ titulo: 'Archivo', valor: (x) => x.archivo }, { titulo: 'Motivo', valor: (x) => x.error }], r.errores)]);
    cargar().catch(err);
  }) }, 'Cargar');
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Comprobantes del mes'),
      selectorMes(periodo, (p) => { periodo = p; cargar().catch(err); })),
    actual && !actual.factura_aqui ? h('section', { class: 'tarjeta' }, h('h2', {}, 'Cargar XML de Hacienda'),
      h('p', { class: 'suave' }, 'Seleccione los XML de las facturas, tiquetes y notas que emitió la empresa y de las facturas de sus proveedores. '
        + 'El sistema distingue solo las ventas de las compras y no carga dos veces el mismo comprobante.'),
      h('div', { class: 'fila' }, archivos, subir)) : null,
    cuerpo);
  await cargar();
}

// --- Reportes contables ------------------------------------------------------------------------

function filasArbol(cuentas) {
  return tabla([
    { titulo: 'Cuenta', valor: (c) => h('span', { class: `nivel-${Math.min(c.nivel, 4)}` }, c.grupo ? h('strong', {}, `${c.codigo} ${c.nombre}`) : `${c.codigo} ${c.nombre}`) },
    { titulo: 'Saldo', num: true, valor: (c) => (c.grupo ? h('strong', {}, dinero(c.saldo)) : dinero(c.saldo)) },
  ], cuentas);
}

export async function vistaContaComprobacion(cont) {
  const cuerpo = h('div');
  const r = rango(() => cargar().catch(err), { desde: `${hoyIso().slice(0, 4)}-01-01` });
  async function cargar() {
    const [desde, hasta] = r.valor();
    const b = await api(`/contabilidad/reportes/comprobacion?desde=${desde}&hasta=${hasta}`);
    const t = b.totales;
    vaciar(cuerpo,
      b.cuadra ? null : aviso('Las sumas no cuadran: revise asientos editados.', 'error'),
      h('section', { class: 'tarjeta' }, tabla([
        { titulo: 'Cuenta', valor: (c) => `${c.codigo} ${c.nombre}` },
        { titulo: 'Saldo inicial', num: true, valor: (c) => dinero(c.saldo_inicial) },
        { titulo: 'Debe', num: true, valor: (c) => dinero(c.debe) },
        { titulo: 'Haber', num: true, valor: (c) => dinero(c.haber) },
        { titulo: 'Saldo deudor', num: true, valor: (c) => (Number(c.saldo_deudor) ? dinero(c.saldo_deudor) : '') },
        { titulo: 'Saldo acreedor', num: true, valor: (c) => (Number(c.saldo_acreedor) ? dinero(c.saldo_acreedor) : '') },
      ], b.cuentas),
      h('p', {}, h('strong', {}, `Totales: debe ${dinero(t.debe || 0)} · haber ${dinero(t.haber || 0)} · deudor ${dinero(t.deudor || 0)} · acreedor ${dinero(t.acreedor || 0)}`))));
  }
  vaciar(cont, h('div', { class: 'encabezado' }, h('h1', {}, 'Balance de comprobación'),
    h('div', { class: 'acciones no-imprimir' }, h('button', { type: 'button', onclick: (e) => conBoton(e.target, () => {
      const [desde, hasta] = r.valor();
      return descargar(`/contabilidad/reportes/comprobacion?desde=${desde}&hasta=${hasta}&formato=csv`, `comprobacion-${sufijo()}.csv`);
    }) }, 'Excel'), botonImprimir())),
  h('div', { class: 'no-imprimir' }, r.nodo), cuerpo);
  await cargar();
}

export async function vistaContaResultados(cont) {
  const cuerpo = h('div');
  const r = rango(() => cargar().catch(err), { desde: `${hoyIso().slice(0, 4)}-01-01` });
  async function cargar() {
    const [desde, hasta] = r.valor();
    const e = await api(`/contabilidad/reportes/resultados?desde=${desde}&hasta=${hasta}`);
    vaciar(cuerpo, h('section', { class: 'tarjeta' }, filasArbol(e.cuentas),
      h('dl', { class: 'datos' },
        h('dt', {}, 'Ingresos'), h('dd', {}, dinero(e.ingresos)), h('dt', {}, 'Costos'), h('dd', {}, dinero(e.costos)),
        h('dt', {}, 'Utilidad bruta'), h('dd', {}, dinero(e.utilidad_bruta)), h('dt', {}, 'Gastos'), h('dd', {}, dinero(e.gastos)),
        h('dt', {}, 'Utilidad (pérdida) neta'), h('dd', {}, h('strong', {}, dinero(e.utilidad_neta))))));
  }
  vaciar(cont, h('div', { class: 'encabezado' }, h('h1', {}, 'Estado de resultados'),
    h('div', { class: 'acciones no-imprimir' }, h('button', { type: 'button', onclick: (ev) => conBoton(ev.target, () => {
      const [desde, hasta] = r.valor();
      return descargar(`/contabilidad/reportes/resultados?desde=${desde}&hasta=${hasta}&formato=csv`, `resultados-${sufijo()}.csv`);
    }) }, 'Excel'), botonImprimir())),
  h('div', { class: 'no-imprimir' }, r.nodo), cuerpo);
  await cargar();
}

export async function vistaContaBalance(cont) {
  const cuerpo = h('div');
  const fecha = h('input', { type: 'date', value: hoyIso(), onchange: () => cargar().catch(err) });
  async function cargar() {
    const b = await api(`/contabilidad/reportes/balance?fecha=${fecha.value}`);
    vaciar(cuerpo,
      b.cuadra ? null : aviso('El balance no cuadra: revise los asientos.', 'error'),
      h('div', { class: 'campos dos' },
        h('section', { class: 'tarjeta' }, h('h2', {}, 'Activo'), filasArbol(b.activo),
          h('p', {}, h('strong', {}, `Total activo: ${dinero(b.total_activo)}`))),
        h('section', { class: 'tarjeta' }, h('h2', {}, 'Pasivo'), filasArbol(b.pasivo),
          h('h2', {}, 'Patrimonio'), filasArbol(b.patrimonio),
          h('p', {}, `Resultado acumulado (ingresos − costos − gastos): ${dinero(b.resultado_acumulado)}`),
          h('p', {}, h('strong', {}, `Total pasivo y patrimonio: ${dinero(b.total_pasivo_patrimonio)}`)))));
  }
  vaciar(cont, h('div', { class: 'encabezado' }, h('h1', {}, 'Balance general'),
    h('div', { class: 'acciones no-imprimir' }, h('button', { type: 'button', onclick: (ev) => conBoton(ev.target,
      () => descargar(`/contabilidad/reportes/balance?fecha=${fecha.value}&formato=csv`, `balance-${sufijo()}-${fecha.value}.csv`)) }, 'Excel'),
    botonImprimir())),
  h('div', { class: 'fila no-imprimir' }, campo('Al', fecha)), cuerpo);
  await cargar();
}

export async function vistaContaMayor(cont) {
  const cuentas = (await api('/contabilidad/cuentas')).filter((c) => c.acepta_movimientos);
  const cuerpo = h('div');
  const cuenta = h('select', { onchange: () => cargar().catch(err) }, cuentas.map((c) => h('option', { value: c.id }, `${c.codigo} ${c.nombre}`)));
  const r = rango(() => cargar().catch(err));
  async function cargar() {
    if (!cuenta.value) { vaciar(cuerpo, aviso('Primero cree el catálogo de cuentas.', 'info')); return; }
    const [desde, hasta] = r.valor();
    const m = await api(`/contabilidad/reportes/mayor?cuenta_id=${cuenta.value}&desde=${desde}&hasta=${hasta}`);
    vaciar(cuerpo, h('section', { class: 'tarjeta' },
      h('p', {}, `Saldo inicial: ${dinero(m.saldo_inicial)}`),
      tabla([
        { titulo: 'Fecha', valor: (x) => fechaCorta(x.fecha) },
        { titulo: 'Asiento', valor: (x) => `N.º ${x.numero}` },
        { titulo: 'Descripción', valor: (x) => [x.descripcion, x.detalle ? h('div', { class: 'suave' }, x.detalle) : null] },
        { titulo: 'Debe', num: true, valor: (x) => (Number(x.debe) ? dinero(x.debe) : '') },
        { titulo: 'Haber', num: true, valor: (x) => (Number(x.haber) ? dinero(x.haber) : '') },
        { titulo: 'Saldo', num: true, valor: (x) => dinero(x.saldo) },
      ], m.movimientos),
      h('p', {}, h('strong', {}, `Saldo final: ${dinero(m.saldo_final)}`))));
  }
  vaciar(cont, h('div', { class: 'encabezado' }, h('h1', {}, 'Libro mayor'),
    h('div', { class: 'acciones no-imprimir' }, h('button', { type: 'button', onclick: (ev) => conBoton(ev.target, () => {
      const [desde, hasta] = r.valor();
      return descargar(`/contabilidad/reportes/mayor?cuenta_id=${cuenta.value}&desde=${desde}&hasta=${hasta}&formato=csv`, `mayor-${sufijo()}.csv`);
    }) }, 'Excel'), botonImprimir())),
  h('div', { class: 'fila no-imprimir' }, campo('Cuenta', cuenta), r.nodo), cuerpo);
  await cargar();
}

// --- Cierre de meses -----------------------------------------------------------------------------

export async function vistaContaPeriodos(cont) {
  const refrescar = () => vistaContaPeriodos(cont).catch(err);
  const lista = await api('/contabilidad/periodos');
  let periodo = mesActual();
  const cerrar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(cerrar, async () => {
    if (!window.confirm('Al cerrar el mes ya no se pueden crear, cambiar ni anular asientos de ese mes. ¿Continuar?')) return;
    await api('/contabilidad/periodos', { method: 'POST', body: { anio: periodo.anio, mes: periodo.mes } });
    toast('Mes cerrado', 'ok');
    refrescar();
  }) }, 'Cerrar mes');
  vaciar(cont,
    h('h1', {}, 'Cierre de meses'),
    h('section', { class: 'tarjeta' }, h('p', { class: 'suave' }, 'Cierre cada mes cuando ya lo declaró: así nadie cambia por error los asientos de ese mes.'),
      h('div', { class: 'fila' }, selectorMes(periodo, (p) => { periodo = p; }), cerrar)),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Meses cerrados'), tabla([
      { titulo: 'Mes', valor: (p) => new Date(`${p.mes}T12:00:00`).toLocaleDateString('es-CR', { month: 'long', year: 'numeric' }) },
      { titulo: 'Cerrado por', valor: (p) => p.cerrado_por || '' },
      { titulo: '', valor: (p) => h('button', { type: 'button', class: 'chico', onclick: (e) => conBoton(e.target, async () => {
        if (!window.confirm('¿Abrir de nuevo este mes?')) return;
        const [anio, mes] = p.mes.split('-');
        await api(`/contabilidad/periodos/${Number(anio)}/${Number(mes)}`, { method: 'DELETE' });
        refrescar();
      }) }, 'Abrir') },
    ], lista)));
}

// --- Asiento de cierre anual -----------------------------------------------------------------------

export async function vistaContaCierre(cont) {
  const anioActual = Number(hoyIso().slice(0, 4));
  const anio = h('select', { 'aria-label': 'Año' }, [0, 1, 2, 3, 4].map((i) => {
    const a = anioActual - i;
    return h('option', { value: String(a), selected: i === 1 }, String(a));
  }));
  const cuerpo = h('div');
  async function cargar() {
    const p = await api(`/contabilidad/cierre-anual?anio=${anio.value}`);
    const utilidad = Number(p.utilidad);
    const registrar = p.registrado || !p.lineas.length ? null : h('button', { type: 'button', class: 'primario no-imprimir', onclick: () => conBoton(registrar, async () => {
      if (!window.confirm(`¿Registrar el asiento de cierre de ${p.anio} con fecha 31/12/${p.anio}?`)) return;
      const a = await api('/contabilidad/cierre-anual', { method: 'POST', body: { anio: Number(anio.value) } });
      toast(`Asiento de cierre registrado (N.º ${a.numero})`, 'ok');
      cargar().catch(err);
    }) }, 'Registrar el asiento de cierre');
    const archivo = h('button', { type: 'button', class: 'no-imprimir', onclick: () => conBoton(archivo,
      () => descargar(`/contabilidad/cierre-anual?anio=${anio.value}&formato=csv`, `cierre-${anio.value}-${sufijo()}.csv`)) }, 'Descargar archivo (Excel)');
    vaciar(cuerpo,
      p.registrado ? aviso(`Ya está registrado como asiento N.º ${p.registrado.numero}. Si necesita rehacerlo, anúlelo en el libro diario.`, 'ok')
        : p.lineas.length ? aviso('Propuesta calculada con los asientos del año. Revísela, descárguela y regístrela; '
          + 'si lleva la contabilidad en otro sistema, cópiela de este archivo línea por línea.', 'info')
          : aviso('Ese año no tiene ingresos, costos ni gastos que cerrar.', 'info'),
      p.falta_cuenta ? aviso('Falta la cuenta de utilidades acumuladas en el catálogo (márquela con esa función).', 'error') : null,
      h('div', { class: 'acciones no-imprimir' }, archivo, botonImprimir(), registrar),
      h('section', { class: 'tarjeta' },
        h('h2', {}, `Asiento de cierre ${p.anio}`),
        h('dl', { class: 'datos' },
          h('dt', {}, 'Empresa'), h('dd', {}, empresaActual()?.nombre || ''),
          h('dt', {}, 'Fecha'), h('dd', {}, fechaCorta(p.fecha)),
          h('dt', {}, 'Descripción'), h('dd', {}, p.descripcion),
          h('dt', {}, utilidad >= 0 ? 'Utilidad del año' : 'Pérdida del año'), h('dd', {}, h('strong', {}, dinero(Math.abs(utilidad))))),
        tabla([
          { titulo: 'Cuenta', valor: (ln) => h('span', { class: 'mono' }, ln.codigo) },
          { titulo: 'Nombre', valor: (ln) => [ln.nombre, ln.detalle ? h('div', { class: 'suave' }, ln.detalle) : null] },
          { titulo: 'Debe', num: true, valor: (ln) => (Number(ln.debe) ? dinero(ln.debe) : '') },
          { titulo: 'Haber', num: true, valor: (ln) => (Number(ln.haber) ? dinero(ln.haber) : '') },
        ], p.lineas),
        h('p', {}, h('strong', {}, `Totales: debe ${dinero(p.total)} · haber ${dinero(p.total)}`))));
  }
  anio.addEventListener('change', () => cargar().catch(err));
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Cierre del año'), h('div', { class: 'no-imprimir' }, campo('Año', anio))),
    h('p', { class: 'suave no-imprimir' }, 'Deja en cero los ingresos, costos y gastos del año y pasa el resultado a utilidades acumuladas. '
      + 'Hágalo después de contabilizar y revisar diciembre. El estado de resultados del año no lo cuenta, así que sigue mostrando la utilidad.'),
    cuerpo);
  await cargar();
}
