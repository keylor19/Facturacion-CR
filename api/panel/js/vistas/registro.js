// Autoservicio: crear la cuenta (Google, Microsoft o correo), confirmar el correo e inscribir la empresa.
import { api, sesion } from '../api.js';
import { h, vaciar, campo, opciones, conBoton, toast, aviso } from '../dom.js';
import { selectorUbicacion } from '../ubicacion.js';
import { TIPOS_IDENTIFICACION } from '../catalogos.js';

const NOMBRE_PROVEEDOR = { google: 'Google', microsoft: 'Microsoft' };
const ERRORES_OAUTH = {
  cancelado: 'Se canceló el ingreso.',
  estado: 'El ingreso venció o no se completó en este navegador. Intente de nuevo.',
  vencido: 'El ingreso tardó demasiado. Intente de nuevo.',
  proveedor: 'No pudimos comunicarnos con Google o Microsoft. Intente de nuevo en unos minutos.',
  correo: 'Su cuenta no tiene un correo verificado.',
  administrador: 'Los administradores del servicio entran con su contraseña y la verificación en dos pasos.',
  inactivo: 'Este usuario está desactivado. Hable con el dueño de su empresa.',
  cerrado: 'La inscripción en línea está cerrada.',
  no_disponible: 'Esa forma de ingreso todavía no está activada. Ingrese o cree su cuenta con correo y contraseña.',
};

const pantalla = (titulo, lema, ...contenido) => h('div', { class: 'login' }, h('div', { class: 'login-panel registro' },
  h('section', { class: 'login-presentacion' },
    h('div', { class: 'login-marca' }, h('img', { src: 'img/icono.svg', alt: '' }), h('span', {}, 'Facturación Electrónica CR')),
    h('h2', {}, titulo), h('p', { class: 'login-lema' }, lema)),
  h('div', { class: 'registro-formulario' }, ...contenido)));

// Botones «Continuar con Google / Microsoft» (solo los configurados)
// Logos oficiales simplificados (SVG creado con el DOM: el CSP no permite estilos en línea)
function logo(proveedor) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'logo-proveedor');
  svg.setAttribute('aria-hidden', 'true');
  const figuras = proveedor === 'google' ? [
    ['path', { d: 'M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 01-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z', fill: '#4285F4' }],
    ['path', { d: 'M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0012 24z', fill: '#34A853' }],
    ['path', { d: 'M5.3 14.3a7.2 7.2 0 010-4.6V6.6H1.3a12 12 0 000 10.8l4-3.1z', fill: '#FBBC05' }],
    ['path', { d: 'M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 001.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z', fill: '#EA4335' }],
  ] : [
    ['rect', { x: '1', y: '1', width: '10', height: '10', fill: '#F25022' }],
    ['rect', { x: '13', y: '1', width: '10', height: '10', fill: '#7FBA00' }],
    ['rect', { x: '1', y: '13', width: '10', height: '10', fill: '#00A4EF' }],
    ['rect', { x: '13', y: '13', width: '10', height: '10', fill: '#FFB900' }],
  ];
  for (const [tag, attrs] of figuras) {
    const el = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    svg.append(el);
  }
  return svg;
}

// Botones «Continuar con Google / Microsoft»: siempre visibles. Si todavía no están activados en el
// servidor, al tocarlos se explica (en vez de esconderlos). Sirven para entrar y para crear la cuenta.
export function botonesProveedores(tipo = () => 'empresa', separador = 'o con su correo') {
  return h('div', { class: 'proveedores' }, ['google', 'microsoft'].map((p) => h('button', {
    type: 'button', class: `proveedor ${p}`,
    onclick: () => {
      const t = tipo();
      if (t) location.href = `/api/v1/auth/oauth/${p}/inicio?tipo=${t}`;
    },
  }, logo(p), `Continuar con ${NOMBRE_PROVEEDOR[p]}`)), separador ? h('p', { class: 'separador' }, separador) : null);
}

