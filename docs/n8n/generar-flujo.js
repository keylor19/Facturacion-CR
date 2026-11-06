// Genera flujo-facturacion-cr.json (flujo de n8n listo para importar). Edite este archivo
// en lugar del JSON y vuelva a generarlo: node docs/n8n/generar-flujo.js
const fs = require('fs');

const BASE = 'https://SU-DOMINIO/api/v1';
const CRED_API = { httpHeaderAuth: { id: 'facturacion-cr-api', name: 'Facturación CR (API key)' } };
const CRED_WEBHOOK = { httpHeaderAuth: { id: 'facturacion-cr-webhooks', name: 'Facturación CR (clave de mis webhooks)' } };

let contador = 0;
const uid = () => `f4c7a000-0000-4000-8000-${String(++contador).padStart(12, '0')}`;
const nodes = [];
const connections = {};
const nodo = (name, type, typeVersion, position, parameters, extra = {}) => {
  nodes.push({ parameters, id: uid(), name, type, typeVersion, position, ...extra });
  return name;
};
const unir = (desde, hacia, salida = 0) => {
  connections[desde] = connections[desde] || { main: [] };
  while (connections[desde].main.length <= salida) connections[desde].main.push([]);
  connections[desde].main[salida].push({ node: hacia, type: 'main', index: 0 });
};
const cadena = (...nombres) => nombres.slice(1).forEach((n, i) => unir(nombres[i], n));
const codigo = (...lineas) => ({ jsCode: lineas.join('\n') });
const nota = (titulo, texto, x, y, alto = 200, ancho = 560) =>
  nodo(titulo, 'n8n-nodes-base.stickyNote', 1, [x, y], { content: texto, height: alto, width: ancho });

const RESPUESTA_COMPLETA = { response: { response: { neverError: true, fullResponse: true } } };
const webhook = (name, metodo, ruta, pos, { protegido = true, opciones = {} } = {}) => nodo(name, 'n8n-nodes-base.webhook', 2, pos, {
  httpMethod: metodo, path: ruta, responseMode: 'responseNode',
  ...(protegido ? { authentication: 'headerAuth' } : {}), options: opciones,
}, { webhookId: uid(), ...(protegido ? { credentials: CRED_WEBHOOK } : {}) });
const http = (name, metodo, url, pos, extra = {}) => nodo(name, 'n8n-nodes-base.httpRequest', 4.2, pos, {
  method: metodo, url, authentication: 'genericCredentialType', genericAuthType: 'httpHeaderAuth',
  ...extra, options: { ...RESPUESTA_COMPLETA, ...(extra.options || {}) },
}, { credentials: CRED_API });
const responder = (name, pos) => nodo(name, 'n8n-nodes-base.respondToWebhook', 1.1, pos,
  { respondWith: 'json', responseBody: '={{ JSON.stringify($json) }}', options: { responseCode: '={{ $json.http_status || 200 }}' } });
const siVerdadero = (name, expresion, pos) => nodo(name, 'n8n-nodes-base.if', 2, pos, {
  conditions: {
    options: { caseSensitive: true, leftValue: '', typeValidation: 'strict' },
    conditions: [{ id: uid(), leftValue: expresion, rightValue: '', operator: { type: 'boolean', operation: 'true', singleValue: true } }],
    combinator: 'and',
  },
  options: {},
});
// Convierte la respuesta HTTP (fullResponse) en { ok, status, datos, error }
const resultado = (name, pos, ...extra) => nodo(name, 'n8n-nodes-base.code', 2, pos, codigo(
  'const r = $json;',
  'const ok = r.statusCode >= 200 && r.statusCode < 300;',
  'const d = r.body?.detail;',
  'const error = ok ? null : (typeof d === \'string\' ? d : d ? JSON.stringify(d) : `HTTP ${r.statusCode}`);',
  ...extra,
  'return [{ json: { ok, status: r.statusCode, error, ...salida(ok ? r.body : null), documentos_disponibles: r.headers?.[\'x-documentos-disponibles\'] ?? null } }];',
));

const COL = [0, 240, 480, 720, 960, 1200];
let y = -300;
const seccion = (alto) => { const actual = y; y += alto; return actual; };

