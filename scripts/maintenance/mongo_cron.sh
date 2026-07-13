#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════════
#  Cron para scripts de manutencao do MongoDB — ponto de entrada do container.
#
#  Agenda:
#    - Cleanup de dados antigos: diario as 03:15
#    - Manutencao de indices:     semanal aos domingos as 04:00
# ═══════════════════════════════════════════════════════════════════════════════
set -eu

cat > /etc/crontabs/root <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MONGO_HOST=${MONGO_HOST:-ms-db}
MONGO_PORT=${MONGO_PORT:-27017}
MONGO_USER=${MONGO_USER:-}
MONGO_PASSWORD=${MONGO_PASSWORD:-}
MONGO_DB=${MONGO_DB:-${MONGO_INITDB_DATABASE:-coleta_db}}
MONGO_AUTH_DB=${MONGO_AUTH_DB:-admin}
MONGO_RETENTION_DAYS=${MONGO_RETENTION_DAYS:-90}
MONGO_CLEANUP_BATCH=${MONGO_CLEANUP_BATCH:-5000}
MONGO_CLEANUP_COLLECTIONS=${MONGO_CLEANUP_COLLECTIONS:-audit_logs}

15 3 * * * sh /maintenance/mongo_cleanup.sh
0  4 * * 0 sh /maintenance/mongo_index_maintenance.sh
EOF

echo "[$(date -Iseconds)] MongoDB maintenance cron configurado"
echo "  - Cleanup: todo dia as 03:15 (retendo ${MONGO_RETENTION_DAYS:-90} dias)"
echo "  - Indices: todo domingo as 04:00"
exec crond -f -l 8
