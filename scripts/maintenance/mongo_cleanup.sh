#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════════
#  Limpeza automatizada de dados/logs antigos no MongoDB (cp-collection-ms).
#
#  Remove registros antigos das colecoes configuradas, em lotes,
#  para evitar sobrecarga do banco.
#
#  Uso manual:
#    docker compose exec mongo-maintenance sh /maintenance/mongo_cleanup.sh
#
#  Variaveis de ambiente (todas com default):
#    MONGO_HOST            — host do MongoDB (default: ms-db)
#    MONGO_PORT            — porta (default: 27017)
#    MONGO_USER / MONGO_PASSWORD — credenciais
#    MONGO_DB              — banco de dados (default: coleta_db)
#    MONGO_AUTH_DB         — banco de autenticacao (default: admin)
#    MONGO_RETENTION_DAYS  — dias de retencao (default: 90)
#    MONGO_CLEANUP_BATCH   — tamanho do lote de delecao (default: 5000)
#    MONGO_CLEANUP_COLLECTIONS — colecoes a limpar, separadas por espaco
#                                 (default: audit_logs)
# ═══════════════════════════════════════════════════════════════════════════════
set -eu

MONGO_HOST="${MONGO_HOST:-ms-db}"
MONGO_PORT="${MONGO_PORT:-27017}"
MONGO_DB="${MONGO_DB:-${MONGO_INITDB_DATABASE:-coleta_db}}"
MONGO_AUTH_DB="${MONGO_AUTH_DB:-admin}"
RETENTION_DAYS="${MONGO_RETENTION_DAYS:-90}"
BATCH_SIZE="${MONGO_CLEANUP_BATCH:-5000}"
COLLECTIONS="${MONGO_CLEANUP_COLLECTIONS:-audit_logs}"

log() {
    echo "[$(date -Iseconds)] $*"
}

build_mongo_uri() {
    if [ -n "${MONGO_USER:-}" ] && [ -n "${MONGO_PASSWORD:-}" ]; then
        echo "mongodb://${MONGO_USER}:${MONGO_PASSWORD}@${MONGO_HOST}:${MONGO_PORT}/${MONGO_DB}?authSource=${MONGO_AUTH_DB}"
    else
        echo "mongodb://${MONGO_HOST}:${MONGO_PORT}/${MONGO_DB}"
    fi
}

MONGO_URI="$(build_mongo_uri)"
NOW_MS="$(date +%s)000"  # timestamp em milissegundos

log "Iniciando limpeza de dados no MongoDB ${MONGO_HOST}:${MONGO_PORT}/${MONGO_DB}"
log "Retencao: ${RETENTION_DAYS} dias | Lote: ${BATCH_SIZE} docs"

for collection in $COLLECTIONS; do
    log "--- Colecao: ${collection} ---"

    # Conta quantos documentos existem antes do cutoff
    total_antes="$(mongosh "$MONGO_URI" --quiet --eval "
        print(db.getCollection('${collection}').countDocuments({
            created_at: { \$lt: new Date(Date.now() - ${RETENTION_DAYS} * 24 * 60 * 60 * 1000) }
        }));
    " 2>/dev/null || echo "0")"

    log "  Documentos antigos a remover: ${total_antes}"

    if [ "$total_antes" = "0" ] || [ -z "$total_antes" ]; then
        log "  Nada a remover em ${collection}. Seguindo..."
        continue
    fi

    deleted_total=0
    remaining="$total_antes"

    while [ "$remaining" -gt 0 ]; do
        result="$(mongosh "$MONGO_URI" --quiet --eval "
            const result = db.getCollection('${collection}').deleteMany(
                { created_at: { \$lt: new Date(Date.now() - ${RETENTION_DAYS} * 24 * 60 * 60 * 1000) } },
                { maxTimeMS: 30000 }
            );
            print(result.deletedCount);
        " 2>/dev/null || echo "0")"

        deleted="${result:-0}"
        deleted_total=$((deleted_total + deleted))
        remaining=$((remaining - deleted))
        log "  ${collection}: removidos ${deleted} docs (total: ${deleted_total}/${total_antes})"

        if [ "$deleted" -eq 0 ]; then
            break
        fi
        sleep 1
    done

    log "  ${collection}: concluido. Total removido: ${deleted_total}"
done

log "Limpeza finalizada."
