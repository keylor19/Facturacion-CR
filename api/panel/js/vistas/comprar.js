// Comprar documentos o meses del sistema web: el cliente paga por SINPE Móvil o transferencia,
// reporta el pago aquí y el administrador lo aprueba. El precio lo calcula el sistema.
import { api } from '../api.js';
import { h, vaciar, dinero, fecha, tabla, modal, conBoton, toast, campo, aviso } from '../dom.js';

const ESTADO = { PENDIENTE: ['Por revisar', 'CONTINGENCIA'], APROBADA: ['Aprobada', 'ACEPTADO'], RECHAZADA: ['Rechazada', 'RECHAZADO'] };

export async function dialogoComprar(alTerminar) {
  const o = await api('/compras/opciones');
  if (!o.planes.length && !o.precio_web_mensual) {
    modal('Comprar', [aviso(`La compra en línea no está disponible. ${o.contacto_ventas ? `Escríbanos: ${o.contacto_ventas}` : 'Contacte a su proveedor.'}`, 'info')]);
    return;
  }
  const plan = h('select', {}, h('option', { value: '' }, 'Sin documentos'),
    o.planes.map((p, i) => h('option', { value: p.id, selected: i === 0 },
      `${p.nombre}: ${p.documentos.toLocaleString('es-CR')} documentos · ${dinero(p.precio, p.moneda)}`)));
  const meses = h('select', {}, h('option', { value: '0' }, 'No'),
    o.meses_web.map((m) => h('option', { value: String(m) }, `${m} ${m === 1 ? 'mes' : 'meses'}`)));
  const medio = h('select', {}, h('option', { value: '06' }, 'SINPE Móvil'), h('option', { value: '04' }, 'Transferencia'));
  const referencia = h('input', { type: 'text', maxlength: '100', required: true, placeholder: 'Número del comprobante del pago' });
  const archivo = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp,application/pdf' });
  const total = h('div', { class: 'total-venta total-general' });

  const calcular = () => {
    const p = o.planes.find((x) => x.id === plan.value);
    const m = Number(meses.value);
    const monto = (p ? Number(p.precio) : 0) + (m && o.precio_web_mensual ? m * Number(o.precio_web_mensual) : 0);
    const moneda = p?.moneda || o.moneda_web;
    total.textContent = monto ? `Total a pagar: ${dinero(monto, moneda)}${o.precio_incluye_iva ? ' (IVA incluido)' : ' más IVA'}` : 'Elija qué desea comprar';
  };
  [plan, meses].forEach((el) => el.addEventListener('change', calcular));
  calcular();

  const enviar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(enviar, async () => {
    if (!referencia.value.trim()) { toast('Indique el número del comprobante del pago', 'error'); return; }
    const form = new FormData();
    if (plan.value) form.append('plan_id', plan.value);
    form.append('meses_web', meses.value);
    form.append('medio_pago', medio.value);
    form.append('referencia', referencia.value.trim());
    if (archivo.files[0]) form.append('comprobante', archivo.files[0]);
    await api('/compras', { method: 'POST', form });
    m.cerrar();
    toast('Recibimos su aviso de pago. Le confirmaremos por correo al revisarlo.', 'ok');
    alTerminar();
  }) }, 'Avisar que ya pagué');

  const m = modal('Comprar documentos', [
    h('div', { class: 'campos' }, o.planes.length ? campo('Paquete de documentos', plan) : null,
      o.precio_web_mensual ? campo(`Sistema en línea (${dinero(o.precio_web_mensual, o.moneda_web)} por mes)`, meses) : null),
    total,
    o.instrucciones_pago ? h('div', { class: 'aviso info instrucciones-pago' }, h('strong', {}, 'Cómo pagar: '), o.instrucciones_pago) : null,
    h('div', { class: 'campos' }, campo('Medio de pago', medio), campo('Referencia del pago', referencia),
      campo('Foto o PDF del comprobante (opcional)', archivo)),
    h('p', { class: 'suave' }, 'Se acredita cuando confirmemos el pago (normalmente el mismo día hábil).'),
  ], { acciones: [enviar], ancho: true });
}

