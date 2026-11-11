// Usuarios del panel: alta, empresa a la que pertenece, rol y bloqueo.
// El administrador ve a todos (y crea los usuarios contadores); el dueño de una empresa, solo a los
// de su empresa y a los contadores que llevan su contabilidad (y les puede quitar el acceso).
import { api } from '../api.js';
import { h, vaciar, fecha, tabla, modal, conBoton, toast, campo, aviso, opciones } from '../dom.js';
import { contexto, empresaActual, puede } from '../app.js';

const ROLES = { dueno: 'Dueño', contador: 'Administrativo', cajero: 'Cajero' };
const AYUDA_ROLES = {
  dueno: 'Todo lo de la empresa: vende, anula, precios, configuración, usuarios y la contabilidad.',
  contador: 'Facturas, notas y anulaciones, cobros y facturas de proveedores. No cambia precios ni usa la caja.',
  cajero: 'Vende (factura, tiquete, punto de venta) y cobra. No anula.',
};
const ACCESO_ADMIN = '__admin__';
const ACCESO_CONTADOR = '__contador__';

export async function vistaUsuarios(cont) {
  if (!puede('usuarios')) { vaciar(cont, aviso('Solo el dueño de la empresa o un administrador maneja los usuarios.', 'alerta')); return; }
  const [usuarios, empresas] = await Promise.all([
    api('/usuarios', { conEmisor: false }),
    contexto.esAdmin ? api('/emisores', { conEmisor: false }) : Promise.resolve([empresaActual()].filter(Boolean)),
  ]);
  const nombreEmpresa = Object.fromEntries(empresas.map((e) => [e.id, e.nombre]));
  const refrescar = () => vistaUsuarios(cont).catch((e) => toast(e.message, 'error'));
  const acceso = (u) => (u.es_admin ? 'Administrador (todas las empresas)'
    : u.es_contador ? 'Contador (escoge sus empresas)' : nombreEmpresa[u.emisor_id] || '—');
  const contadores = contexto.esAdmin ? null : await seccionContadores(() => vistaUsuarios(cont));

  vaciar(cont,
    h('div', { class: 'encabezado' }, h('h1', {}, 'Usuarios'),
      h('button', { type: 'button', class: 'primario', onclick: () => dialogoNuevo(empresas, refrescar) }, '+ Nuevo usuario')),
    h('section', { class: 'tarjeta' }, tabla([
      { titulo: 'Nombre', valor: (u) => [u.nombre, h('div', { class: 'suave' }, u.email)] },
      contexto.esAdmin ? { titulo: 'Acceso', valor: acceso } : null,
      { titulo: 'Rol', valor: (u) => (u.es_admin || u.es_contador ? '—' : selectorRol(u, refrescar)) },
      { titulo: 'Último ingreso', valor: (u) => fecha(u.ultimo_login) || 'Nunca' },
      { titulo: 'Estado', valor: (u) => (u.activo ? 'Activo' : h('span', { class: 'badge RECHAZADO' }, 'Inactivo')) },
      { titulo: 'Dos pasos', valor: (u) => (u.dos_pasos ? h('span', { class: 'badge ACEPTADO' }, 'Activa')
        : h('span', { class: `badge ${u.es_admin ? 'CONTINGENCIA' : ''}` }, 'No')) },
      { titulo: '', valor: (u) => h('div', { class: 'acciones' },
        h('button', { type: 'button', class: 'chico', onclick: () => dialogoPassword(u) }, 'Cambiar contraseña'),
        u.dos_pasos && u.id !== contexto.usuario?.id && contexto.esAdmin ? h('button', { type: 'button', class: 'chico', onclick: (ev) => conBoton(ev.target, async () => {
          if (!confirm(`¿Quitar la verificación en dos pasos de ${u.nombre}? Deberá configurarla de nuevo.`)) return;
          await api(`/usuarios/${u.id}/2fa`, { method: 'DELETE', conEmisor: false });
          toast('Verificación en dos pasos reiniciada', 'ok');
          refrescar();
        }) }, 'Reiniciar 2 pasos') : null,
        u.id === contexto.usuario?.id ? null : h('button', { type: 'button', class: `chico ${u.activo ? 'peligro' : ''}`, onclick: (ev) => conBoton(ev.target, async () => {
          await api(`/usuarios/${u.id}`, { method: 'PATCH', body: { activo: !u.activo }, conEmisor: false });
          refrescar();
        }) }, u.activo ? 'Desactivar' : 'Activar')) },
    ].filter(Boolean), usuarios)),
    contadores,
    h('section', { class: 'tarjeta' }, h('h2', {}, 'Qué puede hacer cada rol'),
      h('dl', { class: 'datos' }, Object.entries(ROLES).map(([k, t]) => [h('dt', {}, t), h('dd', {}, AYUDA_ROLES[k])]),
        [h('dt', {}, 'Contador'), h('dd', {}, 'Usuario aparte: escoge las empresas a las que les lleva la contabilidad (o inscribe las que '
          + 'no facturan aquí). Solo ve la contabilidad: no factura ni ve el resto del sistema. El dueño le puede quitar el acceso.')])));
}

