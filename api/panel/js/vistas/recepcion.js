// Aceptación de documentos: las facturas de proveedores llegan solas desde el
// correo de la empresa (o se suben a mano) y aquí solo se aceptan o rechazan.
import { api, descargar } from '../api.js';
import { h, vaciar, dinero, fecha, badge, tabla, modal, conBoton, toast, campo, opciones, aviso, TIPOS } from '../dom.js';
import { CONDICIONES_IMPUESTO } from '../catalogos.js';

const MENSAJES = { 1: 'Aceptado', 2: 'Aceptado parcialmente', 3: 'Rechazado' };
const ORIGENES = { correo: 'Correo', manual: 'Subido', api: 'API' };

export async function vistaRecepcion(cont) {
  const soloPendientes = h('input', { type: 'checkbox', checked: true });
  const resultados = h('div');
  const estadoBuzon = h('section', { class: 'tarjeta' });

  async function cargar() {
    const lista = await api(`/recepcion?limit=200${soloPendientes.checked ? '&pendientes=true' : ''}`);
    vaciar(resultados, tabla([
      { titulo: 'Fecha', valor: (d) => [fecha(d.fecha_emision, false), h('div', { class: 'suave' }, ORIGENES[d.origen] || '')] },
      { titulo: 'Proveedor', valor: (d) => [d.proveedor_nombre, h('div', { class: 'suave' }, `${TIPOS[d.tipo_documento] || ''} · ${d.proveedor_identificacion}`)] },
      { titulo: 'IVA', num: true, valor: (d) => dinero(d.total_impuesto, d.moneda) },
      { titulo: 'Total', num: true, valor: (d) => h('strong', {}, dinero(d.total_comprobante, d.moneda)) },
      { titulo: 'Estado', valor: (d) => [
        d.firma_valida ? null : h('div', {}, h('span', { class: 'badge RECHAZADO' }, 'Firma no válida')),
        d.mensaje ? [MENSAJES[d.mensaje], ' ', badge(d.estado)] : h('span', { class: 'badge PENDIENTE' }, 'Por responder'),
        d.detalle_mensaje ? h('div', { class: 'suave' }, `“${d.detalle_mensaje}”`) : null] },
      { titulo: '', valor: (d) => acciones(d) },
    ], lista));
    if (!lista.length) {
      resultados.append(aviso(soloPendientes.checked
        ? 'No hay facturas por responder. Las que lleguen al correo aparecerán aquí solas.'
        : 'Aún no hay facturas de proveedores registradas.', 'info'));
    }
  }
  const recargar = () => cargar().catch(err);

  function acciones(d) {
    const xml = h('button', { type: 'button', class: 'chico', title: 'Descargar el XML del proveedor', onclick: (e) => {
      e.stopPropagation();
      descargar(`/recepcion/${d.id}/xml?tipo=original`, `${d.clave}.xml`).catch(err);
    } }, 'XML');
    if (!d.estado || d.estado === 'RECHAZADO') {
      return h('div', { class: 'acciones' },
        h('button', { type: 'button', class: 'chico primario', onclick: () => dialogoRapido(d, '1', recargar) }, 'Aceptar'),
        h('button', { type: 'button', class: 'chico peligro', onclick: () => dialogoRapido(d, '3', recargar) }, 'Rechazar'),
        h('button', { type: 'button', class: 'chico', title: 'Aceptación parcial o condición del IVA', onclick: () => dialogoResponder(d, recargar) }, 'Más…'),
        xml);
    }
    if (['ERROR_COMUNICACION', 'CONTINGENCIA', 'ENVIADO', 'PENDIENTE'].includes(d.estado)) {
      return h('div', { class: 'acciones' }, h('button', { type: 'button', class: 'chico', onclick: (e) => conBoton(e.target, async () => {
        await api(`/recepcion/${d.id}/reenviar`, { method: 'POST' });
        toast('Reenvío / consulta encolada', 'ok');
      }) }, 'Reintentar'), xml);
    }
    return xml;
  }

  // Carga manual (para lo que no llegó por correo)
  const archivos = h('input', { type: 'file', accept: '.xml,application/xml,text/xml', multiple: true });
  const subir = h('button', { type: 'button', onclick: () => conBoton(subir, async () => {
    if (!archivos.files.length) { toast('Seleccione uno o más archivos XML', 'error'); return; }
    const errores = [];
    let ok = 0;
    for (const archivo of archivos.files) {
      const form = new FormData();
      form.append('archivo', archivo);
      try { await api('/recepcion/archivo', { method: 'POST', form }); ok += 1; } catch (e) { errores.push(`${archivo.name}: ${e.message}`); }
    }
    archivos.value = '';
    if (ok) toast(`${ok} comprobante(s) registrado(s)`, 'ok');
    if (errores.length) toast(errores.join('\n'), 'error');
    await cargar();
  }) }, 'Registrar');

  soloPendientes.addEventListener('change', recargar);

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Aceptación de documentos'),
      h('label', { class: 'check' }, soloPendientes, 'Solo por responder')),
    estadoBuzon,
    h('section', { class: 'tarjeta' }, resultados),
    h('details', { class: 'tarjeta' },
      h('summary', {}, 'Subir XML manualmente'),
      h('div', { class: 'subir' }, h('p', {}, 'Para facturas que no llegaron al correo conectado.'), archivos),
      h('div', { class: 'acciones' }, subir)));
  await Promise.all([cargar(), pintarBuzon(estadoBuzon, recargar)]);
}

