// Aplicación principal: sesión, diseño y enrutador por hash.
import { api, sesion } from './api.js';
import { h, vaciar, toast } from './dom.js';
import { vistaLogin } from './vistas/login.js';
import { vistaTablero } from './vistas/tablero.js';
import { vistaComprobantes, vistaDetalleComprobante } from './vistas/comprobantes.js';
import { vistaEmitir, vistaEditarBorrador, vistaNuevaProforma } from './vistas/emitir.js';
import { vistaProformas, vistaPreliminares } from './vistas/borradores.js';
import { vistaPuntoVenta, vistaCajas, vistaDetalleCaja } from './vistas/puntoVenta.js';
import { vistaDescargas } from './vistas/descargas.js';
import { vistaFacturaRapida } from './vistas/facturaRapida.js';
import { vistaRecepcion } from './vistas/recepcion.js';
import { vistaReportes, vistaD104 } from './vistas/reportes.js';
import { vistaConsultas } from './vistas/consultas.js';
import { vistaEmpresas, vistaDetalleEmpresa } from './vistas/empresas.js';
import { vistaTableroAdmin, vistaAjustesVentas, vistaContabilidad } from './vistas/admin.js';
import { vistaUsuarios } from './vistas/usuarios.js';
import { vistaCuenta } from './vistas/cuenta.js';
import { vistaSaldo } from './vistas/saldo.js';
import { vistaPlanes } from './vistas/planes.js';
import { vistaAuditoria } from './vistas/auditoria.js';
import { vistaClientes, vistaCargarClientes, vistaReporteClientes } from './vistas/clientes.js';
import { vistaProductos, vistaCargarProductos, vistaReporteProductos, vistaCombos } from './vistas/productos.js';
import { vistaCategorias, vistaDescuentos } from './vistas/promociones.js';
import { vistaInventario } from './vistas/inventario.js';
import { vistaComprobantesPago } from './vistas/pagos.js';
import { vistaCuentasPorCobrar, vistaEstadoCuenta } from './vistas/cobros.js';
import { vistaRecurrentes } from './vistas/recurrentes.js';
import { vistaBienvenida } from './vistas/bienvenida.js';
import {
  vistaRegistro, vistaConfirmar, recibirOauth, vistaErrorOauth, vistaInscribirEmpresa,
} from './vistas/registro.js';
import { vistaSolicitudes } from './vistas/comprar.js';
import { vistaServicios, vistaMensualidades } from './vistas/servicios.js';
import {
  vistaContaInicio, vistaContaCuentas, vistaContaAsientos, vistaContaDocumentos, vistaContaComprobacion,
  vistaContaResultados, vistaContaBalance, vistaContaMayor, vistaContaPeriodos, vistaContaCierre,
} from './vistas/contabilidad.js';
import { vistaInformacionCuenta, vistaActividadEconomica } from './vistas/configuracion.js';

export const contexto = {
  usuario: null, esAdmin: false, empresas: [], controlSaldo: false, saldoAlerta: 20, debeActivar2fa: false,
  rol: 'dueno', permisos: [], esContador: false, faltaEmpresa: false,
};

