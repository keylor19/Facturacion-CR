# API de Facturación Electrónica — Costa Rica (Hacienda)

Backend que recibe facturas en JSON desde tu sistema, genera el XML v4.4,
lo firma digitalmente (XAdES-EPES) y lo envía al API de Recepción de
Comprobantes Electrónicos del Ministerio de Hacienda.

## Stack
FastAPI + PostgreSQL + Redis + Celery, todo orquestado con Docker Compose.

## Estructura
```
api/
  main.py               → aplicación FastAPI
  routes/
    facturas.py          → POST/GET /api/v1/facturas
    callback.py           → recibe notificaciones de Hacienda
    health.py             → /api/v1/health
  models/
    database.py           → modelos SQLAlchemy
    schemas.py             → validación Pydantic de entrada/salida
  services/
    clave_generator.py     → clave de 50 dígitos
    xml_generator.py         → JSON → XML v4.4
    firma.py                  → firma XAdES-EPES
    hacienda_auth.py            → OIDC (login contra Hacienda)
    hacienda_client.py           → POST/GET contra Hacienda
workers/
  celery_app.py, tasks.py    → envío asíncrono con reintentos
config/settings.py            → variables de entorno
```

## 1. Requisitos previos (esto es tuyo, fuera del código)
Antes de que esto sirva de algo necesitás, en este orden:

1. **Inscripción en ATV** con el módulo de Comprobantes Electrónicos activo.
2. **Certificado digital** (.p12) vigente del contribuyente.
3. **Credenciales del API de recepción**: Hacienda las envía al buzón
   electrónico tras activar el paso 1. Es un usuario/contraseña distinto
   al de ATV web.
4. Los **XSD/anexos técnicos v4.4** descargados desde ATV → "Anexos y
   Estructuras", para validar tu XML antes de enviarlo.

## 2. Configuración
```bash
cp .env.example .env
# Editar .env con tus credenciales reales
# Colocar tu certificado en certs/certificado.p12
```

## 3. Levantar todo
```bash
docker compose up --build
```
Esto levanta: API (puerto 8000), worker de Celery, beat (tareas
periódicas), PostgreSQL y Redis.

Documentación interactiva (Swagger) disponible en: `http://localhost:8000/docs`

## 4. Probar el flujo completo
```bash
curl -X POST http://localhost:8000/api/v1/facturas \
  -H "Content-Type: application/json" \
  -d '{
    "receptor": {
      "nombre": "Juan Pérez",
      "tipo_identificacion": "01",
      "numero_identificacion": "123456789",
      "correo": "juan@example.com"
    },
    "productos": [
      {
        "descripcion": "Servicio de consultoría",
        "cantidad": 1,
        "precio_unitario": 50000,
        "impuesto_porcentaje": 13
      }
    ]
  }'
```
Respuesta esperada (202 Accepted): un `factura_id` y `clave`. La factura
queda en estado `PENDIENTE` → `ENVIADO` → `ACEPTADO`/`RECHAZADO` a medida
que el worker la procesa y Hacienda responde.

Seguimiento:
```bash
curl http://localhost:8000/api/v1/facturas/{factura_id}
```

## 5. IMPORTANTE antes de ir a producción
Este esqueleto es funcional pero hay 3 puntos que **debés validar tú
mismo** contra el ambiente de pruebas real de Hacienda antes de confiar en
esto con clientes reales:

1. **Firma XAdES** (`api/services/firma.py`): la estructura general está
   correcta, pero XAdES es estricto — probá contra `stag` y ajustá según
   los rechazos específicos que te devuelva Hacienda.
2. **XML v4.4 completo** (`api/services/xml_generator.py`): cubre los
   campos obligatorios más comunes de una factura simple. Facturas con
   exoneraciones, múltiples impuestos, referencias a otros documentos,
   etc. necesitan campos adicionales del XSD oficial.
3. **`client_id` del OIDC** (`api/services/hacienda_auth.py`): confirmalo
   contra el Anexo 1 vigente antes de depender de él.

Recomendación: antes de programar nada de esto en producción, hacé un
`curl` manual contra `HACIENDA_TOKEN_URL` con tus credenciales reales para
confirmar que la autenticación funciona, y después probá un envío manual
contra `stag` con un XML de ejemplo firmado.

## 6. Siguientes pasos sugeridos
- Migrar `Base.metadata.create_all` a **Alembic** para migraciones versionadas.
- Agregar autenticación (JWT) a tu propia API (`/api/v1/facturas`) para que
  no cualquiera pueda facturar en tu nombre.
- Agregar validación del XML contra el XSD oficial con `xmlschema` antes
  de firmar (ahorra la mayoría de rechazos).
- Agregar tabla de contadores con lock para el consecutivo si vas a tener
  varias sucursales/terminales facturando en paralelo.
- Configurar Celery Beat para correr `reintentar_contingencia` cada 5-10 min.
- Poner NGINX + Let's Encrypt delante de la API en producción.
