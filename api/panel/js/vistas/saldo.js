import { api } from '../api.js';
import { h, vaciar, dinero, fecha, tabla, aviso } from '../dom.js';
import { contexto } from '../app.js';

const ESTADO_PAQUETE = { VIGENTE: 'ACEPTADO', AGOTADO: 'PENDIENTE', VENCIDO: 'CONTINGENCIA', ANULADO: 'RECHAZADO' };

export function tablaPaquetes(paquetes, accion) {
  return tabla([
    { titulo: 'Fecha', valor: (p) => fecha(p.fecha, false) },
    { titulo: 'Paquete', valor: (p) => [p.nombre, p.referencia_pago ? h('div', { class: 'suave' }, `Pago: ${p.referencia_pago}`) : null] },
    { titulo: 'Comprados', num: true, valor: (p) => p.documentos.toLocaleString('es-CR') },
    { titulo: 'Usados', num: true, valor: (p) => p.usados.toLocaleString('es-CR') },
    { titulo: 'Disponibles', num: true, valor: (p) => p.disponibles.toLocaleString('es-CR') },
    { titulo: 'Vence', valor: (p) => (p.vence ? fecha(p.vence, false) : 'No vence') },
    { titulo: 'Precio', num: true, valor: (p) => dinero(p.precio, p.moneda) },
    { titulo: 'Estado', valor: (p) => h('span', { class: `badge ${ESTADO_PAQUETE[p.estado]}` }, p.estado) },
    accion ? { titulo: '', valor: (p) => accion(p) } : null,
  ].filter(Boolean), paquetes);
}

export function kpisSaldo(r) {
  return h('div', { class: 'kpis' },
    h('div', { class: `kpi ${r.alerta ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, 'Documentos disponibles'),
      h('div', { class: 'valor' }, r.disponible.toLocaleString('es-CR'))),
    h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Usados este mes'),
      h('div', { class: 'valor' }, r.usados_este_mes.toLocaleString('es-CR'))),
    h('div', { class: `kpi ${r.por_vencer ? 'alerta' : ''}` }, h('div', { class: 'etiqueta' }, 'Por vencer pronto'),
      h('div', { class: 'valor' }, r.por_vencer.toLocaleString('es-CR'))));
}

export async function vistaSaldo(cont) {
  const [r, movs] = await Promise.all([api('/saldo'), api('/saldo/movimientos?limit=200')]);
  if (!r.control_activo) {
    vaciar(cont, h('h1', {}, 'Mi saldo'), aviso('El control de saldo está desactivado: la facturación no tiene límite.', 'info'));
    return;
  }
  vaciar(cont,
    h('h1', {}, 'Mi saldo de documentos'),
    r.disponible <= 0
      ? aviso('Su saldo está agotado: no puede emitir comprobantes. Contacte a su proveedor para adquirir un paquete.', 'error')
      : r.alerta ? aviso(`Quedan pocos documentos (${r.disponible}). Adquiera un paquete para no interrumpir la facturación.`, 'alerta') : null,
    kpisSaldo(r),
    h('p', { class: 'suave' }, 'Cada comprobante firmado y enviado a Hacienda (facturas, tiquetes, notas, recibos de pago y respuestas a proveedores) consume 1 documento. Los reintentos no consumen.'),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Paquetes adquiridos'), tablaPaquetes(r.paquetes)),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Consumo reciente'),
      tabla([
        { titulo: 'Fecha', valor: (m) => fecha(m.fecha) },
        { titulo: 'Documento', valor: (m) => m.descripcion },
        { titulo: 'Clave', valor: (m) => (m.factura_id
          ? h('a', { href: `#/comprobantes/${m.factura_id}`, class: 'mono' }, m.referencia)
          : h('span', { class: 'mono' }, m.referencia)) },
        { titulo: 'Paquete', valor: (m) => m.paquete },
      ], movs)),
    contexto.esAdmin ? h('p', { class: 'suave' }, 'Como administrador puede acreditar paquetes desde Empresas.') : null);
}
