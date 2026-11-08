# Guía completa del sistema — Facturación Electrónica CR (v4.4)

Documento para presentar el sistema al equipo: qué es, cómo está construido,
cómo se entra, cómo fluye una factura de punta a punta y cómo se opera.

> Las **claves reales** no están en este documento (se guardan aparte, fuera
> del repositorio). Aquí solo se explica **dónde** está cada una y **para qué** sirve.

---

## 1. Qué es, en una frase

Una plataforma que **emite y recibe comprobantes electrónicos ante el
Ministerio de Hacienda de Costa Rica (versión 4.4)** para **muchas empresas a
la vez**, pensada para venderse a **contadores**: cada empresa compra
**paquetes de documentos**. Quien se conecta por API paga **solo documentos**;
quien usa el **sistema en línea** (panel web) paga además su mensualidad.

### El modelo de negocio

| Se cobra | Cómo funciona | Qué pasa si no paga |
|---|---|---|
| **Documentos** (paquetes) | Cada factura, tiquete, nota, recibo de pago o respuesta a un proveedor descuenta **1**. | Sin saldo no puede emitir (error `402`). |
| **Conexión por API** | Para empresas que ya tienen un sistema (POS, ERP, n8n). **Sin mensualidad**: se paga con documentos. | Si se desactiva su casilla, sus llaves responden `403`. |
| **Mensualidad del panel web** | Para empresas sin sistema: facturan desde el navegador. Es un servicio adicional. | Al vencer (+ días de gracia) sus usuarios no entran al panel. |

Reglas del cobro:
- Se cobra en la **misma operación** que crea el documento: si la emisión falla antes de firmarse, **no se cobra**.
- Reintentos y reenvíos **no** cobran de nuevo.
- Si Hacienda **rechaza** el documento, el crédito **no se devuelve** (ya se firmó y se envió).
- El pago es manual (SINPE / transferencia); el administrador lo registra en el panel.

---

## 2. Arquitectura (las piezas)

```
                    Internet (HTTPS)
                          │
                    ┌─────▼─────┐
                    │   Caddy   │  certificado HTTPS automático (solo producción)
                    └─────┬─────┘
                          │
   Panel web (navegador)  │   Sistemas de clientes (POS/ERP/n8n)
            └─────────────┼─────────────┘
                    ┌─────▼─────┐
                    │    API    │  FastAPI (Python 3.12) — puerto 8000
                    │  + Panel  │  el panel son archivos HTML/JS servidos en /panel/
                    └──┬─────┬──┘
                       │     │ encola tareas
              ┌────────▼┐   ┌▼────────┐
              │PostgreSQL│   │  Redis  │
              │ (datos)  │   │ (cola)  │
              └────────▲┘   └┬────────┘
                       │     │
                 ┌─────┴─────▼─────┐        ┌──────────────────────┐
                 │ Worker (Celery) │◄──────►│  Hacienda (API v1)   │
                 │ Beat  (Celery)  │        │  sandbox / producción│
                 └─────────────────┘        └──────────────────────┘
```

