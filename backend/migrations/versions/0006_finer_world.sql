-- Il pianeta passa a una tassellatura tre volte piu' fitta (frequenza 139 -> 193.212 tile).
-- Come 0004 e 0005: ridimensionare significa un mondo nuovo, quindi la mappa viene azzerata
-- e il primo avvio successivo la rigenera. E' l'unico percorso sanzionato per sostituire
-- una mappa altrimenti immutabile.

ALTER TABLE world_map DROP CONSTRAINT world_map_frequency_check;
ALTER TABLE world_map ADD CONSTRAINT world_map_frequency_check
    CHECK (frequency BETWEEN 2 AND 160);

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
