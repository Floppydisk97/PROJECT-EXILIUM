"""Landing, and the ground it opens.

Two claims are being tested. That a colony takes a tile once and for ever, with the database
refusing every way round it. And that what the tile says about itself really does shape the
ground -- because if it does not, choosing a landing site is a formality with a nice view.
"""
from uuid import uuid4

import psycopg
import pytest

from app import citygen
from app.db import transaction
from app.mapservice import generate_and_store
import math

from app import worldgen
from app.service import (
    DomainError, _site_of, city_ground, city_state, land, provision, river_of, world_seed,
)
from app.sim.config import POLICY_RATES, production_rate

FREQUENCY = 12       # 1442 tiles: enough for coasts, rivers and several biomes
SMALL = 96           # a test-sized colony: production is 768 a side and three seconds, and
                     # these assertions are about shape, not about scale


def world():
    with transaction() as conn:
        generate_and_store(conn, "Approdo", FREQUENCY)


def player(name="Exilium"):
    with transaction() as conn:
        return provision(conn, name)


def a_land_tile(biome=None, with_river=False):
    # Not frozen: a tile can be dry by elevation and still be ice end to end, and landing
    # there is refused -- see `test_a_site_with_nothing_to_build_on_is_refused`.
    clause = ("elevation >= 0 AND biome NOT IN ('ocean', 'lake', 'sea_ice')"
              " AND temperature > -8")
    if biome:
        clause += f" AND biome = '{biome}'"
    if with_river:
        # La soglia, non "piu' di zero": ogni casella di terra porta la propria pioggia, e
        # chiedere un fiume con quel confronto restituiva la prima casella asciutta trovata.
        clause += f" AND river_flow >= {worldgen.river_min_flow(10 * FREQUENCY**2 + 2)}"
    with transaction() as conn:
        row = conn.execute(
            f"SELECT id FROM world_tiles WHERE map_id = 1 AND {clause} ORDER BY id LIMIT 1"
        ).fetchone()
    return None if row is None else row["id"]


def test_landing_takes_a_tile_and_rolls_the_ground(database):
    world()
    p = player()
    tile = a_land_tile()
    with transaction() as conn:
        result = land(conn, p["city_id"], p["player_id"], tile)
    assert result["tile_id"] == tile
    with transaction() as conn:
        row = conn.execute("SELECT tile_id, landed_at, map_seed FROM cities").fetchone()
    assert row["tile_id"] == tile and row["landed_at"] is not None
    assert len(row["map_seed"]) == 32


def test_a_colony_cannot_land_twice_or_move_afterwards(database):
    """Irreversible, and refused in two independent places. The rule says no; the trigger says
    no to anything that got past the rule. A constraint only the application enforces is one a
    future code path is free to forget."""
    world()
    p = player()
    with transaction() as conn:
        rows = conn.execute(
            "SELECT id FROM world_tiles WHERE map_id = 1 AND elevation >= 0"
            " AND biome NOT IN ('ocean','lake','sea_ice') AND temperature > -8"
            " ORDER BY id LIMIT 2"
        ).fetchall()
    first, second = rows[0]["id"], rows[1]["id"]
    with transaction() as conn:
        land(conn, p["city_id"], p["player_id"], first)
    with pytest.raises(DomainError) as error, transaction() as conn:
        land(conn, p["city_id"], p["player_id"], second)
    assert error.value.detail == "already_landed"
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute("UPDATE cities SET tile_id = %s", (second,))


def test_two_colonies_cannot_share_a_tile(database):
    """The scarcity that makes a site worth choosing. There is one river in that desert."""
    world()
    first, second = player("A"), player("B")
    tile = a_land_tile()
    with transaction() as conn:
        land(conn, first["city_id"], first["player_id"], tile)
    # All three columns, so that what refuses this is the uniqueness of the tile and not the
    # all-or-nothing check standing in front of it.
    with pytest.raises(psycopg.errors.UniqueViolation), transaction() as conn:
        conn.execute(
            "UPDATE cities SET tile_id = %s, landed_at = now(), map_seed = %s WHERE id = %s",
            (tile, "f" * 32, second["city_id"]),
        )
    # ... and through the front door it is a refusal with a reason, not a crash.
    with pytest.raises(DomainError) as error, transaction() as conn:
        land(conn, second["city_id"], second["player_id"], tile)
    assert error.value.detail == "tile_taken"