| Contenedor | Qué hace |
|---|---|
| **api** | Recibe las solicitudes, valida, arma el XML, lo **firma**, lo guarda y encola el envío. Al arrancar aplica las migraciones de la base (`alembic upgrade head`). También sirve el panel web. |
| **worker** | Envía los documentos a Hacienda, consulta su estado, manda correos y webhooks. Trabaja en segundo plano para que el usuario no espere. |
| **beat** | Reloj de tareas programadas (ver sección 8). |
| **db** | PostgreSQL 16: empresas, comprobantes, usuarios, saldo, bitácora, etc. |
| **redis** | Cola de mensajes entre la API y el worker; también límites de uso y caché. |
| **caddy** *(solo prod)* | Servidor web público con HTTPS automático (Let's Encrypt). |
| **respaldo** *(solo prod)* | Copia diaria de la base de datos en la carpeta `respaldos/` (se guardan 14 días). |

Todo corre con **Docker Compose**: `docker-compose.yml` (base) y
`docker-compose.prod.yml` (agrega Caddy y respaldos para producción).

### Organización del código

| Carpeta | Contenido |
|---|---|
| `api/main.py` | Arranque de la aplicación, cabeceras de seguridad, rutas. |
| `api/routes/` | Los **endpoints** (puertas de entrada): `facturas`, `recepcion`, `emisores`, `auth`, `saldo`, `catalogo`, `hacienda`, `reportes`, `callback`, `health`. |
| `api/services/` | La **lógica**: `emision` (arma y firma), `xml_generator`, `firma` (XAdES-EPES), `clave_generator` (clave de 50 dígitos), `hacienda_client` (envío), `saldo`, `suscripciones`, `inventario`, `pdf`, `correo`, `webhooks`, `cifrado`, `usuarios`, `dos_pasos`, `auditoria`… |
| `api/models/` | Tablas de la base (`database.py`) y validación del JSON de entrada (`schemas.py`). |
| `api/panel/` | El panel web (HTML + JavaScript sin frameworks). Una "vista" por pantalla en `js/vistas/`. |
| `api/cli.py` | Comandos de consola (crear usuarios, llaves, etc.). |
| `workers/` | Tareas en segundo plano (`tasks.py`) y su calendario (`celery_app.py`). |
| `config/settings.py` | Toda la configuración; se lee del archivo `.env`. |
| `migrations/` | Cambios de estructura de la base (9 versiones). |
| `xsd/` | Esquemas oficiales de Hacienda para validar cada XML antes de enviarlo. |
| `tests/` | ~195 pruebas automáticas. |
| `deploy/` | Configuración de Caddy y script de respaldo. |
| `docs/` | Manuales (administrador, integración, despliegue, n8n, entrega al cliente). |

---

## 3. Cómo se entra al sistema

Hay **tres formas de acceso**, cada una para un público distinto:

### 3.1 Panel web (personas)

- **En la computadora local:** `http://localhost:8000/panel/` (también `http://localhost:8000/` redirige ahí).
- **En producción:** `https://<dominio>/panel/`.
- Se entra con **correo + contraseña**. Si el usuario tiene verificación en dos pasos, luego pide el **código de 6 dígitos** de la app (Google/Microsoft Authenticator, Authy).

**Importante:** el sistema **no trae ningún usuario por defecto**. El primer
administrador se crea desde la consola del servidor:

```bash
docker compose run --rm api python -m api.cli crear-usuario --email usted@correo.cr --nombre "Su nombre" --admin
```

El comando pide la contraseña (mínimo 10 caracteres) dos veces. Después,
desde el panel (**Usuarios → + Nuevo usuario**) se crean los demás.

Las contraseñas se guardan con **scrypt** (un hash de un solo sentido): **nadie,
ni siquiera el administrador, puede ver una contraseña**. Si alguien la olvida,
se le asigna una nueva o se crea otro usuario.

Tipos de usuario:

| Tipo | Ve | Para quién |
|---|---|---|
| **Administrador** | Todas las empresas + menú *Empresas, Planes y ventas, Usuarios, Bitácora*. | Nosotros / el contador. |
| **Usuario de una empresa** | Solo su empresa. | El cliente final del contador. |

Protecciones del inicio de sesión:
- 5 intentos fallidos → bloqueo de 15 minutos (`MAX_INTENTOS_LOGIN`, `MINUTOS_BLOQUEO_LOGIN`).
- Máximo 20 intentos de login por minuto por IP.
- La sesión dura 8 horas (`SESION_HORAS`).
- En **producción**, los administradores están **obligados** a activar la verificación en dos pasos la primera vez que entran (en pruebas es opcional).

### 3.2 API key (sistemas)

Los sistemas (POS, ERP, n8n) no usan usuario y contraseña: envían una
**API key** en el encabezado `X-API-Key` de cada solicitud.

| Tipo de llave | Alcance | Cómo se crea |
|---|---|---|
| **Llave de administrador de arranque** | Todo. Para operar sobre una empresa se agrega el encabezado `X-Emisor-Id`. | Variable `API_KEYS` del `.env`. |
| **Llave de administrador** | Igual que la anterior. | `python -m api.cli crear-api-key --nombre "X" --admin` |
| **Llave de una empresa** | Solo esa empresa. Requiere la mensualidad de API vigente. | Panel → Empresas → ficha → *Integración con otros sistemas → Nueva llave*. |

Las llaves empiezan con `fcr_`, se muestran **una sola vez** al crearlas y en
la base se guarda solo su huella (SHA-256). Si se pierde, se revoca y se crea otra.

### 3.3 Documentación interactiva de la API

- Local / pruebas: `http://localhost:8000/docs` (Swagger) y `/redoc`.
- En producción está oculta salvo que `DOCS_PUBLICAS=true`.
- En `/docs` se presiona **Authorize**, se pega la API key y se pueden probar todos los endpoints desde el navegador. Es la mejor forma de mostrarle la API al equipo.

---

## 4. Cómo levantar el sistema en una computadora (demostración)

Requisito: **Docker Desktop** instalado y **abierto** (el ícono de la ballena en verde).

```bash
cd C:\Proyectos\proyecto-facturacion-cr

# 1) Arrancar todo (la primera vez tarda porque construye la imagen)
docker compose up -d --build

# 2) Ver que los 5 contenedores estén "running" / "healthy"
docker compose ps

# 3) Si no hay usuario aún, crear el administrador
docker compose run --rm api python -m api.cli crear-usuario --email admin@demo.cr --nombre "Admin" --admin

# 4) Abrir en el navegador
#    http://localhost:8000/panel/   (panel)
#    http://localhost:8000/docs     (API)
#    http://localhost:8000/api/v1/health   (debe responder ok)
```

Comandos útiles:

| Para | Comando |
|---|---|
| Ver registros (logs) de la API | `docker compose logs -f api` |
| Ver qué hace el worker con Hacienda | `docker compose logs -f worker` |
| Detener todo (sin borrar datos) | `docker compose down` |
| Correr las pruebas automáticas | `docker compose run --rm api sh -c "pip install -q --user -r requirements-dev.txt && python -m pytest -q"` |
| Quitar la verificación en dos pasos a alguien | `docker compose exec api python -m api.cli reiniciar-2fa --email x@correo.cr` |

> ⚠️ **Nunca** usar `docker compose down -v`: la `-v` borra el volumen de la base de datos (todas las empresas y facturas).

---

## 5. El recorrido de una factura, paso a paso

Este es el corazón del sistema. Cuando alguien presiona **Firmar y enviar a
Hacienda** en el panel (o un POS hace `POST /api/v1/facturas`):

### Fase A — En la API (el usuario espera; dura menos de un segundo)

1. **Autenticación**: ¿quién es? (sesión del panel o API key) y ¿sobre qué empresa opera?
2. **Idempotencia**: si trae `referencia_externa` que ya existe, devuelve la factura existente en vez de duplicarla (protege contra reintentos del POS).
3. **¿La empresa está lista?**: tiene certificado y credenciales de Hacienda.
4. **¿Tiene saldo?**: si no → `402 Saldo agotado`.
5. **Validaciones de Hacienda antes de firmar**: que cada código **CABYS** exista en el catálogo oficial y que las **exoneraciones** apliquen.
6. **Tipo de cambio**: si es en dólares/euros y no lo indicaron, se toma automáticamente (el del día de la venta si es contingencia).
7. **Consecutivo**: número siguiente por empresa + sucursal + terminal + tipo de documento.
8. **Clave numérica de 50 dígitos**: país (506) + fecha + cédula + consecutivo + situación + código de seguridad.
9. **XML v4.4**: con todos los cálculos (IVA por tarifa, descuentos, exoneraciones, otros cargos, totales).
10. **Firma digital XAdES-EPES** con el certificado `.p12` de **esa** empresa (se descifra en memoria solo para firmar) y **verificación** de la firma recién hecha.
11. **Validación contra el XSD oficial** de Hacienda.
12. **Inventario**: si los productos controlan existencias, las descuenta (si no alcanza, no emite).
13. **Cobro**: descuenta 1 documento del saldo.
14. Se guarda todo con estado **PENDIENTE** y se **encola** el envío. El usuario ya recibe la respuesta.

### Fase B — En el worker (segundo plano)

15. Obtiene un **token** de Hacienda con el usuario/contraseña del API de esa empresa (OpenID Connect).
16. **Envía** el XML firmado → estado **ENVIADO**.
17. Hacienda procesa y responde de dos maneras (se usan ambas):
    - **Callback**: Hacienda llama a `https://<dominio>/api/v1/hacienda/callback/<CALLBACK_TOKEN>`. El sistema **no confía** en lo que dice el aviso: solo lo toma como señal y **consulta** el estado real a Hacienda.
    - **Consulta activa**: un minuto después del envío, y cada 10 minutos para lo que siga pendiente.
18. Estado final: **ACEPTADO** o **RECHAZADO** (con el motivo de Hacienda).
19. Si fue aceptado: se envía por **correo** al cliente el XML, la respuesta de Hacienda y el **PDF con código QR**; se avisa por **webhook** si la empresa lo configuró.
20. Si fue rechazado: se **revierte el inventario** automáticamente.

### Estados posibles

```
PENDIENTE ──► ENVIADO ──► ACEPTADO
                │    └──► RECHAZADO
                ▼
       ERROR_COMUNICACION ──(se reintenta solo cada 5 min)──► ENVIADO
```

Todo queda en la **bitácora del comprobante** (Comprobantes → detalle → eventos).

---

## 6. Qué puede hacer el sistema

| Área | Funciones |
|---|---|
| **Comprobantes** | Factura (01), Nota de débito (02), Nota de crédito (03), Tiquete (04), Factura de compra (08), Factura de exportación (09), Recibo electrónico de pago (10). |
| **Anulación** | En un paso: genera la nota de crédito que anula el comprobante. Se elige el motivo: anulación normal (código 01, cuenta en el mes de la nota) o error material (código 13, cuenta en el mes de la factura original). |
| **Códigos de referencia 2026** | Notas 9 y 10 de Anexos y Estructuras 4.4 (vigentes desde el 1-11-2026): códigos 13 a 17 y tipos 19 y 20. El reporte de IVA cuenta las notas 13/14 en el mes de la factura original y avisa qué declaraciones rectificar. |
| **Contingencia** | Situación 2 (sustituye papel) y 3 (sin internet), con la fecha real de la venta (máx. 30 días). |
| **Impuestos** | Todas las tarifas de IVA, exentos, no sujetos, exoneraciones, bienes usados, IVA cobrado en fábrica, IVA devuelto, selectivo de consumo, impuestos específicos, descuentos, 10 % de servicio. |
| **Recepción** | Subir el XML de la factura de un proveedor, verificar su firma y responder: **aceptar, aceptar parcialmente o rechazar** (Mensaje Receptor). |
| **Consultas a Hacienda** | Contribuyentes (avisa si es moroso u omiso), actividades, exoneraciones, CABYS, tipo de cambio. Se guardan localmente y se refrescan cada 15 días; si Hacienda está caída se usan los datos guardados. |
| **Reportes** | Resumen de IVA mensual (insumo para la D-104) y libros de ventas y compras en CSV (Excel). |
| **Facturación en línea** | Catálogo de clientes, productos e **inventario con kárdex** y costo promedio. |
| **Integraciones** | API REST, **webhooks** firmados (HMAC) y flujo listo para **n8n** (`docs/n8n/`). |

---

## 7. Recorrido por el panel (para la demostración)

**Menú de todos los usuarios** (cada opción del menú trae una línea que explica para qué sirve):

| Menú | Qué trae | Qué mostrar |
|---|---|---|
| **Inicio** | Accesos rápidos (Factura rápida, Factura electrónica, Tiquete, Mis documentos, Facturas de proveedores) y el resumen del mes. | Avisos de saldo y de certificado con su enlace para resolverlos. |
| **Facturar** | *Vender:* Factura rápida, Factura electrónica, Tiquete, Punto de venta. *Corregir una factura ya enviada:* Nota de crédito, Nota de débito. *Otros:* Proforma o cotización, Factura de compra, Factura de exportación. | Formulario en 3 pasos: 1) ¿A quién le factura? (cédula → datos de Hacienda), 2) ¿Qué vende? (productos, CABYS), 3) ¿Cómo le pagan? El total y *Firmar y enviar a Hacienda* quedan fijos abajo. Exoneración y opciones técnicas (sucursal, terminal, contingencia) están plegadas. |
| **Documentos** | *Lo que vendí:* emitidos, facturas sin enviar, proformas, cierres de caja. *Lo que compré:* facturas de proveedores. *Cobros:* facturas por cobrar, recibos de pago. *Respaldo:* descargar XML y PDF. | Detalle: PDF, XML, estado, reenviar, anular, recibo de pago. |
| **Clientes y productos** | Mis clientes, importar clientes, mis productos, inventario, categorías, descuentos, combos, importar productos. | Catálogos de la facturación en línea; inventario y kárdex. |
| **Reportes** | Reporte de IVA (D-104), reportes de clientes y productos, consultas a Hacienda. | IVA del mes y libros en Excel. |
| **Configuración** | Datos de la empresa, actividad económica, saldo de documentos, mi usuario, usuarios. | Cambiar contraseña y activar la verificación en dos pasos. |

