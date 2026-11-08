// Empresas cliente (administrador): lista con alertas y ficha por pestañas (saldo, compras, documentos,
// certificado y credenciales de Hacienda, datos, integración por API, usuarios).
import { abrir, api, sesion } from '../api.js';
import { h, vaciar, fecha, tabla, modal, conBoton, toast, campo, opciones, aviso, dinero, badge, alCompletarCedula, avisoContribuyente, avisoNoInscrito, limpiarIdentificacion, TIPOS } from '../dom.js';
import { MEDIOS_PAGO, TIPOS_IDENTIFICACION } from '../catalogos.js';
import { selectorUbicacion } from '../ubicacion.js';
import { contexto, cargarContexto, enrutar } from '../app.js';
import { kpisSaldo, tablaServicios } from './saldo.js';
import { NIVELES, estadoComprobante } from './admin.js';

// Comprobante que se le emite al cliente por la venta (según los ajustes de ventas)
function controlesComprobante(ajustes) {
  const tipo = h('select', {}, [['01', 'Factura electrónica'], ['04', 'Tiquete electrónico'], ['ninguno', 'No emitir comprobante']]
    .map(([v, t]) => h('option', { value: v, selected: v === (ajustes.emisor_ventas_id ? ajustes.tipo_comprobante : 'ninguno') }, t)));
  const medio = h('select', {}, Object.entries(MEDIOS_PAGO).filter(([k]) => k !== '05' && k !== '99')
    .map(([k, v]) => h('option', { value: k, selected: k === ajustes.medio_pago }, v)));
  return {
    nodo: [
      h('div', { class: 'campos' }, campo('Comprobante para el cliente', tipo), campo('Medio de pago', medio)),
      ajustes.emisor_ventas_id
        ? h('p', { class: 'suave' }, `Lo emite ${ajustes.emisor_ventas} y se le envía por correo al cliente. Las cortesías (precio 0) no se facturan.`)
        : aviso('No se emitirá comprobante: configure en Ventas → Facturación de ventas qué empresa factura.', 'alerta'),
    ],
    valor: () => ({ comprobante: tipo.value, medio_pago: medio.value }),
  };
}

function avisarComprobante(comprobante, texto) {
  if (comprobante?.error) toast(`${texto}, pero el comprobante no se emitió:\n${comprobante.error}`, 'error');
  else if (comprobante?.factura_id) toast(`${texto} y se emitió el comprobante al cliente`, 'ok');
  else toast(texto, 'ok');
}

// --- Calculadoras de precio -------------------------------------------------
// Documentos: un plan del catálogo o "cantidad × precio por documento".
// Sistema web: "meses × precio mensual", o regalía (sin costo).
// Cada una devuelve { nodo, calculo(), cuerpo(), error() } y avisa con alCambiar()
// para que el diálogo de empresa nueva pueda sumar el total a pagar.

const redondear = (n) => Math.round(n * 100) / 100;
const MONEDAS = ['CRC', 'USD'];
const selectorMoneda = () => h('select', {}, MONEDAS.map((m) => h('option', { value: m }, m)));
const notaIva = (ajustes) => (ajustes.precio_incluye_iva === false ? 'más IVA' : 'IVA incluido');

function controlesDocumentos(planes, ajustes, alCambiar = () => {}) {
  const plan = h('select', {},
    planes.map((p) => h('option', { value: p.id }, `${p.nombre} · ${p.documentos.toLocaleString('es-CR')} documentos · ${dinero(p.precio, p.moneda)}`)),
    h('option', { value: '' }, 'Otra cantidad: precio por documento'));
  const documentos = h('input', { type: 'number', min: '1', step: '1', placeholder: 'Ej. 500' });
  const unitario = h('input', { type: 'number', min: '0', step: '0.01', placeholder: '0 = cortesía' });
  const moneda = selectorMoneda();
  const vigencia = h('input', { type: 'number', min: '1', placeholder: 'Vacío = no vence' });
  const libres = h('div', { class: 'campos' }, campo('Cantidad de documentos', documentos),
    campo('Precio por documento', unitario), campo('Moneda', moneda), campo('Vigencia (días)', vigencia));
  const resumen = h('div', { class: 'total-venta' });

  const elegido = () => planes.find((p) => p.id === plan.value);
  const calculo = () => {
    const p = elegido();
    if (p) return { documentos: p.documentos, unitario: Number(p.precio) / p.documentos, total: Number(p.precio), moneda: p.moneda };
    const d = Math.trunc(Number(documentos.value)) || 0;
    const u = Number(unitario.value) || 0;
    return { documentos: d, unitario: u, total: redondear(d * u), moneda: moneda.value };
  };
  const pintar = () => {
    libres.classList.toggle('oculto', Boolean(plan.value));
    const c = calculo();
    vaciar(resumen, c.documentos
      ? [h('span', {}, `${c.documentos.toLocaleString('es-CR')} documentos × ${dinero(c.unitario, c.moneda)}`),
        h('strong', {}, c.total ? `${dinero(c.total, c.moneda)} (${notaIva(ajustes)})` : 'Cortesía')]
      : h('span', { class: 'suave' }, 'Indique la cantidad de documentos y el precio por documento'));
    alCambiar();
  };
  for (const el of [plan, documentos, unitario, moneda]) { el.addEventListener('input', pintar); el.addEventListener('change', pintar); }
  if (!planes.length) plan.value = '';
  pintar();

  return {
    nodo: [campo('Plan', plan), libres, resumen],
    calculo,
    error: () => (calculo().documentos > 0 ? null : 'Indique la cantidad de documentos'),
    cuerpo: () => {
      if (plan.value) return { plan_id: plan.value };
      const c = calculo();
      return { documentos: c.documentos, precio: c.total.toFixed(2), moneda: c.moneda,
        dias_vigencia: vigencia.value ? Number(vigencia.value) : null,
        // En la bitácora y en el comprobante queda: "Paquete a ₡30 por documento: 500 documentos electrónicos"
        nombre: `Paquete a ${dinero(c.unitario, c.moneda).replace(/,00$/, '')} por documento`.slice(0, 80) };
    },
  };
}

