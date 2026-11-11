// Inicio de la empresa: accesos rápidos, avisos (saldo, certificado), números del mes y últimos comprobantes.
import { api } from '../api.js';
import { h, vaciar, dinero, fecha, badge, mesActual, selectorMes, tabla, TIPOS, ESTADOS } from '../dom.js';
import { contexto, empresaActual, puede } from '../app.js';

export async function vistaTablero(cont) {
  let periodo = mesActual();
  const cuerpo = h('div');

  async function cargar() {
    vaciar(cuerpo, h('p', { class: 'cargando' }, 'Cargando…'));
    const [est, ultimos] = await Promise.all([
      // El cajero no ve los números del mes: su inicio son los accesos rápidos y los últimos comprobantes
      puede('reportes') ? api(`/reportes/estadisticas?anio=${periodo.anio}&mes=${periodo.mes}`) : Promise.resolve(null),
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
          h('a', { href: '#/saldo' }, 'Ver saldo y recargar')));
      }
    }
    if (emp && !emp.tiene_certificado) {
      avisos.push(h('div', { class: 'aviso alerta' }, 'Esta empresa no tiene la llave criptográfica cargada; no podrá emitir. ',
        h('a', { href: contexto.esAdmin ? `#/empresas/${emp.id}` : '#/bienvenida' }, contexto.esAdmin ? 'Revisar datos de la empresa' : 'Ver primeros pasos')));
    } else if (emp?.cert_vence) {
      const dias = Math.floor((new Date(emp.cert_vence) - new Date()) / 86400000);
      if (dias < 30) {
        avisos.push(h('div', { class: 'aviso alerta' }, `El certificado digital vence en ${dias} días (${fecha(emp.cert_vence, false)}). `
          + 'Renuévelo en el BCCR o en su banco y cárguelo de nuevo. ',
        h('a', { href: contexto.esAdmin ? `#/empresas/${emp.id}` : '#/configuracion/cuenta' }, 'Ir a datos de la empresa')));
      }
    }

    const total = est ? Object.values(est.comprobantes_por_estado).reduce((a, b) => a + b, 0) : 0;
    vaciar(cuerpo,
      avisos,
      est && h('div', { class: 'kpis' },
        kpi('Ventas aceptadas del mes', dinero(est.ventas_aceptadas_crc)),
        kpi('IVA de ventas', dinero(est.iva_ventas_crc)),
        kpi('Comprobantes emitidos', total),
        kpi('Con error o rechazados', est.con_error_o_rechazados, est.con_error_o_rechazados > 0, '#/comprobantes'),
        kpi('Facturas de proveedores por aceptar', est.recibidos_sin_responder, est.recibidos_sin_responder > 0, '#/recepcion')),
      est && h('div', { class: 'campos dos' },
        h('section', { class: 'tarjeta' }, h('h2', {}, 'Por estado'),
          tabla([{ titulo: 'Estado', valor: (r) => badge(r[0]) }, { titulo: 'Cantidad', num: true, valor: (r) => r[1] }],
            Object.entries(est.comprobantes_por_estado))),
        h('section', { class: 'tarjeta' }, h('h2', {}, 'Por tipo'),
          tabla([{ titulo: 'Tipo', valor: (r) => TIPOS[r[0]] || r[0] }, { titulo: 'Cantidad', num: true, valor: (r) => r[1] }],
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
    h('div', { class: 'encabezado' }, h('div', {}, h('h1', {}, 'Inicio'),
      h('p', { class: 'suave ayuda-tipo' }, '¿Qué desea hacer hoy?')),
      puede('reportes') ? selectorMes(periodo, (p) => { periodo = p; cargar(); }) : null),
    accesosRapidos(),
    cuerpo);
  await cargar();
}

function kpi(etiqueta, valor, alerta = false, enlace = null) {
  const caja = h('div', { class: `kpi ${alerta ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, etiqueta), h('div', { class: 'valor' }, valor));
  return enlace ? h('a', { href: enlace, class: 'enlace-kpi' }, caja) : caja;
}

// Botones grandes con lo que más se hace, para no tener que buscar en el menú
function accesosRapidos() {
  const facturacion = empresaActual()?.facturacion_web !== false || contexto.esAdmin;
  const accesos = [
    facturacion && puede('emitir') && ['#/factura-rapida', 'Factura rápida', 'Venta de contado'],
    facturacion && puede('emitir') && ['#/emitir/01', 'Factura electrónica', 'Cliente con cédula'],
    facturacion && puede('emitir') && ['#/emitir/04', 'Tiquete', 'Consumidor final'],
    ['#/comprobantes', 'Mis documentos', 'Ver, reenviar o anular'],
    puede('recepcion') && ['#/recepcion', 'Facturas de proveedores', 'Aceptar o rechazar'],
  ].filter(Boolean);
  return h('div', { class: 'accesos' }, accesos.map(([href, titulo, ayuda], i) => h('a', { href, class: `acceso ${i === 0 ? 'principal' : ''}` },
    h('strong', {}, titulo), h('span', {}, ayuda))));
}
