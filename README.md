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

### Giocare, in tre comandi

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api python -m app.mapcli          # il pianeta, una volta sola
docker compose exec api python -m app.cli "Prima colonia"
```

L'ultimo comando stampa un **token**: è l'unica volta che lo vedi. Poi:

1. apri <http://localhost:3000> — il pianeta, e si naviga senza token perché è un file;
2. clicca una terra e scendi: la casella dice cosa rende *prima* di sceglierla;
3. apri <http://localhost:3000/citta>, incolla il token, e la colonia è tua.

Il visore sa già dove sta il server: l'indirizzo entra nella compilazione (`NEXT_PUBLIC_API_URL`,
impostato da `compose.yaml` su `http://localhost:8000`, che è l'indirizzo visto dal BROWSER e
non dalla rete di compose). Per puntare altrove c'è il campo **Server**, nella pagina della
colonia e nel menu di gioco.

### Ricominciare da capo

Atterrare e' definitivo -- e' una regola del mondo, tenuta ferma da tre guardie: la chiave
esterna dal ledger, il trigger che rende il ledger immutabile, e il vincolo che una colonia a
terra non si sposta. Per ricominciare c'e' invece un'operazione di **amministrazione**, che sta
fuori dal mondo come lo sta cancellare un salvataggio:

```bash
docker compose exec api python -m app.resetcli --confirm
```

Via giocatori, colonie, ordini, impianti, scorte e ledger. **Il pianeta resta**: e' immutabile
e costa minuti di CPU, e un reset della partita non e' un reset della geografia. Senza
`--confirm` dice soltanto cosa farebbe.

In locale c'e' anche la strada piu' corta, che azzera pure il pianeta -- ma col seme fisso
ritrovi lo stesso: `docker compose down -v && docker compose up -d`.

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
docker compose exec api python -m app.mapcli
```

`--frequency N` (2..160) regola la suddivisione geodetica: i tile sono `10*N^2 + 2`. Il
default N=139 produce **193.212 tile**, di cui ~54.100 di terra (sea level al 72° percentile,
scelto perché sotto quella soglia le terre percolano in un unico supercontinente): una città
per casella di terra, quindi il mondo ospita dieci volte il target di **5.000 giocatori**.
Generazione ~6 s e ~330 MB di picco: è l'intera sfera costruita in memoria in una volta, ed è
questo a fissare il tetto della frequenza su un'istanza piccola.

Il generatore v2 produce forme del terreno riconoscibili, non macchie di rumore:

- **montagne** — rumore *ridged* raccolto in cinture, quindi catene in fila con roccia
  d'alta quota e vette innevate (quote fino a ~7.000 m);
- **fiumi e laghi** — accumulo di deflusso a valle sul grafo dei tile: ogni tile di terra
  conosce il proprio tile di valle, e i bacini chiusi con abbastanza acqua diventano laghi;
- **deserti** — profilo zonale delle precipitazioni con vere fasce aride subtropicali,
  più continentalità (distanza dal mare) e ombra pluviometrica sottovento alle catene;
- **isole** — un'ottava ad alta frequenza semina arcipelaghi in mare aperto; le componenti
  connesse danno a ogni tile la dimensione della sua massa continentale;
- **poli** — poli più freddi, quindi calotte glaciali e banchisa formano vere calotte.

`mapservice.read_map` produce il *render model* **in colonne**. A questa scala un oggetto JSON per
tile spenderebbe più byte a ripetere i nomi dei campi che sulla geografia, quindi ogni campo
è un array parallelo; e i vertici dei poligoni sono centroidi condivisi da tre tile ciascuno,
quindi vivono in un unico pool e il tile ne cita solo gli indici. Insieme portano il payload a
un terzo della codifica ingenua: **14,1 MB grezzi → 3,5 MB gzip** (contro 32 MB → 5,2 MB).
Contiene le terre, la banchisa polare, l'anello di piattaforma continentale attorno a ogni
costa (l'oceano oltre la piattaforma è un guscio liscio lato client), la rete idrografica già
risolta in segmenti e la normale del terreno di ogni tile. Latitudine e longitudine non
viaggiano: il client le ricava dal vettore centro. La tabella conserva la geografia completa.
La rigenerazione è rifiutata: ridimensionare o rigenerare il mondo richiede una migrazione
dedicata (vedi `0004_bigger_world`, `0005_landforms`, `0006_finer_world`).

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

## Deploy pubblico su Render

Il file `render.yaml` è un blueprint che provisiona l'intero stack (dove worker e
PostgreSQL possono girare, a differenza di Vercel). Su Render: **New → Blueprint**,
connetti questo repo, scegli il branch che contiene `render.yaml`, poi **Apply**.

Vengono creati: `exilium-db` (PostgreSQL), `exilium-api` (FastAPI; applica le migrazioni
e genera `Hesperia` alla prima partenza) e `exilium-web` (frontend del globo). Il worker
del tick è incluso ma commentato: su Render richiede un piano a pagamento, e non serve per
vedere il globo (la geografia è statica). L'URL pubblico è quello di `exilium-web`.

Note piano free: i web service vanno in sleep quando inattivi (primo caricamento più lento)
e il database free scade dopo 30 giorni.

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

Il visore non chiama il backend: e' un sito statico e il pianeta viaggia con lui, in
`frontend/public/map`. Quel file lo scrive `python -m app.mapexport` (dalla directory
`backend`) e va rigenerato solo quando cambia il mondo, cioe' quando arriva una migrazione
che azzera la mappa. `npm start` serve la cartella `out` costruita da `npm run build`.
Il backend resta l'autorita' su citta', ordini e ledger: quella parte vuole un token e non
la tocca nessuna pagina pubblica.
I manifest Python diretti sono `requirements*.txt`; i file `requirements*.lock.txt`
fissano anche dipendenze transitive. `package-lock.json` viene usato con `npm ci`.

## Il tempo, in sviluppo

Un tick al giorno rende impossibile provare il gioco. L'orologio del mondo si comprime, dalla
directory `backend`:

```
python -m app.gameclock            # legge velocità e ora del mondo
python -m app.gameclock 3600 --yes # un'ora di mondo per secondo reale
python -m app.gameclock 1 --yes    # torna al tempo vero
```

`--yes` serve solo se il mondo ha già delle città: cambiare l'orologio cambia quanto ciascuna
guadagna per secondo reale. **Un mondo condiviso gira a 1** — la velocità viaggia in `/world`
proprio perché un mondo che non ci gira possa dirlo invece di sembrare rotto.

Il worker non serve alla correttezza: una città è aggiornata nel momento in cui la si legge.
Fa lo spazzino, perché in un mondo condiviso una città che ha finito smetta di dirsi occupata
anche mentre il suo proprietario dorme.

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
