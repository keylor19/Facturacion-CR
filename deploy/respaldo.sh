#!/bin/sh
# Respaldo diario de la base de datos (formato custom de pg_dump) con retención.
# Restaurar: pg_restore -h db -U facturacion -d facturacion --clean /respaldos/<archivo>.dump
#
# Cada respaldo se verifica leyendo su índice (pg_restore --list): un archivo dañado se
# detecta el mismo día y no semanas después, cuando se necesita.
# ALERTA_URL (opcional): dirección que recibe un POST con el texto del error (Slack,
# Teams, Telegram por un puente, n8n…). Así un respaldo fallido no pasa desapercibido.
set -e
DIAS="${DIAS_RETENCION:-14}"
mkdir -p /respaldos

alertar() {
  echo "$(date) $1" >&2
  if [ -n "$ALERTA_URL" ]; then
    wget -q -O /dev/null --header="Content-Type: text/plain" --post-data="Facturación CR: $1" "$ALERTA_URL" || true
  fi
}

while true; do
  ARCHIVO="/respaldos/facturacion-$(date +%Y%m%d-%H%M).dump"
  if pg_dump -h db -U facturacion -Fc facturacion > "$ARCHIVO.tmp" && pg_restore --list "$ARCHIVO.tmp" > /dev/null; then
    mv "$ARCHIVO.tmp" "$ARCHIVO"
    echo "$(date) respaldo OK y verificado: $ARCHIVO ($(du -h "$ARCHIVO" | cut -f1))"
  else
    rm -f "$ARCHIVO.tmp"
    alertar "ERROR en el respaldo diario de la base de datos ($(hostname))"
  fi
  find /respaldos -name 'facturacion-*.dump' -mtime +"$DIAS" -delete
  sleep 86400
done
