import { api, sesion } from '../api.js';
import { h, vaciar } from '../dom.js';
import { cargarContexto } from '../app.js';

export function vistaLogin() {
  const email = h('input', { type: 'email', name: 'email', autocomplete: 'username', required: true });
  const password = h('input', { type: 'password', name: 'password', autocomplete: 'current-password', required: true });
  const mensaje = h('div');
  const boton = h('button', { type: 'submit', class: 'primario' }, 'Ingresar');

  const form = h('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      boton.disabled = true;
      vaciar(mensaje);
      try {
        const r = await api('/auth/login', {
          method: 'POST', body: { email: email.value, password: password.value }, conEmisor: false, redirigir401: false,
        });
        sesion.token = r.token;
        await cargarContexto();
        location.hash = '#/tablero';
      } catch (err) {
        vaciar(mensaje, h('div', { class: 'aviso error' }, err.message));
        password.value = '';
      } finally {
        boton.disabled = false;
      }
    },
  },
  h('div', { class: 'marca-login' }, h('img', { src: 'img/icono.svg', alt: '' })),
  h('h1', {}, 'Facturación Electrónica'),
  h('label', {}, 'Correo', email),
  h('label', {}, 'Contraseña', password),
  mensaje,
  boton);

  return h('div', { class: 'login' }, form);
}