export function vistaRegistro() {
  const info = h('p', { class: 'suave' }, 'Cargando…');
  const tipoEmpresa = h('input', { type: 'radio', name: 'tipo', value: 'empresa', checked: true });
  const tipoContador = h('input', { type: 'radio', name: 'tipo', value: 'contador' });
  const tipo = () => (tipoContador.checked ? 'contador' : 'empresa');
  const nombre = h('input', { type: 'text', maxlength: '100', required: true, autocomplete: 'name' });
  const correo = h('input', { type: 'email', required: true, autocomplete: 'email' });
  const password = h('input', { type: 'password', minlength: '10', required: true, autocomplete: 'new-password' });
  const acepto = h('input', { type: 'checkbox', required: true });
  const trampa = h('input', { type: 'text', name: 'sitio_web', tabindex: '-1', autocomplete: 'off' });
  const proveedores = h('div');
  const conCorreo = h('div');
  const mensaje = h('div');
  const boton = h('button', { type: 'submit', class: 'primario' }, 'Crear mi cuenta');

  const form = h('form', { onsubmit: async (e) => {
    e.preventDefault();
    boton.disabled = true;
    vaciar(mensaje);
    try {
      const r = await api('/registro', { method: 'POST', conEmisor: false, redirigir401: false, body: {
        tipo: tipo(), nombre: nombre.value.trim(), correo: correo.value.trim(), password: password.value,
        acepto_terminos: acepto.checked, sitio_web: trampa.value,
      } });
      vaciar(form, h('div', { class: 'aviso ok' }, `Listo. Le enviamos un correo a ${r.correo} con el enlace para activar su cuenta `
        + '(vence en 48 horas). Revise también el correo no deseado.'), h('p', {}, h('a', { href: '#/login' }, 'Ir a ingresar')));
    } catch (err) {
      vaciar(mensaje, h('div', { class: 'aviso error' }, err.message));
      boton.disabled = false;
    }
  } },
  h('h1', {}, 'Crear cuenta'), info,
  h('div', { class: 'modalidades' },
    h('label', { class: 'opcion-modalidad' }, tipoEmpresa, h('strong', {}, 'Voy a facturar'),
      h('span', { class: 'suave' }, 'Inscribo mi empresa, mis usuarios y compro mis documentos.')),
    h('label', { class: 'opcion-modalidad' }, tipoContador, h('strong', {}, 'Soy contador'),
      h('span', { class: 'suave' }, 'Llevo la contabilidad de mis clientes.'))),
  h('label', { class: 'check' }, acepto, 'Acepto los ', h('a', { href: 'legal/terminos.html', target: '_blank', rel: 'noopener' }, 'términos del servicio'),
    ' y la ', h('a', { href: 'legal/privacidad.html', target: '_blank', rel: 'noopener' }, 'política de privacidad')),
  proveedores,
  conCorreo,
  h('label', { class: 'trampa', 'aria-hidden': 'true' }, 'No llenar', trampa),
  mensaje,
  h('p', {}, '¿Ya tiene cuenta? ', h('a', { href: '#/login' }, 'Ingresar')));

  api('/registro', { conEmisor: false, redirigir401: false }).then((r) => {
    if (!r.disponible) {
      vaciar(form, h('h1', {}, 'Crear cuenta'), aviso(`La inscripción en línea no está abierta. ${r.contacto_ventas ? `Escríbanos: ${r.contacto_ventas}` : ''}`, 'info'),
        h('p', {}, h('a', { href: '#/login' }, 'Volver')));
      return;
    }
    info.textContent = `Si va a facturar, incluye ${r.prueba_documentos} documentos gratis${r.prueba_dias ? ` y ${r.prueba_dias} días del sistema en línea` : ''}.`;
    // Google / Microsoft: hay que aceptar los términos antes de continuar
    vaciar(proveedores, botonesProveedores(() => {
      if (!acepto.checked) { toast('Primero acepte los términos del servicio', 'error'); return null; }
      return tipo();
    }, 'o cree su cuenta con correo y contraseña'));
    vaciar(conCorreo, h('div', { class: 'campos' }, campo('Su nombre', nombre), campo('Correo', correo), campo('Contraseña (mínimo 10)', password)), boton);
  }).catch(() => { info.textContent = ''; });
  return pantalla('Pruebe gratis', 'Cree su cuenta en un minuto: con Google, con Microsoft o con su correo.', form);
}

export function vistaConfirmar(token) {
  const cuerpo = h('div', {}, h('h1', {}, 'Activando su cuenta…'));
  api('/registro/confirmar', { method: 'POST', body: { token }, conEmisor: false, redirigir401: false })
    .then((r) => vaciar(cuerpo, h('h1', {}, '¡Cuenta activada!'),
      h('div', { class: 'aviso ok' }, `Ya puede ingresar con ${r.correo}.`),
      h('a', { href: '#/login', class: 'boton primario' }, 'Ingresar')))
    .catch((e) => vaciar(cuerpo, h('h1', {}, 'No se pudo activar'), h('div', { class: 'aviso error' }, e.message),
      h('a', { href: '#/login', class: 'boton' }, 'Ir a ingresar')));
  return pantalla('Bienvenido', 'Un paso más y empieza a facturar.', cuerpo);
}

// Vuelta de Google / Microsoft: guarda la sesión y borra el token de la barra de direcciones
export function recibirOauth(token) {
  sesion.token = token;
  history.replaceState(null, '', `${location.pathname}#/tablero`);
}

