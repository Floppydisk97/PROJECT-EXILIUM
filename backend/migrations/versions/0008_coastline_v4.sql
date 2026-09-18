-- DESTRUCTIVE MAP RESET for generator v4. Back up and verify the database before upgrade.
-- This removes all persisted Hesperia geography. The API startup command must repopulate
-- Hesperia-01 after Alembic succeeds. Downgrade cannot reconstruct deleted geography;
-- rollback means restoring the verified pre-0008 database backup.

ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map DISABLE TRIGGER world_map_immutable;
DELETE FROM world_tiles;
DELETE FROM world_map;
ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable;
ALTER TABLE world_map ENABLE TRIGGER world_map_immutable;
