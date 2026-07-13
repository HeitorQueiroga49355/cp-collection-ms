#!/bin/sh
set -e

# O cron inicia os jobs com um ambiente "limpo", sem as variáveis do container.
# Persistimos o ambiente atual aqui para que backup.sh/restore.sh consigam
# acessar MONGO_HOST, MONGO_USER etc. quando disparados pelo cron.
printenv | sed "s/^\([A-Za-z_][A-Za-z0-9_]*\)=\(.*\)$/export \1='\2'/" > /scripts/env.sh
chmod +x /scripts/env.sh

mkdir -p "${BACKUP_DIR:-/backups/mongo}"
touch /var/log/cron.log

# Configura o cliente MinIO se as variáveis estiverem presentes.
if [ -n "${MINIO_ENDPOINT:-}" ] && [ -n "${MINIO_ACCESS_KEY:-}" ]; then
  mc alias set minio "http://${MINIO_ENDPOINT}" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" --quiet
  mc mb --ignore-existing "minio/${MINIO_BACKUP_BUCKET:-mongo-backups}" || true
  echo "MinIO configurado: http://${MINIO_ENDPOINT} (bucket: ${MINIO_BACKUP_BUCKET:-mongo-backups})"
fi

# Instalado via `crontab <file>` (crontab de usuário, sem campo de username) —
# não usar /etc/cron.d/ aqui, pois esse diretório é lido como crontab de
# sistema e exige um campo de usuário extra na linha.
echo "${CRON_SCHEDULE:-0 3 * * *} /scripts/backup.sh >> /var/log/cron.log 2>&1" > /scripts/crontab
crontab /scripts/crontab

cron
echo "mongo-backup ativo. Agendamento: ${CRON_SCHEDULE:-0 3 * * *}"
tail -f /var/log/cron.log
