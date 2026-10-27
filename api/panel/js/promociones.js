// Descuentos automáticos: al agregar un producto del catálogo se aplica el
// descuento vigente que más le favorezca al cliente (uno por línea).
import { api } from './api.js';

export async function descuentosVigentes() {
  try { return await api('/catalogo/descuentos?vigentes=true'); } catch { return []; }
}

// Devuelve { monto, codigo, nombre } o null. precio es sin IVA.
export function mejorDescuento(lista, producto, cantidad, precio = producto.precio_unitario) {
  const bruto = Number(cantidad) * Number(precio);
  if (!(bruto > 0)) return null;
  let mejor = null;
  for (const d of lista) {
    if (d.alcance === 'categoria' && d.categoria_id !== producto.categoria_id) continue;
    if (d.alcance === 'producto' && d.producto_id !== producto.id) continue;
    if (d.cantidad_minima && Number(cantidad) < Number(d.cantidad_minima)) continue;
    const calculado = d.tipo === 'porcentaje' ? bruto * Number(d.valor) / 100 : Number(d.valor) * Number(cantidad);
    const monto = Math.round(Math.min(bruto, calculado) * 100) / 100;
    if (monto > 0 && (!mejor || monto > mejor.monto)) mejor = { monto, codigo: d.codigo_descuento, nombre: d.nombre };
  }
  return mejor;
}
