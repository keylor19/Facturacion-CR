#!/bin/sh
# Respaldo diario de la base de datos (formato custom de pg_dump) con retención.
# Restaurar: pg_restore -h db -U facturacion -d facturacion --clean /respaldos/<archivo>.dump
set -e
DIAS="${DIAS_RETENCION:-14}"
mkdir -p /respaldos
while true; do
  ARCHIVO="/respaldos/facturacion-$(date +%Y%m%d-%H%M).dump"
  if pg_dump -h db -U facturacion -Fc facturacion > "$ARCHIVO.tmp"; then
    mv "$ARCHIVO.tmp" "$ARCHIVO"
    echo "$(date) respaldo OK: $ARCHIVO"
  else
    rm -f "$ARCHIVO.tmp"
    echo "$(date) ERROR en el respaldo" >&2
  fi
  find /respaldos -name 'facturacion-*.dump' -mtime +"$DIAS" -delete
  sleep 86400
done
