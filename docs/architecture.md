# Fondazione del mondo autoritativo

## Decisioni iniziali

Un mondo singleton (id 1), una città per giocatore, una risorsa `alloy`.
Gli importi sono interi in millesimi: 1000 milli-alloy = 1 alloy. Nessun float.
API e worker usano esclusivamente l'orologio PostgreSQL in UTC, troncato al secondo.
Il client invia intenzioni, mai saldi, tassi, proprietari, date o risultati.
Ogni tick scade alle 00:00 UTC: 24 ore esatte, indipendenti da ora legale e riavvii.
Il primo tick è la prima mezzanotte successiva alla migrazione.

Regole dimostrative, versionate come ruleset 1 (non bilanciamento definitivo):

- politica `balanced`: 10 milli-alloy/s; `industrial`: 20 milli-alloy/s;
- ogni livello produttivo aggiunge 5 milli-alloy/s;
- dotazione iniziale 100000 milli-alloy, anch'essa registrata nel ledger;
- un ordine `upgrade` per città per tick, costo 100000 al momento della risoluzione;
  se manca la copertura, l'ordine fallisce senza effetti;
- un `policy_vote` per città per tick. Maggioranza semplice, pari peso per città;
  pareggio o nessun voto conservano la politica corrente;
- nessuna modifica/cancellazione dell'ordine accettato nella prima versione.

Queste due regole esercitano ordini strategici e decisioni politiche differite.
Guerre, fazioni, diplomazia e bilanciamento politico restano da progettare.

## Dove vivono le regole

Le regole del gioco stanno in `app/sim/`: stato e effetti come valori congelati (`state.py`),
costanti di bilanciamento come dati (`config.py`), regole pure (`rules.py`) e il tick
(`tick.py`). Quel modulo non può importare psycopg, FastAPI o il proprio adattatore, e il
vincolo non è una convenzione ma un test che analizza gli import con `ast`.

Una regola non scrive mai: **descrive**. `settle_city` restituisce una liquidazione,
`resolve_order` un esito, `advance` l'intero risultato di un tick — voci di ledger comprese —
senza toccare nulla. `app/service.py` è l'unico codice che trasforma un effetto descritto in
una riga, dentro una sola transazione.

La granularità è scelta, non casuale. Le operazioni economiche usano regole **per entità**
perché città diverse devono procedere in parallelo e serializzare solo sulla propria riga;
una regola che pretendesse il mondo intero a ogni lettura le rimetterebbe in fila. Solo il
tick, che il lock esclusivo già serializza, è una regola su tutto il mondo. Il perché per
esteso è in `decisions.md`, ADR-003.

## Schema e invarianti

`world` contiene politica, prossimo confine temporale e numero dell'ultimo tick.
`players` contiene soltanto hash SHA-256 di token casuali ad alta entropia.
`cities` contiene proprietario univoco, livello e istante di produzione liquidata.
`resource_ledger` contiene accrediti/addebiti firmati, causale, evento univoco e data
economica. Il ledger resta l'unica fonte di verità ed è immutabile. `cities.balance_milli`
è un cursore materializzato del saldo, non un secondo saldo autonomo: il trigger di
inserimento del ledger lo aggiorna nella stessa transazione dell'entry ed è SEMPRE uguale
a `SUM(resource_ledger.amount)` (invariante verificata dai test di equivalenza). Serve a
evitare la scansione O(n) del ledger sia in lettura del saldo sia nel controllo di scoperto.
`orders` conserva intenzione, chiave idempotente, tick bersaglio ed esito.
`ticks` conserva confine, ruleset e riepilogo del risultato atomico.

Vincoli PostgreSQL: mondo unico, foreign key senza cascade distruttivi, un solo
proprietario per città, importi non nulli e segni compatibili con causale, eventi
ledger univoci, chiave ordine unica per città, massimo un ordine per tipo/città/tick,
numero tick e confine univoci. Trigger vietano UPDATE/DELETE/TRUNCATE del ledger e
dei tick. Il trigger degli addebiti blocca la riga città, aggiorna il cursore del saldo
e impedisce un saldo negativo con costo O(1). Un amministratore DB resta fidato: può
cambiare lo schema o disabilitare trigger.

Invarianti applicative e concorrenza: le operazioni economiche (lettura città, invio
ordine, provisioning) prendono `world FOR SHARE` — un lock condiviso che le lascia
procedere in parallelo tra loro ma esclude un tick in corso — e serializzano solo sulla
riga della propria città (`cities FOR UPDATE`). Città diverse non si bloccano a vicenda;
la stessa città serializza, così una produzione non viene mai liquidata due volte. Il tick
prende `world FOR UPDATE` (esclusivo): attende le operazioni in volo e ne blocca di nuove,
osservando un mondo quiescente. Non viene mai liquidata produzione oltre un tick non ancora
risolto. Nessun tempo fornito dal client viene usato. L'accesso a una città richiede token
del suo proprietario (404 per città altrui).

## Produzione continua e tick

La produzione matura per tempo trascorso, anche senza richieste e durante downtime:
`(until - settled_at).total_seconds * rate`, con aritmetica intera e granularità 1 s.
Viene materializzata su lettura della propria città, invio ordine e tick; non richiede
un job al secondo. Il cursore e l'accredito vengono confermati nella stessa transazione.

Il worker prende il lock del mondo, legge `clock_timestamp()` DOPO il lock e, se il
tick è scaduto, esegue una sola transazione:

1. liquida tutte le città esattamente fino al confine con il vecchio tasso;
2. risolve gli upgrade in ordine di id, registrando costo ed esito;
3. conta i voti e applica la politica al periodo successivo;
4. registra il tick e avanza il confine di 24 ore.

Crash prima del commit: rollback completo. Crash dopo il commit: al retry il worker
trova il confine già avanzato. Due worker si serializzano sullo stesso lock. I vincoli
univoci sono un'ulteriore difesa. Nessuna chiamata esterna dentro la transazione.
Il recupero elabora un tick per transazione, fino a 32 per ciclo, senza saltare giorni.
Richieste economiche durante arretrati ricevono 503 + Retry-After; il worker recupera
la storia prima di accettare nuove intenzioni. `/health/ready` segnala anche gli arretrati.

La chiave `Idempotency-Key` UUID è obbligatoria. Il retry con identico payload restituisce
lo stesso ordine anche dopo la risoluzione; riusarla con payload diverso dà 409.
Il confronto precede il controllo degli arretrati: un retry non crea nuovi effetti.
Il cutoff è l'ora DB dopo acquisizione lock, non l'arrivo HTTP. Alla scadenza esatta
non si accettano ordini per il tick in chiusura.

## Geografia: il pianeta Hesperia

La mappa è separata dal mondo economico. `world_map` è singleton (id 1) e conserva nome,
seed, frequenza geodetica, livello del mare e versione del generatore; `world_tiles` conserva
una riga per casella. Come il ledger, entrambe sono un audit: trigger vietano
UPDATE/DELETE/TRUNCATE. Rigenerare non è un'operazione applicativa — `generate_and_store`
rifiuta con 409 se la mappa esiste già — ed è possibile solo tramite una migrazione dedicata
che disabilita i trigger, azzera le tabelle e le riabilita. È il percorso usato da tutte le migrazioni
che hanno cambiato la geografia, da `0004` a `0009`.

La sfera è un icosaedro suddiviso: ogni vertice originale è una casella del duale di
Goldberg, quindi esagoni con esattamente dodici pentagoni ai vertici dell'icosaedro
(`10*f² + 2` caselle). La generazione è deterministica dal seed e gira una volta sola: la
riproducibilità cross-platform dei float non è richiesta, quella entro un interprete sì ed è
verificata dai test. Nessun valore economico è in virgola mobile.

Il generatore v5 produce forme riconoscibili anziché macchie di rumore: catene montuose da
rumore *ridged* raccolto in cinture; fiumi da accumulo di deflusso a valle sul grafo delle
caselle, con i bacini chiusi abbastanza pieni promossi a laghi; deserti da un profilo zonale
delle precipitazioni con fasce aride subtropicali, continentalità (BFS della distanza dal
mare) e ombra pluviometrica campionata sopravvento; arcipelaghi da rumore ad alta frequenza,
con le componenti connesse a dare la dimensione di ogni massa continentale.

Tre meccanismi decidono la geografia, e vale la pena distinguerli perché fanno cose diverse.
Il **domain warping** — il campo continentale letto in un punto spostato da un secondo campo
di rumore — è ciò che dà penisole, insenature e un profilo che non sembra disegnato col
compasso; ma deforma un contorno senza cambiare che cosa è collegato a che cosa. A cambiarlo
sono i **bacini oceanici**: rumore *ridged* alto lungo linee e quasi nullo altrove,
sottratto alla terra. Dove una linea taglia un istmo lascia uno stretto, dove arriva a una
costa e si ferma lascia un golfo, dove due si incontrano lascia un mare interno. Il terzo è
un **dettaglio di costa** che si spegne con la distanza dalla linea d'acqua: applicato
ovunque bucherebbe gli interni continentali e punteggerebbe l'oceano profondo, applicato
solo alla costa è ciò che sfrangia le rive e lascia isolotti al largo.

Alzare la frequenza del campo continentale, che sarebbe la mossa ovvia per avere più
continenti, fa il contrario: misurata da 2.2 a 4.6, porta una massa sola a tenere dal 88 al
99% delle terre emerse, perché più terra vicino alla linea d'acqua percola più facilmente,
non meno. È il motivo per cui quel parametro è rimasto dov'era.

### L'acqua ferma

Il terreno, da solo, non produce laghi. La regola precedente — una casella senza vicine più
basse, che raccoglie abbastanza pioggia — poteva trovare soltanto una fossa larga una casella,
perché il fondo di un bacino vero è largo parecchie caselle e ognuna di esse ha una vicina più
bassa *dentro lo stesso bacino*. Su un pianeta di 193.212 caselle il risultato erano trenta
caselle di lago.

Le depressioni vengono quindi riempite fino al punto di sfioro (*priority flood*: si parte dal
mare e si cammina verso l'interno sempre dalla casella più bassa del fronte, così un bacino
circondato da terreno più alto si riempie esattamente fino al suo sfioro e non un metro di
più). Ciò che quella superficie copre è acqua. I fiumi sono instradati sulla superficie e non
sul terreno nudo, quindi un fiume entra in un lago, lo attraversa ed esce dall'altra parte
invece di fermarsi alla prima conca.

