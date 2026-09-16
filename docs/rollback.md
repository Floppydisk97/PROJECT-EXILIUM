# Rollback della migrazione 0002

La migrazione `0002_first_colony_loop` è intenzionalmente forward-only. Un downgrade
SQL eliminerebbe account, sessioni, membership, celle, colonie e costruzioni create
dopo il deploy e non potrebbe ricostruire in modo affidabile i vecchi token. Alembic
interrompe quindi `downgrade()` invece di simulare una reversibilità distruttiva.

Prima del deploy di `0002`:

1. fermare API e worker oppure portarli in manutenzione;
2. creare un backup PostgreSQL consistente e conservarne checksum e versione;
3. provare il ripristino su un database separato;
4. applicare `alembic upgrade head`, verificare `/health/ready` e riaprire il traffico.

Per tornare a `0001`:

1. fermare API, worker e job di migrazione;
2. conservare un backup forense dello stato fallito;
3. ripristinare integralmente il backup pre-`0002` in un nuovo database o volume;
4. verificare che `alembic current` restituisca `0001` e che ledger e tick coincidano
   con il backup verificato;
5. puntare i servizi della foundation al database ripristinato e riavviarli.

Non eseguire `DROP` manuali sul database attivo e non riutilizzare dati scritti dalla
versione `0002` con il codice `0001`. Il rollback perde intenzionalmente tutte le
operazioni accettate dopo il punto del backup; questa conseguenza va dichiarata prima
della decisione operativa.
