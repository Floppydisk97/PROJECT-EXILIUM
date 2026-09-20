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

---

## ADR-006 — Il terreno vale tre numeri, non uno

**Decisione.** Una colonia atterrata conserva tre interi misurati sulla propria mappa: **resa**
(fertilità della terra edificabile), **fatica** (verde e palude da sgomberare) e **spazio**
(celle edificabili). La resa alza il tasso di produzione, la fatica allunga gli avanzamenti, lo
spazio dà un tetto **morbido**. È il ruleset 2.

**Motivazione.** Prima di questo, dove atterravi cambiava la vista e nient'altro. La manopola
ovvia — «la fertilità alza la produzione» — è stata scartata **dopo averla misurata**: con un
numero solo esiste un sito migliore in assoluto, e scegliere diventa cercarlo. Non è una
decisione, è una classifica. E i due candidati ovvi non erano neppure in tensione: la foresta
pluviale batte il deserto sia in fertilità sia in spazio (correlazione fra i due assi: −0,12).

Tre numeri che tirano in direzioni diverse producono invece un **sorpasso**: simulando un anno,
la terra grassa è avanti del 37% a dieci giorni e il deserto la passa fra i novanta giorni e
l'anno. Nessun sito è la risposta a tutti gli orizzonti.

**Alternative considerate.**
1. *Una manopola sola (la resa).* Due giorni di lavoro invece di una settimana. Scartata per la
   ragione sopra: costruisce una classifica.
2. *Solo attrito* — il terreno non cambia la resa, cambia quanto costa crescere. Difficile da
   sbilanciare, ma la scelta del sito si sente invece di leggersi.
3. *La seconda risorsa subito* (minerali nella roccia, cibo nel fertile). È la soluzione che fa
   contare davvero la geografia, e resta la strada per il ruleset 3 — ma tocca ledger, costi,
   avanzamenti e interfaccia tutti insieme, e non era il momento.

**Rischi e criticità.**
- **I biomi intermedi restano smorti.** La tundra è media in tutto, quindi non è la migliore da
  nessuna parte. Accettato consapevolmente: la cura è l'alternativa 3, dove il freddo e la
  roccia diventano *necessari* invece che scadenti. Aggiungere ora una quarta manopola sarebbe
  rattoppare un problema che ha già una soluzione strutturale.
- **La palude è quattro volte indietro.** Non è un difetto: una palude *è* un brutto posto per
  una città, e il visore mostra 0,3% di edificabile mentre la stai guardando. Una trappola
  visibile è una scelta; sarebbe un tranello solo se non si vedesse.
- **Due copie del calcolo**, come per il generatore. Il riferimento verifica anche i tre numeri
  economici: se divergessero, il sito che hai pesato e quello che hai preso non sarebbero lo
  stesso, e ogni confronto cella per cella continuerebbe a passare.
- **I numeri sono di partenza, non bilanciati.** Stanno tutti in `sim/config.py`, e cambiarli è
  un ruleset nuovo — non una riscrittura silenziosa della storia, perché il ledger timbra ogni
  riga.

**Da rivedere se.** Arriva la seconda risorsa: a quel punto resa e fatica diventano due voci di
un conto più grande, e il tetto morbido potrebbe non servire più.

---

## ADR-007 — Il cibo è un tetto, il magazzino pieno è uno stallo

**Decisione.** Quattro risorse (lega, cibo, legname, pietra) con un magazzino per risorsa e un
ledger per risorsa. Il cibo si consuma per livello e **limita il livello raggiungibile**;
avanzare oltre ciò che il sito sfama è **rifiutato**. Ogni magazzino ha un tetto, e un
magazzino pieno smette di guadagnare. Un livello costa pietra e legname. La lega non si conia
più: tornerà come primo prodotto della prima catena.

**Motivazione.** L'obiettivo dichiarato sono catene di produzione in stile Anno, dove le isole
hanno risorse diverse e il commercio è necessario. Questo è il gradino su cui poggia tutto: il
ledger e il magazzino diventano multi-risorsa, e la geografia comincia a dire *cosa* hai.

Lo stallo a magazzino pieno è stato **scelto dall'utente contro il mio consiglio**: io avevo
proposto «la colonia non si ferma mai», perché questo mondo cammina mentre il giocatore dorme
e uno stallo a sorpresa punisce chi non può collegarsi spesso. La scelta è stata mantenuta e
resa vivibile in un altro modo — vedi sotto.

**Alternative considerate.**
1. *Non fermarsi mai* (eccesso perso o convertito). Più clemente, meno teso. Scartata
   dall'utente.
