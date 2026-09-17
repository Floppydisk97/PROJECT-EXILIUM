"""Persistence and read model for the authoritative planet map.

Generation is one-shot: the map is written once and then immutable (DB triggers enforce it).
The economic world (policy, ticks, ledger) is untouched here; this module only owns geography.
"""
from psycopg.types.json import Jsonb

from app import worldgen
from app.service import DomainError


def _round3(v):
    return [round(c, 6) for c in v]


def generate_and_store(conn, seed: str, frequency: int = 12) -> dict:
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
    rows = [
        (t.id, t.lat, t.lon, *_round3(t.center), t.elevation, t.temperature, t.rainfall,
         t.biome, list(t.neighbors), Jsonb([_round3(p) for p in t.polygon]))
        for t in world.tiles
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO world_tiles
               (id, lat, lon, cx, cy, cz, elevation, temperature, rainfall, biome, neighbors, polygon)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )
    biomes: dict[str, int] = {}
    for t in world.tiles:
        biomes[t.biome] = biomes.get(t.biome, 0) + 1
    return {
        "name": worldgen.WORLD_NAME, "seed": world.seed, "frequency": world.frequency,
        "tiles": len(world.tiles), "biomes": biomes,
    }


def read_map(conn) -> dict:
    meta = conn.execute(
        "SELECT name, seed, frequency, sea_level, generated_at FROM world_map WHERE id = 1"
    ).fetchone()
    if meta is None:
        raise DomainError(404, "World map not generated")
    tiles = conn.execute(
        """SELECT id, lat, lon, cx, cy, cz, elevation, temperature, rainfall,
                  biome, neighbors, polygon
           FROM world_tiles WHERE map_id = 1 ORDER BY id"""
    ).fetchall()
    return {
        "name": meta["name"], "seed": meta["seed"], "frequency": meta["frequency"],
        "sea_level": meta["sea_level"], "tile_count": len(tiles),
        "tiles": [
            {
                "id": t["id"], "lat": t["lat"], "lon": t["lon"],
                "center": [t["cx"], t["cy"], t["cz"]],
                "elevation": t["elevation"], "temperature": t["temperature"],
                "rainfall": t["rainfall"], "biome": t["biome"],
                "neighbors": t["neighbors"], "polygon": t["polygon"],
            }
            for t in tiles
        ],
    }