**Menú solo del administrador:**

| Pantalla | Qué mostrar |
|---|---|
| **Empresas** | Lista con saldo (verde/amarillo/rojo), certificados por vencer. En la ficha: datos, certificado `.p12`, credenciales de Hacienda, **Probar conexión**, vender paquete, cobrar mensualidades, API keys, webhook, logo. |
| **Planes y ventas** | Catálogo de paquetes y los ingresos del mes. |
| **Usuarios** | Crear, desactivar, reiniciar dos pasos. |
| **Bitácora** | Quién hizo qué y desde qué IP (logins, cambios de certificado, ventas, llaves…). |

El selector de empresa (arriba) define sobre cuál empresa se trabaja.

---

## 8. Tareas automáticas (el "beat")

| Cuándo | Qué hace |
|---|---|
| Cada 5 minutos | Reintenta lo que quedó PENDIENTE o con ERROR_COMUNICACION. |
| Cada 10 minutos | Consulta el estado de lo ENVIADO cuyo callback no llegó. |
| 3:00 a. m. | Actualiza datos de Hacienda guardados, tipo de cambio del día y el catálogo CABYS si el BCCR publicó uno nuevo. |
| 6:00 a. m. | Avisa de certificados digitales vencidos o por vencer (30 días antes). |
| 6:10 a. m. | Avisa de paquetes de documentos por vencer. |
| 6:20 a. m. | Avisa de mensualidades por vencer o vencidas. |

