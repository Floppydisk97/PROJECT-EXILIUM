"""Persistence and read model for the authoritative planet map.

Generation is one-shot: the map is written once and then immutable (DB triggers enforce it).
The economic world (policy, ticks, ledger) is untouched here; this module only owns geography.

`read_map` is a RENDER model, not a dump of the table: it returns the land tiles the client
draws (the ocean is a smooth shell, so ocean polygons would be dead weight) and a neighbour
count instead of the full adjacency array. The table keeps the complete geography.
"""
from psycopg.types.json import Jsonb

from app import worldgen
from app.service import DomainError

INSERT_CHUNK = 4000  # bound peak memory while writing tens of thousands of tiles


def _round(v):
    # Five decimals on a unit sphere is well under a pixel at any sane zoom, and keeps
    # the JSON payload small enough for a phone.
    return [round(c, 5) for c in v]


def _tile_rows(world):
    for t in world.tiles:
        yield (
            t.id, t.lat, t.lon, *_round(t.center), t.elevation, t.temperature, t.rainfall,
            t.biome, list(t.neighbors), Jsonb([_round(p) for p in t.polygon]),
        )


def generate_and_store(conn, seed: str, frequency: int = worldgen.PRODUCTION_FREQUENCY) -> dict:
    if conn.execute("SELECT 1 FROM world_map WHERE id = 1").fetchone():
        raise DomainError(409, "World map already generated; a new world needs a new migration")
    try:
        world = worldgen.generate(seed, frequency)
    except ValueError as error:
        raise DomainError(422, str(error))

    conn.execute(
        """INSERT INTO world_map(id, name, seed, frequency, sea_level, generator_version)
           VALUES (1, %s, %s, %s, %s, %s)""",
        (worldgen.WORLD_NAME, world.seed, world.frequency, world.sea_level,
         worldgen.GENERATOR_VERSION),
    )
    statement = """INSERT INTO world_tiles
        (id, lat, lon, cx, cy, cz, elevation, temperature, rainfall, biome, neighbors, polygon)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    chunk = []
    with conn.cursor() as cur:
        for row in _tile_rows(world):
            chunk.append(row)
            if len(chunk) >= INSERT_CHUNK:
                cur.executemany(statement, chunk)
                chunk.clear()
        if chunk:
            cur.executemany(statement, chunk)

    biomes: dict[str, int] = {}
    land = 0
    for t in world.tiles:
        biomes[t.biome] = biomes.get(t.biome, 0) + 1
        land += t.elevation >= 0
    return {
        "name": worldgen.WORLD_NAME, "seed": world.seed, "frequency": world.frequency,
        "tiles": len(world.tiles), "land": land, "biomes": biomes,
    }


def read_map(conn) -> dict:
    meta = conn.execute(
        "SELECT name, seed, frequency, sea_level, generated_at FROM world_map WHERE id = 1"
    ).fetchone()
    if meta is None:
        raise DomainError(404, "World map not generated")
    total = int(conn.execute(
        "SELECT count(*) AS n FROM world_tiles WHERE map_id = 1"
    ).fetchone()["n"])
    tiles = conn.execute(
        """SELECT id, lat, lon, cx, cy, cz, elevation, temperature, rainfall, biome,
                  COALESCE(array_length(neighbors, 1), 0) AS neighbor_count, polygon
           FROM world_tiles WHERE map_id = 1 AND elevation >= 0 ORDER BY id"""
    ).fetchall()
    return {
        "name": meta["name"], "seed": meta["seed"], "frequency": meta["frequency"],
        "sea_level": meta["sea_level"], "tile_count": total, "land_count": len(tiles),
        "tiles": [
            {
                "id": t["id"], "lat": t["lat"], "lon": t["lon"],
                "center": [t["cx"], t["cy"], t["cz"]],
                "elevation": t["elevation"], "temperature": t["temperature"],
                "rainfall": t["rainfall"], "biome": t["biome"],
                "neighbor_count": t["neighbor_count"], "polygon": t["polygon"],
            }
            for t in tiles
        ],
    }
