from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.sim.config import (
    LEVEL_RATE, POLICY_RATES, ROOM_PER_LEVEL, UPGRADE_DURATION,
    harvest_rate, production_rate, store_cap, time_to_full, upgrade_cost, upgrade_duration,
)
from app.sim.config import WORKS
from app.sim.rules import (
    demand, majority_policy, net_flows, power, production_amount, settle_city, throttle,
)
from app.sim.state import CityState, PolicyPeriod

START = datetime(2026, 1, 1, tzinfo=UTC)
FOREVER = [PolicyPeriod("balanced", START - timedelta(days=1), None)]
NOW = START
BALANCED = FOREVER


def test_production_is_additive_and_integer_over_long_downtime():
    middle, end = START + timedelta(seconds=73), START + timedelta(days=900, seconds=5)
    assert production_amount(START, end, FOREVER, 2) == (900 * 86400 + 5) * 20
    assert (production_amount(START, middle, FOREVER, 2)
            + production_amount(middle, end, FOREVER, 2)
            == production_amount(START, end, FOREVER, 2))


def test_production_is_paid_at_the_rate_the_time_actually_had():
    """The rule the tick's boundary used to enforce, now enforced by arithmetic instead of by
    holding every city still. An hour at 10/s followed by an hour at 20/s is 108000, not
    either rate applied to the whole two hours."""
    switch = START + timedelta(hours=1)
    end = START + timedelta(hours=2)
    timeline = [
        PolicyPeriod("balanced", START, switch),
        PolicyPeriod("industrial", switch, None),
    ]
    assert production_amount(START, end, timeline, 0) == 3600 * 10 + 3600 * 20
    assert production_amount(START, end, timeline, 0) != production_amount(START, end, FOREVER, 0)


def test_a_gap_in_the_timeline_is_refused_rather_than_paid_as_nothing():
    """An uncovered stretch means the timeline is broken. Returning zero for it would turn a
    bug into quietly missing alloy that nobody could ever account for."""
    gapped = [
        PolicyPeriod("balanced", START, START + timedelta(hours=1)),
        PolicyPeriod("balanced", START + timedelta(hours=2), None),
    ]
    with pytest.raises(ValueError, match="does not cover"):
        production_amount(START, START + timedelta(hours=3), gapped, 0)


def test_policy_ties_preserve_incumbent():
    assert majority_policy("industrial", {}) == "industrial"
    assert majority_policy("balanced", {"balanced": 1, "industrial": 1}) == "balanced"
    assert majority_policy("balanced", {"industrial": 2}) == "industrial"


def test_invalid_time_cannot_mint_resources():
    with pytest.raises(ValueError):
        production_amount(START, START - timedelta(seconds=1), FOREVER, 0)
    with pytest.raises(ValueError):
        production_amount(START.replace(tzinfo=None), START, FOREVER, 0)
    with pytest.raises(ValueError):
        production_amount(START, START + timedelta(microseconds=1), FOREVER, 0)


def test_the_ground_pays_and_the_ground_charges():
    """Ruleset 2, and the reason for it: before this, where you landed changed the view and
    nothing else, so choosing a site was a formality with a scenery.

    The two knobs pull in opposite directions on purpose. One knob would only ever have made
    a ranking -- a best site, and a search instead of a decision.
    """
    # Rich ground pays more for the same level...
    poor = production_rate("balanced", 10, 1)
    rich = production_rate("balanced", 10, 88)
    assert rich > poor * 3 // 2

    # ... and takes far longer to reach the next one, because it has to be cleared first.
    open_ground = upgrade_duration(10, effort=0)
    overgrown = upgrade_duration(10, effort=48)
    assert overgrown > open_ground * 2

    # A site with nothing on it is the baseline, not a penalty: an unlanded colony produces
    # exactly what it produced before there was any ground in the rules at all.
    assert production_rate("balanced", 10, 0) == POLICY_RATES["balanced"] + 10 * LEVEL_RATE
    assert upgrade_duration(10) == UPGRADE_DURATION * 11


