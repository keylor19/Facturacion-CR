// Factura rápida: venta de contado desde el catálogo en una sola pantalla.
// Sin cliente se emite tiquete; al elegir un cliente se emite factura electrónica.
// El punto de venta usa la misma pantalla (crearVenta) enviando a su caja.
import { api } from '../api.js';
import { h, vaciar, dinero, conBoton, toast, campo, opciones, aviso } from '../dom.js';
import { MEDIOS_PAGO, TARIFAS_IVA } from '../catalogos.js';
import { dialogoElegirCliente } from './emitir.js';
import { descuentosVigentes, mejorDescuento } from '../promociones.js';

const conIva = (p) => Number(p.precio_unitario) * (1 + (TARIFAS_IVA[p.codigo_tarifa_iva]?.[1] || 0) / 100);

// enviar(datos) emite y devuelve la respuesta de la API; alEmitir(r) se llama después.
export function crearVenta({ enviar = (datos) => api('/facturas', { method: 'POST', body: datos }), alEmitir = () => {} } = {}) {
  const lineas = [];
  let cliente = null;

  const q = h('input', { type: 'search', placeholder: 'Escriba o escanee el código, la descripción o el CABYS', autocomplete: 'off' });
  const sugerencias = h('div', { class: 'sugerencias' });
  const cuerpo = h('tbody');
  const totales = h('tbody');
  const medio = h('select', {}, opciones(MEDIOS_PAGO, '01'));
  const recibido = h('input', { type: 'number', step: '0.01', min: '0', placeholder: 'Opcional' });
  const vuelto = h('strong');
  const datosCliente = h('div');
  const resultado = h('div');
  const emitir = h('button', { type: 'button', class: 'primario grande' }, 'Emitir');

  // Descuentos automáticos vigentes (se cargan en segundo plano)
  let descuentos = [];
  descuentosVigentes().then((lista) => { descuentos = lista; pintar(); });
  const descuentoDe = (l) => mejorDescuento(descuentos, l.p, l.cantidad);
  const subtotalDe = (l) => l.cantidad * Number(l.p.precio_unitario) - (descuentoDe(l)?.monto || 0);

  const calculo = () => lineas.reduce((s, l) => {
    const sub = subtotalDe(l);
    const iva = sub * (TARIFAS_IVA[l.p.codigo_tarifa_iva]?.[1] || 0) / 100;
    return { subtotal: s.subtotal + sub, iva: s.iva + iva };
  }, { subtotal: 0, iva: 0 });

  function pintar() {
    vaciar(cuerpo, lineas.length ? lineas.map((l, i) => {
      const cant = h('input', { type: 'number', step: '0.001', min: '0.001', value: String(l.cantidad), 'aria-label': 'Cantidad' });
      cant.addEventListener('change', () => {
        l.cantidad = Number(cant.value) > 0 ? Number(cant.value) : 1;
        pintar();
      });
      const sub = subtotalDe(l);
      const promo = descuentoDe(l);
      const tarifa = TARIFAS_IVA[l.p.codigo_tarifa_iva]?.[1] || 0;
      return h('tr', {},
        h('td', {}, l.p.descripcion, h('div', { class: 'suave mono' }, l.p.codigo),
          promo ? h('div', { class: 'badge ACEPTADO' }, `${promo.nombre}: −${dinero(promo.monto)}`) : null),
        h('td', { class: 'cant' }, cant),
        h('td', { class: 'num' }, dinero(l.p.precio_unitario)),
        h('td', { class: 'num' }, `${tarifa}%`),
        h('td', { class: 'num' }, dinero(sub * (1 + tarifa / 100))),
        h('td', {}, h('button', { type: 'button', class: 'chico peligro', 'aria-label': 'Quitar', onclick: () => { lineas.splice(i, 1); pintar(); } }, '✕')));
    }) : h('tr', {}, h('td', { colspan: '6', class: 'suave' }, 'Agregue productos con el buscador.')));
    const { subtotal, iva } = calculo();
    const total = subtotal + iva;
    vaciar(totales,
      h('tr', {}, h('td', {}, 'Subtotal'), h('td', { class: 'num' }, dinero(subtotal))),
      h('tr', {}, h('td', {}, 'IVA'), h('td', { class: 'num' }, dinero(iva))),
      h('tr', { class: 'total' }, h('td', {}, 'Total'), h('td', { class: 'num' }, dinero(total))));
    const pago = Number(recibido.value || 0);
    vuelto.textContent = pago > total ? dinero(pago - total) : dinero(0);
    emitir.textContent = `Emitir ${cliente ? 'factura' : 'tiquete'} · ${dinero(total)}`;
    emitir.disabled = !lineas.length;
  }

  function agregar(p) {
    const existente = lineas.find((l) => l.p.id === p.id);
    if (existente) existente.cantidad += 1; else lineas.push({ p, cantidad: 1 });
    q.value = '';
    vaciar(sugerencias);
    pintar();
    q.focus();
  }

  let espera;
  let ultimaBusqueda = 0;
  async function buscar(enter = false) {
    const texto = q.value.trim();
    if (!texto) { vaciar(sugerencias); return; }
    const n = ++ultimaBusqueda;
    const lista = await api(`/catalogo/productos?limite=8&q=${encodeURIComponent(texto)}`);
    if (n !== ultimaBusqueda) return;
    // Lector de código de barras: Enter con un código exacto lo agrega directo
    const exacto = lista.find((p) => p.codigo.toLowerCase() === texto.toLowerCase());
    if (enter && (exacto || lista.length === 1)) { agregar(exacto || lista[0]); return; }
    listarSugerencias(lista);
  }
  // Botones por categoría para buscar sin escribir (útil en pantallas táctiles)
  const categorias = h('div', { class: 'acciones categorias' });
  const listarSugerencias = (lista) => vaciar(sugerencias, lista.length
    ? lista.map((p) => h('button', { type: 'button', class: 'sugerencia', onclick: () => agregar(p) },
      h('span', {}, p.descripcion, h('span', { class: 'suave mono' }, ` · ${p.codigo}`)),
      h('strong', {}, dinero(conIva(p)))))
    : h('p', { class: 'suave' }, 'Sin coincidencias en el catálogo. ', h('a', { href: '#/productos' }, 'Registrar producto')));
  api('/catalogo/categorias').then((lista) => vaciar(categorias, lista.filter((c) => c.productos).map((c) => h('button', {
    type: 'button', class: 'chico', onclick: () => api(`/catalogo/productos?limite=60&categoria_id=${c.id}`).then(listarSugerencias).catch(err),
  }, c.nombre)))).catch(() => {});

  q.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(() => buscar().catch(err), 250); });
  q.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(espera); buscar(true).catch(err); }
  });
  recibido.addEventListener('input', pintar);

  function pintarCliente() {
    vaciar(datosCliente, cliente
      ? [h('p', {}, h('strong', {}, cliente.nombre), h('br'), h('span', { class: 'mono' }, cliente.numero_identificacion),
        cliente.correo ? [h('br'), h('span', { class: 'suave' }, cliente.correo)] : null),
      h('button', { type: 'button', class: 'chico', onclick: () => { cliente = null; pintarCliente(); } }, 'Quitar cliente (emitir tiquete)')]
      : [h('p', { class: 'suave' }, 'Consumidor final: se emite tiquete electrónico.'),
        h('button', { type: 'button', onclick: () => dialogoElegirCliente((c) => { cliente = c; pintarCliente(); }) }, 'Elegir de mis clientes (factura)')]);
    pintar();
  }

  emitir.addEventListener('click', () => conBoton(emitir, async () => {
    vaciar(resultado);
    const datos = {
      tipo_documento: cliente ? '01' : '04', condicion_venta: '01', moneda: 'CRC',
      medios_pago: [{ tipo: medio.value }],
      productos: lineas.map((l) => {
        const { p, cantidad } = l;
        const linea = {
          producto_id: p.id, codigo_comercial: p.codigo, codigo_cabys: p.codigo_cabys, descripcion: p.descripcion,
          cantidad: String(cantidad), unidad_medida: p.unidad_medida, precio_unitario: String(p.precio_unitario),
          codigo_tarifa_iva: p.codigo_tarifa_iva,
        };
        const promo = descuentoDe(l);
        if (promo) Object.assign(linea, { descuento: String(promo.monto), codigo_descuento: promo.codigo });
        return linea;
      }),
    };
    if (cliente) {
      datos.receptor = { nombre: cliente.nombre, tipo_identificacion: cliente.tipo_identificacion, numero_identificacion: cliente.numero_identificacion };
      if (cliente.correo) datos.receptor.correo = cliente.correo;
      if (cliente.codigo_actividad) datos.codigo_actividad_receptor = cliente.codigo_actividad;
    }
    try {
      const r = await enviar(datos);
      toast(r.message, 'ok');
      lineas.length = 0;
      cliente = null;
      recibido.value = '';
      medio.value = '01';
      pintarCliente();
      vaciar(resultado, h('div', { class: 'aviso ok' }, 'Comprobante emitido. ',
        h('a', { href: `#/comprobantes/${r.factura_id}` }, 'Ver comprobante e imprimir PDF')));
      q.focus();
      alEmitir(r);
    } catch (e) {
      vaciar(resultado, aviso(e.message, 'error'));
    }
  }));

  pintarCliente();
  const nodo = h('div', { class: 'venta-rapida' },
    h('div', {},
      h('section', { class: 'tarjeta' }, campo('Buscar producto', q), categorias, sugerencias),
      h('section', { class: 'tarjeta' }, h('div', { class: 'tabla' }, h('table', {},
        h('thead', {}, h('tr', {}, ['Producto', 'Cantidad', 'Precio sin IVA', 'IVA', 'Total', ''].map((t, i) => h('th', { class: i >= 2 && i <= 4 ? 'num' : '' }, t)))),
        cuerpo)))),
    h('aside', {},
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Cliente'), datosCliente),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Pago'),
        campo('Medio de pago', medio), campo('Monto recibido (₡)', recibido),
        h('p', {}, 'Vuelto: ', vuelto),
        h('table', { class: 'totales' }, totales),
        resultado,
        emitir)));
  return { nodo, enfocar: () => q.focus() };
}

export async function vistaFacturaRapida(cont) {
  const venta = crearVenta();
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Factura rápida'),
      h('div', { class: 'acciones' },
        h('a', { href: '#/punto-venta', class: 'boton' }, 'Punto de venta'),
        h('a', { href: '#/emitir/01', class: 'boton' }, 'Formulario completo'))),
    venta.nodo);
  venta.enfocar();
}

function err(e) { toast(e.message, 'error'); }
