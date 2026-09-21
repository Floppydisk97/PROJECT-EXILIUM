"""The rules of ruleset 2: pure functions from state to described effects.

These are deliberately per-entity rather than one function over the whole world. The world is
shared and persistent, and different players' cities are meant to proceed in parallel -- they
serialise only on their own row, never on each other. A rule that demanded the entire world as
its argument would quietly undo that: every read of one city would have to load, and therefore
lock, all of them.

There used to be one exception, the tick, which held the world exclusively because it settled
every city at once. It is gone, and with it the barrier. What made that possible is that
policy became a timeline instead of a single current value -- see `production_amount`.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from collections.abc import Mapping

from app.sim.config import (
    MAX_LEVEL, MAX_WORKS, POWER_SITES, RESOURCES, WORKS, food_income, food_upkeep,
    harvest_rate, power_made, production_rate, store_cap, supported_level, upgrade_cost,
    upgrade_duration, work_cost, work_duration,
)
from app.sim.state import (
    Advance, CityState, Commitment, Completion, LedgerEntry, PolicyPeriod, Settlement,
)


def _whole_seconds(*moments: datetime) -> None:
    for moment in moments:
        if moment.tzinfo is None:
            raise ValueError("Timezone-aware timestamps required")
        if moment.microsecond:
            raise ValueError("Production timestamps must have whole-second precision")


def production_amount(
    start: datetime, end: datetime, periods: list[PolicyPeriod], level: int,
    site_food: int = 0,
) -> int:
    """Milli-alloy matured over an interval, integrated across the policies it crosses.

    Integer arithmetic at one-second granularity, so splitting an interval anywhere gives the
    same total as not splitting it -- which is what lets production accrue during downtime
    without a job running every second.

    The periods argument is the whole reason the tick could be removed. Production is paid at
    the rate the time actually had; with one policy per call, the only way to guarantee that
    was to settle every city at the moment of a change, before letting the new rate start.
    That is a global barrier. Integrating instead means a city works out its own history, when
    somebody looks at it, without holding anyone else still.

    An interval not covered by any period is a bug rather than free alloy, so it is refused.

    `site_food` is the colony's ground, and it multiplies the rate rather than the total:
    the rate has to be one integer per slice, or splitting an interval would not give the
    same answer as not splitting it.
    """
    _whole_seconds(start, end)
    if end < start or level < 0:
        raise ValueError("Invalid production interval or level")
    if end == start:
        return 0

    total = 0
    covered = 0
    for period in periods:
        slice_start = max(start, period.from_at)
        slice_end = end if period.to_at is None else min(end, period.to_at)
        if slice_end <= slice_start:
            continue
        elapsed = slice_end - slice_start
        seconds = elapsed.days * 86400 + elapsed.seconds
        covered += seconds
        total += seconds * production_rate(period.policy, level, site_food)

    whole = end - start
    if covered != whole.days * 86400 + whole.seconds:
        raise ValueError("Policy timeline does not cover the production interval")
    return total


def majority_policy(current: str, votes: dict[str, int]) -> str:
    """Simple majority, one standing vote per city. A tie or an empty ballot keeps what is in
    force: a vote nobody contested must not be able to change anything.

    Continuous now rather than counted at a boundary -- a city holds its preference and the
    majority is whatever the held preferences currently say.
    """
    balanced = votes.get("balanced", 0)
    industrial = votes.get("industrial", 0)
    if balanced == industrial:
        return current
    return "balanced" if balanced > industrial else "industrial"


HARVESTED = ("food", "timber", "stone", "ore")


def resource_rate(resource: str, policy: str, city: CityState) -> int:
    """Cio' che la TERRA da', al secondo. Le opere non c'entrano: questo e' il raccolto."""
    if resource == "food":
        # La terra da' quello che da'; le bocche si moltiplicano col livello. Da qui il tetto
        # vero della colonia, garantito positivo da `supported_level`.
        return food_income(city.site_food, policy) - food_upkeep(city.level)
    if resource not in HARVESTED:
        return 0
    site = {"timber": city.site_timber, "stone": city.site_stone, "ore": city.site_ore}[resource]
    return harvest_rate(resource, city.level, site, policy)


def running(city: CityState) -> dict[str, int]:
    """Quante opere di ciascun tipo stanno davvero girando. Le spente non contano: un
    impianto in pausa non consuma, non produce e non pretende corrente."""
    return {kind: max(0, count - city.idle.get(kind, 0))
            for kind, count in city.works.items() if count - city.idle.get(kind, 0) > 0}


def power(city: CityState) -> tuple[int, int]:
    """Corrente prodotta e corrente pretesa, al secondo.

    Un flusso, non una scorta. Nessuno la mette in magazzino: cio' che non si produce adesso
    non si consuma adesso, e gli impianti che ne chiedono girano piu' piano.
    """
    made = used = 0
    for kind, count in running(city).items():
        work = WORKS[kind]
        if "from" in work:
            made += power_made(kind, getattr(city, f"site_{work['from']}")) * count
        used += work.get("draw", 0) * count
    return made, used


def demand(city: CityState) -> dict[str, int]:
    """Cio' che le opere ACCESE vorrebbero consumare al secondo, se girassero a pieno."""
    wanted: dict[str, int] = {}
    for kind, count in running(city).items():
        for resource, per_second in WORKS[kind].get("inputs", {}).items():
            wanted[resource] = wanted.get(resource, 0) + per_second * count
    return wanted