function err(e) { toast(e.message, 'error'); }

// --- Buzón de correo ----------------------------------------------------------------

async function pintarBuzon(seccion, alImportar) {
  const b = await api('/buzon-correo');
  const repintar = () => pintarBuzon(seccion, alImportar).catch(err);
  if (!b) {
    vaciar(seccion,
      h('div', { class: 'encabezado' }, h('h2', {}, 'Recibir las facturas automáticamente'),
        h('button', { type: 'button', class: 'primario', onclick: () => dialogoBuzon(null, repintar) }, 'Conectar correo')),
      h('p', { class: 'suave' }, 'Conecte el correo donde sus proveedores le envían las facturas electrónicas. '
        + 'Cada 5 minutos el sistema toma los XML adjuntos y los deja aquí listos para aceptar o rechazar.'));
    return;
  }
  const revisar = h('button', { type: 'button', onclick: () => conBoton(revisar, async () => {
    const r = await api('/buzon-correo/revisar', { method: 'POST' });
    toast(r.importados ? `${r.importados} factura(s) nueva(s) del correo` : 'No hay facturas nuevas en el correo', 'ok');
    await repintar();
    if (r.importados) alImportar();
  }) }, 'Revisar ahora');
  const estado = !b.activo ? h('span', { class: 'badge PENDIENTE' }, 'Pausado')
    : b.ultimo_error ? h('span', { class: 'badge RECHAZADO' }, 'Con error') : h('span', { class: 'badge ACEPTADO' }, 'Conectado');
  vaciar(seccion,
    h('div', { class: 'encabezado' },
      h('div', {}, h('h2', {}, 'Correo de facturas ', estado),
        h('p', { class: 'suave' }, `${b.usuario} · ${b.ultima_revision ? `revisado ${fecha(b.ultima_revision)}` : 'aún sin revisar'}`
          + ` · ${b.documentos_importados} factura(s) importada(s)`)),
      h('div', { class: 'acciones' }, b.activo ? revisar : null,
        h('button', { type: 'button', onclick: () => dialogoBuzon(b, repintar) }, 'Configurar'))),
    b.ultimo_error ? aviso(`No se pudo leer el correo: ${b.ultimo_error}`, 'error') : null);
}

