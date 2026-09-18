"""Deterministic, seed-based world generation for the single planet 'Hesperia'.

Authoritative and server-side: the client never generates terrain, it only renders
what this module produced and the API persisted. The planet is a geodesic sphere
(a subdivided icosahedron); every original vertex is one hexagonal tile, with exactly
twelve pentagons at the icosahedron's corners, so the render reads like RimWorld's globe.

Generator v3 builds a world with recognisable landforms rather than noise blobs:

* mountains  -- ridged noise gathered into belts, so ranges run in chains with alpine
                rock and snow caps on top, not isolated bumps;
* rivers     -- real downhill flow accumulation over the tile graph; every land tile
                knows its downstream tile, and closed basins with enough water are lakes;
* coasts     -- the continental field is sampled through a domain warp, so outlines are
                irregular instead of round, and a second pass of detail that bites only
                near the waterline cuts the gulfs, straits and offshore islets;
* islands    -- ridged high-frequency noise gated by a slow mask, so islands arrive in
                arcs and chains rather than as lone specks; connected components give
                every tile the size of its landmass;
* deserts    -- a latitude rainfall profile with subtropical dry belts, plus
                continentality (distance from the sea) and orographic rain shadow behind
                the ranges. The dry belt is a belt, not a trench: deserts are meant to be
                a feature of continental interiors and rain shadows, not the default
                colour of the subtropics;
* poles      -- colder poles, so ice sheets and sea ice form real caps.

Generation uses floats and a seeded PRNG. It runs once and its result is persisted, so
cross-platform float reproducibility is not required; a given (seed, frequency) is stable
within one interpreter, which the tests assert. No economic value is float-based here.
"""
from __future__ import annotations

import hashlib
import math
import random
from collections import deque
from dataclasses import dataclass

WORLD_NAME = "Hesperia"
GENERATOR_VERSION = 3

# Production size. Sea level sits at SEA_PERCENTILE, so ~24% of tiles are land; one player
# settles one land tile. f=139 -> 193212 tiles, ~46000 land: nine times the 5000-player
# target, and fine enough that a coastline reads as a coastline up close.
# Generation measures ~10 s and ~328 MB peak, which is what sets the ceiling here: the whole
# sphere is built in memory at once, so a small instance cannot go much past this.
PRODUCTION_FREQUENCY = 139
MIN_PLAYER_CAPACITY = 5000

# Relief exaggeration, shared with the client so terrain normals computed here match the
# geometry drawn there: rendered radius = 1 + clamp(elevation, 0, ELEVATION_MAX)/ELEVATION_MAX
# * RELIEF_GAIN. Served in the map metadata so the two never drift apart.
ELEVATION_MAX = 7000
RELIEF_GAIN = 0.075

# A tile carries this much water before it counts as a river; a closed basin holding this
# much is a lake. Units are "tiles' worth of rainfall", from the flow accumulation below.
RIVER_MIN_FLOW = 20
LAKE_MIN_FLOW = 26

# Coastline shape. The continental field is a sum of sinusoids, which on its own draws
# round blobs however many octaves it gets. Sampling it at a point displaced by a second
# noise field -- domain warping -- is what gives peninsulas, bays and an outline that does
# not look like it was drawn with a compass.
WARP_STRENGTH = 0.28

# Detail that fades out with distance from the waterline, as a fraction of the elevation
# span. Applied everywhere it would punch lakes into continental interiors and speckle the
# deep ocean; applied only at the coast it is exactly what cuts gulfs and straits and
# leaves islets just offshore. The amplitude is deliberately larger than the band, so the
# coast really moves instead of being merely roughened.
COAST_DETAIL = 0.15
COAST_BAND = 0.10

# Island arcs: ridged high-frequency noise, allowed only where a slow mask is high. Ridges
# are lines, so the islands come out in chains the way volcanic arcs do; a plain octave of
# noise gives isolated dots instead.
ARC_STRENGTH = 0.66
ARC_BIAS = 0.34
SPECKLE_STRENGTH = 0.18

