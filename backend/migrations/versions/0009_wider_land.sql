-- Il generatore passa alla versione 5. Tre aggiustamenti dopo aver guardato la v4 in
-- produzione:
--
-- 1. I laghi maggiori erano troppo grandi. Raggio massimo delle conche e dei mari interni
--    ridotto: il corpo d'acqua maggiore passa da 625 caselle a 442, la gamma delle
--    dimensioni resta (un solo corpo oltre le 300 caselle, cinque fra 100 e 299,
--    ventuno fra 20 e 99, e la coda di pozze).
-- 2. Piu' terra utilizzabile. Il livello del mare scende dal 76esimo al 73esimo percentile,
--    quindi le terre emerse passano dal 24 al 27 per cento della sfera. Al netto di acqua
--    ferma, ghiaccio permanente e roccia nuda -- che non sono terra su cui si fonda nulla --
--    la superficie utilizzabile passa dal 16,9 al 21,6 per cento.
-- 3. I fiumi non attraversano piu' i laghi. Non e' una modifica alla geografia ma al render
--    model, quindi da sola non avrebbe richiesto una migrazione.
--
-- Come le precedenti: una geografia nuova e' un mondo nuovo, quindi la mappa viene azzerata
-- e il primo avvio successivo la rigenera.
--
-- PERCORSO DISTRUTTIVO, invariato rispetto a 0008:
--   Reset         DELETE di world_tiles e world_map con i trigger di immutabilita'
--                 disabilitati per la sola durata della transazione.
--   Backup        NON esiste oggi un modo per farlo: scripts/backup.sh passa per
--                 `docker compose` e vede solo lo stack locale, e il database gestito non
--                 accetta connessioni esterne (ipAllowList vuota). E' un debito noto.
--   Ripopolamento app.mapcli rigenera dal seed in circa otto secondi e trecento megabyte
--                 di picco, in modo deterministico.
--   Prerequisito  nessuna citta' e' legata a una casella, e questa migrazione tocca solo
--                 world_tiles e world_map: players, cities, resource_ledger, orders e ticks
--                 restano intatti.

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
