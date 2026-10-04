import { api, sesion } from '../api.js';
import { h, vaciar, conBoton, toast, campo, aviso } from '../dom.js';
import { contexto, enrutar } from '../app.js';

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
    contexto.debeActivar2fa
      ? aviso('Por seguridad, los administradores deben activar la verificación en dos pasos antes de usar el panel.', 'alerta')
      : null,
    h('section', { class: 'tarjeta' },
      h('dl', { class: 'datos' }, h('dt', {}, 'Nombre'), h('dd', {}, u.nombre), h('dt', {}, 'Correo'), h('dd', {}, u.email),
        h('dt', {}, 'Acceso'), h('dd', {}, u.es_admin ? 'Administrador' : 'Una empresa'))),
    seccionDosPasos(u),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Cambiar contraseña'),
      h('div', { class: 'campos' }, campo('Contraseña actual', actual), campo('Nueva (mínimo 10)', nueva), campo('Repetir nueva', repetir)),
      h('div', { class: 'acciones' }, guardar)));
}

function inputCodigo() {
  return h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '6', pattern: '[0-9]{6}' });
}

function seccionDosPasos(u) {
  const seccion = h('section', { class: 'tarjeta' });
  const titulo = h('h2', {}, 'Verificación en dos pasos');

  if (u.dos_pasos) {
    const password = h('input', { type: 'password', autocomplete: 'current-password' });
    const codigo = inputCodigo();
    const quitar = h('button', { type: 'button', class: 'peligro', onclick: () => conBoton(quitar, async () => {
      await api('/auth/2fa/desactivar', { method: 'POST', body: { password: password.value, codigo: codigo.value.trim() }, conEmisor: false, redirigir401: false });
      toast('Verificación en dos pasos desactivada', 'ok');
      enrutar();
    }) }, 'Desactivar');
    return vaciar(seccion, titulo,
      h('p', {}, h('span', { class: 'badge ACEPTADO' }, 'Activa'),
        ' Cada inicio de sesión pide el código de 6 dígitos de su app autenticadora.'),
      u.es_admin ? h('p', { class: 'suave' }, 'Si pierde el teléfono, otro administrador puede reiniciarla desde Usuarios.') : h('div', { class: 'campos' },
        campo('Contraseña', password), campo('Código actual', codigo)),
      u.es_admin ? null : h('div', { class: 'acciones' }, quitar));
  }

  const comenzar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(comenzar, async () => {
    const r = await api('/auth/2fa/iniciar', { method: 'POST', conEmisor: false });
    const urlQr = URL.createObjectURL(new Blob([r.qr_svg], { type: 'image/svg+xml' }));
    const codigo = inputCodigo();
    const activar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(activar, async () => {
      await api('/auth/2fa/activar', { method: 'POST', body: { codigo: codigo.value.trim() }, conEmisor: false, redirigir401: false });
      URL.revokeObjectURL(urlQr);
      toast('Verificación en dos pasos activada', 'ok');
      location.hash = '#/tablero';
      enrutar();
    }) }, 'Activar');
    vaciar(seccion, titulo,
      h('ol', {},
        h('li', {}, 'Instale una app autenticadora (Google Authenticator, Microsoft Authenticator, Authy…).'),
        h('li', {}, 'Escanee este código QR con la app:')),
      h('img', { src: urlQr, alt: 'Código QR para la app autenticadora', width: '220', height: '220', class: 'qr' }),
      h('p', { class: 'suave' }, 'Si no puede escanearlo, ingrese esta clave manualmente: ', h('code', {}, r.secreto)),
      h('ol', { start: '3' }, h('li', {}, 'Escriba el código de 6 dígitos que muestra la app:')),
      h('div', { class: 'campos' }, campo('Código', codigo)),
      h('div', { class: 'acciones' }, activar));
    codigo.focus();
  }) }, 'Activar verificación en dos pasos');

  return vaciar(seccion, titulo,
    h('p', {}, 'Agrega un código de su teléfono además de la contraseña. Aunque alguien robe su contraseña, no podrá ingresar.'),
    h('div', { class: 'acciones' }, comenzar));
}
