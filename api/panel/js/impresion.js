// Impresión del comprobante en hoja carta o en rollo de impresora térmica (80 mm o 58 mm).
// El tamaño de rollo se recuerda en este navegador (cada caja tiene su impresora).
import { abrir, api } from './api.js';
import { h, conBoton, modal, campo, toast } from './dom.js';

const CLAVE = 'rollo-impresora';
const ROLLOS = { '80mm': 'Rollo 80 mm', '58mm': 'Rollo 58 mm' };

export function rolloPreferido() {
  try {
    const v = localStorage.getItem(CLAVE);
    return ROLLOS[v] ? v : '80mm';
  } catch {
    return '80mm';
  }
}

function recordarRollo(v) {
  try { localStorage.setItem(CLAVE, v); } catch { /* sin almacenamiento: se usa 80 mm */ }
}

export const imprimirTiquete = (facturaId) => abrir(`/facturas/${facturaId}/pdf?formato=${rolloPreferido()}`);

// Botón "Imprimir tiquete" con selector del ancho del rollo
export function controlesTiquete(facturaId) {
  const rollo = h('select', { title: 'Ancho del papel de la impresora', onchange: (e) => recordarRollo(e.target.value) },
    Object.entries(ROLLOS).map(([v, t]) => h('option', { value: v, selected: v === rolloPreferido() }, t)));
  const boton = h('button', { type: 'button', onclick: () => conBoton(boton, () => imprimirTiquete(facturaId)) }, 'Imprimir tiquete');
  return h('span', { class: 'grupo-tiquete' }, boton, rollo);
}

// Enviar por WhatsApp: pide el número (opcional) y abre WhatsApp con el mensaje y el enlace de descarga.
export function botonWhatsapp(facturaId) {
  return h('button', { type: 'button', onclick: () => {
    const telefono = h('input', { type: 'tel', maxlength: '20', placeholder: '8888 7777 (vacío = elegir en WhatsApp)' });
    const enviar = h('button', { type: 'button', class: 'primario', onclick: async () => {
      // La ventana se abre en el clic para que el navegador no la bloquee
      const ventana = window.open('', '_blank');
      try {
        const e = await api(`/facturas/${facturaId}/enlace?telefono=${encodeURIComponent(telefono.value.trim())}`);
        if (ventana) ventana.location = e.whatsapp; else location.href = e.whatsapp;
        m.cerrar();
      } catch (err) {
        if (ventana) ventana.close();
        toast(err.message, 'error');
      }
    } }, 'Abrir WhatsApp');
    const copiar = h('button', { type: 'button', onclick: async () => {
      try {
        const e = await api(`/facturas/${facturaId}/enlace`);
        await navigator.clipboard.writeText(e.pdf);
        toast('Enlace copiado: péguelo en el chat o mensaje', 'ok');
      } catch (err) {
        toast(err.message || 'No se pudo copiar', 'error');
      }
    } }, 'Copiar enlace');
    const m = modal('Enviar por WhatsApp', [
      h('p', { class: 'suave' }, 'Se abre WhatsApp con un mensaje y un enlace para que el cliente descargue el PDF (no necesita usuario).'),
      campo('Celular del cliente', telefono),
    ], { acciones: [copiar, enviar] });
  } }, 'Enviar por WhatsApp');
}
