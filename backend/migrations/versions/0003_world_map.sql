-- Il pianeta autoritativo 'Hesperia': una sfera geodetica di tile generata da seed.
-- Separato dal mondo economico (tabella world): qui vivono geografia e clima, non saldi.
-- La mappa è singleton e immutabile una volta generata; nessun overwrite silenzioso.

CREATE TABLE world_map (
    id smallint PRIMARY KEY CHECK (id = 1),
    name text NOT NULL,
    seed text NOT NULL,
    frequency integer NOT NULL CHECK (frequency BETWEEN 2 AND 48),
    sea_level double precision NOT NULL,
    generator_version integer NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE world_tiles (
    map_id smallint NOT NULL DEFAULT 1 REFERENCES world_map(id),
    id integer NOT NULL CHECK (id >= 0),
    lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
    cx double precision NOT NULL,
    cy double precision NOT NULL,
    cz double precision NOT NULL,
    elevation integer NOT NULL,
    temperature double precision NOT NULL,
    rainfall integer NOT NULL CHECK (rainfall >= 0),
    biome text NOT NULL CHECK (biome IN (
        'ocean', 'sea_ice', 'ice_sheet', 'tundra', 'boreal_forest',
        'temperate_forest', 'temperate_swamp', 'arid_shrubland', 'desert',
        'tropical_rainforest', 'tropical_swamp')),
    neighbors integer[] NOT NULL,
    polygon jsonb NOT NULL,
    PRIMARY KEY (map_id, id)
);
CREATE INDEX world_tiles_biome ON world_tiles(map_id, biome);

-- La mappa è un audit geografico: una volta generata non si muta né si cancella per riga.
-- Rigenerare significa un nuovo mondo (nuovo seed) tramite una migrazione dedicata.
CREATE FUNCTION reject_map_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'world map is immutable once generated' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER world_tiles_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON world_tiles
FOR EACH STATEMENT EXECUTE FUNCTION reject_map_mutation();
CREATE TRIGGER world_map_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON world_map
FOR EACH STATEMENT EXECUTE FUNCTION reject_map_mutation();
