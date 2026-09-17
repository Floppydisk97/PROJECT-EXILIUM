#!/usr/bin/env bash
# Backup verificato del mondo autoritativo. Dump custom-format (pg_dump -Fc):
# separa schema/dati/vincoli, comprime e permette restore selettivo.
# Il ledger e i tick restano immutabili: questo è l'unico modo supportato per
# conservare il mondo (down -v cancella il volume in modo permanente).
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
DB="${POSTGRES_DB:-exilium}"
USER="${POSTGRES_USER:-exilium}"
OUT_DIR="${BACKUP_DIR:-backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_DIR/exilium-$STAMP.dump"

echo "Dump di '$DB' in corso..."
docker compose exec -T db pg_dump -U "$USER" -Fc "$DB" >"$OUT"

# Verifica che il dump sia leggibile (TOC integro) prima di dichiararlo valido.
# Copia in-container per un archivio seekable, poi rimuove il temporaneo.
docker compose cp "$OUT" db:/tmp/exilium-verify.dump
if ! docker compose exec -T db pg_restore -l /tmp/exilium-verify.dump >/dev/null 2>&1; then
    docker compose exec -T db rm -f /tmp/exilium-verify.dump || true
    echo "ERRORE: dump non leggibile; backup non valido: $OUT" >&2
    exit 1
fi
docker compose exec -T db rm -f /tmp/exilium-verify.dump

echo "Backup verificato: $OUT ($(wc -c <"$OUT") byte)"
