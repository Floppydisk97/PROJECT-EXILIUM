-- Il generatore passa alla versione 4. Tre cambiamenti, in ordine di peso:
--
-- 1. Le depressioni del terreno vengono riempite fino al punto di sfioro (priority flood),
--    quindi esistono laghi di ogni dimensione, dalle pozze ai mari interni, e i fiumi
--    attraversano i laghi invece di fermarsi alla prima conca. Il mondo precedente aveva
--    trenta caselle di lago su centonovantatremila.
-- 2. Gli archi di isole sono centri seminati anziche' creste di rumore, e la base di rumore
--    dei bacini oceanici e' isotropa: spariscono le fasce parallele quasi periodiche che
--    rendevano le coste una successione di nastri a esse.
-- 3. Corretto un errore nella scala del rilievo: la quota veniva normalizzata su un massimo
--    del campo fissato a 1.0 anziche' sul massimo reale. Ogni contributo aggiunto al campo
--    gonfiava quindi tutte le altezze del pianeta.
--
-- Come 0004, 0005, 0006 e 0007: una geografia nuova e' un mondo nuovo, quindi la mappa viene
-- azzerata e il primo avvio successivo la rigenera.
--
-- PERCORSO DISTRUTTIVO, da leggere prima di applicarla in produzione:
--   Reset         DELETE di world_tiles e world_map, con i trigger di immutabilita'
--                 disabilitati per la durata della transazione e riabilitati subito dopo.
--   Backup        scripts/backup.sh produce un dump verificato (pg_dump -Fc piu' controllo
--                 del TOC). Va eseguito PRIMA: questa migrazione non ha un downgrade, e il
--                 rollback e' il ripristino del dump.
--   Ripopolamento il comando di avvio dell'API esegue app.mapcli, che rigenera dal seed in
--                 circa sette secondi e trecento megabyte di picco. E' deterministico: lo
--                 stesso seed ricostruisce esattamente la stessa mappa.
--   Prerequisito  nessuna citta' e' legata a una casella. Resta vero oggi; quando quel
--                 legame esistera' questa migrazione non potra' piu' essere scritta cosi'.

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
