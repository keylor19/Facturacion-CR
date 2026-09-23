import { api, sesion } from '../api.js';
import { h, vaciar, conBoton, toast, campo, aviso } from '../dom.js';
import { contexto } from '../app.js';

export async function vistaCuenta(cont) {
  const u = contexto.usuario;
  if (!u) { vaciar(cont, aviso('Solo disponible para usuarios del panel.', 'info')); return; }
  const actual = h('input', { type: 'password', autocomplete: 'current-password' });
  const nueva = h('input', { type: 'password', autocomplete: 'new-password', minlength: '10' });
  const repetir = h('input', { type: 'password', autocomplete: 'new-password' });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    if (nueva.value !== repetir.value) { toast('Las contraseñas no coinciden', 'error'); return; }
    await api('/auth/cambiar-password', { method: 'POST', body: { actual: actual.value, nueva: nueva.value }, conEmisor: false, redirigir401: false });
    toast('Contraseña cambiada. Ingrese de nuevo.', 'ok');
    sesion.limpiar();
    location.hash = '#/login';
  }) }, 'Cambiar contraseña');

  vaciar(cont,
    h('h1', {}, 'Mi cuenta'),
    h('section', { class: 'tarjeta' },
      h('dl', { class: 'datos' }, h('dt', {}, 'Nombre'), h('dd', {}, u.nombre), h('dt', {}, 'Correo'), h('dd', {}, u.email),
        h('dt', {}, 'Acceso'), h('dd', {}, u.es_admin ? 'Administrador' : 'Una empresa'))),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Cambiar contraseña'),
      h('div', { class: 'campos' }, campo('Contraseña actual', actual), campo('Nueva (mínimo 10)', nueva), campo('Repetir nueva', repetir)),
      h('div', { class: 'acciones' }, guardar)));
}
