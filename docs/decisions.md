# Decisioni architetturali

Registro delle scelte che vincolano il progetto. Ogni voce dichiara la decisione, perché è
stata presa, cosa è stato scartato, cosa costa e **a quali condizioni va riaperta** — perché
una decisione senza condizione di revisione è un dogma, non una decisione.

Il brief di progetto chiede dieci documenti separati (visione, modello dati, regole,
formule, roadmap, stato funzionalità, debito tecnico, decisioni, formato salvataggi).
Oggi il backend è di ~1.500 righe: dieci file sarebbero nove intestazioni vuote, cioè
esattamente l'impalcatura prematura che lo stesso brief vieta. Per ora vivono qui e in
`architecture.md`, e si separano quando hanno contenuto proprio.

---

## ADR-001 — Il tick resta a 24 ore reali, su mondo persistente condiviso

**Decisione.** Il confine del tick è la mezzanotte UTC, esattamente 24 ore, indipendente da
riavvii e ora legale. Il mondo è unico, persistente e condiviso.

**Motivazione.** È la premessa del gioco, non un dettaglio implementativo: un mondo che
continua a esistere e ad avanzare quando il giocatore non c'è. La produzione matura per
tempo trascorso, quindi non richiede un job al secondo e sopravvive al downtime.

**Alternative considerate.** Un tick di simulazione accelerabile e in pausa, come in un
colony builder classico. Scartata: cambierebbe il genere, non solo il codice. Le due
premesse sono incompatibili e questa è stata scelta consapevolmente.

**Conseguenze.** Il ritmo del gioco è quello di un gestionale a turni lunghi, non di una
simulazione in tempo reale: il bilanciamento dovrà rendere interessante una decisione al
giorno. Il tick di massa resta una barriera globale (`world FOR UPDATE`), che è il limite di
scala noto e documentato. Il debug e il bilanciamento non possono basarsi sull'attesa di
tick reali: servono strumenti che eseguano la simulazione fuori dal tempo, e sono possibili
proprio perché `advance` è pura (ADR-003).

**Da rivedere se.** Il playtest mostra che una decisione ogni 24 ore non basta a reggere
l'interesse, oppure se la barriera globale diventa il collo di bottiglia misurato.

---

## ADR-002 — Il multiplayer resta

**Decisione.** Più giocatori nello stesso mondo, un insediamento per giocatore, autenticazione
a token, politica decisa da un'elezione comune.

**Motivazione.** È già la struttura del database (`cities.owner_id UNIQUE`, `players`, una
sola elezione per mondo) e corrisponde alla visione di un mondo interconnesso in cui le
dipendenze economiche nascono fra giocatori e non solo fra colonie di uno stesso giocatore.

**Alternative considerate.** Tornare a singolo giocatore, che semplificherebbe molto:
niente token, niente isolamento fra proprietari, niente elezione, salvataggi locali banali,
porting a Godot più diretto. Scartata per scelta esplicita.

**Conseguenze — da tenere a mente, perché non sono gratuite.** Il server resta autoritativo,
quindi Render (o un equivalente) resta necessario per giocare, e il gioco non può diventare
un eseguibile offline senza una seconda modalità. Ogni futura meccanica va pensata come
comando validato lato server, non come mutazione locale. La distribuzione su Steam di un
gioco che richiede un server persistente è un problema di costi ricorrenti, non solo tecnico:
va affrontato prima della pagina negozio, non dopo.

**Da rivedere se.** Il costo del server persistente diventa insostenibile, o il playtest
mostra che l'interazione fra giocatori non aggiunge quanto costa.

---

## ADR-003 — Le regole vivono in `app/sim/`, non in SQL

**Decisione.** Tutte le regole di gioco stanno in `app/sim/`, che non può importare psycopg,
FastAPI o il proprio adattatore (vincolo verificato da un test che analizza gli import con
`ast`). `app/service.py` è l'unico codice che trasforma un effetto descritto in una riga.

**Motivazione.** Prima di questa separazione la simulazione *era* un insieme di transazioni
SQL: nessuno stato in memoria, nessuna regola eseguibile senza database, e le invarianti vere
dentro i trigger PostgreSQL. Tre conseguenze concrete: impossibile simulare accelerato per
bilanciare, impossibile riprodurre uno stato in un test, e in un eventuale porting a Godot —
dove PostgreSQL non esiste — quelle regole andrebbero riscritte da zero anziché tradotte.
È stato fatto adesso perché le regole erano 27 righe: è il momento più economico che il
progetto avrà.

**Alternative considerate.** Lasciare la logica in SQL e aggiungere le meccaniche lì:
scartata, perché ogni regola scritta in SQL è una regola da buttare al porting. Un unico
`advance(WorldState)` su tutto il mondo per ogni operazione: **scartata perché avrebbe
distrutto una proprietà esistente e testata** — oggi città diverse liquidano in parallelo e
serializzano solo sulla propria riga; caricare il mondo intero a ogni lettura le avrebbe
messe di nuovo in fila. Da qui la forma adottata: regole per entità (`settle_city`,
`resolve_order`) per le operazioni economiche, e una regola globale (`advance`) per il solo
tick, che il lock esclusivo già serializza.

**Conseguenze.** Le regole sono testabili senza database (11 test, 0,05 s). Lo stato è
esplicito e serializzabile (`snapshot`). Il costo è un livello di traduzione in più fra righe
e valori: ogni campo nuovo va aggiunto in due posti. È un costo accettato in cambio del
confine.

