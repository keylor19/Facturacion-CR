// Productos y servicios de la empresa: precios, CABYS, impuestos, categorías, combos, inventario e importación CSV.
import { api } from '../api.js';
import { h, vaciar, tabla, modal, conBoton, toast, campo, dinero, fecha } from '../dom.js';
import { TARIFAS_IVA, UNIDADES } from '../catalogos.js';
import { dialogoCabys, dialogoElegirProducto } from './emitir.js';
import { descargarCsv, numeroCsv, pantallaCarga, siNo } from '../csv.js';

const TARIFA_POR_PORCENTAJE = { 13: '08', 8: '07', 4: '04', 2: '03', 1: '02', 0.5: '09' };
const TIPOS_MOVIMIENTO = {
  venta: 'Venta', devolucion: 'Devolución', compra: 'Compra', reverso: 'Reverso (rechazo)',
  entrada: 'Entrada', salida: 'Salida', ajuste: 'Ajuste',
};
export const cantidad = (v) => (v === null || v === undefined ? '' : Number(v).toLocaleString('es-CR', { maximumFractionDigits: 3 }));

export function existenciaBadge(p) {
  if (p.es_combo) {
    return h('span', { class: `badge ${p.combo_disponible !== null && Number(p.combo_disponible) <= 0 ? 'RECHAZADO' : 'prod'}` },
      p.combo_disponible === null ? 'Combo' : `Combo · alcanzan ${cantidad(p.combo_disponible)}`);
  }
  if (!p.controla_inventario) return h('span', { class: 'suave' }, 'No controla');
  return h('span', { class: `badge ${p.bajo_minimo ? 'RECHAZADO' : 'ACEPTADO'}`, title: p.bajo_minimo ? 'En o por debajo del mínimo' : '' },
    `${cantidad(p.existencia)} ${p.unidad_medida}`);
}

export const categoriasEmpresa = () => api('/catalogo/categorias').catch(() => []);

// Componentes de un combo: lista editable de productos y cantidades
function editorComponentes(iniciales) {
  const componentes = (iniciales || []).map((c) => ({ ...c, cantidad: Number(c.cantidad) }));
  const tablaComp = h('div');
  const pintar = () => vaciar(tablaComp, componentes.length ? h('table', {}, h('tbody', {}, componentes.map((c, i) => {
    const cant = h('input', { type: 'number', step: '0.001', min: '0.001', value: String(c.cantidad), 'aria-label': 'Cantidad' });
    cant.addEventListener('change', () => { c.cantidad = Number(cant.value) > 0 ? Number(cant.value) : 1; });
    return h('tr', {},
      h('td', {}, c.descripcion, h('div', { class: 'suave mono' }, c.codigo)),
      h('td', { class: 'cant' }, cant),
      h('td', {}, h('button', { type: 'button', class: 'chico peligro', 'aria-label': 'Quitar', onclick: () => { componentes.splice(i, 1); pintar(); } }, '✕')));
  }))) : h('p', { class: 'suave' }, 'Agregue los productos que lleva el combo.'));
  const agregar = h('button', { type: 'button', onclick: () => dialogoElegirProducto((x) => {
    if (x.es_combo) { toast('Un combo no puede contener otro combo', 'error'); return; }
    const existente = componentes.find((c) => c.producto_id === x.id);
    if (existente) existente.cantidad += 1;
    else componentes.push({ producto_id: x.id, codigo: x.codigo, descripcion: x.descripcion, cantidad: 1 });
    pintar();
  }) }, '+ Agregar producto');
  pintar();
  return {
    nodo: h('div', {}, tablaComp, agregar),
    valor: () => componentes.map((c) => ({ producto_id: c.producto_id, cantidad: String(c.cantidad) })),
  };
}

