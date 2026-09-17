-- Generatore v2: montagne, fiumi, laghi, isole, deserti e calotte polari.
-- I tile acquistano la normale del terreno (per l'ombreggiatura del rilievo), la rete
-- idrografica (portata e tile di valle) e la dimensione della massa continentale.
-- Come per 0004, ridimensionare il mondo significa un mondo nuovo: la mappa viene
-- azzerata e il primo avvio successivo la rigenera. E' l'unico percorso sanzionato
-- per sostituire una mappa altrimenti immutabile.

ALTER TABLE world_tiles ADD COLUMN nx double precision NOT NULL DEFAULT 0;
ALTER TABLE world_tiles ADD COLUMN ny double precision NOT NULL DEFAULT 0;
ALTER TABLE world_tiles ADD COLUMN nz double precision NOT NULL DEFAULT 1;
ALTER TABLE world_tiles ADD COLUMN river_flow integer NOT NULL DEFAULT 0
    CHECK (river_flow >= 0);
ALTER TABLE world_tiles ADD COLUMN downstream integer NOT NULL DEFAULT -1
    CHECK (downstream >= -1);
ALTER TABLE world_tiles ADD COLUMN landmass_size integer NOT NULL DEFAULT 0
    CHECK (landmass_size >= 0);

ALTER TABLE world_tiles DROP CONSTRAINT world_tiles_biome_check;
ALTER TABLE world_tiles ADD CONSTRAINT world_tiles_biome_check CHECK (biome IN (
    'ocean', 'lake', 'sea_ice', 'ice_sheet', 'snow_cap', 'bare_rock', 'tundra',
    'boreal_forest', 'temperate_forest', 'temperate_swamp', 'arid_shrubland', 'desert',
    'tropical_rainforest', 'tropical_swamp'));

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;

-- I default servivano solo a poter aggiungere le colonne a tabella piena: la mappa ora e'
-- vuota e ogni riga futura arriva completa dal generatore.
ALTER TABLE world_tiles ALTER COLUMN nx DROP DEFAULT;
ALTER TABLE world_tiles ALTER COLUMN ny DROP DEFAULT;
ALTER TABLE world_tiles ALTER COLUMN nz DROP DEFAULT;
ALTER TABLE world_tiles ALTER COLUMN river_flow DROP DEFAULT;
ALTER TABLE world_tiles ALTER COLUMN downstream DROP DEFAULT;
ALTER TABLE world_tiles ALTER COLUMN landmass_size DROP DEFAULT;

CREATE INDEX world_tiles_rivers ON world_tiles(map_id, river_flow)
    WHERE river_flow > 0;