function dialogoBuzon(b, alGuardar) {
  const f = {
    servidor: h('input', { type: 'text', maxlength: '200', value: b?.servidor || '', placeholder: 'imap.gmail.com', autocomplete: 'off' }),
    puerto: h('input', { type: 'number', min: '1', max: '65535', value: String(b?.puerto || 993) }),
    usuario: h('input', { type: 'email', maxlength: '200', value: b?.usuario || '', placeholder: 'facturas@suempresa.com', autocomplete: 'off' }),
    password: h('input', { type: 'password', maxlength: '200', autocomplete: 'new-password', placeholder: b ? 'Dejar vacío para conservar la actual' : '' }),
    carpeta: h('input', { type: 'text', maxlength: '200', value: b?.carpeta || 'INBOX' }),
  };
  const activo = h('input', { type: 'checkbox', checked: b ? b.activo : true });
  // Servidores comunes: al escribir el correo se sugiere el servidor IMAP
  const SERVIDORES = { 'gmail.com': 'imap.gmail.com', 'outlook.com': 'outlook.office365.com', 'hotmail.com': 'outlook.office365.com',
    'live.com': 'outlook.office365.com', 'yahoo.com': 'imap.mail.yahoo.com', 'icloud.com': 'imap.mail.me.com' };
  f.usuario.addEventListener('change', () => {
    const dominio = f.usuario.value.split('@')[1]?.toLowerCase();
    if (!f.servidor.value && SERVIDORES[dominio]) f.servidor.value = SERVIDORES[dominio];
  });

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    await api('/buzon-correo', { method: 'PUT', body: {
      servidor: f.servidor.value.trim(), puerto: Number(f.puerto.value || 993), usuario: f.usuario.value.trim(),
      password: f.password.value || null, carpeta: f.carpeta.value.trim() || 'INBOX', activo: activo.checked,
    } });
    m.cerrar();
    toast('Correo conectado. Las facturas se revisarán cada 5 minutos.', 'ok');
    alGuardar();
  }) }, 'Probar y guardar');
  const desconectar = b ? h('button', { type: 'button', class: 'peligro', onclick: () => conBoton(desconectar, async () => {
    if (!window.confirm('¿Desconectar el correo? Las facturas ya importadas se conservan.')) return;
    await api('/buzon-correo', { method: 'DELETE' });
    m.cerrar();
    alGuardar();
  }) }, 'Desconectar') : null;

  const m = modal(b ? 'Correo de facturas' : 'Conectar el correo de facturas', [
    h('div', { class: 'campos' }, campo('Correo', f.usuario), campo('Contraseña', f.password),
      campo('Servidor IMAP', f.servidor), campo('Puerto (SSL)', f.puerto), campo('Carpeta', f.carpeta),
      h('label', { class: 'check' }, activo, 'Revisar automáticamente')),
    aviso('Gmail y Outlook piden una "contraseña de aplicación" (no la contraseña normal) y tener IMAP activado. '
      + 'Recomendamos un correo exclusivo para facturas. El sistema solo lee: no borra ni marca los correos como leídos. '
      + 'La primera vez importa las facturas de los últimos 30 días.', 'info'),
  ], { acciones: [desconectar, guardar].filter(Boolean) });
}

// --- Respuesta a Hacienda -----------------------------------------------------------

function resumen(d) {
  return h('dl', { class: 'datos' },
    h('dt', {}, 'Proveedor'), h('dd', {}, `${d.proveedor_nombre} (${d.proveedor_identificacion})`),
    h('dt', {}, 'Fecha'), h('dd', {}, fecha(d.fecha_emision)),
    h('dt', {}, 'Total'), h('dd', {}, h('strong', {}, dinero(d.total_comprobante, d.moneda))),
    h('dt', {}, 'IVA'), h('dd', {}, dinero(d.total_impuesto, d.moneda)),
    h('dt', {}, 'Clave'), h('dd', { class: 'mono' }, d.clave));
}

