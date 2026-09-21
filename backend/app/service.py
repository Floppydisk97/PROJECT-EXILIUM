"""The adapter between the simulation and the database.

Every rule of the game lives in `app/sim/`, which cannot see PostgreSQL. This module is the
seam: it loads rows into simulation state, asks the rules what should happen, and writes the
described effects back inside one transaction. It also owns what is genuinely the database's
job and not the simulation's -- locking, authorisation, idempotency and the clock.

THE LOCK MODEL, which is the whole reason the rules are per-entity.

There is no global barrier any more. A city is advanced under a lock on its OWN row: two
requests touching the same city serialise, and two touching different cities do not meet at
all. The tick used to take `world FOR UPDATE` and settle everybody at once, which is what put
a ceiling on how many players the world could hold.

What is left of the world row is the policy timeline, and it is locked only when the majority
actually changes -- a short lock on a handful of rows, not a stall over every city.
"""
import hashlib
import secrets

import psycopg
from uuid import uuid4

from app import db
from app import citygen
from app import worldgen
from app.sim import CityState, Commitment, PolicyPeriod, advance_city, begin_upgrade
from app.sim.rules import begin_work
from app.sim.config import (
    ALL_RESOURCES, POWER_SITES, RESOURCES, RULESET, STARTING_STOCK, WORKS, power_made,
    store_cap, supported_level, time_to_full, upgrade_cost, upgrade_duration, work_cost,
    work_duration,
)
from app.sim.rules import majority_policy, net_flows, power, throttle


class DomainError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def owned_city(conn, city_id, owner_id, lock=False):
    # lock=True takes a row lock on this city only: concurrent advances of the SAME city
    # serialize (no duplicate production, no two commitments), while different cities proceed
    # in parallel. Read-only authorization checks pass lock=False.
    suffix = " FOR UPDATE" if lock else ""
    city = conn.execute(
        "SELECT * FROM cities WHERE id = %s AND owner_id = %s" + suffix, (city_id, owner_id)
    ).fetchone()
    if city is None:
        raise DomainError(404, "City not found")
    return city


def works(conn, city_id) -> tuple[dict[str, int], dict[str, int]]:
    """Le opere costruite e quante ne sono spente, per tipo. Zero non si conserva: un'opera
    che non c'e' non e' una riga con un conteggio a zero, e' una riga che non esiste."""
    rows = conn.execute(
        "SELECT kind, count, idle FROM city_works WHERE city_id = %s AND count > 0", (city_id,)
    ).fetchall()
    return ({row["kind"]: int(row["count"]) for row in rows},
            {row["kind"]: int(row["idle"]) for row in rows if row["idle"]})


def stock(conn, city_id) -> dict[str, int]:
    """Every store this city holds. O(1) reads of the materialized cursors: the ledger
    trigger keeps each one exactly equal to SUM(resource_ledger.amount) for that resource,
    which `test_materialized_balance_*` guards."""
    rows = conn.execute(
        "SELECT resource, amount_milli FROM city_stock WHERE city_id = %s", (city_id,)
    ).fetchall()
    held = {row["resource"]: int(row["amount_milli"]) for row in rows}
    return {resource: held.get(resource, 0) for resource in ALL_RESOURCES}


def balance(conn, city_id) -> int:
    """The alloy store alone. Ruleset 2 minted it; nothing mints it now, and it is still
    spendable -- what was earned is not confiscated because the rules moved on."""
    return stock(conn, city_id)["alloy"]


