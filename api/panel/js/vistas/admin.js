// Panel del administrador de la plataforma: tablero de ventas, vencimientos y
// empresas con problemas, y ajustes de cómo se facturan las ventas.
import { abrir, api, descargar } from '../api.js';
import { h, vaciar, dinero, fecha, tabla, conBoton, toast, campo, aviso, badge, mesActual, selectorMes } from '../dom.js';
import { MEDIOS_PAGO, TARIFAS_IVA } from '../catalogos.js';
import { dialogoCabys } from './emitir.js';

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'set', 'oct', 'nov', 'dic'];
const nombreMes = (periodo) => { const [a, m] = periodo.split('-'); return `${MESES[Number(m) - 1]} ${a.slice(2)}`; };
const kpi = (etiqueta, valor, { clase = '', enlace = null, nota = null } = {}) => {
  const caja = h('div', { class: `kpi ${clase}` }, h('div', { class: 'etiqueta' }, etiqueta), h('div', { class: 'valor' }, valor),
    nota ? h('div', { class: 'suave' }, nota) : null);
  return enlace ? h('a', { href: enlace, class: 'enlace-kpi' }, caja) : caja;
};
export const NIVELES = { error: ['RECHAZADO', 'Problema'], alerta: ['CONTINGENCIA', 'Atención'], info: ['PENDIENTE', 'Aviso'] };

// Barras de ventas por mes (una serie, colones). SVG con atributos: la CSP no permite estilos en línea.
function graficaVentas(meses) {
  const ns = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, ...hijos) => {
    const n = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, String(v)));
    hijos.forEach((c) => n.append(c instanceof Node ? c : document.createTextNode(String(c))));
    return n;
  };
  const valores = meses.map((m) => Number(m.CRC || 0));
  const max = Math.max(...valores, 1);
  const ancho = 560; const alto = 180; const base = 150; const tope = 24; const paso = ancho / meses.length; const barra = Math.min(48, paso * 0.55);
  const svg = el('svg', { viewBox: `0 0 ${ancho} ${alto}`, class: 'grafica', role: 'img', 'aria-label': 'Ventas por mes en colones, últimos 6 meses' });
  svg.append(el('line', { x1: 0, x2: ancho, y1: base, y2: base, class: 'eje' }));
  meses.forEach((m, i) => {
    const v = valores[i];
    const altoBarra = v > 0 ? Math.max(4, (base - tope) * v / max) : 0;
    const x = i * paso + (paso - barra) / 2;
    const y = base - altoBarra;
    const grupo = el('g', { class: `barra-mes ${i === meses.length - 1 ? 'actual' : ''}`, tabindex: 0 },
      el('title', {}, `${nombreMes(m.periodo)}: ${dinero(v)}${m.USD ? ` + ${dinero(m.USD, 'USD')}` : ''}`),
      el('rect', { x: i * paso, y: tope - 10, width: paso, height: base - tope + 10, class: 'zona' }));   // área de hover más grande que la barra
    if (altoBarra) {
      const r = Math.min(4, altoBarra);   // punta redondeada, base recta sobre el eje
      grupo.append(el('path', { class: 'marca', d: `M${x},${base} V${y + r} Q${x},${y} ${x + r},${y} H${x + barra - r} Q${x + barra},${y} ${x + barra},${y + r} V${base} Z` }));
    }
    grupo.append(el('text', { x: x + barra / 2, y: base + 18, class: 'etiqueta-eje', 'text-anchor': 'middle' }, nombreMes(m.periodo)));
    if (i === meses.length - 1 && v > 0) {
      grupo.append(el('text', { x: x + barra / 2, y: y - 6, class: 'etiqueta-valor', 'text-anchor': 'middle' }, dinero(v)));
    }
    svg.append(grupo);
  });
  const vistaTabla = h('details', {}, h('summary', {}, 'Ver como tabla'), tabla([
    { titulo: 'Mes', valor: (m) => nombreMes(m.periodo) },
    { titulo: 'Colones', num: true, valor: (m) => dinero(m.CRC || 0) },
    { titulo: 'Dólares', num: true, valor: (m) => (m.USD ? dinero(m.USD, 'USD') : '—') },
  ], meses));
  return [svg, vistaTabla];
}

