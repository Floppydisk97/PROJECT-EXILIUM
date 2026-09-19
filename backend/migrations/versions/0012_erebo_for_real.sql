-- Secondo azzeramento della mappa a un'ora dal primo, e la ragione non e' la geografia.
--
-- La 0011 aveva due meta': il seme nuovo (Erebo-01) e la dimensione nuova (231.042 caselle).
-- La seconda e' arrivata, la prima no. In produzione e' nato Hesperia-01 a 231.042 caselle:
-- il pianeta vecchio alla dimensione nuova.
--
-- Il motivo. render.yaml e' un blueprint: descrive come un servizio va creato, e non tocca
-- un servizio gia' esistente finche' non se ne fa un sync. Il comando di avvio in esecuzione
-- portava ancora il seme come letterale --
--
--     python -m app.mapcli "Hesperia-01"
--
-- -- e un argomento esplicito vince su qualunque default messo nel codice. La 0011 ha
-- cancellato la mappa, e la riga successiva l'ha ricostruita col seme sbagliato.
--
-- E' lo stesso inciampo del giorno prima, quando API_INTERNAL_URL era stata cambiata nel
-- blueprint e non sul servizio. Quella volta era stata aggiornata anche sul servizio via
-- API; questa volta il campo era il comando di avvio, per cui quello strumento non esiste,
-- e la meta' mancante e' passata inosservata. **Cambiare render.yaml non cambia niente di
-- cio' che gira.**
--
-- Il comando di avvio ora e' `python -m app.mapcli` senza argomenti e il seme vive solo in
-- worldgen.PRODUCTION_SEED, quindi questo azzeramento fa nascere Erebo-01 davvero.
--
-- UNA COSA DA SAPERE PRIMA DI APPLICARLA. Sul piano free l'istanza ha 0,15 di core. La
-- rigenerazione della 0011 ha impiegato sei minuti e mezzo con la CPU incollata al limite,
-- Render ha stampato "Port scan timeout reached" e ha continuato a sondare: il servizio si
-- e' salvato per fortuna, non per progetto. Nella finestra fra il DELETE qui sotto e la fine
-- della rigenerazione il client mostra "mondo non ancora generato". Generare il pianeta
-- dentro il percorso di avvio e' una gara contro il timeout di Render, e va tolta di li'.
--
-- PERCORSO DISTRUTTIVO, invariato rispetto a 0008, 0009, 0010 e 0011:
--   Reset         DELETE di world_tiles e world_map con i trigger di immutabilita'
--                 disabilitati per la sola durata della transazione.
--   Backup        NON esiste oggi un modo per farlo: scripts/backup.sh passa per
--                 `docker compose` e vede solo lo stack locale, e il database gestito non
--                 accetta connessioni esterne (ipAllowList vuota). Quinta volta che questa
--                 riga viene scritta.
--   Ripopolamento app.mapcli rigenera dal seme nel codice; 27 s e 377 MB di picco su una
--                 macchina intera, sei minuti e mezzo a 0,15 di core.
--   Prerequisito  nessuna citta' e' legata a una casella, e questa migrazione tocca solo
--                 world_tiles e world_map: players, cities, resource_ledger, orders e ticks
--                 restano intatti.

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
