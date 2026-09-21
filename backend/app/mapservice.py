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
import json

from psycopg.types.json import Jsonb

from app import worldgen
from app.service import DomainError

INSERT_CHUNK = 4000  # bound peak memory while writing tens of thousands of tiles



def _round(v, digits=4):
    # Four decimals on a unit sphere is ~1/250th of a tile at production frequency: far
    # under a pixel at any sane zoom, and it keeps the payload small enough for a phone.
    #
    # `+ 0.0` turns -0.0 into 0.0, which is not pedantry. Rounding a tiny negative coordinate
    # gives -0.0; it compares equal to 0.0, so no comparison notices, but it SERIALIZES as
    # "-0.0" and PostgreSQL hands it back as 0.0. The map built from the database and the map
    # built from the seed were therefore equal as data and different as bytes -- and corners
    # are pooled by exact value, so the two could also have pooled differently. Ten of these
    # appeared in a 1442-tile world.
    return [round(c, digits) + 0.0 for c in v]


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
    threshold = worldgen.river_min_flow(len(world.tiles))
    for t in world.tiles:
        biomes[t.biome] = biomes.get(t.biome, 0) + 1
        land += t.elevation >= 0 and t.biome not in worldgen.WATER_BIOMES
        rivers += t.river_flow >= threshold and t.elevation >= 0
    return {
        "name": worldgen.WORLD_NAME, "seed": world.seed, "frequency": world.frequency,
        "tiles": len(world.tiles), "land": land, "rivers": rivers, "biomes": biomes,
    }


def _river_columns(conn, tile_count: int) -> dict:
    """Rivers as ready-to-draw segments, in columns. The backend pairs each reach with the
    tile it drains into, so the client needs no adjacency and can build the ribbons directly.

    A lake tile is never the *source* of a reach. It sits at its water surface, so it passes
    the `elevation >= 0` test, and it carries every drop its basin collected, so it passes
    the flow test too -- which drew a river straight across the middle of the lake. A river
    still ends at the shore, because the reach whose downstream is the lake is kept.

    The threshold comes from the size of the map actually stored, not from a fixed number,
    because flow is counted in tiles: the same cut-off on a finer grid draws the ditches too.
    """
    rows = conn.execute(
        """SELECT up.cx AS ax, up.cy AS ay, up.cz AS az,
                  down.cx AS bx, down.cy AS by, down.cz AS bz,
                  up.river_flow AS flow, up.elevation AS up_elev, down.elevation AS down_elev
           FROM world_tiles up
           JOIN world_tiles down
             ON down.map_id = up.map_id AND down.id = up.downstream
           WHERE up.map_id = 1 AND up.elevation >= 0 AND up.biome <> 'lake'
                 AND up.river_flow >= %s
           ORDER BY up.id""",
        (worldgen.river_min_flow(tile_count),),
    ).fetchall()
    a: list[float] = []
    b: list[float] = []
    flow: list[int] = []
    ae: list[int] = []
    be: list[int] = []
    for r in rows:
        a += [r["ax"], r["ay"], r["az"]]
        b += [r["bx"], r["by"], r["bz"]]
        flow.append(r["flow"])
        ae.append(r["up_elev"])
        be.append(max(0, r["down_elev"]))
    return {"a": a, "b": b, "flow": flow, "ae": ae, "be": be}


