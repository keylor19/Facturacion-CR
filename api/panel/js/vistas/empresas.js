import { api, sesion } from '../api.js';
import { h, vaciar, fecha, tabla, modal, conBoton, toast, campo, opciones, aviso, dinero, alCompletarCedula, avisoContribuyente, avisoNoInscrito } from '../dom.js';
import { TIPOS_IDENTIFICACION } from '../catalogos.js';
import { contexto, cargarContexto, enrutar } from '../app.js';
import { kpisSaldo, tablaPaquetes, tablaServicios } from './saldo.js';

function dialogoVender(e, planes, alTerminar) {
  const plan = h('select', {}, h('option', { value: '' }, 'Cantidad libre (cortesía o precio especial)'),
    planes.map((p) => h('option', { value: p.id }, `${p.nombre} · ${p.documentos} documentos · ${p.moneda} ${p.precio}`)));
  const documentos = h('input', { type: 'number', min: '1' });
  const precio = h('input', { type: 'number', min: '0', step: '0.01', placeholder: '0 = cortesía' });
  const vigencia = h('input', { type: 'number', min: '1', placeholder: 'Vacío = no vence' });
  const referencia = h('input', { type: 'text', maxlength: '100', placeholder: 'N.º de comprobante SINPE / transferencia' });
  const notas = h('input', { type: 'text', maxlength: '1000' });
  const libres = h('div', { class: 'campos' }, campo('Documentos', documentos), campo('Precio', precio), campo('Vigencia (días)', vigencia));
  plan.addEventListener('change', () => libres.classList.toggle('oculto', Boolean(plan.value)));
  if (planes.length) { plan.value = planes[0].id; libres.classList.add('oculto'); }

  const vender = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(vender, async () => {
    const cuerpo = { referencia_pago: referencia.value.trim() || null, notas: notas.value.trim() || null };
    if (plan.value) {
      cuerpo.plan_id = plan.value;
    } else {
      Object.assign(cuerpo, { documentos: Number(documentos.value), precio: precio.value || '0',
        dias_vigencia: vigencia.value ? Number(vigencia.value) : null });
    }
    const r = await api(`/emisores/${e.id}/paquetes`, { method: 'POST', body: cuerpo, conEmisor: false });
    m.cerrar();
    toast(`Paquete acreditado. Saldo: ${r.disponible.toLocaleString('es-CR')} documentos`, 'ok');
    alTerminar();
  }) }, 'Acreditar paquete');

  const m = modal(`Vender paquete a ${e.nombre}`, [
    campo('Plan', plan), libres,
    h('div', { class: 'campos' }, campo('Referencia del pago', referencia), campo('Notas', notas)),
    h('p', { class: 'suave' }, 'Registre el paquete después de confirmar el pago. Queda en la bitácora de ventas.'),
  ], { acciones: [vender] });
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
  ['provincia', 'Provincia (1-7)', 'text', 1],
  ['canton', 'Cantón (2 dígitos)', 'text', 2],
  ['distrito', 'Distrito (2 dígitos)', 'text', 2],
  ['barrio', 'Barrio', 'text', 50, true],
  ['otras_senas', 'Otras señas', 'text', 250],
  ['proveedor_sistemas', 'Proveedor de sistemas (vacío = la misma empresa)', 'text', 12, true],
  ['registro_fiscal_8707', 'Registro fiscal Ley 8707 (solo si vende bebidas alcohólicas)', 'text', 12, true],
];

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
  const lista = await api('/emisores', { conEmisor: false });
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Empresas'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoNueva() }, '+ Nueva empresa')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Empresa', valor: (e) => [e.nombre, h('div', { class: 'suave' }, e.numero_identificacion)] },
      { titulo: 'Ambiente', valor: (e) => h('span', { class: `badge ${e.ambiente}` }, e.ambiente === 'prod' ? 'Producción' : 'Pruebas') },
      { titulo: 'Certificado', valor: (e) => (e.tiene_certificado ? `vence ${fecha(e.cert_vence, false)}` : h('span', { class: 'badge RECHAZADO' }, 'falta')) },
      { titulo: 'Credenciales Hacienda', valor: (e) => (e.tiene_credenciales_hacienda ? '✔' : h('span', { class: 'badge RECHAZADO' }, 'faltan')) },
      { titulo: 'Documentos', num: true, valor: (e) => (e.saldo_documentos === null || e.saldo_documentos === undefined ? '—'
        : h('span', { class: `badge ${e.saldo_documentos <= 0 ? 'RECHAZADO' : e.saldo_documentos <= contexto.saldoAlerta ? 'CONTINGENCIA' : 'ACEPTADO'}` },
          e.saldo_documentos.toLocaleString('es-CR'))) },
      { titulo: 'Activa', valor: (e) => (e.activo ? 'Sí' : 'No') },
    ], lista, (e) => { location.hash = `#/empresas/${e.id}`; })));
}

