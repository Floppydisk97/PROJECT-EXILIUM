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

La soglia è quindi espressa **rispetto alla griglia su cui è misurata**, un tratto disegnato
ogni duemila caselle di pianeta (`river_min_flow`), e viaggia nei metadati come le altre
costanti condivise. Sul pianeta di produzione fa 97: 946 tratti, 92 sistemi fluviali, 0,17
paralleli per tratto.

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

`GET /world/map` non è un dump della tabella ma ciò che il client disegna: le terre, la
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

## Decisioni

Le scelte che vincolano il progetto — il tick da 24 ore, il multiplayer, il confine della
simulazione, l'assenza di un formato di salvataggio separato — sono registrate in
`decisions.md` con motivazione, alternative scartate e condizione di revisione.

## Riferimenti tecnici

- [PostgreSQL: row locks](https://www.postgresql.org/docs/17/explicit-locking.html)
- [FastAPI: container da immagine Python](https://fastapi.tiangolo.com/deployment/docker/)
- [Next.js: installazione](https://nextjs.org/docs/app/getting-started/installation)
