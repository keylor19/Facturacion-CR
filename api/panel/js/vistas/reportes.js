// Reporte de IVA del mes (insumo D-104) con libros de ventas y compras, y aviso de las notas por error
// material (códigos 13/14) que obligan a rectificar otro mes.
import { api, descargar } from '../api.js';
import { h, vaciar, dinero, mesActual, selectorMes, tabla, conBoton, aviso, toast } from '../dom.js';
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
      h('p', {}, h('a', { href: '#/d104', class: 'boton primario' }, 'Ver el borrador de la D-104 para TRIBU-CR')),
      aviso(r.advertencia, 'info'),
      seccionErrorMaterial(r.notas_error_material, r.rectificaciones_pendientes),
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

// Notas con código 13 o 14 (error material): su efecto contable va al mes de la factura
// original, así que pueden obligar a rectificar una declaración ya presentada.
function seccionErrorMaterial(notas, rectificar) {
  if (!notas) return null;
  const anteriores = notas.afectan_meses_anteriores;
  const posteriores = notas.emitidas_despues_que_afectan_este_mes;
  if (!anteriores.length && !posteriores.length) return null;
  const columnas = [
    { titulo: 'Emitida', valor: (n) => n.fecha_emision },
    { titulo: 'Documento', valor: (n) => h('a', { href: `#/comprobantes/${n.factura_id}` }, `${n.tipo} ${n.consecutivo}`) },
    { titulo: 'Motivo', valor: (n) => n.motivo },
    { titulo: 'Mes que afecta', valor: (n) => n.periodo_fiscal },
    { titulo: 'IVA', num: true, valor: (n) => dinero(n.iva_crc) },
    { titulo: 'Total', num: true, valor: (n) => dinero(n.total_crc) },
  ];
  return h('section', { class: 'tarjeta' }, h('h2', {}, 'Notas por error material'),
    anteriores.length ? [
      aviso(`Rectifique la declaración de IVA de: ${rectificar.join(', ')}. Estas notas se emitieron este mes, `
        + 'pero por ser error material (código 13 o 14) su ajuste cuenta en el mes de la factura original. '
        + 'No están sumadas en este mes.', 'alerta'),
      tabla(columnas, anteriores)] : null,
    posteriores.length ? [
      aviso('Estas notas se emitieron después de cerrar este mes, pero lo afectan (error material). Ya están sumadas '
        + 'arriba: si la declaración de este mes ya se presentó, hay que rectificarla.', 'alerta'),
      tabla(columnas, posteriores)] : null);
}

// Borrador de la declaración de IVA (D-104) para copiar a TRIBU-CR: cada monto con su botón «Copiar».
export async function vistaD104(cont) {
  let periodo = mesActual();
  const cuerpo = h('div');
  const copiar = (valor) => h('button', { type: 'button', class: 'chico no-imprimir', title: 'Copiar el monto', onclick: async () => {
    try {
      await navigator.clipboard.writeText(String(Number(valor).toFixed(2)));
      toast('Monto copiado', 'ok');
    } catch {
      toast('No se pudo copiar', 'error');
    }
  } }, 'Copiar');
  const monto = (v) => h('span', { class: 'monto-copiable' }, dinero(v), ' ', copiar(v));

  async function cargar() {
    vaciar(cuerpo, h('p', { class: 'cargando' }, 'Cargando…'));
    const q = `anio=${periodo.anio}&mes=${periodo.mes}`;
    const b = await api(`/reportes/d104?${q}`);
    const t = b.totales;
    const bCsv = h('button', { type: 'button', onclick: () => conBoton(bCsv, () => descargar(`/reportes/d104.csv?${q}`, `d104-${b.emisor.identificacion}-${b.periodo}.csv`)) }, 'Descargar (Excel)');
    vaciar(cuerpo,
      h('div', { class: 'acciones no-imprimir' }, bCsv, h('button', { type: 'button', onclick: () => window.print() }, 'Imprimir')),
      h('div', { class: 'kpis' },
        kpi('IVA de ventas (débito)', dinero(t.iva_debito_fiscal)),
        kpi('IVA de compras (crédito)', dinero(t.iva_credito_fiscal)),
        Number(t.saldo_a_favor) > 0 ? kpi('Saldo a favor', dinero(t.saldo_a_favor)) : kpi('Impuesto a pagar', dinero(t.impuesto_a_pagar))),
      b.rectificaciones_pendientes.length
        ? aviso(`Hay notas por error material que corrigen meses anteriores (${b.rectificaciones_pendientes.join(', ')}): esos meses requieren declaración rectificativa.`, 'alerta') : null,
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Ventas (débito fiscal)'),
        tabla([
          { titulo: 'Concepto', valor: (x) => x.concepto },
          { titulo: 'Base', num: true, valor: (x) => monto(x.base) },
          { titulo: 'IVA', num: true, valor: (x) => monto(x.iva) },
        ], b.ventas)),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Compras (crédito fiscal)'),
        tabla([
          { titulo: 'Concepto', valor: (x) => x.concepto },
          { titulo: 'Documentos', num: true, valor: (x) => x.documentos },
          { titulo: 'Total', num: true, valor: (x) => monto(x.total) },
          { titulo: 'IVA acreditable', num: true, valor: (x) => monto(x.iva_acreditable) },
        ], b.compras),
        b.facturas_compra.documentos ? h('p', { class: 'suave' }, `${b.facturas_compra.concepto}: ${b.facturas_compra.documentos} por ${dinero(b.facturas_compra.total)} (IVA ${dinero(b.facturas_compra.iva)}).`) : null),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Resultado'),
        h('dl', { class: 'datos' },
          h('dt', {}, 'IVA débito fiscal'), h('dd', {}, monto(t.iva_debito_fiscal)),
          h('dt', {}, 'IVA crédito fiscal'), h('dd', {}, monto(t.iva_credito_fiscal)),
          h('dt', {}, 'IVA devuelto (salud con tarjeta)'), h('dd', {}, monto(t.iva_devuelto)),
          h('dt', {}, 'Impuesto a pagar'), h('dd', {}, h('strong', {}, monto(t.impuesto_a_pagar))),
          h('dt', {}, 'Saldo a favor'), h('dd', {}, monto(t.saldo_a_favor)))),
      b.advertencias.map((a) => aviso(a, 'info')));
  }

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('div', {}, h('a', { href: '#/reportes', class: 'no-imprimir' }, '← Reporte de IVA'), h('h1', {}, 'Borrador de la D-104')),
      selectorMes(periodo, (p) => { periodo = p; cargar().catch((e) => toast(e.message, 'error')); })),
    h('p', { class: 'suave' }, 'Montos del mes en colones, listos para copiar a la declaración del IVA en TRIBU-CR. Revíselos con su contador.'),
    cuerpo);
  await cargar();
}
