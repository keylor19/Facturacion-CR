// Cliente de la API: sesión, empresa activa y manejo de errores.

export const sesion = {
  get token() { return sessionStorage.getItem('token'); },
  set token(v) { v ? sessionStorage.setItem('token', v) : sessionStorage.removeItem('token'); },
  get emisorId() { return sessionStorage.getItem('emisorId'); },
  set emisorId(v) { v ? sessionStorage.setItem('emisorId', v) : sessionStorage.removeItem('emisorId'); },
  limpiar() { sessionStorage.clear(); },
};

export class ApiError extends Error {
  constructor(mensaje, status, headers = null) { super(mensaje); this.status = status; this.headers = headers; }
}

function formatearDetalle(detalle) {
  if (Array.isArray(detalle)) {
    return detalle.map((e) => {
      const campo = (e.loc || []).filter((p) => p !== 'body').join(' → ');
      const msg = String(e.msg || '').replace(/^Value error, /, '');
      return campo ? `${campo}: ${msg}` : msg;
    }).join('\n');
  }
  return typeof detalle === 'string' ? detalle : JSON.stringify(detalle);
}

export async function api(ruta, { method = 'GET', body, form, raw = false, conEmisor = true, redirigir401 = true } = {}) {
  const headers = {};
  if (sesion.token) headers.Authorization = `Bearer ${sesion.token}`;
  if (conEmisor && sesion.emisorId) headers['X-Emisor-Id'] = sesion.emisorId;
  let cuerpo;
  if (form) {
    cuerpo = form;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    cuerpo = JSON.stringify(body);
  }

  let r;
  try {
    r = await fetch(`/api/v1${ruta}`, { method, headers, body: cuerpo });
  } catch {
    throw new ApiError('No se pudo conectar con el servidor', 0);
  }

  if (r.status === 401 && redirigir401) {
    sesion.limpiar();
    location.hash = '#/login';
    throw new ApiError('La sesión venció; ingrese de nuevo', 401);
  }
  if (!r.ok) {
    let detalle = r.statusText;
    try { detalle = formatearDetalle((await r.json()).detail); } catch { /* sin cuerpo JSON */ }
    // Administrador sin verificación en dos pasos: debe activarla en Mi cuenta
    if (r.status === 403 && r.headers.get('X-Requiere-2FA') === 'activar' && location.hash !== '#/cuenta') {
      location.hash = '#/cuenta';
    }
    throw new ApiError(detalle || `Error ${r.status}`, r.status, r.headers);
  }
  if (raw) return r;
  if (r.status === 204) return null;
  const tipo = r.headers.get('content-type') || '';
  return tipo.includes('json') ? r.json() : r.text();
}

async function comoBlob(ruta) {
  const r = await api(ruta, { raw: true });
  return r.blob();
}

export async function descargar(ruta, nombre) {
  const url = URL.createObjectURL(await comoBlob(ruta));
  const a = document.createElement('a');
  a.href = url;
  a.download = nombre;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export async function abrir(ruta) {
  const ventana = window.open('', '_blank');
  const url = URL.createObjectURL(await comoBlob(ruta));
  if (ventana) ventana.location = url; else location.href = url;
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