def test_water_is_refused(database):
    world()
    p = player()
    with transaction() as conn:
        ocean = conn.execute(
            "SELECT id FROM world_tiles WHERE map_id = 1 AND biome = 'ocean' LIMIT 1"
        ).fetchone()["id"]
    with pytest.raises(DomainError) as error, transaction() as conn:
        land(conn, p["city_id"], p["player_id"], ocean)
    assert error.value.detail == "not_dry_land"


def test_the_ground_is_not_stored_and_the_seed_is_what_travels(database):
    """The heart of it. 590.000 cells a colony would be three billion rows at the size this
    planet is built for; what is kept is a thirty-two character seed -- and what is SENT is
    that same seed, not the map it grows.

    Sending the map was nine megabytes and three seconds of CPU per request, for cells the
    receiver can grow in four tenths of a second from what is returned here.
    """
    world()
    p = player()
    with transaction() as conn:
        land(conn, p["city_id"], p["player_id"], a_land_tile())
    with transaction() as conn:
        first = city_ground(conn, p["city_id"], p["player_id"])
        second = city_ground(conn, p["city_id"], p["player_id"])
    assert first == second
    assert "cells" not in first
    # Everything the ground needs to be grown, and nothing that has to be carried.
    assert set(first) == {"city_id", "tile_id", "seed", "size", "hex_width_m",
                          "site", "ground_names"}
    assert len(first["seed"]) == 32
    with transaction() as conn:
        # Nothing about those cells went anywhere near a table.
        tables = conn.execute(
            "SELECT count(*) AS n FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_name LIKE '%cell%'"
        ).fetchone()["n"]
    assert tables == 0


def test_the_same_seed_gives_the_same_place_back(database):
    """Which is the only reason storing a seed instead of a map is sound. It used to be
    checked through the endpoint, back when the endpoint shipped the cells; the property
    belongs to the generator, so it is asked of the generator."""
    site = citygen.Site("temperate_forest", 220, 12.0, 1100, 900, False)
    first = citygen.generate("abc", site, SMALL)
    second = citygen.generate("abc", site, SMALL)
    assert first.ground == second.ground and first.height == second.height
    assert first.fertility == second.fertility and first.vegetation == second.vegetation
    # ... and a different seed is a different place, or the seed would not be doing anything.
    assert citygen.generate("abd", site, SMALL).ground != first.ground


def test_the_tile_decides_the_ground_not_the_colony(database):
    """A change of rule, deliberate. The seed used to mix the city id, so the ground was rolled
    at the moment of landing and nobody could know what they were taking until they had taken
    it. Scouting a site and then choosing it is a better game -- and it costs nothing, because
    one colony to a tile means two colonies never want different ground from the same place.

    It is also what lets the planet viewer show you the ground BEFORE you commit to it.
    """
    world()
    tile = a_land_tile()
    assert citygen.seed_for("Approdo", tile) == citygen.seed_for("Approdo", tile)
    # A different tile is a different place...
    assert citygen.seed_for("Approdo", tile) != citygen.seed_for("Approdo", tile + 1)
    # ... and a different world does not hand out the old one's ground.
    assert citygen.seed_for("Approdo", tile) != citygen.seed_for("Altrove", tile)


def test_an_unlanded_colony_has_no_ground(database):
    world()
    p = player()
    with pytest.raises(DomainError) as error, transaction() as conn:
        city_ground(conn, p["city_id"], p["player_id"])
    assert error.value.detail == "not_landed"