function controlesPanelWeb(ajustes, alCambiar = () => {}) {
  const regalia = h('input', { type: 'checkbox' });
  const meses = h('select', {}, [[1, '1 mes'], [3, '3 meses'], [6, '6 meses'], [12, '12 meses (anual)']]
    .map(([v, t]) => h('option', { value: String(v) }, t)));
  const mensual = h('input', { type: 'number', min: '0', step: '0.01', placeholder: 'Ej. 5000 (0 = cortesía)' });
  const moneda = selectorMoneda();
  const pago = h('div', { class: 'campos' }, campo('Período', meses), campo('Precio mensual', mensual), campo('Moneda', moneda));
  const resumen = h('div', { class: 'total-venta' });

  const calculo = () => (regalia.checked
    ? { regalia: true, meses: 0, mensual: 0, total: 0, moneda: moneda.value }
    : { regalia: false, meses: Number(meses.value), mensual: Number(mensual.value) || 0,
      total: redondear(Number(meses.value) * (Number(mensual.value) || 0)), moneda: moneda.value });
  const pintar = () => {
    pago.classList.toggle('oculto', regalia.checked);
    const c = calculo();
    vaciar(resumen, c.regalia
      ? [h('span', {}, 'Regalía: sin costo y sin vencimiento'), h('strong', {}, dinero(0, c.moneda))]
      : [h('span', {}, `${c.meses} ${c.meses === 1 ? 'mes' : 'meses'} × ${dinero(c.mensual, c.moneda)}`),
        h('strong', {}, `${dinero(c.total, c.moneda)} (${notaIva(ajustes)})`)]);
    alCambiar();
  };
  for (const el of [regalia, meses, mensual, moneda]) { el.addEventListener('input', pintar); el.addEventListener('change', pintar); }
  pintar();

  return {
    nodo: [h('label', { class: 'check' }, regalia, 'Regalía (sin costo y sin vencimiento)'), pago, resumen],
    calculo,
    error: () => (regalia.checked || mensual.value !== '' ? null : 'Indique el precio mensual del sistema web (o márquelo como regalía)'),
    cuerpo: () => {
      const c = calculo();
      return c.regalia ? { servicio: 'facturacion_web', regalia: true }
        : { servicio: 'facturacion_web', meses: c.meses, precio: c.total.toFixed(2), moneda: c.moneda };
    },
  };
}

// Suma por moneda: "₡25 000,00" o "₡25 000,00 + $10,00"
function textoTotal(montos) {
  const porMoneda = {};
  for (const { total, moneda } of montos) porMoneda[moneda] = redondear((porMoneda[moneda] || 0) + total);
  const partes = Object.entries(porMoneda).filter(([, t]) => t > 0).map(([m, t]) => dinero(t, m));
  return partes.length ? partes.join(' + ') : 'Sin costo';
}

function dialogoVender(e, planes, ajustes, alTerminar) {
  const comp = controlesComprobante(ajustes);
  const docs = controlesDocumentos(planes, ajustes);
  const referencia = h('input', { type: 'text', maxlength: '100', placeholder: 'N.º de comprobante SINPE / transferencia' });
  const notas = h('input', { type: 'text', maxlength: '1000' });

  const vender = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(vender, async () => {
    const falta = docs.error();
    if (falta) { toast(falta, 'error'); return; }
    const cuerpo = { ...docs.cuerpo(), referencia_pago: referencia.value.trim() || null, notas: notas.value.trim() || null, ...comp.valor() };
    const r = await api(`/emisores/${e.id}/paquetes`, { method: 'POST', body: cuerpo, conEmisor: false });
    m.cerrar();
    avisarComprobante(r.comprobante, `Paquete acreditado (saldo: ${r.disponible.toLocaleString('es-CR')} documentos)`);
    alTerminar();
  }) }, 'Acreditar paquete');

  const m = modal(`Vender documentos a ${e.nombre}`, [
    docs.nodo,
    h('div', { class: 'campos' }, campo('Referencia del pago', referencia), campo('Notas', notas)),
    comp.nodo,
    h('p', { class: 'suave' }, 'Registre el paquete después de confirmar el pago. Queda en la bitácora de ventas.'),
  ], { acciones: [vender], ancho: true });
}

// Texto listo para entregar al cliente con todo lo que necesita su sistema para conectarse
function datosConexion(e, llave) {
  const base = `${window.location.origin}/api/v1`;
  const texto = [
    `Conexión a la API de facturación electrónica — ${e.nombre} (${e.numero_identificacion})`,
    '',
    `URL base:  ${base}`,
    `API key:   ${llave}`,
    'Header:    X-API-Key: <API key>',
    `Ambiente:  ${e.ambiente === 'prod' ? 'Producción' : 'Pruebas (sandbox de Hacienda)'}`,
    `Documentación interactiva: ${window.location.origin}/docs`,
    '',
    'Ejemplo (emitir una factura):',
    `curl -X POST ${base}/facturas \\`,
    `  -H "X-API-Key: ${llave}" -H "Content-Type: application/json" \\`,
    '  -d \'{"tipo_documento":"01","referencia_externa":"VENTA-1",',
    '       "receptor":{"nombre":"Cliente","tipo_identificacion":"01","numero_identificacion":"112345678"},',
    '       "productos":[{"codigo_cabys":"8361100000000","descripcion":"Servicio","cantidad":"1",',
    '                     "unidad_medida":"Sp","precio_unitario":"10000","codigo_tarifa_iva":"08"}],',
    '       "medios_pago":[{"tipo":"04"}]}\'',
    '',
    'Saldo de documentos: GET /saldo (también viene en el header X-Documentos-Disponibles).',
    'Guarde la API key como un secreto: no se puede volver a consultar.',
  ].join('\n');
  const copiar = h('button', { type: 'button', class: 'primario', onclick: async () => {
    try { await navigator.clipboard.writeText(texto); toast('Copiado: envíelo al cliente por un canal seguro', 'ok'); } catch { toast('Seleccione el texto y cópielo manualmente', 'error'); }
  } }, 'Copiar datos de conexión');
  return h('div', { class: 'secreto' },
    h('strong', {}, 'Llave creada. Copie ahora los datos de conexión: la llave no se volverá a mostrar.'),
    h('pre', { class: 'mono bloque' }, texto),
    copiar);
}

const CAMPOS = [
  ['nombre', 'Razón social / nombre', 'text', 100],
  ['nombre_comercial', 'Nombre comercial', 'text', 80],
  ['codigo_actividad', 'Código de actividad', 'text', 6],
  ['correo', 'Correo', 'email', 160],
  ['telefono', 'Teléfono', 'text', 20],
  ['provincia', 'Provincia'],
  ['canton', 'Cantón'],
  ['distrito', 'Distrito'],
  ['barrio', 'Barrio', 'text', 50, true],
  ['otras_senas', 'Otras señas', 'text', 250],
  ['proveedor_sistemas', 'Proveedor de sistemas (vacío = la misma empresa)', 'text', 12, true],
  ['registro_fiscal_8707', 'Registro fiscal Ley 8707 (solo si vende bebidas alcohólicas)', 'text', 12, true],
];

