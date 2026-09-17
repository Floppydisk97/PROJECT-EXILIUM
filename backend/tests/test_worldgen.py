import math

import pytest

from app import worldgen


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
    assert 0.5 < ocean < 0.75  # a water world, not fully flooded


def test_production_frequency_supports_the_player_capacity():
    world = worldgen.generate("Hesperia-01", frequency=worldgen.PRODUCTION_FREQUENCY)
    assert len(world.tiles) == 10 * worldgen.PRODUCTION_FREQUENCY ** 2 + 2
    land = sum(1 for t in world.tiles if t.elevation >= 0)
    # One player settles one land tile; the world must seat at least the target capacity.
    assert land >= worldgen.MIN_PLAYER_CAPACITY
    assert sum(1 for t in world.tiles if len(t.polygon) == 5) == 12


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValueError):
        worldgen.generate("Church", frequency=1)
    with pytest.raises(ValueError):
        worldgen.generate("   ", frequency=8)


def test_rivers_flow_downhill_into_the_sea_or_a_lake():
    world = worldgen.generate("Church", frequency=24)
    by_id = {t.id: t for t in world.tiles}
    rivers = [t for t in world.tiles if t.elevation >= 0 and t.river_flow >= worldgen.RIVER_MIN_FLOW]
    assert rivers, "a world this size must carry rivers"
    for t in world.tiles:
        if t.elevation < 0:
            assert t.downstream == -1
            continue
        if t.downstream == -1:
            continue  # closed basin
        downstream = by_id[t.downstream]
        assert downstream.id in t.neighbors          # water only moves to a neighbour
        assert downstream.elevation < t.elevation    # and only downhill: no cycles
        assert downstream.river_flow >= t.river_flow or downstream.elevation < 0


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
    # Ice belongs at the poles, deserts do not.
    ice = [abs(t.lat) for t in world.tiles if t.biome == "ice_sheet"]
    assert min(ice) > 45
    sizes = {t.landmass_size for t in world.tiles if t.elevation >= 0}
    assert len(sizes) > 3  # several separate continents and islands, not one blob
