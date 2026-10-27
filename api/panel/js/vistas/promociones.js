// Categorías de productos y descuentos automáticos.
import { api } from '../api.js';
import { h, vaciar, dinero, fecha, tabla, modal, conBoton, toast, campo, aviso } from '../dom.js';
import { DESCUENTOS } from '../catalogos.js';
import { categoriasEmpresa } from './productos.js';
import { dialogoElegirProducto } from './emitir.js';

export async function vistaCategorias(cont) {
  const lista = await categoriasEmpresa();
  const refrescar = () => vistaCategorias(cont).catch((e) => toast(e.message, 'error'));
  const dialogo = (c) => {
    const nombre = h('input', { type: 'text', maxlength: '60', value: c?.nombre || '' });
    const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
      await api(c ? `/catalogo/categorias/${c.id}` : '/catalogo/categorias', { method: c ? 'PUT' : 'POST', body: { nombre: nombre.value.trim() } });
      m.cerrar();
      toast(c ? 'Categoría renombrada' : 'Categoría creada', 'ok');
      refrescar();
    }) }, 'Guardar');
    const m = modal(c ? `Categoría: ${c.nombre}` : 'Nueva categoría', [campo('Nombre', nombre)], { acciones: [guardar] });
  };
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Categorías'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogo(null) }, '+ Nueva categoría')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Nombre', valor: (c) => c.nombre },
      { titulo: 'Productos', num: true, valor: (c) => h('a', { href: '#/productos', onclick: (e) => e.stopPropagation() }, c.productos) },
      { titulo: '', valor: (c) => h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => {
        ev.stopPropagation();
        conBoton(ev.target, async () => {
          if (!window.confirm(`¿Eliminar la categoría "${c.nombre}"? Sus ${c.productos} producto(s) quedan sin categoría y se eliminan sus descuentos.`)) return;
          await api(`/catalogo/categorias/${c.id}`, { method: 'DELETE' });
          refrescar();
        });
      } }, 'Eliminar') },
    ], lista, dialogo)),
    h('p', { class: 'suave' }, 'Asigne la categoría al editar cada producto o en la carga desde Excel. '
      + 'Sirven para filtrar el catálogo, como botones en el punto de venta y para descuentos por categoría.'));
}

const ALCANCES = { todos: 'Todos los productos', categoria: 'Una categoría', producto: 'Un producto' };
// Códigos de Hacienda permitidos para descuentos automáticos (ver DescuentoRequest)
const CODIGOS = Object.fromEntries(Object.entries(DESCUENTOS).filter(([k]) => !['01', '02', '99'].includes(k)));

function resumenDescuento(d) {
  const valor = d.tipo === 'porcentaje' ? `${Number(d.valor)}%` : `${dinero(d.valor)} por unidad`;
  const desde = d.cantidad_minima ? ` desde ${Number(d.cantidad_minima)} unidades` : '';
  return `${valor}${desde}`;
}

function vigencia(d) {
  if (!d.desde && !d.hasta) return 'Siempre';
  const f = (x) => fecha(`${x}T12:00:00`, false);
  return `${d.desde ? f(d.desde) : '…'} – ${d.hasta ? f(d.hasta) : '…'}`;
}

function estadoDescuento(d) {
  const hoy = new Date().toISOString().slice(0, 10);
  if (!d.activo) return h('span', { class: 'badge PENDIENTE' }, 'Inactivo');
  if (d.hasta && d.hasta < hoy) return h('span', { class: 'badge RECHAZADO' }, 'Vencido');
  if (d.desde && d.desde > hoy) return h('span', { class: 'badge CONTINGENCIA' }, 'Programado');
  return h('span', { class: 'badge ACEPTADO' }, 'Vigente');
}

