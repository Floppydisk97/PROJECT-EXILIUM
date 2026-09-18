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
che disabilita i trigger, azzera le tabelle e le riabilita. È il percorso usato da `0004`
(mondo più grande), `0005` (forme del terreno) e `0006` (tassellatura più fitta).

La sfera è un icosaedro suddiviso: ogni vertice originale è una casella del duale di
Goldberg, quindi esagoni con esattamente dodici pentagoni ai vertici dell'icosaedro
(`10*f² + 2` caselle). La generazione è deterministica dal seed e gira una volta sola: la
riproducibilità cross-platform dei float non è richiesta, quella entro un interprete sì ed è
verificata dai test. Nessun valore economico è in virgola mobile.

Il generatore v2 produce forme riconoscibili anziché macchie di rumore: catene montuose da
rumore *ridged* raccolto in cinture; fiumi da accumulo di deflusso a valle sul grafo delle
caselle, con i bacini chiusi abbastanza pieni promossi a laghi; deserti da un profilo zonale
delle precipitazioni con fasce aride subtropicali, continentalità (BFS della distanza dal
mare) e ombra pluviometrica campionata sopravvento; arcipelaghi da un'ottava ad alta
frequenza, con le componenti connesse a dare la dimensione di ogni massa continentale.

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

Sulla geografia i limiti sono altrettanto espliciti. La generazione costruisce l'intera
sfera in memoria in una volta: è il picco di memoria, non il tempo, a fissare il tetto della
frequenza, e su un'istanza piccola quel tetto è vicino. Il payload e il tempo di costruzione
lato client crescono linearmente con le caselle, quindi ogni aumento della tassellatura è un
compromesso con il primo caricamento, soprattutto su mobile. La mappa non ha ancora alcun
legame con le città: quando esisterà, una migrazione che azzera le caselle non sarà più
un'operazione innocua e andrà ripensata.

## Riferimenti tecnici

- [PostgreSQL: row locks](https://www.postgresql.org/docs/17/explicit-locking.html)
- [FastAPI: container da immagine Python](https://fastapi.tiangolo.com/deployment/docker/)
- [Next.js: installazione](https://nextjs.org/docs/app/getting-started/installation)
