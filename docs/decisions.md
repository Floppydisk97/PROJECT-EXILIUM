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

---

## ADR-009 — L'energia è un flusso, e un impianto si può spegnere

**Decisione.** L'energia non è una risorsa di magazzino e non entra nel ledger: è un **flusso**,
due numeri al secondo (prodotta, pretesa). Quattro fonti — eolico, solare, idroelettrico,
geotermico — rendono in proporzione all'**attitudine del luogo**. Quando la corrente non basta,
tutti gli impianti rallentano alla stessa frazione. E ogni impianto si può mettere in pausa,
riaccendere e abbattere, istantaneamente.

**Motivazione.** Se l'energia si accumulasse, una colonia ne banchereb­be di notte e il vincolo
sparirebbe: tornerebbe a essere «abbastanza, prima o poi». Come flusso è invece il caso che lo
strozzatore delle catene già sapeva trattare — un ingresso senza buffer — quindi non è servita
nessuna macchina nuova.

La pausa chiude il difetto più grave del gradino precedente, che avevo trovato **provando** il
gioco e non leggendolo: una fonderia mangiava il legname per sempre, e siccome il legname serve
anche a costruire, un solo impianto poteva bloccare per sempre la crescita di una colonia.

E l'energia riscatta il deserto senza che nessuna regola debba fare un'eccezione per lui: era
il sito povero di tutto, ed è il posto migliore del pianeta per il sole.

**Alternative considerate.**
1. *Energia come quinta risorsa con magazzino.* Uniforme col resto e più semplice da scrivere.
   Scartata: toglie il vincolo invece di crearlo, e trasforma una decisione in un'attesa.
2. *Batterie fin da subito* (un accumulo limitato). Interessante, e prematuro: prima serve che
   il flusso stringa davvero, poi avrà senso poterlo livellare.
3. *A corrente insufficiente si spegne qualcosa automaticamente.* Scartata: la scelta di cosa
   sacrificare è del giocatore, ed è precisamente il genere di decisione per cui esiste la
   pausa.
4. *Pausa come impegno* (occupa la colonia, come costruire). Scartata: sarebbe punire il
   giocatore per aver cambiato idea.

**Rischi e criticità.**
- **Il sole non ha ancora un ciclo giorno/notte**, né il vento una variabilità. Oggi una fonte
  rende costante: è onesto per un primo gradino, ma toglie alle rinnovabili proprio ciò che le
  rende interessanti. Le batterie diventano sensate solo quando ci sarà.
- **Il nucleare non c'è**, come previsto: è la fonte che non dipende dal luogo, e va aggiunta
  quando ci sarà una scala tecnologica che la giustifichi — altrimenti è solo la centrale
  migliore, e le altre quattro diventano decorazione.
- **Abbattere non rimborsa.** Scelta voluta e dichiarata nell'interfaccia; se giocando
  sembrerà una punizione invece di una conseguenza, un rimborso parziale è una riga.
- **Il regime unico** (tutti rallentano insieme) è semplice da spiegare ma grossolano: con
  catene lunghe si vorrà dare precedenza a qualcosa. Sarà una priorità per impianto.

**Da rivedere se.** Arrivano il ciclo giorno/notte o il nucleare: entrambi cambiano il senso di
«quanta ne produco adesso», e il primo rende finalmente utile un accumulo.

---

## ADR-010 — Il gioco è uno schermo, e i comandi hanno una definizione sola

**Decisione.** `/colonia` diventa uno schermo di gioco: terreno a tutta finestra, barra delle
risorse in alto, minimappa e pulsanti in basso a sinistra, pannello dei comandi a scomparsa a
destra. I comandi della colonia (costruire, impianti, voto) vivono in **un solo componente**,
`city/CityPanel.tsx`, usato sia dalla pagina `/citta` sia dal pannello di gioco.

**Motivazione.** Un gioco non si legge, ci si sta dentro: finché l'interfaccia era fatta di
pagine con titoli e paragrafi, ogni azione costava una navigazione e il terreno — la cosa che
il giocatore guarda — era un riquadro fra due blocchi di testo. E i comandi duplicati sarebbero
stati il **quinto** caso di «due elenchi che devono coincidere» di questo progetto: i primi
quattro sono costati un difetto ciascuno, tre dei quali trovati solo provando il gioco.

**Alternative scartate.**
1. *Pannello sempre aperto a lato* (stile foglio di calcolo). Scartata: ruba un terzo dello
   schermo per sempre a ciò che dovrebbe dominarlo.
2. *Duplicare i comandi nel pannello, semplificati.* Scartata per la ragione sopra; «tanto è
   una copia piccola» è esattamente come sono nati gli altri quattro casi.
3. *Sostituire `/citta` con lo schermo di gioco.* Scartata per ora: la pagina larga resta il
   posto dove si legge tutto insieme, e serve da riscontro quando il pannello mente.
4. *Minimappa come immagine generata a parte.* Scartata: due disegni dello stesso terreno
   divergono. Campiona la stessa funzione, in un buffer disegnato una volta sola.

**Costo.** Un componente che deve stare bene in due larghezze molto diverse: dentro il
pannello la tabella degli impianti si impagina a blocchi, e il costo di costruzione è dovuto
uscire dal bottone per finire sotto la ricetta.

**Rischi e criticità.**
- **L'interfaccia non è sotto test come lo sono i calcoli.** `city/format.ts` è testato perché
  un numero sbagliato si legge come plausibile; il disegno invece è verificato a schermate, a
  mano, su una finestra sola. Un difetto di impaginazione su un telefono stretto oggi non lo
  vedrebbe nessuno prima del giocatore.
- **La minimappa è un buffer in memoria per colonia.** Con una sola colonia non si vede; se un
  giorno si passasse fra colonie senza ricaricare la pagina, andrà invalidato.
