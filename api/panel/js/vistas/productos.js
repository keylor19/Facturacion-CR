import { api } from '../api.js';
import { h, vaciar, tabla, modal, conBoton, toast, campo, dinero, fecha } from '../dom.js';
import { TARIFAS_IVA, UNIDADES } from '../catalogos.js';
import { dialogoCabys } from './emitir.js';

const TARIFA_POR_PORCENTAJE = { 13: '08', 8: '07', 4: '04', 2: '03', 1: '02', 0.5: '09' };
const TIPOS_MOVIMIENTO = {
  venta: 'Venta', devolucion: 'Devolución', compra: 'Compra', reverso: 'Reverso (rechazo)',
  entrada: 'Entrada', salida: 'Salida', ajuste: 'Ajuste',
};
export const cantidad = (v) => (v === null || v === undefined ? '' : Number(v).toLocaleString('es-CR', { maximumFractionDigits: 3 }));

export function existenciaBadge(p) {
  if (!p.controla_inventario) return h('span', { class: 'suave' }, 'No controla');
  return h('span', { class: `badge ${p.bajo_minimo ? 'RECHAZADO' : 'ACEPTADO'}`, title: p.bajo_minimo ? 'En o por debajo del mínimo' : '' },
    `${cantidad(p.existencia)} ${p.unidad_medida}`);
}

export function dialogoProducto(producto, alGuardar) {
  const p = producto || {};
  const nuevo = !p.id;
  const f = {
    codigo: h('input', { type: 'text', maxlength: '20', value: p.codigo || '', placeholder: 'Código interno, p. ej. MART-01' }),
    codigo_cabys: h('input', { type: 'text', maxlength: '13', value: p.codigo_cabys || '', placeholder: '13 dígitos' }),
    descripcion: h('input', { type: 'text', maxlength: '200', value: p.descripcion || '' }),
    unidad_medida: h('select', {}, Object.entries(UNIDADES).map(([k, v]) => h('option', { value: k, selected: k === (p.unidad_medida || 'Unid') }, `${k} · ${v}`))),
    precio_unitario: h('input', { type: 'number', step: '0.01', min: '0', value: p.precio_unitario ?? '' }),
    codigo_tarifa_iva: h('select', {}, Object.entries(TARIFAS_IVA).map(([k, [t]]) => h('option', { value: k, selected: k === (p.codigo_tarifa_iva || '08') }, t))),
    costo_unitario: h('input', { type: 'number', step: '0.01', min: '0', value: p.costo_unitario ?? '', placeholder: 'Opcional' }),
    existencia_minima: h('input', { type: 'number', step: '0.001', min: '0', value: p.existencia_minima ?? '', placeholder: 'Avisar al llegar a…' }),
    existencia_inicial: h('input', { type: 'number', step: '0.001', min: '0', value: '0' }),
  };
  const esServicio = h('input', { type: 'checkbox', checked: !!p.es_servicio });
  const controla = h('input', { type: 'checkbox', checked: nuevo ? true : !!p.controla_inventario });
  const bloqueInventario = h('div', { class: 'campos' },
    nuevo ? campo('Existencia inicial', f.existencia_inicial) : null,
    campo('Existencia mínima', f.existencia_minima), campo('Costo unitario (sin IVA)', f.costo_unitario));
  const actualizar = () => {
    if (esServicio.checked) controla.checked = false;
    controla.disabled = esServicio.checked;
    bloqueInventario.classList.toggle('oculto', !controla.checked);
  };
  esServicio.addEventListener('change', actualizar);
  controla.addEventListener('change', actualizar);
  actualizar();

  const buscarCabys = h('button', { type: 'button', onclick: () => dialogoCabys((item) => {
    f.codigo_cabys.value = item.codigo;
    if (!f.descripcion.value) f.descripcion.value = String(item.descripcion).slice(0, 200);
    const t = TARIFA_POR_PORCENTAJE[Number(item.impuesto)];
    if (t) f.codigo_tarifa_iva.value = t;
  }) }, 'Buscar CABYS');

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = {
      codigo: f.codigo.value.trim(), codigo_cabys: f.codigo_cabys.value.trim(), descripcion: f.descripcion.value.trim(),
      unidad_medida: f.unidad_medida.value, precio_unitario: f.precio_unitario.value || '0',
      codigo_tarifa_iva: f.codigo_tarifa_iva.value, es_servicio: esServicio.checked,
      controla_inventario: controla.checked,
      costo_unitario: f.costo_unitario.value || null, existencia_minima: f.existencia_minima.value || null,
    };
    if (nuevo && controla.checked) cuerpo.existencia_inicial = f.existencia_inicial.value || '0';
    const r = nuevo
      ? await api('/catalogo/productos', { method: 'POST', body: cuerpo })
      : await api(`/catalogo/productos/${p.id}`, { method: 'PATCH', body: cuerpo });
    m.cerrar();
    toast(nuevo ? 'Producto guardado' : 'Producto actualizado', 'ok');
    alGuardar(r);
  }) }, 'Guardar');

  const m = modal(nuevo ? 'Nuevo producto o servicio' : `Producto: ${p.descripcion}`, [
    h('div', { class: 'campos' },
      campo('Código', f.codigo),
      h('div', { class: 'fila doble' }, campo('CABYS', f.codigo_cabys), buscarCabys),
      campo('Descripción', f.descripcion), campo('Unidad de medida', f.unidad_medida),
      campo('Precio unitario sin IVA (₡)', f.precio_unitario), campo('IVA', f.codigo_tarifa_iva),
      h('label', { class: 'check' }, esServicio, 'Es un servicio'),
      h('label', { class: 'check' }, controla, 'Controlar inventario (descontar existencias al vender)')),
    bloqueInventario,
    nuevo ? null : h('p', { class: 'suave' }, 'La existencia se cambia con "Movimiento" (entrada, salida o ajuste por conteo).'),
  ], { acciones: [guardar], ancho: true });
}