// Aceptar (con todo el IVA como crédito) o rechazar, con un comentario
function dialogoRapido(d, mensaje, alTerminar) {
  const rechazo = mensaje === '3';
  const comentario = h('textarea', { rows: '3', maxlength: '160', placeholder: rechazo ? 'Ej.: Monto no corresponde a lo pedido' : 'Opcional' });
  const enviar = h('button', { type: 'button', class: rechazo ? 'peligro' : 'primario', onclick: () => conBoton(enviar, async () => {
    const detalle = comentario.value.trim();
    if (rechazo && !detalle) { toast('Indique el motivo del rechazo', 'error'); return; }
    const cuerpo = { mensaje };
    if (detalle) cuerpo.detalle_mensaje = detalle;
    if (!rechazo && Number(d.total_impuesto) > 0) {
      cuerpo.condicion_impuesto = '01';
      cuerpo.monto_impuesto_acreditar = String(d.total_impuesto);
    }
    await api(`/recepcion/${d.id}/mensaje`, { method: 'POST', body: cuerpo });
    m.cerrar();
    toast(rechazo ? 'Factura rechazada ante Hacienda' : 'Factura aceptada ante Hacienda', 'ok');
    alTerminar();
  }) }, rechazo ? 'Rechazar factura' : 'Aceptar factura');
  const m = modal(rechazo ? 'Rechazar factura' : 'Aceptar factura', [
    resumen(d),
    d.firma_valida ? null : aviso('La firma digital de este XML no es válida. Considere rechazarlo.', 'alerta'),
    campo(rechazo ? 'Motivo del rechazo (obligatorio, lo verá el proveedor)' : 'Comentario', comentario),
    rechazo || !Number(d.total_impuesto) ? null
      : h('p', { class: 'suave' }, 'Se acredita todo el IVA (condición 01). Para otra condición use "Más…".'),
  ], { acciones: [enviar] });
  comentario.focus();
}

function dialogoResponder(d, alTerminar) {
  const mensaje = h('select', {}, Object.entries(MENSAJES).map(([k, v]) => h('option', { value: k }, v)));
  const condicion = h('select', {}, opciones(CONDICIONES_IMPUESTO, '01'));
  const acreditar = h('input', { type: 'number', step: '0.01', min: '0', value: String(d.total_impuesto) });
  const gasto = h('input', { type: 'number', step: '0.01', min: '0' });
  const detalle = h('input', { type: 'text', maxlength: '160' });
  const bloqueImpuesto = h('div', { class: 'campos' },
    campo('Condición del IVA', condicion), campo('IVA a acreditar', acreditar), campo('Gasto aplicable', gasto));
  const sinIva = Number(d.total_impuesto) === 0;
  const actualizar = () => bloqueImpuesto.classList.toggle('oculto', mensaje.value === '3' || sinIva);
  mensaje.addEventListener('change', actualizar);
  actualizar();

  const enviar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(enviar, async () => {
    const cuerpo = { mensaje: mensaje.value };
    if (detalle.value.trim()) cuerpo.detalle_mensaje = detalle.value.trim();
    if (mensaje.value !== '3' && !sinIva) {
      cuerpo.condicion_impuesto = condicion.value;
      if (acreditar.value !== '') cuerpo.monto_impuesto_acreditar = acreditar.value;
      if (gasto.value !== '') cuerpo.monto_gasto_aplicable = gasto.value;
    }
    await api(`/recepcion/${d.id}/mensaje`, { method: 'POST', body: cuerpo });
    m.cerrar();
    toast('Mensaje receptor firmado y enviado a Hacienda', 'ok');
    alTerminar();
  }) }, 'Firmar y enviar');

  const m = modal('Responder comprobante', [
    resumen(d),
    d.firma_valida ? null : aviso('La firma digital de este XML no es válida. Considere rechazarlo.', 'alerta'),
    campo('Respuesta', mensaje),
    bloqueImpuesto,
    campo('Detalle (obligatorio para aceptación parcial o rechazo)', detalle),
  ], { acciones: [enviar] });
}