- **Le impostazioni sono quasi vuote** (indirizzo del server e poco altro). Il menu esiste per
  avere il posto dove metterle, non perché ci sia già qualcosa da regolare: se resta vuoto a
  lungo è un guscio, e un guscio nel menu principale è rumore.
- **L'aggiornamento è un sondaggio ogni 30 secondi.** Va bene per un mondo che cammina in ore,
  ma due schede aperte sulla stessa colonia possono mostrare due verità per mezzo minuto.

**Da rivedere se.** Arriva il gioco su telefono come bersaglio serio (l'impaginazione a mano
non basta più), oppure il pannello cresce al punto da avere sezioni proprie: a quel punto
diventa una scheda con delle linguette, non un pannello solo più lungo.

---

## ADR-011 — Il rilievo si calcola dall'altezza che il generatore già scrive

> **Superata in parte da ADR-014.** L'ombreggiatura descritta qui è stata rimossa: su un
> rilievo fatto di poche armoniche produceva fasce diagonali, non colline. Restano la
> profondità dell'acqua e la distanza dalla riva, e il file ora si chiama `colony/relief.ts`.

**Decisione.** Il terreno della colonia è illuminato: pendenza, conche, profondità dell'acqua e
distanza dalla riva, tutto derivato da `cells.height` — la colonna che il generatore scriveva
già e che nessuno leggeva. Il modello sta in `colony/light.ts`, è funzione pura delle celle, è
sotto test, e vale **esattamente 1.0** sul terreno piatto.

**Motivazione.** Il difetto non si vedeva come un difetto: un terreno piatto e uniforme si
legge come uno stile grafico, non come un dato mancante. Ma una collina e una pianura uscivano
identiche, e in un gioco in cui il sito è tutto — fertilità, pietra, vento, sole — il terreno
era l'unica cosa che non raccontava niente di sé.

**Alternative scartate.**
1. *Ombreggiare a tempo di disegno, nello shader.* Scartata: qui non c'è un motore 3D, è una
   tela 2D, e il rilievo non cambia mai. Calcolarlo sessanta volte al secondo per un dato
   immutabile è spesa pura.
2. *Una scala di pendenza assoluta, uguale per tutti i siti.* Scartata misurandola: un deserto
   piatto diventava carta bianca e una valle alpina carbone. La scala si tara sul sito.
3. *Alzare i pixel per cella del buffer da 2 a 3 o 4.* Scartata: 4 sono 9,4 megapixel, oltre
   quel che Safari su telefono alloca. La grana ancorata al terreno costa zero memoria e
   risolve lo stesso problema.
4. *Tenere il verde a una fermata sola.* Scartata: era la ragione per cui un bosco sembrava un
   prato scuro.

**Costo.** Il caricamento passa da **905 ms a ~1.400 ms** (stessa macchina, dalla richiesta al
terreno in piedi). Il fotogramma non cambia: 16,7 ms prima e dopo, perché il buffer si dipinge
una volta sola. Mezzo secondo in più una volta, per un terreno che si vede.

**Rischi e criticità.**
- **Il mezzo secondo è misurato su un portatile.** Su un telefono di fascia media sarà
  plausibilmente il triplo, e non l'ho provato: non ho un telefono qui. È la misura che manca.
- **La costa che serpeggia è un cambio al GENERATORE**, non al disegno. Le colonie già
  fondate hanno i loro numeri del sito scritti in riga al momento dell'atterraggio: il
  terreno che vedranno adesso è leggermente diverso da quello su cui quei numeri furono
  calcolati. Lo scarto è piccolo (la costa si sposta di una ventina di celle) ma esiste, e
  l'unico modo pulito di azzerarlo è rifondare le colonie di prova.
- **Il disegno resta verificato a occhio.** I test tengono il modello di luce — piano uguale a
  1, verso del sole, acqua che si fa fonda, niente terrazze — ma che il risultato sia *bello*
  lo dicono solo le schermate, una per volta, su una finestra sola.
- **La memoria del rilievo** è ~1,8 MB per colonia, tenuti vivi in una `WeakMap` finché la
  colonia è viva. Con una colonia sola non si vede; passando fra colonie senza ricaricare, va
  guardato.

**Da rivedere se.** Il caricamento su telefono risulta inaccettabile: la via è dipingere il
buffer a pezzi, un riquadro alla volta, invece di tutto in una passata — il che cambia
l'architettura del disegno, non una costante.

---

## ADR-012 — La prima colonia di un mondo online nasce da una variabile, non da una rotta

**Decisione.** All'avvio, e **solo** se `BOOTSTRAP_COLONY` è impostata, il servizio conia una
colonia e scrive il token nei propri log. Due guardie: senza la variabile non fa niente, e se
esiste già un giocatore si rifiuta.

**Motivazione.** Un giocatore nasce da `app.cli`, che è amministrazione locale e non ha mai
avuto una rotta HTTP — è la ragione per cui rendere pubblico il repository non ha aperto nulla
a nessuno. Ma su un'istanza del piano gratuito **non esiste una shell**, quindi quel comando
non si può lanciare lì dentro, e un mondo online senza un solo giocatore non si può provare.

**Alternative scartate.**
1. *Una rotta di amministrazione protetta da un segreto.* Scartata: è esattamente la
   superficie che il progetto ha evitato dal primo giorno, e un segreto in un header è una
   cosa che si dimentica addosso a un servizio pubblico.
2. *Aprire il database alla rete e coniare da casa.* Scartata: espone il database a internet
   per sempre, per un'operazione che serve una volta.
3. *Un cron job che esegue la CLI.* Scartata: un servizio in più che resta lì, e un cron che
   conia proprietari a ogni firing è peggio di questo.
4. *SSH sull'istanza.* Non disponibile sul piano gratuito.

**Costo.** Il token passa dai log del servizio. Sono privati del workspace, ma restano
scritti: la variabile va tolta subito dopo, e questo è un passo che dipende da una persona.