# Ocean basins. Ridged noise -- high along lines, near zero away from them -- subtracted
# from the land. Where a line crosses a neck of land it leaves a strait, where it reaches a
# coast and stops it leaves a gulf, and where two of them meet it leaves an inland sea.
# This is the only thing here that changes what is connected to what: warping an outline
# makes it irregular but leaves the same landmass behind it, and raising the continental
# frequency makes things worse rather than better, because more land near the waterline
# percolates more readily, not less. Measured at f=48, seed Hesperia-01, this takes the
# largest landmass from 75% of all land down to 40%, leaving three continents.
RIFT_STRENGTH = 0.85
RIFT_FREQUENCY = 3.8
RIFT_SHARPNESS = 2

# The base frequency of the continental field. Swept from 2.2 to 4.6: higher values gave a
# *single* mass holding 88-99% of the land, so this stays where it is.
CONTINENT_FREQUENCY = 2.2

# Fraction of the planet under water. Fixes how much land exists, never how it is connected.
# At f=139 this leaves ~46000 land tiles, nine times the 5000-player target.
SEA_PERCENTILE = 0.76

# Biome ids are stable identifiers; the frontend maps them to colours and labels.
BIOMES = (
    "ocean", "lake", "sea_ice", "ice_sheet", "snow_cap", "bare_rock", "tundra",
    "boreal_forest", "temperate_forest", "temperate_swamp", "arid_shrubland", "desert",
    "tropical_rainforest", "tropical_swamp",
)

# Biomes that are water: no colony settles there even though a lake sits above sea level.
WATER_BIOMES = frozenset({"ocean", "lake", "sea_ice"})


@dataclass(frozen=True)
class Tile:
    id: int
    lat: float          # degrees, [-90, 90]
    lon: float          # degrees, (-180, 180]
    center: tuple[float, float, float]   # unit vector
    elevation: int      # metres relative to sea level (negative = underwater)
    temperature: float  # average °C, one decimal
    rainfall: int       # mm/year
    biome: str
    neighbors: tuple[int, ...]
    polygon: tuple[tuple[float, float, float], ...]  # dual-cell ring on the unit sphere
    normal: tuple[float, float, float]   # terrain normal in render space (relief shading)
    river_flow: int     # accumulated upstream water; 0 on ocean tiles
    downstream: int     # tile the water leaves to, or -1 for ocean tiles and closed basins
    landmass_size: int  # tiles in this tile's connected landmass; 0 on ocean


@dataclass(frozen=True)
class World:
    seed: str
    frequency: int
    sea_level: float
    tiles: tuple[Tile, ...]


def _seed_int(seed: str, salt: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{salt}".encode()).digest()[:8], "big")


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z)
    return (x / length, y / length, z / length)


def _icosahedron() -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    t = (1.0 + math.sqrt(5.0)) / 2.0
    raw = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]
    verts = [_normalize(v) for v in raw]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    return verts, faces


