# Fondazione del mondo autoritativo

## Decisioni iniziali

Un mondo singleton (`exilium-prime`, id 1), più colonie future per giocatore e una
risorsa `alloy`. La vertical slice consente per regola applicativa di fondare soltanto
la prima colonia; il database limita a una la capitale ma ammette colonie non-capitali.
Gli importi sono interi in millesimi: 1000 milli-alloy = 1 alloy. Nessun float.
API e worker usano esclusivamente l'orologio PostgreSQL in UTC, troncato al secondo.
Il client invia intenzioni, mai saldi, tassi, proprietari, date o risultati.
Ogni tick scade alle 00:00 UTC: 24 ore esatte, indipendenti da ora legale e riavvii.
Il primo tick è la prima mezzanotte successiva alla migrazione.

Regole dimostrative, versionate come ruleset 1 (non bilanciamento definitivo):

- politica `balanced`: 10 milli-alloy/s; `industrial`: 20 milli-alloy/s;
- ogni livello produttivo aggiunge 5 milli-alloy/s;
- ogni estrattore aggiunge 25 milli-alloy/s e costa 60000 milli-alloy;
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
`players` contiene handle normalizzato e password Argon2; `auth_sessions` contiene
soltanto hash SHA-256 di token casuali, scadenza e revoca. Il token grezzo vive solo
nel cookie HttpOnly, SameSite=Lax e Secure salvo configurazione locale esplicita.
`world_memberships` registra l'ingresso idempotente in `exilium-prime`.
`world_cells` è una griglia logica minima; `cities` contiene proprietario, cella,
capitale, livello e istante di produzione liquidata. `city_buildings` registra estrattori.
`resource_ledger` contiene accrediti/addebiti firmati, causale, evento univoco e data
economica. Il saldo è SEMPRE la somma del ledger, senza un secondo saldo mutabile.
`orders` conserva intenzione, chiave idempotente, tick bersaglio ed esito.
`idempotency_records` associa globalmente per giocatore chiave, tipo azione,
SHA-256 del payload canonico e risultato. È immutabile.
`ticks` conserva confine, ruleset e riepilogo del risultato atomico.

Vincoli PostgreSQL: mondo unico, foreign key senza cascade distruttivi, cella unica
e costruibile, una sola capitale per proprietario (senza vietare altre colonie),
importi non nulli e segni compatibili con causale, eventi
ledger univoci, chiave ordine unica per città, massimo un ordine per tipo/città/tick,
numero tick e confine univoci. Trigger vietano UPDATE/DELETE/TRUNCATE del ledger e
dei tick. Il trigger degli addebiti blocca la città e impedisce un saldo negativo.
Un amministratore DB resta fidato: può cambiare lo schema o disabilitare trigger.

Invarianti applicative: ogni mutazione economica blocca prima `world FOR UPDATE`,
poi opera su città/ordini nello stesso ordine deterministico. Non viene mai liquidata
produzione oltre un tick non ancora risolto. Nessun tempo fornito dal client viene usato.
L'accesso a una città richiede una sessione valida del proprietario (404 per città altrui).
Fondazione, accredito genesis, costruzione e relativo addebito sono transazioni atomiche.

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

La chiave `Idempotency-Key` UUID è obbligatoria per fondazione, costruzione e ordini.
Il retry con identico endpoint, bersaglio e payload restituisce lo stesso risultato;
riusarla con azione, bersaglio o payload diverso dà 409 prima di qualsiasi modifica.
Il confronto precede il controllo degli arretrati: un retry non crea nuovi effetti.
Il cutoff è l'ora DB dopo acquisizione lock, non l'arrivo HTTP. Alla scadenza esatta
non si accettano ordini per il tick in chiusura.

## Limiti deliberati

Il lock globale privilegia correttezza e auditabilità; non è una soluzione per milioni
di città. La somma del ledger e la liquidazione di tutte le città richiederanno snapshot
riconciliabili e partizionamento prima di una scala elevata. Non introdurre cache saldi
senza test di equivalenza col ledger. Nessun requisito di alta disponibilità è ancora
implementato. Compose è per sviluppo locale; non include TLS, backup, recupero password
o verifica email. Il frontend non può leggere il cookie di sessione e non salva token.

In `APP_ENV=production` il flag Secure viene imposto anche se una variabile tenta di
disabilitarlo. Ogni richiesta mutante che porta il cookie deve avere un header `Origin`
presente in `TRUSTED_ORIGINS`; l'assenza della configurazione chiude gli endpoint con 403.
Compose dichiara invece `development` e cookie non Secure per il solo HTTP su loopback.
La migrazione `0002` è forward-only: la procedura di ripristino da backup verificato è
documentata in [rollback 0002](rollback.md).

## Riferimenti tecnici

- [PostgreSQL: row locks](https://www.postgresql.org/docs/17/explicit-locking.html)
- [FastAPI: container da immagine Python](https://fastapi.tiangolo.com/deployment/docker/)
- [Next.js: installazione](https://nextjs.org/docs/app/getting-started/installation)
