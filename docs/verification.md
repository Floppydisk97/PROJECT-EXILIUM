# Verifica della fondazione

Repository iniziale: vuota, solo `.git`, nessun commit e nessun file applicativo.
Branch di lavoro: `foundation/authoritative-world`. Nessun commit eseguito.

## Verifiche eseguite localmente

| Verifica | Esito |
| --- | --- |
| Python 3.12, dipendenze da lockfile, `pip check` | OK |
| `pytest -q` su PostgreSQL 17.11 reale | **22 passed**, nessun test saltato |
| Migrazione iniziale e seconda esecuzione senza modifiche | OK |
| `npm run typecheck` | OK |
| `npm run build`, Next.js 16.3.5, React 19.3.0, Node 22.23.2 | OK |
| `npm install` audit iniziale | 0 vulnerabilità segnalate |
| `docker-compose --env-file .env.example config --quiet` | OK, Compose 5.5.1 |
| HTTP API `/health/ready` e `/world` su database migrato | 200 |
| HTTP frontend standalone collegato a FastAPI/PostgreSQL | 200, politica e stato corretti |
| Cinque asset statici richiamati dalla pagina standalone | 200 |
| Frontend con backend arrestato | Messaggio di indisponibilità corretto |
| `git diff --check` | OK |

I test includono: produzione additiva con downtime, pareggi elettorali, timestamp
invalidi, mondo singleton, cambio tasso esattamente al tick, retry dopo commit,
errore iniettato dopo addebito con rollback completo, quattro worker concorrenti,
quattro invii concorrenti dello stesso ordine, conflitti di idempotenza, recupero
di tre giorni senza salti, blocco delle nuove operazioni durante recupero, immutabilità
del ledger e dei tick (anche TRUNCATE), saldo non negativo, eventi duplicati,
upgrade senza copertura, autenticazione e isolamento tra proprietari, payload
manipolati, paginazione, quattro liquidazioni concorrenti, cutoff esatto e voto
con tre giocatori nello stesso mondo.

Pytest riporta due avvisi di deprecazione di dipendenze Starlette/AnyIO riguardanti
il TestClient; non sono errori o test saltati.

## Consolidamento e scalabilità (migrazione 0002)

| Verifica | Esito |
| --- | --- |
| `pytest -q` su PostgreSQL 17 reale, dopo 0002 | **24 passed** (22 originali + 2 nuovi) |
| Equivalenza `balance_milli == SUM(ledger)` post produzione/upgrade | OK |
| Rifiuto scoperto O(1) senza scansione ledger (CheckViolation) | OK |
| Rerun migrazioni 0001+0002 e mondo singleton | OK |
| Immutabilità ledger/tick e concorrenza (4 worker, 4 invii) invariate | OK |
| `pg_dump -Fc` + `pg_restore --disable-triggers` in DB nuovo | OK, nessun raddoppio del cursore |
| Invariante saldo verificata sul DB ripristinato | 105000 = 105000 |
| Digest immutabili risolti dal registry e fissati | postgres/python/node |

I due test aggiunti sono `test_materialized_balance_equals_ledger_sum` (equivalenza dopo
recupero multi-giorno e materializzazione su lettura) e
`test_materialized_balance_rejects_overdraft_without_scanning_ledger`.

## Limiti della verifica

Docker Engine non è installato nell'ambiente: build e avvio dei container non sono
stati eseguiti localmente. Sono predisposti nella CI insieme ai test PostgreSQL e
alla build frontend; la CI non è stata eseguita su un servizio remoto. Di `backup.sh`
e `restore.sh` è stata validata localmente solo la meccanica SQL (`pg_dump`/`pg_restore`
e la verifica dell'invariante); il wrapper `docker compose` non è stato eseguito.
Le immagini base Docker sono ora fissate per digest immutabile.
Non sono stati eseguiti test di carico, disaster recovery o deployment pubblico.

Node, PostgreSQL e il validatore Compose sono stati scaricati come strumenti
portatili in `.tools/` (ignorata da Git). Database e server dello smoke test sono
stati arrestati al termine. Nessun servizio di sistema è stato installato.