def _subdivide(frequency: int):
    """Geodesic subdivision: each icosahedron face becomes frequency^2 small triangles.
    Returns unit-sphere vertices and the small-triangle faces indexing them."""
    base_verts, base_faces = _icosahedron()
    verts: list[tuple[float, float, float]] = []
    index: dict[tuple[int, int, int], int] = {}

    def add(v: tuple[float, float, float]) -> int:
        v = _normalize(v)
        key = (round(v[0], 9), round(v[1], 9), round(v[2], 9))
        existing = index.get(key)
        if existing is not None:
            return existing
        index[key] = len(verts)
        verts.append(v)
        return len(verts) - 1

    faces: list[tuple[int, int, int]] = []
    for a, b, c in base_faces:
        va, vb, vc = base_verts[a], base_verts[b], base_verts[c]
        # Barycentric grid of points across the triangle, projected to the sphere.
        grid: list[list[int]] = []
        for i in range(frequency + 1):
            row: list[int] = []
            for j in range(frequency - i + 1):
                k = frequency - i - j
                point = tuple(
                    (i * va[d] + j * vb[d] + k * vc[d]) / frequency for d in range(3)
                )
                row.append(add(point))  # type: ignore[arg-type]
            grid.append(row)
        for i in range(frequency):
            for j in range(frequency - i):
                faces.append((grid[i][j], grid[i + 1][j], grid[i][j + 1]))
                if j < frequency - i - 1:
                    faces.append((grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
    return verts, faces


def _tangent_basis(normal):
    ref = (0.0, 0.0, 1.0) if abs(normal[2]) < 0.9 else (1.0, 0.0, 0.0)
    u_axis = _normalize(_cross(normal, ref))
    return u_axis, _cross(normal, u_axis)


def _dual_cells(verts, faces):
    """For each vertex build its Goldberg dual cell: the ring of incident-face centroids,
    ordered around the vertex normal. Also return vertex adjacency (tile neighbours),
    ordered the same way so the terrain normal can walk the ring."""
    incident: list[list[int]] = [[] for _ in verts]
    adjacency: list[set[int]] = [set() for _ in verts]
    centroids: list[tuple[float, float, float]] = []
    for fi, (a, b, c) in enumerate(faces):
        centroids.append(_normalize((
            verts[a][0] + verts[b][0] + verts[c][0],
            verts[a][1] + verts[b][1] + verts[c][1],
            verts[a][2] + verts[b][2] + verts[c][2],
        )))
        for u in (a, b, c):
            incident[u].append(fi)
        adjacency[a].update((b, c))
        adjacency[b].update((a, c))
        adjacency[c].update((a, b))

    polygons: list[tuple[tuple[float, float, float], ...]] = []
    ordered_neighbors: list[tuple[int, ...]] = []
    for vi in range(len(verts)):
        faces_here = incident[vi]
        normal = verts[vi]
        u_axis, v_axis = _tangent_basis(normal)

        def angle_of(point) -> float:
            return math.atan2(_dot(point, v_axis), _dot(point, u_axis))

        polygons.append(tuple(
            centroids[fi] for fi in sorted(faces_here, key=lambda fi: angle_of(centroids[fi]))
        ))
        ordered_neighbors.append(tuple(
            sorted(adjacency[vi], key=lambda nb: angle_of(verts[nb]))
        ))
        # Release each vertex's scratch as soon as its cell is built. At production size the
        # incidence lists and adjacency sets are tens of megabytes, and holding all of them
        # to the end is what pushes a small instance towards its memory limit.
        incident[vi] = ()
        adjacency[vi] = frozenset()
    return polygons, ordered_neighbors


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _rotate_z(v, angle):
    """Rotate around the polar axis: +angle moves the point east (increasing longitude)."""
    c, s = math.cos(angle), math.sin(angle)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2])


class _BandNoise:
    """Smooth band-limited noise on the unit sphere: a sum of directional sinusoids with
    seeded random directions, frequencies and phases. Cheap, continuous and deterministic."""

    def __init__(self, rng: random.Random, octaves: int, base_freq: float):
        self.terms = []
        amp = 1.0
        freq = base_freq
        total = 0.0
        for _ in range(octaves):
            direction = _normalize((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
            phase = rng.uniform(0, 2 * math.pi)
            self.terms.append((direction, freq, phase, amp))
            total += amp
            amp *= 0.55
            freq *= 1.9
        self.total = total

    def at(self, p: tuple[float, float, float]) -> float:
        value = 0.0
        for direction, freq, phase, amp in self.terms:
            value += amp * math.sin(freq * _dot(direction, p) + phase)
        return value / self.total  # roughly [-1, 1]


def _domain_warp(fields, p, amount: float):
    """Displace a sample point by a vector noise field. The continental field then reads
    its own smooth shape through a distorted lens, which is what turns round blobs into
    coastlines with peninsulas and bays."""
    wx, wy, wz = fields
    return _normalize((p[0] + amount * wx.at(p),
                       p[1] + amount * wy.at(p),
                       p[2] + amount * wz.at(p)))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(fraction * len(ordered))))
    return ordered[idx]


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _rain_profile(lat: float) -> float:
    """Zonal rainfall: a wet equator (the ITCZ), drier subtropics around 25° where the big
    deserts sit, wet mid-latitude storm tracks around 52°, and dry poles. The two wet bands
    are wide enough to overlap in the subtropics and the floor is well above zero, so the
    dry belt is a belt and not a trench: a subtropical coast comes out as shrubland, and
    only a continental interior or the lee of a range goes all the way to desert."""
    a = abs(lat)
    itcz = math.exp(-((a / 15.0) ** 2))
    storm_track = math.exp(-(((a - 52.0) / 18.0) ** 2))
    return 2400.0 * itcz + 1500.0 * storm_track + 230.0


def _upwind_angle(lat: float) -> float:
    """Prevailing winds: tropical easterlies below 30°, westerlies above. The returned
    rotation points upwind, so sampling there says what the air crossed before arriving."""
    return 0.11 if abs(lat) < 30.0 else -0.11


