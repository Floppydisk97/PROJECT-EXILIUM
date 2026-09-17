#!/usr/bin/env bash
# Restore verificato in un mondo ricreato da zero. DISTRUTTIVO: rimpiazza l'intero
# database. Ferma api/worker, ricrea il database vuoto e ricarica il dump con
# --disable-triggers (i trigger di immutabilità e il cursore del saldo non devono
# rifirare durante il caricamento). Al termine verifica l'invariante fondamentale:
# per ogni città balance_milli == SUM(resource_ledger.amount). Aborta se diverge.
set -euo pipefail

cd "$(dirname "$0")/.."
DUMP="${1:-}"
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "Uso: scripts/restore.sh <file.dump>   (richiede RESTORE_CONFIRM=yes)" >&2
    exit 2
fi
if [ "${RESTORE_CONFIRM:-}" != "yes" ]; then
    echo "Restore DISTRUTTIVO di '$DUMP'. Ripetere con RESTORE_CONFIRM=yes per procedere." >&2
    exit 2
fi

[ -f .env ] && set -a && . ./.env && set +a
DB="${POSTGRES_DB:-exilium}"
USER="${POSTGRES_USER:-exilium}"

echo "Arresto api e worker..."
docker compose stop api worker

echo "Ricreazione del database '$DB'..."
docker compose exec -T db psql -U "$USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = '$DB' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "$DB";
CREATE DATABASE "$DB";
SQL

echo "Caricamento del dump..."
docker compose cp "$DUMP" db:/tmp/exilium-restore.dump
docker compose exec -T db pg_restore -U "$USER" --disable-triggers --exit-on-error \
    -d "$DB" /tmp/exilium-restore.dump
docker compose exec -T db rm -f /tmp/exilium-restore.dump

echo "Verifica invariante saldo == somma ledger..."
BAD="$(docker compose exec -T db psql -U "$USER" -d "$DB" -tAc \
  "SELECT count(*) FROM cities c WHERE c.balance_milli <> (SELECT COALESCE(SUM(amount),0) FROM resource_ledger r WHERE r.city_id = c.id)")"
if [ "$(echo "$BAD" | tr -d '[:space:]')" != "0" ]; then
    echo "ERRORE: restore incoerente; il saldo materializzato diverge dal ledger. Non avviare api/worker." >&2
    exit 1
fi

echo "Restore verificato. Riavvio api e worker..."
docker compose start api worker
echo "Fatto. Controllare /health/ready prima di aprire il traffico."