def supply(city: CityState) -> dict[str, int]:
    """Cio' che le opere ACCESE renderebbero al secondo, se girassero a pieno."""
    made: dict[str, int] = {}
    for kind, count in running(city).items():
        for resource, per_second in WORKS[kind].get("outputs", {}).items():
            made[resource] = made.get(resource, 0) + per_second * count
    return made


def throttle(city: CityState, policy: str, stock: Mapping[str, int]) -> int:
    """A quanti millesimi della propria capacita' girano le opere, ADESSO.

    Due cose le rallentano, e sono la stessa cosa vista da due lati.

    Un INGRESSO: un'opera tira dal magazzino finche' ce n'e', quindi puo' girare a pieno anche
    consumando piu' di quanto arrivi -- sta svuotando un buffer. Quando il buffer e' a zero
    puo' girare solo al ritmo con cui l'ingresso arriva. E' questo che rende necessaria
    l'integrazione a eventi: il momento in cui si esaurisce cambia il tasso.

    La CORRENTE: che e' un ingresso senza buffer, sempre. Se ne serve piu' di quanta se ne
    produce, tutti gli impianti vanno alla stessa frazione -- non se ne sceglie uno da
    spegnere, perche' quella scelta e' del giocatore e si fa mettendo in pausa.
    """
    wanted = demand(city)
    made, used = power(city)
    running_at = 1000
    if used > 0:
        running_at = min(running_at, 1000 * made // used)
    if not wanted:
        return running_at
    for resource, per_second in wanted.items():
        if stock.get(resource, 0) > 0 or per_second <= 0:
            continue
        arriving = max(0, resource_rate(resource, policy, city))
        running_at = min(running_at, 1000 * arriving // per_second)
    return running_at


def net_flows(city: CityState, policy: str, stock: Mapping[str, int]) -> dict[str, int]:
    """Il bilancio al secondo di ogni risorsa: raccolto, meno cio' che le opere consumano,
    piu' cio' che rendono. Un intero per risorsa, valido finche' nessuna scorta cambia stato."""
    running = throttle(city, policy, stock)
    flows = {resource: resource_rate(resource, policy, city) for resource in RESOURCES}
    for resource, per_second in demand(city).items():
        flows[resource] = flows.get(resource, 0) - per_second * running // 1000
    for resource, per_second in supply(city).items():
        flows[resource] = flows.get(resource, 0) + per_second * running // 1000
    return flows


# Quanti cambi di regime si accettano dentro una sola liquidazione. Ogni risorsa puo'
# ragionevolmente cambiare stato due volte -- tocca lo zero, tocca il tetto -- quindi questo
# e' abbondante. Esiste perche' un giorno una catena mal fatta potrebbe oscillare, e un ciclo
# infinito dentro una richiesta e' il modo peggiore di scoprirlo.
MAX_EVENTS = 64


def _seconds(span) -> int:
    return span.days * 86400 + span.seconds


def settle_city(
    city: CityState, until: datetime, periods: list[PolicyPeriod]
) -> Settlement | None:
    """Portare i magazzini di questa citta' fino a `until`. None se il cursore e' gia' li'.

    Finche' le risorse si limitavano a salire, questo era una moltiplicazione: la scorta
    cresceva a tasso costante e bastava fermarla al tetto. Una CATENA rompe quella comodita',
    perche' consuma: se il minerale e' finito mercoledi', la fonderia si e' fermata mercoledi'
    e il tasso di giovedi' non e' quello di martedi'.

    Quindi si integra a EVENTI. Fra un evento e l'altro tutto e' lineare, quindi il momento in
    cui una scorta tocca lo zero o il tetto si CALCOLA invece di aspettarlo: si salta li', si
    ricalcolano i tassi, si prosegue. Nessun tick e' tornato -- una colonia ferma da un anno
    si liquida ancora in una manciata di passi, non in trentun milioni.
    """
    _whole_seconds(city.settled_at, until)
    if until < city.settled_at:
        raise ValueError("Invalid production interval")
    if until == city.settled_at:
        return None

    cap = store_cap(city.level)
    stock = dict(city.stock)
    opening = dict(city.stock)

    covered = 0
    for period in periods:
        slice_start = max(city.settled_at, period.from_at)
        slice_end = until if period.to_at is None else min(until, period.to_at)
        if slice_end <= slice_start:
            continue
        remaining = _seconds(slice_end - slice_start)
        covered += remaining

        for _ in range(MAX_EVENTS):
            if remaining <= 0:
                break
            flows = net_flows(city, period.policy, stock)
            step = remaining
            for resource, rate in flows.items():
                held = stock.get(resource, 0)
                if rate > 0 and held < cap:
                    step = min(step, -(-(cap - held) // rate))      # ceil: al tetto, non oltre
                elif rate < 0 and held > 0:
                    step = min(step, -(-held // -rate))
            step = max(1, min(step, remaining))
            for resource, rate in flows.items():
                held = stock.get(resource, 0)
                stock[resource] = max(0, min(cap, held + rate * step))
            remaining -= step
        else:
            # Non e' un caso da ignorare: significa che i tassi continuano a cambiare, cioe'
            # che una catena oscilla. Meglio rifiutare rumorosamente che pagare un anno con
            # l'economia dell'ultimo secondo.
            raise ValueError("Troppi cambi di regime in una sola liquidazione")

    if covered != _seconds(until - city.settled_at):
        raise ValueError("Policy timeline does not cover the production interval")

    entries = tuple(
        LedgerEntry(city.id, stock[resource] - opening.get(resource, 0), "production",
                    f"production:{city.id}:{resource}:"
                    f"{city.settled_at.isoformat()}:{until.isoformat()}",
                    until, resource)
        for resource in sorted(stock)
        if stock[resource] != opening.get(resource, 0)
    )
    return Settlement(city=replace(city, settled_at=until, stock=stock), entries=entries)


def advance_city(
    city: CityState,
    commitment: Commitment | None,
    periods: list[PolicyPeriod],
    now: datetime,
) -> Advance:
    """Everything that has happened to one city between its cursor and now.

    The order is the rule, not an implementation detail. A commitment that came due at some
    point in the middle splits the interval: production before it is earned at the OLD level,
    the commitment then completes, and production after it is earned at the new one. Settling
    the whole stretch first and raising the level afterwards would pay the past at a rate the
    past did not have -- the same mistake the tick's boundary existed to prevent, which does
    not stop being a mistake just because the boundary is gone.
    """
    _whole_seconds(now)
    settlements: list[Settlement] = []
    completions: list[Completion] = []

    if commitment is not None and commitment.completes_at <= now:
        settlement = settle_city(city, commitment.completes_at, periods)
        if settlement is not None:
            settlements.append(settlement)
            city = settlement.city
        if commitment.kind == "work":
            # Da questo istante la colonia consuma e produce di piu': la fetta successiva va
            # calcolata con l'opera IN PIEDI, non con quella di prima. E' la stessa ragione
            # per cui un avanzamento spezza l'intervallo.
            built = dict(city.works)
            built[commitment.choice] = built.get(commitment.choice, 0) + 1
            city = replace(city, works=built)
            completions.append(Completion(commitment.id, "work_built", city.level))
        else:
            city = replace(city, level=city.level + 1)
            completions.append(Completion(commitment.id, "level_increased", city.level))

    settlement = settle_city(city, now, periods)
    if settlement is not None:
        settlements.append(settlement)
        city = settlement.city

    return Advance(city=city, settlements=tuple(settlements), completions=tuple(completions))


def begin_upgrade(
    city: CityState, busy: bool, now: datetime
) -> tuple[tuple[LedgerEntry, ...], datetime] | str:
    """Start an upgrade, or say in one word why not.

    The materials leave now: committing IS spending, so a city cannot queue four upgrades out
    of one store and cannot take the stone back out from under a commitment already running.
    What it buys is a moment in the future, and until then it is busy.

    The food check is a REFUSAL and not a punishment. A colony that grew past what its ground
    feeds would starve with no way back, and landing is irreversible -- so the level that
    cannot be fed is the level that cannot be started. It is measured against the least
    favourable policy, because the majority votes on how fast everyone goes, not on who
    survives.
    """
    _whole_seconds(now)
    if busy:
        return "already_busy"
    if city.level >= MAX_LEVEL:
        return "maximum_level"
    if city.level + 1 > supported_level(city.site_food):
        return "not_enough_food"
    cost = upgrade_cost(city.level, city.site_room)
    for resource, amount in sorted(cost.items()):
        if city.stock.get(resource, 0) < amount:
            return f"insufficient_{resource}"
    entries = tuple(
        LedgerEntry(city.id, -amount, "upgrade",
                    f"upgrade:{city.id}:{resource}:{now.isoformat()}", now, resource)
        for resource, amount in sorted(cost.items())
    )
    return entries, now + upgrade_duration(city.level, city.site_effort, city.site_room)


def begin_work(
    city: CityState, busy: bool, kind: str, now: datetime
) -> tuple[tuple[LedgerEntry, ...], datetime] | str:
    """Costruire un'opera, o dire in una parola perche' no.

    Stessa forma dell'avanzamento, e non per pigrizia: la scarsita' di questo gioco e'
    l'ATTENZIONE. Una colonia fa una cosa alla volta, quindi mettere in piedi una fonderia
    significa non star crescendo, e crescere significa non star costruendo fonderie. E' li'
    che sta la scelta, non nel magazzino.
    """
    _whole_seconds(now)
    if kind not in WORKS:
        return "unknown_work"
    if busy:
        return "already_busy"
    if city.works.get(kind, 0) >= MAX_WORKS:
        return "too_many_works"
    for resource, amount in sorted(work_cost(kind).items()):
        if city.stock.get(resource, 0) < amount:
            return f"insufficient_{resource}"
    entries = tuple(
        LedgerEntry(city.id, -amount, "upgrade",
                    f"work:{city.id}:{kind}:{resource}:{now.isoformat()}", now, resource)
        for resource, amount in sorted(work_cost(kind).items())
    )
    return entries, now + work_duration(kind)
