-- Le risorse di base. Il terreno smette di dire quanto vai forte e comincia a dire COSA hai.
--
-- `site_yield` diventa `site_food`: si chiamava "resa" quando la risorsa era una sola e la
-- domanda "resa di che cosa?" non aveva senso. Ora ce l'ha.
ALTER TABLE cities RENAME COLUMN site_yield TO site_food;
ALTER TABLE cities RENAME CONSTRAINT cities_site_all_or_nothing TO cities_site_complete;

ALTER TABLE cities
    ADD COLUMN site_timber smallint CHECK (site_timber BETWEEN 0 AND 100),
    ADD COLUMN site_stone  smallint CHECK (site_stone  BETWEEN 0 AND 100);

-- Tutte o nessuna, come prima: mezza descrizione di un terreno e' un modo silenzioso di far
-- produrre una colonia cio' che non ha sotto i piedi.
ALTER TABLE cities DROP CONSTRAINT cities_site_complete;
ALTER TABLE cities ADD CONSTRAINT cities_site_complete CHECK (
    (site_food IS NULL AND site_timber IS NULL AND site_stone IS NULL
     AND site_effort IS NULL AND site_room IS NULL)
    OR (site_food IS NOT NULL AND site_timber IS NOT NULL AND site_stone IS NOT NULL
        AND site_effort IS NOT NULL AND site_room IS NOT NULL)
);
ALTER TABLE cities DROP CONSTRAINT cities_site_needs_ground;
ALTER TABLE cities ADD CONSTRAINT cities_site_needs_ground CHECK (
    site_food IS NULL OR tile_id IS NOT NULL
);
