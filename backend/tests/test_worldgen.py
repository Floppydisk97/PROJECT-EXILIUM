import math

import pytest

from app import worldgen
from app.worldmetrics import measure


def test_geodesic_tile_counts_and_twelve_pentagons():
    for frequency in (2, 6, 12):
        world = worldgen.generate("Church", frequency=frequency)
        assert len(world.tiles) == 10 * frequency * frequency + 2
        pentagons = sum(1 for t in world.tiles if len(t.polygon) == 5)
        hexagons = sum(1 for t in world.tiles if len(t.polygon) == 6)
        assert pentagons == 12
        assert pentagons + hexagons == len(world.tiles)


def test_generation_is_deterministic_and_seed_sensitive():
    a = worldgen.generate("Church", frequency=8)
    b = worldgen.generate("Church", frequency=8)
    assert [(t.biome, t.elevation, t.temperature, t.rainfall) for t in a.tiles] == \
           [(t.biome, t.elevation, t.temperature, t.rainfall) for t in b.tiles]
    other = worldgen.generate("Exile", frequency=8)
    assert [t.biome for t in a.tiles] != [t.biome for t in other.tiles]


def test_tiles_are_on_the_unit_sphere_with_symmetric_neighbors():
    world = worldgen.generate("Church", frequency=6)
    by_id = {t.id: t for t in world.tiles}
    for t in world.tiles:
        assert math.isclose(sum(c * c for c in t.center), 1.0, abs_tol=1e-6)
        assert -90 <= t.lat <= 90 and -180 <= t.lon <= 180
        assert t.biome in worldgen.BIOMES
        assert 5 <= len(t.neighbors) <= 6
        for nb in t.neighbors:
            assert t.id in by_id[nb].neighbors  # adjacency is symmetric


def test_climate_is_physically_ordered():
    world = worldgen.generate("Church", frequency=12)
    poles = [t.temperature for t in world.tiles if abs(t.lat) > 70]
    equator = [t.temperature for t in world.tiles if abs(t.lat) < 10]
    assert sum(poles) / len(poles) < sum(equator) / len(equator)
    ocean = sum(1 for t in world.tiles if t.elevation < 0) / len(world.tiles)
    assert 0.5 < ocean < 0.85  # a water world, not fully flooded


@pytest.mark.parametrize("seed", ["Hesperia-01", "Hesperia-02", "Hesperia-03", "Hesperia-04"])
def test_production_frequency_supports_capacity_and_topology_for_supported_seeds(seed):
    world = worldgen.generate(seed, frequency=worldgen.PRODUCTION_FREQUENCY)
    assert len(world.tiles) == 10 * worldgen.PRODUCTION_FREQUENCY ** 2 + 2
    land = sum(1 for t in world.tiles if t.elevation >= 0)
    # One player settles one land tile; the world must seat at least the target capacity.
    assert land >= worldgen.MIN_PLAYER_CAPACITY
    assert sum(1 for t in world.tiles if len(t.polygon) == 5) == 12
    metrics = measure(world)
    assert metrics["land_share"] == pytest.approx(0.24, abs=0.0002)
    assert metrics["continent_count"] >= 3
    assert metrics["largest_mass_land_share"] < 0.55
    assert metrics["dry_land_share"] < 0.25
    if seed == "Hesperia-01":
        assert metrics["islands_under_20"] == 34
        assert metrics["thin_land_share"] <= 0.031049
        assert metrics["coast_direction_spectrum"]["peak_to_mean"] < 1.667


@pytest.mark.parametrize("seed", ["Hesperia-01", "Hesperia-02", "Hesperia-03", "Hesperia-04"])
def test_supported_seeds_remain_split_at_review_frequency(seed):
    metrics = measure(worldgen.generate(seed, frequency=60))
    assert metrics["land_share"] == pytest.approx(0.24, abs=0.0002)
    assert metrics["continent_count"] >= 3
    assert metrics["largest_mass_land_share"] < 0.55
    assert metrics["dry_land_share"] < 0.25


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValueError):
        worldgen.generate("Church", frequency=1)
    with pytest.raises(ValueError):
        worldgen.generate("   ", frequency=8)


def test_rivers_flow_downhill_into_the_sea_or_a_lake():
    """Water never climbs, and the drainage graph has no cycles.

    The invariant used to be the stronger `strictly downhill`, which held only because a
    river stopped at the first hollow it met. Now that depressions are filled and routing
    follows the water surface, a river crosses a lake at constant level -- so two consecutive
    tiles can share an elevation, and acyclicity has to be asserted directly rather than
    inferred from a strict descent.
    """
    world = worldgen.generate("Church", frequency=24)
    by_id = {t.id: t for t in world.tiles}
    rivers = [t for t in world.tiles if t.elevation >= 0 and t.river_flow >= worldgen.RIVER_MIN_FLOW]
    assert rivers, "a world this size must carry rivers"
    for t in world.tiles:
        if t.elevation < 0:
            assert t.downstream == -1
            continue
        if t.downstream == -1:
            continue  # a basin with nowhere to spill
        downstream = by_id[t.downstream]
        assert downstream.id in t.neighbors            # water only moves to a neighbour
        assert downstream.elevation <= t.elevation     # and never uphill
        assert downstream.river_flow >= t.river_flow or downstream.elevation < 0

    # Every drop reaches the sea or a terminal basin: following downstream from anywhere
    # terminates. A cycle would make flow accumulation meaningless and loop forever here.
    state = {}   # 0 = on the current path, 1 = already known to terminate
    for start in world.tiles:
        if start.elevation < 0 or start.id in state:
            continue
        path = []
        current = start.id
        while current != -1 and current not in state:
            assert state.get(current) != 0, "the drainage graph contains a cycle"
            state[current] = 0
            path.append(current)
            current = by_id[current].downstream
        assert current == -1 or state[current] == 1, "the drainage graph contains a cycle"
        for tile_id in path:
            state[tile_id] = 1