def entry(conn, city_id, amount, reason, event_key, effective_at, resource="alloy"):
    conn.execute(
        """INSERT INTO resource_ledger(city_id, resource, amount, reason, event_key,
                                       effective_at, ruleset)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (city_id, resource, amount, reason, event_key, effective_at, RULESET),
    )


def write_entry(conn, described):
    entry(conn, described.city_id, described.amount, described.reason,
          described.event_key, described.effective_at, described.resource)


def city_state(row, held: dict[str, int] | None = None,
               built: dict[str, int] | None = None,
               idle: dict[str, int] | None = None) -> CityState:
    """A database row as the simulation sees it: nothing about ownership or naming, which
    are the adapter's business, and no column the rules do not actually read.

    The stores come in as an argument rather than as a column, because they live in their own
    table now -- passing them explicitly is what stops a caller silently settling a city
    against empty stores.
    """
    return CityState(
        id=row["id"],
        level=row["level"],
        settled_at=row["settled_at"],
        stock=held or {},
        works=built or {},
        idle=idle or {},
        # What the colony kept of its ground. Null until it lands -- and null is not zero
        # room, it is no ground to be crowded against, which is what an orbiting colony has.
        site_food=row["site_food"] or 0,
        site_timber=row["site_timber"] or 0,
        site_stone=row["site_stone"] or 0,
        site_ore=row["site_ore"] or 0,
        site_wind=row["site_wind"] or 0,
        site_sun=row["site_sun"] or 0,
        site_water=row["site_water"] or 0,
        site_heat=row["site_heat"] or 0,
        site_effort=row["site_effort"] or 0,
        site_room=row["site_room"],
    )


def policy_periods(conn, since) -> list[PolicyPeriod]:
    """The policy timeline covering everything from `since` onwards.

    Only the periods a city still has to settle across are loaded, which is normally one.
    A world whose policy changes daily and a city untouched for a year would load a year of
    them -- bounded by how often the majority actually moves, not by how many cities exist.
    """
    rows = conn.execute(
        """SELECT policy, from_at, to_at FROM policy_periods
           WHERE to_at IS NULL OR to_at > %s
           ORDER BY from_at""",
        (since,),
    ).fetchall()
    return [PolicyPeriod(r["policy"], r["from_at"], r["to_at"]) for r in rows]


def current_policy(conn) -> str:
    return conn.execute(
        "SELECT policy FROM policy_periods WHERE to_at IS NULL"
    ).fetchone()["policy"]


def commitment_of(conn, city_id) -> Commitment | None:
    row = conn.execute(
        "SELECT id, city_id, kind, choice, completes_at FROM orders "
        "WHERE city_id = %s AND status = 'pending'",
        (city_id,),
    ).fetchone()
    return None if row is None else Commitment(
        row["id"], row["city_id"], row["kind"], row["completes_at"], row["choice"]
    )


def advance(conn, city_row, now):
    """Bring one city up to `now`: finish what came due, then mature its production.

    This is what the tick was, narrowed to a single city. It runs lazily -- whenever somebody
    looks at the city or asks it to do something -- so a world with nobody watching costs
    nothing and a city nobody touches is still correct the moment it is read.
    """
    city = city_state(city_row, stock(conn, city_row["id"]), *works(conn, city_row["id"]))
    result = advance_city(
        city, commitment_of(conn, city_row["id"]), policy_periods(conn, city.settled_at), now
    )
    for settlement in result.settlements:
        for described in settlement.entries:
            write_entry(conn, described)
    for completion in result.completions:
        conn.execute(
            "UPDATE orders SET status = 'applied', outcome = %s WHERE id = %s",
            (completion.outcome, completion.commitment_id),
        )
    # Le opere che sono state messe in piedi durante questa liquidazione. Scritte qui e non
    # nelle regole, che descrivono e non applicano mai.
    if result.city.works != city.works:
        for kind, count in result.city.works.items():
            conn.execute(
                """INSERT INTO city_works (city_id, kind, count) VALUES (%s, %s, %s)
                   ON CONFLICT (city_id, kind) DO UPDATE SET count = EXCLUDED.count""",
                (result.city.id, kind, count),
            )
    if result.settlements or result.completions:
        conn.execute(
            "UPDATE cities SET settled_at = %s, level = %s WHERE id = %s",
            (result.city.settled_at, result.city.level, result.city.id),
        )
    return result


def provision(conn, name):
    if not 1 <= len(name.strip()) <= 80:
        raise DomainError(422, "City name must contain 1-80 characters")
    now = db.database_now(conn)
    owner, city, token = uuid4(), uuid4(), secrets.token_urlsafe(32)
    conn.execute("INSERT INTO players VALUES (%s, %s, %s)", (owner, token_hash(token), now))
    conn.execute(
        "INSERT INTO cities(id, owner_id, name, created_at, settled_at) VALUES (%s, %s, %s, %s, %s)",
        (city, owner, name.strip(), now, now),
    )
    # Le scorte con cui si scende. Una per risorsa: il ledger e' per risorsa, e "genesis"
    # deve leggersi come tutto il resto invece che essere un caso a parte.
    for resource, amount in sorted(STARTING_STOCK.items()):
        entry(conn, city, amount, "genesis", f"genesis:{city}:{resource}", now, resource)
    return {"player_id": owner, "city_id": city, "token": token}


def stall_forecast(conn, city_row, now) -> dict[str, int | None]:
    """Fra quanti secondi ogni magazzino smettera' di guadagnare. None se non si fermera'.

    Calcolato con la politica in vigore, che e' l'onesto: una politica diversa e' un mondo
    diverso, e prometterlo per una che non e' stata votata sarebbe una previsione di comodo.
    """
    held = stock(conn, city_row["id"])
    cap = store_cap(city_row["level"])
    policy = current_policy(conn)
    city = city_state(city_row, held, *works(conn, city_row["id"]))
    # I flussi NETTI, non il raccolto. La lega non si raccoglie: la fonde un'opera, e una
    # previsione fatta sul solo raccolto diceva "fermo" di una risorsa che stava crescendo.
    flows = net_flows(city, policy, held)
    forecast: dict[str, int | None] = {}
    for resource in RESOURCES:
        seconds = time_to_full(held[resource], cap, flows.get(resource, 0))
        forecast[resource] = None if seconds is None else int(seconds)
    return forecast


def works_view(conn, city_row) -> dict:
    """Le opere, il regime a cui girano e il bilancio della corrente.

    La corrente si riporta come DUE numeri e non come una scorta, perche' e' un flusso: se
    la si mostrasse come un magazzino, la prima domanda del giocatore sarebbe "quanta ne ho
    da parte", e la risposta onesta e' che non se ne ha mai da parte.
    """
    held = stock(conn, city_row["id"])
    built, idle = works(conn, city_row["id"])
    city = city_state(city_row, held, built, idle)
    made, used = power(city)
    return {
        "works": built,
        "works_idle": idle,
        "work_permille": throttle(city, current_policy(conn), held),
        "power_made": made,
        "power_used": used,
        # Cosa sa dare questo posto, per fonte. Un pannello in un deserto e uno sotto la
        # pioggia sono lo stesso pannello e non sono la stessa centrale.
        "site_power": {name: city_row[f"site_{name}"] or 0 for name in POWER_SITES},
        "catalogue": {
            kind: {
                "label": work["label"],
                "inputs": work.get("inputs", {}),
                "outputs": work.get("outputs", {}),
                "draw": work.get("draw", 0),
                "power": (power_made(kind, city_row[f"site_{work['from']}"] or 0)
                          if "from" in work else 0),
                "from": work.get("from"),
                "cost_milli": {r: str(a) for r, a in work_cost(kind).items()},
                "seconds": int(work_duration(kind).total_seconds()),
            }
            for kind, work in WORKS.items()
        },
    }


def city_view(conn, city_row, now) -> dict:
    busy = commitment_of(conn, city_row["id"])
    level = city_row["level"]
    return {
        "id": city_row["id"], "name": city_row["name"], "level": level,
        "stock_milli": {name: str(amount) for name, amount in stock(conn, city_row["id"]).items()},
        "alloy_milli": str(balance(conn, city_row["id"])),
        "settled_at": now,
        "policy": current_policy(conn),
        "policy_vote": city_row["policy_vote"],
        # What it would take to start the next upgrade, so a client never has to know the
        # curve: the rules own it and say so.
        "next_upgrade_cost_milli": {name: str(amount)
                                    for name, amount in upgrade_cost(level, city_row["site_room"]).items()},
        "next_upgrade_seconds": int(upgrade_duration(
            level, city_row["site_effort"] or 0, city_row["site_room"]).total_seconds()),
        # Il tetto che la terra impone, e quando ogni magazzino smettera' di guadagnare.
        # Il secondo numero e' cio' che rende accettabile lo stallo in un mondo che cammina
        # mentre il giocatore dorme: fermarsi e' la tensione voluta, fermarsi A SORPRESA e'
        # una faccenda da sbrigare. Detto prima, si pianifica.
        "supported_level": supported_level(city_row["site_food"] or 0),
        "stalls_in_seconds": stall_forecast(conn, city_row, now),
        # Le opere, e a che regime stanno girando. Il secondo numero e' cio' che spiega un
        # magazzino che non cresce come ci si aspettava: una fonderia a secco non si ferma,
        # rallenta, e senza dirlo sembrerebbe soltanto che i conti non tornino.
        **works_view(conn, city_row),
        "busy_until": None if busy is None else busy.completes_at,
        "busy_with": None if busy is None else busy.kind,
    }


def read_city(conn, city_id, owner_id):
    city = owned_city(conn, city_id, owner_id, lock=True)
    now = db.database_now(conn)
    advance(conn, city, now)
    return city_view(conn, owned_city(conn, city_id, owner_id), now)


def start_upgrade(conn, city_id, owner_id, key):
    """Commit this city to an upgrade. The alloy goes now; the level arrives later.

    Idempotent on `key`, because a retried request must not spend twice -- the same guarantee
    the order queue used to give, kept now that there is no queue.
    """
    city_row = owned_city(conn, city_id, owner_id, lock=True)
    previous = conn.execute(
        "SELECT * FROM orders WHERE city_id = %s AND idempotency_key = %s", (city_id, key)
    ).fetchone()
    if previous:
        return previous

    now = db.database_now(conn)
    result = advance(conn, city_row, now)
    decision = begin_upgrade(result.city, commitment_of(conn, city_id) is not None, now)
    if isinstance(decision, str):
        raise DomainError(409, decision)
    spends, completes_at = decision
    for described in spends:
        write_entry(conn, described)
    # `cost_milli` records what the commitment took, summed across resources. It is a record
    # of the past, not an input to anything: what it cost is already gone from the stores.
    return conn.execute(
        """INSERT INTO orders(city_id, idempotency_key, kind, choice, submitted_at,
                              completes_at, cost_milli)
           VALUES (%s, %s, 'upgrade', NULL, %s, %s, %s) RETURNING *""",
        (city_id, key, now, completes_at, sum(-described.amount for described in spends)),
    ).fetchone()


def start_work(conn, city_id, owner_id, kind, key):
    """Impegnare questa citta' a costruire un'opera. Stessa forma dell'avanzamento, e non per
    pigrizia: una colonia fa una cosa alla volta, quindi costruire una fonderia significa non
    star crescendo. E' li' che sta la scelta."""
    city_row = owned_city(conn, city_id, owner_id, lock=True)
    previous = conn.execute(
        "SELECT * FROM orders WHERE city_id = %s AND idempotency_key = %s", (city_id, key)
    ).fetchone()
    if previous:
        return previous

    now = db.database_now(conn)
    result = advance(conn, city_row, now)
    decision = begin_work(result.city, commitment_of(conn, city_id) is not None, kind, now)
    if isinstance(decision, str):
        raise DomainError(409, decision)
    spends, completes_at = decision
    for described in spends:
        write_entry(conn, described)
    return conn.execute(
        """INSERT INTO orders(city_id, idempotency_key, kind, choice, submitted_at,
                              completes_at, cost_milli)
           VALUES (%s, %s, 'work', %s, %s, %s, %s) RETURNING *""",
        (city_id, key, kind, now, completes_at,
         sum(-described.amount for described in spends)),
    ).fetchone()


def set_work_running(conn, city_id, owner_id, kind, wanted):
    """Accendere o spegnere impianti di un tipo. Istantaneo: e' un interruttore, non un lavoro.

    E' la mancanza piu' grave che il gradino precedente aveva lasciato: una fonderia mangiava
    il legname per sempre, e siccome il legname serve anche a costruire, un solo impianto
    poteva bloccare la crescita di una colonia senza che il giocatore potesse farci niente.
    Un impianto in pausa non consuma, non produce e non pretende corrente.
    """
    if kind not in WORKS:
        raise DomainError(422, "unknown_work")
    city_row = owned_city(conn, city_id, owner_id, lock=True)
    # Prima si porta la citta' al presente: cio' che ha prodotto FINO A ORA lo ha prodotto
    # col vecchio assetto, e spegnere un impianto non deve riscrivere l'ultima ora.
    advance(conn, city_row, db.database_now(conn))

    built, _idle = works(conn, city_id)
    have = built.get(kind, 0)
    if not have:
        raise DomainError(409, "no_such_work")
    if not 0 <= wanted <= have:
        raise DomainError(422, "out_of_range")
    conn.execute(
        "UPDATE city_works SET idle = %s WHERE city_id = %s AND kind = %s",
        (have - wanted, city_id, kind),
    )
    return works_view(conn, owned_city(conn, city_id, owner_id))


def demolish_work(conn, city_id, owner_id, kind):
    """Abbattere un impianto. Niente rimborso, e va detto: cio' che e' stato messo in opera
    e' stato messo in opera. Chi vuole solo fermarlo ha la pausa."""
    if kind not in WORKS:
        raise DomainError(422, "unknown_work")
    city_row = owned_city(conn, city_id, owner_id, lock=True)
    advance(conn, city_row, db.database_now(conn))

    built, idle = works(conn, city_id)
    have = built.get(kind, 0)
    if not have:
        raise DomainError(409, "no_such_work")
    # Si abbatte per prima una gia' spenta, se ce n'e': e' l'unica scelta che non cambia
    # cio' che la colonia sta producendo in questo istante.
    stopped = max(0, idle.get(kind, 0) - 1)
    conn.execute(
        "UPDATE city_works SET count = %s, idle = %s WHERE city_id = %s AND kind = %s",
        (have - 1, min(stopped, have - 1), city_id, kind),
    )
    return works_view(conn, owned_city(conn, city_id, owner_id))


def cast_vote(conn, city_id, owner_id, choice):
    """Set this city's standing preference and, if the majority moved, close the current
    policy period and open a new one.

    The world row is locked for the length of that decision so two votes cannot both think
    they flipped it. It is one row, held for one statement -- not the old barrier, which held
    every city still for as long as it took to settle all of them.
    """
    if choice not in ("balanced", "industrial"):
        raise DomainError(422, "Vote must be 'balanced' or 'industrial'")
    owned_city(conn, city_id, owner_id, lock=True)
    conn.execute("SELECT 1 FROM world WHERE id = 1 FOR UPDATE")
    conn.execute("UPDATE cities SET policy_vote = %s WHERE id = %s", (choice, city_id))

    votes = {
        row["policy_vote"]: int(row["n"]) for row in conn.execute(
            "SELECT policy_vote, count(*) AS n FROM cities "
            "WHERE policy_vote IS NOT NULL GROUP BY policy_vote"
        ).fetchall()
    }
    standing = current_policy(conn)
    elected = majority_policy(standing, votes)
    if elected != standing:
        now = db.database_now(conn)
        open_from = conn.execute(
            "SELECT from_at FROM policy_periods WHERE to_at IS NULL"
        ).fetchone()["from_at"]
        if open_from == now:
            # Two changes inside the same second. A period of zero length is not a period --
            # it would cover no production and could not be told apart from the one it
            # replaced -- so the standing one is corrected rather than closed and reopened.
            conn.execute(
                "UPDATE policy_periods SET policy = %s WHERE to_at IS NULL", (elected,)
            )
        else:
            conn.execute("UPDATE policy_periods SET to_at = %s WHERE to_at IS NULL", (now,))
            conn.execute(
                "INSERT INTO policy_periods(policy, from_at) VALUES (%s, %s)", (elected, now)
            )
    return {"policy_vote": choice, "policy": elected, "votes": votes}


def _site_of(conn, tile_id: int) -> tuple[citygen.Site, dict]:
    """What the planet says about a tile, in the shape the local generator accepts.

    `coastal` is a property of the NEIGHBOURHOOD, not of the tile: a colony is on the coast
    when open water is next door. It is worked out here rather than stored because the map is
    immutable, so the answer can never go stale, and a column would be one more thing that has
    to be right at generation time.
    """
    row = conn.execute(
        """SELECT t.id, t.biome, t.elevation, t.temperature, t.rainfall, t.river_flow,
                  t.landmass_size, t.lat, t.lon, m.frequency,
                  EXISTS (SELECT 1 FROM world_tiles n
                          WHERE n.map_id = t.map_id AND n.id = ANY(t.neighbors)
                            AND n.biome IN ('ocean', 'sea_ice')) AS coastal
           FROM world_tiles t JOIN world_map m ON m.id = t.map_id
           WHERE t.map_id = 1 AND t.id = %s""",
        (tile_id,),
    ).fetchone()
    if row is None:
        raise DomainError(404, "No such tile on this world")
    site = citygen.Site(
        biome=row["biome"], elevation=row["elevation"], temperature=row["temperature"],
        rainfall=row["rainfall"], river_flow=river_of(row["river_flow"], row["frequency"]),
        coastal=row["coastal"],
    )
    return site, row


def river_of(stored_flow: int, frequency: int) -> int:
    """The flow of a river that really crosses this tile, or zero.

    `world_tiles.river_flow` is accumulated drainage, and every land tile drains at least its
    own rainfall, so it is above zero almost everywhere. `citygen` took it at face value and
    put a river through the middle of every colony on the planet -- on a tile carrying a flow
    of two, which is a wet patch, not a watercourse. The globe has always drawn its rivers
    above `worldgen.river_min_flow`; this is the same test, so the ground and the globe now
    say the same thing about the same tile.

    The threshold comes from the size of the map actually stored, via its frequency, and not
    from a constant: a smaller world generated for a test has a smaller bar, and hard-coding
    the production number would have quietly drained every river out of the test worlds.
    """
    return stored_flow if stored_flow >= worldgen.river_min_flow(10 * frequency**2 + 2) else 0


def land(conn, city_id, owner_id, tile_id: int) -> dict:
    """Put a colony on a tile, once and for all.

    Three things are refused, and each is a rule rather than a technicality: a colony already
    down cannot move, water cannot be landed on, and a tile already taken is taken. The last is
    what makes a site worth choosing -- there is exactly one river in that desert, and if
    somebody else is on it there is not another.
    """
    city = owned_city(conn, city_id, owner_id, lock=True)
    if city["tile_id"] is not None:
        raise DomainError(409, "already_landed")

    site, tile = _site_of(conn, tile_id)
    if tile["elevation"] < 0 or site.biome in ("ocean", "lake", "sea_ice"):
        raise DomainError(409, "not_dry_land")

    now = db.database_now(conn)
    seed = citygen.seed_for(world_seed(conn), tile_id)
    # Il sito viene RILEVATO una volta sola, qui, e ridotto ai numeri che l'economia chiede.
    # Da nessun'altra parte: il rilevamento e' mezzo milione di campioni, cioe' secondi, e la
    # produzione si ricalcola ogni volta che qualcuno guarda una colonia.
    #
    # `survey` e non `generate`: la mappa che si guarda e' fatta di 2,36 milioni di esagoni da
    # un metro quadro, e generarla qui sarebbe sedici secondi dentro questa richiesta. Il
    # rilevamento ha una risoluzione sua, fissa, ed e' la stessa che il visore usa per mostrare
    # i numeri prima dell'atterraggio -- che e' il motivo per cui i due non possono divergere.
    economy = citygen.survey(seed, site)
    if economy.room == 0:
        # Dry by elevation and yet nothing to build on: an ice cap, a glacier, a mountain that
        # is frozen end to end. Landing is IRREVERSIBLE -- a trigger refuses to move a colony
        # once it is down -- so allowing this would create a colony that can never build
        # anything, for ever, with no way back. Hard ground is a choice; no ground is a trap.
        # The viewer already shows the buildable count before anybody commits.
        raise DomainError(409, "no_ground")
    try:
        conn.execute(
            """UPDATE cities SET tile_id = %s, landed_at = %s, map_seed = %s,
                                 site_food = %s, site_timber = %s, site_stone = %s,
                                 site_ore = %s, site_wind = %s, site_sun = %s,
                                 site_water = %s, site_heat = %s,
                                 site_effort = %s, site_room = %s
               WHERE id = %s""",
            (tile_id, now, seed, economy.food, economy.timber, economy.stone, economy.ore,
             economy.wind, economy.sun, economy.water, economy.heat,
             economy.effort, economy.room, city_id),
        )
    except psycopg.errors.UniqueViolation:
        raise DomainError(409, "tile_taken")
    return {"tile_id": tile_id, "landed_at": now, "biome": site.biome,
            "coastal": site.coastal, "river_flow": site.river_flow,
            "site_food": economy.food, "site_timber": economy.timber,
            "site_stone": economy.stone, "site_ore": economy.ore,
            "site_wind": economy.wind, "site_sun": economy.sun,
            "site_water": economy.water, "site_heat": economy.heat,
            "site_effort": economy.effort,
            "site_room": economy.room}


def world_seed(conn) -> str:
    return conn.execute("SELECT seed FROM world_map WHERE id = 1").fetchone()["seed"]


def city_ground(conn, city_id, owner_id) -> dict:
    """What the colony's ground GROWS FROM -- the seed, and what the planet says about the
    site. Not the cells.

    It used to send the cells, and at 128 a side that was merely wasteful. At 768 it is a way
    for one authenticated caller to take the server down: 590.000 cells is 9 MB of JSON and
    nearly three seconds of CPU, held inside a transaction, on an instance that has a tenth of
    one CPU and a hundred-second ceiling. The rate limit allows a hundred and twenty of those
    a minute from a single address.

    And it bought nothing. The cells are a pure function of exactly what is returned here, and
    the client computes them in four tenths of a second -- faster than the server can, and
    without the round trip. So this sends the seed and lets the ground grow where it is looked
    at.

    The server keeps its own generator (`citygen.py`) because it must be able to say where a
    thing may be built. That is a small question asked about one cell; it is not a reason to
    ship the whole map.
    """
    city = owned_city(conn, city_id, owner_id)
    if city["tile_id"] is None:
        raise DomainError(409, "not_landed")
    site, _tile = _site_of(conn, city["tile_id"])
    return {
        "city_id": city["id"], "tile_id": city["tile_id"], "seed": city["map_seed"],
        "size": citygen.SIZE, "hex_width_m": citygen.HEX_WIDTH_M,
        "site": {
            "biome": site.biome, "elevation": site.elevation,
            "temperature": site.temperature, "rainfall": site.rainfall,
            "river_flow": site.river_flow, "coastal": site.coastal,
        },
        "ground_names": list(citygen.GROUNDS),
    }