export async function dialogoProducto(producto, alGuardar, { combo = false } = {}) {
  const p = producto || {};
  const nuevo = !p.id;
  const categorias = await categoriasEmpresa();
  const f = {
    codigo: h('input', { type: 'text', maxlength: '20', value: p.codigo || '', placeholder: 'Código interno, p. ej. MART-01' }),
    codigo_cabys: h('input', { type: 'text', maxlength: '13', value: p.codigo_cabys || '', placeholder: '13 dígitos' }),
    descripcion: h('input', { type: 'text', maxlength: '200', value: p.descripcion || '' }),
    unidad_medida: h('select', {}, Object.entries(UNIDADES).map(([k, v]) => h('option', { value: k, selected: k === (p.unidad_medida || 'Unid') }, `${k} · ${v}`))),
    precio_unitario: h('input', { type: 'number', step: '0.01', min: '0', value: p.precio_unitario ?? '' }),
    codigo_tarifa_iva: h('select', {}, Object.entries(TARIFAS_IVA).map(([k, [t]]) => h('option', { value: k, selected: k === (p.codigo_tarifa_iva || '08') }, t))),
    categoria_id: h('select', {}, h('option', { value: '' }, 'Sin categoría'),
      categorias.map((c) => h('option', { value: c.id, selected: c.id === p.categoria_id }, c.nombre))),
    costo_unitario: h('input', { type: 'number', step: '0.01', min: '0', value: p.costo_unitario ?? '', placeholder: 'Opcional' }),
    existencia_minima: h('input', { type: 'number', step: '0.001', min: '0', value: p.existencia_minima ?? '', placeholder: 'Avisar al llegar a…' }),
    existencia_inicial: h('input', { type: 'number', step: '0.001', min: '0', value: '0' }),
  };
  const esServicio = h('input', { type: 'checkbox', checked: !!p.es_servicio });
  const esCombo = h('input', { type: 'checkbox', checked: combo || !!p.es_combo });
  const controla = h('input', { type: 'checkbox', checked: nuevo ? !esCombo.checked : !!p.controla_inventario });
  const editor = editorComponentes(p.componentes);
  const bloqueCombo = h('div', {}, h('h3', {}, 'Contenido del combo'),
    h('p', { class: 'suave' }, 'Se factura como una sola línea con el precio del combo; al venderlo se descuentan las existencias de cada producto.'),
    editor.nodo);
  const bloqueInventario = h('div', { class: 'campos' },
    nuevo ? campo('Existencia inicial', f.existencia_inicial) : null,
    campo('Existencia mínima', f.existencia_minima), campo('Costo unitario (sin IVA)', f.costo_unitario));
  const actualizar = () => {
    if (esServicio.checked || esCombo.checked) controla.checked = false;
    controla.disabled = esServicio.checked || esCombo.checked;
    bloqueInventario.classList.toggle('oculto', !controla.checked);
    bloqueCombo.classList.toggle('oculto', !esCombo.checked);
  };
  [esServicio, esCombo, controla].forEach((el) => el.addEventListener('change', actualizar));
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
      controla_inventario: controla.checked, categoria_id: f.categoria_id.value,
      costo_unitario: f.costo_unitario.value || null, existencia_minima: f.existencia_minima.value || null,
    };
    if (esCombo.checked) {
      cuerpo.componentes = editor.valor();
      if (!cuerpo.componentes.length) { toast('Agregue al menos un producto al combo', 'error'); return; }
    } else if (p.es_combo) {
      cuerpo.componentes = [];
    }
    if (nuevo && controla.checked) cuerpo.existencia_inicial = f.existencia_inicial.value || '0';
    const r = nuevo
      ? await api('/catalogo/productos', { method: 'POST', body: cuerpo })
      : await api(`/catalogo/productos/${p.id}`, { method: 'PATCH', body: cuerpo });
    m.cerrar();
    toast(nuevo ? 'Producto guardado' : 'Producto actualizado', 'ok');
    alGuardar(r);
  }) }, 'Guardar');

  const m = modal(nuevo ? (combo ? 'Nuevo combo' : 'Nuevo producto o servicio') : `Producto: ${p.descripcion}`, [
    h('div', { class: 'campos' },
      campo('Código', f.codigo),
      h('div', { class: 'fila doble' }, campo('CABYS', f.codigo_cabys), buscarCabys),
      campo('Descripción', f.descripcion), campo('Unidad de medida', f.unidad_medida),
      campo('Precio unitario sin IVA (₡)', f.precio_unitario), campo('IVA', f.codigo_tarifa_iva),
      campo('Categoría', f.categoria_id),
      h('label', { class: 'check' }, esServicio, 'Es un servicio'),
      h('label', { class: 'check' }, esCombo, 'Es un combo (varios productos a un precio)'),
      h('label', { class: 'check' }, controla, 'Controlar inventario (descontar existencias al vender)')),
    bloqueCombo,
    bloqueInventario,
    nuevo || p.es_combo ? null : h('p', { class: 'suave' }, 'La existencia se cambia con "Movimiento" (entrada, salida o ajuste por conteo).'),
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

export async function vistaProductos(cont, estado = { q: '', filtro: '', categoria: '' }) {
  const combos = estado.filtro === 'solo_combos';
  const q = h('input', { type: 'search', placeholder: 'Código, descripción o CABYS', value: estado.q });
  const filtro = h('select', { 'aria-label': 'Filtro' },
    [['', 'Todos'], ['solo_inventario', 'Con inventario'], ['bajo_minimo', 'Bajo el mínimo'], ['solo_combos', 'Combos']]
      .map(([v, t]) => h('option', { value: v, selected: v === estado.filtro }, t)));
  const params = new URLSearchParams();
  if (estado.q) params.set('q', estado.q);
  if (estado.filtro) params.set(estado.filtro, 'true');
  if (estado.categoria) params.set('categoria_id', estado.categoria);
  const [lista, categorias] = await Promise.all([api(`/catalogo/productos?${params}`), categoriasEmpresa()]);
  const categoria = h('select', { 'aria-label': 'Categoría' }, h('option', { value: '' }, 'Todas las categorías'),
    categorias.map((c) => h('option', { value: c.id, selected: c.id === estado.categoria }, c.nombre)));
  const refrescar = () => vistaProductos(cont, { q: q.value.trim(), filtro: filtro.value, categoria: categoria.value })
    .catch((e) => toast(e.message, 'error'));
  filtro.addEventListener('change', refrescar);
  categoria.addEventListener('change', refrescar);

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
    h('div', { class: 'encabezado' }, h('h1', {}, combos ? 'Combos' : 'Productos y servicios'),
      h('div', { class: 'acciones' },
        combos ? null : h('a', { href: '#/productos/cargar', class: 'boton' }, 'Cargar desde Excel'),
        combos ? null : h('a', { href: '#/productos/reporte', class: 'boton' }, 'Reporte'),
        h('button', { type: 'button', class: combos ? 'primario' : '', onclick: () => dialogoProducto(null, refrescar, { combo: true }) }, '+ Nuevo combo'),
        combos ? null : h('button', { type: 'button', class: 'primario', onclick: () => dialogoProducto(null, refrescar) }, '+ Nuevo producto'))),
    h('form', { class: 'fila', onsubmit: (e) => { e.preventDefault(); refrescar(); } }, q, categoria, filtro,
      h('button', { type: 'submit' }, 'Buscar')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Código', valor: (p) => h('span', { class: 'mono' }, p.codigo) },
      { titulo: 'Descripción', valor: (p) => [p.descripcion, h('div', { class: 'suave mono' }, `CABYS ${p.codigo_cabys}`),
        p.es_combo ? h('div', { class: 'suave' }, p.componentes.map((c) => `${cantidad(c.cantidad)} × ${c.descripcion}`).join(' + ')) : null] },
      { titulo: 'Categoría', valor: (p) => p.categoria || '' },
      { titulo: 'Precio sin IVA', num: true, valor: (p) => dinero(p.precio_unitario, 'CRC') },
      { titulo: 'IVA', valor: (p) => `${TARIFAS_IVA[p.codigo_tarifa_iva]?.[1] ?? ''}%` },
      { titulo: 'Existencia', valor: existenciaBadge },
      { titulo: '', valor: acciones },
    ], lista, (p) => dialogoProducto(p, refrescar))),
    h('p', { class: 'suave' }, 'Toque un producto para editarlo. Al facturar, use «+ Agregar de mis productos» para agregarlo con un clic.'));
}