// Controles del formulario de empresa; la ubicación se elige por nombre.
function entradasEmpresa(valores = {}) {
  const entradas = Object.fromEntries(CAMPOS.map(([k, , t, max]) => [k, h('input', { type: t, maxlength: String(max), value: valores[k] || '' })]));
  const { provincia, canton, distrito } = selectorUbicacion(valores);
  return Object.assign(entradas, { provincia, canton, distrito });
}

// Campos obligatorios a la vista; los que solo aplican a algunas empresas, plegados
// (se abren solos si ya tienen valor).
function camposEmpresa(entradas) {
  const opcionales = CAMPOS.filter((c) => c[4]);
  return [
    h('div', { class: 'campos' }, CAMPOS.filter((c) => !c[4]).map(([k, etiqueta]) => campo(etiqueta, entradas[k]))),
    h('details', { open: opcionales.some(([k]) => entradas[k].value) },
      h('summary', {}, 'Datos opcionales (solo si aplican)'),
      h('div', { class: 'campos' }, opcionales.map(([k, etiqueta]) => campo(etiqueta, entradas[k])))),
  ];
}

function sinPermiso(cont) {
  vaciar(cont, aviso('Esta sección es solo para administradores.', 'alerta'));
}

export async function vistaEmpresas(cont) {
  if (!contexto.esAdmin) { sinPermiso(cont); return; }
  const [lista, diagnosticos] = await Promise.all([
    api('/emisores', { conEmisor: false }), api('/admin/diagnosticos', { conEmisor: false }),
  ]);
  const q = h('input', { type: 'search', placeholder: 'Buscar por nombre o cédula' });
  const filtro = h('select', { 'aria-label': 'Filtro' },
    [['', 'Todas'], ['problemas', 'Con problemas'], ['activas', 'Activas'], ['inactivas', 'Inactivas']].map(([v, t]) => h('option', { value: v }, t)));
  const resultados = h('div');
  const estado = (e) => {
    const alertas = (diagnosticos[e.id] || []).filter((a) => a.nivel !== 'info');
    if (!alertas.length) return badge('ACEPTADO', 'Al día');
    const a = alertas[0];
    return [badge(NIVELES[a.nivel][0], a.titulo), alertas.length > 1 ? h('div', { class: 'suave' }, `y ${alertas.length - 1} más`) : null];
  };
  const pintar = () => {
    const texto = q.value.trim().toLowerCase();
    const visibles = lista.filter((e) => (!texto || e.nombre.toLowerCase().includes(texto) || e.numero_identificacion.includes(texto))
      && (filtro.value !== 'problemas' || (diagnosticos[e.id] || []).some((a) => a.nivel !== 'info'))
      && (filtro.value !== 'activas' || e.activo) && (filtro.value !== 'inactivas' || !e.activo));
    vaciar(resultados, tabla([
      { titulo: 'Empresa', valor: (e) => [e.nombre, h('div', { class: 'suave' }, e.numero_identificacion)] },
      { titulo: 'Estado', valor: estado },
      { titulo: 'Ambiente', valor: (e) => h('span', { class: `badge ${e.ambiente}` }, e.ambiente === 'prod' ? 'Producción' : 'Pruebas') },
      { titulo: 'Certificado', valor: (e) => (e.tiene_certificado ? `vence ${fecha(e.cert_vence, false)}` : h('span', { class: 'badge RECHAZADO' }, 'falta')) },
      { titulo: 'Documentos', num: true, valor: (e) => (e.saldo_documentos === null || e.saldo_documentos === undefined ? '—'
        : h('span', { class: `badge ${e.saldo_documentos <= 0 ? 'RECHAZADO' : e.saldo_documentos <= contexto.saldoAlerta ? 'CONTINGENCIA' : 'ACEPTADO'}` },
          e.saldo_documentos.toLocaleString('es-CR'))) },
      { titulo: 'Activa', valor: (e) => (e.activo ? 'Sí' : 'No') },
    ], visibles, (e) => { location.hash = `#/empresas/${e.id}`; }));
  };
  q.addEventListener('input', pintar);
  filtro.addEventListener('change', pintar);
  pintar();
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Empresas cliente'),
      h('button', { type: 'button', class: 'primario', onclick: (ev) => conBoton(ev.target, dialogoNueva) }, '+ Nueva empresa')),
    h('div', { class: 'fila' }, q, filtro),
    h('section', { class: 'tarjeta' }, resultados));
}

