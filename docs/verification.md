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
| `pytest -q` su PostgreSQL 17 reale | **25 passed** (22 originali + 3 nuovi) |
| Equivalenza `balance_milli == SUM(ledger)` post produzione/upgrade | OK |
| Rifiuto scoperto O(1) senza scansione ledger (CheckViolation) | OK |
| Lock ridotto: città distinte liquidano in parallelo, stessa città serializza | OK, 1 sola produzione/città |
| Concorrenza invariata (4 worker un solo commit, 4 invii stesso ordine, cutoff) | OK |
| Immutabilità ledger/tick (anche TRUNCATE) e rerun migrazioni 0001+0002 | OK |
| `pg_dump -Fc` + `pg_restore --disable-triggers` in DB nuovo | OK, nessun raddoppio del cursore |
| Invariante saldo verificata sul DB ripristinato | 105000 = 105000 |
| Digest immutabili risolti dal registry e fissati | postgres/python/node |

I tre test aggiunti sono `test_materialized_balance_equals_ledger_sum` (equivalenza dopo
recupero multi-giorno e materializzazione su lettura),
`test_materialized_balance_rejects_overdraft_without_scanning_ledger` e
`test_distinct_cities_settle_concurrently_without_global_lock` (modello di lock ridotto).
Il round-trip backup→restore su Docker reale è ora esercitato dalla CI (job `containers`);
Dependabot propone i bump dei digest immutabili, delle GitHub Actions e delle dipendenze npm.

I test che liquidano prima di `age_world` congelano l'orologio (`freeze_clock`) per evitare
produzione spuria sub-secondo nel setup: asserti sui saldi deterministici, finestra del tick
invariata. Suite ripetuta 40× (test interessati) e 10× (completa) senza flakiness.

## Limiti della verifica

Docker Engine non è installato nell'ambiente: build e avvio dei container non sono
stati eseguiti localmente. Sono predisposti nella CI insieme ai test PostgreSQL e
alla build frontend; la CI non è stata eseguita su un servizio remoto. La meccanica SQL di
`backup.sh`/`restore.sh` (`pg_dump`/`pg_restore --disable-triggers` e la verifica
dell'invariante) è stata validata localmente; il wrapper `docker compose` degli script è
esercitato dal job `containers` della CI ma non è stato eseguito qui in assenza di Docker.
Le immagini base Docker sono ora fissate per digest immutabile.
Non sono stati eseguiti test di carico, disaster recovery o deployment pubblico.

Node, PostgreSQL e il validatore Compose sono stati scaricati come strumenti
portatili in `.tools/` (ignorata da Git). Database e server dello smoke test sono
stati arrestati al termine. Nessun servizio di sistema è stato installato.