---

## 9. Seguridad (cómo se protegen los datos)

| Riesgo | Protección |
|---|---|
| Robo de certificados y contraseñas de Hacienda de los clientes | Se guardan **cifrados** (Fernet: AES + HMAC) con la `MASTER_KEY`. En la base no se pueden leer. |
| Robo de contraseñas del panel | Hash **scrypt** con sal; nadie las puede ver. |
| Robo de API keys | Solo se guarda su huella SHA-256. |
| Una empresa viendo datos de otra | Cada consulta se filtra por la empresa de la llave/usuario; las llaves de empresa no pueden cambiar de empresa. |
| Adivinar contraseñas o llaves | Bloqueo por intentos, límites por IP y por llave (300 solicitudes/min), 2FA obligatoria para administradores en producción. |
| Callback falso que marque una factura como aceptada | Token secreto en la URL + el sistema verifica siempre contra Hacienda. |
| XML malicioso de proveedores | Lector XML endurecido (sin XXE). |
| Ataques al panel en el navegador | Content-Security-Policy estricta, sin scripts en línea, anti-iframe, HSTS en producción. |
| Configuración insegura en producción | Con `AMBIENTE=prod` la aplicación **se niega a arrancar** si la contraseña de la base es débil, falta la `MASTER_KEY`, el callback no es HTTPS, etc. |
| Contenedores | La aplicación no corre como root; la API solo escucha en `127.0.0.1` y se publica a través de Caddy. |
| Auditoría | Bitácora de todas las acciones sensibles con usuario e IP. |