async function dialogoNueva() {
  // Planes de documentos y ajustes de ventas, para registrar la venta inicial
  const [planes, ajustes] = await Promise.all([
    api('/planes?activos=true', { conEmisor: false }), api('/admin/ajustes', { conEmisor: false })]);
  const tipo = h('select', {}, opciones({ '02': TIPOS_IDENTIFICACION['02'], '01': TIPOS_IDENTIFICACION['01'], '03': 'DIMEX', '04': 'NITE' }, '02'));
  const numero = h('input', { type: 'text', maxlength: '12' });
  const entradas = entradasEmpresa();
  const ambiente = h('select', {}, h('option', { value: 'stag' }, 'Pruebas (stag)'), h('option', { value: 'prod' }, 'Producción'));

  // Al escribir la identificación se consultan los datos en Hacienda y se precargan.
  const estadoHacienda = h('div');
  const listaActividades = h('datalist', { id: 'actividades-nueva-empresa' });
  entradas.codigo_actividad.setAttribute('list', listaActividades.id);

  const consultar = alCompletarCedula(numero, tipo, async (cedula, vigente) => {
    vaciar(estadoHacienda, h('p', { class: 'suave' }, 'Consultando Hacienda…'));
    let c;
    try {
      c = await api(`/hacienda/contribuyentes/${cedula}`, { conEmisor: false });
    } catch (e) {
      if (vigente()) vaciar(estadoHacienda, e.status === 404 ? avisoNoInscrito(cedula) : aviso(e.message, 'error'));
      return;
    }
    if (!vigente()) return;
    entradas.nombre.value = c.nombre || '';
    if (c.tipoIdentificacion) tipo.value = c.tipoIdentificacion;
    const activas = (c.actividades || []).filter((a) => a.estado === 'A' || !a.estado);
    vaciar(listaActividades, activas.map((a) => h('option', { value: String(a.codigo).padStart(6, '0') }, a.descripcion)));
    const principal = activas.find((a) => a.tipo === 'P') || activas[0];
    entradas.codigo_actividad.value = principal ? String(principal.codigo).padStart(6, '0') : '';
    vaciar(estadoHacienda, avisoContribuyente(c, activas),
      activas.length > 1 ? h('p', { class: 'suave' }, 'Tiene varias actividades: puede elegir otra en "Código de actividad".') : null);
  });
  const autocompletar = h('button', { type: 'button', onclick: () => conBoton(autocompletar, consultar) }, 'Buscar en Hacienda');
  // Modalidad de venta: solo API (paga documentos) o API + sistema web (documentos + mensualidad).
  // Se puede cambiar después en la pestaña "Datos" de la empresa.
  const modalidad = (valor, titulo, ayuda, marcado) => {
    const radio = h('input', { type: 'radio', name: 'modalidad-empresa', value: valor, checked: marcado });
    return [radio, h('label', { class: 'opcion-modalidad' }, radio, h('strong', {}, titulo), h('span', { class: 'suave' }, ayuda))];
  };
  const [soloApi, tarjetaApi] = modalidad('api', 'Solo conexión por API',
    'Factura desde su POS, ERP, tienda en línea o n8n. Paga únicamente los documentos que compra.', true);
  const [conPanel, tarjetaWeb] = modalidad('web', 'API + sistema web',
    'Además entra al panel a hacer facturas, clientes, inventario y punto de venta. Lleva mensualidad (o regalía).', false);

  // Venta inicial: documentos (cantidad × precio por documento) + sistema web (meses × mensualidad).
  // El total a pagar se recalcula con cada cambio.
  const total = h('div', { class: 'total-venta total-general' });
  const recalcular = () => {
    if (!docs || !web) return;
    const montos = [docs.calculo()];
    if (conPanel.checked) montos.push(web.calculo());
    vaciar(total, h('span', {}, `Total a pagar (${notaIva(ajustes)})`), h('strong', {}, textoTotal(montos)));
  };
  let docs = null;
  let web = null;
  docs = controlesDocumentos(planes, ajustes, recalcular);
  web = controlesPanelWeb(ajustes, recalcular);
  const comp = controlesComprobante(ajustes);
  const referencia = h('input', { type: 'text', maxlength: '100', placeholder: 'N.º de comprobante SINPE / transferencia' });
  const venderAhora = h('input', { type: 'checkbox', checked: true });
  const bloqueWeb = h('div', { class: 'oculto' }, h('h3', {}, 'Sistema web'), web.nodo);
  const bloqueVenta = h('div', {},
    h('h3', {}, 'Documentos'), docs.nodo, bloqueWeb, total,
    h('div', { class: 'campos' }, campo('Referencia del pago', referencia)), comp.nodo);
  const alCambiarModalidad = () => { bloqueWeb.classList.toggle('oculto', !conPanel.checked); recalcular(); };
  soloApi.addEventListener('change', alCambiarModalidad);
  conPanel.addEventListener('change', alCambiarModalidad);
  venderAhora.addEventListener('change', () => bloqueVenta.classList.toggle('oculto', !venderAhora.checked));
  recalcular();

  // Registra lo vendido. Si falla, la empresa ya existe: se avisa para registrarlo en "Compras".
  const registrarVenta = async (e) => {
    const pago = { referencia_pago: referencia.value.trim() || null, ...comp.valor() };
    try {
      await api(`/emisores/${e.id}/paquetes`, { method: 'POST', body: { ...docs.cuerpo(), ...pago }, conEmisor: false });
      if (conPanel.checked) {
        const cuerpoWeb = web.cuerpo();
        await api(`/emisores/${e.id}/suscripciones`, { method: 'POST', conEmisor: false,
          body: cuerpoWeb.regalia ? cuerpoWeb : { ...cuerpoWeb, ...pago } });
      }
      return true;
    } catch (err) {
      toast(`La empresa se creó, pero la venta no se registró: ${err.message}\nRegístrela en la pestaña "Compras".`, 'error');
      return false;
    }
  };

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    if (venderAhora.checked) {
      const falta = docs.error() || (conPanel.checked ? web.error() : null);
      if (falta) { toast(falta, 'error'); return; }
    }
    const cuerpo = { tipo_identificacion: tipo.value, numero_identificacion: limpiarIdentificacion(numero.value), ambiente: ambiente.value };
    for (const [k, el] of Object.entries(entradas)) if (el.value.trim()) cuerpo[k] = el.value.trim();
    const e = await api('/emisores', { method: 'POST', body: cuerpo, conEmisor: false });
    if (conPanel.checked) await api(`/emisores/${e.id}`, { method: 'PATCH', body: { facturacion_web: true }, conEmisor: false });
    const vendido = venderAhora.checked ? await registrarVenta(e) : false;
    m.cerrar();
    await cargarContexto();
    sesion.emisorId = e.id;
    if (vendido) toast('Empresa creada y venta registrada. Siga con el certificado .p12 y las credenciales de Hacienda.', 'ok');
    else if (!venderAhora.checked) toast('Empresa creada. Siga con: certificado .p12, credenciales de Hacienda y vender los documentos.', 'ok');
    location.hash = `#/empresas/${e.id}`;
  }) }, 'Crear empresa');

  const m = modal('Nueva empresa', [
    h('p', { class: 'etiqueta-seccion' }, '¿Cómo va a facturar esta empresa?'),
    h('div', { class: 'modalidades' }, tarjetaApi, tarjetaWeb),
    h('div', { class: 'campos' }, campo('Tipo', tipo), h('div', { class: 'fila' }, campo('Identificación', numero), autocompletar),
      campo('Ambiente de Hacienda', ambiente)),
    estadoHacienda, listaActividades,
    camposEmpresa(entradas),
    h('section', { class: 'venta-inicial' },
      h('label', { class: 'check etiqueta-seccion' }, venderAhora, 'Registrar ahora lo que compra (el cliente ya pagó)'),
      bloqueVenta),
  ], { acciones: [guardar], ancho: true });
}

const ESTADO_COBRO = { VIGENTE: 'ACEPTADO', PROGRAMADA: 'PENDIENTE', VENCIDA: 'CONTINGENCIA', ANULADA: 'RECHAZADO' };