**Rischi e criticità.**
- **Un percorso di creazione che vive nel codice di produzione.** Innocuo finché le due
  guardie tengono, e c'è un test per ciascuna — verificato che cadono se le si toglie. Ma è
  una superficie che prima non esisteva.
- **Il token nei log** resta finché il servizio non ruota i log. Chi legge i log del workspace
  legge il token del primo giocatore.
- **Solo il PRIMO.** Per il secondo giocatore serve comunque la riga di comando: questa non è
  una via per amministrare un mondo, è una via per accenderlo.

**Da rivedere se.** L'istanza passa a un piano con shell: allora `app.cli` si lancia lì e
questo modulo esce, perché smette di avere una ragione.

---

## ADR-013 — Ricominciare è amministrazione, non una mossa del gioco

**Decisione.** Un soft reset (`app.resetcli --confirm`, o la variabile `RESET_WORLD` su un
servizio senza shell) cancella giocatori, colonie, ordini, impianti, scorte e ledger, e
**lascia in piedi il pianeta**. Le tre guardie che rendono definitivo l'atterraggio restano
dove sono: il reset le disattiva di proposito per la durata di una transazione.

**Motivazione.** Provare il gioco significa inevitabilmente volerlo ricominciare, e oggi non
si poteva: la chiave esterna dal ledger, il trigger di immutabilità e il vincolo
sull'atterraggio formano un anello chiuso — verificato sul campo, non a memoria. Quelle
guardie però sono giuste: sono regole del mondo. Ciò che mancava era il gradino sopra, dove si
cancella un salvataggio.

**Alternative scartate.**
1. *Rendere reversibile l'atterraggio.* Scartata: una casella buona è scarsa, e poterci
   ripensare gratis toglierebbe il peso all'unica scelta che il pianeta chiede.
2. *Abbandonare la colonia come mossa di gioco.* Non scartata — rimandata. È design vero
   (penali? attesa? si può riatterrare?) e non si improvvisa dentro un comando di servizio.
3. *Cancellare a cascata con `ON DELETE CASCADE`.* Scartata: le chiavi sono `NO ACTION` di
   proposito, perché niente sparisca di nascosto. L'ordine di cancellazione è esplicito.
4. *Rigenerare anche il pianeta.* Scartata: costa minuti di CPU e, col seme fisso, darebbe lo
   stesso pianeta. Serve solo cambiando seme o generatore, ed è un'altra operazione.

**Costo.** Un percorso distruttivo che vive nel codice di produzione, e un trigger di
immutabilità che per qualche istante è spento.

**Rischi e criticità.**
- **Una variabile d'ambiente che azzera un mondo** è la cosa più pericolosa di questa sessione.
  Per questo è idempotente: l'ultima parola onorata si conserva sulla riga del mondo, quindi
  una variabile dimenticata è innocua e per azzerare di nuovo se ne cambia una. C'è un test, e
  cade se si toglie la memoria.
- **Il trigger va riacceso.** Se restasse spento sarebbe un difetto invisibile: tutto
  continuerebbe a funzionare finché qualcuno non riscrive il passato. C'è un test che prova a
  cancellare dal ledger *dopo* il reset e pretende un rifiuto.
- **La linea del tempo della politica** va riaperta, o la prima colonia nuova verrebbe
  liquidata su un intervallo che nessun periodo copre — caso rifiutato, non pagato come zero.
  Anche questo ha il suo test.
- **Niente backup automatico prima del reset.** `scripts/backup.sh` esiste e va lanciato a
  mano: il comando non lo fa per conto suo, e su un mondo condiviso vero dovrebbe.

**Da rivedere se.** Arriva l'abbandono come mossa di gioco: allora il reset resta per
l'amministrazione e smette di essere l'unico modo di liberare una casella.

---

## ADR-014 — Il fiume viene dal pianeta, e nessun sito è sterile

**Decisione.** Tre cose, viste tutte nella stessa schermata di gioco e tutte con la stessa
forma: il terreno diceva cose che il pianeta non aveva detto.

1. **Il fiume c'è solo se la casella del mondo ha un fiume.** `citygen` leggeva
   `world_tiles.river_flow` alla lettera, ma quel numero è *deflusso accumulato* e ogni casella
   di terra porta almeno la propria pioggia: sulla mappa spedita il 62% delle caselle era sopra
   zero, e ognuna di quelle si apriva con un fiume in mezzo. Chi costruisce un `Site` ora
   confronta la portata con `worldgen.river_min_flow` — la **stessa soglia** su cui il globo ha
   sempre disegnato i suoi fiumi — e passa zero quando non la raggiunge. Sulla mappa spedita si
   passa dal 62,4% all'1,4%. Gli specchi d'acqua restano: vengono dalle conche, non dal fiume.
2. **L'ombreggiatura del rilievo è stata tolta**, non spenta con una costante. Il rilievo di
   una colonia viene da un rumore a poche armoniche, quindi le sue pendenze sono larghe e
   regolari: ombreggiarle non produceva colline, produceva fasce diagonali chiare e scure lunghe
   tutta la mappa, sempre nella stessa direzione. L'ombra corta sotto una pianta resta — quella
   dice che la pianta sta in piedi.
3. **Nessun posto è del tutto sterile.** Ogni terra asciutta che non sia ghiaccio porta un fondo
   di fertilità e di copertura, più delle **macchie** larghe che fanno l'oasi, la radura in
   quota, la conca erbosa in mezzo alla ghiaia. Dove la macchia è forte rompe anche la lastra di
   roccia in pietraia — che conta come pietra esattamente come la roccia, quindi la montagna
   resta la montagna e in più ha dove piantare qualcosa.

**Motivazione.** Un fiume su ogni casella toglie al fiume il suo significato: se c'è ovunque
non è una ragione per scegliere un posto. E una casella con zero cibo e zero legna non è un
sito difficile, è un sito che non si può giocare — il deserto e la roccia nuda erano
esattamente quello.

**Alternative scartate.**
1. *Tenere l'ombreggiatura abbassandone la forza.* Scartata: il difetto non è l'intensità, è la
   forma. Fasce deboli restano fasce.