export const vistaCombos = (cont) => vistaProductos(cont, { q: '', filtro: 'solo_combos', categoria: '' });

const COLUMNAS_CSV = ['codigo', 'codigo_cabys', 'descripcion', 'unidad_medida', 'precio_sin_iva', 'iva_porcentaje',
  'es_servicio', 'controla_inventario', 'existencia_inicial', 'existencia_minima', 'costo_unitario', 'categoria'];

export async function vistaCargarProductos(cont) {
  const categorias = Object.fromEntries((await categoriasEmpresa()).map((c) => [c.nombre.toLowerCase(), c.id]));
  vaciar(cont, pantallaCarga({
    titulo: 'Cargar productos',
    volver: h('a', { href: '#/productos' }, '← Productos'),
    descripcion: 'Una fila por producto o servicio. Obligatorios: código interno, CABYS de 13 dígitos y descripción. '
      + 'IVA en porcentaje (13, 4, 2, 1, 0) o "exento". Unidad según Hacienda (Unid, Sp, Kg, L…). '
      + 'Columnas de sí/no: escriba "si" o déjelas vacías. La categoría (opcional) debe existir en Productos → Categorías. '
      + 'Los códigos que ya existen se reportan y no se modifican.',
    plantilla: 'plantilla-productos.csv',
    ejemplo: [COLUMNAS_CSV,
      ['MART-01', '4299990000000', 'Martillo de acero 16 oz', 'Unid', '4500', '13', '', 'si', '25', '5', '3000', ''],
      ['SERV-01', '8314100000100', 'Hora de soporte técnico', 'h', '15000', '13', 'si', '', '', '', '', '']],
    columnas: [
      { titulo: 'Código', valor: (r) => h('span', { class: 'mono' }, r.fila.codigo || '') },
      { titulo: 'Descripción', valor: (r) => r.fila.descripcion || '' },
      { titulo: 'Precio sin IVA', num: true, valor: (r) => r.fila.precio_sin_iva || '' },
      { titulo: 'IVA', valor: (r) => r.fila.iva_porcentaje || '' },
    ],
    convertir(fila) {
      const servicio = siNo(fila.es_servicio);
      const controla = !servicio && siNo(fila.controla_inventario);
      const ivaTexto = String(fila.iva_porcentaje || '13').toLowerCase();
      const tarifa = ivaTexto.startsWith('exent') ? '10' : TARIFA_POR_PORCENTAJE[Number(numeroCsv(ivaTexto))] || (Number(numeroCsv(ivaTexto)) === 0 ? '01' : null);
      const unidad = Object.keys(UNIDADES).find((u) => u.toLowerCase() === (fila.unidad_medida || 'Unid').toLowerCase());
      const cuerpo = {
        codigo: fila.codigo, codigo_cabys: (fila.codigo_cabys || '').replace(/\D/g, ''), descripcion: fila.descripcion,
        unidad_medida: unidad, precio_unitario: numeroCsv(fila.precio_sin_iva) || '0', codigo_tarifa_iva: tarifa,
        es_servicio: servicio, controla_inventario: controla,
        costo_unitario: numeroCsv(fila.costo_unitario) || null, existencia_minima: controla ? numeroCsv(fila.existencia_minima) || null : null,
      };
      if (controla) cuerpo.existencia_inicial = numeroCsv(fila.existencia_inicial) || '0';
      if (fila.categoria) {
        cuerpo.categoria_id = categorias[fila.categoria.toLowerCase()];
        if (!cuerpo.categoria_id) return { error: `La categoría "${fila.categoria}" no existe` };
      }
      if (!cuerpo.codigo) return { error: 'Falta el código' };
      if (!/^\d{13}$/.test(cuerpo.codigo_cabys)) return { error: 'CABYS debe tener 13 dígitos' };
      if (!cuerpo.descripcion) return { error: 'Falta la descripción' };
      if (!unidad) return { error: `Unidad "${fila.unidad_medida}" no reconocida` };
      if (!tarifa) return { error: `IVA "${fila.iva_porcentaje}" no reconocido` };
      return { cuerpo };
    },
    enviar: (cuerpo) => api('/catalogo/productos', { method: 'POST', body: cuerpo }),
  }));
}

