import { api } from '../api.js';
import { h, vaciar, fecha, tabla, modal, conBoton, toast, campo, aviso } from '../dom.js';
import { contexto } from '../app.js';

export async function vistaUsuarios(cont) {
  if (!contexto.esAdmin) { vaciar(cont, aviso('Esta sección es solo para administradores.', 'alerta')); return; }
  const [usuarios, empresas] = await Promise.all([
    api('/usuarios', { conEmisor: false }), api('/emisores', { conEmisor: false }),
  ]);
  const nombreEmpresa = Object.fromEntries(empresas.map((e) => [e.id, e.nombre]));
  const refrescar = () => vistaUsuarios(cont).catch((e) => toast(e.message, 'error'));

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Usuarios'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoNuevo(empresas, refrescar) }, '+ Nuevo usuario')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Nombre', valor: (u) => [u.nombre, h('div', { class: 'suave' }, u.email)] },
      { titulo: 'Acceso', valor: (u) => (u.es_admin ? 'Administrador (todas las empresas)' : nombreEmpresa[u.emisor_id] || '—') },
      { titulo: 'Último ingreso', valor: (u) => fecha(u.ultimo_login) || 'Nunca' },
      { titulo: 'Estado', valor: (u) => (u.activo ? 'Activo' : h('span', { class: 'badge RECHAZADO' }, 'Inactivo')) },
      { titulo: '', valor: (u) => h('div', { class: 'acciones' },
        h('button', { type: 'button', class: 'chico', onclick: () => dialogoPassword(u) }, 'Cambiar contraseña'),
        u.id === contexto.usuario?.id ? null : h('button', { type: 'button', class: `chico ${u.activo ? 'peligro' : ''}`, onclick: (ev) => conBoton(ev.target, async () => {
          await api(`/usuarios/${u.id}`, { method: 'PATCH', body: { activo: !u.activo }, conEmisor: false });
          refrescar();
        }) }, u.activo ? 'Desactivar' : 'Activar')) },
    ], usuarios)));
}

function dialogoNuevo(empresas, alTerminar) {
  const email = h('input', { type: 'email' });
  const nombre = h('input', { type: 'text', maxlength: '100' });
  const password = h('input', { type: 'password', autocomplete: 'new-password', minlength: '10' });
  const acceso = h('select', {}, h('option', { value: '' }, 'Administrador (todas las empresas)'),
    empresas.map((e) => h('option', { value: e.id }, `Solo ${e.nombre}`)));
  const crear = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(crear, async () => {
    await api('/usuarios', {
      method: 'POST', conEmisor: false,
      body: { email: email.value.trim(), nombre: nombre.value.trim(), password: password.value, es_admin: !acceso.value, emisor_id: acceso.value || null },
    });
    m.cerrar();
    toast('Usuario creado', 'ok');
    alTerminar();
  }) }, 'Crear');
  const m = modal('Nuevo usuario', [
    h('div', { class: 'campos' }, campo('Correo', email), campo('Nombre', nombre),
      campo('Contraseña inicial (mínimo 10)', password), campo('Acceso', acceso)),
  ], { acciones: [crear] });
}

function dialogoPassword(u) {
  const password = h('input', { type: 'password', autocomplete: 'new-password', minlength: '10' });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    await api(`/usuarios/${u.id}`, { method: 'PATCH', body: { password: password.value }, conEmisor: false });
    m.cerrar();
    toast('Contraseña actualizada; se cerraron sus sesiones', 'ok');
  }) }, 'Guardar');
  const m = modal(`Contraseña de ${u.nombre}`, [campo('Nueva contraseña (mínimo 10)', password)], { acciones: [guardar] });
}
