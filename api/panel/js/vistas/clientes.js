import { api } from '../api.js';
import { h, vaciar, tabla, modal, conBoton, toast, campo, opciones, aviso, alCompletarCedula, avisoContribuyente, avisoNoInscrito } from '../dom.js';
import { TIPOS_IDENTIFICACION } from '../catalogos.js';

// Formulario de cliente (nuevo o edición). alGuardar recibe el cliente guardado.
export function dialogoCliente(cliente, alGuardar) {
  const c = cliente || {};
  const f = {
    tipo_identificacion: h('select', {}, opciones(TIPOS_IDENTIFICACION, c.tipo_identificacion || '01')),
    numero_identificacion: h('input', { type: 'text', maxlength: '20', value: c.numero_identificacion || '', placeholder: 'Sin guiones' }),
    nombre: h('input', { type: 'text', maxlength: '100', value: c.nombre || '' }),
    nombre_comercial: h('input', { type: 'text', maxlength: '80', value: c.nombre_comercial || '' }),
    correo: h('input', { type: 'email', value: c.correo || '' }),
    telefono: h('input', { type: 'tel', maxlength: '20', value: c.telefono || '', placeholder: '88887777' }),
    codigo_actividad: h('input', { type: 'text', maxlength: '6', value: c.codigo_actividad || '', placeholder: 'Opcional' }),
    provincia: h('input', { type: 'text', maxlength: '1', value: c.provincia || '', placeholder: '1' }),
    canton: h('input', { type: 'text', maxlength: '2', value: c.canton || '', placeholder: '01' }),
    distrito: h('input', { type: 'text', maxlength: '2', value: c.distrito || '', placeholder: '01' }),
    otras_senas: h('input', { type: 'text', maxlength: '250', value: c.otras_senas || '' }),
    notas: h('textarea', { rows: '2', maxlength: '1000' }, c.notas || ''),
  };

  // Al escribir la identificación se precargan los datos de Hacienda
  const info = h('div');
  const listaActividades = h('datalist', { id: 'actividades-cliente' });
  f.codigo_actividad.setAttribute('list', listaActividades.id);
  const consultar = alCompletarCedula(f.numero_identificacion, f.tipo_identificacion, async (id, vigente) => {
    vaciar(info, h('p', { class: 'suave' }, 'Consultando Hacienda…'));
    let r;
    try {
      r = await api(`/hacienda/contribuyentes/${id}`);
    } catch (e) {
      if (vigente()) vaciar(info, e.status === 404 ? avisoNoInscrito(id) : aviso(e.message, 'error'));
      return;
    }
    if (!vigente()) return;
    if (r.nombre) f.nombre.value = r.nombre;
    if (r.tipoIdentificacion) f.tipo_identificacion.value = r.tipoIdentificacion;
    const activas = (r.actividades || []).filter((a) => a.estado === 'A' || !a.estado);
    vaciar(listaActividades, activas.map((a) => h('option', { value: String(a.codigo).padStart(6, '0') }, a.descripcion)));
    const principal = activas.find((a) => a.tipo === 'P') || activas[0];
    f.codigo_actividad.value = principal ? String(principal.codigo).padStart(6, '0') : '';
    vaciar(info, avisoContribuyente(r, activas));
  });
  const buscar = h('button', { type: 'button', onclick: () => conBoton(buscar, consultar) }, 'Volver a consultar');

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = {};
    for (const [k, el] of Object.entries(f)) cuerpo[k] = el.value.trim() || null;
    const r = c.id
      ? await api(`/catalogo/clientes/${c.id}`, { method: 'PUT', body: cuerpo })
      : await api('/catalogo/clientes', { method: 'POST', body: cuerpo });
    m.cerrar();
    toast(c.id ? 'Cliente actualizado' : 'Cliente guardado', 'ok');
    alGuardar(r);
  }) }, 'Guardar');

  const m = modal(c.id ? `Cliente: ${c.nombre}` : 'Nuevo cliente', [
    h('div', { class: 'campos' },
      campo('Tipo de identificación', f.tipo_identificacion),
      h('div', { class: 'fila doble' }, campo('Identificación', f.numero_identificacion), buscar),
      campo('Nombre o razón social', f.nombre), campo('Nombre comercial', f.nombre_comercial),
      campo('Correo (recibe las facturas)', f.correo), campo('Teléfono', f.telefono),
      campo('Actividad económica', f.codigo_actividad)),
    info, listaActividades,
    h('h3', {}, 'Ubicación (opcional)'),
    h('div', { class: 'campos' }, campo('Provincia', f.provincia), campo('Cantón', f.canton),
      campo('Distrito', f.distrito), campo('Otras señas', f.otras_senas)),
    campo('Notas internas', f.notas),
  ], { acciones: [guardar], ancho: true });
}

export async function vistaClientes(cont, busqueda = '') {
  const q = h('input', { type: 'search', placeholder: 'Buscar por nombre o identificación', value: busqueda });
  const lista = await api(`/catalogo/clientes${busqueda ? `?q=${encodeURIComponent(busqueda)}` : ''}`);
  const refrescar = () => vistaClientes(cont, q.value.trim()).catch((e) => toast(e.message, 'error'));

  const eliminar = (c) => h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => {
    ev.stopPropagation();
    conBoton(ev.target, async () => {
      if (!window.confirm(`¿Quitar a ${c.nombre} del catálogo? Sus facturas no se afectan.`)) return;
      await api(`/catalogo/clientes/${c.id}`, { method: 'DELETE' });
      refrescar();
    });
  } }, 'Quitar');

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Clientes'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoCliente(null, refrescar) }, '+ Nuevo cliente')),
    h('form', { class: 'fila', onsubmit: (e) => { e.preventDefault(); refrescar(); } }, q,
      h('button', { type: 'submit' }, 'Buscar')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Nombre', valor: (c) => [c.nombre, c.nombre_comercial ? h('div', { class: 'suave' }, c.nombre_comercial) : null] },
      { titulo: 'Identificación', valor: (c) => h('span', { class: 'mono' }, c.numero_identificacion) },
      { titulo: 'Correo', valor: (c) => c.correo || '' },
      { titulo: 'Teléfono', valor: (c) => c.telefono || '' },
      { titulo: '', valor: eliminar },
    ], lista, (c) => dialogoCliente(c, refrescar))),
    h('p', { class: 'suave' }, 'Toque un cliente para editarlo. Al facturar, elíjalo en "Cliente (receptor)".'));
}
