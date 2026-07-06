#!/bin/sh
set -e

[ -f /scripts/env.sh ] && . /scripts/env.sh

BACKUP_DIR="${BACKUP_DIR:-/backups/mongo}"

# -y/--yes pula a confirmação interativa (útil para scripts/CI).
ASSUME_YES=""
if [ "$1" = "-y" ] || [ "$1" = "--yes" ]; then
  ASSUME_YES="1"
  shift
fi

# Aceita um caminho completo, só o nome do arquivo (dentro de BACKUP_DIR)
# ou nenhum argumento (usa o backup mais recente).
ARCHIVE="$1"
if [ -z "$ARCHIVE" ]; then
  ARCHIVE=$(ls -1t "$BACKUP_DIR"/"${MONGO_DB}"_*.gz 2>/dev/null | head -n 1)
elif [ ! -f "$ARCHIVE" ]; then
  ARCHIVE="$BACKUP_DIR/$ARCHIVE"
fi

if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
  echo "Nenhum backup encontrado em $BACKUP_DIR (ou argumento inválido: '$1')." >&2
  exit 1
fi

echo "Backups disponíveis em $BACKUP_DIR:"
ls -1t "$BACKUP_DIR"/"${MONGO_DB}"_*.gz 2>/dev/null
echo
echo "Restaurando a partir de: $ARCHIVE"
echo "ATENÇÃO: as collections existentes do banco '$MONGO_DB' serão substituídas (--drop)."

if [ -z "$ASSUME_YES" ]; then
  echo "Confirma a restauração? [y/N]"
  read -r CONFIRM
  case "$CONFIRM" in
    y|Y|yes|YES) ;;
    *) echo "Restauração cancelada."; exit 0 ;;
  esac
fi

mongorestore \
  --host "$MONGO_HOST" \
  --port "$MONGO_PORT" \
  --username "$MONGO_USER" \
  --password "$MONGO_PASSWORD" \
  --authenticationDatabase admin \
  --archive="$ARCHIVE" \
  --gzip \
  --drop

echo "[$(date -Iseconds)] Restauração concluída a partir de $ARCHIVE"
