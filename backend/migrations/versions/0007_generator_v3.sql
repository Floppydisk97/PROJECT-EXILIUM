-- Il generatore passa alla versione 3: bacini oceanici che spezzano davvero la terra in tre
-- continenti invece di un supercontinente, coste deformate con golfi e stretti, archi di
-- isole, e una fascia arida che e' una fascia e non una voragine: deserto piu' steppa arida
-- passano da un terzo delle terre emerse a un quinto.
--
-- Come 0004, 0005 e 0006: una geografia nuova e' un mondo nuovo, quindi la mappa viene
-- azzerata e il primo avvio successivo la rigenera. E' l'unico percorso sanzionato per
-- sostituire una mappa altrimenti immutabile, ed e' innocuo soltanto finche' nessuna
-- citta' e' legata a una casella. Quando quel legame esistera', questa migrazione non
-- potra' piu' essere scritta cosi'.

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