**Da rivedere se.** La traduzione riga↔stato diventa una fonte ricorrente di bug, o il
profilo mostra che il caricamento dello stato pesa sul tick.

---

## ADR-004 — Nessun formato di salvataggio separato, per ora

**Decisione.** Non esiste un `saveVersion` né un formato di salvataggio applicativo. Lo stato
autoritativo è il database, versionato dalle migrazioni Alembic; le regole sono versionate da
`RULESET`, che ogni tick registra sulla propria riga.

**Motivazione.** Questa è una correzione consapevole a una proposta precedente di chi scrive,
che prevedeva `saveVersion: 1` e migrazioni di salvataggio. Con ADR-001 e ADR-002 — mondo
persistente, condiviso, server-autoritativo — **non esiste un file di salvataggio del
giocatore**: il salvataggio *è* il database. Introdurre un secondo formato di persistenza
significherebbe mantenere due rappresentazioni dello stesso stato in sincronia, che è il
tipo di sistema prematuramente complesso che il brief chiede di evitare.

**Alternative considerate.** Costruire subito serializzazione completa e migrazioni di
salvataggio, come chiesto in origine nel brief. Scartata per la ragione sopra; ciò che serviva
davvero — uno stato esplicito e serializzabile per test, confronto e futuro porting — è
ottenuto da `sim.snapshot()` senza un secondo archivio da mantenere.

**Conseguenze.** Il backup è `scripts/backup.sh` (dump verificato), non un file di salvataggio.
Un porting a Godot dovrà esportare dal database, non leggere un save.

**Da rivedere se.** Nasce una modalità offline o single-player, oppure serve trasferire un
mondo fra installazioni diverse. In quel momento `snapshot()` è il punto di partenza.

---

## ADR-005 — Il terreno della colonia si genera sul client

**Decisione.** La mappa di una colonia è generata **nel browser**, da `app/colony/citygen.ts`,
a partire dal file del pianeta e dall'identificativo della casella. Il backend conserva la
stessa definizione in `app/citygen.py` e resta l'autorità su tutto ciò che viene *deciso*
(atterraggio, costruzioni, voto); il client la usa per *guardare*.

**Motivazione.** Il visore è un sito statico (ADR sul cold start) e il pianeta è già un file.
Se anche la colonia è una funzione pura di quel file, l'intera catena «scegli una casella →
vedi su cosa stai scendendo» funziona senza nulla di sveglio da nessuna parte, e senza
aspettare il risveglio di un servizio gratuito. La strada precedente — sei mappe cucinate dal
backend e messe accanto alla pagina — mostrava sempre le stesse sei: proprio la casella che si
stava scegliendo era l'unica che non si poteva guardare.

**Alternative considerate.**
1. *Un endpoint che spedisce le celle.* Una sola definizione, nessun rischio di divergenza.
   Scartata due volte. La prima perché rimette un servizio sveglio nel percorso del semplice
   guardare, che è esattamente quello che si è appena tolto. La seconda perché è stata
   misurata: con la mappa a 768 celle di lato sono 9 MB di JSON e 2,8 s di CPU per richiesta,
   dentro una transazione, su un'istanza che di CPU ne ha un decimo — mentre il destinatario
   le stesse celle se le fa in 0,4 s. `GET /cities/{id}/ground` ora manda il seme e il sito.
2. *Generare sul client e basta, togliendo la copia Python.* Scartata: il server deve poter
   validare dove una costruzione può stare, e non può chiederlo al client.
3. *Reimplementare in JavaScript il generatore di Python* (Mersenne Twister e `gauss`).
   Scartata: centinaia di righe da tenere allineate a un dettaglio implementativo di CPython.

**Rischi e criticità.** Una definizione in due lingue è il modo classico di scrivere un bug
silenzioso: divergono di un valore e il client mostra un posto che sul server non esiste.
Due cose lo tengono a bada, e vanno mantenute entrambe.
- *Portabilità per costruzione*: `prng.py` / `prng.ts` sono mulberry32 su interi a 32 bit, seme
  FNV-1a, direzioni per campionamento sulla sfera (niente logaritmi, dove due linguaggi possono
  differire sull'ultimo bit).
- *Equivalenza come test*: `python -m app.colonyref` scrive `colony/reference.json` e
  `citygen.test.ts` confronta cella per cella. Cambiare una costante da una parte sola fa
  cadere la suite — verificato mutandone una. Il file porta anche i semi derivati da Python,
  perché il seme è ciò che le due copie hanno in comune: se divergesse, ogni confronto cella
  per cella continuerebbe a passare mentre il client mostra il sito sbagliato.

Resta un rischio non coperto: il generatore è **pubblico**. Chi legge il bundle può calcolare
il terreno di ogni casella del pianeta prima di chiunque altro. Oggi è irrilevante — il gioco
è in sviluppo privato — e a regime va accettato (è informazione derivabile comunque) oppure
tolto passando all'alternativa 1 per le caselle non ancora rivelate.

**Da rivedere se.** Nasce il client scaricabile con una sessione persistente: lì la latenza non
c'è più e l'alternativa 1 elimina la duplicazione. Oppure se l'equivalenza cella-per-cella
comincia a costare più di quanto valga.
