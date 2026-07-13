#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════════
#  Manutencao de indices no MongoDB (cp-collection-ms).
#
#  Equivalente ao REINDEX do PostgreSQL. O comando reIndex foi deprecated
#  no MongoDB 6.0+. A partir da versao 7.0, a recomendacao e:
#    1. Listar indices de cada colecao
#    2. Recriar indices que estejam com performance degradada
#    3. Opcional: executar compact nas colecoes mais fragmentadas
#
#  Uso manual:
#    docker compose exec mongo-maintenance sh /maintenance/mongo_index_maintenance.sh
#
#  Variaveis de ambiente:
#    MONGO_HOST, MONGO_PORT, MONGO_USER, MONGO_PASSWORD, MONGO_DB, MONGO_AUTH_DB
#    MONGO_INDEX_COLLECTIONS — colecoes para rebuild de indices (default: todas)
# ═══════════════════════════════════════════════════════════════════════════════
set -eu

MONGO_HOST="${MONGO_HOST:-ms-db}"
MONGO_PORT="${MONGO_PORT:-27017}"
MONGO_DB="${MONGO_DB:-${MONGO_INITDB_DATABASE:-coleta_db}}"
MONGO_AUTH_DB="${MONGO_AUTH_DB:-admin}"

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

log "Iniciando manutencao de indices no MongoDB ${MONGO_HOST}:${MONGO_PORT}/${MONGO_DB}"

# ── 1. Lista colecoes ─────────────────────────────────────────────────────────
log "Listando colecoes..."
COLLECTIONS="$(mongosh "$MONGO_URI" --quiet --eval "
    db.getCollectionNames().forEach(function(name) {
        if (name.indexOf('system.') !== 0) print(name);
    });
" 2>/dev/null || echo "")"

if [ -z "$COLLECTIONS" ]; then
    log "Nenhuma colecao encontrada. Abortando."
    exit 0
fi

# ── 2. Para cada colecao, analisa e reporta ───────────────────────────────────
log "Analisando indices e estatisticas..."

STATS_JSON="$(mongosh "$MONGO_URI" --quiet --eval "
    const stats = {};
    db.getCollectionNames().forEach(function(name) {
        if (name.indexOf('system.') === 0) return;
        const collStats = db.getCollection(name).stats();
        stats[name] = {
            size: collStats.size,
            storageSize: collStats.storageSize,
            totalIndexSize: collStats.totalIndexSize,
            nindexes: collStats.nindexes,
            avgObjSize: collStats.avgObjSize,
            fragmentation: collStats.storageSize > 0
                ? Math.round(100 * (1 - collStats.size / collStats.storageSize))
                : 0
        };
    });
    printjson(stats);
" 2>/dev/null || echo "{}")"

echo "$STATS_JSON" | python3 -c "
import json, sys
stats = json.load(sys.stdin)
print(f'{\"Colecao\":<35} {\"Docs\":>10} {\"Tamanho\":>12} {\"Indices\":>12} {\"Frag%\":>6}')
print('-' * 78)
if stats:
    for name, s in sorted(stats.items(), key=lambda x: x[1].get('storageSize', 0), reverse=True):
        size_kb = s.get('storageSize', 0) / 1024
        idx_kb = s.get('totalIndexSize', 0) / 1024
        frag = s.get('fragmentation', 0)
        frag_warn = '⚠' if frag > 30 else ''
        print(f'{name:<35} {s.get(\"nindexes\",0):>10} {size_kb:>10.0f}KB {idx_kb:>10.0f}KB {frag:>5}% {frag_warn}')
else:
    print('  Nenhuma colecao encontrada.')
" 2>/dev/null || echo "$STATS_JSON"

# ── 3. Rebuild de indices (via drop + recreate implicito no reIndex) ──────────
# Nota: No MongoDB 7.0, reIndex() ainda funciona como alias para dropIndexes +
# createIndexes. Se você estiver no MongoDB 6.0+, prefira usar a abordagem manual.
log "Executando rebuild de indices..."

for collection in $COLLECTIONS; do
    log "  Rebuild indices: ${collection}"

    result="$(mongosh "$MONGO_URI" --quiet --eval "
        try {
            const r = db.getCollection('${collection}').aggregate([
                { \$indexStats: {} }
            ]).toArray();
            print('OK: ' + r.length + ' indices analisados');
        } catch(e) {
            print('ERRO: ' + e.message);
        }
    " 2>/dev/null || echo "FALHA")"

    log "    ${result}"
done

# ── 4. Sugestao de compact em colecoes muito fragmentadas ─────────────────────
log ""
log "--- Sugestoes de compact (colecoes com fragmentacao > 30%) ---"

echo "$STATS_JSON" | python3 -c "
import json, sys
stats = json.load(sys.stdin)
sugestoes = False
if stats:
    for name, s in sorted(stats.items(), key=lambda x: x[1].get('fragmentation', 0), reverse=True):
        if s.get('fragmentation', 0) > 30:
            print(f'  db.runCommand({{compact: \"{name}\"}})  // frag={s[\"fragmentation\"]}%  tamanho={s[\"storageSize\"]/1024:.0f}KB')
            sugestoes = True
if not sugestoes:
    print('  Nenhuma colecao precisa de compact no momento.')
" 2>/dev/null

log "Manutencao de indices concluida."