2. *Rallentare senza spegnersi.* Via di mezzo, più difficile da spiegare e da bilanciare.
3. *La fame che uccide* invece del rifiuto: una colonia cresciuta troppo perde livelli.
   Scartata: atterrare è irreversibile, e un vicolo cieco in più non serviva a nessuno.

**Rischi e criticità.**
- **Lo stallo resta una scommessa di design.** La mitigazione è che è *prevedibile*:
  `time_to_full` calcola il momento esatto, quindi il giocatore pianifica invece di scoprire.
  Se giocandoci sembrerà una tassa invece che una tensione, è una costante in `sim/config.py`.
- **I biomi poveri dipendono dal commercio che non esiste ancora.** Mitigato da un minimo
  garantito di raccolto (`HARVEST_FLOOR`) e da scorte iniziali: nessun sito è bloccato, alcuni
  sono solo lenti. Quando arriverà il commercio il minimo potrà scendere.
- **Il cibo riempie il proprio magazzino in poche ore** e poi resta lì: oggi non ha altro
  sbocco che il mantenimento. Diventerà un ingrediente con le catene; fino ad allora è un
  numero che sta fermo, ed è onesto dirlo.
- **Una definizione dell'economia in un solo posto** — `sim/config.py` — ma ora con più
  manopole che interagiscono. I numeri sono di partenza, non bilanciati.

**Da rivedere se.** Arrivano le catene: lì i tassi diventano negativi e dipendenti fra loro, la
forma chiusa salta e serve l'integrazione a eventi. `time_to_full` è già il pezzo che servirà.

---

## ADR-008 — Le catene si integrano a eventi, non si simulano a passi

**Decisione.** Un'opera (per ora la fonderia) consuma e produce di continuo. Liquidare una
colonia significa **camminare sugli eventi**: fra un evento e l'altro i tassi sono costanti,
quindi il momento in cui una scorta tocca lo zero o il tetto si *calcola* e ci si salta sopra.
Un'opera tira dal magazzino finché ce n'è e, a buffer vuoto, gira al ritmo con cui l'ingresso
arriva — in millesimi, per restare in aritmetica intera.

**Motivazione.** Senza catene la produzione era un integrale in forma chiusa, ed è ciò che ha
permesso di togliere il tick: una colonia dimenticata da un anno si liquida con una
moltiplicazione. Un processo che consuma distrugge quella comodità. L'alternativa ovvia —
simulare a passi fissi — rimette il tick dalla finestra e uccide il mondo continuo.

Misurato: dieci anni di assenza si liquidano in 0,15 ms, e spezzare un intervallo dà lo stesso
risultato **al milli** (verificato su 48 ore, in un colpo contro ora per ora).

**Alternative considerate.**
1. *Passi fissi (un minuto, un'ora).* Semplice da scrivere, e sbagliato: reintroduce il tick,
   e una colonia ferma da un anno diventerebbe mezzo milione di iterazioni.
2. *Lotti discreti* («ogni 30 s consuma 2 e produce 1»), più vicino ad Anno nello spirito. Ma
   un anno di lotti è un milione di eventi, a meno di calcolarne il numero in forma chiusa —
   che è di nuovo il calcolo dei flussi, con più cerimonia.
3. *Niente throttling: a ingresso vuoto l'opera si spegne.* Scartata perché oscilla — si
   spegne, il buffer si riempie di un grammo, si riaccende — a frequenza infinita.

**Rischi e criticità.**
- **Un'opera non si può spegnere né demolire.** È la mancanza più grave di questo gradino:
  una fonderia mangia il legname per sempre, e siccome il legname serve anche a costruire, una
  sola opera può bloccare la crescita di una colonia senza che il giocatore possa farci nulla.
  In Anno un edificio si mette in pausa. Qui ancora no, ed è il prossimo pezzo da fare.
- **Il numero di eventi è limitato** (`MAX_EVENTS`) e superarlo *alza un errore*. È voluto: un
  ciclo infinito dentro una richiesta è il modo peggiore di scoprire che una catena oscilla.
  Ma significa che una catena futura mal fatta romperà la lettura di una città invece di
  degradare in silenzio — che è la scelta giusta, e va ricordata.
- **Il throttling arrotonda.** I millesimi perdono qualcosa a ogni calcolo; è deterministico e
  riproducibile, ma una catena lunga accumulerà una perdita sistematica a sfavore del
  giocatore. Da rivedere quando le catene avranno più di un anello.
- **Ancora nessun commercio.** I numeri sono tarati perché nessun sito regga una fonderia da
  solo: finché non si può scambiare, questo significa che tutti girano a regime ridotto.

**Da rivedere se.** Le catene diventano a più stadi (un'opera che mangia ciò che un'altra
produce): lì il calcolo dei flussi smette di essere una divisione e diventa una propagazione
sul grafo, e va scritto come tale invece che allargato per gradi.