def test_the_world_has_lakes_of_many_sizes_and_at_least_one_inland_sea():
    """Standing water is a spectrum, not a rarity.

    Before depressions were filled the rule could only find single-tile pits, and the
    production world had thirty lake tiles in total. These bounds are what stop that
    silently coming back.
    """
    world = worldgen.generate("Hesperia-01", frequency=60)
    lake = [t for t in world.tiles if t.biome == "lake"]
    assert lake, "a planet with rain and relief must hold standing water"

    by_id = {t.id: t for t in world.tiles}
    seen: set[int] = set()
    bodies = []
    for tile in lake:
        if tile.id in seen:
            continue
        seen.add(tile.id)
        body = [tile.id]
        frontier = [tile.id]
        while frontier:
            current = frontier.pop()
            for neighbor in by_id[current].neighbors:
                if by_id[neighbor].biome == "lake" and neighbor not in seen:
                    seen.add(neighbor)
                    body.append(neighbor)
                    frontier.append(neighbor)
        bodies.append(len(body))

    assert len(bodies) >= 15                       # many, not a handful
    assert max(bodies) >= 60                       # and at least one big enough to matter
    assert sum(1 for size in bodies if size <= 4) >= 3   # down to tarns

    # A lake's surface is flat: every tile of one body shares an elevation. Stored at the
    # bed instead, a lake would be drawn as a lumpy blue hillside.
    for tile in lake:
        for neighbor in tile.neighbors:
            other = by_id[neighbor]
            if other.biome == "lake":
                assert abs(other.elevation - tile.elevation) <= 1


def test_landmasses_are_consistent_across_their_tiles():
    world = worldgen.generate("Church", frequency=24)
    by_id = {t.id: t for t in world.tiles}
    for t in world.tiles:
        if t.elevation < 0:
            assert t.landmass_size == 0
            continue
        assert t.landmass_size >= 1
        for nb in t.neighbors:
            if by_id[nb].elevation >= 0:
                assert by_id[nb].landmass_size == t.landmass_size


def test_terrain_normals_are_unit_vectors_pointing_outward():
    world = worldgen.generate("Church", frequency=12)
    for t in world.tiles:
        assert math.isclose(sum(c * c for c in t.normal), 1.0, abs_tol=1e-6)
        # Relief tilts the normal, but never past the horizon of its own tile.
        assert sum(a * b for a, b in zip(t.normal, t.center)) > 0.2


def test_the_production_world_has_deserts_mountains_and_polar_caps():
    world = worldgen.generate("Hesperia-01", frequency=40)
    counts: dict[str, int] = {}
    for t in world.tiles:
        counts[t.biome] = counts.get(t.biome, 0) + 1
    land = sum(1 for t in world.tiles if t.elevation >= 0)
    # Each landform the world is supposed to show must actually be there, in a sane share.
    assert counts.get("desert", 0) + counts.get("arid_shrubland", 0) > land * 0.05
    assert counts.get("bare_rock", 0) + counts.get("snow_cap", 0) > land * 0.02
    assert counts.get("ice_sheet", 0) > 0 and counts.get("sea_ice", 0) > 0
    forest = sum(counts.get(b, 0) for b in
                 ("boreal_forest", "temperate_forest", "tropical_rainforest"))
    assert forest > land * 0.15
    # Deserts are a feature, not the default surface: the generator used to paint a third
    # of the land arid, which is what this bound exists to stop coming back.
    assert counts.get("desert", 0) + counts.get("arid_shrubland", 0) < land * 0.25
    assert counts.get("desert", 0) > 0  # ... but a world with no desert at all is wrong too
    # Ice belongs at the poles, deserts do not.
    ice = [abs(t.lat) for t in world.tiles if t.biome == "ice_sheet"]
    assert min(ice) > 45
    sizes = {t.landmass_size for t in world.tiles if t.elevation >= 0}
    assert len(sizes) > 3  # several separate continents and islands, not one blob


def test_the_production_world_is_not_one_supercontinent():
    """The land must be broken into continents with sea between them, and be dotted with
    islands. Nothing about a smooth elevation field guarantees this -- at this sea level it
    percolates into a single mass unless the ocean basins cut it -- so it is asserted."""
    world = worldgen.generate("Hesperia-01", frequency=48)
    land = [t for t in world.tiles if t.elevation >= 0]
    counts: dict[int, int] = {}
    for t in land:
        counts[t.landmass_size] = counts.get(t.landmass_size, 0) + 1
    # tiles-of-this-size / size == how many distinct masses have that size.
    masses = sum(n // size for size, n in counts.items())
    biggest = max(t.landmass_size for t in land)

    assert biggest < len(land) * 0.55   # no single mass holding most of the world
    assert sum(1 for size in counts if size > 300) >= 3   # at least three real continents
    assert masses >= 20                                    # and a scattering of islands