export async function seccionMisCompras(alRefrescar) {
  const lista = await api('/compras');
  return h('section', { class: 'tarjeta' },
    h('div', { class: 'encabezado' }, h('h2', {}, 'Compras en línea'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoComprar(alRefrescar).catch((e) => toast(e.message, 'error')) }, 'Comprar documentos')),
    lista.length ? tabla([
      { titulo: 'Fecha', valor: (s) => fecha(s.created_at) },
      { titulo: 'Compra', valor: (s) => [s.documentos ? `${s.documentos.toLocaleString('es-CR')} documentos` : null,
        s.meses_web ? `${s.documentos ? ' + ' : ''}${s.meses_web} mes(es) web` : null] },
      { titulo: 'Monto', num: true, valor: (s) => dinero(s.monto, s.moneda) },
      { titulo: 'Referencia', valor: (s) => s.referencia },
      { titulo: 'Estado', valor: (s) => [h('span', { class: `badge ${ESTADO[s.estado][1]}` }, ESTADO[s.estado][0]),
        s.motivo ? h('div', { class: 'suave' }, s.motivo) : null] },
    ], lista) : h('p', { class: 'suave' }, 'Pague por SINPE Móvil o transferencia y avísenos aquí: el saldo se acredita al confirmar el pago.'));
}

// --- Administrador: pagos por revisar ------------------------------------------------------
export async function vistaSolicitudes(cont, estado = 'PENDIENTE') {
  const refrescar = () => vistaSolicitudes(cont, estado).catch((e) => toast(e.message, 'error'));
  const lista = await api(`/admin/solicitudes${estado ? `?estado=${estado}` : ''}`, { conEmisor: false });
  const filtro = h('select', { onchange: (e) => vistaSolicitudes(cont, e.target.value).catch((err) => toast(err.message, 'error')) },
    [['PENDIENTE', 'Por revisar'], ['APROBADA', 'Aprobadas'], ['RECHAZADA', 'Rechazadas'], ['', 'Todas']]
      .map(([v, t]) => h('option', { value: v, selected: v === estado }, t)));
  const verComprobante = (s) => h('button', { type: 'button', class: 'chico', onclick: (e) => conBoton(e.target, async () => {
    const blob = await api(`/admin/solicitudes/${s.id}/comprobante`, { conEmisor: false, raw: true }).then((r) => r.blob());
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }) }, 'Ver comprobante');
  const aprobar = (s) => {
    const comprobante = h('select', {}, h('option', { value: '' }, 'No emitir'), h('option', { value: '01', selected: true }, 'Factura'), h('option', { value: '04' }, 'Tiquete'));
    const ok = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(ok, async () => {
      await api(`/admin/solicitudes/${s.id}/aprobar`, { method: 'POST', conEmisor: false, body: { comprobante: comprobante.value || null } });
      m.cerrar();
      toast('Compra aprobada y acreditada', 'ok');
      refrescar();
    }) }, 'Aprobar y acreditar');
    const m = modal(`Aprobar pago de ${s.empresa}`, [
      h('p', {}, `${dinero(s.monto, s.moneda)} · referencia ${s.referencia}. Confirme que el dinero ya está en la cuenta.`),
      campo('Comprobante por la venta', comprobante),
    ], { acciones: [ok] });
  };
  const rechazar = (s) => {
    const motivo = h('input', { type: 'text', maxlength: '300', placeholder: 'Ej.: no aparece el depósito' });
    const ok = h('button', { type: 'button', class: 'peligro', onclick: () => conBoton(ok, async () => {
      await api(`/admin/solicitudes/${s.id}/rechazar`, { method: 'POST', conEmisor: false, body: { motivo: motivo.value.trim() } });
      m.cerrar();
      refrescar();
    }) }, 'Rechazar');
    const m = modal('Rechazar pago', [campo('Motivo (se le envía al cliente)', motivo)], { acciones: [ok] });
  };
  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Pagos por revisar'), filtro),
    h('p', { class: 'suave' }, 'Compras que los clientes pagaron por SINPE Móvil o transferencia. Al aprobar se acredita el saldo y se emite el comprobante.'),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Fecha', valor: (s) => fecha(s.created_at) },
      { titulo: 'Empresa', valor: (s) => s.empresa },
      { titulo: 'Compra', valor: (s) => `${s.documentos ? `${s.documentos} docs` : ''}${s.meses_web ? ` ${s.meses_web} mes(es) web` : ''}` },
      { titulo: 'Monto', num: true, valor: (s) => dinero(s.monto, s.moneda) },
      { titulo: 'Referencia', valor: (s) => [s.referencia, h('div', { class: 'suave' }, s.medio_pago === '06' ? 'SINPE Móvil' : 'Transferencia')] },
      { titulo: 'Estado', valor: (s) => h('span', { class: `badge ${ESTADO[s.estado][1]}` }, ESTADO[s.estado][0]) },
      { titulo: '', valor: (s) => h('div', { class: 'acciones' },
        s.tiene_comprobante ? verComprobante(s) : null,
        s.estado === 'PENDIENTE' ? h('button', { type: 'button', class: 'chico primario', onclick: () => aprobar(s) }, 'Aprobar') : null,
        s.estado === 'PENDIENTE' ? h('button', { type: 'button', class: 'chico peligro', onclick: () => rechazar(s) }, 'Rechazar') : null) },
    ], lista)));
}