// Permiso que pide cada pantalla según el rol del usuario (dueño, contador o cajero).
// Las notas van antes que el resto de #/emitir porque se revisan en orden.
const PERMISO_RUTA = [
  [/^#\/emitir\/0[23]\b/, 'anular'],
  [/^#\/(emitir|factura-rapida|proformas?|preliminares|recurrentes)\b/, 'emitir'],
  [/^#\/(punto-venta|cajas)\b/, 'pos'],
  [/^#\/recepcion\b/, 'recepcion'],
  // IVA, D-104 y todo lo contable es solo del contador
  [/^#\/(reportes|d104|contabilidad|conta\/)/, 'contabilidad'],
  [/^#\/(descargas|clientes\/reporte|productos\/reporte)\b/, 'reportes'],
  [/^#\/(productos\/cargar|inventario|categorias|descuentos|combos)\b/, 'catalogo'],
  [/^#\/clientes\/cargar\b/, 'clientes'],
  [/^#\/(pagos|comprobantes-pago|estado-cuenta)\b/, 'cobrar'],
  [/^#\/usuarios\b/, 'usuarios'],
];

export const puede = (permiso) => (contexto.esAdmin && permiso !== 'contabilidad') || contexto.permisos.includes(permiso);

// Pantallas que puede abrir el contador (todo lo demás lo devuelve a su inicio)
const RUTAS_CONTADOR = /^#\/(contabilidad|conta\/|reportes$|d104$|consultas$|cuenta$|servicios$)/;

function rutaPermitida(ruta) {
  const regla = PERMISO_RUTA.find(([re]) => re.test(ruta));
  return !regla || puede(regla[1]);
}

const RUTAS = [
  [/^#\/tablero$/, vistaTablero, true],
  [/^#\/comprobantes$/, vistaComprobantes, true],
  [/^#\/comprobantes\/([\w-]+)$/, vistaDetalleComprobante, true],
  [/^#\/emitir$/, vistaEmitir, true],
  [/^#\/emitir\/(\d{2})$/, vistaEmitir, true],
  [/^#\/emitir\/borrador\/([\w-]+)$/, vistaEditarBorrador, true],
  [/^#\/proforma\/nueva$/, vistaNuevaProforma, true],
  [/^#\/proformas$/, vistaProformas, true],
  [/^#\/preliminares$/, vistaPreliminares, true],
  [/^#\/factura-rapida$/, vistaFacturaRapida, true],
  [/^#\/punto-venta$/, vistaPuntoVenta, true],
  [/^#\/cajas$/, vistaCajas, true],
  [/^#\/cajas\/([\w-]+)$/, vistaDetalleCaja, true],
  [/^#\/descargas$/, vistaDescargas, true],
  [/^#\/recepcion$/, vistaRecepcion, true],
  [/^#\/reportes$/, vistaReportes, true],
  [/^#\/consultas$/, vistaConsultas, false],
  [/^#\/pagos$/, vistaCuentasPorCobrar, true],
  [/^#\/estado-cuenta\/([^/]+)$/, vistaEstadoCuenta, true],
  [/^#\/recurrentes$/, vistaRecurrentes, true],
  [/^#\/d104$/, vistaD104, true],
  [/^#\/bienvenida$/, vistaBienvenida, true],
  [/^#\/contabilidad$/, vistaContaInicio, false],
  [/^#\/conta\/cuentas$/, vistaContaCuentas, true],
  [/^#\/conta\/asientos$/, vistaContaAsientos, true],
  [/^#\/conta\/documentos$/, vistaContaDocumentos, true],
  [/^#\/conta\/comprobacion$/, vistaContaComprobacion, true],
  [/^#\/conta\/resultados$/, vistaContaResultados, true],
  [/^#\/conta\/balance$/, vistaContaBalance, true],
  [/^#\/conta\/mayor$/, vistaContaMayor, true],
  [/^#\/conta\/periodos$/, vistaContaPeriodos, true],
  [/^#\/conta\/cierre$/, vistaContaCierre, true],
  [/^#\/comprobantes-pago$/, vistaComprobantesPago, true],
  [/^#\/empresas$/, vistaEmpresas, false],
  [/^#\/empresas\/([\w-]+)$/, vistaDetalleEmpresa, false],
  [/^#\/empresas\/([\w-]+)\/(\w+)$/, vistaDetalleEmpresa, false],
  [/^#\/admin$/, vistaTableroAdmin, false],
  [/^#\/admin\/ajustes$/, vistaAjustesVentas, false],
  [/^#\/admin\/solicitudes$/, vistaSolicitudes, false],
  [/^#\/admin\/mensualidades$/, vistaMensualidades, false],
  [/^#\/servicios$/, vistaServicios, false],
  [/^#\/admin\/contabilidad$/, vistaContabilidad, false],
  [/^#\/usuarios$/, vistaUsuarios, false],
  [/^#\/cuenta$/, vistaCuenta, false],
  [/^#\/configuracion\/cuenta$/, vistaInformacionCuenta, true],
  [/^#\/configuracion\/actividad$/, vistaActividadEconomica, true],
  [/^#\/saldo$/, vistaSaldo, true],
  [/^#\/planes$/, vistaPlanes, false],
  [/^#\/auditoria$/, vistaAuditoria, false],
  [/^#\/clientes$/, vistaClientes, true],
  [/^#\/clientes\/cargar$/, vistaCargarClientes, true],
  [/^#\/clientes\/reporte$/, vistaReporteClientes, true],
  [/^#\/productos$/, vistaProductos, true],
  [/^#\/productos\/cargar$/, vistaCargarProductos, true],
  [/^#\/productos\/reporte$/, vistaReporteProductos, true],
  [/^#\/inventario$/, vistaInventario, true],
  [/^#\/categorias$/, vistaCategorias, true],
  [/^#\/descuentos$/, vistaDescuentos, true],
  [/^#\/combos$/, vistaCombos, true],
];

// Rutas del módulo de facturación en línea (se ocultan si la empresa no lo tiene)
const MODULO_FACTURACION = /^#\/(emitir|factura-rapida|punto-venta|cajas|proformas?|preliminares|clientes|productos|inventario|pagos|estado-cuenta|recurrentes|categorias|descuentos|combos)\b/;

// Menú principal. Cada opción: [ruta, texto, qué hace (ayuda), solo administradores].
// { seccion: '…' } agrupa opciones dentro del desplegable para que se entienda qué hacer.
const MENU = [
  { titulo: 'Facturar', icono: 'factura', items: [
    { seccion: 'Vender' },
    ['#/factura-rapida', 'Factura rápida', 'Venta de contado en pocos pasos'],
    ['#/emitir/01', 'Factura electrónica', 'Cliente con cédula, crédito o exoneración'],
    ['#/emitir/04', 'Tiquete electrónico', 'Venta a consumidor final sin cédula'],
    ['#/punto-venta', 'Punto de venta', 'Caja con apertura y cierre del día'],
    { seccion: 'Corregir una factura ya enviada' },
    ['#/emitir/03', 'Nota de crédito', 'Anular, devolver mercadería o rebajar el monto'],
    ['#/emitir/02', 'Nota de débito', 'Cobrar un monto adicional a una factura'],
    { seccion: 'Otros documentos' },
    ['#/proforma/nueva', 'Proforma o cotización', 'Sin validez fiscal; luego se convierte en factura'],
    ['#/recurrentes', 'Facturas recurrentes', 'Alquileres y mensualidades que se emiten solos'],
    ['#/emitir/08', 'Factura de compra', 'Compra a un proveedor que no factura'],
    ['#/emitir/09', 'Factura de exportación', 'Venta a un cliente en el extranjero'],
  ] },
  { titulo: 'Documentos', icono: 'carpeta', items: [
    { seccion: 'Lo que vendí' },
    ['#/comprobantes', 'Documentos emitidos', 'Ver estado, PDF, reenviar por correo o anular'],
    ['#/preliminares', 'Facturas sin enviar', 'Guardadas como preliminar para terminar luego'],
    ['#/proformas', 'Proformas', 'Cotizaciones pendientes de facturar'],
    ['#/cajas', 'Cierres de caja', 'Resumen de cada turno del punto de venta'],
    { seccion: 'Lo que compré' },
    ['#/recepcion', 'Facturas de proveedores', 'Aceptar o rechazar ante Hacienda'],
    { seccion: 'Cobros' },
    ['#/pagos', 'Cuentas por cobrar', 'Saldos, atrasos, abonos y estado de cuenta por cliente'],
    ['#/comprobantes-pago', 'Recibos de pago', 'Recibos electrónicos emitidos'],
    { seccion: 'Respaldo' },
    ['#/descargas', 'Descargar XML y PDF', 'Todos los documentos de un mes en un ZIP'],
  ] },
  { titulo: 'Clientes y productos', icono: 'caja', items: [
    { seccion: 'Clientes' },
    ['#/clientes', 'Mis clientes', 'Agregar, editar o buscar clientes'],
    ['#/clientes/cargar', 'Importar clientes', 'Cargar muchos desde Excel (CSV)'],
    { seccion: 'Productos y servicios' },
    ['#/productos', 'Mis productos', 'Precios, CABYS e impuesto de cada producto'],
    ['#/inventario', 'Inventario', 'Existencias y movimientos'],
    ['#/categorias', 'Categorías', 'Ordenar productos por grupo'],
    ['#/descuentos', 'Descuentos', 'Promociones automáticas'],
    ['#/combos', 'Combos', 'Varios productos que se venden juntos'],
    ['#/productos/cargar', 'Importar productos', 'Cargar muchos desde Excel (CSV)'],
  ] },
  { titulo: 'Reportes', icono: 'grafico', items: [
    { seccion: 'Listados' },
    ['#/clientes/reporte', 'Reporte de clientes', 'Ventas por cliente'],
    ['#/productos/reporte', 'Reporte de productos', 'Ventas por producto'],
    { seccion: 'Hacienda' },
    ['#/consultas', 'Consultas a Hacienda', 'Cédulas, CABYS, exoneraciones y tipo de cambio'],
  ] },
  // Solo el dueño de la empresa (sus demás usuarios no la ven)
  { titulo: 'Contabilidad', icono: 'caja', items: [
    { seccion: 'Del mes' },
    ['#/conta/documentos', 'Comprobantes del mes', 'Contabilizar ventas, compras y costo de ventas'],
    ['#/conta/asientos', 'Libro diario', 'Asientos manuales y automáticos'],
    ['#/conta/periodos', 'Cierre de meses', 'Bloquear los meses ya declarados'],
    ['#/conta/cierre', 'Cierre del año', 'Asiento de cierre anual y su archivo digital'],
    { seccion: 'Estados financieros' },
    ['#/conta/balance', 'Balance general', 'Activo, pasivo y patrimonio a una fecha'],
    ['#/conta/resultados', 'Estado de resultados', 'Ingresos, costos y gastos de un período'],
    ['#/conta/comprobacion', 'Balance de comprobación', 'Sumas y saldos de todas las cuentas'],
    ['#/conta/mayor', 'Libro mayor', 'Movimientos de una cuenta'],
    { seccion: 'Impuestos' },
    ['#/reportes', 'Reporte de IVA', 'Ventas, compras e IVA del mes; libros en Excel'],
    ['#/d104', 'Borrador D-104', 'Montos listos para copiar a TRIBU-CR'],
    { seccion: 'Configuración' },
    ['#/conta/cuentas', 'Catálogo de cuentas', 'Cuentas de la empresa (base NIIF para PYMES)'],
  ] },
  { titulo: 'Configuración', icono: 'engranaje', items: [
    { seccion: 'Mi empresa' },
    ['#/bienvenida', 'Primeros pasos', 'Llave criptográfica, usuario de Hacienda y lo que falta'],
    ['#/configuracion/cuenta', 'Datos de la empresa', 'Nombre, certificado y estado del servicio'],
    ['#/configuracion/actividad', 'Actividad económica', 'La registrada en Hacienda'],
    ['#/saldo', 'Saldo de documentos', 'Cuántas facturas le quedan disponibles'],
    ['#/servicios', 'Mis servicios y facturas', 'Precio de cada mensualidad, activar y pagar'],
    { seccion: 'Usuarios' },
    ['#/cuenta', 'Mi usuario', 'Contraseña y verificación en dos pasos'],
    ['#/usuarios', 'Usuarios', 'Quién entra al sistema y qué puede hacer (dueño, contador, cajero)'],
  ] },
];

// El contador: solo la contabilidad de las empresas que tiene a cargo.
const MENU_CONTADOR = [
  { titulo: 'Contabilidad', icono: 'factura', items: [
    ['#/contabilidad', 'Mis empresas', 'Las empresas que lleva y cómo va cada una'],
    { seccion: 'Del mes' },
    ['#/conta/documentos', 'Comprobantes del mes', 'Contabilizar ventas y compras; cargar XML'],
    ['#/conta/asientos', 'Libro diario', 'Asientos manuales y automáticos'],
    ['#/conta/periodos', 'Cierre de meses', 'Bloquear los meses ya declarados'],
    ['#/conta/cierre', 'Cierre del año', 'Asiento de cierre anual y su archivo digital'],
    { seccion: 'Configuración' },
    ['#/conta/cuentas', 'Catálogo de cuentas', 'Cuentas de la empresa (base NIIF para PYMES)'],
    ['#/servicios', 'Mi mensualidad', 'Precio de su cuenta de contador y sus facturas'],
  ] },
  { titulo: 'Estados financieros', icono: 'grafico', items: [
    ['#/conta/balance', 'Balance general', 'Activo, pasivo y patrimonio a una fecha'],
    ['#/conta/resultados', 'Estado de resultados', 'Ingresos, costos y gastos de un período'],
    ['#/conta/comprobacion', 'Balance de comprobación', 'Sumas y saldos de todas las cuentas'],
    ['#/conta/mayor', 'Libro mayor', 'Movimientos de una cuenta'],
  ] },
  { titulo: 'Impuestos', icono: 'carpeta', items: [
    ['#/reportes', 'Reporte de IVA', 'Ventas, compras e IVA del mes; libros en Excel'],
    ['#/d104', 'Borrador D-104', 'Montos listos para copiar a TRIBU-CR'],
    ['#/consultas', 'Consultas a Hacienda', 'Cédulas, CABYS, exoneraciones y tipo de cambio'],
  ] },
];

// El administrador de la plataforma no factura: solo administra empresas, ventas y accesos.
const MENU_ADMIN = [
  { titulo: 'Empresas', icono: 'escudo', items: [
    ['#/empresas', 'Empresas cliente', 'Certificado, credenciales, compras y alertas de cada empresa'],
    ['#/usuarios', 'Usuarios', 'Accesos de las empresas y de los administradores'],
  ] },
  { titulo: 'Ventas', icono: 'grafico', items: [
    ['#/planes', 'Planes y ventas', 'Paquetes de documentos, mensualidades e ingresos'],
    ['#/admin/solicitudes', 'Pagos por revisar', 'Compras en línea pagadas por SINPE o transferencia'],
    ['#/admin/mensualidades', 'Mensualidades', 'Facturas mensuales de los servicios y sus pagos'],
    ['#/admin/contabilidad', 'Contabilidad', 'Ventas del mes con su comprobante, IVA y libros para el contador'],
    ['#/admin/ajustes', 'Facturación y avisos', 'Quién factura las ventas y qué dice el correo de pocos documentos'],
  ] },
  { titulo: 'Sistema', icono: 'engranaje', items: [
    ['#/auditoria', 'Bitácora', 'Quién hizo qué y cuándo'],
    ['#/consultas', 'Consultas a Hacienda', 'Cédulas, CABYS, exoneraciones y tipo de cambio'],
    ['#/cuenta', 'Mi usuario', 'Contraseña y verificación en dos pasos'],
  ] },
];
const esOpcion = (item) => Array.isArray(item);

// Íconos de línea (SVG creado con el DOM: no requiere estilos ni scripts en línea)
const ICONOS = {
  inicio: 'M3 11l9-8 9 8M5 9.5V21h5v-6h4v6h5V9.5',
  factura: 'M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6M9 16h3',
  carpeta: 'M3 6a1 1 0 011-1h5l2 2h9a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1z',
  caja: 'M3 7l9-4 9 4-9 4-9-4zM3 7v10l9 4 9-4V7M12 11v10',
  grafico: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  engranaje: 'M12 9a3 3 0 100 6 3 3 0 000-6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1',
  escudo: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  usuario: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0',
  flecha: 'M6 9l6 6 6-6',
  menu: 'M4 6h16M4 12h16M4 18h16',
  mas: 'M12 5v14M5 12h14',
};
function icono(nombre, clase = 'icono') {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', clase);
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', ICONOS[nombre]);
  svg.append(path);
  return svg;
}

export async function cargarContexto() {
  const yo = await api('/auth/yo');
  contexto.usuario = yo.usuario;
  contexto.esAdmin = yo.es_admin;
  contexto.empresas = yo.empresas;
  contexto.controlSaldo = yo.control_saldo;
  contexto.saldoAlerta = yo.saldo_alerta;
  contexto.debeActivar2fa = !!yo.debe_activar_2fa;
  contexto.rol = yo.rol || 'dueno';
  contexto.permisos = yo.permisos || [];
  contexto.esContador = !!yo.es_contador;
  contexto.faltaEmpresa = !!yo.falta_empresa;
  if (!contexto.empresas.some((e) => e.id === sesion.emisorId)) {
    sesion.emisorId = contexto.empresas[0]?.id || null;
  }
}

function moduloDisponible(ruta) {
  if (contexto.esAdmin || !MODULO_FACTURACION.test(ruta)) return true;
  return empresaActual()?.facturacion_web !== false;
}

export function empresaActual() {
  return contexto.empresas.find((e) => e.id === sesion.emisorId) || null;
}

function selectorEmpresa() {
  if (!contexto.empresas.length) return h('span', { class: 'suave' }, 'Sin empresas registradas');
  const sel = h('select', {
    'aria-label': 'Empresa',
    onchange: () => { sesion.emisorId = sel.value; enrutar(); },
  }, contexto.empresas.map((e) => h('option', { value: e.id, selected: e.id === sesion.emisorId },
    `${e.nombre} · ${e.numero_identificacion}`)));
  if (contexto.empresas.length === 1) sel.disabled = true;
  const emp = empresaActual();
  return h('div', { class: 'empresa' }, sel,
    contexto.esContador ? h('span', { class: 'badge prod' }, 'Contabilidad') : [
      emp ? h('span', { class: `badge ${emp.ambiente}` }, emp.ambiente === 'prod' ? 'Producción' : 'Pruebas') : null,
      indicadorSaldo(emp)]);
}

function indicadorSaldo(emp) {
  if (!emp || !contexto.controlSaldo || emp.saldo_documentos === null || emp.saldo_documentos === undefined) return null;
  const n = emp.saldo_documentos;
  const clase = n <= 0 ? 'RECHAZADO' : n <= contexto.saldoAlerta ? 'CONTINGENCIA' : 'ACEPTADO';
  return h('a', { href: '#/saldo', class: `badge ${clase}`, title: 'Documentos disponibles' },
    `${n.toLocaleString('es-CR')} documentos`);
}

async function salir() {
  try { await api('/auth/logout', { method: 'POST', conEmisor: false, redirigir401: false }); } catch { /* ya vencida */ }
  sesion.limpiar();
  Object.assign(contexto, { usuario: null, esAdmin: false, empresas: [], controlSaldo: false });
  location.hash = '#/login';
}

// Coincide la ruta exacta o una subruta (p. ej. el detalle de un comprobante).
const enRuta = (ruta, href) => ruta === href || ruta.startsWith(`${href}/`);

// Cierra los desplegables al tocar fuera de ellos o con Escape (se registra una vez).
function cerrarMenus(excepto = null) {
  document.querySelectorAll('.menu-grupo.abierto').forEach((g) => {
    if (g !== excepto) {
      g.classList.remove('abierto');
      g.querySelector('.menu-boton')?.setAttribute('aria-expanded', 'false');
    }
  });
}
document.addEventListener('click', (e) => { if (!e.target.closest('.menu-grupo')) cerrarMenus(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') cerrarMenus(); });

function grupoMenu(titulo, iconoNombre, items, ruta, clase = '') {
  const activo = items.some((it) => esOpcion(it) && enRuta(ruta, it[0]));
  const boton = h('button', { type: 'button', class: 'menu-boton', 'aria-haspopup': 'true', 'aria-expanded': 'false' },
    icono(iconoNombre), h('span', {}, titulo), icono('flecha', 'icono flecha'));
  const grupo = h('div', { class: `menu-grupo ${activo ? 'activo' : ''} ${clase}` }, boton,
    h('div', { class: 'desplegable', role: 'menu' },
      items.map((it) => (esOpcion(it)
        ? h('a', { href: it[0], role: 'menuitem', class: ruta === it[0] ? 'activo' : '' },
          h('span', { class: 'opcion' }, it[1]), it[2] ? h('span', { class: 'ayuda' }, it[2]) : null)
        : h('div', { class: 'seccion-menu', role: 'presentation' }, it.seccion)))));
  boton.addEventListener('click', () => {
    const abrir = !grupo.classList.contains('abierto');
    cerrarMenus(grupo);
    grupo.classList.toggle('abierto', abrir);
    boton.setAttribute('aria-expanded', String(abrir));
  });
  return grupo;
}

// Quita opciones no permitidas y los títulos de sección que quedan sin opciones.
function filtrarItems(items) {
  const permitidos = items.filter((it) => !esOpcion(it) || ((!it[3] || contexto.esAdmin) && moduloDisponible(it[0]) && rutaPermitida(it[0])));
  return permitidos.filter((it, i) => esOpcion(it) || esOpcion(permitidos[i + 1] || {}));
}

export const inicio = () => (contexto.esAdmin ? '#/admin' : contexto.esContador ? '#/contabilidad' : '#/tablero');

function diseno(ruta) {
  const admin = contexto.esAdmin;
  const grupos = (admin ? MENU_ADMIN : contexto.esContador ? MENU_CONTADOR : MENU)
    .map((g) => ({ ...g, items: filtrarItems(g.items) }))
    .filter((g) => g.items.some(esOpcion));
  const usuario = contexto.usuario;
  const contenido = h('main', { class: 'contenido' });
  const nav = h('nav', { class: 'menu', 'aria-label': 'Principal' },
    h('a', { href: inicio(), class: `menu-inicio ${ruta === inicio() ? 'activo' : ''}`, title: 'Inicio', 'aria-label': 'Inicio' }, icono('inicio')),
    grupos.map((g) => grupoMenu(g.titulo, g.icono, g.items, ruta)),
    !admin && moduloDisponible('#/emitir') && empresaActual() && puede('emitir')
      ? h('a', { href: '#/emitir/01', class: 'boton primario nueva-factura' }, icono('mas'), 'Nueva factura') : null);
  const alternar = h('button', { type: 'button', class: 'menu-movil', 'aria-label': 'Menú', 'aria-expanded': 'false', onclick: () => {
    const abierto = nav.classList.toggle('visible');
    alternar.setAttribute('aria-expanded', String(abierto));
  } }, icono('menu'));

  const raiz = h('div', { class: 'layout' },
    h('header', { class: 'cabecera' },
      h('div', { class: 'barra' },
        alternar,
        h('a', { href: inicio(), class: 'marca' }, h('img', { src: 'img/icono.svg', alt: '' }), h('span', {}, 'Facturación CR')),
        admin ? h('span', { class: 'badge prod' }, 'Administración') : selectorEmpresa(),
        h('span', { class: 'espacio' }),
        usuario ? grupoMenu(usuario.nombre, 'usuario', [['#/cuenta', 'Mi usuario', 'Contraseña y verificación en dos pasos']], ruta, 'menu-usuario') : null,
        h('button', { type: 'button', class: 'salir', onclick: salir }, 'Salir')),
      nav),
    contenido);
  return { raiz, contenido };
}

function pantallaSinPanel(emp) {
  return h('div', { class: 'layout' },
    h('header', { class: 'cabecera' }, h('div', { class: 'barra' },
      h('span', { class: 'marca' }, h('img', { src: 'img/icono.svg', alt: '' }), h('span', {}, 'Facturación CR')),
      h('span', { class: 'espacio' }),
      h('a', { href: '#/cuenta', class: 'boton' }, 'Mi usuario'),
      h('button', { type: 'button', class: 'salir', onclick: salir }, 'Salir'))),
    h('main', { class: 'contenido' }, h('section', { class: 'tarjeta sin-panel' },
      h('h1', {}, emp.nombre),
      h('p', {}, 'Su servicio de facturación electrónica funciona conectado a su sistema (API): '
        + 'sus comprobantes se emiten y se envían a Hacienda desde allí.'),
      h('div', { class: 'aviso info' }, 'El sistema en línea para facturar desde el navegador no está activo (o está suspendido por '
        + 'una factura vencida). Puede ver su precio, activarlo o pagar en «Mis servicios».'),
      h('a', { href: '#/servicios', class: 'boton primario' }, 'Mis servicios y facturas'))));
}

export async function enrutar() {
  const app = document.getElementById('app');
  const ruta = location.hash || '#/tablero';

  // Vuelta de Google / Microsoft
  const oauth = ruta.match(/^#\/oauth\/(ses_[\w-]+)$/);
  if (oauth) { recibirOauth(oauth[1]); enrutar(); return; }
  const errorOauth = ruta.match(/^#\/oauth-error\/(\w+)$/);
  if (errorOauth) { vaciar(app, vistaErrorOauth(errorOauth[1])); return; }
  // Pantallas sin sesión: inscripción propia y confirmación del correo
  if (ruta === '#/registro') { vaciar(app, vistaRegistro()); return; }
  const confirmar = ruta.match(/^#\/confirmar\/([\w-]+)$/);
  if (confirmar) { vaciar(app, vistaConfirmar(confirmar[1])); return; }
  if (ruta === '#/login' || !sesion.token) {
    vaciar(app, vistaLogin());
    return;
  }
  // Se recarga en cada navegación para que el saldo y las empresas estén al día
  try { await cargarContexto(); } catch { return; }

  // Administrador sin verificación en dos pasos: solo puede entrar a Mi cuenta para activarla
  if (contexto.debeActivar2fa && ruta !== '#/cuenta') { location.hash = '#/cuenta'; return; }
  // El inicio del administrador es su tablero, no el de facturación de una empresa
  if (contexto.esAdmin && ruta === '#/tablero') { location.hash = '#/admin'; return; }
  // Cuenta nueva que va a facturar: primero inscribe su empresa
  if (contexto.faltaEmpresa && ruta !== '#/cuenta') { vaciar(app, vistaInscribirEmpresa(salir)); return; }
  // El contador solo usa la contabilidad
  if (contexto.esContador && !RUTAS_CONTADOR.test(ruta)) { location.hash = '#/contabilidad'; return; }
  // El panel web es un servicio adicional: sin él, la empresa factura solo por API
  const emp = empresaActual();
  if (!contexto.esAdmin && !contexto.esContador && emp && emp.facturacion_web === false && !['#/cuenta', '#/servicios'].includes(ruta)) {
    vaciar(app, pantallaSinPanel(emp));
    return;
  }
  const encontrada = RUTAS.find(([re]) => re.test(ruta));
  if (!encontrada) { location.hash = inicio(); return; }
  const [re, vista, requiereEmpresa] = encontrada;
  const { raiz, contenido } = diseno(ruta);
  vaciar(app, raiz);

  if (!moduloDisponible(ruta)) {
    vaciar(contenido, h('div', { class: 'aviso info' },
      'La facturación en línea no está activa para esta empresa. Contacte a su proveedor para activarla.'));
    return;
  }
  if (!rutaPermitida(ruta)) {
    vaciar(contenido, h('div', { class: 'aviso info' },
      'Su usuario no tiene permiso para esta sección. Si la necesita, pídasela al dueño de la empresa.'));
    return;
  }
  if (requiereEmpresa && !empresaActual()) {
    vaciar(contenido, h('div', { class: 'aviso info' },
      contexto.esAdmin ? 'Registre primero una empresa en la sección Empresas.' : 'Su usuario no tiene una empresa asignada.'));
    return;
  }
  try {
    await vista(contenido, ...ruta.match(re).slice(1));
  } catch (e) {
    if (e.headers?.get?.('X-Requiere-Servicio')) {
      // Servicio con mensualidad sin activar (o suspendido): se le dice el precio y dónde activarlo
      vaciar(contenido, h('section', { class: 'tarjeta' }, h('h2', {}, 'Este servicio tiene mensualidad'),
        h('div', { class: 'aviso info' }, e.message),
        h('a', { href: '#/servicios', class: 'boton primario' }, 'Ver precio y activarlo')));
    } else if (e.status !== 401) {
      vaciar(contenido, h('div', { class: 'aviso error' }, e.message));
      toast(e.message, 'error');
    }
  }
}

window.addEventListener('hashchange', enrutar);
enrutar();