export async function vistaTableroAdmin(cont) {
  const [t, ajustes] = await Promise.all([api('/admin/tablero', { conEmisor: false }), api('/admin/ajustes', { conEmisor: false })]);
  const ventasMes = Object.entries(t.ventas_mes);
  const conProblemas = t.empresas.filter((e) => e.activo && (e.errores || e.alertas));
  const irEmpresa = (seccion = '') => (x) => { location.hash = `#/empresas/${x.emisor_id}${seccion ? `/${seccion}` : ''}`; };

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Tablero de administración'),
      h('div', { class: 'acciones' }, h('a', { href: '#/planes', class: 'boton' }, 'Planes y ventas'),
        h('a', { href: '#/empresas', class: 'boton primario' }, 'Empresas'))),
    ajustes.emisor_ventas_id ? null : h('div', { class: 'aviso alerta' },
      'Las ventas aún no generan comprobante para el cliente. ', h('a', { href: '#/admin/ajustes' }, 'Configure qué empresa factura las ventas.')),
    h('div', { class: 'kpis' },
      ventasMes.length ? ventasMes.map(([m, v]) => kpi(`Ventas del mes (${m})`, dinero(v, m), { enlace: '#/planes' }))
        : kpi('Ventas del mes', dinero(0), { enlace: '#/planes' }),
      kpi('Documentos vendidos este mes', t.documentos_vendidos_mes.toLocaleString('es-CR'), { nota: `${t.documentos_consumidos_mes.toLocaleString('es-CR')} usados por los clientes` }),
      kpi('Compras por revisar', t.pagos_por_revisar, { clase: t.pagos_por_revisar ? 'alerta' : '', enlace: '#/admin/solicitudes' }),
      kpi('Mensualidades por confirmar', t.mensualidades_por_confirmar, { clase: t.mensualidades_por_confirmar ? 'alerta' : '', enlace: '#/admin/mensualidades' }),
      kpi('Inscripciones esta semana', t.empresas_nuevas_semana, { enlace: '#/empresas',
        nota: `${t.cuentas_nuevas_semana} cuenta(s) nueva(s) · ${t.cuentas_sin_empresa} sin inscribir su empresa` }),
      kpi('Empresas activas', t.empresas_activas, { enlace: '#/empresas' }),
      kpi('Empresas con problemas', t.empresas_con_errores, { clase: t.empresas_con_errores ? 'alerta' : '', nota: `${t.empresas_con_alertas} requieren atención` })),
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Ventas por mes (colones)'), graficaVentas(t.ventas_por_mes)),
      h('section', { class: 'tarjeta' }, h('h2', {}, `Por vencer o renovar (${t.vencimientos.length})`),
        t.vencimientos.length ? tabla([
          { titulo: 'Empresa', valor: (v) => v.empresa },
          { titulo: 'Qué', valor: (v) => [h('strong', {}, v.tipo), h('div', { class: 'suave' }, v.detalle)] },
          { titulo: 'Fecha', valor: (v) => (v.vence ? h('span', { class: `badge ${new Date(v.vence) < new Date() ? 'RECHAZADO' : 'CONTINGENCIA'}` }, fecha(v.vence, false)) : '—') },
        ], t.vencimientos.slice(0, 12), irEmpresa('compras')) : aviso('Nada vence en los próximos 15 días.', 'ok'))),
    h('section', { class: 'tarjeta' }, h('h2', {}, `Empresas con problemas para facturar (${conProblemas.length})`),
      conProblemas.length ? tabla([
        { titulo: 'Empresa', valor: (e) => [e.empresa, h('div', { class: 'suave' }, e.numero_identificacion)] },
        { titulo: 'Problema principal', valor: (e) => (e.principal ? [badge(NIVELES[e.principal.nivel][0], NIVELES[e.principal.nivel][1]), ' ',
          h('strong', {}, e.principal.titulo), h('div', { class: 'suave' }, e.principal.detalle)] : '') },
        { titulo: 'Total', valor: (e) => [e.errores ? `${e.errores} problema(s)` : '', e.errores && e.alertas ? ' · ' : '', e.alertas ? `${e.alertas} aviso(s)` : ''] },
      ], conProblemas, irEmpresa()) : aviso('Todas las empresas activas pueden facturar sin problemas.', 'ok')),
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Últimas ventas'), tabla([
        { titulo: 'Fecha', valor: (v) => fecha(v.fecha, false) },
        { titulo: 'Empresa', valor: (v) => [v.empresa, h('div', { class: 'suave' }, v.detalle)] },
        { titulo: 'Monto', num: true, valor: (v) => dinero(v.precio, v.moneda) },
        { titulo: 'Comprobante', valor: (v) => estadoComprobante(v.comprobante, Number(v.precio)) },
      ], t.ultimas_ventas, irEmpresa('compras'))),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Mejores clientes (12 meses)'), tabla([
        { titulo: 'Empresa', valor: (c) => c.empresa },
        { titulo: 'Compras', num: true, valor: (c) => c.compras },
        { titulo: 'Total', num: true, valor: (c) => Object.entries(c.total).map(([m, v]) => dinero(v, m)).join(' + ') },
        { titulo: 'Última', valor: (c) => fecha(c.ultima, false) },
      ], t.mejores_clientes, irEmpresa('compras')))));
}

