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


SEEDS = ["Hesperia-01", "Hesperia-02", "Hesperia-03", "Hesperia-04"]
SHIPPED_SEED = "Hesperia-01"   # the one world this game actually has


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("frequency", [60, worldgen.PRODUCTION_FREQUENCY])
def test_every_seed_gets_a_well_formed_planet(seed, frequency):
    """What the generator guarantees for ANY seed: the geodesic is correct, the land
    fraction is the one chosen, and the world seats the target player count.

    Deliberately NOT asserted here: how many continents there are and how big the largest
    one is. Those are properties of a particular seed, not of the algorithm -- the ocean
    basins make a split likely, never certain, and raising the land fraction makes a
    supercontinent more likely, not less. `Hesperia-04` forms one. See `architecture.md`.
    """
    world = worldgen.generate(seed, frequency=frequency)
    assert len(world.tiles) == 10 * frequency ** 2 + 2
    assert sum(1 for t in world.tiles if len(t.polygon) == 5) == 12
    metrics = measure(world)
    # Tracks the design parameter rather than a copied number: the land fraction is chosen
    # by SEA_PERCENTILE, and a test that restates it as a literal goes stale the first time
    # the choice changes -- which is exactly what happened.
    assert metrics["land_share"] == pytest.approx(1 - worldgen.SEA_PERCENTILE, abs=0.0005)
    if frequency == worldgen.PRODUCTION_FREQUENCY:
        # One player settles one land tile; the world must seat at least the target.
        assert metrics["usable_land_tiles"] >= worldgen.MIN_PLAYER_CAPACITY


@pytest.mark.parametrize("frequency", [60, worldgen.PRODUCTION_FREQUENCY])
def test_the_shipped_world_is_split_habitable_and_compact(frequency):
    """What the world we actually ship must look like, at both resolutions.

    These are the bounds the design cares about, and they are asserted against the seed the
    game runs on rather than against a suite -- because a bound that no seed is required to
    meet is not a requirement, and one that every seed must meet would be a promise the
    generator cannot keep.
    """
    metrics = measure(worldgen.generate(SHIPPED_SEED, frequency=frequency))
    assert metrics["continent_count"] >= 3
    assert metrics["largest_mass_land_share"] < 0.55
    assert metrics["dry_land_share"] < 0.25
    assert metrics["usable_of_land"] > 0.70       # ice and bare rock stay a minority
    if frequency == worldgen.PRODUCTION_FREQUENCY:
        # Only at production tiling: a coarser mesh cannot resolve an islet a few tiles
        # across, so the same planet honestly shows fewer of them at f=60.
        assert metrics["islands_under_20"] >= 25
    # The number that captures the complaint this work started from: coasts came out as
    # ribbons and S-shapes. v3, the version in production before this, scored 18.37.
    assert metrics["compactness"] < 13.0
    assert metrics["coast_direction_spectrum"]["peak_to_mean"] < 1.667


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
    rivers = [t for t in world.tiles if t.elevation >= 0 and t.river_flow >= worldgen.river_min_flow(len(world.tiles))]
    assert rivers, "a world this size must carry rivers"
    for t in world.tiles:
        if t.elevation < 0:
            assert t.downstream == -1
            continue
        assert t.downstream != -1   # see test_every_river_reaches_the_sea
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
    assert max(bodies) >= 40                       # and at least one big enough to matter
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


def test_every_river_reaches_the_sea_and_none_dies_in_a_lake():
    """The surface of a lake is flat, so "flow downhill" decides nothing on it and the tie
    has to be broken by something that knows where the outlet is. Breaking it on the ground
    beneath -- which is what the generator did for three versions -- sends water to the
    deepest point of the basin: the one tile with no way out. On the shipped planet that
    ended 651 rivers inside a lake, the largest of them carrying the drainage of a whole
    continent, and the planet had no river that reached the sea at all.

    Two assertions, because the cheap one alone would pass on a planet whose rivers were all
    trickles: drainage never terminates inland, *and* the biggest river on the planet is one
    that makes it to the coast.
    """
    world = worldgen.generate(SHIPPED_SEED, frequency=60)
    by_id = {t.id: t for t in world.tiles}
    land = [t for t in world.tiles if t.elevation >= 0]

    stranded = [t for t in land if t.downstream == -1]
    assert not stranded, f"{len(stranded)} land tiles drain nowhere"

    biggest = max(t.river_flow for t in land)
    mouths = [t for t in land if by_id[t.downstream].elevation < 0]
    assert max(t.river_flow for t in mouths) == biggest


def test_rivers_do_not_run_in_parallel_combs():
    """What the threshold is *for*. Flow is counted in tiles, so a fixed cut-off means a
    smaller and smaller catchment as the grid gets finer: at twenty on the production planet
    a reach was the drainage of about ten tiles, and nearly every reach had a second one
    running alongside it -- 0.94 unrelated neighbours per reach, drawn as hatching the moment
    you zoomed in. `river_min_flow` scales the cut-off with the grid instead.

    "Alongside" has to be defined carefully: a river that turns on a hex grid puts two of its
    own tiles side by side without either draining into the other, and that is a meander, not
    a second river. So a neighbouring reach counts against us only when the two do not meet
    again within four steps downstream.
    """
    world = worldgen.generate(SHIPPED_SEED, frequency=60)
    by_id = {t.id: t for t in world.tiles}
    threshold = worldgen.river_min_flow(len(world.tiles))
    drawn = {
        t.id for t in world.tiles
        if t.elevation >= 0 and t.biome != "lake" and t.river_flow >= threshold
    }
    assert len(drawn) > 100, "a world this size must carry rivers to measure"

    def downstream_of(start, limit=40):
        seen, step, at = {}, 0, start
        while at != -1 and step <= limit:
            seen[at] = step
            at, step = by_id[at].downstream, step + 1
        return seen

    paths = {i: downstream_of(i) for i in drawn}
    unrelated = 0
    for i in drawn:
        for n in by_id[i].neighbors:
            if n <= i or n not in drawn:
                continue
            if by_id[i].downstream == n or by_id[n].downstream == i:
                continue
            shared = paths[i].keys() & paths[n].keys()
            if min((paths[i][k] + paths[n][k] for k in shared), default=99) > 4:
                unrelated += 1
    assert unrelated / len(drawn) < 0.45