def test_the_biome_really_shapes_the_ground(database):
    """If this does not hold, choosing a landing site is a formality with a nice view.

    A swamp is mostly water and fertile; a desert is nearly all dry and barren. Asserted as an
    ordering rather than on exact numbers, because the numbers are balancing knobs in
    BIOME_RULES and are meant to be turned.
    """
    swamp = citygen.generate("x", citygen.Site("tropical_swamp", 40, 26.0, 2400, 0, False), SMALL)
    desert = citygen.generate("x", citygen.Site("desert", 300, 31.0, 80, 0, False), SMALL)
    ice = citygen.generate("x", citygen.Site("ice_sheet", 900, -30.0, 120, 0, False), SMALL)

    assert desert.buildable > swamp.buildable * 3
    assert _mean(swamp.fertility) > _mean(desert.fertility) * 3
    assert _mean(ice.fertility) == 0
    assert _mean(swamp.vegetation) > _mean(desert.vegetation)


def test_a_river_makes_its_banks_worth_landing_on(database):
    """The one reason to land in a desert. Without it the site looked interesting on the
    planet and was worthless on the ground."""
    dry = citygen.generate("x", citygen.Site("desert", 300, 31.0, 80, 0, False), SMALL)
    watered = citygen.generate("x", citygen.Site("desert", 300, 31.0, 80, 3100, False), SMALL)
    # Il confronto e' fra i due posti MIGLIORI, e il margine e' molto piu' stretto di quanto
    # fosse: da quando nessun sito e' del tutto sterile, un deserto ha comunque le sue macchie
    # verdi, quindi la sponda non parte piu' da zero. Vale ancora la pena di andarci -- la
    # sponda batte la migliore oasi, e con l'acqua arriva l'unica fonte d'energia che il
    # deserto non ha -- ma non e' piu' la differenza fra vivere e morire.
    assert max(watered.fertility) > 1.5 * max(dry.fertility)
    assert max(watered.vegetation) > 1.5 * max(dry.vegetation)
    assert watered.economy.water > 50 and dry.economy.water == 0
    # The bank is silt, not the sand the river crossed -- which is what stops the bonus being
    # halved by the biome's own ground right where it matters most.
    soil = citygen.GROUNDS.index("soil")
    assert soil in watered.ground and soil not in dry.ground


def _mean(values):
    return sum(values) / len(values)


def test_landing_writes_down_what_the_ground_is_worth(database):
    """The map is grown once, here, and reduced to three numbers. Nowhere else: production is
    worked out every time somebody looks at a city, and a colony is 590.000 cells."""
    world()
    p = player()
    with transaction() as conn:
        landed = land(conn, p["city_id"], p["player_id"], a_land_tile())
    assert {"site_food", "site_timber", "site_stone", "site_effort", "site_room"} <= set(landed)
    with transaction() as conn:
        row = conn.execute(
            "SELECT site_food, site_timber, site_stone, site_room FROM cities WHERE id = %s",
            (p["city_id"],),
        ).fetchone()
    assert row["site_food"] == landed["site_food"]
    assert row["site_room"] > 0
    # E i numeri sono quelli del posto, non una stima: rilevarlo di nuovo dal seme memorizzato
    # da' la stessa risposta. `survey` e non `generate`: e' il rilevamento a risoluzione fissa
    # che il server ha scritto, e generare la mappa intera qui sarebbe sedici secondi per
    # confrontare un numero che nessuno ha calcolato cosi'.
    with transaction() as conn:
        seed = conn.execute("SELECT map_seed FROM cities WHERE id = %s",
                            (p["city_id"],)).fetchone()["map_seed"]
        site, _tile = _site_of(conn, a_land_tile())
    assert citygen.survey(seed, site).food == row["site_food"]


