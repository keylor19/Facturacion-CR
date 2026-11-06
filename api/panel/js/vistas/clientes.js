// Clientes frecuentes de la empresa: lista, alta y edición, importación desde CSV y reporte de ventas por cliente.
import { api } from '../api.js';
import { h, vaciar, tabla, modal, conBoton, toast, campo, opciones, aviso, alCompletarCedula, avisoContribuyente, avisoNoInscrito, limpiarIdentificacion } from '../dom.js';
import { TIPOS_IDENTIFICACION } from '../catalogos.js';
import { selectorUbicacion } from '../ubicacion.js';
import { descargarCsv, pantallaCarga } from '../csv.js';

// Formulario de cliente (nuevo o edición). alGuardar recibe el cliente guardado.
export function dialogoCliente(cliente, alGuardar) {
  const c = cliente || {};
  const ubicacion = selectorUbicacion(c);
  const f = {
    tipo_identificacion: h('select', {}, opciones(TIPOS_IDENTIFICACION, c.tipo_identificacion || '01')),
    numero_identificacion: h('input', { type: 'text', maxlength: '20', value: c.numero_identificacion || '', placeholder: 'Sin guiones' }),
    nombre: h('input', { type: 'text', maxlength: '100', value: c.nombre || '' }),
    nombre_comercial: h('input', { type: 'text', maxlength: '80', value: c.nombre_comercial || '' }),
    correo: h('input', { type: 'email', value: c.correo || '' }),
    telefono: h('input', { type: 'tel', maxlength: '20', value: c.telefono || '', placeholder: '88887777' }),
    codigo_actividad: h('input', { type: 'text', maxlength: '6', value: c.codigo_actividad || '', placeholder: 'Opcional' }),
    provincia: ubicacion.provincia,
    canton: ubicacion.canton,
    distrito: ubicacion.distrito,
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
      if (vigente()) vaciar(info, e.status === 404 ? avisoNoInscrito(id, { comoCliente: true }) : aviso(e.message, 'error'));
      return;
    }
    if (!vigente()) return;
    if (r.nombre) f.nombre.value = r.nombre;
    if (r.tipoIdentificacion) f.tipo_identificacion.value = r.tipoIdentificacion;
    const activas = (r.actividades || []).filter((a) => a.estado === 'A' || !a.estado);
    vaciar(listaActividades, activas.map((a) => h('option', { value: String(a.codigo).padStart(6, '0') }, a.descripcion)));
    const principal = activas.find((a) => a.tipo === 'P') || activas[0];
    f.codigo_actividad.value = principal ? String(principal.codigo).padStart(6, '0') : '';
    vaciar(info, avisoContribuyente(r, activas, { comoCliente: true }));
  });
  const buscar = h('button', { type: 'button', onclick: () => conBoton(buscar, consultar) }, 'Buscar en Hacienda');

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
      h('div', { class: 'acciones' },
        h('a', { href: '#/clientes/cargar', class: 'boton' }, 'Cargar desde Excel'),
        h('a', { href: '#/clientes/reporte', class: 'boton' }, 'Reporte'),
        h('button', { type: 'button', class: 'primario', onclick: () => dialogoCliente(null, refrescar) }, '+ Nuevo cliente'))),
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

const COLUMNAS_CSV = ['tipo_identificacion', 'numero_identificacion', 'nombre', 'nombre_comercial', 'correo', 'telefono',
  'codigo_actividad', 'provincia', 'canton', 'distrito', 'otras_senas', 'notas'];

