"""Deterministic, seed-based world generation for the single planet 'Hesperia'.

Authoritative and server-side: the client never generates terrain, it only renders
what this module produced and the API persisted. The planet is a geodesic sphere
(a subdivided icosahedron); every original vertex is one hexagonal tile, with exactly
twelve pentagons at the icosahedron's corners, so the render reads like RimWorld's globe.

Generation uses floats and a seeded PRNG. It runs once and its result is persisted, so
cross-platform float reproducibility is not required; a given (seed, frequency) is stable
within one interpreter, which the tests assert. No economic value is float-based here.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass

WORLD_NAME = "Hesperia"
GENERATOR_VERSION = 1

# Biome ids are stable identifiers; the frontend maps them to colours and labels.
BIOMES = (
    "ocean", "sea_ice", "ice_sheet", "tundra", "boreal_forest",
    "temperate_forest", "temperate_swamp", "arid_shrubland", "desert",
    "tropical_rainforest", "tropical_swamp",
)


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


def _dual_cells(verts, faces):
    """For each vertex build its Goldberg dual cell: the ring of incident-face centroids,
    ordered around the vertex normal. Also return vertex adjacency (tile neighbours)."""
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
    for vi, faces_here in enumerate(incident):
        normal = verts[vi]
        # Build an orthonormal tangent basis to sort centroids by angle around the vertex.
        ref = (0.0, 0.0, 1.0) if abs(normal[2]) < 0.9 else (1.0, 0.0, 0.0)
        u_axis = _normalize(_cross(normal, ref))
        v_axis = _cross(normal, u_axis)
        ordered = sorted(
            faces_here,
            key=lambda fi: math.atan2(_dot(centroids[fi], v_axis), _dot(centroids[fi], u_axis)),
        )
        polygons.append(tuple(centroids[fi] for fi in ordered))
    return polygons, [tuple(sorted(a)) for a in adjacency]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


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


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(fraction * len(ordered))))
    return ordered[idx]


def _biome(elevation: int, temperature: float, rainfall: int, lat: float) -> str:
    if elevation < 0:
        return "sea_ice" if temperature < -5 else "ocean"
    if temperature < -18:
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


def generate(seed: str, frequency: int = 12) -> World:
    if not 2 <= frequency <= 48:
        raise ValueError("frequency must be between 2 and 48")
    if not seed.strip():
        raise ValueError("seed must be non-empty")

    verts, faces = _subdivide(frequency)
    polygons, adjacency = _dual_cells(verts, faces)

    elev_rng = random.Random(_seed_int(seed, "elevation"))
    temp_rng = random.Random(_seed_int(seed, "temperature"))
    rain_rng = random.Random(_seed_int(seed, "rainfall"))
    elevation_noise = _BandNoise(elev_rng, octaves=6, base_freq=1.4)
    warp_noise = _BandNoise(temp_rng, octaves=3, base_freq=2.2)
    rain_noise = _BandNoise(rain_rng, octaves=5, base_freq=2.6)

    raw_elev = [elevation_noise.at(v) for v in verts]
    # ~62% ocean, like a water world; sea level is the corresponding elevation percentile.
    sea_level = _percentile(raw_elev, 0.62)

    tiles: list[Tile] = []
    for i, v in enumerate(verts):
        lat = math.degrees(math.asin(max(-1.0, min(1.0, v[2]))))
        lon = math.degrees(math.atan2(v[1], v[0]))
        e = raw_elev[i] - sea_level
        # Land rises up to ~4500 m; ocean basins down to ~-6000 m.
        elevation = int(round(e * (4500 if e >= 0 else 6000) / max(1e-6, 1 - sea_level)))

        lat_factor = math.cos(math.radians(lat))
        base_temp = -32 + 62 * lat_factor            # ~30°C equator, ~-32°C poles
        lapse = 0.0055 * max(0, elevation)            # cooler with altitude
        temperature = round(base_temp - lapse + 6 * warp_noise.at(v), 1)

        # Wet equator and temperate bands, dry subtropics and poles, plus noise.
        band = 0.5 + 0.5 * math.cos(math.radians(lat * 3.4))
        rainfall = max(0, int(round(1400 * band + 1300 * (rain_noise.at(v) * 0.5 + 0.5) - 300)))
        if elevation < 0:
            rainfall = max(rainfall, 900)

        biome = _biome(elevation, temperature, rainfall, lat)
        tiles.append(Tile(
            id=i, lat=round(lat, 4), lon=round(lon, 4), center=v,
            elevation=elevation, temperature=temperature, rainfall=rainfall,
            biome=biome, neighbors=adjacency[i], polygon=polygons[i],
        ))

    return World(seed=seed, frequency=frequency, sea_level=sea_level, tiles=tuple(tiles))