def _mountain_field(ridge_noise, belt_noise, p) -> float:
    """Ridged noise gathered into belts: creases (1 - |noise|) sharpened into chains, and
    allowed only where a slow 'belt' field is high, so ranges run in lines like real orogeny."""
    ridge = 1.0 - abs(ridge_noise.at(p))
    belt = _smoothstep(0.22, 0.70, belt_noise.at(p) * 0.5 + 0.5)
    return (ridge ** 3) * belt


def _biome(elevation, temperature, rainfall, is_lake) -> str:
    if elevation < 0:
        return "sea_ice" if temperature < -4 else "ocean"
    if is_lake:
        return "lake"
    # High ground reads as mountain before climate does: rock, and snow where it is cold.
    if elevation >= 5000 or (elevation >= 3900 and temperature < -4):
        return "snow_cap"
    if elevation >= 2500:
        return "bare_rock"
    if temperature < -16:
        return "ice_sheet"
    if temperature < -6:
        return "tundra"
    if temperature < 4:
        return "boreal_forest"
    if temperature < 20:
        if rainfall < 600:
            return "arid_shrubland" if rainfall > 250 else "desert"
        return "temperate_swamp" if rainfall > 2200 else "temperate_forest"
    # Hot.
    if rainfall < 300:
        return "desert"
    if rainfall < 700:
        return "arid_shrubland"
    return "tropical_swamp" if rainfall > 2600 else "tropical_rainforest"


def _distance_to_ocean(elevations, neighbors) -> list[int]:
    """Breadth-first hop count from the sea over the land graph. Feeds continentality:
    the deep interior of a continent gets far less rain than its coast."""
    distance = [0 if e < 0 else -1 for e in elevations]
    frontier = deque(i for i, e in enumerate(elevations) if e < 0)
    while frontier:
        i = frontier.popleft()
        for nb in neighbors[i]:
            if distance[nb] == -1:
                distance[nb] = distance[i] + 1
                frontier.append(nb)
    # An all-land world would leave -1 values; clamp so callers never see the sentinel.
    return [d if d >= 0 else 40 for d in distance]


def _landmass_sizes(elevations, neighbors) -> list[int]:
    """Connected components over land adjacency, so a tile knows whether it belongs to a
    continent or to a three-tile island."""
    sizes = [0] * len(elevations)
    seen = [False] * len(elevations)
    for start in range(len(elevations)):
        if seen[start] or elevations[start] < 0:
            continue
        component: list[int] = []
        seen[start] = True
        frontier = deque([start])
        while frontier:
            i = frontier.popleft()
            component.append(i)
            for nb in neighbors[i]:
                if not seen[nb] and elevations[nb] >= 0:
                    seen[nb] = True
                    frontier.append(nb)
        for i in component:
            sizes[i] = len(component)
    return sizes


def _river_network(elevations, neighbors, rainfall):
    """Downhill flow accumulation. Each land tile drains to its lowest neighbour; walking
    the tiles from high to low is a valid topological order, so one pass accumulates every
    upstream contribution. Tiles with no lower neighbour are closed basins (lake candidates).
    """
    count = len(elevations)
    downstream = [-1] * count
    land = [i for i in range(count) if elevations[i] >= 0]
    for i in land:
        best, best_elev = -1, elevations[i]
        for nb in neighbors[i]:
            # Strictly lower only: no equal-height step, so the drainage graph stays acyclic.
            if elevations[nb] < best_elev:
                best, best_elev = nb, elevations[nb]
        downstream[i] = best

    # Rain falling on a tile, in "tile-equivalents": a soaking tile contributes several.
    flow = [0.0] * count
    for i in land:
        flow[i] = max(0.25, rainfall[i] / 900.0)
    for i in sorted(land, key=lambda t: elevations[t], reverse=True):
        target = downstream[i]
        if target != -1 and elevations[target] >= 0:
            flow[target] += flow[i]
    return [int(flow[i]) for i in range(count)], downstream


