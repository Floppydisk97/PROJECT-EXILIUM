-- Il generatore passa alla versione 6. Due difetti dell'idrologia, uno reale e uno grafico.
--
-- 1. I fiumi morivano dentro i laghi. La superficie di un lago e' piatta, quindi "scendi
--    verso il vicino piu' basso" non decide nulla: il pareggio veniva risolto sul fondale,
--    cioe' mandando l'acqua nel punto piu' profondo della conca -- l'unica casella che per
--    definizione non ha uscita. Misurato sulla mappa in produzione: 709 caselle di terra
--    senza deflusso, 651 delle quali dentro un lago, e la portata piu' alta del pianeta
--    (1465) si fermava li'. Il pianeta non aveva un solo fiume che arrivasse al mare.
--    Ora il pareggio si risolve sull'ordine in cui il riempimento delle conche raggiunge le
--    caselle, che e' gia' l'ordine in cui l'acqua ne uscirebbe: il fiume attraversa il lago,
--    esce dall'emissario e prosegue. Caselle senza deflusso: zero. Portata massima: 3543,
--    e sta su una foce.
--
-- 2. Fiumi a ripetizione. La portata si conta in caselle, quindi la stessa soglia significa
--    un bacino sempre piu' piccolo man mano che la griglia si infittisce: a 20, su questo
--    pianeta, un tratto di fiume era il drenaggio di una decina di caselle, cioe' un fosso.
--    Ne venivano disegnati 5.529, e quasi ognuno aveva un secondo corso parallelo accanto
--    (0,94 vicini non collegati per tratto) -- il tratteggio che si vede appena si zooma.
--    La soglia ora e' rapportata alla griglia (una casella su duemila, cioe' 97 qui):
--    946 tratti, 92 sistemi fluviali, 0,17 paralleli per tratto.
--
-- Terzo effetto collaterale, voluto: il terreno adottato e' la superficie riempita per
-- tutte le caselle e non solo per i laghi. Una conca troppo poco profonda per essere un lago
-- conservava il proprio fondale mentre il fiume sopra le veniva instradato sul riempimento,
-- cioe' un fiume disegnato in salita fuori da una pozza. Le conche cosi' livellate sono per
-- costruzione piu' basse di LAKE_MIN_DEPTH: pochi metri, e gia' sott'acqua.
--
-- Come le precedenti: una geografia nuova e' un mondo nuovo, quindi la mappa viene azzerata
-- e il primo avvio successivo la rigenera.
--
-- PERCORSO DISTRUTTIVO, invariato rispetto a 0008 e 0009:
--   Reset         DELETE di world_tiles e world_map con i trigger di immutabilita'
--                 disabilitati per la sola durata della transazione.
--   Backup        NON esiste oggi un modo per farlo: scripts/backup.sh passa per
--                 `docker compose` e vede solo lo stack locale, e il database gestito non
--                 accetta connessioni esterne (ipAllowList vuota). E' un debito noto.
--   Ripopolamento app.mapcli rigenera dal seed in circa tredici secondi e trecento megabyte
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
