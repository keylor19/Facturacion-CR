// Descargar documentos: ZIP con XML, respuestas de Hacienda, PDF e índice para el contador.
import { descargar } from '../api.js';
import { h, vaciar, conBoton, campo, aviso, mesActual, TIPOS } from '../dom.js';
import { empresaActual } from '../app.js';

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export async function vistaDescargas(cont) {
  const { anio, mes } = mesActual();
  const desde = h('input', { type: 'date', value: iso(new Date(anio, mes - 1, 1)) });
  const hasta = h('input', { type: 'date', value: iso(new Date(anio, mes, 0)) });
  const emitidos = h('input', { type: 'checkbox', checked: true });
  const recibidos = h('input', { type: 'checkbox', checked: true });
  const pdf = h('input', { type: 'checkbox' });
  const tipo = h('select', {}, h('option', { value: '' }, 'Todos'),
    Object.entries(TIPOS).map(([k, v]) => h('option', { value: k }, v)));
  const atajos = [['Este mes', 0], ['Mes anterior', -1]].map(([texto, delta]) => h('button', { type: 'button', class: 'chico', onclick: () => {
    desde.value = iso(new Date(anio, mes - 1 + delta, 1));
    hasta.value = iso(new Date(anio, mes + delta, 0));
  } }, texto));

  const boton = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(boton, async () => {
    const params = new URLSearchParams({
      desde: desde.value, hasta: hasta.value, emitidos: String(emitidos.checked), recibidos: String(recibidos.checked), pdf: String(pdf.checked),
    });
    if (tipo.value) params.set('tipo_documento', tipo.value);
    const cedula = empresaActual()?.numero_identificacion || '';
    await descargar(`/reportes/documentos.zip?${params}`, `comprobantes-${cedula}-${desde.value}-${hasta.value}.zip`);
  }) }, 'Descargar ZIP');

  vaciar(cont,
    h('h1', {}, 'Descargar documentos'),
    h('section', { class: 'tarjeta' },
      h('div', { class: 'acciones' }, atajos),
      h('div', { class: 'campos' }, campo('Desde', desde), campo('Hasta', hasta), campo('Tipo de comprobante emitido', tipo)),
      h('div', { class: 'acciones' },
        h('label', { class: 'check' }, emitidos, 'Comprobantes emitidos'),
        h('label', { class: 'check' }, recibidos, 'Facturas de proveedores (recibidas)'),
        h('label', { class: 'check' }, pdf, 'Incluir PDF (más lento; hasta 500 documentos)')),
      h('div', { class: 'acciones' }, boton)),
    aviso('El ZIP trae los XML firmados, las respuestas de Hacienda y un índice (indice.csv) que abre en Excel. '
      + 'Es lo que normalmente pide el contador para la declaración. Máximo un año por descarga.', 'info'));
}
