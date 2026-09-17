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