// --- 0. Instrucciones ------------------------------------------------------------------
nota('Léame', [
  '# Facturación CR — conexión con n8n',
  'Flujo listo para automatizar la facturación electrónica de Costa Rica con este API.',
  '',
  '**Antes de importar:** abra este archivo .json con un editor de texto y reemplace `SU-DOMINIO` por el dominio del servicio (ej. `facturas.miempresa.com`). Es un solo reemplazo para todo el flujo.',
  '',
  '**Después de importar:**',
  '1. Credencial *Header Auth* **Facturación CR (API key)** → Name `X-API-Key`, Value = la API key de la empresa.',
  '2. Credencial *Header Auth* **Facturación CR (clave de mis webhooks)** → Name `X-Clave`, Value = una clave larga que solo conozca su sistema. Protege las URLs de este flujo.',
  '3. Nodo *Verificar firma*: pegue el secreto del webhook del servicio y active `NODE_FUNCTION_ALLOW_BUILTIN=crypto` en n8n.',
  '4. Active el flujo. Guía completa: docs/n8n.md',
].join('\n'), -300, seccion(420), 400, 700);

// --- 1. Cliente por cédula ---------------------------------------------------------------
let y1 = seccion(520);
nota('1. Cliente por cédula', '## 1. Autollenar el cliente\nGET `/webhook/facturacion/cliente?cedula=3101005744`\n\nDatos de Hacienda (inscrito, actividades) + correo si ya es cliente de la empresa.', -300, y1, 160);
webhook('Webhook cliente', 'GET', 'facturacion/cliente', [COL[0], y1 + 220]);
nodo('Validar cédula', 'n8n-nodes-base.code', 2, [COL[1], y1 + 220], codigo(
  "const cedula = String($json.query.cedula || '').replace(/\\D/g, '');",
  'return [{ json: { cedula, valida: cedula.length >= 9 && cedula.length <= 12 } }];'));
siVerdadero('¿Cédula completa?', '={{ $json.valida }}', [COL[2], y1 + 220]);
http('Hacienda: contribuyente', 'GET', `=${BASE}/hacienda/contribuyentes/{{ $json.cedula }}`, [COL[3], y1 + 120]);
http('Mis clientes', 'GET', `${BASE}/catalogo/clientes`, [COL[4], y1 + 120], {
  sendQuery: true, queryParameters: { parameters: [{ name: 'q', value: "={{ $('Validar cédula').first().json.cedula }}" }] } });
nodo('Armar datos del cliente', 'n8n-nodes-base.code', 2, [COL[5], y1 + 120], codigo(
  "const h = $('Hacienda: contribuyente').first().json;",
  "const c = $('Mis clientes').first().json;",
  "const cedula = $('Validar cédula').first().json.cedula;",
  'const hacienda = h.statusCode === 200 ? h.body : null;',
  'const guardado = c.statusCode === 200 && Array.isArray(c.body) ? c.body.find((x) => x.numero_identificacion === cedula) : null;',
  "const activas = (hacienda?.actividades || []).filter((a) => a.estado === 'A' || !a.estado);",
  "const principal = activas.find((a) => a.tipo === 'P') || activas[0];",
  'const situacion = hacienda?.situacion || {};',
  'return [{ json: {',
  '  encontrado: Boolean(hacienda || guardado),',
  "  inscrito: (situacion.estado || '').toLowerCase() === 'inscrito',",
  "  moroso: situacion.moroso === 'SI', omiso: situacion.omiso === 'SI',",
  '  receptor: {',
  '    nombre: hacienda?.nombre || guardado?.nombre || null,',
  '    tipo_identificacion: hacienda?.tipoIdentificacion || guardado?.tipo_identificacion || null,',
  '    numero_identificacion: cedula, correo: guardado?.correo || null,',
  '  },',
  "  codigo_actividad: guardado?.codigo_actividad || (principal ? String(principal.codigo).padStart(6, '0') : null),",
  "  actividades: activas.map((a) => ({ codigo: String(a.codigo).padStart(6, '0'), descripcion: a.descripcion, principal: a.tipo === 'P' })),",
  '  cliente_id: guardado?.id || null,',
  '  datos_guardados_por_falla_de_hacienda: Boolean(hacienda?._respaldo_local),',
  "  mensaje: h.statusCode === 404 ? 'No está inscrito en Hacienda' : h.statusCode >= 400 ? (h.body?.detail || 'No se pudo consultar Hacienda') : null,",
  '} }];'));