def build_model(meta: dict, rows: list, total: int, rivers: dict) -> dict:
    """The render model, in columns -- the shape, with the source already chosen.

    Two things keep this affordable at production size. Every tile's polygon corner is a
    face centroid shared by three tiles, so the corners live in one pool and a tile only
    quotes indices into it. And the per-tile fields are columns rather than a list of
    objects: a JSON object per tile would spend more bytes repeating field names than on
    the geography itself. Together they cut the payload to a third of the naive encoding.

    Latitude and longitude are not sent: the client derives them from the centre vector.

    `rows` must already be the drawn subset, sorted by id: the database reaches it with SQL
    and a freshly generated world reaches it in Python, because those two run under very
    different constraints. What must not differ is the answer, and
    `test_mapexport.py` holds them to being identical.
    """
    biome_index = {name: i for i, name in enumerate(worldgen.BIOMES)}
    corner_index: dict[tuple[float, float, float], int] = {}
    corners: list[float] = []
    ids: list[int] = []
    center: list[float] = []
    elevation: list[int] = []
    temperature: list[float] = []
    rainfall: list[int] = []
    biome: list[int] = []
    river_flow: list[int] = []
    landmass_size: list[int] = []
    neighbor_count: list[int] = []
    coastal: list[int] = []
    ring: list[int] = []
    ring_offset: list[int] = [0]
    land_count = 0

    for row in rows:
        ids.append(row["id"])
        center += [row["cx"], row["cy"], row["cz"]]
        elevation.append(row["elevation"])
        temperature.append(row["temperature"])
        rainfall.append(row["rainfall"])
        biome.append(biome_index[row["biome"]])
        river_flow.append(row["river_flow"])
        landmass_size.append(row["landmass_size"])
        neighbor_count.append(row["neighbor_count"])
        coastal.append(1 if row["coastal"] else 0)
        if row["elevation"] >= 0 and row["biome"] != "lake":
            land_count += 1
        for point in row["polygon"]:
            key = (point[0], point[1], point[2])
            index = corner_index.get(key)
            if index is None:
                index = len(corner_index)
                corner_index[key] = index
                corners += point
            ring.append(index)
        ring_offset.append(len(ring))

    return {
        "name": meta["name"], "seed": meta["seed"], "frequency": meta["frequency"],
        "sea_level": meta["sea_level"], "tile_count": total, "land_count": land_count,
        # relief_gain and elevation_max used to travel with the map so the client's extrusion
        # matched the normals the server shaded against. Neither exists any more: the client
        # draws the ground flat and marks relief with a glyph, on absolute thresholds in
        # metres that it owns itself.
        "river_min_flow": worldgen.river_min_flow(total),
        "biome_names": list(worldgen.BIOMES),
        "corners": corners,
        "rivers": rivers,
        "tiles": {
            "id": ids, "center": center, "elevation": elevation,
            "temperature": temperature, "rainfall": rainfall, "biome": biome,
            "river_flow": river_flow, "landmass_size": landmass_size,
            "neighbor_count": neighbor_count, "coastal": coastal,
            "ring": ring, "ring_offset": ring_offset,
        },
    }


def read_map(conn) -> dict:
    """The render model, read from the authoritative database."""
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
    #
    # Deliberately three plain statements instead of one query with the shelf as a subquery:
    # at production size the planner turns `id IN (SELECT ...)` over 193k rows into something
    # that runs for minutes, while a sequential scan plus a primary-key lookup on an explicit
    # id array stays in the seconds and does not depend on how fresh the statistics are.
    shelf_ids = [
        row["id"] for row in conn.execute(
            """SELECT DISTINCT unnest(neighbors) AS id
               FROM world_tiles WHERE map_id = 1 AND elevation >= 0"""
        ).fetchall()
    ]
    # The terrain normals (nx, ny, nz) are deliberately not selected. They were computed for
    # the hillshade of an extruded terrain; the ground is one flat shell now, so nothing
    # reads them, and at three numbers per tile they were 13 per cent of the response (15 per
    # cent gzipped, which is what actually travels). They stay in the table: recomputing them
    # means regenerating the world, and the client could want them again.
    # `coastal` travels with the tile because the client has no adjacency -- the render model
    # sends a neighbour COUNT, not their ids -- and without it it cannot tell whether landing
    # there means having the sea beside you. It is a property of the neighbourhood, so either
    # it is sent or it is lost.
    select = """SELECT t.id, t.cx, t.cy, t.cz, t.elevation, t.temperature, t.rainfall,
                       t.biome, t.river_flow, t.landmass_size,
                       COALESCE(array_length(t.neighbors, 1), 0) AS neighbor_count, t.polygon,
                       EXISTS (SELECT 1 FROM world_tiles n
                               WHERE n.map_id = t.map_id AND n.id = ANY(t.neighbors)
                                 AND n.biome IN ('ocean', 'sea_ice')) AS coastal
                FROM world_tiles t WHERE t.map_id = 1 AND """
    rows = conn.execute(
        select + "(t.elevation >= 0 OR t.biome = 'sea_ice')"
    ).fetchall()
    rows += conn.execute(
        select + "t.elevation < 0 AND t.biome = 'ocean' AND t.id = ANY(%s)",
        (shelf_ids,),
    ).fetchall()
    rows.sort(key=lambda row: row["id"])

    return build_model(meta, rows, total, _river_columns(conn, total))
