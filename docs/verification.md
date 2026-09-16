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

## Limiti della verifica

Docker Engine non è installato nell'ambiente: build e avvio dei container non sono
stati eseguiti localmente. Sono predisposti nella CI insieme ai test PostgreSQL e
alla build frontend; la CI non è stata eseguita su un servizio remoto.
Le immagini base Docker usano tag di versione principale, non digest immutabili.
Non sono stati eseguiti test di carico, disaster recovery o deployment pubblico.

Node, PostgreSQL e il validatore Compose sono stati scaricati come strumenti
portatili in `.tools/` (ignorata da Git). Database e server dello smoke test sono
stati arrestati al termine. Nessun servizio di sistema è stato installato.
