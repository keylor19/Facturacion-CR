# Puesta en línea del servicio

Guía para publicar la plataforma en internet con HTTPS, de modo que los
sistemas de sus clientes se conecten desde cualquier lugar.

## 1. Lo que necesita

| Recurso | Recomendación |
|---|---|
| Servidor | VPS Linux (Ubuntu 24.04) con 2 vCPU, 4 GB RAM y 40 GB de disco para empezar. Proveedores: DigitalOcean, Hetzner, AWS Lightsail, Vultr o un hosting nacional. |
| Dominio | Por ejemplo `api.sufacturacion.cr`, con un registro DNS **A** que apunte a la IP del servidor. |
| Puertos | 80 y 443 abiertos (HTTPS). El 22 (SSH) solo para usted. Nada más. |
| Correo saliente | Cuenta SMTP (Google Workspace, Microsoft 365, Amazon SES, Brevo…) para enviar facturas y avisos. |

## 2. Instalar

```bash
# En el servidor
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
git clone <su-repositorio> facturacion && cd facturacion
cp .env.example .env
```

Edite `.env`:

```ini
AMBIENTE=prod
DOMINIO=api.sufacturacion.cr
CALLBACK_BASE_URL=https://api.sufacturacion.cr
POSTGRES_PASSWORD=<contraseña larga>
DATABASE_URL=postgresql+psycopg2://facturacion:<la misma contraseña>@db:5432/facturacion
MASTER_KEY=<ver abajo>
CALLBACK_TOKEN=<ver abajo>
API_KEYS=                      # opcional; puede administrar solo con usuarios del panel
DOCS_PUBLICAS=true             # para que los integradores vean /docs
SMTP_HOST=… SMTP_USER=… SMTP_PASSWORD=… SMTP_FROM=facturas@sufacturacion.cr
```

Genere los secretos:

```bash
docker compose run --rm --no-deps api python -m api.cli generar-master-key   # -> MASTER_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"               # -> CALLBACK_TOKEN
docker compose run --rm --no-deps --user root api python -m api.cli descargar-xsd
```

> ⚠️ **Guarde una copia de `MASTER_KEY` fuera del servidor** (gestor de contraseñas).
> Sin ella no se pueden leer los certificados ni las contraseñas de Hacienda de sus clientes.

## 3. Arrancar

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose run --rm api python -m api.cli crear-usuario --email usted@correo.cr --nombre "Su nombre" --admin
```

- Panel: `https://api.sufacturacion.cr/panel/`
- API para sus clientes: `https://api.sufacturacion.cr/api/v1`
- Documentación interactiva: `https://api.sufacturacion.cr/docs`

Con `AMBIENTE=prod` la aplicación **no arranca** si falta algo crítico
(MASTER_KEY, CALLBACK_TOKEN, callback con HTTPS…); el mensaje dice qué falta.

## 4. Qué queda funcionando

| Servicio | Función |
|---|---|
| `caddy` | HTTPS automático (Let's Encrypt, se renueva solo), redirección de HTTP a HTTPS, límite de 6 MB por solicitud |
| `api` | API y panel web (no se expone directamente a internet) |
| `worker` | Envía a Hacienda, consulta estados, correos, webhooks |
| `beat` | Reintentos, consultas pendientes, avisos de certificados y paquetes por vencer |
| `db` / `redis` | Base de datos y cola de trabajos |
| `respaldo` | Respaldo diario de la base en `respaldos/` (se conservan `DIAS_RETENCION_RESPALDO` días) |

## 5. Operación

| Tarea | Comando |
|---|---|
| Ver estado | `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps` |
| Ver errores | `docker compose logs -f --tail=100 api worker` |
| Actualizar a una versión nueva | `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (las migraciones se aplican solas) |
| Restaurar un respaldo | `docker compose exec -T db pg_restore -U facturacion -d facturacion --clean < respaldos/<archivo>.dump` |
| Salud del servicio | `https://api.sufacturacion.cr/api/v1/health` (para un monitor externo como UptimeRobot) |

**Copie los respaldos fuera del servidor** (otro proveedor o almacenamiento
en la nube) al menos una vez al día: si el servidor se pierde, se pierden
también los respaldos que están en él.

## 6. Seguridad del servidor

La aplicación ya trae sus protecciones (cifrado de certificados y contraseñas,
2FA, límites de intentos, bitácora, HTTPS). El servidor también hay que
cerrarlo; en Ubuntu:

```bash
# Firewall: solo SSH, HTTP y HTTPS
sudo ufw default deny incoming
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp
sudo ufw enable

# SSH solo con llave (después de copiar su llave con ssh-copy-id)
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# Actualizaciones de seguridad automáticas y bloqueo de ataques a SSH
sudo apt install -y unattended-upgrades fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades
```

- **Docker y el firewall:** `docker-compose.prod.yml` no publica los puertos
  de la base, Redis ni la API; solo Caddy (80/443). No agregue `ports:` a
  esos servicios, porque Docker los abriría saltándose `ufw`.
- **`.env` es lo más valioso del servidor:** `chmod 600 .env`. Con
  `MASTER_KEY` y una copia de la base se descifran los certificados de todos
  los clientes, así que guarde `MASTER_KEY` en un gestor de contraseñas y
  **nunca** en el mismo lugar que los respaldos.
- **Respaldos fuera del servidor y cifrados**, por ejemplo con
  `rclone` hacia un almacenamiento con cifrado, o
  `gpg --symmetric respaldos/<archivo>.dump` antes de copiarlos.
- **Proveedor de la nube:** active 2FA en la cuenta del proveedor (quien entra
  ahí puede apagar o copiar el servidor completo).
- **Actualizar la aplicación** cada mes (`git pull` + `up -d --build`) para
  recibir parches de las librerías. Antes puede revisarlas con
  `pip-audit -r requirements.txt`.

## 7. Lista de verificación antes de vender

- [ ] Dominio con HTTPS funcionando y panel accesible.
- [ ] `MASTER_KEY` respaldada fuera del servidor.
- [ ] Respaldos diarios copiándose fuera del servidor.
- [ ] SMTP configurado (los clientes reciben facturas y avisos de saldo).
- [ ] Monitor externo vigilando `/api/v1/health`.
- [ ] "Proveedor de sistemas" = su cédula en cada empresa (usted es el proveedor del software ante Hacienda).
- [ ] Términos de servicio y política de privacidad con sus clientes (usted custodia sus certificados).
- [ ] Una factura real en producción emitida y aceptada para su propia empresa.
- [ ] Firewall, SSH solo con llave y actualizaciones automáticas (sección 6).
- [ ] Verificación en dos pasos activada en todos los administradores del panel.
- [ ] Las API keys de administrador de `API_KEYS` (`.env`) solo las conoce usted; los sistemas de los clientes usan llaves **de su empresa**, nunca de administrador.