responder('Responder cliente', [COL[5] + 240, y1 + 120]);
nodo('Cédula incompleta', 'n8n-nodes-base.code', 2, [COL[3], y1 + 340], codigo(
  "return [{ json: { encontrado: false, mensaje: 'La cédula debe tener entre 9 y 12 dígitos', http_status: 422 } }];"));
responder('Responder cédula incompleta', [COL[4], y1 + 340]);
cadena('Webhook cliente', 'Validar cédula', '¿Cédula completa?');
unir('¿Cédula completa?', 'Hacienda: contribuyente', 0);
unir('¿Cédula completa?', 'Cédula incompleta', 1);
cadena('Hacienda: contribuyente', 'Mis clientes', 'Armar datos del cliente', 'Responder cliente');
cadena('Cédula incompleta', 'Responder cédula incompleta');

// --- 2. Producto ---------------------------------------------------------------------------
let y2 = seccion(400);
nota('2. Buscar producto', '## 2. Buscar producto o servicio\nGET `/webhook/facturacion/producto?q=martillo`\n\nProductos de la empresa (precio, IVA, existencia, descuentos no incluidos) y sugerencias del catálogo CABYS.', -300, y2, 160);
webhook('Webhook producto', 'GET', 'facturacion/producto', [COL[0], y2 + 220]);
http('Mis productos', 'GET', `${BASE}/catalogo/productos`, [COL[1], y2 + 220], {
  sendQuery: true, queryParameters: { parameters: [{ name: 'q', value: '={{ $json.query.q }}' }, { name: 'limite', value: '10' }] } });
http('CABYS', 'GET', `${BASE}/hacienda/cabys`, [COL[2], y2 + 220], {
  sendQuery: true, queryParameters: { parameters: [{ name: 'q', value: "={{ $('Webhook producto').first().json.query.q }}" }, { name: 'top', value: '10' }] } });
nodo('Armar resultados', 'n8n-nodes-base.code', 2, [COL[3], y2 + 220], codigo(
  "const q = $('Webhook producto').first().json.query.q || '';",
  "const p = $('Mis productos').first().json;",
  "const c = $('CABYS').first().json;",
  "const TARIFA = { 13: '08', 8: '07', 4: '04', 2: '03', 1: '02', 0.5: '09' };",
  'const productos = (p.statusCode === 200 && Array.isArray(p.body) ? p.body : []).map((x) => ({',
  "  origen: 'mis_productos', producto_id: x.id, codigo: x.codigo, descripcion: x.descripcion, categoria: x.categoria,",
  '  codigo_cabys: x.codigo_cabys, unidad_medida: x.unidad_medida, precio_unitario: x.precio_unitario,',
  '  codigo_tarifa_iva: x.codigo_tarifa_iva, es_combo: x.es_combo,',
  '  existencia: x.es_combo ? x.combo_disponible : x.controla_inventario ? x.existencia : null,',
  '}));',
  'const lista = c.statusCode === 200 ? (Array.isArray(c.body) ? c.body : c.body.cabys || []) : [];',
  'const cabys = lista.slice(0, 10).map((x) => ({',
  "  origen: 'cabys', codigo_cabys: x.codigo, descripcion: x.descripcion, impuesto: x.impuesto,",
  '  codigo_tarifa_iva: TARIFA[Number(x.impuesto)] || null,',
  '}));',
  'return [{ json: { q, productos, cabys } }];'));
responder('Responder productos', [COL[4], y2 + 220]);
cadena('Webhook producto', 'Mis productos', 'CABYS', 'Armar resultados', 'Responder productos');

