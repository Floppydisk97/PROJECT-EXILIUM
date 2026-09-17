"""Persistence and read model for the authoritative planet map.

Generation is one-shot: the map is written once and then immutable (DB triggers enforce it).
The economic world (policy, ticks, ledger) is untouched here; this module only owns geography.

`read_map` is a RENDER model, not a dump of the table. It returns what the client actually
draws -- the land, the sea ice that forms the polar caps, the ring of shallow sea that gives
every coast its continental shelf, and the river network already resolved into segments --
plus a neighbour count instead of the full adjacency array. Open ocean beyond the shelf is a
smooth shell on the client, so its polygons would be dead weight. The table keeps the
complete geography either way.
"""
from psycopg.types.json import Jsonb

from app import worldgen
from app.service import DomainError

INSERT_CHUNK = 4000  # bound peak memory while writing tens of thousands of tiles


def _round(v, digits=4):
    # Four decimals on a unit sphere is ~1/250th of a tile at production frequency: far
    # under a pixel at any sane zoom, and it keeps the payload small enough for a phone.
    return [round(c, digits) for c in v]


def _tile_rows(world):
    for t in world.tiles:
        yield (
            t.id, t.lat, t.lon, *_round(t.center), t.elevation, t.temperature, t.rainfall,
            t.biome, list(t.neighbors), Jsonb([_round(p) for p in t.polygon]),
            *_round(t.normal, 4), t.river_flow, t.downstream, t.landmass_size,
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
        (id, lat, lon, cx, cy, cz, elevation, temperature, rainfall, biome, neighbors,
         polygon, nx, ny, nz, river_flow, downstream, landmass_size)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
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
    rivers = 0
    for t in world.tiles:
        biomes[t.biome] = biomes.get(t.biome, 0) + 1
        land += t.elevation >= 0 and t.biome not in worldgen.WATER_BIOMES
        rivers += t.river_flow >= worldgen.RIVER_MIN_FLOW and t.elevation >= 0
    return {
        "name": worldgen.WORLD_NAME, "seed": world.seed, "frequency": world.frequency,
        "tiles": len(world.tiles), "land": land, "rivers": rivers, "biomes": biomes,
    }


def _river_segments(conn) -> list[dict]:
    """Rivers as ready-to-draw segments: every tile carrying enough water, paired with the
    tile it drains into. Resolving the pairing here means the client needs no adjacency and
    can render the network as plain line segments, coast included."""
    rows = conn.execute(
        """SELECT up.cx AS ax, up.cy AS ay, up.cz AS az,
                  down.cx AS bx, down.cy AS by, down.cz AS bz,
                  up.river_flow AS flow, up.elevation AS up_elev, down.elevation AS down_elev
           FROM world_tiles up
           JOIN world_tiles down
             ON down.map_id = up.map_id AND down.id = up.downstream
           WHERE up.map_id = 1 AND up.elevation >= 0 AND up.river_flow >= %s
           ORDER BY up.id""",
        (worldgen.RIVER_MIN_FLOW,),
    ).fetchall()
    return [
        {
            "a": [r["ax"], r["ay"], r["az"]], "b": [r["bx"], r["by"], r["bz"]],
            "flow": r["flow"], "ae": r["up_elev"], "be": max(0, r["down_elev"]),
        }
        for r in rows
    ]


def read_map(conn) -> dict:
    meta = conn.execute(
        "SELECT name, seed, frequency, sea_level, generated_at FROM world_map WHERE id = 1"
    ).fetchone()
    if meta is None:
        raise DomainError(404, "World map not generated")
    total = int(conn.execute(
        "SELECT count(*) AS n FROM world_tiles WHERE map_id = 1"
    ).fetchone()["n"])
    # Land, the sea ice that makes the polar caps read as caps rather than open water, and
    # one ring of sea around every coast: shaded by its real depth, that ring is the shelf
    # that stops continents looking like plates dropped on flat blue.
    tiles = conn.execute(
        """WITH shelf AS (
               SELECT DISTINCT unnest(neighbors) AS id
               FROM world_tiles WHERE map_id = 1 AND elevation >= 0
           )
           SELECT t.id, t.lat, t.lon, t.cx, t.cy, t.cz, t.elevation, t.temperature,
                  t.rainfall, t.biome, t.nx, t.ny, t.nz, t.river_flow, t.landmass_size,
                  COALESCE(array_length(t.neighbors, 1), 0) AS neighbor_count, t.polygon
           FROM world_tiles t
           WHERE t.map_id = 1
             AND (t.elevation >= 0 OR t.biome = 'sea_ice'
                  OR t.id IN (SELECT id FROM shelf))
           ORDER BY t.id"""
    ).fetchall()
    land_count = sum(1 for t in tiles if t["elevation"] >= 0 and t["biome"] != "lake")
    return {
        "name": meta["name"], "seed": meta["seed"], "frequency": meta["frequency"],
        "sea_level": meta["sea_level"], "tile_count": total, "land_count": land_count,
        # Shared with worldgen so the client's relief matches the normals computed there.
        "elevation_max": worldgen.ELEVATION_MAX, "relief_gain": worldgen.RELIEF_GAIN,
        "rivers": _river_segments(conn),
        "tiles": [
            {
                "id": t["id"], "lat": t["lat"], "lon": t["lon"],
                "center": [t["cx"], t["cy"], t["cz"]],
                "normal": [t["nx"], t["ny"], t["nz"]],
                "elevation": t["elevation"], "temperature": t["temperature"],
                "rainfall": t["rainfall"], "biome": t["biome"],
                "river_flow": t["river_flow"], "landmass_size": t["landmass_size"],
                "neighbor_count": t["neighbor_count"], "polygon": t["polygon"],
            }
            for t in tiles
        ],
    }