function dialogoNueva() {
  const tipo = h('select', {}, opciones({ '02': TIPOS_IDENTIFICACION['02'], '01': TIPOS_IDENTIFICACION['01'], '03': 'DIMEX', '04': 'NITE' }, '02'));
  const numero = h('input', { type: 'text', maxlength: '12' });
  const entradas = Object.fromEntries(CAMPOS.map(([k, , t, max]) => [k, h('input', { type: t, maxlength: String(max) })]));
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
  const autocompletar = h('button', { type: 'button', onclick: () => conBoton(autocompletar, consultar) }, 'Volver a consultar');

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = { tipo_identificacion: tipo.value, numero_identificacion: numero.value.replace(/\D/g, ''), ambiente: ambiente.value };
    for (const [k, el] of Object.entries(entradas)) if (el.value.trim()) cuerpo[k] = el.value.trim();
    const e = await api('/emisores', { method: 'POST', body: cuerpo, conEmisor: false });
    m.cerrar();
    await cargarContexto();
    sesion.emisorId = e.id;
    toast('Empresa creada. Cargue ahora el certificado y las credenciales.', 'ok');
    location.hash = `#/empresas/${e.id}`;
  }) }, 'Crear empresa');

  const m = modal('Nueva empresa', [
    h('div', { class: 'campos' }, campo('Tipo', tipo), h('div', { class: 'fila' }, campo('Identificación', numero), autocompletar),
      campo('Ambiente de Hacienda', ambiente)),
    estadoHacienda, listaActividades,
    camposEmpresa(entradas),
  ], { acciones: [guardar], ancho: true });
}

const ESTADO_COBRO = { VIGENTE: 'ACEPTADO', PROGRAMADA: 'PENDIENTE', VENCIDA: 'CONTINGENCIA', ANULADA: 'RECHAZADO' };

function dialogoCobrarServicio(e, servicio, alTerminar) {
  const meses = h('select', {}, [[1, '1 mes'], [3, '3 meses'], [6, '6 meses'], [12, '12 meses (anual)']]
    .map(([v, t]) => h('option', { value: String(v) }, t)));
  const precio = h('input', { type: 'number', min: '0', step: '0.01', placeholder: 'Total del período (0 = cortesía)' });
  const moneda = h('select', {}, ['CRC', 'USD'].map((m) => h('option', { value: m }, m)));
  const referencia = h('input', { type: 'text', maxlength: '100', placeholder: 'Comprobante SINPE o transferencia' });
  const notas = h('input', { type: 'text', maxlength: '1000' });
  const vence = servicio.vence ? new Date(servicio.vence) : null;
  const cobrar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(cobrar, async () => {
    if (precio.value === '') { toast('Indique el precio cobrado', 'error'); return; }
    const r = await api(`/emisores/${e.id}/suscripciones`, {
      method: 'POST', conEmisor: false,
      body: { servicio: servicio.servicio, meses: Number(meses.value), precio: precio.value, moneda: moneda.value,
        referencia_pago: referencia.value.trim() || null, notas: notas.value.trim() || null },
    });
    m.cerrar();
    toast(`${servicio.nombre}: pagado hasta ${fecha(r.servicio.vence, false)}`, 'ok');
    alTerminar();
  }) }, 'Registrar pago');
  const m = modal(`Cobrar ${servicio.nombre} · ${e.nombre}`, [
    vence && vence > new Date()
      ? aviso(`Está pagado hasta ${fecha(servicio.vence, false)}: el nuevo período empieza ese día.`, 'info') : null,
    h('div', { class: 'campos' }, campo('Período', meses), campo('Precio cobrado', precio), campo('Moneda', moneda),
      campo('Referencia del pago', referencia), campo('Notas', notas)),
  ], { acciones: [cobrar] });
}