// --- 3. Emitir -------------------------------------------------------------------------------
let y3 = seccion(380);
nota('3. Emitir', '## 3. Emitir factura, tiquete o nota\nPOST `/webhook/facturacion/emitir` con el JSON del comprobante (igual que `POST /facturas`).\n\n**Siempre** envíe `referencia_externa` única (ID del pedido o de la conversación): si n8n reintenta, no se duplica ni se cobra dos veces.', -300, y3, 180);
webhook('Webhook emitir', 'POST', 'facturacion/emitir', [COL[0], y3 + 220]);
http('Emitir en el servicio', 'POST', `${BASE}/facturas`, [COL[1], y3 + 220], {
  sendBody: true, specifyBody: 'json', jsonBody: '={{ JSON.stringify($json.body) }}' });
resultado('Resultado de la emisión', [COL[2], y3 + 220],
  'const salida = (b) => ({ factura_id: b?.factura_id ?? null, clave: b?.clave ?? null, estado: b?.estado ?? null, http_status: r.statusCode });');
responder('Responder emisión', [COL[3], y3 + 220]);
cadena('Webhook emitir', 'Emitir en el servicio', 'Resultado de la emisión', 'Responder emisión');

// --- 4. Consultar factura y PDF ------------------------------------------------------------
let y4 = seccion(520);
nota('4. Consultar', '## 4. Consultar una factura y su PDF\nGET `/webhook/facturacion/factura?id=…` o `?referencia=PEDIDO-123`\nGET `/webhook/facturacion/pdf?id=…` → devuelve el PDF (para adjuntarlo en WhatsApp o correo).', -300, y4, 160);
webhook('Webhook consultar', 'GET', 'facturacion/factura', [COL[0], y4 + 220]);
http('Buscar factura', 'GET',
  `={{ $json.query.id ? '${BASE}/facturas/' + encodeURIComponent($json.query.id) : '${BASE}/facturas?referencia_externa=' + encodeURIComponent($json.query.referencia || '') }}`,
  [COL[1], y4 + 220]);
nodo('Armar factura', 'n8n-nodes-base.code', 2, [COL[2], y4 + 220], codigo(
  "const q = $('Webhook consultar').first().json.query || {};",
  "if (!q.id && !q.referencia) return [{ json: { ok: false, http_status: 422, error: 'Indique ?id= o ?referencia=' } }];",
  'const r = $json;',
  'let f = r.body;',
  'if (Array.isArray(f)) f = f[0] || null;',
  'const ok = r.statusCode === 200 && Boolean(f);',
  'if (!ok) return [{ json: { ok: false, http_status: r.statusCode === 200 ? 404 : r.statusCode, error: r.body?.detail || \'No se encontró el comprobante\' } }];',
  'return [{ json: {',
  '  ok: true, factura_id: f.factura_id, referencia_externa: f.referencia_externa, clave: f.clave,',
  '  consecutivo: f.numero_consecutivo, tipo_documento: f.tipo_documento, fecha: f.fecha_emision,',
  '  cliente: f.receptor_nombre, identificacion: f.receptor_identificacion,',
  '  moneda: f.moneda, impuesto: f.monto_impuesto, total: f.monto_total,',
  "  estado: f.estado, aceptado: f.estado === 'ACEPTADO', rechazado: f.estado === 'RECHAZADO',",
  '  mensaje_hacienda: f.mensaje_hacienda, correo_enviado: f.correo_enviado,',
  '} }];'));
responder('Responder factura', [COL[3], y4 + 220]);
cadena('Webhook consultar', 'Buscar factura', 'Armar factura', 'Responder factura');
webhook('Webhook PDF', 'GET', 'facturacion/pdf', [COL[0], y4 + 380]);
nodo('Descargar PDF', 'n8n-nodes-base.httpRequest', 4.2, [COL[1], y4 + 380], {
  method: 'GET', url: `=${BASE}/facturas/{{ encodeURIComponent($json.query.id || 'sin-id') }}/pdf`,
  authentication: 'genericCredentialType', genericAuthType: 'httpHeaderAuth',
  options: { response: { response: { responseFormat: 'file', outputPropertyName: 'data', fullResponse: true, neverError: true } } },
}, { credentials: CRED_API });
siVerdadero('¿PDF encontrado?', '={{ $json.statusCode === 200 }}', [COL[2], y4 + 380]);
nodo('Responder PDF', 'n8n-nodes-base.respondToWebhook', 1.1, [COL[3], y4 + 340], { respondWith: 'binary', options: {} });
nodo('PDF no disponible', 'n8n-nodes-base.code', 2, [COL[3], y4 + 460], codigo(
  "return [{ json: { ok: false, http_status: $json.statusCode === 404 || $json.statusCode === 422 ? 404 : $json.statusCode, error: 'No se encontró el comprobante (revise ?id=)' } }];"));
