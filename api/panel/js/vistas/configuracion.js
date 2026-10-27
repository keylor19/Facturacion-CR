// Configuración de la empresa activa: información de la cuenta y actividades económicas.
// Los cambios a los datos fiscales los hace el administrador (Empresas), porque
// afectan la firma y el envío a Hacienda.
import { api } from '../api.js';
import { h, vaciar, fecha, tabla, aviso, avisoContribuyente, avisoNoInscrito } from '../dom.js';
import { TIPOS_IDENTIFICACION } from '../catalogos.js';
import { UBICACIONES } from '../datos-ubicaciones.js';
import { contexto, empresaActual } from '../app.js';

function lugar(e) {
  const prov = UBICACIONES[e.provincia];
  const canton = prov?.[1][e.canton];
  return [prov?.[0], canton?.[0], canton?.[1][e.distrito]].filter(Boolean).join(', ');
}

function enlaceEdicion(e, texto) {
  return contexto.esAdmin
    ? h('a', { href: `#/empresas/${e.id}`, class: 'boton primario' }, texto)
    : null;
}

const notaCambios = () => (contexto.esAdmin ? null
  : h('p', { class: 'suave' }, 'Para cambiar estos datos, el certificado o las credenciales de Hacienda, contacte a su proveedor del sistema.'));

export async function vistaInformacionCuenta(cont) {
  const e = empresaActual();
  const vence = e.cert_vence ? Math.floor((new Date(e.cert_vence) - new Date()) / 86400000) : null;
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Información de la cuenta'), enlaceEdicion(e, 'Editar empresa')),
    h('div', { class: 'campos dos' },
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Datos del emisor'),
        h('dl', { class: 'datos' },
          h('dt', {}, 'Nombre o razón social'), h('dd', {}, e.nombre),
          e.nombre_comercial ? [h('dt', {}, 'Nombre comercial'), h('dd', {}, e.nombre_comercial)] : null,
          h('dt', {}, 'Identificación'), h('dd', {}, `${TIPOS_IDENTIFICACION[e.tipo_identificacion] || ''} ${e.numero_identificacion}`),
          h('dt', {}, 'Actividad económica'), h('dd', {}, h('a', { href: '#/configuracion/actividad' }, e.codigo_actividad || '—')),
          h('dt', {}, 'Correo'), h('dd', {}, e.correo || '—'),
          h('dt', {}, 'Teléfono'), h('dd', {}, e.telefono || '—'),
          h('dt', {}, 'Ubicación'), h('dd', {}, [lugar(e), e.otras_senas].filter(Boolean).join(' · ') || '—'))),
      h('section', { class: 'tarjeta' }, h('h2', {}, 'Estado del servicio'),
        h('dl', { class: 'datos' },
          h('dt', {}, 'Ambiente'), h('dd', {}, h('span', { class: `badge ${e.ambiente}` }, e.ambiente === 'prod' ? 'Producción' : 'Pruebas')),
          h('dt', {}, 'Certificado digital'), h('dd', {}, e.tiene_certificado
            ? h('span', { class: `badge ${vence !== null && vence < 30 ? 'CONTINGENCIA' : 'ACEPTADO'}` },
              e.cert_vence ? `Vence ${fecha(e.cert_vence, false)}` : 'Cargado')
            : h('span', { class: 'badge RECHAZADO' }, 'No cargado')),
          h('dt', {}, 'Facturación en línea'), h('dd', {}, e.facturacion_web !== false ? 'Activa' : 'No contratada'),
          h('dt', {}, 'Logo en el PDF'), h('dd', {}, e.tiene_logo ? 'Sí' : 'No'),
          contexto.controlSaldo && e.saldo_documentos !== null && e.saldo_documentos !== undefined
            ? [h('dt', {}, 'Documentos disponibles'), h('dd', {}, h('a', { href: '#/saldo' }, e.saldo_documentos.toLocaleString('es-CR')))]
            : null))),
    notaCambios());
}

export async function vistaActividadEconomica(cont) {
  const e = empresaActual();
  const info = h('div', {}, h('p', { class: 'cargando' }, 'Consultando Hacienda…'));
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Actividad económica'), enlaceEdicion(e, 'Cambiar actividad')),
    h('section', { class: 'tarjeta' },
      h('p', {}, 'Actividad que se usa al emitir: ', h('strong', { class: 'mono' }, e.codigo_actividad || '—')),
      h('p', { class: 'suave' }, 'Si la empresa tiene varias actividades inscritas, puede indicar otra en cada comprobante enviado por API.')),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Actividades inscritas en Hacienda'), info),
    notaCambios());

  let c;
  try {
    c = await api(`/hacienda/contribuyentes/${e.numero_identificacion}`);
  } catch (err) {
    vaciar(info, err.status === 404 ? avisoNoInscrito(e.numero_identificacion) : aviso(err.message, 'error'));
    return;
  }
  const actividades = c.actividades || [];
  const activas = actividades.filter((a) => a.estado === 'A' || !a.estado);
  const codigo = (a) => String(a.codigo).padStart(6, '0');
  vaciar(info,
    avisoContribuyente(c, activas),
    e.codigo_actividad && !activas.some((a) => codigo(a) === e.codigo_actividad)
      ? aviso(`La actividad configurada (${e.codigo_actividad}) no aparece activa en Hacienda; los comprobantes podrían ser rechazados.`, 'alerta')
      : null,
    tabla([
      { titulo: 'Código', valor: (a) => h('span', { class: 'mono' }, codigo(a)) },
      { titulo: 'Descripción', valor: (a) => a.descripcion },
      { titulo: 'Tipo', valor: (a) => (a.tipo === 'P' ? 'Principal' : 'Secundaria') },
      { titulo: 'Estado', valor: (a) => (a.estado === 'A' || !a.estado ? h('span', { class: 'badge ACEPTADO' }, 'Activa') : h('span', { class: 'badge RECHAZADO' }, 'Inactiva')) },
      { titulo: '', valor: (a) => (codigo(a) === e.codigo_actividad ? h('span', { class: 'badge prod' }, 'En uso') : null) },
    ], actividades));
}
