import { api, sesion } from '../api.js';
import { h, vaciar } from '../dom.js';
import { cargarContexto, contexto } from '../app.js';

export function vistaLogin() {
  const email = h('input', { type: 'email', name: 'email', autocomplete: 'username', required: true });
  const password = h('input', { type: 'password', name: 'password', autocomplete: 'current-password', required: true });
  const codigo = h('input', {
    type: 'text', name: 'codigo', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '6', pattern: '[0-9]{6}',
  });
  const campoCodigo = h('label', { hidden: true }, 'Código de la app autenticadora', codigo);
  const mensaje = h('div');
  const boton = h('button', { type: 'submit', class: 'primario' }, 'Ingresar');

  const form = h('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      boton.disabled = true;
      vaciar(mensaje);
      try {
        const body = { email: email.value, password: password.value };
        if (!campoCodigo.hidden && codigo.value) body.codigo = codigo.value.trim();
        const r = await api('/auth/login', { method: 'POST', body, conEmisor: false, redirigir401: false });
        sesion.token = r.token;
        await cargarContexto();
        location.hash = contexto.debeActivar2fa ? '#/cuenta' : '#/tablero';
      } catch (err) {
        if (err.headers?.get('X-Requiere-2FA') === 'codigo') {
          // Contraseña correcta: falta el código de 6 dígitos (o el ingresado no sirvió)
          const yaPedido = !campoCodigo.hidden;
          campoCodigo.hidden = false;
          email.readOnly = true;
          password.readOnly = true;
          codigo.value = '';
          codigo.required = true;
          codigo.focus();
          vaciar(mensaje, h('div', { class: `aviso ${yaPedido ? 'error' : 'info'}` }, err.message));
        } else {
          vaciar(mensaje, h('div', { class: 'aviso error' }, err.message));
          password.value = '';
        }
      } finally {
        boton.disabled = false;
      }
    },
  },
  h('div', { class: 'marca-login' }, h('img', { src: 'img/icono.svg', alt: '' })),
  h('h1', {}, 'Facturación Electrónica'),
  h('label', {}, 'Correo', email),
  h('label', {}, 'Contraseña', password),
  campoCodigo,
  mensaje,
  boton);

  return h('div', { class: 'login' }, form);
}
