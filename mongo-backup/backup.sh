#!/bin/sh
set -e

# Quando disparado pelo cron, carrega as variáveis de ambiente persistidas
# pelo entrypoint.sh (cron não herda o ambiente do container).
[ -f /scripts/env.sh ] && . /scripts/env.sh

BACKUP_DIR="${BACKUP_DIR:-/backups/mongo}"
RETENTION="${BACKUP_RETENTION:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE="$BACKUP_DIR/${MONGO_DB}_${TIMESTAMP}.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -Iseconds)] Iniciando backup de '$MONGO_DB' em $ARCHIVE"

mongodump \
  --host "$MONGO_HOST" \
  --port "$MONGO_PORT" \
  --username "$MONGO_USER" \
  --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --db "$MONGO_DB" \
  --archive="$ARCHIVE" \
  --gzip

echo "[$(date -Iseconds)] Backup concluído: $ARCHIVE"

# Retenção: mantém apenas os $RETENTION backups mais recentes.
cd "$BACKUP_DIR"
ls -1t "${MONGO_DB}"_*.gz 2>/dev/null | tail -n "+$((RETENTION + 1))" | while read -r old; do
  echo "[$(date -Iseconds)] Removendo backup antigo: $old"
  rm -f -- "$old"
done