2. *Un secondo numero di soglia dentro `citygen`.* Scartata: sarebbe stata l'ottava coppia di
   copie che devono essere d'accordo. La regola ha una definizione sola, in `worldgen`, e il
   client legge lo stesso numero dal file del pianeta.
3. *Azzerare la portata nella tabella del mondo.* Scartata: la mappa è immutabile, e il
   deflusso è un dato vero che serve ad altro. Si filtra al confine, dove si costruisce il sito.
4. *Un velo di verde uniforme su tutto.* Scartata: un deserto con un velo di verde dappertutto
   non è un deserto, è una steppa. Le macchie sono larghe e rade di proposito.
5. *Alberi anche sulla calotta polare.* Scartata, ed è l'eccezione dichiarata: su un ghiacciaio
   non cresce niente. Se un giorno si vorrà colonizzare una calotta, la risposta è un modo di
   vivere diverso, non un albero sul ghiaccio.

**Costo.** Il gemello TypeScript e quello Python sono cambiati insieme e `reference.json` è
stato rigenerato: una deriva di una cella fa cadere la build, come sempre. Due test di
atterraggio dicevano cose che non sono più vere e sono stati riscritti — non rilassati per
farli passare: il margine fra una sponda di fiume e il deserto intorno **si è davvero
ristretto**, ed è giusto che il test lo dica.

**Rischi e criticità.**
- **L'economia di ogni sito si è spostata verso l'alto.** `food` e `timber` non sono più mai
  zero, quindi il bilanciamento della produzione va riguardato: il deserto era il sito povero
  di tutto e adesso è solo il più povero.
- **Il fiume nel deserto vale meno di prima.** Sulla fertilità di punta il vantaggio della
  sponda è sceso da circa otto volte a circa due. Resta la sola fonte d'acqua corrente — e
  quella sì, è zero contro novanta — ma se il fiume deve tornare a essere *la* ragione per
  attraversare la sabbia, la leva è `RIPARIAN_GAIN`, non il fondo.
- **Un fiume è ora raro: l'1,4% delle caselle.** È voluto — una casella col fiume diventa
  contesa — ma su un mondo con pochi giocatori significa che quasi nessuno ne vedrà uno.
- **Il terreno senza ombreggiatura è più piatto da leggere.** Le colline si intuiscono
  dall'acqua che si raccoglie e dalla roccia che affiora, non dalla luce. Se non basterà, la
  strada non è rimettere l'ombra: sono le curve di livello o un rilievo con più armoniche.

**Da rivedere se.** Il rilievo della colonia smette di essere un rumore a poche armoniche: con
una geografia vera — creste, valli scavate dall'acqua — l'ombreggiatura tornerebbe a dire
qualcosa invece di stampare righe.

**Nota a margine — un difetto trovato per strada.** La CI di questa modifica è caduta su un
test che non c'entrava niente: `rewind` invecchiava le colonie **sottraendo** dal momento in
cui erano nate, e l'orologio veniva fermato con una **seconda** lettura. Fra le due, su una
macchina carica, il secondo gira: il tempo trascorso diventava 61 invece di 60 e la colonia si
trovava 244 di pietra invece di 240. È il genere di caduta che si chiama *flaky* e si ririlancia.
Riprodotto apposta (un secondo di attesa in mezzo alla preparazione: stesso numero, `100244`),
e chiuso alla radice — l'età si scrive come un **istante**, e invecchiare e fermare escono da
**una sola** lettura dell'orologio. C'è un test che fa girare il secondo di proposito: senza la
correzione cade sempre, non una volta su venti.

---

## ADR-015 — La colonia è una griglia di esagoni, e un esagono è un metro quadro

**Decisione.** Il terreno della colonia smette di essere una scacchiera di celle quadrate da
otto metri e diventa una griglia di **esagoni con la punta in alto**, uno per metro quadro,
righe sfalsate di mezzo esagono. Le linee si accendono e si spengono da un comando. Con
1.536 esagoni di lato la colonia è **1,65 km × 1,43 km**.