function seccionServicios(e, datos, alCambiar) {
  if (!datos.control_activo) return null;
  const anular = (s) => (['VIGENTE', 'PROGRAMADA'].includes(s.estado) ? h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => conBoton(ev.target, async () => {
    if (!window.confirm(`¿Anular el cobro de ${s.nombre} (${s.meses} mes/es)? El período deja de contar.`)) return;
    await api(`/suscripciones/${s.id}/anular`, { method: 'POST', conEmisor: false });
    toast('Cobro anulado', 'ok');
    alCambiar();
  }) }, 'Anular') : null);
  return h('section', { class: 'tarjeta' },
    h('h2', {}, 'Servicios alquilados (mensualidad)'),
    h('p', { class: 'suave' }, 'Se cobran aparte de los documentos. Cada servicio funciona con su casilla habilitada en "Datos de la empresa" y el pago al día.'),
    tablaServicios(datos.servicios, (s) => h('button', { type: 'button', class: 'chico primario', onclick: () => dialogoCobrarServicio(e, s, alCambiar) },
      s.vence ? 'Renovar' : 'Cobrar')),
    datos.historial.length ? h('h3', {}, 'Historial de cobros') : null,
    datos.historial.length ? tabla([
      { titulo: 'Fecha', valor: (s) => fecha(s.fecha, false) },
      { titulo: 'Servicio', valor: (s) => s.nombre },
      { titulo: 'Período', valor: (s) => `${fecha(s.desde, false)} – ${fecha(s.hasta, false)}` },
      { titulo: 'Precio', num: true, valor: (s) => dinero(s.precio, s.moneda) },
      { titulo: 'Pago', valor: (s) => s.referencia_pago || '—' },
      { titulo: 'Estado', valor: (s) => h('span', { class: `badge ${ESTADO_COBRO[s.estado]}` }, s.estado) },
      { titulo: '', valor: anular },
    ], datos.historial) : null);
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

