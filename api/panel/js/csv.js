// Lectura y escritura de CSV para cargas masivas y reportes. Se usa ";" como
// separador (Excel en español) con BOM, igual que los libros de ventas y compras.
import { h, vaciar, tabla, conBoton, toast, aviso } from './dom.js';

export function descargarCsv(nombre, encabezados, filas) {
  const celda = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const texto = [encabezados, ...filas].map((f) => f.map(celda).join(';')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['﻿', texto], { type: 'text/csv;charset=utf-8' }));
  const a = h('a', { href: url, download: nombre });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// Devuelve una lista de objetos con las columnas del encabezado en minúscula.
// Acepta ";" o "," como separador y campos entre comillas.
export function leerCsv(texto) {
  const limpio = texto.replace(/^﻿/, '');
  const primera = limpio.split(/\r?\n/, 1)[0] || '';
  const sep = (primera.match(/;/g) || []).length >= (primera.match(/,/g) || []).length ? ';' : ',';
  const filas = [];
  let fila = [];
  let valor = '';
  let comillas = false;
  for (let i = 0; i < limpio.length; i += 1) {
    const c = limpio[i];
    if (comillas) {
      if (c === '"' && limpio[i + 1] === '"') { valor += '"'; i += 1; } else if (c === '"') comillas = false; else valor += c;
    } else if (c === '"') comillas = true;
    else if (c === sep) { fila.push(valor); valor = ''; } else if (c === '\n' || c === '\r') {
      if (c === '\r' && limpio[i + 1] === '\n') i += 1;
      fila.push(valor); filas.push(fila); fila = []; valor = '';
    } else valor += c;
  }
  if (valor || fila.length) { fila.push(valor); filas.push(fila); }
  const [encabezado, ...datos] = filas.filter((f) => f.some((v) => v.trim()));
  if (!encabezado) return [];
  const claves = encabezado.map((k) => k.trim().toLowerCase());
  return datos.map((f) => Object.fromEntries(claves.map((k, i) => [k, (f[i] || '').trim()])));
}

// "1.500,50", "1,500.50" y "1500,5" → "1500.50" / "1500.5"
export function numeroCsv(v) {
  const s = String(v || '').replace(/\s|₡|\$/g, '');
  if (!s) return '';
  const coma = s.lastIndexOf(',');
  const punto = s.lastIndexOf('.');
  if (coma > punto) return s.replace(/\./g, '').replace(',', '.');
  return s.replace(/,/g, '');
}

export const siNo = (v) => ['si', 'sí', 's', 'x', '1', 'true', 'yes'].includes(String(v || '').trim().toLowerCase());

// Pantalla de carga masiva: plantilla, vista previa con validación y registro fila por fila.
// convertir(fila) devuelve { cuerpo, error } ; enviar(cuerpo) llama a la API.
export function pantallaCarga({ titulo, descripcion, plantilla, ejemplo, columnas, convertir, enviar, volver }) {
  const archivo = h('input', { type: 'file', accept: '.csv,text/csv' });
  const vista = h('div');
  let pendientes = [];

  const importar = h('button', { type: 'button', class: 'primario', disabled: true, onclick: () => conBoton(importar, async () => {
    const resultados = [];
    for (const [i, p] of pendientes.entries()) {
      importar.textContent = `Registrando ${i + 1} de ${pendientes.length}…`;
      try { await enviar(p.cuerpo); resultados.push({ ...p, ok: true, mensaje: 'Registrado' }); } catch (e) { resultados.push({ ...p, ok: false, mensaje: e.message }); }
    }
    const ok = resultados.filter((r) => r.ok).length;
    toast(`${ok} de ${resultados.length} registrados`, ok === resultados.length ? 'ok' : 'error');
    pendientes = [];
    importar.disabled = true;
    archivo.value = '';
    vaciar(vista,
      aviso(`Resultado: ${ok} registrados, ${resultados.length - ok} con error.`, ok === resultados.length ? 'ok' : 'alerta'),
      tabla([
        { titulo: 'Fila', num: true, valor: (r) => r.numero },
        ...columnas,
        { titulo: 'Resultado', valor: (r) => h('span', { class: `badge ${r.ok ? 'ACEPTADO' : 'RECHAZADO'}` }, r.mensaje) },
      ], resultados));
  }) }, 'Registrar');

  archivo.addEventListener('change', async () => {
    const f = archivo.files[0];
    if (!f) return;
    const filas = leerCsv(await f.text()).map((fila, i) => ({ numero: i + 2, fila, ...convertir(fila) }));
    pendientes = filas.filter((r) => !r.error);
    importar.disabled = !pendientes.length;
    vaciar(vista,
      filas.length ? aviso(`${filas.length} filas leídas: ${pendientes.length} listas para registrar, ${filas.length - pendientes.length} con errores (no se registran).`,
        pendientes.length === filas.length ? 'ok' : 'alerta') : aviso('El archivo no tiene filas de datos.', 'error'),
      tabla([
        { titulo: 'Fila', num: true, valor: (r) => r.numero },
        ...columnas,
        { titulo: 'Validación', valor: (r) => (r.error ? h('span', { class: 'badge RECHAZADO' }, r.error) : h('span', { class: 'badge ACEPTADO' }, 'Lista')) },
      ], filas));
  });

  return [
    h('div', { class: 'encabezado' }, h('div', {}, volver, h('h1', {}, titulo))),
    h('section', { class: 'tarjeta' },
      h('h2', {}, '1. Descargue la plantilla'),
      h('p', { class: 'suave' }, descripcion),
      h('div', { class: 'acciones' }, h('button', { type: 'button', onclick: () => descargarCsv(plantilla, ejemplo[0], ejemplo.slice(1)) }, 'Descargar plantilla (Excel)'))),
    h('section', { class: 'tarjeta' },
      h('h2', {}, '2. Suba el archivo lleno'),
      h('div', { class: 'subir' }, h('p', {}, 'Guarde la plantilla como "CSV (delimitado por comas)" y selecciónela aquí.'), archivo),
      vista,
      h('div', { class: 'acciones' }, importar)),
  ];
}