Gli esagoni restano nello stesso vettore rettangolare di prima — colonna e riga, sfalsamento
"odd-r" — quindi il confronto cella per cella fra i due gemelli regge senza cambiare forma.
La geometria (dov'è un esagono, quale sta sotto un punto, chi è vicino a chi) ha **una sola
definizione**, in `colony/hexgrid.ts`: a quelle domande rispondono in tre — il pittore del
terreno, il puntatore e la griglia — e mezzo esagono di scarto fra il colore e la linea
sarebbe invisibile a qualunque test ma evidente a chiunque guardi.

**L'economia diventa un rilevamento a risoluzione fissa.** `citygen.survey` misura il sito su
768 campioni; `generate` disegna la mappa su 1.536. Il server chiama `survey`, e il client
chiama **lo stesso** `survey` per i numeri che mostra prima dell'atterraggio.

**Motivazione.** Un metro quadro è la scala a cui si costruisce: un edificio da dieci metri
per dieci occupa cento esagoni e si può disporre. Con la cella da otto metri ne occupava uno
e mezzo, cioè non c'era niente da disporre. Ed è la scala dell'immagine di riferimento.

**Numeri, misurati e non stimati.** Un esagono da 1 m² per coprire i 37,7 km² di prima sono
**37,7 milioni di esagoni e 264 MB** di soli dati: non è lento, è impossibile in un browser.
Quindi o l'esagono è un metro quadro e la colonia si restringe, o la colonia resta regionale
e l'esagono non è un metro quadro. Scelta la prima.

| | oggi (0,59 M celle) | ora (2,36 M esagoni) |
|---|---|---|
| `generate` (TypeScript) | 0,62 s | 1,51 s |
| `survey` | — | 0,37 s |
| pittura del terreno | ~0,8 s | 1,31 s |
| **totale, caricamento** | **~1,4 s** | **~3,2 s** |
| `generate` (Python, server) | 4,04 s | **3,96 s** — invariato, grazie a `survey` |

**Alternative scartate.**
1. *Rilevare l'economia alla risoluzione del disegno.* Scartata misurandola: sedici secondi
   dentro la richiesta di atterraggio, su un'istanza gratuita con un worker solo. Sarebbe un
   timeout, e per cambiare la terza cifra decimale di numeri poi arrotondati a intero.
2. *Far calcolare al client l'economia sulla mappa che disegna.* Scartata, ed è la più
   pericolosa perché funzionerebbe: darebbe numeri veri e **diversi** da quelli memorizzati.
   Scegliere un sito è una decisione presa sui numeri del visore.
3. *Un pixel per esagono nel buffer del terreno.* Scartata: mezzo esagono di sfalsamento non
   avrebbe dove stare e il buffer tornerebbe una scacchiera dritta, col colore mezza cella
   fuori dalle linee a righe alterne. Con due pixel, mezzo esagono è **un** pixel esatto —
   indici interi, nessun arrotondamento.
4. *Cuocere le linee dentro il buffer.* Scartata: non si potrebbero spegnere senza
   rigenerarlo, e a due pixel per esagono sarebbero una sbavatura grigia.
5. *Esagono a lato piatto.* Scartata per somiglianza con l'immagine di riferimento; è una
   riga di geometria, si cambia in un pomeriggio.
6. *Tenere i 37,7 km² con un esagono da 64 m².* Scartata dall'utente: salterebbe il metro
   quadro, che è la cosa che rende la griglia utile a costruirci sopra.

**Costo.** Il caricamento passa da ~1,4 s a ~3,2 s misurati su questa macchina. Il buffer del
terreno passa da 2,4 a 4,7 megapixel (19 MB) — sotto i 9,4 che Safari su telefono ha già
rifiutato una volta, ma non di molto.

**Rischi e criticità.**
- **Su telefono il caricamento può arrivare a dieci secondi.** Il messaggio di avanzamento
  c'è, ma è una attesa vera. Se diventa insopportabile, la strada è generare in un
  `Web Worker`, non ridurre la griglia.
- **La colonia si restringe da 37,7 km² a 2,4 km².** È la conseguenza diretta del metro
  quadro. Non c'è modo di avere tutti e due.
- **`room` non è più un numero che si possa contare sullo schermo**: conta le celle del
  rilevamento. A chi gioca si mostra la superficie edificabile in ettari, che è la stessa
  informazione in una forma verificabile. Ma nel codice resta un conteggio, e chi lo legge
  senza sapere questo lo interpreterebbe male.
- **Il terreno nel buffer è fatto di rettangoli, non di esagoni.** A due pixel per esagono i
  colori stanno nel posto giusto ma la forma la danno le linee sopra. Da vicino, con le linee
  spente, il confine fra due terreni è squadrato invece che a nido d'ape.
- **La colonia già fondata ha numeri scritti con la griglia vecchia.** Il disegno cambia, i
  numeri memorizzati no: per vederli coerenti serve un soft reset e un nuovo atterraggio.
- **Il bake delle colonie di esempio era rotto da mesi** e non se n'era accorto nessuno,
  perché `ColonyPicker` non sta su nessuna pagina. *(Chiuso in ADR-018: tolto.)*

**Da rivedere se.** Si comincia a costruire davvero: allora servirà sapere quali esagoni sono
occupati, e quello è uno strato nuovo — non una proprietà del terreno.

---

## ADR-016 — Il client diventa un'applicazione Godot, e il generatore ha un terzo gemello

**Decisione.** Il client di gioco viene rifatto in **Godot 4**, come **applicazione desktop**.
Il server non cambia: FastAPI, PostgreSQL, il pianeta, l'economia, il ledger e le regole
restano dove sono. Godot sostituisce il modo di **guardare** e di **comandare**, non il mondo.

Primo strato, ed è quello che regge tutto il resto: `client/exilium/citygen.gd`, il **terzo
gemello** del generatore, tenuto cella per cella sullo **stesso** `reference.json` che tiene
quello TypeScript. `client/tests/run.gd` gira senza finestra e senza editor, e sta in CI.

**Motivazione.** Dove sta andando il gioco — costruire sulle caselle, unità, animazioni — è
lavoro che in Godot è già risolto e su una tela 2D si fa a mano per sempre. Gli esagoni in
particolare: `TileSet` ha la forma esagonale con l'asse di sfalsamento scegliibile, cioè
esattamente il layout "odd-r" che `hexgrid.ts` implementa a mano.

**Misurato, non supposto.**

| | |
|---|---|
| i tre gemelli sullo stesso riferimento | **82 verifiche, 20.480 celle identiche** |
| il PRNG (`seed_int`, `next_uint`, `direction`) | identico **bit per bit** |
| `generate` 0,59 M celle, JavaScript | 0,62 s |
| `generate` 0,59 M celle, **GDScript** | **2,79 s — circa 4,5× più lento** |

**Il problema aperto, e va detto prima di costruirci sopra.** A 2,36 milioni di esagoni
GDScript impiegherebbe ~11 s, più il rilevamento: troppo per uno schermo di caricamento.
La via naturale sembrava il parallelismo — il generatore è puro e ogni cella è indipendente,
e un'applicazione desktop ha thread veri. **Misurato in CI, su quattro core non strozzati: non
serve a niente.**

```
core dichiarati dal sistema: 4
una sola passata, 0,59 M celle  -> 2.56 s
quattro blocchi in fila         -> 2.63 s
gli stessi quattro in parallelo -> 2.64 s   (1.0x)
```

Quattro blocchi indipendenti su quattro thread impiegano **esattamente** quanto in fila.
GDScript, per questo carico, è di fatto serializzato. La proiezione a 2,36 milioni di esagoni
resta **~10,5 s, con o senza thread**.

La misura la continua a fare la CI: `tests/bench.gd` gira a ogni giro e stampa il numero nel
log, senza far cadere niente. Serve perché il numero cambierà — con una versione nuova del
motore, o con una di queste tre strade:

1. **Non generare tutto al caricamento.** Il disegno può crescere a pezzi, man mano che la
   telecamera si sposta; il rilevamento dell'economia sta già a 768 e costa 2,5 s. È la via
   che non cambia linguaggio, e va provata per prima.
2. **C#** (Godot .NET): stesso motore, thread veri, un runtime in più da spedire.
3. **Una GDExtension** in C++ o Rust: la più veloce e la più complicata da costruire.

Quel che NON va fatto è tenersi i dieci secondi sperando che passino.

**E il client si può guardare senza editor.** `--headless` non disegna affatto, ma con un
server grafico finto (xvfb) e OpenGL su Mesa, Godot rende davvero: `tests/shot.gd` fotografa
una scena in un PNG. Un visore è l'unico posto dove sbagliare non si vede — viene fuori una
cosa un po' strana, e una cosa un po' strana sembra una scelta — quindi poter guardare senza
aprire l'editor è la differenza fra verificare e fidarsi.

**Alternative scartate.**
1. *Restare sul browser e basta.* Il fastidio immediato — i 3,2 s di caricamento — si
   aggiusterebbe con un Web Worker, molto più a buon mercato. Scartata perché il motore serve
   per dove si va, non per dove si è: il posizionamento degli edifici e le unità resterebbero
   lavoro a mano su una tela 2D per sempre.
2. *Esportare anche per il web.* Scartata dall'utente. Il `.wasm` di Godot è ~40 MB (~5 MB in
   Brotli) più il pacchetto del gioco, e servirebbero gli header COOP/COEP su Render: la prima
   apertura peggiorerebbe rispetto alla pagina statica di oggi.