function dialogoCobrarServicio(e, servicio, ajustes, alTerminar) {
  const comp = controlesComprobante(ajustes);
  const referencia = h('input', { type: 'text', maxlength: '100', placeholder: 'Comprobante SINPE o transferencia' });
  const notas = h('input', { type: 'text', maxlength: '1000' });
  const vence = servicio.vence ? new Date(servicio.vence) : null;
  // La regalía (sin costo ni vencimiento) no lleva pago ni comprobante
  const bloquePago = h('div', {}, h('div', { class: 'campos' }, campo('Referencia del pago', referencia)), comp.nodo);
  let web = null;   // se asigna abajo; el aviso inicial de la calculadora llega antes
  web = controlesPanelWeb(ajustes, () => { if (web) bloquePago.classList.toggle('oculto', web.calculo().regalia); });
  const cobrar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(cobrar, async () => {
    const falta = web.error();
    if (falta) { toast(falta, 'error'); return; }
    const cuerpo = { ...web.cuerpo(), servicio: servicio.servicio, notas: notas.value.trim() || null };
    if (!cuerpo.regalia) Object.assign(cuerpo, { referencia_pago: referencia.value.trim() || null, ...comp.valor() });
    const r = await api(`/emisores/${e.id}/suscripciones`, { method: 'POST', conEmisor: false, body: cuerpo });
    m.cerrar();
    avisarComprobante(r.comprobante, r.servicio.regalia ? `${servicio.nombre}: activo como regalía`
      : `${servicio.nombre}: pagado hasta ${fecha(r.servicio.vence, false)}`);
    alTerminar();
  }) }, 'Registrar');
  const m = modal(`${servicio.nombre} · ${e.nombre}`, [
    servicio.servicio === 'facturacion_web'
      ? h('p', { class: 'suave' }, 'El panel web es opcional: la empresa factura por API aunque no lo tenga. Cóbrelo como extra o regálelo.') : null,
    vence && vence > new Date()
      ? aviso(`Está pagado hasta ${fecha(servicio.vence, false)}: el nuevo período empieza ese día.`, 'info') : null,
    servicio.regalia ? aviso('Ya está activo como regalía.', 'info') : null,
    web.nodo,
    bloquePago,
    campo('Notas', notas),
  ], { acciones: [cobrar], ancho: true });
}

function seccionLogo(id, tieneLogo, alCambiar) {
  const vista = h('div');
  if (tieneLogo) {
    api('/empresa/logo', { raw: true, emisor: id })
      .then((r) => r.blob())
      .then((b) => vaciar(vista, h('img', { src: URL.createObjectURL(b), alt: 'Logo actual', class: 'logo-empresa' })))
      .catch(() => {});
  }
  const archivo = h('input', { type: 'file', accept: 'image/png,image/jpeg' });
  const subir = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(subir, async () => {
    if (!archivo.files[0]) { toast('Seleccione una imagen PNG o JPEG', 'error'); return; }
    const form = new FormData();
    form.append('archivo', archivo.files[0]);
    await api('/empresa/logo', { method: 'PUT', form, emisor: id });
    toast('Logo actualizado: aparecerá en los PDF', 'ok');
    alCambiar();
  }) }, 'Cargar logo');
  const quitar = tieneLogo ? h('button', { type: 'button', class: 'peligro', onclick: () => conBoton(quitar, async () => {
    await api('/empresa/logo', { method: 'DELETE', emisor: id });
    toast('Logo eliminado', 'ok');
    alCambiar();
  }) }, 'Quitar logo') : null;
  return h('section', { class: 'tarjeta' }, h('h2', {}, 'Logo en las facturas (PDF)'),
    tieneLogo ? vista : aviso('Sin logo: el PDF muestra solo el nombre de la empresa.', 'info'),
    h('div', { class: 'fila' }, campo('Imagen PNG o JPEG (máximo 300 KB)', archivo), subir, quitar));
}

const PESTANAS = [
  ['resumen', 'Resumen'], ['compras', 'Compras'], ['documentos', 'Documentos'], ['hacienda', 'Hacienda y certificado'],
  ['datos', 'Datos'], ['integracion', 'Integración'], ['usuarios', 'Usuarios'],
];

function listaAlertas(id, alertas) {
  if (!alertas.length) return aviso('Sin problemas: la empresa puede facturar normalmente.', 'ok');
  return h('div', { class: 'alertas' }, alertas.map((a) => h('div', { class: `alerta-empresa ${a.nivel}` },
    h('div', {}, badge(NIVELES[a.nivel][0], NIVELES[a.nivel][1]), ' ', h('strong', {}, a.titulo)),
    h('div', {}, a.detalle),
    h('a', { href: `#/empresas/${id}/${a.seccion}` }, 'Ver y resolver →'))));
}

async function pestanaResumen(id, e, cont) {
  const [alertas, saldoEmpresa] = await Promise.all([
    api(`/admin/emisores/${id}/diagnostico`, { conEmisor: false }), api(`/emisores/${id}/paquetes`, { conEmisor: false }),
  ]);
  const dias = e.cert_vence ? Math.floor((new Date(e.cert_vence) - new Date()) / 86400000) : null;
  vaciar(cont,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Estado para facturar'), listaAlertas(id, alertas)),
    saldoEmpresa.control_activo ? kpisSaldo(saldoEmpresa) : null,
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Conexión con Hacienda'),
        h('dl', { class: 'datos' },
          h('dt', {}, 'Ambiente'), h('dd', {}, h('span', { class: `badge ${e.ambiente}` }, e.ambiente === 'prod' ? 'Producción' : 'Pruebas')),
          h('dt', {}, 'Certificado'), h('dd', {}, e.tiene_certificado ? `Vence ${fecha(e.cert_vence, false)} (${dias} días)` : h('span', { class: 'badge RECHAZADO' }, 'Falta')),
          h('dt', {}, 'Credenciales API'), h('dd', {}, e.tiene_credenciales_hacienda ? e.hacienda_usuario : h('span', { class: 'badge RECHAZADO' }, 'Faltan')))),
      saldoEmpresa.control_suscripciones ? h('section', { class: 'tarjeta' }, h('h2', {}, 'Servicios alquilados'),
        tablaServicios(saldoEmpresa.servicios)) : null));
}

