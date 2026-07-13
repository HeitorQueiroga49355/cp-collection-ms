#!/bin/sh
set -eu

[ -f /scripts/env.sh ] && . /scripts/env.sh

BACKUP_DIR="${BACKUP_DIR:-/backups/mongo}"
RETENTION="${BACKUP_RETENTION:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE="$BACKUP_DIR/${MONGO_DB}_${TIMESTAMP}.gz"

# Envia notificação via webhook (Slack, Discord, ntfy.sh, etc.).
# Não interrompe o script se o curl falhar.
notify() {
  LEVEL="$1"
  MSG="$2"
  echo "[${LEVEL}] $MSG"
  if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
    curl -sf -X POST "$NOTIFY_WEBHOOK_URL" \
      -H 'Content-Type: application/json' \
      -d "{\"text\":\"[${LEVEL}] ${MSG}\"}" || true
  fi
}

# Flag de sucesso: se o script sair com EXIT=0 antes de ser setada, houve falha.
BACKUP_OK=0
on_exit() {
  if [ "$BACKUP_OK" -eq 0 ]; then
    notify "ERRO" "Backup de '$MONGO_DB' falhou em $(date -Iseconds). Verifique /var/log/cron.log."
  fi
}
trap on_exit EXIT

mkdir -p "$BACKUP_DIR"
echo "[$(date -Iseconds)] Iniciando backup de '$MONGO_DB' → $ARCHIVE"

mongodump \
  --host "$MONGO_HOST" \
  --port "$MONGO_PORT" \
  --username "$MONGO_USER" \
  --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --db "$MONGO_DB" \
  --archive="$ARCHIVE" \
  --gzip

# Verifica se o arquivo gerado é um gzip válido.
gzip -t "$ARCHIVE"
echo "[$(date -Iseconds)] Integridade verificada: $ARCHIVE"

# Upload offsite para MinIO (opcional — requer MINIO_ENDPOINT configurado).
if [ -n "${MINIO_ENDPOINT:-}" ]; then
  mc cp "$ARCHIVE" "minio/${MINIO_BACKUP_BUCKET:-mongo-backups}/"
  echo "[$(date -Iseconds)] Upload MinIO concluído: ${MINIO_BACKUP_BUCKET}/$(basename "$ARCHIVE")"
fi

# Retenção local: mantém apenas os $RETENTION backups mais recentes.
cd "$BACKUP_DIR"
ls -1t "${MONGO_DB}"_*.gz 2>/dev/null | tail -n "+$((RETENTION + 1))" | while read -r old; do
  echo "[$(date -Iseconds)] Removendo backup antigo: $old"
  rm -f -- "$old"
done

BACKUP_OK=1
notify "OK" "Backup de '$MONGO_DB' concluído: $(basename "$ARCHIVE")"