responder('Responder PDF no disponible', [COL[4], y4 + 460]);
cadena('Webhook PDF', 'Descargar PDF', '¿PDF encontrado?');
unir('¿PDF encontrado?', 'Responder PDF', 0);
unir('¿PDF encontrado?', 'PDF no disponible', 1);
cadena('PDF no disponible', 'Responder PDF no disponible');

// --- 5. Acciones -----------------------------------------------------------------------------
let y5 = seccion(560);
nota('5. Acciones', [
  '## 5. Acciones (un solo punto de entrada)',
  'POST `/webhook/facturacion/accion` con `{ "accion": "…", … }`:',
  '- `anular` {factura_id, razon, codigo?} → nota de crédito por el total (codigo 01 normal, 13 error material)',
  '- `reenviar_correo` {factura_id, destinatarios?}',
  '- `consultar_hacienda` / `reintentar` {factura_id}',
  '- `registrar_pago` {factura_id, monto, medio_pago?} (crédito 08/10)',
  '- `crear_proforma` {datos, vence?} · `convertir_proforma` {proforma_id} · `anular_proforma` {proforma_id}',
  '- `registrar_recibida` {xml_base64} · `aceptar_recibida` / `rechazar_recibida` {documento_id, comentario}',
].join('\n'), -300, y5, 300, 620);
webhook('Webhook acción', 'POST', 'facturacion/accion', [COL[0], y5 + 360]);
nodo('Preparar acción', 'n8n-nodes-base.code', 2, [COL[1], y5 + 360], codigo(
  `const BASE = '${BASE}';`,
  'const b = $json.body || {};',
  'const id = encodeURIComponent(b.factura_id || b.proforma_id || b.documento_id || \'\');',
  'const acciones = {',
  "  anular: ['POST', `/facturas/${id}/anular`, { razon: b.razon, codigo: b.codigo || '01', referencia_externa: b.referencia_externa }],",
  "  reenviar_correo: ['POST', `/facturas/${id}/correo`, { destinatarios: b.destinatarios || null }],",
  "  consultar_hacienda: ['POST', `/facturas/${id}/consultar`, {}],",
  "  reintentar: ['POST', `/facturas/${id}/reenviar`, {}],",
  "  registrar_pago: ['POST', `/facturas/${id}/recibo-pago`, { monto: String(b.monto), medios_pago: [{ tipo: b.medio_pago || '04' }], referencia_externa: b.referencia_externa }],",
  "  crear_proforma: ['POST', '/borradores', { clase: 'proforma', datos: b.datos, vence: b.vence || null }],",
  "  convertir_proforma: ['POST', `/borradores/${id}/emitir`, {}],",
  "  anular_proforma: ['DELETE', `/borradores/${id}`, null],",
  "  registrar_recibida: ['POST', '/recepcion', { xml_base64: b.xml_base64, respuesta_hacienda_base64: b.respuesta_hacienda_base64 }],",
  "  aceptar_recibida: ['POST', `/recepcion/${id}/mensaje`, { mensaje: '1', condicion_impuesto: b.condicion_impuesto || '01', detalle_mensaje: b.comentario || null }],",
  "  rechazar_recibida: ['POST', `/recepcion/${id}/mensaje`, { mensaje: '3', detalle_mensaje: b.comentario }],",
  '};',
  'const a = acciones[b.accion];',
  "if (!a) return [{ json: { valida: false, error: `Acción desconocida: ${b.accion}. Use: ${Object.keys(acciones).join(', ')}` } }];",
  "if (b.accion === 'rechazar_recibida' && !b.comentario) return [{ json: { valida: false, error: 'Indique el motivo del rechazo en comentario' } }];",
  "if (!id && !['crear_proforma', 'registrar_recibida'].includes(b.accion)) return [{ json: { valida: false, error: 'Falta el id (factura_id, proforma_id o documento_id)' } }];",
  'const [method, ruta, cuerpo] = a;',
  'return [{ json: { valida: true, accion: b.accion, method, url: BASE + ruta, cuerpo: cuerpo ? JSON.stringify(cuerpo) : \'{}\' } }];'));