export function estadoComprobante(c, precio = 1) {
  if (!c) return h('span', { class: 'suave' }, precio > 0 ? 'Sin comprobante' : 'Cortesía');
  if (c.error) return h('span', { class: 'badge RECHAZADO', title: c.error }, 'No se emitió');
  return [badge(c.estado), h('div', { class: 'suave' }, `${c.tipo_documento === '04' ? 'Tiquete' : 'Factura'} ${c.consecutivo.slice(-10)}`)];
}

// --- Ajustes: quién factura las ventas de la plataforma -------------------------------

export async function vistaAjustesVentas(cont) {
  const [a, empresas] = await Promise.all([api('/admin/ajustes', { conEmisor: false }), api('/emisores?activo=true', { conEmisor: false })]);
  const emisor = h('select', {}, h('option', { value: '' }, 'No emitir comprobante por las ventas'),
    empresas.map((e) => h('option', { value: e.id, selected: e.id === a.emisor_ventas_id }, `${e.nombre} · ${e.numero_identificacion}`)));
  const cabys = h('input', { type: 'text', maxlength: '13', value: a.codigo_cabys || '', placeholder: '13 dígitos' });
  const tarifa = h('select', {}, Object.entries(TARIFAS_IVA).map(([k, [t]]) => h('option', { value: k, selected: k === a.codigo_tarifa_iva }, t)));
  const incluyeIva = h('input', { type: 'checkbox', checked: a.precio_incluye_iva });
  const tipo = h('select', {}, h('option', { value: '01', selected: a.tipo_comprobante === '01' }, 'Factura electrónica (recomendado: el cliente es una empresa)'),
    h('option', { value: '04', selected: a.tipo_comprobante === '04' }, 'Tiquete electrónico'));
  const medio = h('select', {}, Object.entries(MEDIOS_PAGO).filter(([k]) => k !== '05' && k !== '99')
    .map(([k, v]) => h('option', { value: k, selected: k === a.medio_pago }, v)));
  const buscar = h('button', { type: 'button', onclick: () => dialogoCabys((item) => { cabys.value = item.codigo; }) }, 'Buscar CABYS');
  const instrucciones = h('textarea', { rows: '4', maxlength: '1000', placeholder: 'Ej.: SINPE Móvil 8888-8888 a nombre de …\nIBAN CR00 0000 0000 0000 0000 00' },
    a.instrucciones_pago || '');
  const contacto = h('input', { type: 'text', maxlength: '200', value: a.contacto_ventas || '', placeholder: 'WhatsApp 8888-8888 · ventas@suempresa.com' });
  const correoAvisos = h('input', { type: 'email', value: a.correo_avisos || '', placeholder: 'ventas@suempresa.com' });
  const autoregistro = h('input', { type: 'checkbox', checked: a.autoregistro });
  const pruebaDocs = h('input', { type: 'number', min: '0', max: '1000', step: '1', value: String(a.prueba_documentos ?? 20) });
  const pruebaDias = h('input', { type: 'number', min: '0', max: '90', step: '1', value: String(a.prueba_dias ?? 15) });
  const precioWeb = h('input', { type: 'number', min: '0', step: '0.01', value: a.precio_web_mensual || '', placeholder: 'Vacío = no se vende en línea' });
  const monedaWeb = h('select', {}, ['CRC', 'USD'].map((m) => h('option', { value: m, selected: m === a.moneda_web }, m)));
  const precioConta = h('input', { type: 'number', min: '0', step: '0.01', value: a.precio_contabilidad_mensual || '', placeholder: 'Vacío = sin costo' });
  const precioContador = h('input', { type: 'number', min: '0', step: '0.01', value: a.precio_contador_mensual || '', placeholder: 'Vacío = sin costo' });
  const diasPagar = h('input', { type: 'number', min: '1', max: '60', step: '1', value: String(a.dias_para_pagar ?? 10) });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    await api('/admin/ajustes', { method: 'PUT', conEmisor: false, body: {
      emisor_ventas_id: emisor.value || null, codigo_cabys: cabys.value.trim() || null, codigo_tarifa_iva: tarifa.value,
      precio_incluye_iva: incluyeIva.checked, tipo_comprobante: tipo.value, medio_pago: medio.value,
      instrucciones_pago: instrucciones.value.trim() || null, contacto_ventas: contacto.value.trim() || null,
      correo_avisos: correoAvisos.value.trim() || null,
      autoregistro: autoregistro.checked, prueba_documentos: Number(pruebaDocs.value || 0), prueba_dias: Number(pruebaDias.value || 0),
      precio_web_mensual: precioWeb.value ? precioWeb.value : null, moneda_web: monedaWeb.value,
      precio_contabilidad_mensual: precioConta.value || null, precio_contador_mensual: precioContador.value || null,
      dias_para_pagar: Number(diasPagar.value || 10),
    } });
    toast('Ajustes guardados', 'ok');
  }) }, 'Guardar');

  vaciar(cont,
    h('h1', {}, 'Facturación de ventas y avisos'),
    aviso('Cada vez que registre la venta de un paquete o una mensualidad con precio, el sistema le emite el comprobante '
      + 'al cliente desde la empresa elegida aquí, lo envía a Hacienda y se lo manda por correo al ser aceptado. '
      + 'Las cortesías (precio 0) no se facturan.', 'info'),
    h('section', { class: 'tarjeta' },
      h('div', { class: 'campos dos' },
        campo('Empresa que emite (la suya, registrada en Empresas con certificado)', emisor),
        h('div', { class: 'fila' }, campo('CABYS del servicio que vende', cabys), buscar),
        campo('IVA', tarifa), campo('Comprobante por defecto', tipo), campo('Medio de pago por defecto', medio),
        h('label', { class: 'check' }, incluyeIva, 'Los precios de los planes ya incluyen el IVA')),
      h('p', { class: 'suave' }, 'En cada venta puede cambiar el tipo de comprobante y el medio de pago, o no emitirlo.')),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Avisos al cliente'),
      h('p', { class: 'suave' }, 'Cuando a una empresa le quedan pocos documentos, se le agotan o se le vence un servicio, '
        + 'el sistema le escribe a su correo con sus planes activos, estas formas de pago y su contacto, invitándola a comprar.'),
      h('div', { class: 'campos dos' }, campo('Formas de pago', instrucciones),
        h('div', {}, campo('Contacto para comprar', contacto),
          campo('Su correo (recibe copia de cada aviso y las respuestas de los clientes)', correoAvisos)))),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Venta en línea'),
      h('p', { class: 'suave' }, 'Los clientes compran los planes activos (con precio) desde Mi saldo: pagan por SINPE o transferencia, '
        + 'le avisan y usted aprueba en Ventas → Pagos por revisar. La inscripción propia necesita el correo de salida (SMTP) configurado.'),
      h('div', { class: 'campos dos' },
        h('label', { class: 'check' }, autoregistro, 'Permitir que nuevas empresas se inscriban solas desde la página de entrada'),
        campo('Documentos gratis al inscribirse', pruebaDocs), campo('Días gratis del sistema en línea', pruebaDias),
        campo('Precio por mes del sistema en línea', precioWeb), campo('Moneda', monedaWeb))),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Mensualidades'),
      h('p', { class: 'suave' }, 'Cada servicio se cobra por aparte. Los documentos, por paquete (prepago). Las mensualidades se activan cuando el '
        + 'cliente las pide (viendo el precio) y se cobran en una factura el día 1 de cada mes, proporcional a los días. Si no paga en el '
        + 'plazo, se suspenden solas. Un precio vacío = ese servicio no se cobra. Se usa la moneda de arriba.'),
      h('div', { class: 'campos dos' },
        campo('Sistema en línea (por mes, arriba)', h('input', { type: 'text', disabled: true, value: 'Se configura en «Venta en línea»' })),
        campo('Contabilidad que lleva el dueño (por mes)', precioConta),
        campo('Cuenta de contador (por mes)', precioContador),
        campo('Días para pagar la factura mensual', diasPagar))),
    h('div', { class: 'acciones' }, guardar));
}

