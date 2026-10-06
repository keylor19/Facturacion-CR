import { api, descargar } from '../api.js';
import { h, vaciar, tabla, conBoton, toast, dinero, aviso } from '../dom.js';
import { cantidad, dialogoMovimiento, existenciaBadge, tablaMovimientos } from './productos.js';

export async function vistaInventario(cont) {
  const [resumen, movs] = await Promise.all([
    api('/inventario/resumen'),
    api('/inventario/movimientos?limite=100'),
  ]);
  const refrescar = () => vistaInventario(cont).catch((e) => toast(e.message, 'error'));
  const exportar = h('button', { type: 'button', onclick: () => conBoton(exportar, () => descargar('/inventario/existencias.csv', 'existencias.csv')) },
    'Descargar existencias (CSV)');

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Inventario'),
      h('div', { class: 'acciones' }, h('a', { href: '#/productos', class: 'boton' }, 'Productos'), exportar)),
    h('div', { class: 'kpis' },
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Productos con inventario'),
        h('div', { class: 'valor' }, String(resumen.productos_con_inventario))),
      h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Valor al costo'),
        h('div', { class: 'valor' }, dinero(resumen.valor_al_costo, 'CRC'))),
      h('div', { class: `kpi ${resumen.bajo_minimo.length ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, 'Bajo el mínimo'),
        h('div', { class: 'valor' }, String(resumen.bajo_minimo.length)))),
    resumen.bajo_minimo.length ? h('section', { class: 'tarjeta' }, h('h2', {}, 'Por reabastecer'),
      tabla([
        { titulo: 'Código', valor: (p) => h('span', { class: 'mono' }, p.codigo) },
        { titulo: 'Descripción', valor: (p) => p.descripcion },
        { titulo: 'Existencia', valor: existenciaBadge },
        { titulo: 'Mínimo', num: true, valor: (p) => cantidad(p.existencia_minima) },
        { titulo: '', valor: (p) => h('button', { type: 'button', class: 'chico', onclick: () => dialogoMovimiento(p, refrescar) }, 'Registrar entrada') },
      ], resumen.bajo_minimo)) : null,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Últimos movimientos'),
      movs.length ? tablaMovimientos(movs)
        : aviso('Aún no hay movimientos. Cree productos con "Controlar inventario" y las ventas los descontarán solas.', 'info')));
}