siVerdadero('¿Acción válida?', '={{ $json.valida }}', [COL[2], y5 + 360]);
http('Ejecutar acción', '={{ $json.method }}', '={{ $json.url }}', [COL[3], y5 + 280], {
  sendBody: true, specifyBody: 'json', jsonBody: '={{ $json.cuerpo }}' });
resultado('Resultado de la acción', [COL[4], y5 + 280],
  "const accion = $('Preparar acción').first().json.accion;",
  'const salida = (b) => ({ accion, http_status: r.statusCode, resultado: b });');
responder('Responder acción', [COL[5], y5 + 280]);
nodo('Acción inválida', 'n8n-nodes-base.code', 2, [COL[3], y5 + 460], codigo(
  'return [{ json: { ok: false, http_status: 422, error: $json.error } }];'));
responder('Responder acción inválida', [COL[4], y5 + 460]);
cadena('Webhook acción', 'Preparar acción', '¿Acción válida?');
unir('¿Acción válida?', 'Ejecutar acción', 0);
unir('¿Acción válida?', 'Acción inválida', 1);
cadena('Ejecutar acción', 'Resultado de la acción', 'Responder acción');
cadena('Acción inválida', 'Responder acción inválida');

// --- 6. Facturas de proveedores y saldo --------------------------------------------------------
let y6 = seccion(440);
nota('6. Consultas', '## 6. Facturas de proveedores por responder y saldo\nGET `/webhook/facturacion/recibidas` → lista para aceptar o rechazar (sección 5).\nGET `/webhook/facturacion/saldo` → documentos disponibles y servicios.', -300, y6, 160);
webhook('Webhook recibidas', 'GET', 'facturacion/recibidas', [COL[0], y6 + 220]);
http('Recibidas pendientes', 'GET', `${BASE}/recepcion`, [COL[1], y6 + 220], {
  sendQuery: true, queryParameters: { parameters: [{ name: 'pendientes', value: 'true' }, { name: 'limit', value: '100' }] } });
resultado('Armar recibidas', [COL[2], y6 + 220],
  'const salida = (b) => ({ http_status: r.statusCode, documentos: (b || []).map((d) => ({',
  '  documento_id: d.id, proveedor: d.proveedor_nombre, identificacion: d.proveedor_identificacion, fecha: d.fecha_emision,',
  '  moneda: d.moneda, impuesto: d.total_impuesto, total: d.total_comprobante, firma_valida: d.firma_valida, origen: d.origen,',
  '})) });');
responder('Responder recibidas', [COL[3], y6 + 220]);
cadena('Webhook recibidas', 'Recibidas pendientes', 'Armar recibidas', 'Responder recibidas');
webhook('Webhook saldo', 'GET', 'facturacion/saldo', [COL[0], y6 + 360]);
http('Consultar saldo', 'GET', `${BASE}/saldo`, [COL[1], y6 + 360]);
resultado('Armar saldo', [COL[2], y6 + 360],
  'const salida = (b) => ({ http_status: r.statusCode, disponible: b?.disponible ?? null, alerta: b?.alerta ?? null,',
  '  por_vencer: b?.por_vencer ?? null, usados_este_mes: b?.usados_este_mes ?? null, servicios: b?.servicios ?? [] });');
responder('Responder saldo', [COL[3], y6 + 360]);
cadena('Webhook saldo', 'Consultar saldo', 'Armar saldo', 'Responder saldo');

// --- 7. Cierre mensual para el contador -------------------------------------------------------------
let y7 = seccion(380);
nota('7. Contador', '## 7. Cierre del mes para el contador (automático)\nEl día 1 a las 7:00 prepara el resumen de IVA y los libros de ventas y compras del mes anterior (Excel).\n\nConecte al final un nodo **Gmail / Send Email / Google Drive** para enviárselos al contador.', -300, y7, 180);
nodo('Día 1 de cada mes', 'n8n-nodes-base.scheduleTrigger', 1.2, [COL[0], y7 + 220], {
  rule: { interval: [{ field: 'months', monthsInterval: 1, triggerAtDayOfMonth: 1, triggerAtHour: 7 }] } });
