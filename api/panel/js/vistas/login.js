// Inicio de sesión del panel, con verificación en dos pasos si el usuario la tiene activa.
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
  h('h1', {}, 'Ingresar'),
  h('p', { class: 'suave' }, 'Use el correo y la contraseña que le entregó su proveedor.'),
  h('label', {}, 'Correo', email),
  h('label', {}, 'Contraseña', password),
  campoCodigo,
  mensaje,
  boton);

  // Presentación del servicio para quien todavía no lo tiene (y el contacto de ventas configurado)
  const contacto = h('p', { class: 'login-contacto' });
  api('/auth/contacto', { conEmisor: false, redirigir401: false })
    .then((r) => { if (r.contacto) vaciar(contacto, h('span', {}, '¿Quiere facturar con nosotros? '), h('strong', {}, r.contacto)); })
    .catch(() => {});
  const ventaja = (titulo, texto) => h('li', {}, h('strong', {}, titulo), h('span', {}, texto));
  const presentacion = h('section', { class: 'login-presentacion' },
    h('div', { class: 'login-marca' }, h('img', { src: 'img/icono.svg', alt: '' }), h('span', {}, 'Facturación Electrónica CR')),
    h('h2', {}, 'Facture ante Hacienda en segundos'),
    h('p', { class: 'login-lema' }, 'Comprobantes electrónicos v4.4 para su empresa: desde su propio sistema o desde el navegador.'),
    h('ul', { class: 'login-ventajas' },
      ventaja('Conexión por API', 'Su POS, ERP, tienda en línea o n8n factura solo. Paga únicamente los documentos que usa.'),
      ventaja('Sistema en línea', 'Facture, maneje clientes, productos, inventario y punto de venta desde cualquier navegador.'),
      ventaja('Al día con Hacienda', 'Códigos de noviembre 2026, CABYS, exoneraciones y facturas de proveedores automáticas.'),
      ventaja('Contabilidad lista', 'Reporte de IVA y libros de ventas y compras para su contador.')),
    contacto);

  return h('div', { class: 'login' }, h('div', { class: 'login-panel' }, presentacion, form));
}
