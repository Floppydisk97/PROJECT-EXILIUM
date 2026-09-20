-- L'atterraggio: la casella smette di essere scenografia.
--
-- Finora una citta' non sapeva dove fosse. Il pianeta si guardava, si sceglieva un sito, e poi
-- il gioco si svolgeva da tutt'altra parte: nessuna colonna legava una colonia alla geografia
-- che la circonda. Da qui in avanti atterrare significa prendere una casella, e quella casella
-- decide con che terreno hai a che fare.
--
-- TRE COLONNE CHE ARRIVANO INSIEME O NON ARRIVANO. `tile_id` dice dove, `landed_at` quando,
-- `map_seed` con quale mondo locale. Un vincolo le tiene legate: una citta' e' in orbita (tutte
-- e tre nulle) oppure a terra (tutte e tre piene). Non esiste uno stato intermedio, perche' una
-- citta' con una casella ma senza seme sarebbe una colonia su un terreno che nessuno sa
-- generare.
--
-- IL SEME, NON LA MAPPA. La mappa locale e' 16.384 celle. Salvarla vorrebbe dire sedicimila
-- righe per colonia, cioe' ottanta milioni per il mondo da cinquemila giocatori che questo
-- pianeta e' dimensionato a reggere. Ma la mappa e' una funzione pura del seme e di cosa il
-- pianeta dice del sito, quindi si rigenera in sei centesimi di secondo ogni volta che serve.
-- Quello che si conserva e' una stringa di trentadue caratteri.
--
-- E' anche cio' che risolve la contraddizione fra "casuale a ogni atterraggio" e "mondo
-- condiviso e persistente": il dado si tira UNA volta, al momento dell'atterraggio, e da li' in
-- poi quel terreno e' identico per tutti e per sempre. Quando le colonie potranno modificare il
-- terreno, le modifiche saranno righe a parte sopra questa base -- come fa un salvataggio di
-- gioco, che non riscrive il mondo ma cio' che gli e' stato fatto.
--
-- UNA CASELLA, UNA COLONIA. L'indice parziale lo impone. Con circa 70.000 caselle di terra e
-- cinquemila giocatori previsti c'e' spazio in abbondanza, e la scarsita' non e' nel numero ma
-- nella QUALITA': un fiume nel deserto e' una casella sola, e se la prende qualcun altro non
-- c'e' piu'. E' questo che rende la scelta del sito una decisione invece di una formalita'.
--
-- ATTERRARE E' IRREVERSIBILE. Un trigger lo impone: una volta a terra, quelle tre colonne non
-- si toccano piu'. Se un giorno esistera' il trasferimento di una colonia, sara' una regola di
-- gioco scritta apposta e non un UPDATE distratto.
--
-- NON DISTRUTTIVA: aggiunge colonne. Le citta' esistenti restano in orbita, cioe' esattamente
-- dove il gioco le teneva finora senza dirlo.

ALTER TABLE cities
    ADD COLUMN map_id smallint NOT NULL DEFAULT 1,
    ADD COLUMN tile_id integer,
    ADD COLUMN landed_at timestamptz,
    ADD COLUMN map_seed text CHECK (map_seed IS NULL OR length(map_seed) = 32);

ALTER TABLE cities ADD CONSTRAINT cities_landed_all_or_nothing CHECK (
    (tile_id IS NULL AND landed_at IS NULL AND map_seed IS NULL) OR
    (tile_id IS NOT NULL AND landed_at IS NOT NULL AND map_seed IS NOT NULL)
);
-- La chiave e' composita e basta lei. Una `REFERENCES world_map(id)` su map_id da sola
-- pretenderebbe che il pianeta esista PRIMA di qualunque colonia -- ma una colonia esiste in
-- orbita prima di atterrare, e in uno schema appena migrato il pianeta non c'e' ancora.
-- Cosi' invece il vincolo non viene verificato finche' tile_id e' nullo, che e' esattamente
-- "finche' non sei atterrato".
ALTER TABLE cities ADD CONSTRAINT cities_tile_exists
    FOREIGN KEY (map_id, tile_id) REFERENCES world_tiles(map_id, id);
CREATE UNIQUE INDEX cities_one_per_tile ON cities(map_id, tile_id) WHERE tile_id IS NOT NULL;

CREATE OR REPLACE FUNCTION reject_relanding() RETURNS trigger AS $$
BEGIN
    IF OLD.tile_id IS NOT NULL AND (
        NEW.tile_id IS DISTINCT FROM OLD.tile_id
        OR NEW.landed_at IS DISTINCT FROM OLD.landed_at
        OR NEW.map_seed IS DISTINCT FROM OLD.map_seed
    ) THEN
        RAISE EXCEPTION 'A landed colony cannot be moved or reseeded'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cities_landing_is_final
    BEFORE UPDATE ON cities
    FOR EACH ROW EXECUTE FUNCTION reject_relanding();