---

## 10. Las claves del sistema: cuáles hay y para qué sirve cada una

| Clave | Dónde vive | Para qué | Si se pierde o se filtra |
|---|---|---|---|
| `MASTER_KEY` | `.env` | Cifra certificados y contraseñas de Hacienda de **todas** las empresas. | **Perdida:** hay que volver a cargar certificado y credenciales de cada empresa. **Filtrada (junto con la base):** se podrían leer esos secretos. Respaldarla fuera del servidor. |
| `API_KEYS` | `.env` | Llave de administrador de arranque (acceso total por API). | Cambiarla en `.env` y reiniciar. |
| `CALLBACK_TOKEN` | `.env` | Parte secreta de la URL que Hacienda llama. | Cambiarla y reiniciar (los avisos viejos se ignoran; la consulta periódica sigue funcionando). |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | `.env` | Acceso a la base de datos. | Cambiarla en ambos lugares. |
| `SMTP_*` | `.env` | Cuenta de correo para enviar facturas. | Cambiar la contraseña en el proveedor de correo. |
| Usuarios del panel | Base de datos (hash) | Acceso de personas. | Se reasigna la contraseña; no se puede recuperar. |
| API keys de empresas | Base de datos (hash) | Acceso de los sistemas de cada cliente. | Revocar y crear otra. |
| Certificado `.p12` + PIN de cada empresa | Base de datos (cifrado) | Firmar los comprobantes. | Lo genera el cliente en ATV. |
| Usuario/contraseña del API de Hacienda de cada empresa | Base de datos (cifrado) | Enviar a Hacienda. Hay uno para **pruebas** y otro para **producción**. | Lo regenera el cliente en ATV. |

