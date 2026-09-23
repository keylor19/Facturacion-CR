import { api, sesion } from '../api.js';
import { h, vaciar, fecha, tabla, modal, conBoton, toast, campo, opciones, aviso } from '../dom.js';
import { TIPOS_IDENTIFICACION } from '../catalogos.js';
import { contexto, cargarContexto, enrutar } from '../app.js';
import { kpisSaldo, tablaPaquetes } from './saldo.js';

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

const CAMPOS = [
  ['nombre', 'Razón social / nombre', 'text', 100],
  ['nombre_comercial', 'Nombre comercial', 'text', 80],
  ['codigo_actividad', 'Código de actividad', 'text', 6],
  ['correo', 'Correo', 'email', 160],
  ['telefono', 'Teléfono', 'text', 20],
  ['provincia', 'Provincia (1-7)', 'text', 1],
  ['canton', 'Cantón (2 dígitos)', 'text', 2],
  ['distrito', 'Distrito (2 dígitos)', 'text', 2],
  ['barrio', 'Barrio', 'text', 50],
  ['otras_senas', 'Otras señas', 'text', 250],
  ['proveedor_sistemas', 'Proveedor de sistemas (identificación)', 'text', 12],
  ['registro_fiscal_8707', 'Registro fiscal bebidas alcohólicas (Ley 8707)', 'text', 12],
];

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

  const autocompletar = h('button', { type: 'button', onclick: () => conBoton(autocompletar, async () => {
    const c = await api(`/hacienda/contribuyentes/${numero.value.replace(/\D/g, '')}`, { conEmisor: false });
    entradas.nombre.value = c.nombre || '';
    if (c.tipoIdentificacion) tipo.value = c.tipoIdentificacion;
    const principal = (c.actividades || []).find((a) => a.tipo === 'P' && a.estado === 'A') || c.actividades?.[0];
    if (principal) entradas.codigo_actividad.value = String(principal.codigo).padStart(6, '0');
  }) }, 'Datos de Hacienda');

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
    h('div', { class: 'campos' }, CAMPOS.map(([k, etiqueta]) => campo(etiqueta, entradas[k]))),
  ], { acciones: [guardar], ancho: true });
}

export async function vistaDetalleEmpresa(cont, id) {
  if (!contexto.esAdmin) { sinPermiso(cont); return; }
  const [e, llaves, saldoEmpresa, planes] = await Promise.all([
    api(`/emisores/${id}`, { conEmisor: false }),
    api(`/api-keys?emisor_id=${id}`, { conEmisor: false }),
    api(`/emisores/${id}/paquetes`, { conEmisor: false }),
    api('/planes?activos=true', { conEmisor: false }),
  ]);
  // Pasa por el enrutador para recargar también el saldo de la barra superior
  const refrescar = () => enrutar();

  // Datos generales
  const entradas = Object.fromEntries(CAMPOS.map(([k, , t, max]) => [k, h('input', { type: t, maxlength: String(max), value: e[k] || '' })]));
  const ambiente = h('select', {}, h('option', { value: 'stag', selected: e.ambiente === 'stag' }, 'Pruebas (stag)'),
    h('option', { value: 'prod', selected: e.ambiente === 'prod' }, 'Producción'));
  const activo = h('input', { type: 'checkbox', checked: e.activo });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = { ambiente: ambiente.value, activo: activo.checked };
    for (const [k, el] of Object.entries(entradas)) cuerpo[k] = el.value.trim() || null;
    for (const k of ['nombre', 'codigo_actividad', 'correo', 'provincia', 'canton', 'distrito', 'otras_senas']) {
      if (!cuerpo[k]) delete cuerpo[k];
    }
    await api(`/emisores/${id}`, { method: 'PATCH', body: cuerpo, conEmisor: false });
    await cargarContexto();
    toast('Datos guardados', 'ok');
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
    vaciar(nuevaLlave, h('div', { class: 'secreto' }, 'Copie la llave ahora, no se volverá a mostrar: ', h('span', { class: 'mono' }, r.api_key)));
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
    seccionSaldo,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Datos de la empresa'),
      h('div', { class: 'campos' }, CAMPOS.map(([k, etiqueta]) => campo(etiqueta, entradas[k])),
        campo('Ambiente de Hacienda', ambiente), h('label', { class: 'check' }, activo, 'Empresa activa')),
      h('div', { class: 'acciones' }, guardar)),
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
