// Facturas recurrentes: comprobantes que se emiten solos (alquileres, mensualidades, servicios fijos).
// Se crean desde el formulario de facturar con «Repetir automáticamente».
import { api } from '../api.js';
import { h, vaciar, dinero, tabla, modal, conBoton, toast, campo, opciones, aviso } from '../dom.js';

export const FRECUENCIAS = { semanal: 'Cada semana', quincenal: 'Cada 15 días', mensual: 'Cada mes', anual: 'Cada año' };
const fechaCorta = (iso) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString('es-CR') : '');
const hoyIso = () => new Date().toLocaleDateString('en-CA');

// Total aproximado de la plantilla (precio x cantidad - descuento + IVA), solo para mostrar
function totalAproximado(datos) {
  const TARIFA = { '01': 0, '02': 1, '03': 2, '04': 4, '05': 0, '06': 4, '07': 8, '08': 13, '09': 0.5, '10': 0, '11': 0 };
  return (datos.productos || []).reduce((s, p) => {
    const sub = Number(p.cantidad || 0) * Number(p.precio_unitario || 0) - Number(p.descuento || 0);
    return s + sub * (1 + (TARIFA[p.codigo_tarifa_iva] ?? 13) / 100);
  }, 0);
}

// Crea o edita una recurrente. `datos` es el cuerpo de POST /facturas armado en el formulario de facturar.
export function dialogoRecurrente({ datos, existente = null, alGuardar = () => {} }) {
  const r = existente || {};
  const nombre = h('input', { type: 'text', maxlength: '120', value: r.nombre || '', placeholder: 'Ej.: Alquiler local 3 - Juan Pérez' });
  const frecuencia = h('select', {}, opciones(FRECUENCIAS, r.frecuencia || 'mensual'));
  const proxima = h('input', { type: 'date', min: hoyIso(), value: r.proxima || hoyIso() });
  const hasta = h('input', { type: 'date', value: r.hasta || '' });
  const ayuda = h('p', { class: 'suave' });
  const explicar = () => {
    const dia = Number(proxima.value.slice(8, 10));
    ayuda.textContent = ['mensual', 'anual'].includes(frecuencia.value) && dia > 28
      ? 'Para cada mes o cada año use un día del 1 al 28 (todos los meses lo tienen).'
      : `Se emite sola a las 7:00 a. m. ${FRECUENCIAS[frecuencia.value].toLowerCase()}, desde el ${fechaCorta(proxima.value)}`
        + `${hasta.value ? ` hasta el ${fechaCorta(hasta.value)}` : ', sin fecha final'}. Al cliente le llega por correo como siempre.`;
  };
  [frecuencia, proxima, hasta].forEach((el) => el.addEventListener('change', explicar));
  explicar();
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    if (!nombre.value.trim()) { toast('Póngale un nombre para reconocerla', 'error'); return; }
    const cuerpo = {
      nombre: nombre.value.trim(), datos: datos || r.datos, frecuencia: frecuencia.value,
      proxima: proxima.value, hasta: hasta.value || null, activa: existente ? r.activa : true,
    };
    const guardada = existente
      ? await api(`/recurrentes/${r.id}`, { method: 'PUT', body: cuerpo })
      : await api('/recurrentes', { method: 'POST', body: cuerpo });
    m.cerrar();
    toast(existente ? 'Factura recurrente actualizada' : 'Listo: se emitirá sola en cada fecha', 'ok');
    alGuardar(guardada);
  }) }, existente ? 'Guardar' : 'Programar');
  const m = modal(existente ? `Recurrente: ${r.nombre}` : 'Repetir esta factura automáticamente', [
    h('div', { class: 'campos' }, campo('Nombre', nombre), campo('Frecuencia', frecuencia),
      campo('Primera emisión', proxima), campo('Última emisión (opcional)', hasta)),
    ayuda,
  ], { acciones: [guardar] });
}

export async function vistaRecurrentes(cont) {
  const lista = await api('/recurrentes');
  const refrescar = () => vistaRecurrentes(cont).catch((e) => toast(e.message, 'error'));
  const accion = (texto, clase, fn) => h('button', { type: 'button', class: `chico ${clase}`, onclick: (e) => {
    e.stopPropagation();
    conBoton(e.target, fn);
  } }, texto);
  const cambiarActiva = (r) => api(`/recurrentes/${r.id}`, { method: 'PUT', body: { ...r, activa: !r.activa } }).then(refrescar);

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Facturas recurrentes'),
      h('a', { href: '#/emitir/01', class: 'boton primario' }, '+ Nueva (desde una factura)')),
    h('p', { class: 'suave' }, 'Alquileres, mensualidades o servicios fijos: llene la factura una vez, toque «Repetir automáticamente» '
      + 'y el sistema la emite sola en cada fecha.'),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Nombre', valor: (r) => [r.nombre, h('div', { class: 'suave' }, r.cliente || 'Consumidor final')] },
      { titulo: 'Frecuencia', valor: (r) => FRECUENCIAS[r.frecuencia] || r.frecuencia },
      { titulo: 'Próxima', valor: (r) => (r.activa ? fechaCorta(r.proxima) : h('span', { class: 'badge' }, 'Pausada')) },
      { titulo: 'Monto aprox.', num: true, valor: (r) => dinero(totalAproximado(r.datos), r.moneda) },
      { titulo: 'Emitidas', num: true, valor: (r) => r.emitidas },
      { titulo: 'Estado', valor: (r) => (r.ultimo_error ? h('span', { class: 'badge RECHAZADO', title: r.ultimo_error }, 'Con error')
        : r.ultima_factura_id ? h('a', { href: `#/comprobantes/${r.ultima_factura_id}`, onclick: (e) => e.stopPropagation() }, 'Ver la última') : '—') },
      { titulo: '', valor: (r) => h('div', { class: 'acciones' },
        accion('Emitir ahora', '', async () => {
          if (!window.confirm(`¿Emitir hoy la factura «${r.nombre}»? La próxima fecha no cambia.`)) return;
          const x = await api(`/recurrentes/${r.id}/emitir-ahora`, { method: 'POST' });
          toast(x.nueva ? 'Factura emitida' : 'Ya se había emitido hoy', 'ok');
          refrescar();
        }),
        accion(r.activa ? 'Pausar' : 'Reanudar', '', () => cambiarActiva(r)),
        accion('Eliminar', 'peligro', async () => {
          if (!window.confirm(`¿Eliminar «${r.nombre}»? Las facturas ya emitidas no se tocan.`)) return;
          await api(`/recurrentes/${r.id}`, { method: 'DELETE' });
          refrescar();
        })) },
    ], lista, (r) => dialogoRecurrente({ existente: r, alGuardar: refrescar }))),
    lista.some((r) => r.ultimo_error)
      ? aviso('Alguna factura recurrente no se pudo emitir (pase el mouse sobre «Con error» para ver por qué). '
        + 'Se vuelve a intentar cada día a las 7:00 a. m.', 'alerta') : null);
}
