import { api, descargar } from '../api.js';
import { h, vaciar, dinero, mesActual, selectorMes, tabla, conBoton, aviso } from '../dom.js';
import { TARIFAS_IVA, CONDICIONES_IMPUESTO } from '../catalogos.js';
import { empresaActual } from '../app.js';

export async function vistaReportes(cont) {
  let periodo = mesActual();
  const cuerpo = h('div');

  async function cargar() {
    vaciar(cuerpo, h('p', { class: 'cargando' }, 'Cargando…'));
    const r = await api(`/reportes/resumen-iva?anio=${periodo.anio}&mes=${periodo.mes}`);
    const sufijo = `${empresaActual()?.numero_identificacion || ''}-${periodo.anio}${String(periodo.mes).padStart(2, '0')}`;
    const q = `anio=${periodo.anio}&mes=${periodo.mes}`;
    const bVentas = h('button', { type: 'button', onclick: () => conBoton(bVentas, () => descargar(`/reportes/ventas.csv?${q}`, `ventas-${sufijo}.csv`)) }, 'Libro de ventas (Excel)');
    const bCompras = h('button', { type: 'button', onclick: () => conBoton(bCompras, () => descargar(`/reportes/compras.csv?${q}`, `compras-${sufijo}.csv`)) }, 'Libro de compras (Excel)');

    const v = r.ventas;
    vaciar(cuerpo,
      h('div', { class: 'acciones' }, bVentas, bCompras),
      h('div', { class: 'kpis' },
        kpi('IVA débito fiscal (ventas)', dinero(r.iva_debito_fiscal)),
        kpi('IVA crédito fiscal (compras)', dinero(r.iva_credito_fiscal)),
        kpi('IVA neto estimado', dinero(r.iva_neto_estimado))),
      aviso(r.advertencia, 'info'),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Ventas'),
        h('div', { class: 'campos' },
          dato('Venta neta', v.venta_neta), dato('Gravado', v.gravado), dato('Exento', v.exento),
          dato('Exonerado', v.exonerado), dato('Otros cargos', v.otros_cargos), dato('Total', v.total)),
        h('h3', {}, 'Por tarifa de IVA'),
        tabla([
          { titulo: 'Tarifa', valor: (x) => TARIFAS_IVA[x.codigo_tarifa_iva]?.[0] || 'Sin IVA' },
          { titulo: 'Base', num: true, valor: (x) => dinero(x.base) },
          { titulo: 'IVA', num: true, valor: (x) => dinero(x.iva) },
          { titulo: 'Exonerado', num: true, valor: (x) => dinero(x.exonerado) },
        ], v.por_tarifa),
        h('h3', {}, 'Documentos'),
        tabla([{ titulo: 'Tipo', valor: (x) => x[0] }, { titulo: 'Cantidad', num: true, valor: (x) => x[1] }],
          Object.entries(v.documentos || {}))),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Compras (facturas de proveedores aceptadas)'),
        tabla([
          { titulo: 'Condición del IVA', valor: (x) => CONDICIONES_IMPUESTO[x.condicion_impuesto] || x.condicion_impuesto },
          { titulo: 'Documentos', num: true, valor: (x) => x.documentos },
          { titulo: 'Total', num: true, valor: (x) => dinero(x.total) },
          { titulo: 'IVA', num: true, valor: (x) => dinero(x.iva) },
          { titulo: 'IVA acreditable', num: true, valor: (x) => dinero(x.iva_acreditable) },
          { titulo: 'Gasto aplicable', num: true, valor: (x) => dinero(x.gasto_aplicable) },
        ], r.compras.por_condicion_impuesto),
        h('p', { class: 'suave' },
          `Facturas de compra emitidas: ${r.compras.facturas_compra_emitidas.documentos} · total ${dinero(r.compras.facturas_compra_emitidas.total)} · IVA ${dinero(r.compras.facturas_compra_emitidas.iva)}`)),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Recibos electrónicos de pago'),
        h('p', { class: 'suave' }, r.recibos_pago.nota),
        tabla([
          { titulo: 'Tarifa', valor: (x) => TARIFAS_IVA[x.codigo_tarifa_iva]?.[0] || 'Sin IVA' },
          { titulo: 'Base', num: true, valor: (x) => dinero(x.base) },
          { titulo: 'IVA', num: true, valor: (x) => dinero(x.iva) },
        ], r.recibos_pago.por_tarifa)));
  }

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Reportes de IVA'),
      selectorMes(periodo, (p) => { periodo = p; cargar().catch(() => {}); })),
    cuerpo);
  await cargar();
}

function kpi(etiqueta, valor) {
  return h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, etiqueta), h('div', { class: 'valor' }, valor));
}

function dato(etiqueta, valor) {
  return h('div', {}, h('div', { class: 'suave' }, etiqueta), h('strong', {}, dinero(valor)));
}