3. *Chiedere il terreno al server invece di generarlo.* Scartata per la stessa ragione di
   sempre: rimetterebbe un'istanza addormentata sulla strada del semplice guardare.
4. *Un secondo file di riferimento dentro `client/`.* Scartata: due riferimenti che devono
   coincidere sono precisamente il difetto che il riferimento esiste per impedire. Il test
   Godot apre quello del frontend per percorso assoluto.
5. *`latest` come versione di Godot in CI.* Scartata: il motore decide come si arrotondano i
   numeri in virgola mobile, e questo job esiste per dire che tre lingue danno le stesse
   celle. Un aggiornamento silenzioso trasformerebbe una verifica in una scommessa.

**Costo.** Una terza copia del generatore — ma sotto la stessa disciplina delle altre due, che
è la ragione per cui è accettabile. Un quarto job in CI (~1 minuto con la cache del binario),
su un repository che i minuti li ha contati. E, davanti, la riscrittura del globo (231.042
poligoni, oggi three.js), della HUD e del client dell'API.

**Rischi e criticità.**
- **Si perde "apri un link e giochi"**, che è come il gioco viene provato oggi. Per questo il
  client web **resta vivo** finché quello Godot non lo sostituisce davvero: non deve esistere
  un periodo senza gioco.
- **Le prestazioni di GDScript sono un rischio non chiuso** (vedi sopra). È la ragione per cui
  il generatore è stato portato *per primo*: se la risposta fosse no, si scopre adesso.
- **Tre copie divergono più facilmente di due.** Il riferimento le tiene, ma solo per quello
  che copre: le celle, l'economia e i semi. Quel che non è nel riferimento non è protetto.
- **Il repository ospita due client.** Finché dura, ogni regola del gioco ha due case.

**Da rivedere se.** Già rivisto: i thread non bastano (vedi sopra). La prossima decisione è
fra generare a pezzi e cambiare linguaggio, e va presa prima di costruirci sopra il resto del
client — non dopo.

---

## ADR-017 — Il pianeta si genera dove c'è memoria, non dove viene servito

