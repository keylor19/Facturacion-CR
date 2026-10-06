import { api } from '../api.js';
import { h, vaciar, fecha, tabla, aviso, toast } from '../dom.js';
import { contexto } from '../app.js';

const ACCIONES = [
  ['', 'Todas'],
  ['login', 'Inicios de sesión'],
  ['emisor.', 'Empresas, certificados y credenciales'],
  ['llave.', 'Llaves de API'],
  ['usuario.', 'Usuarios'],
  ['paquete.', 'Ventas de paquetes'],
  ['plan.', 'Planes'],
  ['cabys.', 'Catálogo CABYS'],
];

export async function vistaAuditoria(cont, filtro = '') {
  if (!contexto.esAdmin) { vaciar(cont, aviso('Esta sección es solo para administradores.', 'alerta')); return; }
  const [registros, empresas] = await Promise.all([
    api(`/admin/auditoria?limite=500${filtro ? `&accion=${encodeURIComponent(filtro)}` : ''}`, { conEmisor: false }),
    api('/emisores', { conEmisor: false }),
  ]);
  const nombreEmpresa = Object.fromEntries(empresas.map((e) => [e.id, e.nombre]));
  const selector = h('select', {
    'aria-label': 'Tipo de acción',
    onchange: () => vistaAuditoria(cont, selector.value).catch((e) => toast(e.message, 'error')),
  }, ACCIONES.map(([v, t]) => h('option', { value: v, selected: v === filtro }, t)));

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Bitácora'), selector),
    h('p', { class: 'suave' }, 'Acciones sensibles: quién las hizo, cuándo y desde qué dirección IP. Se muestran las 500 más recientes.'),
    h('section', { class: 'tarjeta' }, registros.length ? tabla([
      { titulo: 'Fecha', valor: (a) => fecha(a.fecha) },
      { titulo: 'Acción', valor: (a) => h('code', {}, a.accion) },
      { titulo: 'Quién', valor: (a) => a.actor },
      { titulo: 'Empresa', valor: (a) => (a.emisor_id ? nombreEmpresa[a.emisor_id] || '—' : '') },
      { titulo: 'Detalle', valor: (a) => a.detalle || '' },
      { titulo: 'IP', valor: (a) => a.ip || '' },
    ], registros) : aviso('No hay registros.', 'info')));
}