def test_the_ceiling_is_soft_because_landing_is_final():
    """A colony that runs out of ground gets slower and dearer, never finished. A wall would
    condemn whoever chose a delta, for ever, in a world where you cannot start again."""
    cramped = 600           # four levels' worth of buildable cells
    free = cramped // ROOM_PER_LEVEL
    assert free == 4

    def dearer(level, room):
        """Quanto costa di piu' che sul terreno largo -- lo stesso fattore su ogni risorsa."""
        tight, loose = upgrade_cost(level, room), upgrade_cost(level)
        factors = {tight[r] // loose[r] for r in loose}
        assert len(factors) == 1, (tight, loose)
        return factors.pop()

    # Inside its room, a cramped colony is an ordinary colony.
    assert upgrade_cost(0, cramped) == upgrade_cost(0)
    assert upgrade_duration(2, 0, cramped) == upgrade_duration(2)

    # Past it, both cost and time climb -- and keep climbing, rather than stopping.
    assert dearer(free, cramped) == 2
    assert dearer(free + 3, cramped) == 5
    assert upgrade_duration(free + 3, 0, cramped) == upgrade_duration(free + 3) * 5
    # Dear, but never impossible.
    assert max(upgrade_cost(free + 50, cramped).values()) < 10 ** 12


def test_a_stretched_upgrade_still_lands_on_a_whole_second():
    """The database refuses a sub-second timestamp, so a multiplier that introduced a
    fraction would fail at the INSERT -- long after the arithmetic that caused it."""
    for effort in range(0, 201, 7):
        for level in (0, 1, 9, 37):
            duration = upgrade_duration(level, effort, 10_000)
            assert duration.microseconds == 0, (level, effort)


def test_the_site_cannot_change_what_splitting_an_interval_means():
    """The whole reason production can accrue from timestamps: settling a week in one go and
    settling it a day at a time have to agree, to the milli."""
    start = NOW
    week = start + timedelta(days=7)
    for site_food in (0, 1, 37, 88, 100):
        whole = production_amount(start, week, BALANCED, 5, site_food)
        piecewise = sum(
            production_amount(start + timedelta(days=d), start + timedelta(days=d + 1),
                              BALANCED, 5, site_food)
            for d in range(7)
        )
        assert whole == piecewise, site_food


def test_a_full_store_is_predictable_before_it_happens():
    """La meta' che rende accettabile lo stallo alla Anno in un mondo che cammina mentre dormi.

    Fermarsi e' la tensione voluta; fermarsi A SORPRESA e' una faccenda da sbrigare. Il
    momento in cui un magazzino smettera' di guadagnare si calcola, quindi si puo' dire prima.
    """
    cap = store_cap(0)
    assert time_to_full(stock=0, cap=cap, rate=100) == cap / 100
    # A meta' strada manca la meta' del tempo.
    assert time_to_full(cap // 2, cap, 100) == (cap - cap // 2) / 100
    # Due stati che sembrerebbero uguali se si confondessero, e non lo sono: uno chiede di
    # spendere, l'altro dice che quella risorsa qui non arriva.
    assert time_to_full(cap, cap, 100) == 0         # gia' pieno
    assert time_to_full(0, cap, 0) is None          # non si riempira' mai


def test_every_site_can_still_build_something():
    """Un deserto non ha ne' roccia ne' alberi. Senza un minimo garantito non potrebbe
    costruire MAI nulla, e sarebbe un vicolo cieco in attesa di un commercio che ancora non
    esiste -- lo stesso errore del sito senza celle edificabili, in un'altra forma."""
    for resource in ("timber", "stone"):
        assert harvest_rate(resource, level=0, site=0) > 0
    # ... ma la terra che ce l'ha resta molto meglio: il minimo e' una rete, non un livellamento.
    assert harvest_rate("stone", 0, 99) > harvest_rate("stone", 0, 0) * 5


SITE = {"site_food": 52, "site_timber": 48, "site_stone": 12, "site_ore": 7,
        "site_wind": 40, "site_sun": 50, "site_water": 26, "site_heat": 10,
        "site_effort": 41, "site_room": 500_000}
# Una fonderia senza corrente non fa nulla, quindi una colonia di prova che vuole fondere ha
# bisogno di una centrale: e' il vincolo nuovo, non un dettaglio del fixture.
POWERED = {"smelter": 1, "solar": 2}
FOREVER_FROM = [PolicyPeriod("balanced", START - timedelta(days=2), None)]


def colony(stock=None, works=None, idle=None, level=0, **site):
    return CityState(id=UUID(int=1), level=level, settled_at=START,
                     stock=dict(stock or {}), works=dict(works or {}),
                     idle=dict(idle or {}), **{**SITE, **site})


def test_a_work_drains_the_buffer_and_then_runs_on_what_arrives():
    """Il cuore della catena, e il motivo per cui la produzione non e' piu' una moltiplicazione.

    Un'opera tira dal magazzino finche' ce n'e': puo' girare a pieno anche consumando piu' di
    quanto arrivi, perche' sta svuotando un buffer. Quando il buffer e' a zero puo' girare
    solo al ritmo con cui l'ingresso arriva -- e da quel momento il tasso e' un altro.
    """
    two = colony(stock={"ore": 40_000, "timber": 200_000}, works={"smelter": 2, "solar": 4})
    assert throttle(two, "balanced", two.stock) == 1000          # c'e' scorta: a pieno
    assert net_flows(two, "balanced", two.stock)["ore"] < 0       # e la sta consumando

    starved = throttle(two, "balanced", {**two.stock, "ore": 0})
    assert 0 < starved < 1000                                     # a secco: al ritmo del filone
    # Non e' un arrotondamento: e' il rapporto fra cio' che arriva e cio' che si vorrebbe.
    arriving = harvest_rate("ore", 0, SITE["site_ore"])
    wanted = WORKS["smelter"]["inputs"]["ore"] * 2
    assert starved == 1000 * arriving // wanted


def test_splitting_an_interval_still_cannot_change_the_answer():
    """L'invariante che ha permesso di togliere il tick, messa alla prova da cio' che avrebbe
    potuto romperla. Con un processo che CONSUMA il tasso cambia dentro l'intervallo, quindi
    liquidare due giorni in un colpo e liquidarli ora per ora devono comunque coincidere --
    al milli, non circa."""
    start = colony(stock={"ore": 40_000, "timber": 200_000}, works={"smelter": 2, "solar": 4})
    whole = settle_city(start, START + timedelta(hours=48), FOREVER_FROM).city.stock

    piecewise = start
    for hour in range(48):
        piecewise = settle_city(piecewise, START + timedelta(hours=hour + 1),
                                FOREVER_FROM).city
    assert whole == piecewise.stock


def test_a_decade_of_absence_is_still_a_handful_of_steps():
    """Nessun tick e' tornato dalla finestra. Ogni risorsa cambia regime al piu' due volte --
    tocca lo zero, tocca il tetto -- quindi la camminata converge e si ferma, invece di
    percorrere trecentoquindici milioni di secondi."""
    forgotten = colony(stock={"ore": 40_000, "timber": 200_000}, works={"smelter": 2, "solar": 4})
    settled = settle_city(forgotten, START + timedelta(days=3650), FOREVER_FROM)
    assert settled is not None
    assert settled.city.settled_at == START + timedelta(days=3650)


def test_nothing_but_a_work_makes_alloy():
    """La lega non si raccoglie: si fonde. E' cio' che rende la catena necessaria invece che
    decorativa, perche' dal livello tre in su un avanzamento la richiede."""
    bare = colony(stock={"ore": 40_000, "timber": 40_000})
    after = settle_city(bare, START + timedelta(hours=6), FOREVER_FROM).city
    assert after.stock.get("alloy", 0) == 0

    with_works = colony(stock={"ore": 40_000, "timber": 40_000}, works=POWERED)
    made = settle_city(with_works, START + timedelta(hours=6), FOREVER_FROM).city
    assert made.stock["alloy"] > 0


def test_an_oscillating_chain_is_refused_instead_of_looping_for_ever():
    """Un ciclo infinito dentro una richiesta e' il modo peggiore di scoprire che una catena
    e' mal fatta. Meglio rifiutare rumorosamente che pagare un anno con l'economia
    dell'ultimo secondo."""
    import app.sim.rules as rules

    normal = rules.MAX_EVENTS
    rules.MAX_EVENTS = 1                       # una sola mossa: qualunque evento lo supera
    try:
        busy = colony(stock={"ore": 40_000, "timber": 200_000}, works={"smelter": 2, "solar": 4})
        with pytest.raises(ValueError, match="regime"):
            settle_city(busy, START + timedelta(days=30), FOREVER_FROM)
    finally:
        rules.MAX_EVENTS = normal


def test_a_work_without_current_does_nothing_at_all():
    """L'energia e' un flusso, non una scorta: cio' che non si produce adesso non si consuma
    adesso. Una fonderia senza centrale non rallenta -- sta ferma."""
    dark = colony(stock={"ore": 40_000, "timber": 40_000}, works={"smelter": 1})
    made, used = power(dark)
    assert made == 0 and used > 0
    assert throttle(dark, "balanced", dark.stock) == 0
    after = settle_city(dark, START + timedelta(hours=6), FOREVER_FROM).city
    assert after.stock.get("alloy", 0) == 0

    # Accesa la centrale, la stessa colonia fonde.
    lit = colony(stock={"ore": 40_000, "timber": 40_000}, works=POWERED)
    assert settle_city(lit, START + timedelta(hours=6), FOREVER_FROM).city.stock["alloy"] > 0


def test_a_paused_work_costs_nothing_and_gives_nothing():
    """La cosa che mancava, e che rendeva una fonderia una condanna: un impianto in pausa non
    consuma, non produce e non pretende corrente. E' l'unico modo che il giocatore ha di dire
    "non adesso" a qualcosa che gli sta mangiando il legname."""
    busy = colony(stock={"ore": 40_000, "timber": 40_000}, works=POWERED)
    asleep = colony(stock={"ore": 40_000, "timber": 40_000}, works=POWERED,
                    idle={"smelter": 1})

    assert demand(asleep) == {}                         # non chiede piu' niente
    assert power(asleep)[1] == 0                        # ne' corrente
    assert power(asleep)[0] == power(busy)[0]           # le centrali restano accese

    # E il legname torna a crescere invece di essere mangiato.
    running_flows = net_flows(busy, "balanced", busy.stock)
    paused_flows = net_flows(asleep, "balanced", asleep.stock)
    assert paused_flows["timber"] > running_flows["timber"]
    assert paused_flows["alloy"] == 0
