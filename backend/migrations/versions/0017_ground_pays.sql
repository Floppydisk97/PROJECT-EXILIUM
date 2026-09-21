-- Il terreno entra nell'economia. Ruleset 2.
--
-- Tre numeri, non la mappa: una colonia e' 590.000 celle e la produzione si calcola ogni
-- volta che qualcuno guarda una citta'. La mappa si riduce UNA volta, all'atterraggio, a cio'
-- che le regole le chiedono davvero -- e cio' che le regole chiedono sta qui.
--
-- Annullabili di proposito. Una colonia ancora in orbita non ha terreno, e NESSUN terreno non
-- e' ZERO terreno: zero spazio vorrebbe dire una colonia gia' stretta prima di essere scesa.
-- Le regole leggono NULL come "nessun effetto", che e' esattamente il comportamento di prima.
ALTER TABLE cities
    ADD COLUMN site_yield  smallint CHECK (site_yield BETWEEN 0 AND 100),
    ADD COLUMN site_effort smallint CHECK (site_effort BETWEEN 0 AND 200),
    ADD COLUMN site_room   integer  CHECK (site_room >= 0);

-- Tutti e tre o nessuno, come per l'atterraggio: mezza descrizione di un terreno sarebbe un
-- modo silenzioso di far produrre una colonia a un tasso che non le appartiene.
ALTER TABLE cities ADD CONSTRAINT cities_site_all_or_nothing CHECK (
    (site_yield IS NULL AND site_effort IS NULL AND site_room IS NULL)
    OR (site_yield IS NOT NULL AND site_effort IS NOT NULL AND site_room IS NOT NULL)
);

-- Il terreno esiste solo dopo l'atterraggio. Non il contrario: una colonia atterrata prima di
-- questa migrazione ha ancora i campi vuoti, e li riempie `python -m app.sitefill` rigenerando
-- dal seme -- che e' un riempimento ESATTO, non una stima, perche' il seme e' salvato.
ALTER TABLE cities ADD CONSTRAINT cities_site_needs_ground CHECK (
    site_yield IS NULL OR tile_id IS NOT NULL
);
