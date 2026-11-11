// Primeros pasos de una empresa nueva: llave criptográfica, usuario de Hacienda, datos, logo,
// productos y primera factura. Cada paso se marca solo cuando ya está hecho.
import { api } from '../api.js';
import { h, vaciar, conBoton, toast, campo, aviso } from '../dom.js';
import { puede } from '../app.js';

const ENLACE_PASO = {
  datos: ['#/configuracion/cuenta', 'Revisar datos'],
  logo: ['#/configuracion/cuenta', 'Agregar logo'],
  productos: ['#/productos', 'Registrar productos'],
  usuarios: ['#/usuarios', 'Agregar usuarios'],
  compra: ['#/saldo', 'Comprar documentos'],
  factura: ['#/factura-rapida', 'Hacer una factura'],
};

function formularioCertificado(alTerminar) {
  const archivo = h('input', { type: 'file', accept: '.p12,.pfx,application/x-pkcs12' });
  const pin = h('input', { type: 'password', autocomplete: 'off', maxlength: '20', placeholder: 'PIN de 4 dígitos' });
  const subir = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(subir, async () => {
    if (!archivo.files[0] || !pin.value) { toast('Seleccione el archivo .p12 e indique el PIN', 'error'); return; }
    const form = new FormData();
    form.append('archivo', archivo.files[0]);
    form.append('password', pin.value);
    const r = await api('/empresa/certificado', { method: 'PUT', form });
    pin.value = '';
    toast(['Llave criptográfica guardada', ...(r.advertencias || [])].join('\n'), r.advertencias?.length ? '' : 'ok');
    alTerminar();
  }) }, 'Guardar llave');
  return h('div', { class: 'campos' }, campo('Archivo .p12', archivo), campo('PIN', pin), h('div', {}, subir));
}

function formularioCredenciales(alTerminar) {
  const usuario = h('input', { type: 'text', maxlength: '100', autocomplete: 'off', placeholder: 'cpf-01-0123-0456@stag.comprobanteselectronicos.go.cr' });
  const clave = h('input', { type: 'password', autocomplete: 'new-password', maxlength: '200' });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    if (!usuario.value.trim() || !clave.value) { toast('Indique el usuario y la contraseña', 'error'); return; }
    await api('/empresa/credenciales-hacienda', { method: 'PUT', body: { usuario: usuario.value.trim(), password: clave.value } });
    clave.value = '';
    toast('Usuario de Hacienda guardado', 'ok');
    alTerminar();
  }) }, 'Guardar usuario');
  return h('div', { class: 'campos' }, campo('Usuario', usuario), campo('Contraseña', clave), h('div', {}, guardar));
}

export async function vistaBienvenida(cont) {
  const refrescar = () => vistaBienvenida(cont).catch((e) => toast(e.message, 'error'));
  const p = await api('/empresa/arranque');
  const resultado = h('div');
  const probar = h('button', { type: 'button', onclick: () => conBoton(probar, async () => {
    const r = await api('/empresa/probar-conexion', { method: 'POST' });
    vaciar(resultado, r.ok
      ? aviso('Conexión correcta: Hacienda aceptó el usuario y la llave criptográfica está vigente.', 'ok')
      : aviso(`Revise: Hacienda → ${r.hacienda}; llave → ${r.certificado}`, 'error'));
  }) }, 'Probar conexión con Hacienda');

  const configurar = puede('configuracion');
  const tarjeta = (paso, i) => {
    let accion = null;
    if (!paso.hecho && configurar && paso.clave === 'certificado') accion = formularioCertificado(refrescar);
    else if (!paso.hecho && configurar && paso.clave === 'credenciales') accion = formularioCredenciales(refrescar);
    else if (ENLACE_PASO[paso.clave]) accion = h('a', { href: ENLACE_PASO[paso.clave][0], class: `boton ${paso.hecho ? '' : 'primario'}` }, ENLACE_PASO[paso.clave][1]);
    return h('section', { class: `tarjeta paso-arranque ${paso.hecho ? 'hecho' : ''}` },
      h('h2', {}, h('span', { class: 'numero-paso' }, paso.hecho ? '✓' : String(i + 1)), paso.titulo,
        paso.obligatorio && !paso.hecho ? h('span', { class: 'badge CONTINGENCIA' }, 'Necesario') : null),
      h('p', { class: 'suave' }, paso.detalle),
      accion);
  };

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('div', {}, h('h1', {}, 'Primeros pasos'),
      h('p', { class: 'suave' }, `${p.hechos} de ${p.total} listos${p.ambiente === 'stag' ? ' · ambiente de pruebas' : ''}`)),
      h('a', { href: '#/tablero', class: 'boton' }, 'Ir al inicio')),
    p.listo_para_facturar
      ? aviso('Ya puede facturar. Los demás pasos son recomendados.', 'ok')
      : aviso('Para emitir comprobantes faltan la llave criptográfica y el usuario de Hacienda. Ambos se sacan en TRIBU-CR, '
        + 'en Comprobantes electrónicos.', 'info'),
    configurar ? null : aviso('Solo el dueño de la empresa puede subir la llave y el usuario de Hacienda.', 'info'),
    p.pasos.map(tarjeta),
    p.pasos.slice(0, 2).every((x) => x.hecho) && configurar ? h('section', { class: 'tarjeta' }, probar, resultado) : null);
}