def _terrain_normals(centers, elevations, neighbors):
    """Geometric normal of the rendered relief: the tile's raised centre against the ring of
    its raised neighbours. The client shades with these, so mountain ranges catch the light
    instead of looking painted on. Uses the same exaggeration the client renders with."""
    def raised(i):
        h = min(max(elevations[i], 0), ELEVATION_MAX) / ELEVATION_MAX * RELIEF_GAIN
        c = centers[i]
        r = 1.0 + h
        return (c[0] * r, c[1] * r, c[2] * r)

    normals: list[tuple[float, float, float]] = []
    for i, center in enumerate(centers):
        if elevations[i] < 0:
            normals.append(center)  # flat sea: the sphere's own normal
            continue
        p = raised(i)
        ring = neighbors[i]
        acc = [0.0, 0.0, 0.0]
        for k in range(len(ring)):
            a = raised(ring[k])
            b = raised(ring[(k + 1) % len(ring)])
            n = _cross((a[0] - p[0], a[1] - p[1], a[2] - p[2]),
                       (b[0] - p[0], b[1] - p[1], b[2] - p[2]))
            acc[0] += n[0]; acc[1] += n[1]; acc[2] += n[2]
        length = math.sqrt(acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2)
        if length < 1e-12 or _dot(acc, center) < 0:
            normals.append(center)  # degenerate ring: fall back to radial
        else:
            normals.append((acc[0] / length, acc[1] / length, acc[2] / length))
    return normals