async function pestanaCompras(id, e, cont, refrescar) {
  const [compras, saldoEmpresa, planes, servicios, ajustes] = await Promise.all([
    api(`/admin/emisores/${id}/compras`, { conEmisor: false }), api(`/emisores/${id}/paquetes`, { conEmisor: false }),
    api('/planes?activos=true', { conEmisor: false }), api(`/emisores/${id}/suscripciones`, { conEmisor: false }),
    api('/admin/ajustes', { conEmisor: false }),
  ]);
  const anular = (c) => {
    const vigente = c.clase === 'paquete' ? c.estado === 'VIGENTE' : ['VIGENTE', 'PROGRAMADA'].includes(c.estado);
    if (!vigente) return null;
    return h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => conBoton(ev.target, async () => {
      const texto = c.clase === 'paquete' ? `¿Anular los ${c.disponibles} documentos restantes de "${c.nombre}"?`
        : `¿Anular el cobro de ${c.nombre}? El período deja de contar.`;
      if (!window.confirm(`${texto} El comprobante emitido no se anula: hágalo con una nota de crédito.`)) return;
      const r = await api(c.clase === 'paquete' ? `/paquetes/${c.id}/anular` : `/suscripciones/${c.id}/anular`, { method: 'POST', conEmisor: false });
      toast(r.aviso_comprobante ? `Venta anulada. ${r.aviso_comprobante.mensaje}` : 'Venta anulada', r.aviso_comprobante ? 'alerta' : 'ok');
      refrescar();
    }) }, 'Anular');
  };
  const accionComprobante = (c) => {
    if (c.comprobante?.factura_id) {
      return h('button', { type: 'button', class: 'chico', onclick: (ev) => conBoton(ev.target,
        () => abrir(`/facturas/${c.comprobante.factura_id}/pdf`, c.comprobante.emisor_id)) }, 'PDF');
    }
    if (Number(c.precio) > 0 && ajustes.emisor_ventas_id) {
      return h('button', { type: 'button', class: 'chico', title: c.comprobante?.error || '', onclick: (ev) => conBoton(ev.target, async () => {
        await api(`/admin/ventas/${c.clase}/${c.id}/comprobante`, { method: 'POST', body: {}, conEmisor: false });
        toast('Comprobante emitido al cliente', 'ok');
        refrescar();
      }) }, c.comprobante?.error ? 'Reintentar' : 'Emitir');
    }
    return null;
  };
  vaciar(cont,
    saldoEmpresa.control_activo ? kpisSaldo(saldoEmpresa) : null,
    h('section', { class: 'tarjeta' },
      h('div', { class: 'encabezado' }, h('h2', {}, 'Historial de compras'),
        h('div', { class: 'acciones' },
          servicios.control_activo ? servicios.servicios.filter((s) => s.con_mensualidad).map((s) => h('button', { type: 'button', onclick: () => dialogoCobrarServicio(e, s, ajustes, refrescar) },
            `${s.vence ? 'Renovar' : 'Cobrar'} ${s.nombre.toLowerCase()}`)) : null,
          saldoEmpresa.control_activo ? h('button', { type: 'button', class: 'primario', onclick: () => dialogoVender(e, planes, ajustes, refrescar) }, '+ Vender paquete') : null)),
      tabla([
        { titulo: 'Fecha', valor: (c) => fecha(c.fecha, false) },
        { titulo: 'Compra', valor: (c) => [c.detalle, c.referencia_pago ? h('div', { class: 'suave' }, `Pago: ${c.referencia_pago}`) : null] },
        { titulo: 'Monto', num: true, valor: (c) => dinero(c.precio, c.moneda) },
        { titulo: 'Uso / vigencia', valor: (c) => (c.clase === 'paquete'
          ? [`${c.usados.toLocaleString('es-CR')} de ${c.documentos.toLocaleString('es-CR')} usados`,
            h('div', { class: 'suave' }, c.vence ? `vence ${fecha(c.vence, false)}` : 'no vence')]
          : `hasta ${fecha(c.hasta, false)}`) },
        { titulo: 'Estado', valor: (c) => h('span', { class: `badge ${ESTADO_COBRO[c.estado] || { AGOTADO: 'PENDIENTE', VENCIDO: 'CONTINGENCIA', ANULADO: 'RECHAZADO' }[c.estado] || ''}` }, c.estado) },
        { titulo: 'Comprobante', valor: (c) => estadoComprobante(c.comprobante, Number(c.precio)) },
        { titulo: '', valor: (c) => h('div', { class: 'acciones' }, accionComprobante(c), anular(c)) },
      ], compras)));
}

async function pestanaDocumentos(id, cont) {
  const [emitidos, recibidos] = await Promise.all([
    api('/facturas?limit=30', { emisor: id }), api('/recepcion?limit=15', { emisor: id }),
  ]);
  vaciar(cont,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Últimos comprobantes emitidos'),
      tabla([
        { titulo: 'Fecha', valor: (f) => fecha(f.fecha_emision) },
        { titulo: 'Documento', valor: (f) => [TIPOS[f.tipo_documento], h('div', { class: 'suave mono' }, f.numero_consecutivo)] },
        { titulo: 'Cliente', valor: (f) => f.receptor_nombre || 'Consumidor final' },
        { titulo: 'Total', num: true, valor: (f) => dinero(f.monto_total, f.moneda) },
        { titulo: 'Estado', valor: (f) => [badge(f.estado), f.estado === 'RECHAZADO' && f.mensaje_hacienda
          ? h('div', { class: 'suave' }, f.mensaje_hacienda.slice(0, 220)) : null] },
        { titulo: '', valor: (f) => h('button', { type: 'button', class: 'chico', onclick: (ev) => conBoton(ev.target, () => abrir(`/facturas/${f.factura_id}/pdf`, id)) }, 'PDF') },
      ], emitidos)),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Facturas de proveedores recientes'),
      tabla([
        { titulo: 'Fecha', valor: (d) => fecha(d.fecha_emision, false) },
        { titulo: 'Proveedor', valor: (d) => d.proveedor_nombre },
        { titulo: 'Total', num: true, valor: (d) => dinero(d.total_comprobante, d.moneda) },
        { titulo: 'Respuesta', valor: (d) => (d.estado ? [badge(d.estado), d.mensaje_hacienda && d.estado === 'RECHAZADO'
          ? h('div', { class: 'suave' }, d.mensaje_hacienda.slice(0, 220)) : null] : h('span', { class: 'badge PENDIENTE' }, 'Por responder')) },
      ], recibidos)));
}

