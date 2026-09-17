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

Invarianti applicative: ogni mutazione economica blocca prima `world FOR UPDATE`,
poi opera su città/ordini nello stesso ordine deterministico. Non viene mai liquidata
produzione oltre un tick non ancora risolto. Nessun tempo fornito dal client viene usato.
L'accesso a una città richiede token del suo proprietario (404 per città altrui).

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

## Limiti deliberati

Il lock globale privilegia correttezza e auditabilità; non è una soluzione per milioni
di città. La somma del ledger e la liquidazione di tutte le città richiederanno snapshot
riconciliabili e partizionamento prima di una scala elevata. Il cursore `balance_milli`
(migrazione 0002) rimuove il costo O(n) del saldo su lettura e scrittura ed è coperto da
test di equivalenza col ledger; ogni ulteriore cache economica deve mantenere la stessa
verifica. Nessun requisito di alta disponibilità è ancora implementato. Compose è per
sviluppo locale; non include TLS né gestione account pubblica. `scripts/backup.sh` e
`scripts/restore.sh` producono e ricaricano dump verificati (il restore rifiuta un mondo
in cui il saldo materializzato diverge dal ledger). I token si provisionano con CLI e non
vengono salvati nel frontend.

## Riferimenti tecnici

- [PostgreSQL: row locks](https://www.postgresql.org/docs/17/explicit-locking.html)
- [FastAPI: container da immagine Python](https://fastapi.tiangolo.com/deployment/docker/)
- [Next.js: installazione](https://nextjs.org/docs/app/getting-started/installation)