def generate(seed: str, frequency: int = 12) -> World:
    if not 2 <= frequency <= 160:
        raise ValueError("frequency must be between 2 and 160")
    if not seed.strip():
        raise ValueError("seed must be non-empty")

    verts, faces = _subdivide(frequency)
    polygons, neighbors = _dual_cells(verts, faces)
    del faces  # the dual cells carry everything the rest of the pipeline needs

    elev_rng = random.Random(_seed_int(seed, "elevation"))
    temp_rng = random.Random(_seed_int(seed, "temperature"))
    rain_rng = random.Random(_seed_int(seed, "rainfall"))
    ridge_rng = random.Random(_seed_int(seed, "mountains"))
    belt_rng = random.Random(_seed_int(seed, "belts"))
    isle_rng = random.Random(_seed_int(seed, "islands"))
    shape_rng = random.Random(_seed_int(seed, "coastline"))
    arc_rng = random.Random(_seed_int(seed, "arcs"))

    continents = _BandNoise(elev_rng, octaves=6, base_freq=CONTINENT_FREQUENCY)
    warp_noise = _BandNoise(temp_rng, octaves=3, base_freq=2.2)
    rain_noise = _BandNoise(rain_rng, octaves=5, base_freq=2.6)
    ridge_noise = _BandNoise(ridge_rng, octaves=4, base_freq=3.1)
    belt_noise = _BandNoise(belt_rng, octaves=3, base_freq=1.7)
    island_noise = _BandNoise(isle_rng, octaves=3, base_freq=13.0)
    # Three independent fields drawn from one generator: the displacement vector.
    coast_warp = tuple(_BandNoise(shape_rng, octaves=3, base_freq=3.4) for _ in range(3))
    coast_noise = _BandNoise(shape_rng, octaves=3, base_freq=8.0)
    arc_noise = _BandNoise(arc_rng, octaves=3, base_freq=17.0)
    arc_mask = _BandNoise(arc_rng, octaves=2, base_freq=2.5)
    rift_noise = _BandNoise(shape_rng, octaves=3, base_freq=RIFT_FREQUENCY)

    # Pass one: the continents, read through the domain warp so their outline is irregular,
    # plus arcs of islands out in open water and a light speckle that breaks up the coasts.
    base_elev = []
    for v in verts:
        arc = _smoothstep(0.50, 0.90, arc_mask.at(v) * 0.5 + 0.5)
        chain = (1.0 - abs(arc_noise.at(v))) ** 3
        rift = (1.0 - abs(rift_noise.at(v))) ** RIFT_SHARPNESS
        base_elev.append(
            continents.at(_domain_warp(coast_warp, v, WARP_STRENGTH))
            + SPECKLE_STRENGTH * island_noise.at(v)
            + ARC_STRENGTH * arc * (chain - ARC_BIAS)
            - RIFT_STRENGTH * rift
        )

    # Pass two: detail that bites only near the waterline. It needs a waterline to measure
    # against, hence the provisional one here; the real sea level is taken again afterwards
    # so the land fraction -- and with it the player capacity -- is unchanged by the detail.
    waterline = _percentile(base_elev, SEA_PERCENTILE)
    reach = COAST_BAND * max(1e-6, 1.0 - waterline)
    amplitude = COAST_DETAIL * max(1e-6, 1.0 - waterline)
    raw_elev = [
        e + amplitude * math.exp(-(((e - waterline) / reach) ** 2)) * coast_noise.at(v)
        for e, v in zip(base_elev, verts)
    ]
    sea_level = _percentile(raw_elev, SEA_PERCENTILE)
    span = max(1e-6, 1.0 - sea_level)

    mountains = [_mountain_field(ridge_noise, belt_noise, v) for v in verts]

    elevations: list[int] = []
    for i, v in enumerate(verts):
        e = raw_elev[i] - sea_level
        if e < 0:
            elevations.append(int(round(e * 6000 / span)))
            continue
        base = e * 2600 / span
        # Ranges rise inland; right at the shoreline they taper off into coastal hills.
        inland = _smoothstep(0.0, 0.18 * span, e)
        elevations.append(int(round(base + 6200 * mountains[i] * inland)))

    ocean_distance = _distance_to_ocean(elevations, neighbors)
    landmass = _landmass_sizes(elevations, neighbors)

    temperatures: list[float] = []
    rainfalls: list[int] = []
    for i, v in enumerate(verts):
        lat = math.degrees(math.asin(max(-1.0, min(1.0, v[2]))))
        elevation = elevations[i]

        lat_factor = math.cos(math.radians(lat))
        base_temp = -36 + 66 * lat_factor            # ~30°C equator, ~-36°C poles
        lapse = 0.0058 * max(0, elevation)            # cooler with altitude
        temperatures.append(round(base_temp - lapse + 6 * warp_noise.at(v), 1))

        rain = _rain_profile(lat)
        # Continentality: rain is wrung out on the way inland, but weighted by how dry the
        # latitude already is. A flat continentality dries the whole planet evenly, which
        # turns every wide landmass arid and still leaves no real desert anywhere; weighting
        # it puts the drying where deserts actually come from -- the interior of a
        # subtropical continent -- and leaves an equatorial or mid-latitude interior wet.
        dryness = _smoothstep(1500.0, 550.0, rain)
        inland = 1.0 - math.exp(-ocean_distance[i] / 13.0)
        rain *= 1.0 - (0.22 + 0.70 * dryness) * inland
        # Orographic effect: compare the range upwind with the ground here. Downwind of a
        # high chain the air is already dry (rain shadow); climbing into it, it dumps rain.
        upwind = _mountain_field(ridge_noise, belt_noise, _rotate_z(v, _upwind_angle(lat)))
        relief = upwind - mountains[i]
        if relief > 0:
            rain *= 1.0 - min(0.66, relief * 2.2)     # in the lee: dry, and sometimes desert
        else:
            rain *= 1.0 + min(0.6, -relief * 1.8)     # windward slope: soaked
        # Narrower than before on the dry side: a desert should be the work of the three
        # mechanisms above agreeing, not of the noise alone rolling low.
        rain *= 0.70 + 0.58 * (rain_noise.at(v) * 0.5 + 0.5)
        if elevation < 0:
            rain = max(rain, 900)
        rainfalls.append(max(0, int(round(rain))))

    river_flow, downstream = _river_network(elevations, neighbors, rainfalls)
    normals = _terrain_normals(verts, elevations, neighbors)

    tiles: list[Tile] = []
    for i, v in enumerate(verts):
        lat = math.degrees(math.asin(max(-1.0, min(1.0, v[2]))))
        lon = math.degrees(math.atan2(v[1], v[0]))
        # A closed basin that collects real water is a lake, not dry ground.
        is_lake = (elevations[i] >= 0 and downstream[i] == -1
                   and river_flow[i] >= LAKE_MIN_FLOW)
        tiles.append(Tile(
            id=i, lat=round(lat, 4), lon=round(lon, 4), center=v,
            elevation=elevations[i], temperature=temperatures[i], rainfall=rainfalls[i],
            biome=_biome(elevations[i], temperatures[i], rainfalls[i], is_lake),
            neighbors=tuple(sorted(neighbors[i])), polygon=polygons[i],
            normal=normals[i], river_flow=river_flow[i], downstream=downstream[i],
            landmass_size=landmass[i],
        ))

    return World(seed=seed, frequency=frequency, sea_level=sea_level, tiles=tuple(tiles))