export async function vistaDetalleEmpresa(cont, id) {
  if (!contexto.esAdmin) { sinPermiso(cont); return; }
  const [e, llaves, saldoEmpresa, planes, servicios] = await Promise.all([
    api(`/emisores/${id}`, { conEmisor: false }),
    api(`/api-keys?emisor_id=${id}`, { conEmisor: false }),
    api(`/emisores/${id}/paquetes`, { conEmisor: false }),
    api('/planes?activos=true', { conEmisor: false }),
    api(`/emisores/${id}/suscripciones`, { conEmisor: false }),
  ]);
  // Pasa por el enrutador para recargar también el saldo de la barra superior
  const refrescar = () => enrutar();

  // Datos generales
  const entradas = Object.fromEntries(CAMPOS.map(([k, , t, max]) => [k, h('input', { type: t, maxlength: String(max), value: e[k] || '' })]));
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

  // Certificado
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
    await cargarContexto();
    refrescar();
  }) }, 'Cargar certificado');

  // Credenciales de Hacienda
  const usuario = h('input', { type: 'text', value: e.hacienda_usuario || '', autocomplete: 'off' });
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

  // Webhook
  const webhook = h('input', { type: 'url', value: e.webhook_url || '', placeholder: 'https://su-sistema/webhook' });
  const secreto = h('div');
  const guardarWebhook = h('button', { type: 'button', onclick: () => conBoton(guardarWebhook, async () => {
    const r = await api(`/emisores/${id}/webhook`, { method: 'PUT', body: { url: webhook.value.trim() || null }, conEmisor: false });
    vaciar(secreto, r.secreto ? h('div', { class: 'secreto' }, 'Secreto para validar la firma (se muestra una sola vez): ', h('span', { class: 'mono' }, r.secreto)) : aviso('Webhook desactivado', 'info'));
  }) }, 'Guardar webhook');

  // API keys
  const nombreLlave = h('input', { type: 'text', placeholder: 'Ej.: POS tienda central', maxlength: '100' });
  const nuevaLlave = h('div');
  const crearLlave = h('button', { type: 'button', onclick: () => conBoton(crearLlave, async () => {
    if (!nombreLlave.value.trim()) { toast('Indique un nombre para la llave', 'error'); return; }
    const r = await api('/api-keys', { method: 'POST', body: { nombre: nombreLlave.value.trim(), emisor_id: id }, conEmisor: false });
    vaciar(nuevaLlave, datosConexion(e, r.api_key));
    nombreLlave.value = '';
  }) }, 'Crear API key');

  // Paquetes de documentos
  const anular = (p) => (p.estado === 'VIGENTE' ? h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => conBoton(ev.target, async () => {
    if (!window.confirm(`¿Anular los ${p.disponibles} documentos restantes de "${p.nombre}"?`)) return;
    await api(`/paquetes/${p.id}/anular`, { method: 'POST', conEmisor: false });
    toast('Paquete anulado', 'ok');
    refrescar();
  }) }, 'Anular') : null);
  const seccionSaldo = saldoEmpresa.control_activo ? h('section', { class: 'tarjeta' },
    h('div', { class: 'encabezado' }, h('h2', {}, 'Documentos (saldo)'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoVender(e, planes, refrescar) }, '+ Vender paquete')),
    kpisSaldo(saldoEmpresa),
    tablaPaquetes(saldoEmpresa.paquetes, anular)) : null;

  vaciar(cont,
    h('div', { class: 'encabezado' },
      h('div', {}, h('a', { href: '#/empresas' }, '← Empresas'), h('h1', {}, `${e.nombre} · ${e.numero_identificacion}`))),
    seccionServicios(e, servicios, refrescar),
    seccionSaldo,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Datos de la empresa'),
      camposEmpresa(entradas),
      h('div', { class: 'campos' },
        campo('Ambiente de Hacienda', ambiente), h('label', { class: 'check' }, activo, 'Empresa activa'),
        h('label', { class: 'check', title: 'Emitir, clientes, productos e inventario desde el panel para los usuarios de la empresa' },
          facturacionWeb, 'Facturación en línea (panel con clientes, productos e inventario)'),
        h('label', { class: 'check', title: 'El sistema de facturación del cliente se conecta con sus API keys' },
          accesoApi, 'Conexión por API (su sistema de facturación)')),
      h('div', { class: 'acciones' }, guardar)),
    seccionLogo(id, e.tiene_logo, refrescar),
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Certificado digital'),
        e.tiene_certificado
          ? aviso(`Cargado: ${e.cert_sujeto} · vence ${fecha(e.cert_vence, false)}`, 'ok')
          : aviso('Sin certificado: no se pueden firmar comprobantes.', 'alerta'),
        campo('Archivo .p12', archivo), campo('PIN del certificado', pin), h('div', { class: 'acciones' }, subirCert)),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Credenciales del API de Hacienda'),
        e.tiene_credenciales_hacienda ? aviso('Credenciales guardadas', 'ok') : aviso('Faltan las credenciales del API (ATV).', 'alerta'),
        campo('Usuario', usuario), campo('Contraseña', clave),
        h('div', { class: 'acciones' }, guardarCred, probar), resultadoPrueba)),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Integración con otros sistemas'),
      e.acceso_api ? null : aviso('La conexión por API está desactivada: las llaves de esta empresa no funcionan. Actívela en "Datos de la empresa".', 'alerta'),
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
