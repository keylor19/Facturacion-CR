// Aplicación principal: sesión, diseño y enrutador por hash.
import { api, sesion } from './api.js';
import { h, vaciar, toast } from './dom.js';
import { vistaLogin } from './vistas/login.js';
import { vistaTablero } from './vistas/tablero.js';
import { vistaComprobantes, vistaDetalleComprobante } from './vistas/comprobantes.js';
import { vistaEmitir } from './vistas/emitir.js';
import { vistaRecepcion } from './vistas/recepcion.js';
import { vistaReportes } from './vistas/reportes.js';
import { vistaConsultas } from './vistas/consultas.js';
import { vistaEmpresas, vistaDetalleEmpresa } from './vistas/empresas.js';
import { vistaUsuarios } from './vistas/usuarios.js';
import { vistaCuenta } from './vistas/cuenta.js';
import { vistaSaldo } from './vistas/saldo.js';
import { vistaPlanes } from './vistas/planes.js';

export const contexto = { usuario: null, esAdmin: false, empresas: [], controlSaldo: false, saldoAlerta: 20 };

const RUTAS = [
  [/^#\/tablero$/, vistaTablero, true],
  [/^#\/comprobantes$/, vistaComprobantes, true],
  [/^#\/comprobantes\/([\w-]+)$/, vistaDetalleComprobante, true],
  [/^#\/emitir$/, vistaEmitir, true],
  [/^#\/recepcion$/, vistaRecepcion, true],
  [/^#\/reportes$/, vistaReportes, true],
  [/^#\/consultas$/, vistaConsultas, false],
  [/^#\/empresas$/, vistaEmpresas, false],
  [/^#\/empresas\/([\w-]+)$/, vistaDetalleEmpresa, false],
  [/^#\/usuarios$/, vistaUsuarios, false],
  [/^#\/cuenta$/, vistaCuenta, false],
  [/^#\/saldo$/, vistaSaldo, true],
  [/^#\/planes$/, vistaPlanes, false],
];

const MENU = [
  ['#/tablero', 'Tablero'],
  ['#/emitir', 'Nuevo comprobante'],
  ['#/comprobantes', 'Comprobantes'],
  ['#/recepcion', 'Facturas de proveedores'],
  ['#/reportes', 'Reportes'],
  ['#/saldo', 'Mi saldo'],
  ['#/consultas', 'Consultas Hacienda'],
];
const MENU_ADMIN = [['#/empresas', 'Empresas'], ['#/planes', 'Planes y ventas'], ['#/usuarios', 'Usuarios']];

export async function cargarContexto() {
  const yo = await api('/auth/yo', { conEmisor: false });
  contexto.usuario = yo.usuario;
  contexto.esAdmin = yo.es_admin;
  contexto.empresas = yo.empresas;
  contexto.controlSaldo = yo.control_saldo;
  contexto.saldoAlerta = yo.saldo_alerta;
  if (!contexto.empresas.some((e) => e.id === sesion.emisorId)) {
    sesion.emisorId = contexto.empresas[0]?.id || null;
  }
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
  return h('div', { class: 'empresa' }, h('strong', {}, 'Empresa:'), sel,
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

function diseno(ruta) {
  const menu = [...MENU, ...(contexto.esAdmin ? MENU_ADMIN : [])];
  const contenido = h('main', { class: 'contenido' });
  const raiz = h('div', { class: 'layout' },
    h('aside', { class: 'lateral' },
      h('div', { class: 'marca' }, h('img', { src: 'img/icono.svg', alt: '' }), 'Facturación CR'),
      h('nav', { 'aria-label': 'Principal' },
        menu.map(([href, texto]) => h('a', { href, class: ruta.startsWith(href) ? 'activo' : '' }, texto)))),
    h('div', { class: 'principal' },
      h('header', { class: 'barra' },
        selectorEmpresa(),
        h('span', { class: 'espacio' }),
        h('span', { class: 'suave' }, contexto.usuario?.nombre || ''),
        h('a', { href: '#/cuenta', class: 'boton' }, 'Mi cuenta'),
        h('button', { type: 'button', onclick: salir }, 'Salir')),
      contenido));
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

  const encontrada = RUTAS.find(([re]) => re.test(ruta));
  if (!encontrada) { location.hash = '#/tablero'; return; }
  const [re, vista, requiereEmpresa] = encontrada;
  const { raiz, contenido } = diseno(ruta);
  vaciar(app, raiz);

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