nodo('Mes anterior', 'n8n-nodes-base.code', 2, [COL[1], y7 + 220], codigo(
  'const hoy = new Date();',
  'const d = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);',
  'return [{ json: { anio: d.getFullYear(), mes: d.getMonth() + 1, periodo: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, \'0\')}` } }];'));
http('Resumen de IVA', 'GET', `=${BASE}/reportes/resumen-iva?anio={{ $json.anio }}&mes={{ $json.mes }}`, [COL[2], y7 + 220]);
const archivo = (name, ruta, pos) => nodo(name, 'n8n-nodes-base.httpRequest', 4.2, pos, {
  method: 'GET', url: `=${BASE}/reportes/${ruta}?anio={{ $('Mes anterior').first().json.anio }}&mes={{ $('Mes anterior').first().json.mes }}`,
  authentication: 'genericCredentialType', genericAuthType: 'httpHeaderAuth',
  options: { response: { response: { responseFormat: 'file', outputPropertyName: 'data' } } },
}, { credentials: CRED_API });
archivo('Libro de ventas', 'ventas.csv', [COL[3], y7 + 220]);
archivo('Libro de compras', 'compras.csv', [COL[4], y7 + 220]);
nodo('Armar envío al contador', 'n8n-nodes-base.code', 2, [COL[5], y7 + 220], codigo(
  "const { periodo } = $('Mes anterior').first().json;",
  "const iva = $('Resumen de IVA').first().json.body || {};",
  "const ventas = $('Libro de ventas').first().binary.data;",
  "const compras = $('Libro de compras').first().binary.data;",
  'ventas.fileName = `ventas-${periodo}.csv`;',
  'compras.fileName = `compras-${periodo}.csv`;',
  'const texto = [',
  '  `Cierre de ${periodo}`,',
  '  `IVA débito (ventas): ${iva.iva_debito_fiscal}`,',
  '  `IVA crédito (compras): ${iva.iva_credito_fiscal}`,',
  '  `IVA neto estimado: ${iva.iva_neto_estimado}`,',
  "  'Adjuntos: libros de ventas y compras (Excel).',",
  "].join('\\n');",
  'return [{ json: { asunto: `Facturación ${periodo}: libros e IVA`, texto, resumen_iva: iva }, binary: { ventas, compras } }];'));
nodo('Enviar al contador (agregue Gmail o correo)', 'n8n-nodes-base.noOp', 1, [COL[5] + 240, y7 + 220], {});
cadena('Día 1 de cada mes', 'Mes anterior', 'Resumen de IVA', 'Libro de ventas', 'Libro de compras', 'Armar envío al contador',
  'Enviar al contador (agregue Gmail o correo)');

// --- 8. Avisos del servicio ------------------------------------------------------------------------------
let y8 = seccion(700);
nota('8. Avisos', [
  '## 8. Avisos del servicio (webhook firmado)',
  'Configure esta URL de **producción** en la ficha de la empresa → Integración → Webhook, y pegue el secreto en *Verificar firma*.',
  '',
  'Eventos: `comprobante.aceptado` · `comprobante.rechazado` · `comprobante.error_comunicacion` · `mensaje_receptor.*` · `saldo.bajo` · `saldo.agotado` · `paquete.por_vencer` · `suscripcion.por_vencer` · `suscripcion.vencida` · `certificado.por_vencer`',
].join('\n'), -300, y8, 220, 620);
nodo('Webhook avisos', 'n8n-nodes-base.webhook', 2, [COL[0], y8 + 320],
  { httpMethod: 'POST', path: 'facturacion/avisos', responseMode: 'onReceived', options: { rawBody: true } }, { webhookId: uid() });