Due dettagli non ovvi, trovati entrambi da un test che falliva. La soglia di profondità si
applica al corpo d'acqua, non alla singola casella: applicata casella per casella ritaglia un
bordo frastagliato dentro un lago solo — la riva bassa diventa terra mentre il centro è acqua —
e lascia un fiume che risale verso il proprio lago. E la quota di una casella d'acqua è la
superficie, non il fondale, esattamente come per l'oceano: ogni casella di un bacino si riempie
allo stesso livello di sfioro, quindi il lago è piatto anziché una collina blu bitorzoluta.
La quota riempita vale però per **ogni** casella, non solo per i laghi: una conca troppo poco
profonda per contare come lago conservava il proprio fondale mentre il fiume che la attraversa
veniva instradato sul riempimento, cioè un fiume disegnato in salita fuori da una pozza.

### Dove va l'acqua su una superficie piatta

Il riempimento risolve una questione e ne apre un'altra: la superficie di un lago è piatta per
costruzione, quindi «scendi verso la vicina più bassa» non decide nulla proprio lì. Il pareggio
veniva risolto sul fondale sottostante, il che è sbagliato nel modo peggiore possibile: manda
l'acqua nel punto più profondo del bacino, l'unica casella che per definizione non ha uscita.
Misurato sulla mappa in produzione della v5: 709 caselle di terra senza deflusso, 651 dentro un
lago, e la portata più alta del pianeta — il drenaggio di un continente intero — si fermava lì.
Il pianeta non aveva un solo fiume che arrivasse al mare, cosa che nessuna metrica allora in uso
avrebbe potuto segnalare.

La risposta era già nel riempimento. Il *priority flood* raggiunge le caselle partendo dal mare
e andando verso l'interno, quindi **l'ordine in cui le raggiunge è l'ordine in cui l'acqua ne
uscirebbe**: a parità di livello, la vicina con ordine minore è quella più vicina a uno sbocco.
Il fiume attraversa il lago, esce dall'emissario e prosegue. Entrambi i confronti fanno calare
in senso stretto la chiave `(livello, ordine)`, quindi il grafo di deflusso non può contenere
cicli e la stessa chiave ordinata al contrario è un ordine valido per accumulare.

### Quanti fiumi disegnare

La portata si conta in caselle d'acqua piovana, quindi una soglia fissa significa un bacino
sempre più piccolo man mano che la griglia si infittisce. Triplicando il numero di caselle
abbiamo quindi triplicato i *corsi* senza ingrandirne nemmeno uno: a soglia 20, su questo
pianeta, un tratto di fiume era il drenaggio di una decina di caselle — un fosso. Ne venivano
disegnati 5.529 e quasi ognuno aveva un secondo corso parallelo accanto (0,94 vicini non
collegati per tratto), cioè il tratteggio che compare appena si zooma.

La soglia è quindi espressa **rispetto alla griglia su cui è misurata** — e rispetto alla
**terra** su quella griglia, non al pianeta: l'oceano non contribuisce a nessun bacino.
Contare l'intera sfera andava bene finché la frazione di terra non si muoveva, ed è stato
sbagliato nel momento in cui si è mossa: portandola dal 27 al 31%, il 15% di caselle in più
ha superato una soglia rimasta ferma e i corsi paralleli sono tornati. Un tratto ogni 538
caselle di **terra** (`river_min_flow`), che viaggia nei metadati come le altre costanti
condivise. Sul pianeta di produzione fa 133: 1.319 tratti e 0,19 paralleli per tratto.

Resta un difetto noto e non corretto: il percorso passa per i centri delle caselle, quindi su
una griglia esagonale svolta a scatti di 60°. Con un decimo dei tratti si nota molto meno di
prima, ma è una scalinata, non un meandro; risolverlo vuol dire disegnare la polilinea
smussata invece che segmento per segmento.

Le dimensioni contano quanto l'esistenza: alla prima versione con i laghi il corpo maggiore
copriva 625 caselle e dominava il continente che lo ospitava. Il raggio massimo delle conche
e dei mari interni è stato ridotto fino a lasciare un solo corpo oltre le trecento caselle,
qualche grande lago, e la coda di pozze sotto le cinque.

Un lago non è attraversato da un fiume. La casella di lago sta alla propria superficie,
quindi supera il test `elevation >= 0`, e raccoglie ogni goccia del suo bacino, quindi supera
anche quello sulla portata: il render model disegnava un fiume dritto in mezzo allo specchio
d'acqua. Il modello esclude ora le caselle di lago come *sorgente* di un tratto, e il fiume
finisce sulla riva perché il tratto che vi entra viene mantenuto.

Il rilievo da solo non offre comunque abbastanza conche, quindi il pianeta ne riceve di
seminate: scodelle con un bordo proprio, in due popolazioni distinte — molte piccole, poche
molto grandi — scavate nella terra e mai sotto il livello del mare, così una conca non toglie
superficie emersa, decide solo che parte di essa sta sott'acqua. Sono campionate per rifiuto
finché non cadono nell'entroterra: con tre quarti del pianeta sott'acqua un'estrazione cieca le
manda quasi tutte in mare, e se le poche grandi finiscano in un posto utile diventa un lancio
di dado che il seed vince o perde. Il bordo è deformato da rumore ad alta frequenza, perché una
scodella di raggio costante è un cerchio e un pianeta di laghi circolari sembra clip art.

I deserti sono passati da un terzo delle terre emerse a un quinto, e soprattutto hanno
cambiato natura. La continentalità non è più uniforme ma **pesata su quanto è già arida la
latitudine**: prosciugare tutto il pianeta in modo uniforme rendeva arida ogni massa
abbastanza larga da avere un interno e non lasciava comunque un deserto vero da nessuna
parte. Pesandola, il prosciugamento va dove i deserti nascono davvero — l'interno di un
continente subtropicale — e un interno equatoriale o temperato resta umido.

### Il render model

`mapservice.read_map` non è un dump della tabella ma ciò che il client disegna: le terre, la
banchisa che forma le calotte polari, un anello di piattaforma continentale attorno a ogni
costa (l'oceano oltre la piattaforma è un guscio liscio lato client, quindi le sue polilinee
sarebbero peso morto) e la rete idrografica già risolta in segmenti. Latitudine e longitudine
non viaggiano: il client le ricava dal vettore centro.

Due scelte lo rendono sostenibile alla dimensione di produzione. I campi sono **colonne** e
non un oggetto per casella: a questa scala i nomi dei campi ripetuti peserebbero più della
geografia. E i vertici dei poligoni sono centroidi di faccia condivisi da tre caselle
ciascuno, quindi vivono in un **pool** unico e la casella ne cita gli indici. Insieme
riducono il payload a un terzo della codifica ingenua.

La risposta è immutabile per costruzione — sostituirla richiede una migrazione, che richiede
un deploy, che riavvia il processo — quindi viene costruita **una volta per processo** e
servita come byte, anche già compressa, con ETag e `Cache-Control: immutable`. Prima di
questa cache ogni richiesta a un endpoint pubblico e non autenticato rifaceva secondi di
lavoro e centinaia di megabyte di liste intermedie. Un limite di richieste per indirizzo fa
da difesa in profondità sulla banda; gli endpoint di salute ne sono esenti, perché un health
check strozzato spegnerebbe il servizio.

Alcune costanti devono combaciare fra i due lati e quindi **viaggiano nei metadati** invece
di essere ricopiate: `elevation_max` e `relief_gain` (la stessa esagerazione del rilievo con
cui il server ha calcolato le normali del terreno) e `river_min_flow`. Una costante ricopiata
a mano è una deriva silenziosa in attesa di accadere.

### Il render

Il terreno è **non illuminato**: l'ombreggiatura del rilievo è calcolata a mano nei colori
dei vertici contro una luce fissa nello spazio del pianeta. Una mappa deve restare leggibile
ovunque, e il modello PBR lasciava metà pianeta al buio. Lo shader aggiunge solo una grana
fine, d'ampiezza scelta per bioma. Gli strati d'acqua si impilano sotto la terra a quota
zero — guscio oceanico, piattaforma, banchisa — e ogni spigolo posseduto da una sola casella
di terra è una linea di costa, da cui scende una parete fino all'acqua.

Ogni casella è un piano alla propria quota, quindi un dislivello fra due vicine lascia una
fessura con dietro soltanto il guscio oceanico: a picco è invisibile, di scorcio — cioè su
quasi tutto il disco del pianeta — la terra si sgrana in esagoni separati con l'azzurro in
mezzo. Anche gli spigoli interni ricevono quindi una parete, dalla casella alta a quella
bassa. Non a tutti: sotto una frazione di casella il gradino non arriva a un pixel nemmeno
al massimo ingrandimento, e la soglia dimezza le pareti da disegnare.

La matematica sta in `app/globe/terrain.ts`: funzioni pure sulle colonne, senza scena e senza
renderer, verificabili senza una GPU. È una separazione voluta, non estetica — il type
checker vede array di numeri e uno screenshot mostra solo il fotogramma che qualcuno ha
guardato, quindi senza test di unità un errore aritmetico qui non ha nulla che lo fermi.

## Il visore della colonia

Top-down 2D, griglia quadrata, tutto disegnato. La profondita' non c'e': **e' tutta
nell'ombra sotto un albero e nell'ordine in cui gli alberi vengono dipinti.** Una sprite piu'
in basso e' piu' vicina, quindi si disegna dopo e copre quella dietro; le ombre cadono tutte
nella stessa direzione. Sono queste due regole, e nient'altro, a far stare in piedi delle
figure piatte.

Il terreno e' un buffer disegnato una volta sola, quindi muovere la mappa e' UNA `drawImage`
invece di sedicimila riempimenti. Le sprite si ridisegnano a ogni fotogramma ma solo quelle
dentro la finestra.

### Quattro cose sbagliate, viste solo a schermo

**Il terreno era un mosaico.** Un buffer da quattro pixel per cella ingrandito a quaranta da
quadrati, e a interpolazione attiva da una sbavatura: entrambe leggono come un diagramma, non
come terra. Ora la grana fine si stende SOPRA, alla risoluzione dello schermo, quindi ha la
stessa nitidezza a ogni ingrandimento.

**Gli alberi erano palline.** Un cerchio e' una palla; cinque lobi scentrati in due toni, piu'
un tronco rastremato sotto, sono una chioma.

**Le rocce erano uova.** Un poligono irregolare con una faccia illuminata e' un masso; un'ellisse
grigia e' un uovo, e un campo di uova identiche e' quello che si vedeva.

**La palette era satura.** Il verde acceso legge come un giocattolo; quello di RimWorld e'
smorto, e smorto e' diventato.

### Due trappole nei percorsi

I percorsi degli asset erano RELATIVI, quindi `colony/manifest.json` chiesto da `/colonia/`
diventava `/colonia/colony/manifest.json`. Il visore del pianeta aveva la stessa forma e
funzionava solo perche' quella pagina sta nella radice -- fortuna, non progetto. Ora sono
tutti radicati.