El archivo `.env` está en `.gitignore`: **nunca** se sube al repositorio.
Los valores actuales se entregan aparte, por un canal seguro.

---

## 11. Ambientes: pruebas y producción

Hay **dos niveles** de ambiente, y conviene explicarlo bien porque confunde:

1. **Ambiente de la aplicación** (`AMBIENTE` en `.env`): `stag` = estamos en pruebas (documentación visible, 2FA opcional, validaciones de producción apagadas); `prod` = servidor real.
2. **Ambiente de Hacienda por empresa** (en la ficha de cada empresa): `Pruebas (stag)` envía al **sandbox** de Hacienda (sin validez fiscal); `Producción` envía a Hacienda real. Una empresa puede estar en pruebas mientras otra ya factura en serio.

Para pasar una empresa a producción: cargar el certificado y las credenciales
**de producción** que el cliente genera en ATV, cambiar el ambiente a
*Producción*, **Probar conexión** y emitir la primera factura real.

### Lo que ya se verificó

El **2 de octubre de 2026** se probó contra el **sandbox real de Hacienda**
con un certificado de pruebas: **19 de 19 documentos aceptados** (facturas
con descuentos, exentos y no sujetos, en dólares, a crédito con recibo de
pago, sin internet, restaurante con 10 % y pago mixto, tiquetes, notas de
débito y crédito, factura de compra y de exportación, y los tres tipos de
mensaje receptor).

---

## 12. Alta de un cliente nuevo (resumen del proceso)

```
1. Pedirle: cédula, dirección registrada en Hacienda, certificado .p12 + PIN,
   usuario y contraseña del API de Hacienda (primero los de PRUEBAS)
2. Panel → Empresas → + Nueva empresa ("Datos de Hacienda" trae el nombre)
3. Ficha → cargar certificado → guardar credenciales → Probar conexión (ok / ok)
4. Ficha → + Vender paquete (con la referencia del SINPE/transferencia)
5. Ficha → marcar el servicio (API y/o facturación en línea) → Cobrar mensualidad
6. Entregar: API key + guía de integración, o usuario del panel "Solo <empresa>"
7. Factura de prueba aceptada → pedir datos de producción → cambiar a Producción
```

Detalle completo en [manual-administrador.md](manual-administrador.md) y
plantillas de mensajes en [entrega-cliente.md](entrega-cliente.md).

---

## 13. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `402` al emitir | Sin saldo: vender un paquete. |
| `403 La conexión por API no está activa` | Mensualidad vencida o casilla desmarcada. |
| `409 No se pudo firmar` | Falta el certificado o el PIN es incorrecto. |
| `422 Código CABYS no existe` | Corregir el código (buscarlo en Consultas Hacienda). |
| Probar conexión → `invalid_grant` | Usuario/contraseña de Hacienda incorrectos o del ambiente equivocado (pruebas vs. producción). |
| Comprobante en `ERROR_COMUNICACION` | Hacienda no respondió; se reintenta solo. Si dice "Error de autenticación", revisar credenciales. |
| Aceptado con advertencia `-37` | La dirección de la empresa no coincide con la de Hacienda: corregirla. |
| Un administrador perdió el teléfono (2FA) | Otro administrador → Usuarios → *Reiniciar 2 pasos*, o el comando `reiniciar-2fa`. |
| `MASTER_KEY inválido` / `No se pudo descifrar` | Se cambió o se perdió la `MASTER_KEY`. |

---

## 14. Pendientes antes de vender en producción

- [ ] Servidor (VPS), dominio y DNS → ver [despliegue.md](despliegue.md).
- [ ] `.env` de producción con **claves nuevas** (no reutilizar las de pruebas): `MASTER_KEY`, `CALLBACK_TOKEN`, contraseña de base de datos de 16+ caracteres.
- [ ] Cuenta SMTP configurada (sin ella no salen los correos a los clientes).
- [ ] Al menos **dos** administradores con verificación en dos pasos.
- [ ] Respaldo de la `MASTER_KEY` en un gestor de contraseñas.
- [ ] Pasarela de pago (hoy el cobro es manual).
