# Project Exilium

Base per city builder sci-fi multiplayer in un mondo persistente unico.
FastAPI è autoritativo; PostgreSQL conserva economia e audit; un worker separato
risolve politica e ordini ogni 24 ore. Next.js/React offre il primo ciclo giocabile.

Leggere prima [schema, invarianti e semantica temporale](docs/architecture.md).
La procedura di ritorno dalla migrazione della slice è in [rollback 0002](docs/rollback.md).
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

Su Linux/macOS usare `cp .env.example .env`. `APP_ENV=development` e il cookie non
Secure sono espliciti perché Compose pubblica soltanto HTTP su loopback. In produzione
usare `APP_ENV=production` e impostare `TRUSTED_ORIGINS` all'origine HTTPS pubblica:
il backend forza comunque Secure e rifiuta mutazioni autenticate senza Origin valido.
Password di esempio solo per sviluppo;
se cambiata, usare caratteri compatibili con un URL oppure percent-encoding nel DSN.
PostgreSQL non espone porte host. API e web sono pubblicate solo su loopback.
Le migrazioni devono completarsi prima dell'avvio di API e worker.

- Gioco web: http://localhost:3000
- OpenAPI: http://localhost:8000/docs
- Liveness: `/health/live`; readiness (DB + tick recuperati): `/health/ready`

Dal browser si può registrare un handle, entrare in `exilium-prime`, scegliere una
cella, fondare la capitale e costruire estrattori. La sessione usa un cookie HttpOnly:
il frontend non riceve né salva il token. In Compose `Secure` è disattivato solo perché
il servizio locale usa HTTP; il valore predefinito dell'API è sicuro per HTTPS.

`GET /me/cities` elenca le proprie città. La prima slice consente una sola fondazione,
ma lo schema ammette future colonie non-capitali. Ledger e ordini sono paginati con
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

Il frontend inoltra le chiamate same-origin al backend attraverso `API_INTERNAL_URL`
(default `http://127.0.0.1:8000`). Non legge token e non effettua calcoli economici.
I manifest Python diretti sono `requirements*.txt`; i file `requirements*.lock.txt`
fissano anche dipendenze transitive. `package-lock.json` viene usato con `npm ci`.

## Operatività iniziale

Il worker controlla ogni 5 secondi e recupera fino a 32 tick per ciclo. Per un ciclo
manuale di recupero: `docker compose exec worker python -m app.worker --once`.
Questo non anticipa la scadenza del tick. Ogni tick confermato viene scritto nei log;
un'eccezione produce rollback e retry. Più worker sono ammessi e si serializzano.

`docker compose down` conserva il volume; `down -v` cancella permanentemente il mondo.
Prima di cambiare regole economiche occorre una nuova versione del ruleset e una
migrazione che preservi la semantica degli ordini pendenti. Le migrazioni distruttive
all'indietro sono disabilitate. Il deployment pubblico richiederà progettazione di
account, TLS, backup verificati e dimensionamento: questa base è per sviluppo locale.
