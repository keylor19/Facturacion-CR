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
import { vistaReportes } from './vistas/reportes.js';
import { vistaConsultas } from './vistas/consultas.js';
import { vistaEmpresas, vistaDetalleEmpresa } from './vistas/empresas.js';
import { vistaUsuarios } from './vistas/usuarios.js';
import { vistaCuenta } from './vistas/cuenta.js';
import { vistaSaldo } from './vistas/saldo.js';
import { vistaPlanes } from './vistas/planes.js';
import { vistaAuditoria } from './vistas/auditoria.js';
import { vistaClientes, vistaCargarClientes, vistaReporteClientes } from './vistas/clientes.js';
import { vistaProductos, vistaCargarProductos, vistaReporteProductos, vistaCombos } from './vistas/productos.js';
import { vistaCategorias, vistaDescuentos } from './vistas/promociones.js';
import { vistaInventario } from './vistas/inventario.js';
import { vistaPagos, vistaComprobantesPago } from './vistas/pagos.js';
import { vistaInformacionCuenta, vistaActividadEconomica } from './vistas/configuracion.js';

export const contexto = {
  usuario: null, esAdmin: false, empresas: [], controlSaldo: false, saldoAlerta: 20, debeActivar2fa: false,
};

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
  [/^#\/pagos$/, vistaPagos, true],
  [/^#\/comprobantes-pago$/, vistaComprobantesPago, true],
  [/^#\/empresas$/, vistaEmpresas, false],
  [/^#\/empresas\/([\w-]+)$/, vistaDetalleEmpresa, false],
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
const MODULO_FACTURACION = /^#\/(emitir|factura-rapida|punto-venta|cajas|proformas?|preliminares|clientes|productos|inventario|pagos|categorias|descuentos|combos)\b/;

// Menú principal: [ruta, texto, solo administradores]
const MENU = [
  { titulo: 'Facturación', icono: 'documento', items: [
    ['#/emitir/01', 'Factura Electrónica'],
    ['#/emitir/04', 'Tiquete Electrónico'],
    ['#/emitir/08', 'Factura Electrónica de Compra'],
    ['#/emitir/09', 'Factura Electrónica de Exportación'],
    ['#/emitir/03', 'Nota de Crédito'],
    ['#/emitir/02', 'Nota de Débito'],
    ['#/proforma/nueva', 'Proforma Electrónica (comprobante provisional)'],
    ['#/factura-rapida', 'Factura Rápida'],
    ['#/punto-venta', 'Punto de Venta'],
    ['#/cajas', 'Cierres de Caja'],
  ] },
  { titulo: 'Documentos', icono: 'documento', items: [
    ['#/comprobantes', 'Documentos Emitidos'],
    ['#/preliminares', 'Documentos Preliminares'],
    ['#/proformas', 'Documentos Proforma (comprobante provisional)'],
    ['#/descargas', 'Descargar Documentos'],
    ['#/reportes', 'Reportes de IVA'],
    ['#/consultas', 'Consultas a Hacienda'],
  ] },
  { titulo: 'Aceptación', icono: 'documento', items: [
    ['#/recepcion', 'Aceptación Documentos'],
  ] },
  { titulo: 'Pagos', icono: 'documento', items: [
    ['#/pagos', 'Administrar Pagos'],
    ['#/comprobantes-pago', 'Comprobantes de Pago'],
  ] },
  { titulo: 'Clientes', icono: 'editar', items: [
    ['#/clientes', 'Mantenimiento'],
    ['#/clientes/cargar', 'Cargar Clientes'],
    ['#/clientes/reporte', 'Reporte Clientes'],
  ] },
  { titulo: 'Productos', icono: 'editar', items: [
    ['#/productos', 'Mantenimiento'],
    ['#/descuentos', 'Descuentos'],
    ['#/productos/cargar', 'Cargar Productos'],
    ['#/productos/reporte', 'Reporte de Productos'],
    ['#/categorias', 'Categorías'],
    ['#/combos', 'Mantenimiento Combos'],
    ['#/inventario', 'Inventario'],
  ] },
  { titulo: 'Configuración', icono: 'editar', items: [
    ['#/configuracion/cuenta', 'Información de la Cuenta'],
    ['#/configuracion/actividad', 'Actividad Económica'],
    ['#/saldo', 'Saldo de Documentos'],
    ['#/cuenta', 'Mi Información de Usuario'],
    ['#/usuarios', 'Mantenimiento de Usuario', true],
  ] },
  { titulo: 'Administración', icono: 'engranaje', admin: true, items: [
    ['#/empresas', 'Empresas'],
    ['#/planes', 'Planes y Ventas'],
    ['#/auditoria', 'Bitácora'],
  ] },
];

// Íconos de línea (SVG creado con el DOM: no requiere estilos ni scripts en línea)
const ICONOS = {
  inicio: 'M3 11l9-8 9 8M5 9.5V21h5v-6h4v6h5V9.5',
  documento: 'M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7',
  editar: 'M4 20h4L19 9l-4-4L4 16zM13 7l4 4M4 4h8',
  engranaje: 'M12 9a3 3 0 100 6 3 3 0 000-6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1',
  usuario: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0',
  flecha: 'M6 9l6 6 6-6',
  menu: 'M4 6h16M4 12h16M4 18h16',
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
  const yo = await api('/auth/yo', { conEmisor: false });
  contexto.usuario = yo.usuario;
  contexto.esAdmin = yo.es_admin;
  contexto.empresas = yo.empresas;
  contexto.controlSaldo = yo.control_saldo;
  contexto.saldoAlerta = yo.saldo_alerta;
  contexto.debeActivar2fa = !!yo.debe_activar_2fa;
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
    emp ? h('span', { class: `badge ${emp.ambiente}` }, emp.ambiente === 'prod' ? 'Producción' : 'Pruebas') : null,
    indicadorSaldo(emp));
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
  const activo = items.some(([href]) => enRuta(ruta, href));
  const boton = h('button', { type: 'button', class: 'menu-boton', 'aria-haspopup': 'true', 'aria-expanded': 'false' },
    icono(iconoNombre), h('span', {}, titulo), icono('flecha', 'icono flecha'));
  const grupo = h('div', { class: `menu-grupo ${activo ? 'activo' : ''} ${clase}` }, boton,
    h('div', { class: 'desplegable', role: 'menu' },
      items.map(([href, texto]) => h('a', { href, role: 'menuitem', class: ruta === href ? 'activo' : '' }, texto))));
  boton.addEventListener('click', () => {
    const abrir = !grupo.classList.contains('abierto');
    cerrarMenus(grupo);
    grupo.classList.toggle('abierto', abrir);
    boton.setAttribute('aria-expanded', String(abrir));
  });
  return grupo;
}

function diseno(ruta) {
  const grupos = MENU
    .filter((g) => !g.admin || contexto.esAdmin)
    .map((g) => ({ ...g, items: g.items.filter(([href, , soloAdmin]) => (!soloAdmin || contexto.esAdmin) && moduloDisponible(href)) }))
    .filter((g) => g.items.length);
  const usuario = contexto.usuario;
  const contenido = h('main', { class: 'contenido' });
  const nav = h('nav', { class: 'menu', 'aria-label': 'Principal' },
    h('a', { href: '#/tablero', class: `menu-inicio ${ruta === '#/tablero' ? 'activo' : ''}`, title: 'Inicio', 'aria-label': 'Inicio' }, icono('inicio')),
    grupos.map((g) => grupoMenu(g.titulo, g.icono, g.items, ruta)));
  const alternar = h('button', { type: 'button', class: 'menu-movil', 'aria-label': 'Menú', 'aria-expanded': 'false', onclick: () => {
    const abierto = nav.classList.toggle('visible');
    alternar.setAttribute('aria-expanded', String(abierto));
  } }, icono('menu'));

  const raiz = h('div', { class: 'layout' },
    h('header', { class: 'cabecera' },
      h('div', { class: 'barra' },
        alternar,
        h('a', { href: '#/tablero', class: 'marca' }, h('img', { src: 'img/icono.svg', alt: '' }), h('span', {}, 'Facturación CR')),
        selectorEmpresa(),
        h('span', { class: 'espacio' }),
        usuario ? grupoMenu(usuario.nombre, 'usuario', [['#/cuenta', 'Mi Información de Usuario']], ruta, 'menu-usuario') : null,
        h('button', { type: 'button', class: 'salir', onclick: salir }, 'Salir')),
      nav),
    contenido);
  return { raiz, contenido };
}

export async function enrutar() {
  const app = document.getElementById('app');
  const ruta = location.hash || '#/tablero';

  if (ruta === '#/login' || !sesion.token) {
    vaciar(app, vistaLogin());
    return;
  }
  // Se recarga en cada navegación para que el saldo y las empresas estén al día
  try { await cargarContexto(); } catch { return; }

  // Administrador sin verificación en dos pasos: solo puede entrar a Mi cuenta para activarla
  if (contexto.debeActivar2fa && ruta !== '#/cuenta') { location.hash = '#/cuenta'; return; }
  const encontrada = RUTAS.find(([re]) => re.test(ruta));
  if (!encontrada) { location.hash = '#/tablero'; return; }
  const [re, vista, requiereEmpresa] = encontrada;
  const { raiz, contenido } = diseno(ruta);
  vaciar(app, raiz);

  if (!moduloDisponible(ruta)) {
    vaciar(contenido, h('div', { class: 'aviso info' },
      'La facturación en línea no está activa para esta empresa. Contacte a su proveedor para activarla.'));
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
    if (e.status !== 401) {
      vaciar(contenido, h('div', { class: 'aviso error' }, e.message));
      toast(e.message, 'error');
    }
  }
}

window.addEventListener('hashchange', enrutar);
enrutar();