def test_a_colony_in_orbit_earns_exactly_what_it_earned_before_the_ground_mattered(database):
    """Null is not zero. A colony that has not landed has no ground to be crowded against,
    and ruleset 2 must not quietly tax it for standing nowhere."""
    world()
    p = player()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM cities WHERE id = %s", (p["city_id"],)).fetchone()
    assert row["site_room"] is None
    state = city_state(row)
    assert state.site_food == 0 and state.site_effort == 0 and state.site_room is None
    assert production_rate("balanced", 7, state.site_food) == POLICY_RATES["balanced"] + 7 * 5


def test_a_site_with_nothing_to_build_on_is_refused(database):
    """Dry by elevation and yet frozen end to end: an ice cap has not one buildable cell.

    Landing is irreversible, so letting a colony down there would strand it for ever with
    nothing it could ever build. Hard ground is a decision -- a swamp has almost no room and
    is allowed -- but NO ground is a trap, and the planet has plenty of it.
    """
    world()
    p = player()
    with transaction() as conn:
        frozen = conn.execute(
            """SELECT id FROM world_tiles WHERE map_id = 1 AND elevation >= 0
                 AND biome NOT IN ('ocean', 'lake', 'sea_ice') AND temperature <= -8
               ORDER BY id LIMIT 1"""
        ).fetchone()
    if frozen is None:
        pytest.skip("this test world happens to have no frozen land")
    with pytest.raises(DomainError) as error, transaction() as conn:
        land(conn, p["city_id"], p["player_id"], frozen["id"])
    assert error.value.detail == "no_ground"


def test_no_site_is_completely_barren():
    """Ogni posto dove si puo' atterrare da' da mangiare e da' legna.

    Prima non era vero: il deserto e la roccia nuda uscivano con zero e zero, e una casella
    senza niente da raccogliere non e' un sito difficile -- e' un sito che non si puo'
    giocare. Adesso il fondo esiste, a macchie: un'oasi, una radura in quota, la conca erbosa
    in mezzo alla ghiaia. La montagna resta la montagna -- ha piu' pietra di tutti -- ma ha
    anche dove piantare qualcosa.

    Il ghiaccio e' l'eccezione dichiarata, e resta fuori di proposito: su una calotta polare
    non cresce niente, e fingere il contrario sarebbe togliere una geografia invece che
    aggiungerne una. Se un giorno si vorra' che anche una calotta si possa colonizzare, la
    risposta e' un modo di vivere diverso, non un albero sul ghiaccio.
    """
    frozen = {"ice_sheet", "snow_cap"}
    for biome, rule in citygen.BIOME_RULES.items():
        if biome in frozen:
            continue
        # Il sito piu' ostile che quel bioma consente: alto, asciutto e senza fiume.
        site = citygen.Site(biome, 1800, 4.0, 60, 0, False)
        made = citygen.generate(f"barren:{biome}", site, SMALL)
        economy = made.economy
        if economy.room == 0:
            # Niente su cui costruire: atterrare qui e' GIA' rifiutato -- vedi
            # `test_a_site_with_nothing_to_build_on_is_refused`. Un posto in cui non si entra
            # non ha bisogno di risorse; un posto in cui si entra e non c'e' niente era il
            # difetto, ed e' quello che le righe sotto tengono chiuso.
            continue
        assert economy.food > 0, biome
        assert economy.timber > 0, biome
        if rule.ground in ("rock", "gravel"):
            assert economy.stone > 0, biome


