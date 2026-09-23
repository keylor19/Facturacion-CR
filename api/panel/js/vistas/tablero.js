import { api } from '../api.js';
import { h, vaciar, dinero, fecha, badge, mesActual, selectorMes, tabla, TIPOS, ESTADOS } from '../dom.js';
import { contexto, empresaActual } from '../app.js';

export async function vistaTablero(cont) {
  let periodo = mesActual();
  const cuerpo = h('div');

  async function cargar() {
    vaciar(cuerpo, h('p', { class: 'cargando' }, 'Cargando…'));
    const [est, ultimos] = await Promise.all([
      api(`/reportes/estadisticas?anio=${periodo.anio}&mes=${periodo.mes}`),
      api('/facturas?limit=10'),
    ]);
    const emp = empresaActual();
    const avisos = [];
    if (contexto.controlSaldo && emp && emp.saldo_documentos !== null && emp.saldo_documentos !== undefined) {
      if (emp.saldo_documentos <= 0) {
        avisos.push(h('div', { class: 'aviso error' }, 'Saldo de documentos agotado: no se pueden emitir comprobantes. ',
          h('a', { href: '#/saldo' }, 'Ver saldo')));
      } else if (emp.saldo_documentos <= contexto.saldoAlerta) {
        avisos.push(h('div', { class: 'aviso alerta' }, `Quedan ${emp.saldo_documentos} documentos disponibles. `,
          h('a', { href: '#/saldo' }, 'Ver saldo')));
      }
    }
    if (emp && !emp.tiene_certificado) {
      avisos.push(h('div', { class: 'aviso alerta' }, 'Esta empresa no tiene certificado digital cargado; no podrá emitir.'));
    } else if (emp?.cert_vence) {
      const dias = Math.floor((new Date(emp.cert_vence) - new Date()) / 86400000);
      if (dias < 30) avisos.push(h('div', { class: 'aviso alerta' }, `El certificado digital vence en ${dias} días (${fecha(emp.cert_vence, false)}).`));
    }

    const total = Object.values(est.comprobantes_por_estado).reduce((a, b) => a + b, 0);
    vaciar(cuerpo,
      avisos,
      h('div', { class: 'kpis' },
        kpi('Ventas aceptadas del mes', dinero(est.ventas_aceptadas_crc)),
        kpi('IVA de ventas', dinero(est.iva_ventas_crc)),
        kpi('Comprobantes emitidos', total),
        kpi('Con error o rechazados', est.con_error_o_rechazados, est.con_error_o_rechazados > 0, '#/comprobantes'),
        kpi('Facturas de proveedores sin responder', est.recibidos_sin_responder, est.recibidos_sin_responder > 0, '#/recepcion')),
      h('div', { class: 'campos dos' },
        h('section', { class: 'tarjeta' }, h('h2', {}, 'Por estado'),
          tabla([{ titulo: 'Estado', valor: (r) => badge(r[0]) }, { titulo: 'Cantidad', num: true, valor: (r) => r[1] }],
            Object.entries(est.comprobantes_por_estado))),
        h('section', { class: 'tarjeta' }, h('h2', {}, 'Por tipo'),
          tabla([{ titulo: 'Tipo', valor: (r) => r[0] }, { titulo: 'Cantidad', num: true, valor: (r) => r[1] }],
            Object.entries(est.comprobantes_por_tipo)))),
      h('section', { class: 'tarjeta' },
        h('div', { class: 'encabezado' }, h('h2', {}, 'Últimos comprobantes'), h('a', { href: '#/comprobantes' }, 'Ver todos')),
        tabla([
          { titulo: 'Fecha', valor: (f) => fecha(f.fecha_emision) },
          { titulo: 'Tipo', valor: (f) => TIPOS[f.tipo_documento] },
          { titulo: 'Consecutivo', valor: (f) => f.numero_consecutivo },
          { titulo: 'Cliente', valor: (f) => f.receptor_nombre || 'Consumidor final' },
          { titulo: 'Total', num: true, valor: (f) => dinero(f.monto_total, f.moneda) },
          { titulo: 'Estado', valor: (f) => badge(f.estado, ESTADOS[f.estado]) },
        ], ultimos, (f) => { location.hash = `#/comprobantes/${f.factura_id}`; })));
  }

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Tablero'),
      selectorMes(periodo, (p) => { periodo = p; cargar(); })),
    cuerpo);
  await cargar();
}

function kpi(etiqueta, valor, alerta = false, enlace = null) {
  const caja = h('div', { class: `kpi ${alerta ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, etiqueta), h('div', { class: 'valor' }, valor));
  return enlace ? h('a', { href: enlace, class: 'enlace-kpi' }, caja) : caja;
}
