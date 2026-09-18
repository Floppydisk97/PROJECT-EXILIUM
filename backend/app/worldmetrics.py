"""Geometry-aware measurements for deterministic Hesperia generations."""
from __future__ import annotations

import cmath
import math
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.worldgen import World

CONTINENT_MIN_LAND_SHARE = 0.005
COMPACTNESS_MIN_AREA = 200

# Land a colony could actually use. Standing water is not land to settle, and neither is
# permanent ice or a bare mountainside -- so "24% land" overstates what the player is
# offered. This is the number a design decision about world size should be read against.
UNUSABLE_BIOMES = frozenset({"lake", "ice_sheet", "bare_rock", "snow_cap"})
DIRECTION_BINS = 18


@dataclass(frozen=True)
class MassMetrics:
    area: int
    perimeter: int
    perimeter_per_area: float
    perimeter_per_sqrt_area: float


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _normalize(v):
    length = math.sqrt(_dot(v, v))
    return tuple(x / length for x in v)


def _components(world: World) -> list[list[int]]:
    land = [tile.elevation >= 0 for tile in world.tiles]
    seen = bytearray(len(world.tiles))
    result: list[list[int]] = []
    for start, is_land in enumerate(land):
        if not is_land or seen[start]:
            continue
        seen[start] = 1
        component: list[int] = []
        queue = deque([start])
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in world.tiles[current].neighbors:
                if land[neighbor] and not seen[neighbor]:
                    seen[neighbor] = 1
                    queue.append(neighbor)
        result.append(component)
    return result


def _coast_direction_spectrum(world: World) -> dict:
    """Measure coast bearings on each edge's local tangent plane.

    A coast edge joins a land centre to a water centre. Its midpoint is normalized back
    onto the sphere; the edge direction is projected into that midpoint's tangent plane.
    Bearings are axial (0 and 180 degrees are the same coastline orientation), relative to
    local geographic north/east, and weighted by the edge's great-circle length.
    """
    bins = [0.0] * DIRECTION_BINS
    moments = {order: 0j for order in (2, 4, 6, 8)}
    total_weight = 0.0
    north_pole = (0.0, 0.0, 1.0)
    for tile in world.tiles:
        if tile.elevation < 0:
            continue
        for neighbor_id in tile.neighbors:
            neighbor = world.tiles[neighbor_id]
            if neighbor.elevation >= 0:
                continue
            a, b = tile.center, neighbor.center
            midpoint = _normalize((a[0] + b[0], a[1] + b[1], a[2] + b[2]))
            tangent_raw = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            radial = _dot(tangent_raw, midpoint)
            tangent = _normalize(tuple(tangent_raw[i] - radial * midpoint[i] for i in range(3)))
            east_raw = _cross(north_pole, midpoint)
            if _dot(east_raw, east_raw) < 1e-18:
                east_raw = _cross((1.0, 0.0, 0.0), midpoint)
            east = _normalize(east_raw)
            north = _normalize(_cross(midpoint, east))
            angle = math.atan2(_dot(tangent, east), _dot(tangent, north)) % math.pi
            weight = math.acos(max(-1.0, min(1.0, _dot(a, b))))
            bins[min(DIRECTION_BINS - 1, int(angle / math.pi * DIRECTION_BINS))] += weight
            for order in moments:
                moments[order] += weight * cmath.exp(1j * order * angle)
            total_weight += weight
    shares = [value / total_weight if total_weight else 0.0 for value in bins]
    return {
        "frame": "local tangent bearing from geographic north; axial [0,180)",
        "bin_width_degrees": 180 / DIRECTION_BINS,
        "bin_shares": [round(value, 6) for value in shares],
        "harmonic_magnitudes": {
            str(order): round(abs(value) / total_weight if total_weight else 0.0, 6)
            for order, value in moments.items()
        },
        "peak_to_mean": round(max(shares) * DIRECTION_BINS if shares else 0.0, 6),
    }


def measure(world: World) -> dict:
    components = _components(world)
    land_count = sum(map(len, components))
    masses: list[MassMetrics] = []
    for component in components:
        perimeter = sum(
            1 for tile_id in component for neighbor in world.tiles[tile_id].neighbors
            if world.tiles[neighbor].elevation < 0
        )
        area = len(component)
        masses.append(MassMetrics(
            area=area,
            perimeter=perimeter,
            perimeter_per_area=perimeter / area,
            perimeter_per_sqrt_area=perimeter / math.sqrt(area),
        ))
    masses.sort(key=lambda mass: mass.area, reverse=True)
    # Area-weighted perimeter/sqrt(area) over the masses large enough to read as land rather
    # than as specks. A compact disc scores 2*sqrt(pi) = 3.54; the ribbons and S-shapes that
    # started this work scored 18.4. Weighted by area because the masses you can see are the
    # ones that matter, and unweighted it would be dominated by three-tile islets.
    shaped = [mass for mass in masses if mass.area >= COMPACTNESS_MIN_AREA]
    shaped_area = sum(mass.area for mass in shaped)
    compactness = (
        sum(mass.perimeter_per_sqrt_area * mass.area for mass in shaped) / shaped_area
        if shaped_area else 0.0
    )
    thin_land = sum(
        1 for tile in world.tiles if tile.elevation >= 0
        and sum(world.tiles[n].elevation >= 0 for n in tile.neighbors) <= 3
    )
    dry = sum(tile.biome in {"desert", "arid_shrubland"} for tile in world.tiles)
    usable = sum(
        tile.elevation >= 0 and tile.biome not in UNUSABLE_BIOMES for tile in world.tiles
    )
    continent_min_area = max(1, math.ceil(land_count * CONTINENT_MIN_LAND_SHARE))
    return {
        "definitions": {
            "mass": "connected component of elevation >= 0 tiles over geodesic adjacency",
            "continent": f"mass with area >= {CONTINENT_MIN_LAND_SHARE:.3%} of all land",
            "continent_min_area": continent_min_area,
            "perimeter": "number of geodesic adjacency edges from land to water",
            "compactness": ("area-weighted perimeter/sqrt(area) over masses of at least "
                            f"{COMPACTNESS_MIN_AREA} tiles; a compact disc scores 3.54"),
        },
        "tiles": len(world.tiles),
        "land_tiles": land_count,
        "land_share": round(land_count / len(world.tiles), 6),
        "continent_count": sum(mass.area >= continent_min_area for mass in masses),
        "mass_count": len(masses),
        "largest_mass_tiles": masses[0].area if masses else 0,
        "largest_mass_land_share": round(masses[0].area / land_count if masses else 0.0, 6),
        "islands_under_20": sum(mass.area < 20 for mass in masses),
        "compactness": round(compactness, 4),
        "usable_land_tiles": usable,
        "usable_land_share": round(usable / len(world.tiles), 6),
        "usable_of_land": round(usable / land_count if land_count else 0.0, 6),
        "dry_land_tiles": dry,
        "dry_land_share": round(dry / land_count if land_count else 0.0, 6),
        "thin_land_tiles": thin_land,
        "thin_land_share": round(thin_land / land_count if land_count else 0.0, 6),
        "masses": [
            {"area": mass.area, "perimeter": mass.perimeter,
             "perimeter_per_area": round(mass.perimeter_per_area, 6),
             "perimeter_per_sqrt_area": round(mass.perimeter_per_sqrt_area, 6)}
            for mass in masses
        ],
        "coast_direction_spectrum": _coast_direction_spectrum(world),
    }