// Cambia el rol en el momento (cierra las sesiones de esa persona para que lo tome)
function selectorRol(u, refrescar) {
  if (u.id === contexto.usuario?.id) return ROLES[u.rol] || u.rol;
  const sel = h('select', { 'aria-label': `Rol de ${u.nombre}`, onchange: async () => {
    sel.disabled = true;
    try {
      await api(`/usuarios/${u.id}`, { method: 'PATCH', body: { rol: sel.value }, conEmisor: false });
      toast(`${u.nombre} ahora es ${ROLES[sel.value].toLowerCase()}`, 'ok');
      refrescar();
    } catch (e) {
      sel.value = u.rol;
      toast(e.message, 'error');
    } finally {
      sel.disabled = false;
    }
  } }, opciones(ROLES, u.rol));
  return sel;
}

// Dueño: contadores que llevan la contabilidad de su empresa
async function seccionContadores(refrescar) {
  const lista = await api('/empresa/contadores').catch(() => []);
  return h('section', { class: 'tarjeta' }, h('h2', {}, 'Contadores con acceso a su contabilidad'),
    h('p', { class: 'suave' }, 'Ven la contabilidad de su empresa (comprobantes, asientos e impuestos), pero no facturan ni cambian nada. '
      + 'Si alguno no debe tener acceso, quíteselo.'),
    lista.length ? tabla([
      { titulo: 'Contador', valor: (c) => [c.nombre, h('div', { class: 'suave' }, c.email)] },
      { titulo: 'Desde', valor: (c) => fecha(c.desde) },
      { titulo: '', valor: (c) => h('button', { type: 'button', class: 'chico peligro', onclick: (ev) => conBoton(ev.target, async () => {
        if (!confirm(`¿Quitarle a ${c.nombre} el acceso a la contabilidad de su empresa?`)) return;
        await api(`/empresa/contadores/${c.id}`, { method: 'DELETE' });
        toast('Acceso quitado', 'ok');
        refrescar();
      }) }, 'Quitar acceso') },
    ], lista) : h('p', { class: 'suave' }, 'Ningún contador lleva la contabilidad de su empresa.'));
}

function dialogoNuevo(empresas, alTerminar) {
  const email = h('input', { type: 'email' });
  const nombre = h('input', { type: 'text', maxlength: '100' });
  const password = h('input', { type: 'password', autocomplete: 'new-password', minlength: '10' });
  const acceso = h('select', {},
    contexto.esAdmin ? [h('option', { value: ACCESO_ADMIN }, 'Administrador (todas las empresas)'),
      h('option', { value: ACCESO_CONTADOR }, 'Contador (escoge las empresas a las que les lleva la contabilidad)')] : null,
    empresas.map((e) => h('option', { value: e.id, selected: !contexto.esAdmin }, `Solo ${e.nombre}`)));
  const rol = h('select', {}, opciones(ROLES, 'cajero'));
  const ayudaRol = h('p', { class: 'suave' }, AYUDA_ROLES.cajero);
  rol.addEventListener('change', () => { ayudaRol.textContent = AYUDA_ROLES[rol.value]; });
  const campoRol = campo('Rol', rol);
  const deEmpresa = () => ![ACCESO_ADMIN, ACCESO_CONTADOR].includes(acceso.value);
  const mostrarRol = () => { campoRol.classList.toggle('oculto', !deEmpresa()); ayudaRol.classList.toggle('oculto', !deEmpresa()); };
  acceso.addEventListener('change', mostrarRol);
  const crear = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(crear, async () => {
    await api('/usuarios', {
      method: 'POST', conEmisor: false,
      body: {
        email: email.value.trim(), nombre: nombre.value.trim(), password: password.value,
        es_admin: acceso.value === ACCESO_ADMIN, es_contador: acceso.value === ACCESO_CONTADOR,
        emisor_id: deEmpresa() ? acceso.value : null, rol: rol.value,
      },
    });
    m.cerrar();
    toast('Usuario creado', 'ok');
    alTerminar();
  }) }, 'Crear');
  const m = modal('Nuevo usuario', [
    h('div', { class: 'campos' }, campo('Correo', email), campo('Nombre', nombre),
      campo('Contraseña inicial (mínimo 10)', password), contexto.esAdmin ? campo('Acceso', acceso) : null, campoRol),
    ayudaRol,
  ], { acciones: [crear] });
  mostrarRol();
}

function dialogoPassword(u) {
  const password = h('input', { type: 'password', autocomplete: 'new-password', minlength: '10' });
  const guardar = h('button', { type: 'button', class: 'primario', onclick: () => conBoton(guardar, async () => {
    await api(`/usuarios/${u.id}`, { method: 'PATCH', body: { password: password.value }, conEmisor: false });
    m.cerrar();
    toast('Contraseña actualizada; se cerraron sus sesiones', 'ok');
  }) }, 'Guardar');
  const m = modal(`Contraseña de ${u.nombre}`, [campo('Nueva contraseña (mínimo 10)', password)], { acciones: [guardar] });
}
