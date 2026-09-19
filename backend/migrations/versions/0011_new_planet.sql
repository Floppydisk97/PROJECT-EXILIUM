-- Pianeta nuovo: seme Erebo-01 al posto di Hesperia-01, e un quinto di caselle in piu'.
-- Il nome del mondo resta Hesperia: il seme e' come il pianeta viene disegnato, il nome e'
-- come si chiama, e sono due cose diverse.
--
-- 1. Il seme. Hesperia-01 non convinceva, e il seme conta piu' di qualsiasi parametro: su
--    quattordici semi provati alla stessa configurazione, le terre emerse passano da
--    dodici continenti con la massa maggiore al 30 per cento (Hesperia-01) a una massa
--    sola che ne tiene l'82 (Cassia-01). Erebo-01 e' il piu' frammentato fra quelli
--    abitabili: 15 continenti, 62 masse, la maggiore al 28 per cento, 38 isolotti sotto le
--    20 caselle. Un mondo di arcipelaghi e mari stretti, con il 40 per cento di fiumi in
--    piu' di prima -- che per un mondo condiviso fra piu' giocatori e' una geografia che
--    vuol dire qualcosa, invece di un unico blocco di terra.
--
-- 2. La dimensione: da 193.212 a 231.042 caselle, il 20 per cento in piu'.
--    Non di piu', e la ragione e' misurata, non estetica. L'intera sfera viene costruita
--    in memoria in una volta sola, quindi il picco cresce linearmente a circa 1,55 kB per
--    casella, e a decidere il tetto e' l'istanza da 512 MB:
--
--        193.212 caselle     9 s      303 MB   (com'era)
--        231.042 caselle    11 s      358 MB   <- qui, 154 MB di margine
--        256.002 caselle    10 s      395 MB   (il massimo che il piano free regge)
--        400.002 caselle    18 s      609 MB   (gia' oltre l'istanza)
--      1.936.002 caselle    92 s    2.898 MB   (il "per dieci": sei volte l'istanza)
--
--    Dietro quel muro ce ne sono altri tre, e pagare un'istanza piu' grande non ne
--    abbatte nessuno da solo: il database free tiene 1 GB e un mondo per dieci sarebbe
--    ~950 MB di sole caselle; il payload della mappa passerebbe da 10,6 a ~105 MB; e il
--    client dovrebbe passare alla GPU mezzo gigabyte di geometria, cosa che nessun
--    telefono fa. Un mondo davvero grande si serve per regioni inquadrate invece che
--    intero: e' un'architettura, non una costante.
--
-- Il seme non e' piu' scritto nel comando di avvio: sta in worldgen.PRODUCTION_SEED e
-- mapcli lo prende da li'. Erano due posti per un fatto solo, senza modo di accorgersi
-- che divergevano.
--
-- Come le precedenti: una geografia nuova e' un mondo nuovo, quindi la mappa viene azzerata
-- e il primo avvio successivo la rigenera.
--
-- PERCORSO DISTRUTTIVO, invariato rispetto a 0008, 0009 e 0010:
--   Reset         DELETE di world_tiles e world_map con i trigger di immutabilita'
--                 disabilitati per la sola durata della transazione.
--   Backup        NON esiste oggi un modo per farlo: scripts/backup.sh passa per
--                 `docker compose` e vede solo lo stack locale, e il database gestito non
--                 accetta connessioni esterne (ipAllowList vuota). E' un debito noto, ed e'
--                 la quarta volta che questa riga viene scritta.
--   Ripopolamento app.mapcli rigenera dal seme in circa undici secondi e 358 MB di picco,
--                 in modo deterministico.
--   Prerequisito  nessuna citta' e' legata a una casella, e questa migrazione tocca solo
--                 world_tiles e world_map: players, cities, resource_ledger, orders e ticks
--                 restano intatti.

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