export async function vistaReporteProductos(cont) {
  const lista = await api('/catalogo/productos?limite=2000');
  const conInventario = lista.filter((p) => p.controla_inventario);
  const valorInventario = conInventario.reduce((s, p) => s + Number(p.existencia) * Number(p.costo_unitario || 0), 0);
  const bajos = conInventario.filter((p) => p.bajo_minimo).length;
  const exportar = () => descargarCsv('productos.csv',
    ['Código', 'CABYS', 'Descripción', 'Categoría', 'Unidad', 'Precio sin IVA', 'IVA %', 'Servicio', 'Combo', 'Controla inventario', 'Existencia', 'Mínimo', 'Costo unitario'],
    lista.map((p) => [p.codigo, p.codigo_cabys, p.descripcion, p.categoria || '', p.unidad_medida, p.precio_unitario, TARIFAS_IVA[p.codigo_tarifa_iva]?.[1] ?? '',
      p.es_servicio ? 'Sí' : 'No', p.es_combo ? 'Sí' : 'No', p.controla_inventario ? 'Sí' : 'No', p.controla_inventario ? p.existencia : '', p.existencia_minima ?? '', p.costo_unitario ?? '']));
  const kpi = (etiqueta, valor, alerta = false) => h('div', { class: `kpi ${alerta ? 'alerta' : ''}` },
    h('div', { class: 'etiqueta' }, etiqueta), h('div', { class: 'valor' }, valor));
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('div', {}, h('a', { href: '#/productos' }, '← Productos'), h('h1', {}, 'Reporte de productos')),
      h('button', { type: 'button', class: 'primario', onclick: exportar }, 'Descargar (Excel)')),
    h('div', { class: 'kpis' },
      kpi('Productos y servicios', lista.length),
      kpi('Con control de inventario', conInventario.length),
      kpi('Bajo el mínimo', bajos, bajos > 0),
      kpi('Valor del inventario (al costo)', dinero(valorInventario))),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Código', valor: (p) => h('span', { class: 'mono' }, p.codigo) },
      { titulo: 'Descripción', valor: (p) => [p.descripcion, h('div', { class: 'suave mono' }, `CABYS ${p.codigo_cabys}`)] },
      { titulo: 'Categoría', valor: (p) => p.categoria || '' },
      { titulo: 'Precio sin IVA', num: true, valor: (p) => dinero(p.precio_unitario) },
      { titulo: 'IVA', valor: (p) => `${TARIFAS_IVA[p.codigo_tarifa_iva]?.[1] ?? ''}%` },
      { titulo: 'Costo', num: true, valor: (p) => (p.costo_unitario ? dinero(p.costo_unitario) : '') },
      { titulo: 'Existencia', valor: existenciaBadge },
    ], lista)));
}