export async function vistaCargarClientes(cont) {
  vaciar(cont, pantallaCarga({
    titulo: 'Cargar clientes',
    volver: h('a', { href: '#/clientes' }, '← Clientes'),
    descripcion: 'Una fila por cliente. Obligatorios: tipo de identificación (01 física, 02 jurídica, 03 DIMEX, 04 NITE), '
      + 'identificación sin guiones y nombre. Ubicación con códigos de Hacienda (provincia 1-7, cantón y distrito de 2 dígitos). '
      + 'Los clientes que ya existen se reportan y no se modifican.',
    plantilla: 'plantilla-clientes.csv',
    ejemplo: [COLUMNAS_CSV,
      ['01', '112345678', 'Juan Pérez Mora', '', 'juan@correo.com', '88887777', '', '1', '01', '01', 'Del parque 100 m norte', ''],
      ['02', '3101123456', 'Comercial Ejemplo S.A.', 'Ejemplo', 'facturas@ejemplo.cr', '22223333', '523002', '', '', '', '', '']],
    columnas: [
      { titulo: 'Identificación', valor: (r) => h('span', { class: 'mono' }, r.fila.numero_identificacion || '') },
      { titulo: 'Nombre', valor: (r) => r.fila.nombre || '' },
      { titulo: 'Correo', valor: (r) => r.fila.correo || '' },
    ],
    convertir(fila) {
      const cuerpo = {};
      for (const k of COLUMNAS_CSV) cuerpo[k] = fila[k] || null;
      if (cuerpo.tipo_identificacion) cuerpo.tipo_identificacion = cuerpo.tipo_identificacion.padStart(2, '0');
      if (cuerpo.numero_identificacion) cuerpo.numero_identificacion = limpiarIdentificacion(cuerpo.numero_identificacion);
      if (cuerpo.telefono) cuerpo.telefono = cuerpo.telefono.replace(/\D/g, '');
      if (cuerpo.codigo_actividad) cuerpo.codigo_actividad = cuerpo.codigo_actividad.replace(/\D/g, '').padStart(6, '0');
      for (const k of ['canton', 'distrito']) if (cuerpo[k]) cuerpo[k] = cuerpo[k].padStart(2, '0');
      if (!TIPOS_IDENTIFICACION[cuerpo.tipo_identificacion]) return { error: 'Tipo de identificación no válido' };
      if (!cuerpo.numero_identificacion) return { error: 'Falta la identificación' };
      if (!cuerpo.nombre) return { error: 'Falta el nombre' };
      return { cuerpo };
    },
    enviar: (cuerpo) => api('/catalogo/clientes', { method: 'POST', body: cuerpo }),
  }));
}

export async function vistaReporteClientes(cont) {
  const lista = await api('/catalogo/clientes?limite=1000');
  const exportar = () => descargarCsv('clientes.csv',
    ['Tipo', 'Identificación', 'Nombre', 'Nombre comercial', 'Correo', 'Teléfono', 'Actividad', 'Provincia', 'Cantón', 'Distrito', 'Otras señas', 'Notas'],
    lista.map((c) => [TIPOS_IDENTIFICACION[c.tipo_identificacion] || c.tipo_identificacion, c.numero_identificacion, c.nombre,
      c.nombre_comercial, c.correo, c.telefono, c.codigo_actividad, c.provincia, c.canton, c.distrito, c.otras_senas, c.notas]));
  const sinCorreo = lista.filter((c) => !c.correo).length;
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('div', {}, h('a', { href: '#/clientes' }, '← Clientes'), h('h1', {}, 'Reporte de clientes')),
      h('button', { type: 'button', class: 'primario', onclick: exportar }, 'Descargar (Excel)')),
    h('div', { class: 'kpis' },
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Clientes registrados'), h('div', { class: 'valor' }, lista.length)),
      h('div', { class: `kpi ${sinCorreo ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, 'Sin correo (no reciben la factura)'), h('div', { class: 'valor' }, sinCorreo))),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Nombre', valor: (c) => c.nombre },
      { titulo: 'Tipo', valor: (c) => TIPOS_IDENTIFICACION[c.tipo_identificacion] || c.tipo_identificacion },
      { titulo: 'Identificación', valor: (c) => h('span', { class: 'mono' }, c.numero_identificacion) },
      { titulo: 'Correo', valor: (c) => c.correo || h('span', { class: 'badge CONTINGENCIA' }, 'Sin correo') },
      { titulo: 'Teléfono', valor: (c) => c.telefono || '' },
      { titulo: 'Actividad', valor: (c) => c.codigo_actividad || '' },
    ], lista)));
}