export function vistaErrorOauth(codigo) {
  const pendiente = codigo === 'no_disponible';
  return pantalla(pendiente ? 'Google y Microsoft, muy pronto' : 'Ingresar con Google o Microsoft',
    pendiente ? 'El administrador del servicio todavía está activando esta forma de ingreso.' : 'No se completó el ingreso con su cuenta.',
    h('div', {}, h('h1', {}, pendiente ? 'Todavía no está activado' : 'No se pudo ingresar'),
      aviso(ERRORES_OAUTH[codigo] || 'Ocurrió un problema al ingresar. Intente de nuevo.', pendiente ? 'info' : 'error'),
      h('div', { class: 'acciones' },
        h('a', { href: '#/login', class: 'boton primario' }, 'Ingresar con correo y contraseña'),
        h('a', { href: '#/registro', class: 'boton' }, 'Crear cuenta'))));
}

// Cuenta nueva sin empresa: inscribe la suya con todos sus datos
export function vistaInscribirEmpresa(salir) {
  const tipo = h('select', {}, opciones(TIPOS_IDENTIFICACION, '02'));
  const cedula = h('input', { type: 'text', inputmode: 'numeric', maxlength: '14', placeholder: 'Sin guiones' });
  const nombre = h('input', { type: 'text', maxlength: '100', readonly: true, placeholder: 'Se llena con los datos de Hacienda' });
  const comercial = h('input', { type: 'text', maxlength: '80', placeholder: 'Opcional' });
  const actividad = h('select', {}, h('option', { value: '' }, 'Busque la cédula primero'));
  const correo = h('input', { type: 'email', placeholder: 'facturas@suempresa.cr' });
  const telefono = h('input', { type: 'tel', maxlength: '20', placeholder: '88887777' });
  const lugar = selectorUbicacion();
  const senas = h('input', { type: 'text', maxlength: '250', placeholder: 'Del parque 100 m norte' });
  const estado = h('div');
  const buscar = h('button', { type: 'button', onclick: () => conBoton(buscar, async () => {
    vaciar(estado);
    const r = await api(`/hacienda/contribuyentes/${cedula.value.replace(/\D/g, '')}`, { conEmisor: false });
    const inscrito = (r.situacion?.estado || '').toLowerCase() === 'inscrito';
    const activas = (r.actividades || []).filter((a) => a.estado === 'A' || !a.estado);
    nombre.value = r.nombre || '';
    if (r.tipoIdentificacion) tipo.value = r.tipoIdentificacion;
    vaciar(actividad, activas.map((a) => h('option', { value: String(a.codigo).padStart(6, '0'), selected: a.tipo === 'P' },
      `${String(a.codigo).padStart(6, '0')} · ${a.descripcion}`)));
    vaciar(estado, inscrito && activas.length ? aviso(`${r.nombre}: inscrito en Hacienda.`, 'ok')
      : aviso('Para facturar electrónicamente la empresa debe estar inscrita en Hacienda con una actividad activa.', 'error'));
  }).catch((e) => vaciar(estado, aviso(e.status === 404 ? 'Esa cédula no aparece en Hacienda.' : e.message, 'error'))) }, 'Buscar en Hacienda');
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    await api('/registro/empresa', { method: 'POST', conEmisor: false, body: {
      tipo_identificacion: tipo.value, numero_identificacion: cedula.value.replace(/\D/g, ''), nombre: nombre.value.trim() || 'Empresa',
      nombre_comercial: comercial.value.trim() || null, codigo_actividad: actividad.value, correo: correo.value.trim(),
      telefono: telefono.value.replace(/\D/g, '') || null, provincia: lugar.provincia.value, canton: lugar.canton.value,
      distrito: lugar.distrito.value, otras_senas: senas.value.trim(),
    } });
    toast('Empresa inscrita. ¡Bienvenido!', 'ok');
    location.hash = '#/bienvenida';
  }) }, 'Inscribir mi empresa');
  return pantalla('Su empresa', 'Inscriba la empresa con la que va a facturar. Después sube la llave de Hacienda, agrega a quienes facturan con usted y compra su paquete.',
    h('div', {}, h('h1', {}, 'Inscribir mi empresa'),
      h('div', { class: 'campos' }, h('div', { class: 'fila doble' }, campo('Cédula de la empresa', cedula), buscar),
        campo('Tipo de identificación', tipo), campo('Nombre o razón social', nombre), campo('Nombre comercial', comercial),
        campo('Actividad económica', actividad), campo('Correo de la empresa', correo), campo('Teléfono', telefono)),
      estado,
      h('h3', {}, 'Dirección'),
      h('div', { class: 'campos' }, campo('Provincia', lugar.provincia), campo('Cantón', lugar.canton), campo('Distrito', lugar.distrito),
        campo('Otras señas', senas)),
      h('div', { class: 'acciones' }, guardar, h('button', { type: 'button', onclick: salir }, 'Salir'))));
}