// --- Contabilidad: ventas del mes conciliadas con sus comprobantes ---------------------

export async function vistaContabilidad(cont) {
  let periodo = mesActual();
  const cuerpo = h('div');

  async function cargar() {
    vaciar(cuerpo, h('p', { class: 'cargando' }, 'Cargando…'));
    const c = await api(`/admin/contabilidad?anio=${periodo.anio}&mes=${periodo.mes}`, { conEmisor: false });
    const vendedor = c.emisor_ventas_id;
    const iva = vendedor
      ? await api(`/reportes/resumen-iva?anio=${periodo.anio}&mes=${periodo.mes}`, { emisor: vendedor }).catch(() => null) : null;
    const pendientes = c.sin_comprobante + c.rechazados + c.en_proceso;
    const sufijo = `${periodo.anio}${String(periodo.mes).padStart(2, '0')}`;
    const q = `anio=${periodo.anio}&mes=${periodo.mes}`;
    const ultimo = new Date(periodo.anio, periodo.mes, 0).getDate();
    const desde = `${periodo.anio}-${String(periodo.mes).padStart(2, '0')}-01`;
    const hasta = `${periodo.anio}-${String(periodo.mes).padStart(2, '0')}-${ultimo}`;
    const boton = (texto, accion) => {
      const b = h('button', { type: 'button', onclick: () => conBoton(b, accion) }, texto);
      return b;
    };
    const accion = (v) => {
      // Rechazado por Hacienda: se emite uno nuevo que lo sustituye (código 16)
      if (v.comprobante?.factura_id && v.comprobante.estado !== 'RECHAZADO') {
        return h('button', { type: 'button', class: 'chico', onclick: (ev) => conBoton(ev.target,
          () => abrir(`/facturas/${v.comprobante.factura_id}/pdf`, v.comprobante.emisor_id)) }, 'PDF');
      }
      if (!vendedor) return null;
      return h('button', { type: 'button', class: 'chico primario', onclick: (ev) => conBoton(ev.target, async () => {
        await api(`/admin/ventas/${v.clase}/${v.id}/comprobante`, { method: 'POST', body: {}, conEmisor: false });
        toast('Comprobante emitido', 'ok');
        await cargar();
      }) }, v.comprobante?.estado === 'RECHAZADO' ? 'Sustituir comprobante' : 'Emitir comprobante');
    };
    const cobradas = c.ventas.filter((v) => !v.anulada);
    const porAnular = c.ventas.filter((v) => v.anulada && v.nota_credito_pendiente);
    vaciar(cuerpo,
      vendedor ? null : h('div', { class: 'aviso alerta' }, 'Aún no hay una empresa que facture las ventas. ',
        h('a', { href: '#/admin/ajustes' }, 'Configúrela en Facturación y avisos.')),
      h('div', { class: 'kpis' },
        Object.entries(c.vendido).map(([m, v]) => kpi(`Vendido (${m})`, dinero(v, m))),
        Object.entries(c.facturado).map(([m, v]) => kpi(`Facturado y aceptado (${m})`, dinero(v, m))),
        kpi('Ventas con comprobante aceptado', `${c.aceptados} de ${cobradas.length}`),
        kpi('Pendientes de revisar', pendientes, { clase: pendientes ? 'alerta' : '',
          nota: `${c.sin_comprobante} sin comprobante · ${c.en_proceso} en proceso · ${c.rechazados} rechazado(s)` })),
      pendientes ? aviso('Antes de cerrar el mes, todas las ventas cobradas deberían tener su comprobante aceptado por Hacienda.', 'alerta')
        : cobradas.length ? aviso('Todas las ventas del mes tienen su comprobante aceptado.', 'ok') : null,
      porAnular.length ? h('section', { class: 'tarjeta' }, h('h2', {}, 'Ventas anuladas con comprobante vigente'),
        aviso('Estas ventas se anularon, pero su comprobante sigue aceptado por Hacienda y suma en la declaración de IVA. '
          + 'Anúlelo con nota de crédito desde la empresa que factura (Documentos emitidos).', 'alerta'),
        tabla([
          { titulo: 'Fecha', valor: (v) => fecha(v.fecha, false) },
          { titulo: 'Empresa', valor: (v) => [v.empresa, h('div', { class: 'suave' }, v.detalle)] },
          { titulo: 'Comprobante', valor: (v) => v.nota_credito_pendiente.consecutivo },
          { titulo: 'Monto', num: true, valor: (v) => dinero(v.precio, v.moneda) },
        ], porAnular)) : null,
      h('section', { class: 'tarjeta' }, h('h2', {}, `Ventas cobradas (${cobradas.length})`), tabla([
        { titulo: 'Fecha', valor: (v) => fecha(v.fecha, false) },
        { titulo: 'Empresa', valor: (v) => [v.empresa, h('div', { class: 'suave' }, v.detalle)] },
        { titulo: 'Pago', valor: (v) => v.referencia_pago || '—' },
        { titulo: 'Monto', num: true, valor: (v) => dinero(v.precio, v.moneda) },
        { titulo: 'Comprobante', valor: (v) => estadoComprobante(v.comprobante) },
        { titulo: '', valor: accion },
      ], cobradas)),
      vendedor ? h('section', { class: 'tarjeta' },
        h('h2', {}, `Para el contador · ${c.emisor_ventas}`),
        iva ? h('div', { class: 'kpis' },
          kpi('IVA cobrado (débito)', dinero(iva.iva_debito_fiscal)), kpi('IVA de compras (crédito)', dinero(iva.iva_credito_fiscal)),
          kpi('IVA neto estimado', dinero(iva.iva_neto_estimado))) : null,
        h('div', { class: 'acciones' },
          boton('Libro de ventas (Excel)', () => descargar(`/reportes/ventas.csv?${q}`, `ventas-${sufijo}.csv`, vendedor)),
          boton('Libro de compras (Excel)', () => descargar(`/reportes/compras.csv?${q}`, `compras-${sufijo}.csv`, vendedor)),
          boton('Comprobantes del mes (ZIP)', () => descargar(`/reportes/documentos.zip?desde=${desde}&hasta=${hasta}&pdf=true`,
            `comprobantes-${sufijo}.zip`, vendedor))),
        h('p', { class: 'suave' }, 'El IVA es una estimación para la declaración D-104; el contador la confirma con los libros.')) : null);
  }

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Contabilidad de ventas'),
      selectorMes(periodo, (p) => { periodo = p; cargar().catch((e) => toast(e.message, 'error')); })),
    cuerpo);
  await cargar();
}
