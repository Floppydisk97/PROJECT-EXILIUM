-- L'orologio del mondo, perche' un tick al giorno rende il gioco improvabile.
--
-- IL PROBLEMA. Una mossa si valuta dopo ventiquattr'ore. Finche' il mondo e' in lavorazione
-- e i giocatori siamo noi, non e' una regola di gioco: e' l'impossibilita' di giocare, e
-- quindi di capire cosa manca.
--
-- PERCHE' NON BASTA ACCORCIARE IL TICK. La produzione non la fa il tick. POLICY_RATES e'
-- in milli-lega al SECONDO, e `settle_city` la calcola dalla differenza fra due timestamp;
-- il tick si limita a portare avanti il cursore fino al confine. Portare TICK_INTERVAL da
-- un giorno a dieci secondi darebbe 8640 cerimonie al giorno, ciascuna con dentro un
-- diecimillesimo di quello che aveva prima: il gioco non accelera di un millesimo.
--
-- Ad andare compresso e' l'OROLOGIO CHE LA SIMULAZIONE LEGGE, non la cadenza del tick.
--
--     tempo_del_mondo = ancora_mondo + (tempo_reale - ancora_reale) * velocita'
--
-- Tre colonne, e una proprieta' che rende questa migrazione sicura da spedire: con le due
-- ancore poste sullo stesso istante e velocita' 1, la formula si riduce a `tempo_reale`
-- ESATTAMENTE. Non "quasi": la sottrazione e la somma si annullano. Quindi finche' nessuno
-- gira la manopola il mondo si comporta come prima, bit per bit.
--
-- IL CAMBIO DI VELOCITA' RI-ANCORA. Cambiare `time_speed` senza toccare le ancore farebbe
-- saltare il tempo del mondo avanti o indietro di giorni -- e all'indietro significa
-- produzione negativa e un ledger che non torna. Quindi chi cambia la velocita' rimette
-- prima l'ancora sull'istante corrente, da cui la continuita' e' garantita per costruzione:
-- nel punto del cambio le due formule danno lo stesso valore.
--
-- COSA RESTA AL TEMPO REALE, ed e' voluto: `recorded_at` nel ledger, `completed_at` negli
-- ordini, `generated_at` sulla mappa. Sono colonne di audit -- dicono quando il fatto e'
-- stato SCRITTO, non quando VALE nel mondo. La distinzione e' la stessa che c'e' gia' fra
-- `effective_at` e `recorded_at`, e tenerla e' cio' che permette di leggere un log di
-- produzione anche dopo aver cambiato la velocita'.
--
-- Il vincolo sul confine di mezzanotte UTC resta intatto: il tempo del mondo e' comunque un
-- timestamp vero, e mezzanotte piu' un giorno e' ancora mezzanotte. Semplicemente, a
-- velocita' 60 un giorno di mondo dura ventiquattro minuti veri.
--
-- NON DISTRUTTIVA: aggiunge tre colonne, non tocca ne' la mappa ne' l'economia.

ALTER TABLE world
    ADD COLUMN time_speed double precision NOT NULL DEFAULT 1,
    ADD COLUMN time_anchor_real timestamptz,
    ADD COLUMN time_anchor_world timestamptz;

-- `now()` e non `clock_timestamp()`: e' il timestamp della transazione, quindi identico nelle
-- due colonne. Ancore sullo stesso istante piu' velocita' 1 significa nessuna differenza.
UPDATE world SET time_anchor_real = now(), time_anchor_world = now() WHERE id = 1;

ALTER TABLE world
    ALTER COLUMN time_anchor_real SET NOT NULL,
    ALTER COLUMN time_anchor_world SET NOT NULL,
    ADD CONSTRAINT world_time_speed_positive CHECK (time_speed > 0);
