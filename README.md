# Project Exilium

Base per city builder sci-fi multiplayer in un mondo persistente unico.
FastAPI è autoritativo; PostgreSQL conserva economia e audit; un worker separato
risolve politica e ordini ogni 24 ore. Next.js/React mostra solo lo stato tecnico.

Leggere prima [schema, invarianti e semantica temporale](docs/architecture.md).
Le regole iniziali di produzione, upgrade e voto servono a verificare la fondazione:
non costituiscono ancora il design del gioco completo.

## Avvio locale con Docker Compose

Prerequisito: Docker Engine/Desktop con Compose v2.

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs worker
```

Su Linux/macOS usare `cp .env.example .env`. Password di esempio solo per sviluppo;
se cambiata, usare caratteri compatibili con un URL oppure percent-encoding nel DSN.
PostgreSQL non espone porte host. API e web sono pubblicate solo su loopback.
Le migrazioni devono completarsi prima dell'avvio di API e worker.

- Stato web: http://localhost:3000
- OpenAPI: http://localhost:8000/docs
- Liveness: `/health/live`; readiness (DB + tick recuperati): `/health/ready`

Provisionare un giocatore locale (il token viene mostrato una sola volta):

```powershell
docker compose exec api python -m app.cli "Prima colonia"
```

I token casuali sono memorizzati solo come hash nel database. Non esiste endpoint
pubblico per creare giocatori, assegnare risorse o forzare tick. Per due giocatori,
eseguire due volte il provisioning con nomi diversi.

Generare il pianeta autoritativo `Hesperia` (una sola volta; sfera geodetica di tile
generata da seed, poi immutabile):

```powershell
docker compose exec api python -m app.mapcli "Hesperia-01"
```

`--frequency N` (2..48, default 12) regola la suddivisione geodetica: i tile sono
`10*N^2 + 2` (N=12 → 1442). La mappa è servita da `GET /world/map` (geografia pubblica,
nessun saldo) e la rigenerazione è rifiutata: un nuovo mondo richiede un nuovo seed via
migrazione dedicata.

Esempio API PowerShell, con i valori restituiti dalla CLI:

```powershell
$cityId = '<city_id>'
$headers = @{ Authorization = 'Bearer <token>'; 'Idempotency-Key' = [guid]::NewGuid().ToString() }
Invoke-RestMethod "http://localhost:8000/cities/$cityId" -Headers $headers
Invoke-RestMethod "http://localhost:8000/cities/$cityId/orders" -Method Post -Headers $headers -ContentType 'application/json' -Body '{"kind":"upgrade"}'
# Per ritentare lo stesso ordine, conservare la stessa Idempotency-Key e lo stesso body.
$headers['Idempotency-Key'] = [guid]::NewGuid().ToString()
Invoke-RestMethod "http://localhost:8000/cities/$cityId/orders" -Method Post -Headers $headers -ContentType 'application/json' -Body '{"kind":"policy_vote","choice":"industrial"}'
Invoke-RestMethod "http://localhost:8000/cities/$cityId/ledger" -Headers $headers
```

`GET /me/cities` elenca le proprie città. Ledger e ordini sono paginati con
`after=<ultimo id>` e `limit=1..200`. Importi, id incrementali e numeri tick sono
stringhe JSON per evitare perdita di precisione JavaScript. `alloy_milli / 1000`
è il valore in unità di risorsa. Una lettura città materializza la produzione
maturata; il ledger mostra solo eventi già materializzati.

## Verifica

```powershell
docker compose --profile test run --build --rm test
```

I test creano schemi PostgreSQL casuali e li eliminano al termine; non azzerano
le tabelle del mondo. Senza `TEST_DATABASE_URL`, pytest salta esplicitamente i test
PostgreSQL: quei soli test unitari non certificano concorrenza e transazioni.

Per sviluppo senza Docker (Python 3.12+, PostgreSQL 17, Node 22):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.lock.txt
$env:DATABASE_URL = 'postgresql://user:password@localhost:5432/exilium'
$env:TEST_DATABASE_URL = $env:DATABASE_URL
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# In un secondo terminale, dalla directory backend:
..\.venv\Scripts\python.exe -m app.worker
# In un terzo terminale, dalla directory frontend:
npm ci
npm run typecheck
npm run build
$env:HOSTNAME = '127.0.0.1'
npm start
```

Il frontend chiama il backend dal server Next.js, attraverso `API_INTERNAL_URL`
(default `http://127.0.0.1:8000`). Non contiene token e non effettua calcoli economici.
I manifest Python diretti sono `requirements*.txt`; i file `requirements*.lock.txt`
fissano anche dipendenze transitive. `package-lock.json` viene usato con `npm ci`.

## Operatività iniziale

Il worker controlla ogni 5 secondi e recupera fino a 32 tick per ciclo. Per un ciclo
manuale di recupero: `docker compose exec worker python -m app.worker --once`.
Questo non anticipa la scadenza del tick. Ogni tick confermato viene scritto nei log;
un'eccezione produce rollback e retry. Più worker sono ammessi e si serializzano.

## Backup e restore

Il mondo vive nel volume PostgreSQL; `down -v` lo cancella in modo permanente. Per
conservarlo, produrre dump verificati (formato custom, compressi):

```bash
scripts/backup.sh                     # scrive backups/exilium-<UTC>.dump e ne verifica il TOC
RESTORE_CONFIRM=yes scripts/restore.sh backups/exilium-<UTC>.dump
```

Il restore è DISTRUTTIVO: ferma api/worker, ricrea il database e ricarica il dump con
`--disable-triggers`, poi verifica l'invariante `balance_milli == SUM(resource_ledger)`
per ogni città e aborta se diverge. Su Windows eseguire gli stessi comandi `docker compose`
mostrati negli script tramite Git Bash o WSL.

Le immagini base Docker (`postgres`, `python`, `node`) sono fissate per digest immutabile
in `compose.yaml`, nei `Dockerfile` e nella CI: build riproducibili. Per aggiornarle,
ricalcolare il digest del tag desiderato e sostituirlo negli stessi punti.

## Ciclo di vita e migrazioni

`docker compose down` conserva il volume; `down -v` cancella permanentemente il mondo.
Prima di cambiare regole economiche occorre una nuova versione del ruleset e una
migrazione che preservi la semantica degli ordini pendenti. Le migrazioni distruttive
all'indietro sono disabilitate. Il deployment pubblico richiederà progettazione di
account, TLS, backup verificati e dimensionamento: questa base è per sviluppo locale.