function pestanaHacienda(id, e, cont, refrescar) {
  const archivo = h('input', { type: 'file', accept: '.p12,.pfx,application/x-pkcs12' });
  const pin = h('input', { type: 'password', autocomplete: 'off' });
  const subirCert = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(subirCert, async () => {
    if (!archivo.files[0] || !pin.value) { toast('Seleccione el archivo .p12 e indique el PIN', 'error'); return; }
    const form = new FormData();
    form.append('archivo', archivo.files[0]);
    form.append('password', pin.value);
    const r = await api(`/emisores/${id}/certificado`, { method: 'PUT', form, conEmisor: false });
    pin.value = '';
    toast(['Certificado cargado', ...(r.advertencias || [])].join('\n'), r.advertencias?.length ? '' : 'ok');
    refrescar();
  }) }, 'Cargar certificado');

  const usuario = h('input', { type: 'text', value: e.hacienda_usuario || '', autocomplete: 'off', placeholder: 'cpj-3-101-…@stag.comprobanteselectronicos.go.cr' });
  const clave = h('input', { type: 'password', autocomplete: 'new-password' });
  const guardarCred = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardarCred, async () => {
    await api(`/emisores/${id}/credenciales-hacienda`, { method: 'PUT', body: { usuario: usuario.value.trim(), password: clave.value }, conEmisor: false });
    clave.value = '';
    toast('Credenciales guardadas (cifradas)', 'ok');
    refrescar();
  }) }, 'Guardar credenciales');

  const resultadoPrueba = h('div');
  const probar = h('button', { type: 'button', onclick: () => conBoton(probar, async () => {
    const r = await api(`/emisores/${id}/probar-conexion`, { method: 'POST', conEmisor: false });
    vaciar(resultadoPrueba, aviso(
      `Hacienda (${r.ambiente}): ${r.hacienda}\nCertificado: ${r.certificado}${r.certificado_dias_para_vencer !== undefined ? ` (${r.certificado_dias_para_vencer} días)` : ''}`,
      r.ok ? 'ok' : 'error'));
  }) }, 'Probar conexión con Hacienda');

  vaciar(cont,
    aviso('El certificado (.p12) y las credenciales del API los genera el cliente en el ATV de Hacienda '
      + '(Comprobantes electrónicos → Llave criptográfica y Usuario del API). Ambos deben ser del mismo ambiente: pruebas o producción.', 'info'),
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Certificado digital (.p12)'),
        e.tiene_certificado
          ? aviso(`Cargado: ${e.cert_sujeto} · vence ${fecha(e.cert_vence, false)}`, new Date(e.cert_vence) < new Date() ? 'error' : 'ok')
          : aviso('Sin certificado: no se pueden firmar comprobantes.', 'alerta'),
        campo(e.tiene_certificado ? 'Reemplazar por un archivo .p12 nuevo' : 'Archivo .p12', archivo), campo('PIN del certificado', pin),
        h('div', { class: 'acciones' }, subirCert)),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Credenciales del API de Hacienda'),
        e.tiene_credenciales_hacienda ? aviso('Credenciales guardadas', 'ok') : aviso('Faltan las credenciales del API (ATV).', 'alerta'),
        campo('Usuario', usuario), campo('Contraseña', clave),
        h('div', { class: 'acciones' }, guardarCred, probar), resultadoPrueba)));
}

function pestanaDatos(id, e, cont, refrescar) {
  const entradas = entradasEmpresa(e);
  const ambiente = h('select', {}, h('option', { value: 'stag', selected: e.ambiente === 'stag' }, 'Pruebas (stag)'),
    h('option', { value: 'prod', selected: e.ambiente === 'prod' }, 'Producción'));
  const activo = h('input', { type: 'checkbox', checked: e.activo });
  const facturacionWeb = h('input', { type: 'checkbox', checked: e.facturacion_web });
  const accesoApi = h('input', { type: 'checkbox', checked: e.acceso_api });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = {
      ambiente: ambiente.value, activo: activo.checked, facturacion_web: facturacionWeb.checked, acceso_api: accesoApi.checked,
    };
    for (const [k, el] of Object.entries(entradas)) cuerpo[k] = el.value.trim() || null;
    for (const k of ['nombre', 'codigo_actividad', 'correo', 'provincia', 'canton', 'distrito', 'otras_senas']) {
      if (!cuerpo[k]) delete cuerpo[k];
    }
    await api(`/emisores/${id}`, { method: 'PATCH', body: cuerpo, conEmisor: false });
    await cargarContexto();
    toast('Datos guardados', 'ok');
    refrescar();
  }) }, 'Guardar cambios');
  vaciar(cont,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Datos de la empresa'),
      camposEmpresa(entradas),
      h('div', { class: 'campos' },
        campo('Ambiente de Hacienda', ambiente), h('label', { class: 'check' }, activo, 'Empresa activa')),
      // Servicios: se encienden o apagan aquí; el cobro del panel web se registra en "Compras".
      h('p', { class: 'etiqueta-seccion' }, 'Servicios habilitados'),
      h('div', { class: 'modalidades' },
        h('label', { class: 'opcion-modalidad' }, accesoApi, h('strong', {}, 'Conexión por API'),
          h('span', { class: 'suave' }, 'Su sistema de facturación se conecta con las API keys (pestaña Integración). Se paga solo con documentos.')),
        h('label', { class: 'opcion-modalidad' }, facturacionWeb, h('strong', {}, 'Sistema web'),
          h('span', { class: 'suave' }, 'Sus usuarios entran al panel a facturar, manejar clientes e inventario. Servicio adicional: se cobra o se regala en "Compras".'))),
      h('div', { class: 'acciones' }, guardar)),
    seccionLogo(id, e.tiene_logo, refrescar));
}