export function dialogoMovimiento(p, alGuardar) {
  const tipo = h('select', {},
    h('option', { value: 'entrada' }, 'Entrada (compra, producción)'),
    h('option', { value: 'salida' }, 'Salida (merma, uso interno, regalía)'),
    h('option', { value: 'ajuste' }, 'Ajuste por conteo físico'));
  const cantidadInput = h('input', { type: 'number', step: '0.001', min: '0' });
  const costo = h('input', { type: 'number', step: '0.01', min: '0', placeholder: 'Opcional: actualiza el costo promedio' });
  const nota = h('input', { type: 'text', maxlength: '300', placeholder: 'Ej.: Factura 123 de Proveedor X' });
  const etiqueta = h('span', {}, 'Cantidad que entra');
  const campoCosto = campo('Costo unitario (sin IVA)', costo);
  const actualizar = () => {
    etiqueta.textContent = { entrada: 'Cantidad que entra', salida: 'Cantidad que sale', ajuste: 'Existencia contada' }[tipo.value];
    campoCosto.classList.toggle('oculto', tipo.value !== 'entrada');
  };
  tipo.addEventListener('change', actualizar);
  actualizar();

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = { producto_id: p.id, tipo: tipo.value, cantidad: cantidadInput.value || '0', nota: nota.value.trim() || null };
    if (tipo.value === 'entrada' && costo.value) cuerpo.costo_unitario = costo.value;
    const r = await api('/inventario/movimientos', { method: 'POST', body: cuerpo });
    m.cerrar();
    toast(`Existencia de ${p.descripcion}: ${cantidad(r.existencia_resultante)}`, 'ok');
    alGuardar();
  }) }, 'Registrar');

  const m = modal(`Movimiento: ${p.descripcion}`, [
    h('p', {}, 'Existencia actual: ', h('strong', {}, `${cantidad(p.existencia)} ${p.unidad_medida}`)),
    h('div', { class: 'campos' }, campo('Tipo', tipo), h('label', {}, etiqueta, cantidadInput), campoCosto, campo('Nota', nota)),
  ], { acciones: [guardar] });
}

export async function dialogoKardex(p) {
  const movs = await api(`/inventario/movimientos?producto_id=${p.id}&limite=500`);
  modal(`Kárdex: ${p.codigo} · ${p.descripcion}`, [tablaMovimientos(movs, false)], { ancho: true });
}

