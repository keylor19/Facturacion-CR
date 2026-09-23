import { api, descargar } from '../api.js';
import { h, vaciar, dinero, fecha, badge, tabla, modal, conBoton, toast, campo, opciones, aviso, TIPOS } from '../dom.js';
import { CONDICIONES_IMPUESTO } from '../catalogos.js';

const MENSAJES = { 1: 'Aceptado', 2: 'Aceptado parcialmente', 3: 'Rechazado' };

export async function vistaRecepcion(cont) {
  const soloPendientes = h('input', { type: 'checkbox', checked: true });
  const resultados = h('div');

  async function cargar() {
    const lista = await api(`/recepcion?limit=200${soloPendientes.checked ? '&pendientes=true' : ''}`);
    vaciar(resultados, tabla([
      { titulo: 'Fecha', valor: (d) => fecha(d.fecha_emision) },
      { titulo: 'Tipo', valor: (d) => TIPOS[d.tipo_documento] || d.tipo_documento },
      { titulo: 'Proveedor', valor: (d) => [d.proveedor_nombre, h('div', { class: 'suave' }, d.proveedor_identificacion)] },
      { titulo: 'IVA', num: true, valor: (d) => dinero(d.total_impuesto, d.moneda) },
      { titulo: 'Total', num: true, valor: (d) => dinero(d.total_comprobante, d.moneda) },
      { titulo: 'Firma', valor: (d) => (d.firma_valida ? '✔ válida' : h('span', { class: 'badge RECHAZADO' }, 'no válida')) },
      { titulo: 'Respuesta', valor: (d) => (d.mensaje ? [MENSAJES[d.mensaje], ' ', badge(d.estado)] : badge(null)) },
      { titulo: '', valor: (d) => acciones(d) },
    ], lista));
  }

  function acciones(d) {
    const botones = [h('button', { type: 'button', class: 'chico', onclick: (e) => { e.stopPropagation(); descargar(`/recepcion/${d.id}/xml?tipo=original`, `${d.clave}.xml`).catch((er) => toast(er.message, 'error')); } }, 'XML')];
    if (!d.estado || d.estado === 'RECHAZADO') {
      botones.push(h('button', { type: 'button', class: 'chico primario', onclick: () => dialogoResponder(d, () => cargar().catch(err)) }, 'Responder'));
    } else if (['ERROR_COMUNICACION', 'CONTINGENCIA', 'ENVIADO', 'PENDIENTE'].includes(d.estado)) {
      botones.push(h('button', { type: 'button', class: 'chico', onclick: (e) => conBoton(e.target, async () => {
        await api(`/recepcion/${d.id}/reenviar`, { method: 'POST' });
        toast('Reenvío / consulta encolada', 'ok');
      }) }, 'Reintentar'));
    }
    return h('div', { class: 'acciones' }, botones);
  }

  // Carga de archivos (uno o varios XML)
  const archivos = h('input', { type: 'file', accept: '.xml,application/xml,text/xml', multiple: true });
  const subir = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(subir, async () => {
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

  soloPendientes.addEventListener('change', () => cargar().catch(err));

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Facturas de proveedores'),
      h('label', { class: 'check' }, soloPendientes, 'Solo sin responder')),
    h('section', { class: 'tarjeta' },
      h('h2', {}, 'Registrar comprobantes recibidos'),
      h('div', { class: 'subir' }, h('p', {}, 'Seleccione los XML de las facturas que le enviaron sus proveedores.'), archivos),
      h('div', { class: 'acciones' }, subir)),
    h('section', { class: 'tarjeta' }, resultados));
  await cargar();
}

function err(e) { toast(e.message, 'error'); }

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
    h('dl', { class: 'datos' },
      h('dt', {}, 'Proveedor'), h('dd', {}, `${d.proveedor_nombre} (${d.proveedor_identificacion})`),
      h('dt', {}, 'Clave'), h('dd', { class: 'mono' }, d.clave),
      h('dt', {}, 'Total'), h('dd', {}, dinero(d.total_comprobante, d.moneda)),
      h('dt', {}, 'IVA'), h('dd', {}, dinero(d.total_impuesto, d.moneda))),
    d.firma_valida ? null : aviso('La firma digital de este XML no es válida. Considere rechazarlo.', 'alerta'),
    campo('Respuesta', mensaje),
    bloqueImpuesto,
    campo('Detalle (obligatorio para aceptación parcial o rechazo)', detalle),
  ], { acciones: [enviar] });
}