**Decisione.** Il pianeta diventa un **file portatile**. `python -m app.mapfile dump` lo genera
dove c'è memoria — un portatile, un runner di CI, qualunque cosa — e `python -m app.mapfile
load` lo rimette dentro un PostgreSQL qualunque **a memoria costante**, via `COPY`. Il server
che serve l'API non genera più niente.

**Motivazione.** Finora il pianeta lo costruiva l'istanza dell'API, all'avvio. Misurato:
**358 MB di picco** alla dimensione di oggi, su un'istanza gratuita che ne ha **512**. Siamo
al soffitto, e il pianeta non può crescere — non perché manchi lo spazio su disco, ma perché
la macchina che lo **serve** non ha la RAM per **farlo**. Sono due cose diverse tenute insieme
da un dettaglio di implementazione, e questo le separa.

**Misurato, su un pianeta ×4 (924.162 caselle):**

| | |
|---|---|
| generarlo e scriverlo | 153 s, **picco 1.407 MB** |
| il file | 71 MB compressi |
| **caricarlo** | 36 s, **picco 36 MB** |
| in tabella | 475 MB |

I 36 MB non crescono col pianeta: si legge una riga per volta e si scrive in un canale.

**La cosa che il file deve garantire**, e che non è "il caricamento funziona": un database
riempito dal file e uno riempito dal generatore devono essere **lo stesso database**. C'è un
test che lo misura — carica, fotografa, cancella, genera, fotografa di nuovo e confronta
casella per casella, colonna per colonna. Se le due strade divergessero avremmo due pianeti
con lo stesso nome, e di copie-che-devono-coincidere questo progetto ne ha già pagate sette.
Per questo `mapservice.TILE_COLUMNS` e `as_database_row` sono **una definizione sola**: la
generazione e il caricamento vestono le caselle con la stessa funzione.

**Alternative scartate.**
1. *Aprire il database alle connessioni esterne e caricarlo da fuori.* È la via rapida, e
   resta possibile — ma espone il database con la sola password per la durata dell'operazione,
   e non toglie il problema: al prossimo pianeta si riparte da capo.
2. *Alzare l'istanza a pagamento per il tempo della costruzione.* Funziona, costa pochi
   centesimi, e non lascia niente dietro di sé. Questo invece vale per sempre e per qualunque
   provider.
3. *Rendere `worldgen` parsimonioso* (colonne invece di oggetti). È il lavoro giusto un giorno
   — 1,5 KB per casella sono quasi tutti ingombro di Python — ma è un refactor del file più
   delicato del progetto per risolvere un problema che si può togliere di mezzo senza toccarlo.
4. *Un formato binario.* Scartato: una riga JSON per casella si guarda con `zcat` quando
   qualcosa non torna, e non ha bisogno di una libreria. A 71 MB compressi il risparmio non
   vale l'opacità.
5. *Scrivere e leggere in due file separati.* Scartato: le due metà di un formato separate
   sono il modo in cui un formato comincia a non essere d'accordo con se stesso.

**Il sigillo sta in fondo**, non in testa, perché chi scrive non può conoscere la somma prima
di aver finito. Chi legge lo verifica **dentro la transazione**: un file troncato o corrotto
non lascia mezzo pianeta nel database, non lascia niente. Ci sono i test per tutti e tre i
casi — troncato, corrotto, e scritto quando una casella aveva altre colonne (il peggiore:
riempirebbe le colonne sbagliate con valori giusti, senza nessun errore).

**Costo.** Un formato in più da mantenere, e un file da qualche decina di megabyte da spostare
a mano quando si cambia pianeta.

**Rischi e criticità.**
- **Non è ancora collegato al deploy.** Il comando di avvio genera ancora il pianeta se manca.
  Collegarlo dipende da dove si finisce per ospitare, e indovinare sarebbe peggio che aspettare.
- **Il file non è versionato nel repository** e non deve esserlo: decine di megabyte di dati
  rigenerabili dal seme. Ma questo vuol dire che **qualcuno deve conservarlo**, o rigenerarlo.
- **Un pianeta più grande di frequenza 160 non entra comunque**: c'è un vincolo nello schema
  (`world_map_frequency_check`) e una guardia in `worldgen`. Alzarli è una migrazione, come
  già fatto in 0004 e 0006 — questo ADR non lo fa.
- **Il database gratuito di Render scade il 17 ottobre 2026** e accetta solo connessioni
  interne. Questo comando rende indolore il trasloco, ma il trasloco va deciso.

**Trovato da una revisione, e sarebbe esploso solo in produzione.** `transaction()` mette
`statement_timeout` a sessanta secondi, perché protegge le **richieste**. Ma il pianeta entra
con un `COPY` solo, e quel `COPY` dura **36 secondi su socket locale** per un pianeta ×4:
verso un database gestito in rete — cioè l'unico caso per cui questo comando esiste — i
sessanta secondi si sforano, e il caricamento viene annullato e rifatto indietro a tre quarti
dell'opera. Il caricamento ora toglie il limite per sé: non è una richiesta, è un comando
amministrativo che qualcuno lancia guardandolo. C'è un test che legge `statement_timeout`
prima e dopo.

La stessa revisione ha trovato che il sigillo copriva **solo le caselle**: un seme o una
versione del generatore corrotti entravano in `world_map` in silenzio mentre la somma
continuava a tornare — un pianeta che dichiara di essere un altro pianeta. Adesso il sigillo
copre anche l'intestazione. E un gzip tagliato a metà dava `EOFError` invece di un rifiuto
comprensibile, e un'intestazione monca un `KeyError`: per chi guarda sono tutti lo stesso
caso, "questo file non si carica", e adesso lo dicono così.

**Da rivedere se.** `worldgen` diventa parsimonioso: allora l'istanza potrebbe tornare a
generare da sola, e questo resterebbe utile solo per traslocare.

---

## ADR-018 — Il visore di esempio delle colonie viene tolto

**Decisione.** Spariscono `backend/app/colonyexport.py`, `frontend/app/colony/ColonyPicker.tsx`,
`frontend/app/lib/colony.ts` e i file cotti in `frontend/public/colony/`.

**Motivazione.** Servivano a mostrare una colonia senza un server, quando il terreno era un
file cotto a tempo di build. Non è più così: il gioco genera il terreno nel browser dal seme
che il server gli dà, e il client Godot fa lo stesso. Il visore di esempio non sta su nessuna
pagina, nessuno script lo lancia, nessun workflow lo nomina — verificato, non supposto.

Ed era **rotto**. `seed_for` ha perso un argomento quando il seme è diventato una proprietà
della casella, e quella riga è rimasta indietro: il bake non girava più da mesi. Se n'è
accorto qualcuno solo perché ho provato a lanciarlo per un'altra ragione.

**È il pezzo di prova che conta più della decisione.** Il codice morto non resta fermo: marcisce,
e marcisce in silenzio. Tenerlo "per ogni evenienza" significa che il giorno in cui servisse
non funzionerebbe comunque — e nel frattempo ogni modifica alla forma di una cella deve
attraversarlo. Questo ha già pagato quel prezzo una volta, quando gli esagoni hanno cambiato
la metratura e ho dovuto sistemare anche lui.

**Alternative scartate.**
1. *Tenerlo e ridargli una pagina.* Sarebbe una pagina che mostra una colonia finta accanto a
   una che mostra quella vera. Due strade per la stessa cosa, e una sola provata.
2. *Tenerlo senza pagina, "per riferimento".* È quel che si è fatto finora, ed è come si è
   rotto senza che nessuno se ne accorgesse.

**Costo.** Se un giorno servisse mostrare una colonia senza server, si riscrive — e si
riscrive più in fretta di quanto si aggiusterebbe questo, perché il terreno adesso si genera
in tre lingue e tutte e tre sanno farlo da un seme.

**Rischi e criticità.**
- **Restano altri moduli senza test** e senza chiamanti automatici: `cityshots`, `worldshots`,
  `worldreport`, `sitefill`, `cli`, `resetcli`, `colonyref`. Sono strumenti da riga di comando
  che qualcuno lancia a mano, il che è legittimo — ma è la stessa condizione in cui
  `colonyexport` è marcito. **`colonyref` è il più pericoloso**: scrive il riferimento su cui
  poggiano i tre gemelli, ed è per questo che ADR-019 gli mette un test attorno.

---

## ADR-019 — Il cerchio della fiducia fra i tre gemelli si chiude

**Decisione.** `backend/tests/test_colonyref.py` confronta **quel che Python genera adesso**
con il `reference.json` che sta nel commit. Marcato `repo`, perché legge `frontend/`.

**Motivazione.** Il confronto fra le tre copie del generatore era a **stella, non a cerchio**.
TypeScript e GDScript guardano il file; **nessuno guardava se il file dice ancora quel che
Python fa**. Bastava cambiare una regola in `citygen.py` e dimenticare di rilanciare
`python -m app.colonyref`: i due gemelli continuavano a combaciare col file vecchio, tutto
restava verde, e intanto avevano smesso di combaciare con Python — cioè con l'unica copia che
decide davvero, perché è quella che gira sul server quando qualcuno atterra.

**Dimostrato, non supposto.** Cambiando `OASIS_FERTILITY_FLOOR` da 12 a 13 senza rigenerare:

```
test_colonyref  FAILED  'nilo' / fertility: la cella 0 vale 33 adesso e 32 nel file.
                        Rilancia `python -m app.colonyref` [...]
