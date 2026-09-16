# Verifica della fondazione

Baseline: commit foundation `ef16d26feb9d170f41d654be809f988e5a8aa0c0`.
Branch di lavoro: `feature/first-colony-loop`. Nessun commit eseguito per la slice.

## Verifiche eseguite localmente

| Verifica | Esito |
| --- | --- |
| Python 3.12, dipendenze da lockfile, `pip check` | OK |
| `pytest -q` su PostgreSQL 17.11 reale | **35 passed**, nessun test saltato |
| Migrazione pulita, upgrade reale `0001 → 0002` e backfill idempotenza | OK |
| `npm run typecheck` | OK |
| `npm run build`, Next.js 16.3.5, React 19.3.0, Node 22.23.2 | OK |
| `npm install` audit iniziale | 0 vulnerabilità segnalate |
| `docker-compose --env-file .env.example config --quiet` | OK, Compose 5.5.1 |
| Smoke Next.js → proxy → FastAPI → PostgreSQL | Registrazione, ingresso, colonia, estrattore e nuovo login OK |
| Cookie sessione | HttpOnly, SameSite=Lax, token hashato; Secure verificato in modalità produzione |
| `git diff --check` | OK |

I test includono: produzione additiva con downtime, pareggi elettorali, timestamp
invalidi, mondo singleton, cambio tasso esattamente al tick, retry dopo commit,
errore iniettato dopo addebito con rollback completo, quattro worker concorrenti,
quattro invii concorrenti dello stesso ordine, conflitti di idempotenza, recupero
di tre giorni senza salti, blocco delle nuove operazioni durante recupero, immutabilità
del ledger e dei tick (anche TRUNCATE), saldo non negativo, eventi duplicati,
upgrade senza copertura, autenticazione e isolamento tra proprietari, payload
manipolati, paginazione, quattro liquidazioni concorrenti, cutoff esatto e voto
con tre giocatori nello stesso mondo. La slice aggiunge test per Argon2, sessioni,
revoca/scadenza, ingresso idempotente, celle invalide e contese, rollback della
fondazione, supporto futuro multi-colonia, fingerprint del payload, retry concorrenti
dell'estrattore, saldo insufficiente e produzione offline dopo un nuovo login.

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