async function dialogoDescuento(d, alGuardar) {
  const categorias = await categoriasEmpresa();
  const f = {
    nombre: h('input', { type: 'text', maxlength: '100', value: d?.nombre || '', placeholder: 'Ej.: 10% en bebidas' }),
    tipo: h('select', {}, h('option', { value: 'porcentaje', selected: d?.tipo !== 'monto' }, 'Porcentaje del precio'),
      h('option', { value: 'monto', selected: d?.tipo === 'monto' }, 'Monto por unidad (sin IVA)')),
    valor: h('input', { type: 'number', step: '0.01', min: '0.01', value: d ? Number(d.valor) : '' }),
    alcance: h('select', {}, Object.entries(ALCANCES).map(([k, v]) => h('option', { value: k, selected: k === (d?.alcance || 'todos') }, v))),
    categoria_id: h('select', {}, categorias.map((c) => h('option', { value: c.id, selected: c.id === d?.categoria_id }, c.nombre))),
    cantidad_minima: h('input', { type: 'number', step: '0.001', min: '0', value: d?.cantidad_minima ? Number(d.cantidad_minima) : '', placeholder: 'Opcional (descuento por volumen)' }),
    codigo_descuento: h('select', {}, Object.entries(CODIGOS).map(([k, v]) => h('option', { value: k, selected: k === (d?.codigo_descuento || '06') }, `${k} · ${v}`))),
    desde: h('input', { type: 'date', value: d?.desde || '' }),
    hasta: h('input', { type: 'date', value: d?.hasta || '' }),
  };
  const activo = h('input', { type: 'checkbox', checked: d ? d.activo : true });
  let producto = d?.producto_id ? { id: d.producto_id, texto: d.producto } : null;
  const textoProducto = h('span');
  const pintarProducto = () => { textoProducto.textContent = producto ? producto.texto : 'Ninguno elegido'; };
  const elegir = h('button', { type: 'button', onclick: () => dialogoElegirProducto((p) => {
    producto = { id: p.id, texto: `${p.codigo} · ${p.descripcion}` };
    pintarProducto();
  }) }, 'Elegir producto');
  pintarProducto();
  const campoCategoria = campo('Categoría', f.categoria_id);
  const campoProducto = h('div', { class: 'fila' }, h('label', {}, 'Producto', textoProducto), elegir);
  const actualizar = () => {
    campoCategoria.classList.toggle('oculto', f.alcance.value !== 'categoria');
    campoProducto.classList.toggle('oculto', f.alcance.value !== 'producto');
  };
  f.alcance.addEventListener('change', actualizar);
  actualizar();

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = {
      nombre: f.nombre.value.trim(), tipo: f.tipo.value, valor: f.valor.value, alcance: f.alcance.value,
      categoria_id: f.alcance.value === 'categoria' ? f.categoria_id.value || null : null,
      producto_id: f.alcance.value === 'producto' ? producto?.id || null : null,
      cantidad_minima: f.cantidad_minima.value || null, codigo_descuento: f.codigo_descuento.value,
      desde: f.desde.value || null, hasta: f.hasta.value || null, activo: activo.checked,
    };
    await api(d ? `/catalogo/descuentos/${d.id}` : '/catalogo/descuentos', { method: d ? 'PUT' : 'POST', body: cuerpo });
    m.cerrar();
    toast('Descuento guardado', 'ok');
    alGuardar();
  }) }, 'Guardar');

  const m = modal(d ? `Descuento: ${d.nombre}` : 'Nuevo descuento', [
    h('div', { class: 'campos' }, h('div', { class: 'doble' }, campo('Nombre', f.nombre)),
      campo('Tipo', f.tipo), campo('Valor', f.valor), campo('Aplica a', f.alcance), campoCategoria, campoProducto,
      campo('Cantidad mínima', f.cantidad_minima), campo('Código de Hacienda', f.codigo_descuento),
      campo('Desde', f.desde), campo('Hasta', f.hasta),
      h('label', { class: 'check' }, activo, 'Activo')),
    categorias.length ? null : aviso('Aún no hay categorías: créelas en Productos → Categorías para descontar por categoría.', 'info'),
  ], { acciones: [guardar], ancho: true });
}

export async function vistaDescuentos(cont) {
  const lista = await api('/catalogo/descuentos');
  const refrescar = () => vistaDescuentos(cont).catch((e) => toast(e.message, 'error'));
  const abrir = (d) => dialogoDescuento(d, refrescar).catch((e) => toast(e.message, 'error'));
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Descuentos'),
      h('button', { type: 'button', class: 'primario', onclick: () => abrir(null) }, '+ Nuevo descuento')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Nombre', valor: (d) => d.nombre },
      { titulo: 'Descuento', valor: resumenDescuento },
      { titulo: 'Aplica a', valor: (d) => (d.alcance === 'categoria' ? `Categoría ${d.categoria}` : d.alcance === 'producto' ? d.producto : 'Todo') },
      { titulo: 'Vigencia', valor: vigencia },
      { titulo: 'Estado', valor: estadoDescuento },
      { titulo: '', valor: (d) => h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => {
        ev.stopPropagation();
        conBoton(ev.target, async () => {
          if (!window.confirm(`¿Eliminar el descuento "${d.nombre}"?`)) return;
          await api(`/catalogo/descuentos/${d.id}`, { method: 'DELETE' });
          refrescar();
        });
      } }, 'Eliminar') },
    ], lista, abrir)),
    aviso('Al agregar un producto del catálogo en la factura, la factura rápida o el punto de venta, se aplica solo el descuento '
      + 'vigente más favorable para el cliente (uno por línea). Si digita otro descuento en la línea, se respeta el suyo.', 'info'));
}
