-- Il pianeta passa a una tassellatura piu' fine (frequenza 80 -> 64002 tile).
-- Ridimensionare significa un mondo nuovo: questa migrazione dedicata allenta il
-- vincolo sulla frequenza e azzera la mappa, cosi' il prossimo avvio la rigenera.
-- E' l'unico percorso sanzionato per sostituire una mappa altrimenti immutabile.

ALTER TABLE world_map DROP CONSTRAINT world_map_frequency_check;
ALTER TABLE world_map ADD CONSTRAINT world_map_frequency_check
    CHECK (frequency BETWEEN 2 AND 96);

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