E il server statico locale non risolveva gli URL puliti: l'export scrive `colonia.html` e il
visitatore chiede `/colonia`. Un host statico vero lo fa da se', il nostro no, e la pagina
dava 404 col file li' accanto.

### Da dove arriva il terreno: dal client

Prima era un file cucinato dal backend e messo accanto alla pagina. Sei mappe, sempre quelle
sei: non si poteva guardare la casella che si stava scegliendo, che e' l'unica cosa per cui
serve guardare. Ora il terreno lo genera IL CLIENT, dal pianeta che ha gia' in mano.

    globo -> "Scendi sul terreno" -> /colonia?tile=N -> il pianeta (file) -> generate(seme, sito)

Niente API, niente asset per colonia, niente nulla di sveglio da nessuna parte: il pianeta e'
gia' un file statico, e la colonia e' una funzione pura di quel file. Il server resta l'autorita'
su tutto cio' che viene DECISO -- atterrare, costruire, votare; questo e' per GUARDARE.

E lo stesso vale per l'API: `GET /cities/{id}/ground` non spedisce piu' le celle. Con la mappa
a 768 erano 9 MB di JSON e quasi tre secondi di CPU dentro una transazione, su un'istanza che
di CPU ne ha un decimo -- centoventi richieste al minuto dallo stesso indirizzo bastavano a
spegnerla. Ora manda il SEME e il sito: chi ha chiesto fa crescere il terreno in quattro
decimi di secondo, piu' in fretta di quanto il server riesca a serializzarlo. Il server tiene
il proprio generatore perche' deve poter dire dove si puo' costruire -- che e' una domanda
piccola su una cella, non un motivo per spedire tutta la mappa.

Il prezzo e' una definizione in due lingue, che di solito e' come si scrive un bug silenzioso:
due generatori che divergono di un valore e il client mostra un posto che sul server non
esiste. Due cose lo impediscono.

**Il generatore e' portabile per costruzione.** Niente `random` di Python, niente Mersenne
Twister da reimplementare in JavaScript: `app/prng.py` e `colony/prng.ts` sono mulberry32 su
interi a 32 bit, con il seme da FNV-1a e le direzioni prese per campionamento sulla sfera --
scelto perche' non usa logaritmi, dove due linguaggi possono differire sull'ultimo bit.

**E l'equivalenza e' un test.** `python -m app.colonyref` scrive `colony/reference.json`
-- cinque siti scelti per i loro RAMI (un fiume, un deserto attraversato da un grande fiume,
una costa con delta, tutto gelato, pietra nuda in quota), 64x64 celle ciascuno -- e
`citygen.test.ts` confronta CELLA PER CELLA terreno, quota, fertilita' e vegetazione.
Cambiare una costante da una parte sola fa cadere la suite: verificato mutando `0,30` in
`0,31` nel solo TypeScript, due test cadono.

Il file contiene anche i SEMI che Python deriva. Il seme e' cio' che le due copie hanno in
comune -- il client lo ricava dal mondo e dalla casella, il server conserva quello che ha
ricavato LUI -- e se divergessero il client disegnerebbe un posto che la mappa autoritativa
non ha, mentre ogni confronto cella per cella continuerebbe a passare. Era verificato solo
contro se' stesso.

## Atterrare: la casella smette di essere scenografia

Il pianeta decide una cosa sola: quale esagono. E' la scala a cui il mondo condiviso viene
deciso, e non e' la scala a cui una colonia si gioca. Atterrare apre una seconda mappa -- un
quadrato di terreno da 768x768 celle -- 590.000 celle, circa SEI chilometri di lato -- che la
casella si porta dietro.

### Sei chilometri, non uno