citygen.test.ts  9 passed
```

Il gemello TypeScript resta verde su un pianeta che Python non fa più. Ora il cerchio è
chiuso: **Python → file** (qui), **file → TypeScript** (`citygen.test.ts`), **file → GDScript**
(`client/tests/run.gd`).

**Gli altri due test** chiudono una trappola già scattata una volta: un campo nuovo in
`SiteEconomy` o in `Site` che il riferimento non scrive lascerebbe i gemelli a generare da un
sito incompleto — e a generarlo **uguale fra loro**, quindi verdi, e diverso da quel che
genera il server. È successo con le quattro attitudini energetiche.

**Alternative scartate.**
1. *Far rigenerare il riferimento alla CI e confrontare il risultato.* Sposterebbe il problema:
   un riferimento rigenerato automaticamente non è più un riferimento, è un'eco.
2. *Un gancio di commit.* Funziona finché qualcuno non lo salta, e non gira in CI.

**Costo.** `build()` rigenera cinque siti a ogni giro: 0,7 secondi.

**Rischi e criticità.**
- **Il test dice "rigenera", non rigenera.** È voluto: rimettere il file nel commit è una
  decisione — il riferimento cambia solo quando qualcuno ha deciso di cambiare una regola.
- **Non copre le cose che il riferimento non porta.** Il disegno, la luce, la resa: lì la
  divergenza fra le copie resta possibile e nessun test la vedrebbe.

---

## ADR-020 — Il backend guadagna un controllo statico

**Decisione.** `mypy` gira in CI, nel job `backend`, **prima** dei test. Non in modalità severa:
lo scopo non è annotare tutto il progetto, è accorgersi quando due pezzi di codice smettono di
essere d'accordo su una firma.

**Motivazione, con un nome.** `colonyexport.py` chiamava `seed_for` con tre argomenti quando la
firma ne prendeva due. È rimasto così **per mesi**, perché nessuno lanciava quel comando e
nessuno strumento guardava. Il frontend aveva `tsc --noEmit` in CI dal primo giorno; il backend
non aveva niente. Provato: su quella riga mypy dice `Too many arguments for "seed_for"`.

**Cosa ha trovato subito**, su codice che tutti i test dichiaravano sano:

| | |
|---|---|
| `sitefill.measure` | dichiarava di restituire `SiteEconomy`, restituiva una **coppia**. Chi chiama la spacchetta, quindi non si è mai rotto niente — ed è il punto: una firma che mente non rompe niente finché qualcuno non la legge per sapere cosa aspettarsi. |
| `sim/rules.py` | `built[commitment.choice]` con `choice: str \| None`. Il database lo vieta (vincolo in `0020`), ma se mai fosse scavalcato `built[None]` **non darebbe errore**: darebbe una colonia con un'opera senza nome, che produce e consuma per sempre. Adesso si ferma. |
| `worldgen` | un indice dichiarato `tuple[int, int, int]` le cui chiavi sono float arrotondati, e una tupla costruita in un ciclo passata dove ne servono tre. |
| `sim/config.py` | `WORKS[kind]["hours"]` era un `object`, quindi ogni conto sull'economia era un conto su un `object`. Ora c'è un `TypedDict` che dice che cos'è un'opera. |

**Alternative scartate.**
1. *Sei test attorno ai sei moduli senza test.* Sproporzionato, e non avrebbe trovato niente di
   tutto questo: il difetto di `colonyexport` era in una funzione che un test avrebbe dovuto
   **eseguire** per vederlo.
2. *Modalità severa.* Alzare l'asticella oltre quel che si riesce a tenere pulito significa
   disattivare il controllo fra un mese.
3. *Un linter invece di un controllo dei tipi.* Un linter non sa quanti argomenti prende una
   funzione definita in un altro file, che è esattamente il difetto da cui veniamo.

**Costo.** Cinque secondi in CI, e cinque pacchetti in più nel lock.

**Rischi e criticità.**
- **Non controlla i corpi delle funzioni non annotate**, che in questo progetto sono molte. Un
  difetto lì resta invisibile come prima.
- **Tre `type: ignore`** in `worldreport.py`, dove `ctypes` espone dei nomi solo su Windows.
  Sono mirati e commentati: l'alternativa era zittire il controllo dappertutto.
- **C'è un test che verifica che la riga in CI esista** (`test_workflow.py`): toglierla non
  farebbe cadere nient'altro.