def test_only_a_real_river_reaches_the_ground(database):
    """Il fiume sul terreno e il fiume sul globo sono lo stesso fiume.

    `world_tiles.river_flow` e' deflusso accumulato e ogni casella di terra ne ha almeno la
    propria pioggia: preso per buono, disegnava un fiume in mezzo a OGNI colonia del pianeta.
    Il globo ha sempre disegnato i suoi fiumi sopra `worldgen.river_min_flow`; questo e' lo
    stesso confronto, quindi le due viste non possono piu' dire cose diverse.
    """
    world()
    threshold = worldgen.river_min_flow(10 * FREQUENCY**2 + 2)
    assert river_of(threshold - 1, FREQUENCY) == 0
    assert river_of(threshold, FREQUENCY) == threshold

    with transaction() as conn:
        # Una casella di terra bagnata ma senza fiume: il caso che era rotto.
        row = conn.execute(
            """SELECT id, river_flow FROM world_tiles
               WHERE map_id = 1 AND elevation >= 0 AND river_flow > 0 AND river_flow < %s
               ORDER BY id LIMIT 1""",
            (threshold,),
        ).fetchone()
        assert row is not None, "un pianeta senza una sola casella di solo ruscellamento"
        site, _tile = _site_of(conn, row["id"])
    assert row["river_flow"] > 0
    assert site.river_flow == 0
    # E su quel terreno non c'e' acqua corrente: niente fiume, niente portata idroelettrica.
    assert citygen.generate("x", site, SMALL).economy.water == 0


def test_the_survey_is_the_number_the_viewer_showed(database):
    """Il numero mostrato prima di atterrare e quello scritto dopo sono lo stesso.

    Da quando la colonia si disegna a 2,36 milioni di esagoni da un metro quadro, la mappa
    che si GUARDA e il rilevamento che si MEMORIZZA non hanno piu' la stessa risoluzione --
    generare la mappa intera nella richiesta di atterraggio sarebbe sedici secondi, misurati.
    Sono due cose diverse di proposito, e questa e' la cosa che deve restare vera perche' la
    differenza sia innocua: scegliere un sito e' una decisione presa sui numeri del visore, e
    se il server ne scrivesse altri sarebbe una promessa non mantenuta.

    Il client chiama il gemello TypeScript di `survey`, e `citygen.test.ts` lo tiene cella per
    cella su questo stesso rilevamento: la catena e' chiusa.
    """
    site = citygen.Site("temperate_forest", 220, 12.0, 1100, 0, False)
    assert citygen.survey("x", site) == citygen.generate("x", site, citygen.SURVEY_SIZE).economy

    world()
    p = player()
    with transaction() as conn:
        tile = a_land_tile()
        landed = land(conn, p["city_id"], p["player_id"], tile)
        seed = citygen.seed_for(world_seed(conn), tile)
        here, _tile = _site_of(conn, tile)
    shown = citygen.survey(seed, here)
    assert landed["site_food"] == shown.food
    assert landed["site_timber"] == shown.timber
    assert landed["site_stone"] == shown.stone
    assert landed["site_room"] == shown.room


def test_a_colony_is_a_field_of_hexagons_a_metre_across(database):
    """Un esagono e' un metro quadro, e la colonia e' larga quanto dice di essere.

    La scala non e' decorazione: e' quella su cui si costruira'. Un edificio da dieci metri
    per dieci occupa cento esagoni, e se l'esagono valesse otto metri come la vecchia cella
    quadrata ne occuperebbe uno e mezzo -- cioe' non ci sarebbe niente da disporre.

    La mappa NON e' quadrata, ed e' la conseguenza che si dimentica: le righe distano radice
    di tre mezzi, quindi 1536 righe sono piu' corte di 1536 colonne. Chi la inquadra deve
    chiedere l'altezza invece di assumerla.
    """
    assert citygen.HEX_AREA_M2 == 1.0
    # Da piatto a piatto: un esagono di un metro quadro e' largo poco piu' di un metro.
    assert 1.07 < citygen.HEX_WIDTH_M < 1.08
    assert citygen.ROW_RATIO == math.sqrt(3.0) / 2.0

    wide = citygen.SIZE * citygen.HEX_WIDTH_M
    tall = citygen.SIZE * citygen.ROW_RATIO * citygen.HEX_WIDTH_M
    assert 1600 < wide < 1700          # circa 1,65 km
    assert tall < wide
    # E il rilevamento e' piu' grossolano del disegno, se no non avrebbe senso averne due.
    assert citygen.SURVEY_SIZE < citygen.SIZE