Un chilometro di lato era il terreno di una scenetta, non di una colonia: ci si costruisce per
mezz'ora e i bordi sono gia' li'. Sei chilometri sono 590.000 celle, trentasei volte l'area di
prima, e il costo si vede in tre punti -- tutti e tre misurati, non stimati.

    generazione            2,5 s in Python (una volta, poi la mappa e' in memoria)
    buffer del terreno     1536x1536 px a 2 px per cella -- 9 MB, dentro il limite di Safari su iPhone
    sprite a schermo       nessuna sotto i 7 px per cella

Il buffer e' sceso da quattro pixel per cella a due: quattro avrebbero voluto 3072x3072, 9,4
megapixel, oltre quello che un telefono alloca. Non si perde nulla, perche' la grana fine si
stende sopra alla risoluzione dello schermo e al buffer resta solo la sfumatura tra due terreni.

E sotto i sette pixel per cella non si disegna piu' niente di eretto: da lontano una finestra
copre centomila celle, e centomila sprite per fotogramma sono una presentazione. La vegetazione
a quella distanza la porta gia' il colore del terreno.

### Si guarda prima di scendere

Il seme di una casella non mescola piu' la colonia che ci arriva: lo decide LA CASELLA. Prima
il dado si tirava nell'istante dell'atterraggio, quindi nessuno poteva sapere su cosa stesse
scendendo finche' non era sceso. Scegliere un sito e poi prenderlo e' un gioco migliore di
prenderlo e poi scoprirlo, e non costa niente: con una colonia per casella non esiste il caso
in cui due colonie vorrebbero terreni diversi dallo stesso posto.

### Casuale una volta, poi per sempre

Una mappa che si rigenera diversa a ogni sguardo non puo' appartenere a un mondo condiviso e
persistente: due giocatori vedrebbero posti diversi e quello che hai costruito ieri sarebbe
altrove oggi. Quindi il dado si tira UNA volta, all'atterraggio, e cio' che si conserva e' il
SEME.

    590.000 celle per colonia, salvate  ->  3 miliardi di righe per il mondo da 5000 giocatori
    il seme che le genera               ->  32 caratteri

La mappa e' una funzione pura del seme e di cosa il pianeta dice del sito, e si rigenera in due
secondi e mezzo in Python -- meno nel browser, che e' dove ora viene generata davvero. Quando le colonie potranno modificare il terreno, le modifiche saranno
righe a parte sopra questa base: come un salvataggio di gioco, che non riscrive il mondo ma
cio' che gli e' stato fatto.

### Il bioma non e' decorazione

Ogni manopola che un sito gira sta in `BIOME_RULES`, come dati: terreno di base, fertilita',
copertura vegetale, asprezza del rilievo, quanto volentieri le conche si riempiono. Piovosita',
temperatura e la quota del pianeta muovono poi quei valori, quindi due deserti non sono lo
stesso deserto. Su tre caselle vere di un pianeta vero:

    palude tropicale, fiume grande, costa    19.180 celle edificabili su 589.824, fertilita' 43
    deserto a 1450 m                        589.287 celle edificabili,            fertilita'  2
    macchia arida sulla costa               393.232 celle edificabili,            fertilita' 20

Spazio o cibo. E' questo che rende la scelta del sito una decisione invece di una formalita'.

### Quattro cose che si sono viste solo guardando le immagini

**Qualunque valore positivo diventava acqua.** La soglia di ristagno era fissa (40 cm), quindi
anche un deserto con piovosita' tre centesimi allagava ogni conca. Ora la soglia e' una frazione
del rilievo della mappa stessa, inversamente alla piovosita'.

**La vicinanza a un'acqua IPOTETICA fertilizzava.** La fascia di riva si calcolava dalla quota
del pelo d'acqua, che esiste anche dove l'acqua non arriva mai: un deserto senza fiume passava
da fertilita' 1 a 20. Ora la fascia la danno solo sorgenti d'acqua vere -- costa e fiume --
piu' le conche, ma solo nei climi che le riempiono davvero.

**La riva di un fiume non e' la sabbia che il fiume attraversa.** Il bonus di riva veniva
dimezzato dal moltiplicatore della sabbia applicato DOPO, proprio dove contava di piu'. Ora la
riva diventa limo: il solo motivo per atterrare in un deserto vale quello che la regola dice.

**La roccia nuda non guardava il bioma.** La soglia era una frazione fissa del rilievo
(`0,62`), quindi OGNI bioma riceveva lo stesso 16,3% di pietra scoperta: una foresta pluviale
con continenti grigi dentro. Cio' che copre la roccia e' la vegetazione, e il bioma dichiara
gia' quanta ne ha, quindi ora e' la copertura ad alzare la linea.

    prima: identico ovunque    dopo: foresta pluviale  3,0%   (copertura 0,95)
                                     foresta temperata 4,3%   (copertura 0,80)
                                     tundra           13,9%   (copertura 0,12)
                                     roccia nuda      98,6%   (copertura 0,02)

A 128 celle era un puntino e non si notava. A 768 era meta' mappa: ingrandire non ha creato il
difetto, lo ha reso impossibile da ignorare.

Nessuna delle quattro si vedeva leggendo il codice, e tutte si sono viste al primo sguardo
alle immagini di `app/cityshots.py` -- che scrive PNG a mano con zlib, perche' un generatore
che non si puo' guardare e' un generatore su cui si sta tirando a indovinare.

### Una casella, una colonia

Un indice parziale lo impone. Con circa 70.000 caselle di terra e cinquemila giocatori previsti
lo spazio abbonda, ma la scarsita' non e' nel numero: e' nella qualita'. Un fiume nel deserto e'
una casella sola. E atterrare e' irreversibile -- un trigger rifiuta di spostare o riseminare
una colonia gia' a terra, cosi' se un giorno esistera' il trasferimento sara' una regola scritta
apposta e non un UPDATE distratto.

## Il terreno entra nell'economia

Fino a ieri atterrare su un delta o su un deserto produceva la STESSA lega: dove scendevi
cambiava la vista e nient'altro, quindi scegliere il sito era una formalita' con un panorama.

### Perche' non bastava un numero

La cosa ovvia era una manopola sola -- la fertilita' alza la produzione -- ed e' stata scartata
misurandola. Con un numero solo esiste un sito migliore in assoluto, e scegliere diventa
cercarlo: una classifica, non una decisione. Peggio, i due candidati ovvi non erano nemmeno in
tensione: la foresta pluviale batte il deserto sia in fertilita' sia in spazio.

### Tre numeri che tirano in direzioni diverse

    cibo     fertilita' della terra EDIFICABILE  ->  alza il tasso di produzione
    legname  verde in piedi, palude esclusa       ->  cio' che lo sgombero restituisce
    pietra   quota di roccia e ghiaia             ->  cio' che c'e' sotto
    fatica   verde da sgomberare PIU' la palude   ->  allunga ogni avanzamento
    spazio   celle edificabili                    ->  quanto cresci prima di stringerti

Legname e fatica sono due numeri e non uno: una palude va prosciugata prima di costruirci --
quindi costa -- ma di legname non ne ha. Sarebbero stati lo stesso numero solo per caso.

E la distribuzione non e' decorazione: e' cio' che fara' servire una colonia a un'altra.

    foresta pluviale   cibo  86   legname  55   pietra   4
    macchia arida      cibo  20   legname   6   pietra  99
    tundra             cibo  41   legname  27   pietra  15
    deserto            cibo   2   legname   0   pietra   0

Nessuno puo' fare tutto in casa.

La resa si misura sulla terra su cui si puo' costruire, non sulla media della mappa: annacquata
dall'acqua, una palude legge come mediocre -- e non e' mediocre, e' ottima terra su cui non ci
sta una citta', che sono due fatti diversi e l'economia li deve tenere separati.

Simulando un anno di tempo di mondo, giocando ovunque allo stesso modo:

    lega accumulata      10 giorni   30 giorni   90 giorni     1 anno
    pluviale                57.511     305.934   1.602.138  13.147.513
    foresta temperata       56.111     298.369   1.565.233  12.853.542
    deserto                 41.284     262.081   1.518.775  13.251.161  <- sorpassa
    tundra                  46.057     258.868   1.418.098  11.964.478
    palude tropicale        31.492     143.591     575.507   3.280.694

**C'e' il sorpasso**, ed e' il punto: a dieci giorni la terra grassa e' avanti del 37%, fra i
novanta giorni e l'anno il deserto la passa. Nessun sito e' la risposta a tutti gli orizzonti,
quindi la domanda «parto forte o cresco per sempre?» ha davvero due risposte.

### Il tetto e' morbido perche' atterrare e' definitivo

Oltre il proprio spazio una colonia non si ferma: ogni livello costa e dura molto di piu'.
Un muro condannerebbe per sempre chi ha scelto un delta, in un mondo dove non si ricomincia.

Per la stessa ragione un sito con ZERO celle edificabili adesso viene rifiutato: una calotta a
3637 metri e' asciutta per quota e ghiacciata da parte a parte, e scenderci significherebbe
non poter costruire mai piu' niente. Terra difficile e' una scelta; nessuna terra e' una
trappola.

### Dove vivono i tre numeri

Sulla riga della citta', scritti UNA volta all'atterraggio. Non possono stare altrove: la
produzione si calcola ogni volta che qualcuno guarda una citta', e una colonia e' 590.000
celle. Sono annullabili, e NULL non e' zero -- zero spazio vorrebbe dire una colonia gia'
stretta prima di essere scesa, mentre una colonia in orbita produce esattamente quello che
produceva prima che il terreno contasse.

Le colonie atterrate sotto il ruleset 1 si riempiono con `python -m app.sitefill`, che le
rigenera dal seme: un riempimento ESATTO e non una stima, che e' precisamente il motivo per
cui il seme era stato salvato.

E il visore li mostra PRIMA dell'atterraggio, perche' e' l'unica cosa che rende la scelta del
sito una scelta. Il gemello TypeScript li calcola e il riferimento li verifica: se le due
copie divergessero, il sito che hai pesato e quello che hai preso non sarebbero lo stesso.

## Il magazzino e il cibo

Quattro risorse invece di una, e due regole nuove che decidono la forma del gioco.

### Il cibo e' il tetto, non il carburante

La terra rende quello che rende -- il cibo NON cresce col livello -- mentre il consumo cresce
con le bocche. Da qui viene il tetto vero di una colonia, e non e' una manopola in piu': e' la
stessa fertilita' gia' misurata che decide un'altra cosa.

    cibo del sito    2  ->  30 milli/s  ->  livello massimo   4     (deserto)
                    41  -> 127 milli/s  ->  livello massimo  16     (tundra)
                    86  -> 240 milli/s  ->  livello massimo  32     (pluviale)

E avanzare oltre cio' che il sito sfama viene **rifiutato**, non permesso e poi punito. Una
colonia cresciuta troppo morirebbe di fame senza ritorno, e atterrare e' definitivo: un
vicolo cieco in piu' non serviva a nessuno. E' lo stesso principio del sito senza celle
edificabili -- terra difficile e' una scelta, nessuna via d'uscita e' una trappola.

Il tetto si calcola sulla politica PIU' SFAVOREVOLE, quindi una maggioranza non puo' affamare
una colonia che aveva fatto i conti giusti: il voto sposta quanto vai forte, non se sopravvivi.

### Magazzino pieno significa fermo

E' la tensione di Anno, scelta consapevolmente. La sua meta' innocua e' che non si perde cio'
che si ha: si smette di guadagnare. La meta' pericolosa e' che questo mondo cammina mentre
dormi, quindi fermarsi a sorpresa sarebbe una punizione per chi ha un lavoro.

Per questo `time_to_full` esiste dal primo giorno: **il momento in cui un magazzino si ferma
si calcola**, quindi si puo' dire prima. Stallo prevedibile e' strategia; stallo a sorpresa e'
una faccenda da sbrigare.

### Niente integratore a eventi, per ora

Una catena con scorte e dipendenze non e' integrabile in forma chiusa: se il minerale e'
finito mercoledi', la fonderia si e' fermata mercoledi', e non lo sai senza ripercorrere la
settimana. Qui pero' ogni tasso e' non negativo -- il cibo lo e' perche' crescere troppo viene
rifiutato -- quindi un magazzino pieno RESTA pieno, e il totale e' ancora

    guadagno = min(tasso x secondi, tetto - scorta)

esatto, applicato dentro ogni periodo di politica invece che alla fine. Il macchinario a
eventi serve quando un processo comincera' a CONSUMARE. Non si costruisce prima di averne
bisogno; `time_to_full` e' gia' il pezzo che servira' allora.

### Cosa costa un livello

Pietra e legname, e i numeri sono scelti perche' i siti si servano a vicenda:

    macchia arida    pietra 0,4h   legname 4,2h
    foresta pluviale pietra 4,2h   legname 0,8h

Sono l'immagine speculare l'una dell'altra. E' li' che nascera' il commercio.

Anche la terra piu' spoglia da' un minimo: un deserto non ha ne' roccia ne' alberi, e senza
quel minimo non potrebbe costruire mai nulla in attesa di un commercio che ancora non esiste.

### La lega non si conia piu'

Tornera' come primo PRODOTTO della prima catena, che e' il posto in cui avrebbe dovuto stare
dall'inizio. Cio' che e' stato guadagnato resta spendibile: le regole cambiano, non si
confisca.

E la politica ora sposta le risorse invece della lega -- senza, il voto, che e' l'unica cosa
condivisa fra tutti i giocatori, sarebbe diventato decorativo.

## La schermata della citta'

E' la prima pagina del visore che NON puo' essere statica, e vale la pena dire perche'.

Il pianeta e' un file e il terreno della colonia e' una funzione di quel file: nessuno dei due
ha bisogno di qualcosa di sveglio. Una CITTA' si': magazzini, livello e cio' che sta facendo
sono DECISI dal server, e calcolarli qui significherebbe inventarli. Quindi questa e' l'unica
parte del visore che dipende da un'istanza in piedi -- di proposito, e solo qui.

    globo e terreno   ->  file statici, niente da svegliare
    la tua colonia    ->  API autenticata, cross-origin per progetto

### Il risveglio non e' un errore

`lib/patience.ts` era stato scritto per il globo e poi tolto quando il globo smise di avere
un server davanti. Torna qui, dov'e' davvero necessario: la pazienza si conta a OROLOGIO,
perche' un'istanza addormentata risponde subito con un 5xx e contare i tentativi brucia un
minuto e mezzo di budget in diciotto secondi.

E un 401 NON si ritenta: un token sbagliato resta sbagliato per quanto si bussi, e novanta
secondi di attesa non direbbero al giocatore nient'altro che "e' rotto".

### Il permesso si da' per nome

Il token viaggia in un header `Authorization`, non in un cookie. Con un permesso aperto il
browser non rifiuterebbe nulla: lascerebbe semplicemente che qualsiasi pagina di internet
spenda un token di cui sia venuta in possesso. E' un difetto peggiore proprio perche'
silenzioso, quindi `ALLOWED_ORIGINS` elenca origini e non contiene mai un asterisco.

### Due domande, e sono aritmetica

La schermata esiste per rispondere a due cose: **quando mi fermo** e **cosa mi manca**. Sono
calcoli, e un calcolo sbagliato dentro un componente non si vede -- si legge come un numero
plausibile. Quindi stanno in `city/format.ts`, fuori dal disegno e sotto test.

    Cibo     105    pieno fra 26 h
    Legname   40    pieno fra 5 giorni
    Pietra    40    pieno fra 5 giorni

Il primo numero e' cio' che hai; il secondo e' la meta' che rende accettabile lo stallo in un
mondo che cammina mentre dormi.

### Una cosa trovata guardandola

La pagina e' pre-renderizzata a build time, dove non esistono ne' `localStorage` ne'
l'indirizzo del server. Decidere cosa mostrare prima di essere nel browser significa
disegnare una cosa e poi un'altra: React lo chiama disallineamento di idratazione e si vedeva
come un errore in console a ogni caricamento. Ora il primo disegno e' vuoto di proposito.

## Le catene: la produzione smette di essere una moltiplicazione

Una fonderia consuma minerale e legname e rende lega. Tre conseguenze, e nessuna e' cosmetica.

### Il minerale e' un asse nuovo, non la pietra riscritta

I filoni hanno un campo di rumore tutto loro, e la soglia la abbassa la QUOTA: la roccia
profonda viene a giorno dove la crosta e' stata spinta su. Se avessero seguito la pietra di
superficie non avrebbero aggiunto nessuna geografia -- una macchia arida sarebbe stata ricca
due volte e la scelta del sito piu' povera, non piu' ricca.

    pluviale in pianura    minerale  7      macchia arida in piano   minerale  8
    pluviale a 1800 m      minerale 16      macchia arida a 2200 m   minerale 22

E i numeri dicono la cosa che conta: **nessuno regge una fonderia con cio' che ha sotto i
piedi.** La montagna arida ha il minerale e non il legno, la giungla il contrario.

    pluviale a 1800 m    regge 1,20 fonderie
    pluviale in pianura  regge 0,90      (manca il minerale)
    macchia arida        regge 0,50      (manca il legname)

E' da qui che nascera' il commercio, e non e' un auspicio: e' il rapporto fra due numeri
misurati.

### L'integrazione a eventi, adesso che serve

Finche' le risorse salivano soltanto, liquidare era una moltiplicazione. Un processo che
CONSUMA la rompe: se il minerale e' finito mercoledi', la fonderia si e' fermata mercoledi' e
il tasso di giovedi' non e' quello di martedi'.

Quindi fra un evento e l'altro tutto e' lineare, e il momento in cui una scorta tocca lo zero
o il tetto si CALCOLA invece di aspettarlo: si salta li', si ricalcolano i tassi, si prosegue.

    dieci anni di assenza  ->  liquidati in 0,15 ms

Nessun tick e' tornato dalla finestra. E l'invariante che aveva permesso di toglierlo regge
ancora: **spezzare un intervallo non cambia il risultato**, al milli, verificato liquidando
due giorni in un colpo e poi ora per ora.

Un'opera tira dal magazzino finche' ce n'e' -- puo' girare a pieno anche consumando piu' di
quanto arrivi, sta svuotando un buffer -- e quando il buffer e' a zero gira al ritmo con cui
l'ingresso arriva. I millesimi tengono tutto intero, perche' un mondo salvato deve riprodursi
identico.

### La lega ha uno sbocco, o sarebbe un numero che nessuno spende

Dal livello tre in su un avanzamento vuole anche lega, che non si raccoglie: si fonde. Senza,
la catena avrebbe prodotto lo stesso difetto che il cibo ha oggi -- una scorta che sale e
resta li' -- ma voluto invece che ereditato.

### Tre difetti che solo il costruirla ha fatto uscire

**Il minerale non era ammesso nel ledger.** La migrazione precedente aveva fissato l'elenco
delle risorse; aggiungerne una alle regole e alla riga della citta' senza estenderlo
significava poterla produrre e non poterla scrivere. Non si vedeva finche' qualcuno non
estraeva il primo grammo. Ora un test confronta i due elenchi invece di sperare.

**La produzione non poteva essere negativa.** Il vincolo diceva: genesis e production
aggiungono, upgrade toglie. Vero finche' nulla consumava. Una colonia che fonde piu' minerale
di quanto ne scavi ha, a fine intervallo, meno minerale di prima -- e quel movimento e'
esattamente cio' che il ledger deve registrare.

**La previsione guardava il raccolto.** La lega non si raccoglie, quindi la schermata diceva
"fermo" di una risorsa che stava crescendo. Ora guarda i flussi netti -- e "gia' pieno" e
"non si fermera' mai" sono tornati due stati distinti, che sembravano uguali e non lo sono.

## L'energia: un flusso, non una scorta

Quattro fonti -- eolico, solare, idroelettrico, geotermico -- e una regola che decide tutto il
resto: **l'energia non si mette in magazzino.**

Se si potesse accumulare, una colonia ne banchereb­be di notte e il vincolo sparirebbe: si
tornerebbe a "abbastanza, prima o poi", che non e' una decisione. Come FLUSSO invece e'
esattamente il caso che lo strozzatore gia' sapeva trattare -- un ingresso senza buffer -- e
non e' servita nessuna macchina nuova, solo un limite in piu' nella stessa funzione.

    Corrente: 46 prodotta - 14 pretesa - tutto a pieno regime
    Corrente:  0 prodotta - 14 pretesa - non basta, tutto gira al 0%

E quando non basta, TUTTI gli impianti rallentano insieme: non se ne sceglie uno da spegnere,
perche' quella scelta e' del giocatore e si fa con la pausa.

### Il deserto smette di essere uno scarto

E' la ragione vera per cui l'energia entra adesso. Il deserto era il sito povero di tutto --
niente roccia, niente alberi, quasi niente cibo -- e il sole lo riscatta senza che nessuna
regola debba fare un'eccezione per lui.

    deserto              sole 100   vento 28   acqua  0   calore 17
    pluviale con fiume   sole  21   vento 26   acqua 88   calore  9
    macchia arida 2200   sole  82   vento 96   acqua  0   calore 25
    tundra costiera      sole  72   vento 60   acqua  0   calore 15

Tre delle quattro attitudini si leggono da cio' che il pianeta gia' diceva -- quota, coste,
piovosita', temperatura, portata del fiume. Il CALORE no: e' geologia nascosta, come i filoni,
e ha un campo di rumore suo, piu' largo perche' un'anomalia termica e' una regione mentre un
giacimento e' una vena.

Lo stesso impianto e' una centrale diversa a seconda di dove sta, e la schermata lo dice:
"Idroelettrico -- 0 corrente/s qui (attitudine 0)" su una casella senza fiume.

## Rendere gestibile cio' che era una condanna

Il gradino precedente aveva lasciato un difetto grave, trovato provandolo e non leggendolo:
**un'opera non si poteva spegnere.** Una fonderia mangiava il legname per sempre, e siccome il
legname serve anche a costruire, un solo impianto poteva bloccare la crescita di una colonia
senza che il giocatore potesse farci niente.

    Pausa     istantaneo  -- un impianto spento non consuma, non produce, non chiede corrente
    Accendi   istantaneo  -- e' un interruttore, non un lavoro
    Abbatti   istantaneo  -- senza rimborso, e si abbatte per prima una gia' spenta

Costruire occupa la colonia -- una cosa alla volta, com'e' sempre stato -- ma accendere e
spegnere no: sarebbe stato punire il giocatore per aver cambiato idea.

### Due elenchi che devono coincidere, e non coincidevano

Lo stesso difetto del minerale nel ledger, in un altro punto: gli impianti nuovi erano nelle
regole e nel database, e l'API li rifiutava perche' lassu' l'elenco era ancora di uno solo --
"Input should be 'smelter'". Adesso il modello della richiesta e' legato a `WORK_KINDS`, e un
test prova a costruire OGNI tipo che le regole conoscono.

E' la terza volta in questo progetto che due elenchi si separano in silenzio. Il rimedio che
funziona non e' ricordarsene: e' un test che li confronta.

### E il riferimento stesso si era separato

La quarta volta, ed e' la peggiore, perche' e' successa AL GUARDIANO. Le quattro attitudini
energetiche sono state aggiunte a Python, e `colonyref.py` ha continuato a scriverne sei --
perche' elencava i campi a mano. Cosi' le due lingue sono divergute mentre il test che esiste
esattamente per accorgersene passava, confrontando due copie vecchie.

Adesso il riferimento scrive `asdict(made.economy)`: aggiungere un campo di qua ROMPE subito
il test di la', che e' il suo mestiere. Un elenco scritto a mano si dimentica; una struttura
no.

## Via il tick: il mondo e' continuo

Il tick era il momento in cui le cose accadevano: gli ordini si accodavano a mezzanotte, ogni
citta' veniva liquidata al confine, e la politica si eleggeva li'. Non c'e' piu'. La produzione
matura dai timestamp, un impegno si completa nell'istante in cui scade, e una citta' viene
portata al presente quando qualcuno la guarda -- sotto un lock sulla SUA riga soltanto.

    decideva quando un ordine si risolve   ->  un ordine occupa tempo e si completa da se'
    UNIQUE(city_id, target_tick, kind)     ->  indice parziale: una cosa in corso per citta'
    elezione a maggioranza al confine      ->  voto permanente, maggioranza continua
    tabella ticks (ruleset, riassunto)     ->  il ledger, riga per riga
    barriera globale world FOR UPDATE      ->  SPARITA. Era il muro di scala dichiarato.
    require_current                        ->  SPARITO: non c'e' piu' niente su cui essere in arretrato.

### Il freno

L'unico limite alla velocita' d'azione era quel vincolo di unicita' per tick. Toglierlo e
basta avrebbe reso il gioco piu' degenere, non meno: con la lega che si accumula, una sola
richiesta avrebbe portato una citta' su di centinaia di livelli.

Il freno di un mondo continuo non e' una quota artificiale, e' che **le azioni occupano
tempo**. L'impegno paga subito e una citta' ne regge uno solo: scegliere di iniziare qualcosa
e' scegliere di non iniziare nient'altro finche' non finisce. La decisione smette di essere
"quando premere" e diventa "a cosa impegnarsi adesso". Costo e durata crescono entrambi col
livello, perche' contro una produzione che compone un costo fisso non e' un costo.

### La politica e' una linea del tempo, ed e' la parte che costa

`production_amount` prende una politica per intervallo, e finora era il tick a garantirlo:
ogni citta' liquidata al confine con la politica uscente, prima che la nuova entrasse -- "un
giorno di produzione non e' mai pagato a una tariffa che quel giorno non aveva". Senza tick,
una politica che cambia a meta' intervallo pagherebbe retroattivamente tutto l'intervallo alla
tariffa nuova.

Si poteva risolvere liquidando TUTTE le citta' al momento del cambio: sarebbe stata di nuovo
una barriera globale, piu' rara ma la stessa cosa, e con migliaia di citta' uno stallo di
secondi. Quindi la politica e' un registro di periodi e la produzione si integra su quelli che
l'intervallo attraversa. Ogni citta' calcola la propria storia da sola, quando qualcuno la
guarda, e nessuno blocca nessun altro. Un intervallo che nessun periodo copre viene RIFIUTATO,
non pagato come zero: un buco nella linea del tempo e' un difetto, non lega gratis.

Due invarianti che sembrano dettagli e non lo sono. I confini dei periodi sono a secondi
interi, perche' il cursore di una citta' e' troncato al secondo e un confine con i microsecondi
cade dopo un cursore che dovrebbe coprire -- costato un test verde che non lo era. E un periodo
di durata zero non e' un periodo: due cambi nello stesso secondo correggono quello in corso
invece di aprirne un altro.

### Cosa e' stato tolto e non rimpianto

Il ritmo variabile del worker, aggiunto lo stesso giorno. Difendeva da `require_current`, che
rifiutava ogni operazione economica mentre il mondo era in arretrato; senza tick non c'e'
arretrato, quindi non c'e' niente da cui difendersi. Il worker ora e' uno SPAZZINO: nessuna
citta' ha bisogno di lui per essere corretta -- lo e' nel momento in cui viene letta -- ma in
un mondo condiviso e' bene che una citta' finita smetta di dirsi occupata anche mentre il suo
proprietario dorme.

E l'orologio aveva due riferimenti indipendenti, uno per modulo, legati all'import. Era un
giunto solo nelle intenzioni: bastava che un modulo guardasse l'ora per conto suo perche' una
prova a tempo congelato usasse in silenzio il tempo vero. Ora passano tutti da `db`.

## L'orologio del mondo

Un tick al giorno rende il gioco improvabile: una mossa si valuta dopo ventiquattr'ore.
Finche' il mondo e' in lavorazione, quella non e' una regola -- e' l'impossibilita' di capire
cosa manca.

**Accorciare il tick non serve a niente.** La produzione non la fa il tick: `POLICY_RATES` e'
in milli-lega al SECONDO e `settle_city` la ricava dalla differenza fra due timestamp; il tick
porta avanti il cursore fino al confine, e basta. Portare `TICK_INTERVAL` da un giorno a dieci
secondi darebbe 8640 cerimonie al giorno con dentro un diecimillesimo ciascuna, e il gioco
andrebbe esattamente alla stessa velocita'. Ad andare compresso e' l'orologio che la
simulazione LEGGE.

    tempo_del_mondo = ancora_mondo + (tempo_reale - ancora_reale) * velocita'

Due ancore e non una, perche' cambiare velocita' deve lasciare il tempo CONTINUO: toccare la
sola velocita' farebbe saltare il mondo avanti o indietro di giorni, e all'indietro significa
produzione negativa e un ledger che non torna. Chi cambia velocita' rimette prima l'ancora
sull'istante corrente, calcolandola con la velocita' VECCHIA -- da cui le due formule si
incontrano nel punto del cambio.

E con le ancore sullo stesso istante e velocita' 1 la formula si riduce a `tempo_reale`
**esattamente**: la sottrazione e la somma si annullano. E' la proprieta' che rende sicuro
spedire tutto questo dentro un mondo che deve girare a un secondo al secondo -- resta inerte
finche' nessuno gira la manopola.

Il giunto e' uno solo, `db.database_now`. Restano al tempo reale, di proposito, le colonne di
audit (`recorded_at`, `completed_at`, `generated_at`): dicono quando un fatto e' stato
SCRITTO, non quando VALE nel mondo, ed e' la stessa distinzione che c'era gia' fra
`effective_at` e `recorded_at`.

### Il difetto che si e' visto solo giocando

Il worker dormiva cinque secondi fissi fra un giro e l'altro. A un giorno al giorno la
finestra fra mezzanotte e il worker che se ne accorge e' un battito di ciglia e non la
incontra nessuno. A 43200x un giorno di mondo passa in due secondi, quindi quella stessa
pausa lascia il mondo "in arretrato" quasi sempre -- e `require_current` rifiuta OGNI
operazione economica mentre lo e'. Il mondo compresso era inutilizzabile: ogni ordine
rispondeva 503.

Ora la pausa e' proporzionale alla velocita' del mondo (quattro sguardi per giorno di mondo,
con un pavimento che evita il ciclo stretto). A velocita' 1 restituisce gli stessi cinque
secondi di prima.

Non c'era modo di trovarlo leggendo il codice: e' saltato fuori al primo tentativo di fondare
una citta' in un mondo veloce.

## Il pianeta e' un file

Il visore chiedeva all'API due cose sole: la mappa, immutabile e generata una volta, e una
pillola di stato che era decorazione. Citta', ordini e ledger vogliono un token e la pagina
pubblica non li ha mai toccati. Quindi tutto il capitolo qui sotto -- risvegli, 502, 429, ore
di istanza, pazienza a orologio -- serviva a consegnare **quattro megabyte che non cambiano
mai**.

E non bastava nemmeno: un'istanza free che smette di risvegliarsi su richiesta e' un difetto
noto di Render, e nessuna quantita' di pazienza nel client lo aggira. L'API, in una giornata,
non si e' svegliata dal traffico neanche una volta: ogni volta che e' ripartita l'aveva accesa
un deploy.

Ora la mappa e' un asset statico. Non puo' essere irraggiungibile, non puo' essere lenta a
svegliarsi, non consuma ore-istanza e non costa niente da servire. E' anche la forma che vuole
il gioco scaricabile: un client il mondo se lo porta come dato, non lo chiede alla rete.

    manifest.json   poche centinaia di byte, sempre riletto: dice come si chiama il pianeta
    planet-<hash>   4,0 MB gzippati, il nome porta l'impronta del contenuto

Il nome col digest e' quello che fa sparire la questione della cache invece di gestirla: il
payload si puo' tenere per sempre e un mondo nuovo ha semplicemente un nome nuovo. Il file
NON si chiama `.gz` di proposito -- un host statico metterebbe `Content-Encoding: gzip` per
indovinello, il browser lo scompatterebbe di nascosto e il client fallirebbe su byte gia'
spacchettati. Uno solo scompatta.

DUE STRADE PER UN MODELLO SOLO. `mapservice.read_map` raggiunge il sottoinsieme disegnato con
SQL, di proposito: alla dimensione di produzione il planner va guidato, e c'e' un commento
lungo che lo spiega. Quella strada vuole un database col mondo dentro. `mapexport` ha solo un
seme, quindi lo raggiunge in Python. Due strade per una risposta sola e' esattamente come
questo progetto si e' gia' fatto male -- il campo continentale era scritto due volte, identico,
finche' le due copie non hanno smesso di concordare. La differenza e' che stavolta l'accordo
e' un test: si genera un mondo, lo si salva, e i due modelli devono venire **identici**, come
dati e come byte.

Il test sui byte ha ripagato subito. I due modelli erano uguali come dati e diversi come
byte: arrotondare una coordinata negativa minuscola da' `-0.0`, che confronta uguale a `0.0`
e quindi non lo nota nessuno, ma si serializza `"-0.0"` mentre PostgreSQL lo restituisce
`0.0`. Dieci in un mondo da 1442 caselle. E i corner sono messi in comune per valore esatto,
quindi le due strade avrebbero anche potuto raggrupparli diversamente.

Cosa resta all'API: tutto il gioco. Citta', ordini, ledger, tick. La geografia se n'e'
semplicemente andata per conto suo.

## Aspettare un'istanza che dorme

Sul piano gratuito di Render un servizio inattivo si spegne dopo quindici minuti e ci mette
quasi un minuto a tornare. Non e' un guasto, e' il piano: va aspettato. Il punto e' *come* si
conta l'attesa.

La prima versione la contava in **tentativi**, e dimensionava la pazienza con un timeout per
tentativo: quattro colpi da venticinque secondi, cioe' -- diceva il commento -- un minuto e
mezzo. Quel ragionamento regge solo se un tentativo fallito e' un tentativo *lento*. Non lo
e'. Davanti a un servizio addormentato il router di Render risponde 5xx **subito**, quindi
ogni colpo costava due secondi invece di venticinque e i quattro colpi finivano in diciotto
secondi. Il timeout non entrava mai in gioco, perche' morde solo una richiesta che resta
appesa. Lo stesso errore, identico, stava anche nel client: tre tentativi con un timeout da
due minuti diventavano sette secondi di pazienza reale.

    pazienza dichiarata      pazienza reale     risveglio necessario
    proxy   90 s                  18 s
    client  360 s                  7 s
    ---------------------------------------------------------------
    totale                    circa 45 s              circa 50 s

Quarantacinque contro cinquanta. Il sito diceva "server non raggiungibile" a un server che
stava benissimo e sarebbe arrivato cinque secondi dopo, e il pulsante "Riprova" ricominciava
una corsa persa in partenza. Da fuori era indistinguibile da un guasto vero.

Ora la pazienza e' **a orologio** (`app/lib/patience.ts`): per quanto in fretta l'altro capo
dica di no, si continua a bussare finche' il tempo promesso non e' passato davvero. Il
divario fra un colpo e l'altro cresce fino a un tetto, cosi' un'attesa lunga non e' anche un
martellamento. Il budget del proxy sta sotto il limite di cento secondi che Render impone
alle proprie richieste: aspettare piu' della piattaforma significa solo farsi tagliare a
meta' attesa e riportare il guasto che si stava cercando di evitare.

Secondo difetto, ed e' quello che ha reso la diagnosi lunga: **una risposta ne' 200 ne' 404
non veniva registrata affatto.** Il log stava solo nel ramo `catch`, e il `fetch` non
sollevava mai eccezione -- riceveva 5xx regolarissimi. Nei log restava quindi il solo
"giving up", che e' esattamente l'informazione inutile: dice che abbiamo rinunciato, non
perche'. Un'API irraggiungibile e una semplicemente lenta lasciavano tracce identiche. Ora
ogni stato inatteso viene scritto.

Della stessa famiglia, e scoperto lo stesso giorno: il processo che costruisce il pianeta
aveva `stdout` e `stderr` su `DEVNULL`. Alla domanda "il mondo e' stato generato?" i log
sapevano rispondere solo che un processo era stato avviato, e la risposta e' dovuta arrivare
riavviando il servizio per sentirgli dire `map already present`. A staccare il figlio serve
`start_new_session`; ammutolirlo non era parte del lavoro.

La morale comune ai tre: **un limite va espresso nell'unita' in cui verra' speso.** Una
pazienza misurata in tentativi non dice niente su quanto si aspettera', perche' il costo di
un tentativo lo decide l'altro capo, non noi.

Resta vero che tutto questo aspetta un risveglio, non lo elimina: la prima apertura della
giornata costa circa un minuto. Toglierlo davvero vuol dire il piano a pagamento. Tenere
sveglio il servizio con ping periodici *non* e' un'alternativa: le ore-istanza gratuite sono
750 al mese per workspace e due servizi sempre accesi ne consumano circa 1440.

## Limiti deliberati

Le operazioni economiche non prendono più un lock globale esclusivo: usano `world FOR
SHARE` e serializzano per città, quindi giocatori diversi procedono in parallelo. Resta un
limite deliberato la barriera globale del tick (`world FOR UPDATE`): privilegia correttezza
e auditabilità e liquida tutte le città in un'unica transazione, quindi il tick e la
liquidazione di massa richiederanno partizionamento e snapshot riconciliabili prima di una
scala molto elevata. Il cursore `balance_milli`
(migrazione 0002) rimuove il costo O(n) del saldo su lettura e scrittura ed è coperto da
test di equivalenza col ledger; ogni ulteriore cache economica deve mantenere la stessa
verifica. Nessun requisito di alta disponibilità è ancora implementato. Compose è per
sviluppo locale; non include TLS né gestione account pubblica. `scripts/backup.sh` e
`scripts/restore.sh` producono e ricaricano dump verificati (il restore rifiuta un mondo
in cui il saldo materializzato diverge dal ledger). I token si provisionano con CLI e non
vengono salvati nel frontend.

Sulla geografia i limiti sono altrettanto espliciti. La misura che conta per il giocatore non è quanta terra c'è ma quanta se ne può usare: acqua
ferma, ghiaccio permanente e roccia nuda non sono terra su cui si fonda qualcosa. Al 73esimo
percentile il 27% della sfera è emerso e il 21,6% è utilizzabile — cioè l'80% delle terre. È
il numero contro cui va letta ogni decisione sulla dimensione del mondo, e per questo è una
metrica e non un calcolo a mano.

La generazione costruisce l'intera
sfera in memoria in una volta: è il picco di memoria, non il tempo, a fissare il tetto della
frequenza, e su un'istanza piccola quel tetto è vicino.

La scala del rilievo normalizza sul massimo reale del campo, non su una costante. Prima lo
faceva su un massimo fissato a 1.0, dando per scontato che la somma di tutti i contributi
avesse quel picco; non l'aveva, e ogni termine aggiunto al campo gonfiava le altezze di tutto
il pianeta. Il difetto è emerso solo quando metà delle terre emerse è diventata roccia e neve:
era latente da tre versioni del generatore. Ogni contributo nuovo va aggiunto sapendo che la
normalizzazione lo assorbe.

**La divisione in continenti non è garantita dall'algoritmo, ed è il seed a deciderla molto
più di qualsiasi parametro.** Misurato su quattordici seed alla stessa identica
configurazione, la massa maggiore va dal **26%** (`Orion-01`) all'**82%** (`Cassia-01`) delle
terre emerse, e la terra utilizzabile dal 10% al 22%. Lo stesso generatore, le stesse
costanti: cambia solo da dove parte il rumore. Il mondo spedito, `Erebo-01`, sta all'estremo
frammentato — 15 continenti, 62 masse, la maggiore al 28% — ed è stato **scelto guardando i
candidati renderizzati**, non calcolato. I bacini oceanici rendono la divisione probabile,
non certa. Un
generatore che la garantisse dovrebbe partire da una struttura esplicita — placche tettoniche
come celle di Voronoi sulla sfera, con i bordi affondati — invece che da un campo di rumore
sperando che tagli nel punto giusto. Finché il mondo è uno solo e il suo seed è fissato la
differenza non si vede; diventerebbe un problema il giorno in cui i mondi fossero generati
su richiesta, perché a quel punto un giocatore su tre si ritroverebbe un supercontinente.

### Dove sta la terra

Tre decisioni separate, che si sono rivelate legate.

**Quanta.** `SEA_PERCENTILE` è un percentile, quindi decide la frazione di terra qualunque
cosa faccia il resto del campo: 0,69 significa 31% di terre emerse, punto.

**Dove non sta.** `_polar_pull` toglie quota al campo continentale fra 51 e 82 gradi, su uno
smoothstep perché la costa si assottigli invece di finire su una riga dritta. Nessuna terra
oltre il circolo polare, massimo 65 gradi. Non dice nulla sul clima — la temperatura ha già
il suo profilo di latitudine; dice dove sta la terra, non quanto fa freddo.

**Come è connessa — e qui sta la trappola.** Abbassare il livello del mare per avere più
terra **salda i continenti**: la massa maggiore era passata dal 28% al 58% e il mondo era
diventato un blocco unico. I bacini oceanici (`RIFT_STRENGTH`) sono l'unico meccanismo che
decide cosa resta attaccato a cosa, quindi vanno alzati insieme al livello del mare per
ritagliare ciò che l'acqua non copre più. **Le due manopole non sono indipendenti e girarne
una sola dà un pianeta diverso da quello che si voleva.**

### Le isole arrivavano a collane di perline

Gli archi di isole ponevano i loro elementi a `index/(n-1)`: spaziatura *esattamente*
uniforme, con un sussulto solo perpendicolare di mezzo grado contro archi venti volte più
lunghi. Con dieci archi passava per catena; a cinquantaquattro il pianeta era infilzato di
linee punteggiate dritte. È la stessa famiglia di difetti delle coste a fasce: **una
regolarità che nessuno aveva scelto, invisibile finché il campione era piccolo.** Ora la
posizione lungo l'arco è sparpagliata fino a mezzo passo, la deriva laterale è in proporzione
all'arco, e ogni arco ha da tre a sette isole.

### Quanto può essere grande il pianeta

L'intera sfera viene costruita in memoria in una volta sola, quindi il picco cresce
linearmente a circa **1,55 kB per casella**, e il tetto non lo decide il gusto ma l'istanza
da 512 MB del piano free. Misurato sul seed spedito, sola generazione:

| caselle | tempo | picco RAM |
|---|---|---|
| 193.212 | 9 s | 303 MB |
| **231.042** | **11 s** | **358 MB** ← quella spedita |
| 256.002 | 10 s | 395 MB — il massimo che il free regge |
| 400.002 | 18 s | 609 MB — già oltre l'istanza |
| 1.936.002 | 92 s | 2.898 MB — il «per dieci»: sei volte l'istanza |

Dietro quel muro ce ne sono altri tre, e **pagare un'istanza più grande non ne abbatte
nessuno da solo**: il database free tiene 1 GB e un mondo per dieci sarebbe ~950 MB di sole
caselle; il payload della mappa passerebbe da 10,6 a ~105 MB; e il client dovrebbe passare
alla GPU mezzo gigabyte di geometria, cosa che nessun telefono fa. Un mondo davvero grande si
serve **per regioni inquadrate** invece che intero, con livelli di dettaglio: è
un'architettura, non una costante da alzare. Il payload e il tempo di costruzione
lato client crescono linearmente con le caselle, quindi ogni aumento della tassellatura è un
compromesso con il primo caricamento, soprattutto su mobile. La mappa non ha ancora alcun
legame con le città: quando esisterà, una migrazione che azzera le caselle non sarà più
un'operazione innocua e andrà ripensata.

## Lo schermo di gioco

Fino a qui il visore era fatto di PAGINE: il globo, il terreno, la citta'. Tre documenti con
un titolo e dei paragrafi, buoni per leggere e sbagliati per giocare. Un gioco non si legge:
si sta dentro. Quindi `/colonia` non e' piu' una pagina con una mappa dentro, e' uno schermo
-- il terreno occupa tutta la finestra e l'interfaccia ci galleggia sopra.

    barra in alto    risorse, corrente, ora del mondo, livello, menu
    angolo in basso  minimappa, e i tre modi di uscire da qui
    pannello destro  i comandi, aperti solo quando servono
    sotto a tutto    il terreno, che non perde mai spazio

La regola che tiene insieme il disegno e' una sola: **niente ruba spazio alla mappa in modo
permanente**. La barra e' alta due righe, il pannello si apre e si chiude, la minimappa sta in
un angolo. Un pannello che occupa sempre un terzo dello schermo e' un pannello che il
giocatore tiene chiuso, e allora tanto valeva non farlo.

### Il terreno copre, non si inquadra

La prima versione teneva la colonia intera dentro il lato corto della finestra, e su uno
schermo largo lasciava due bande nere ai fianchi. Corretto per un visore di mappe, sbagliato
per un gioco: adesso l'ingrandimento minimo e' quello che COPRE la finestra. Vedere tutta la
colonia in un colpo solo non e' piu' un compito della tela, e' il mestiere della minimappa.

### La minimappa disegna il terreno vero

Non e' un'immagine a parte: campiona la stessa funzione che disegna la tela grande, con lo
stesso colore per cella, e se la ridisegnasse ad ogni movimento della telecamera costerebbe
quanto la tela. Quindi il terreno finisce UNA volta in un buffer e resta li'; sopra ci va solo
il rettangolo dell'inquadratura, che e' quattro numeri. Il rettangolo sparisce quando coincide
con tutta la mappa, perche' un bordo che ripete il bordo non dice niente.

Un clic sulla minimappa sposta la telecamera. E' l'unico punto in cui un pezzo di interfaccia
comanda la tela, e passa per una funzione sola (`goTo`) invece che per lo stato di React: una
panoramica non deve attraversare un ciclo di rendering.

### I comandi hanno DUE case, e una sola definizione

La stessa fonderia si costruisce dalla pagina `/citta` e dal pannello dentro il gioco. Farne
due copie sarebbe stato il quinto caso di "due elenchi che devono coincidere" di questo
progetto -- il primo che si fosse aggiornato avrebbe lasciato l'altro a mentire al giocatore.
Quindi i comandi stanno in `city/CityPanel.tsx`, e le due schermate lo OSPITANO.

Il prezzo e' che un componente deve stare bene in due larghezze molto diverse. Dentro il
pannello da 30rem la tabella degli impianti smette di essere una tabella: ogni impianto
diventa un blocco col nome sopra e i comandi sotto. Ed e' per la stessa ragione che il costo
di costruzione e' uscito dal bottone -- "Costruisci (pietra 120.000, legname 120.000 -- 3.0 h)"
andava a capo tre volte -- per finire sotto la ricetta, dove serve leggerlo prima di premere.

La stessa trappola era gia' scattata in piccolo: la pastiglia della barra aveva la SUA copia
della regola a tre stati -- "pieno", "fermo", il tempo che manca -- scritta dentro il disegno.
Adesso e' `stallShort` accanto a `stallNote`, nello stesso file e sotto lo stesso test: due
frasi diverse, una regola sola.

### Cosa NON c'e' ancora

Le impostazioni sono l'indirizzo del server e poco altro, perche' non c'e' ancora niente da
impostare: nessun suono, nessuna velocita' da regolare in un mondo che cammina da solo,
nessuna scorciatoia. Il menu esiste comunque, perche' e' il posto dove quelle cose andranno e
inventarlo dopo significa rifare il disegno.

## La luce, che non c'era

Il terreno della colonia era dipinto piatto: un colore per cella, e sopra un velo di puntini
bianchi a schermo. Il generatore pero' scriveva gia' l'ALTEZZA di ogni cella, in metri, e non
la guardava nessuno -- una collina e una piana uscivano dello stesso identico colore. Il
difetto non si vedeva come un difetto: si vedeva come uno stile.

    prima     un colore per cella, puntinio bianco, confini a mezzatinta
    adesso    pendenza, conche, acqua che si fa fonda, rive, macchie nel terreno

### Il piano vale esattamente uno

La regola che tiene insieme tutto il modello: su terreno piatto la luce vale **1.0**, cioe' il
colore della tavolozza esce com'e' stato scelto. La luce aggiunge solo cio' che il terreno fa
davvero. Senza quel vincolo ogni ritocco alla tavolozza sarebbe stato una trattativa con
l'illuminazione, e si sarebbe finiti a scegliere i colori guardando il risultato invece che il
posto.

E la scala della pendenza la decide il SITO, non una costante: si misura la pendenza tipica
della colonia e si tara su quella. Un deserto piatto e una valle alpina hanno lo stesso
diritto di vedersi; con una scala assoluta uno sarebbe stato carta bianca e l'altro carbone.

### L'ombra e' azzurra

L'ombra non e' nero, e' il cielo che ci arriva dentro. Quindi la luce non ha solo una
quantita' ma un colore: caldo dove batte, azzurro dove non arriva. E' una riga di codice ed e'
meta' della differenza fra un terreno e un disegno sfumato col grigio.

### Tre cose trovate solo guardandole

**Le curve di livello stampate sulla sabbia.** Le altezze sono interi di metri e le celle sono
larghe otto: un gradino di un metro vale 0,125 di pendenza, che in una piana e' PIU' della
pendenza vera. Derivare quella scala a gradini dava terrazze, e le terrazze si leggevano come
un'impronta digitale su tutta la piana. Sette celle di media prima di derivare -- una
cinquantina di metri -- sciolgono il gradino e non toccano un rilievo largo centinaia.

**La nuvola bianca appoggiata sul bosco.** Con un tetto di luce alto, una rupe grigio chiaro
arrivava a centosettanta di grigio piu' la tinta calda: in mezzo a una foresta verde scura si
leggeva come una nuvola, non come una rupe. Estremi piu' stretti, roccia piu' scura, e una
grana per materiale -- la roccia e' mossa, la sabbia no.

**La costa tirata col righello.** Era una diagonale netta attraverso la mappa: a sei
chilometri non si legge come una costa, si legge come la sponda di un canale. Adesso serpeggia
con un campo di rumore suo, come il fiume ha sempre fatto. E' un cambio al GENERATORE, quindi
in tutte e due le lingue, con il riferimento rigenerato e il test di equivalenza a controllare
che le due copie siano ancora la stessa cosa.

### Un bosco non e' un prato scuro

Il verde era uno solo, piu' o meno carico: la differenza fra prato e foresta era solo di
luminosita', ed e' per questo che un bosco sembrava un prato scuro. Adesso sono due fermate,
prato e bosco, e la terra povera fa foglie gialle invece che foglie scure -- che e' la
differenza fra una macchia mediterranea e una foresta.

Le piante, poi, erano lo stesso cespuglio timbrato cento volte su una griglia uniforme. Tre
tiri di dado indipendenti invece di uno riciclato (taglia, inclinazione, colore), il numero
dei lobi che cambia, e la densita' moltiplicata per un campo di macchie: e' quello che apre le
radure. Ogni pianta prende la luce della cella su cui sta, se no un bosco in ombra restava
verde acceso e sembrava incollato sopra il terreno.

### La grana e' una cosa da vicino

Il puntinio stava a risoluzione di SCHERMO, quindi a tutta mappa erano seicentomila celle
sotto un velo di sabbia: si leggeva come carta vetrata. Adesso le macchie larghe stanno nel
BUFFER -- crescono insieme al terreno -- e il puntinio fine entra solo avvicinandosi, con una
seconda passata ancorata al terreno perche' il buffer ha due pixel per cella e ingrandito a
venti e' una poltiglia.

### Cosa costa

Misurato, stessa macchina, dalla richiesta al terreno in piedi:

| | prima | adesso |
|---|---|---|
| caricamento | 905 ms | 1.400 ms |
| fotogramma | 16,7 ms | 16,7 ms |

Il disegno non e' cambiato di prezzo -- il buffer si dipinge una volta e poi panoramica e
ingrandimento restano un `drawImage`. Il caricamento si' -- di mezzo secondo -- ed e' quasi
tutto nel ciclo per sottopixel, non nelle chiamate al rumore: precalcolare i reticoli delle
macchie non ha spostato niente, e la prova e' stata tolta invece di essere tenuta per fede.
Cio' che ha spostato e' la memoria: il percorso del colore non alloca piu' un vettore per
cella.

### E una prova che falliva a caso

Durante questo lavoro la suite del backend ha fallito una volta su un test che da solo
passava sempre: `test_the_timeline_records_a_move_and_collapses_one_that_took_no_time`. Non
era casuale, e non era del gioco.

`database_now` tronca al secondo. Quel test fermava l'orologio DOPO aver creato i giocatori,
mentre ogni altra prova lo ferma prima -- e il primo periodo di politica nasce insieme ai
giocatori. Se la loro creazione scavalcava un secondo intero, il periodo iniziale aveva
lunghezza positiva, non veniva accorpato, e l'asserzione trovava due righe invece di una.
Scavalcare un secondo intero dipende da quanto e' carica la macchina, ed era carica perche'
stavo compilando il visore nello stesso momento.

Vale la pena scriverlo perche' il primo istinto e' chiamarla una fluttuazione e rilanciare: e
una prova che fallisce una volta ogni tanto, lasciata li', prima o poi si prende la colpa di
qualcos'altro.

## Rendere pubblico il repository

La CI era ferma perché i 2.000 minuti Actions inclusi nell'account erano esauriti, e due
repository se li dividevano. Su un repository **pubblico** i runner standard non consumano
quell'allowance: è la strada scelta, ed è gratis.

Prima di premere, tre cose sono state verificate e non date per buone:

    segreti usati dai workflow   nessuno   -> una PR da un fork non ha niente da rubare
    credenziali nella storia     zero      -> cercati dpg-, ghp_, github_pat_, chiavi
    account creabili via rete    nessuno   -> `provision` vive solo nella CLI

### Una rotta pubblica che non serviva più a nessuno

`GET /world/map` serviva quattro megabyte di pianeta, senza autenticazione, a centoventi
richieste al minuto per indirizzo. Da quando il pianeta è un file statico **nel visore non
c'era più una riga che la chiamasse**: la nominavano solo i test e questo documento.

Non era un buco di sicurezza — la geografia è pubblica per definizione — ma era mezzo
gigabyte al minuto di banda esposto da un'istanza gratuita, per codice morto. È uscita prima
che il repository diventasse leggibile da chiunque, insieme alla cache del payload che
esisteva solo per lei. Ciò che resta è `read_map`, che serve ancora all'esportazione statica
e al test di equivalenza fra le due strade.

Delle due prove che la coprivano ne resta una, sull'unica regola che vale ancora: lo stato
del mondo non si mette in cache, perché cambia.

### Perché il job `containers` era rosso, e perché ci sono voluti due giorni

Con i runner tornati, l'errore si è finalmente letto:

    FileNotFoundError: [Errno 2] No such file or directory: '/.github/workflows/ci.yml'
    5 failed, 121 passed

Un difetto solo, cinque volte. **L'immagine di prova contiene solo `backend/`** — il
Dockerfile copia quel contesto e basta — quindi un test che legge un file del REPOSITORY (il
workflow in `.github/`, il pianeta spedito in `frontend/`) lì dentro non trova niente.

Quattro erano i test scritti poche ore prima per tenere allineate le guardie della CI. Il
quinto, `test_the_shipped_asset_describes_the_world_the_code_builds`, era lì dal 19 settembre:
il run 118 — il primo rosso — **è esattamente il commit che lo ha introdotto**, e il 117,
l'ultimo verde, è quello prima. La CI è stata rossa due giorni per un test che non poteva
funzionare lì dal minuto in cui è nato.

Il rimedio non è far provare all'immagine cose che non contiene: quei test portano il
marcatore `repo` e il `CMD` dell'immagine li deseleziona. Non si perde copertura, perché il
job `backend` ha il repository intero sotto mano e li esegue tutti.

    5/126 raccolti con -m "repo"        i cinque che cadevano
    121/126 con -m "not repo"           esattamente i 121 che passavano

E la ragione per cui ci sono voluti due giorni è scritta sopra: `docker compose logs` senza
limite seppelliva l'errore. Anche `--tail 40` non bastava — vale PER SERVIZIO, e con cinque
servizi fanno duecento righe fra l'errore e la fine del log. Adesso sono quindici, che è
quanto serve a dire se un container è morto.

### I fork, e il doppio giro

Un repository pubblico può ricevere PR da un fork, e il push di un fork qui non arriva: senza
l'evento `pull_request` un contributo esterno entrerebbe senza che nessuno lo abbia provato.
Quindi ci sono tutti e due gli eventi — e ogni job scarta il caso doppio, girando su
`pull_request` solo quando il ramo di partenza non è di questo repository.

La condizione è scritta tre volte, perché GitHub non ha un `if` a livello di workflow. A
tenerle uguali c'è `tests/test_workflow.py` e non la memoria: è il sesto caso di "due elenchi
che devono coincidere" di questo progetto, e il rimedio che funziona è sempre lo stesso.
Verificato che i tre controlli cadono davvero, separando una guardia, togliendo un tetto di
tempo e facendo divergere i due `paths-ignore`.

## Il mondo online, e due servizi morti

Il gioco e' in piedi su due servizi e un database:

    exilium-web   sito statico   il pianeta, il terreno, lo schermo di gioco
    exilium-api   web service    l'autorita': citta', ordini, ledger        OREGON
    exilium-db    PostgreSQL     il mondo                                   OREGON

### La regione non e' un dettaglio

Il primo servizio API e' rimasto MORTO dal 18 settembre e nessuno se n'era accorto: zero
righe di log, tutti i deploy falliti in compilazione perche' puntava a un `./Dockerfile` che
alla radice non esiste. Ma sotto quel guasto ce n'era un secondo, che non si sarebbe visto
nemmeno correggendo il primo: il servizio stava a **Frankfurt** e il database a **Oregon**, e
l'indirizzo interno di un database Render non attraversa le regioni.

Il guasto di una regione sbagliata non si presenta come "regione sbagliata": si presenta come
un servizio che non parte. Per questo il servizio nuovo e' nato dove sta il database, e
`render.yaml` adesso lo dice.

### Le tre copie del pianeta, finalmente confrontabili

Il pianeta vive nella tabella, che decide DOVE si atterra, e nel file spedito col visore, che
decide COSA si vede. Un test confronta il file col codice; il database era la terza copia e
non la guardava nessuno -- e un pianeta diverso nel database significa scegliere una casella
guardandone un'altra, in silenzio.

Adesso l'API scrive nel log, all'avvio, di quale pianeta si tratta. La prima volta che l'ha
fatto, la risposta e' stata quella che serviva:

    database   Hesperia - Erebo-01 - freq 152 - gen 8 - 231.042 caselle
    file       Hesperia - Erebo-01 - freq 152 - gen 8 - 231.042 caselle

Non allinea le copie: rende leggibile la terza, che e' la condizione per accorgersi.

## Decisioni

Le scelte che vincolano il progetto — il tick da 24 ore, il multiplayer, il confine della
simulazione, l'assenza di un formato di salvataggio separato — sono registrate in
`decisions.md` con motivazione, alternative scartate e condizione di revisione.

## Riferimenti tecnici

- [PostgreSQL: row locks](https://www.postgresql.org/docs/17/explicit-locking.html)
- [FastAPI: container da immagine Python](https://fastapi.tiangolo.com/deployment/docker/)
- [Next.js: installazione](https://nextjs.org/docs/app/getting-started/installation)