nodo('Verificar firma', 'n8n-nodes-base.code', 2, [COL[1], y8 + 320], codigo(
  "const crypto = require('crypto');",
  "const SECRETO = 'PEGUE_AQUI_EL_SECRETO_DEL_WEBHOOK';",
  'const item = $input.first();',
  "const firma = item.json.headers['x-facturacion-firma'] || '';",
  'let cuerpo;',
  'try {',
  "  cuerpo = await this.helpers.getBinaryDataBuffer(0, 'data');",
  '} catch (e) {',
  '  cuerpo = Buffer.from(JSON.stringify(item.json.body));',
  '}',
  "const esperada = 'sha256=' + crypto.createHmac('sha256', SECRETO).update(cuerpo).digest('hex');",
  'const valida = firma.length === esperada.length && crypto.timingSafeEqual(Buffer.from(firma), Buffer.from(esperada));',
  "const evento = item.json.headers['x-facturacion-evento'] || item.json.body?.evento || '';",
  "const grupo = evento === 'comprobante.aceptado' ? 'aceptado'",
  "  : ['comprobante.rechazado', 'mensaje_receptor.rechazado'].includes(evento) ? 'rechazado'",
  "  : evento.startsWith('saldo.') || evento.startsWith('paquete.') || evento.startsWith('suscripcion.') || evento.startsWith('certificado.') ? 'servicio'",
  "  : 'otro';",
  'return [{ json: { valida, evento, grupo, datos: item.json.body } }];'));
siVerdadero('¿Firma válida?', '={{ $json.valida }}', [COL[2], y8 + 320]);
nodo('Descartar (firma inválida)', 'n8n-nodes-base.noOp', 1, [COL[3], y8 + 520], {});
siVerdadero('¿Aceptado por Hacienda?', "={{ $json.grupo === 'aceptado' }}", [COL[3], y8 + 240]);
nodo('Aceptado: avisar al cliente (WhatsApp, correo, CRM)', 'n8n-nodes-base.noOp', 1, [COL[4], y8 + 160], {});
siVerdadero('¿Rechazado?', "={{ $json.grupo === 'rechazado' }}", [COL[4], y8 + 320]);
nodo('Rechazado: revisar mensaje_hacienda y corregir', 'n8n-nodes-base.noOp', 1, [COL[5], y8 + 240], {});
siVerdadero('¿Aviso del servicio?', "={{ $json.grupo === 'servicio' }}", [COL[5], y8 + 400]);
nodo('Saldo, vencimientos o certificado: avisar al encargado', 'n8n-nodes-base.noOp', 1, [COL[5] + 240, y8 + 320], {});
nodo('Otros eventos', 'n8n-nodes-base.noOp', 1, [COL[5] + 240, y8 + 480], {});
cadena('Webhook avisos', 'Verificar firma', '¿Firma válida?');
unir('¿Firma válida?', '¿Aceptado por Hacienda?', 0);
unir('¿Firma válida?', 'Descartar (firma inválida)', 1);
unir('¿Aceptado por Hacienda?', 'Aceptado: avisar al cliente (WhatsApp, correo, CRM)', 0);
unir('¿Aceptado por Hacienda?', '¿Rechazado?', 1);
unir('¿Rechazado?', 'Rechazado: revisar mensaje_hacienda y corregir', 0);
unir('¿Rechazado?', '¿Aviso del servicio?', 1);
unir('¿Aviso del servicio?', 'Saldo, vencimientos o certificado: avisar al encargado', 0);
unir('¿Aviso del servicio?', 'Otros eventos', 1);

// --- Validación y salida ------------------------------------------------------------------------------------
const nombres = new Set(nodes.map((n) => n.name));
if (nombres.size !== nodes.length) throw new Error('Nombres de nodo repetidos');
for (const [desde, { main }] of Object.entries(connections)) {
  if (!nombres.has(desde)) throw new Error(`Conexión desde nodo inexistente: ${desde}`);
  for (const salida of main) for (const c of salida) if (!nombres.has(c.node)) throw new Error(`Conexión a nodo inexistente: ${c.node}`);
}
const flujo = {
  name: 'Facturación CR — conexión completa con el API',
  nodes, connections, active: false, settings: { executionOrder: 'v1' }, pinData: {},
  meta: { templateCredsSetupCompleted: false },
};
const salida = process.argv[2] || require('path').join(__dirname, 'flujo-facturacion-cr.json');
fs.writeFileSync(salida, `${JSON.stringify(flujo, null, 2)}\n`);
console.log(`${nodes.length} nodos, ${Object.keys(connections).length} conexiones → ${salida}`);