async function pestanaIntegracion(id, e, cont, refrescar) {
  const llaves = await api(`/api-keys?emisor_id=${id}`, { conEmisor: false });
  const webhook = h('input', { type: 'url', value: e.webhook_url || '', placeholder: 'https://su-sistema/webhook' });
  const secreto = h('div');
  const guardarWebhook = h('button', { type: 'button', onclick: () => conBoton(guardarWebhook, async () => {
    const r = await api(`/emisores/${id}/webhook`, { method: 'PUT', body: { url: webhook.value.trim() || null }, conEmisor: false });
    vaciar(secreto, r.secreto ? h('div', { class: 'secreto' }, 'Secreto para validar la firma (se muestra una sola vez): ', h('span', { class: 'mono' }, r.secreto)) : aviso('Webhook desactivado', 'info'));
  }) }, 'Guardar webhook');
  const nombreLlave = h('input', { type: 'text', placeholder: 'Ej.: POS tienda central', maxlength: '100' });
  const nuevaLlave = h('div');
  const crearLlave = h('button', { type: 'button', onclick: () => conBoton(crearLlave, async () => {
    if (!nombreLlave.value.trim()) { toast('Indique un nombre para la llave', 'error'); return; }
    const r = await api('/api-keys', { method: 'POST', body: { nombre: nombreLlave.value.trim(), emisor_id: id }, conEmisor: false });
    vaciar(nuevaLlave, datosConexion(e, r.api_key));
    nombreLlave.value = '';
  }) }, 'Crear API key');
  vaciar(cont, h('section', { class: 'tarjeta' }, h('h2', {}, 'Integración con otros sistemas'),
    e.acceso_api ? null : aviso('La conexión por API está desactivada: las llaves de esta empresa no funcionan. Actívela en "Datos".', 'alerta'),
    h('h3', {}, 'API keys'),
    tabla([
      { titulo: 'Nombre', valor: (k) => k.nombre },
      { titulo: 'Prefijo', valor: (k) => h('span', { class: 'mono' }, `${k.prefijo}…`) },
      { titulo: 'Último uso', valor: (k) => fecha(k.ultimo_uso) || 'Nunca' },
      { titulo: 'Estado', valor: (k) => (k.activa ? 'Activa' : 'Revocada') },
      { titulo: '', valor: (k) => (k.activa ? h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => conBoton(ev.target, async () => {
        await api(`/api-keys/${k.id}`, { method: 'DELETE', conEmisor: false });
        toast('Llave revocada', 'ok');
        refrescar();
      }) }, 'Revocar') : null) },
    ], llaves),
    h('div', { class: 'fila' }, campo('Nueva llave', nombreLlave), crearLlave), nuevaLlave,
    h('h3', {}, 'Webhook (aviso de cambios de estado)'),
    h('div', { class: 'fila' }, campo('URL', webhook), guardarWebhook), secreto));
}

async function pestanaUsuarios(id, e, cont, refrescar) {
  const usuarios = (await api('/usuarios', { conEmisor: false })).filter((u) => u.emisor_id === id);
  const email = h('input', { type: 'email' });
  const nombre = h('input', { type: 'text', maxlength: '100' });
  const password = h('input', { type: 'password', autocomplete: 'new-password', minlength: '10' });
  const crear = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(crear, async () => {
    await api('/usuarios', { method: 'POST', conEmisor: false,
      body: { email: email.value.trim(), nombre: nombre.value.trim(), password: password.value, es_admin: false, emisor_id: id } });
    toast(`Usuario creado: ya puede entrar al panel de ${e.nombre}`, 'ok');
    refrescar();
  }) }, 'Crear usuario');
  vaciar(cont,
    e.facturacion_web ? null : aviso('Esta empresa no tiene el panel web habilitado: sus usuarios no podrán entrar. '
      + 'Actívelo en Datos y cóbrelo o regálelo en Compras.', 'alerta'),
    h('section', { class: 'tarjeta' }, h('h2', {}, `Usuarios de ${e.nombre}`),
      tabla([
        { titulo: 'Nombre', valor: (u) => [u.nombre, h('div', { class: 'suave' }, u.email)] },
        { titulo: 'Último ingreso', valor: (u) => fecha(u.ultimo_login) || 'Nunca' },
        { titulo: 'Estado', valor: (u) => (u.activo ? 'Activo' : h('span', { class: 'badge RECHAZADO' }, 'Inactivo')) },
        { titulo: '', valor: (u) => h('button', { type: 'button', class: `chico ${u.activo ? 'peligro' : ''}`, onclick: (ev) => conBoton(ev.target, async () => {
          await api(`/usuarios/${u.id}`, { method: 'PATCH', body: { activo: !u.activo }, conEmisor: false });
          refrescar();
        }) }, u.activo ? 'Desactivar' : 'Activar') },
      ], usuarios)),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Nuevo usuario para esta empresa'),
      h('div', { class: 'campos' }, campo('Correo', email), campo('Nombre', nombre), campo('Contraseña inicial (mínimo 10)', password)),
      h('p', { class: 'suave' }, 'Solo verá esta empresa. Para cambiarle la contraseña o reiniciar la verificación en dos pasos use Empresas → Usuarios.'),
      h('div', { class: 'acciones' }, crear)));
}

export async function vistaDetalleEmpresa(cont, id, pestana = 'resumen') {
  if (!contexto.esAdmin) { sinPermiso(cont); return; }
  if (!PESTANAS.some(([k]) => k === pestana)) pestana = 'resumen';
  const [e, alertas] = await Promise.all([
    api(`/emisores/${id}`, { conEmisor: false }), api(`/admin/emisores/${id}/diagnostico`, { conEmisor: false }),
  ]);
  const errores = alertas.filter((a) => a.nivel === 'error').length;
  const refrescar = () => vistaDetalleEmpresa(cont, id, pestana).catch((err) => toast(err.message, 'error'));
  const cuerpo = h('div');
  vaciar(cont,
    h('div', { class: 'encabezado' },
      h('div', {}, h('a', { href: '#/empresas' }, '← Empresas'),
        h('h1', {}, e.nombre, ' ', errores ? badge('RECHAZADO', `${errores} problema(s)`) : badge('ACEPTADO', 'Puede facturar')),
        h('p', { class: 'suave' }, `${TIPOS_IDENTIFICACION[e.tipo_identificacion] || ''} ${e.numero_identificacion} · ${e.correo}`))),
    h('nav', { class: 'pestanas' }, PESTANAS.map(([k, t]) => h('a', { href: `#/empresas/${id}/${k}`, class: k === pestana ? 'activo' : '' },
      t, k === 'resumen' && errores ? ` (${errores})` : ''))),
    cuerpo);
  const vistas = {
    resumen: () => pestanaResumen(id, e, cuerpo),
    compras: () => pestanaCompras(id, e, cuerpo, refrescar),
    documentos: () => pestanaDocumentos(id, cuerpo),
    hacienda: () => pestanaHacienda(id, e, cuerpo, refrescar),
    datos: () => pestanaDatos(id, e, cuerpo, refrescar),
    integracion: () => pestanaIntegracion(id, e, cuerpo, refrescar),
    usuarios: () => pestanaUsuarios(id, e, cuerpo, refrescar),
  };
  await vistas[pestana]();
}
