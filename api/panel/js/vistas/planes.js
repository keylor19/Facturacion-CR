import { api } from '../api.js';
import { h, vaciar, dinero, fecha, tabla, modal, conBoton, toast, campo, aviso, mesActual, selectorMes } from '../dom.js';
import { contexto } from '../app.js';

export async function vistaPlanes(cont) {
  if (!contexto.esAdmin) { vaciar(cont, aviso('Esta sección es solo para administradores.', 'alerta')); return; }
  let periodo = mesActual();
  const planes = await api('/planes', { conEmisor: false });
  const refrescar = () => vistaPlanes(cont).catch((e) => toast(e.message, 'error'));
  const ventas = h('div');

  async function cargarVentas() {
    const v = await api(`/admin/ventas?anio=${periodo.anio}&mes=${periodo.mes}`, { conEmisor: false });
    vaciar(ventas,
      h('div', { class: 'kpis' },
        Object.entries(v.ingresos).map(([m, total]) => h('div', { class: 'kpi' },
          h('div', { class: 'etiqueta' }, `Ingresos ${m}`), h('div', { class: 'valor' }, dinero(total, m)),
          h('div', { class: 'suave' }, `Documentos ${dinero(v.ingresos_documentos?.[m] || 0, m)} · Servicios ${dinero(v.ingresos_servicios?.[m] || 0, m)}`))),
        h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Paquetes vendidos'), h('div', { class: 'valor' }, v.paquetes_vendidos.length)),
        h('div', { class: 'kpi' }, h('div', { class: 'etiqueta' }, 'Documentos consumidos'), h('div', { class: 'valor' }, v.documentos_consumidos.toLocaleString('es-CR')))),
      h('h3', {}, 'Paquetes vendidos'),
      tabla([
        { titulo: 'Fecha', valor: (p) => fecha(p.fecha) },
        { titulo: 'Empresa', valor: (p) => p.empresa },
        { titulo: 'Paquete', valor: (p) => p.nombre },
        { titulo: 'Documentos', num: true, valor: (p) => p.documentos.toLocaleString('es-CR') },
        { titulo: 'Precio', num: true, valor: (p) => dinero(p.precio, p.moneda) },
        { titulo: 'Pago', valor: (p) => p.referencia_pago || '—' },
      ], v.paquetes_vendidos),
      h('h3', {}, 'Mensualidades de servicios cobradas'),
      tabla([
        { titulo: 'Fecha', valor: (s) => fecha(s.fecha) },
        { titulo: 'Empresa', valor: (s) => s.empresa },
        { titulo: 'Servicio', valor: (s) => s.nombre },
        { titulo: 'Período', valor: (s) => `${s.meses} mes(es): ${fecha(s.desde, false)} – ${fecha(s.hasta, false)}` },
        { titulo: 'Precio', num: true, valor: (s) => dinero(s.precio, s.moneda) },
        { titulo: 'Pago', valor: (s) => s.referencia_pago || '—' },
      ], v.servicios_vendidos || []),
      h('h3', {}, 'Consumo por empresa'),
      tabla([
        { titulo: 'Empresa', valor: (c) => h('a', { href: `#/empresas/${c.emisor_id}` }, c.empresa) },
        { titulo: 'Documentos', num: true, valor: (c) => c.documentos.toLocaleString('es-CR') },
      ], v.consumo_por_empresa));
  }

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Planes y ventas'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoPlan(null, refrescar) }, '+ Nuevo plan')),
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Catálogo de planes'),
      tabla([
        { titulo: 'Plan', valor: (p) => [p.nombre, p.descripcion ? h('div', { class: 'suave' }, p.descripcion) : null] },
        { titulo: 'Documentos', num: true, valor: (p) => p.documentos.toLocaleString('es-CR') },
        { titulo: 'Precio', num: true, valor: (p) => dinero(p.precio, p.moneda) },
        { titulo: 'Precio por documento', num: true, valor: (p) => dinero(Number(p.precio) / p.documentos, p.moneda) },
        { titulo: 'Vigencia', valor: (p) => (p.dias_vigencia ? `${p.dias_vigencia} días` : 'No vence') },
        { titulo: 'Estado', valor: (p) => (p.activo ? 'Activo' : h('span', { class: 'badge RECHAZADO' }, 'Inactivo')) },
        { titulo: '', valor: (p) => h('button', { type: 'button', class: 'chico', onclick: () => dialogoPlan(p, refrescar) }, 'Editar') },
      ], planes)),
    h('section', { class: 'tarjeta' },
      h('div', { class: 'encabezado' }, h('h2', {}, 'Ventas y consumo del mes'),
        selectorMes(periodo, (p) => { periodo = p; cargarVentas().catch((e) => toast(e.message, 'error')); })),
      ventas));
  await cargarVentas();
}

function dialogoPlan(plan, alTerminar) {
  const nombre = h('input', { type: 'text', maxlength: '80', value: plan?.nombre || '' });
  const descripcion = h('input', { type: 'text', maxlength: '300', value: plan?.descripcion || '' });
  const documentos = h('input', { type: 'number', min: '1', value: plan ? String(plan.documentos) : '', disabled: Boolean(plan) });
  const precio = h('input', { type: 'number', min: '0', step: '0.01', value: plan ? String(plan.precio) : '' });
  const moneda = h('select', { disabled: Boolean(plan) }, ['CRC', 'USD'].map((m) => h('option', { value: m, selected: plan?.moneda === m }, m)));
  const vigencia = h('input', { type: 'number', min: '1', placeholder: 'Vacío = no vence', value: plan?.dias_vigencia ? String(plan.dias_vigencia) : '' });
  const activo = h('input', { type: 'checkbox', checked: plan ? plan.activo : true });

  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    const cuerpo = { nombre: nombre.value.trim(), descripcion: descripcion.value.trim() || null, precio: precio.value,
      dias_vigencia: vigencia.value ? Number(vigencia.value) : null };
    if (plan) {
      cuerpo.activo = activo.checked;
      await api(`/planes/${plan.id}`, { method: 'PATCH', body: cuerpo, conEmisor: false });
    } else {
      await api('/planes', { method: 'POST', conEmisor: false, body: { ...cuerpo, documentos: Number(documentos.value), moneda: moneda.value } });
    }
    m.cerrar();
    toast('Plan guardado', 'ok');
    alTerminar();
  }) }, 'Guardar');

  const m = modal(plan ? `Editar ${plan.nombre}` : 'Nuevo plan', [
    h('div', { class: 'campos' }, campo('Nombre', nombre), campo('Documentos', documentos), campo('Precio', precio),
      campo('Moneda', moneda), campo('Vigencia (días)', vigencia)),
    campo('Descripción', descripcion),
    plan ? h('label', { class: 'check' }, activo, 'Plan activo (disponible para vender)') : null,
  ], { acciones: [guardar] });
}
