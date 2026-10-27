// Selector encadenado provincia → cantón → distrito, por nombre. Los valores
// siguen siendo los códigos de Hacienda ("1", "01", "01").
import { h, vaciar } from './dom.js';
import { UBICACIONES } from './datos-ubicaciones.js';

const opcion = (valor, texto, seleccionado) => h('option', { value: valor, selected: valor === seleccionado }, texto);

// Un código guardado que no esté en el catálogo se conserva como opción, para no perderlo.
function llenar(select, mapa, seleccionado, vacio) {
  // Orden por código: JavaScript pone primero las claves "10", "11"… por parecer enteros
  const items = Object.entries(mapa || {}).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => opcion(k, Array.isArray(v) ? v[0] : v, seleccionado));
  const desconocido = seleccionado && !(seleccionado in (mapa || {})) ? opcion(seleccionado, `Código ${seleccionado}`, seleccionado) : null;
  vaciar(select, h('option', { value: '' }, vacio), items, desconocido);
  select.disabled = !mapa;
}

export function selectorUbicacion(valores = {}) {
  const provincia = h('select', {});
  const canton = h('select', {});
  const distrito = h('select', {});

  const cantones = () => UBICACIONES[provincia.value]?.[1];
  const distritos = () => cantones()?.[canton.value]?.[1];

  const fijar = ({ provincia: p = '', canton: c = '', distrito: d = '' } = {}) => {
    llenar(provincia, UBICACIONES, p || '', '— Provincia —');
    llenar(canton, p ? cantones() || {} : null, c || '', '— Cantón —');
    llenar(distrito, c ? distritos() || {} : null, d || '', '— Distrito —');
  };

  provincia.addEventListener('change', () => fijar({ provincia: provincia.value }));
  canton.addEventListener('change', () => fijar({ provincia: provincia.value, canton: canton.value }));

  fijar(valores);
  return { provincia, canton, distrito, fijar };
}