export function tablaMovimientos(movs, conProducto = true) {
  return tabla([
    { titulo: 'Fecha', valor: (m) => fecha(m.fecha) },
    conProducto ? { titulo: 'Producto', valor: (m) => [m.producto_descripcion, h('div', { class: 'suave' }, m.producto_codigo)] } : null,
    { titulo: 'Movimiento', valor: (m) => TIPOS_MOVIMIENTO[m.tipo] || m.tipo },
    { titulo: 'Cantidad', num: true, valor: (m) => h('span', { class: Number(m.cantidad) < 0 ? 'negativo' : '' },
      `${Number(m.cantidad) > 0 ? '+' : ''}${cantidad(m.cantidad)}`) },
    { titulo: 'Existencia', num: true, valor: (m) => cantidad(m.existencia_resultante) },
    { titulo: 'Detalle', valor: (m) => [m.nota || '', m.factura_id ? h('div', {}, h('a', { href: `#/comprobantes/${m.factura_id}` }, 'Ver comprobante')) : null] },
    { titulo: 'Usuario', valor: (m) => m.usuario || '' },
  ].filter(Boolean), movs);
}

export async function vistaProductos(cont, estado = { q: '', filtro: '' }) {
  const q = h('input', { type: 'search', placeholder: 'Código, descripción o CABYS', value: estado.q });
  const filtro = h('select', { 'aria-label': 'Filtro' },
    [['', 'Todos'], ['solo_inventario', 'Con inventario'], ['bajo_minimo', 'Bajo el mínimo']]
      .map(([v, t]) => h('option', { value: v, selected: v === estado.filtro }, t)));
  const params = new URLSearchParams();
  if (estado.q) params.set('q', estado.q);
  if (estado.filtro) params.set(estado.filtro, 'true');
  const lista = await api(`/catalogo/productos?${params}`);
  const refrescar = () => vistaProductos(cont, { q: q.value.trim(), filtro: filtro.value }).catch((e) => toast(e.message, 'error'));
  filtro.addEventListener('change', refrescar);

  const acciones = (p) => h('div', { class: 'acciones' },
    p.controla_inventario ? h('button', { type: 'button', class: 'chico', onclick: (ev) => { ev.stopPropagation(); dialogoMovimiento(p, refrescar); } }, 'Movimiento') : null,
    p.controla_inventario ? h('button', { type: 'button', class: 'chico', onclick: (ev) => { ev.stopPropagation(); dialogoKardex(p).catch((e) => toast(e.message, 'error')); } }, 'Kárdex') : null,
    h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => {
      ev.stopPropagation();
      conBoton(ev.target, async () => {
        if (!window.confirm(`¿Quitar "${p.descripcion}" del catálogo? Su historial se conserva.`)) return;
        await api(`/catalogo/productos/${p.id}`, { method: 'DELETE' });
        refrescar();
      });
    } }, 'Quitar'));

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Productos y servicios'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoProducto(null, refrescar) }, '+ Nuevo producto')),
    h('form', { class: 'fila', onsubmit: (e) => { e.preventDefault(); refrescar(); } }, q, filtro,
      h('button', { type: 'submit' }, 'Buscar')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Código', valor: (p) => h('span', { class: 'mono' }, p.codigo) },
      { titulo: 'Descripción', valor: (p) => [p.descripcion, h('div', { class: 'suave mono' }, `CABYS ${p.codigo_cabys}`)] },
      { titulo: 'Precio sin IVA', num: true, valor: (p) => dinero(p.precio_unitario, 'CRC') },
      { titulo: 'IVA', valor: (p) => `${TARIFAS_IVA[p.codigo_tarifa_iva]?.[1] ?? ''}%` },
      { titulo: 'Existencia', valor: existenciaBadge },
      { titulo: '', valor: acciones },
    ], lista, (p) => dialogoProducto(p, refrescar))),
    h('p', { class: 'suave' }, 'Toque un producto para editarlo. Al facturar, use "+ Del catálogo" para agregarlo con un clic.'));
}
