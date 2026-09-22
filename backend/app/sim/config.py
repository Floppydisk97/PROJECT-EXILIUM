"""Balancing constants for ruleset 2. Data, not behaviour.

Every number the economy turns on lives here, so balancing is reading one file rather than
grepping for literals. `RULESET` stamps every ledger row: a world records which rules
produced it, so a future change to these numbers is a new ruleset and not a silent rewrite
of history. It used to be stamped on the tick; with no tick, each movement carries it.
"""
from datetime import timedelta
from typing import TypedDict

RULESET = 2

# Production, in milli-alloy per second. Integers only: the economy must never depend on
# float rounding, since a saved world has to replay identically.
POLICY_RATES = {"balanced": 10, "industrial": 20}
LEVEL_RATE = 5          # each productive level adds this much per second
STARTING_ALLOY = 100_000        # ruleset 2: non si conia piu', ma cio' che c'e' resta

# Cio' con cui si scende. Una colonia che atterra senza niente non potrebbe costruire il
# primo edificio prima di aver raccolto per ore, e la prima ora di gioco sarebbe un'attesa.
# Bastano per il primo avanzamento e avanza qualcosa.
STARTING_STOCK = {"food": 100_000, "timber": 100_000, "stone": 100_000}
MAX_LEVEL = 1_000_000

# An upgrade costs alloy AND time, and both grow with the level being left behind.
#
# Time is the one that matters. With production compounding (every level adds LEVEL_RATE per
# second) and a flat cost, the game measured out as a pure exponential with nothing to decide:
# the only strategy was to spend the moment you could afford it. What a continuous world has
# instead of a queue is scarcity of ATTENTION -- a city does one thing at a time, so choosing
# to start something is choosing not to start anything else until it finishes.
#
# Starting numbers, not balanced ones. At level 0 an upgrade is an hour of world time and 100
# alloy; at level 10 it is eleven hours and 1100. Turn them here.
UPGRADE_COST = 100_000
UPGRADE_DURATION = timedelta(hours=1)


# What the ground is worth. Ruleset 2: before it, where you landed changed the view and
# nothing else, so choosing a site was a formality with a scenery.
#
# Three numbers, measured on the colony's own map at landing (see `citygen.SiteEconomy`), and
# deliberately pulling in different directions -- because one number would only ever produce a
# ranking, and a ranking is not a decision. Rich ground pays more per level and takes far
# longer to reach the next; open poor ground pays almost nothing per level and accumulates
# them without end. Simulated over a year of world time, the fertile site leads by 37 per cent
# at ten days and the desert has passed it by the end: neither is the answer, which is the
# point.
YIELD_BASE = 150        # rate is multiplied by (YIELD_BASE + yield) / YIELD_BASE: 1.00 .. 1.67
EFFORT_WEIGHT = 4       # an upgrade lasts (100 + EFFORT_WEIGHT * effort) / 100 as long
ROOM_PER_LEVEL = 150    # buildable cells a level takes before the colony starts to crowd


# Le risorse. La lega non si produce piu': tornera' come primo PRODOTTO della prima catena,
# che e' il posto in cui avrebbe dovuto stare dall'inizio. Cio' che e' stato guadagnato resta
# spendibile -- non si confisca -- semplicemente non se ne conia altra.
RESOURCES = ("food", "timber", "stone", "ore", "alloy")
ALL_RESOURCES = RESOURCES

# Milli-unita' al secondo. La terra rende quello che rende: il cibo NON cresce col livello,
# mentre il consumo si'. Da qui viene il tetto vero della colonia -- un sito fertile regge una
# citta' grande, uno arido una piccola -- e non e' una manopola in piu', e' la stessa
# fertilita' gia' misurata che decide un'altra cosa.
FOOD_BASE = 25          # cio' che la colonia si coltiva da sola ovunque, anche sul ghiaccio
FOOD_FROM_LAND = 250    # cio' che ci aggiunge la terra, in proporzione alla sua fertilita'
FOOD_UPKEEP = 6         # per livello: piu' gente, piu' bocche

# Legname e pietra si RACCOLGONO, quindi piu' braccia raccolgono di piu': questi scalano col
# livello. Un sito senza roccia non produce pietra affatto -- ed e' voluto, perche' e' cio'
# che un giorno fara' servire una colonia a un'altra.
TIMBER_RATE = 40
STONE_RATE = 40
# Piu' alto degli altri non perche' scavare sia facile, ma perche' il minerale ha una SCALA
# diversa: la pietra copre 0-99 della mappa, i filoni 7-22. Lo stesso moltiplicatore avrebbe
# reso ogni fonderia affamata dieci a uno, che non e' un bilanciamento -- e' un'unita' di
# misura sbagliata travestita da scelta di gioco.
ORE_RATE = 75
# Anche la terra piu' spoglia da' qualcosa: si cava la propria ghiaia, si recupera. Senza
# questo un deserto -- niente roccia, niente alberi -- non potrebbe costruire MAI nulla, e
# sarebbe un vicolo cieco in attesa di un commercio che ancora non esiste.
HARVEST_FLOOR = 12

# Il magazzino. Pieno significa FERMO: quella risorsa smette di accumularsi finche' non se ne
# spende. E' la tensione di Anno, ed e' innocua -- non si perde cio' che si ha, si smette di
# guadagnare -- purche' il momento in cui accadra' sia prevedibile. Lo e': `time_to_full`.
STORE_BASE = 2_000_000          # due unita' di magazzino appena scesi
STORE_PER_LEVEL = 1_000_000


def production_rate(policy: str, level: int, site_food: int = 0) -> int:
    """Milli-lega al secondo. Ruleset 2, e non produce piu' nulla nel ruleset 3.

    Tenuta perche' la storia di un mondo si legge con le regole che l'hanno prodotta, e il
    ledger timbra ogni riga con il proprio ruleset.
    """
    return ((POLICY_RATES[policy] + level * LEVEL_RATE) * (YIELD_BASE + site_food)) // YIELD_BASE


# La politica sposta cio' che la colonia fa delle proprie braccia. Senza la lega non avrebbe
# piu' nulla da spostare, e il voto -- che e' l'unica cosa condivisa fra tutti i giocatori --
# sarebbe diventato decorativo.
POLICY_SHIFT = {
    "balanced":   {"food": 100, "timber": 100, "stone": 100, "ore": 100},
    "industrial": {"food":  80, "timber": 125, "stone": 125, "ore": 125},
}


def food_income(site_food: int, policy: str = "balanced") -> int:
    """Milli-cibo al secondo che la TERRA da'. Non dipende dal livello: un campo rende quanto
    rende, e sono le bocche a moltiplicarsi."""
    return (FOOD_BASE + FOOD_FROM_LAND * site_food // 100) * POLICY_SHIFT[policy]["food"] // 100


def food_upkeep(level: int) -> int:
    """Milli-cibo al secondo che la colonia mangia."""
    return FOOD_UPKEEP * level


def supported_level(site_food: int) -> int:
    """Il livello piu' alto che questa terra riesce a nutrire.

    E' il motivo per cui non esiste una spirale della fame: avanzare oltre cio' che il sito
    sfama viene RIFIUTATO, invece di essere permesso e poi punito con una colonia che non si
    puo' piu' salvare. Atterrare e' definitivo; un vicolo cieco in piu' non serviva a nessuno.
    """
    # Col la politica PIU' SFAVOREVOLE, non con quella in vigore. La politica la vota la
    # maggioranza, e una maggioranza non deve poter far morire di fame una colonia che aveva
    # fatto i conti giusti: il voto sposta quanto vai forte, non se sopravvivi.
    worst = min(shift["food"] for shift in POLICY_SHIFT.values())
    return ((FOOD_BASE + FOOD_FROM_LAND * site_food // 100) * worst // 100) // FOOD_UPKEEP


def harvest_rate(resource: str, level: int, site: int, policy: str = "balanced") -> int:
    """Milli-unita' al secondo di cio' che si raccoglie. Un intero per l'intera fetta su cui
    viene usato, per la stessa ragione di sempre: spezzare un intervallo non deve cambiare il
    totale."""
    base = {"timber": TIMBER_RATE, "stone": STONE_RATE, "ore": ORE_RATE}[resource]
    gathered = base * (level + 1) * max(site, HARVEST_FLOOR) // 100
    return gathered * POLICY_SHIFT[policy][resource] // 100


# LE OPERE. Una colonia costruisce impianti che consumano, producono, e chiedono CORRENTE.
#
# L'energia non e' una quinta risorsa da accumulare: e' un FLUSSO. Se si potesse mettere in
# magazzino, una colonia ne banchereb­be di notte e il vincolo sparirebbe -- si tornerebbe a
# "abbastanza prima o poi", che non e' una decisione. Come flusso invece e' il caso che lo
# strozzatore gia' sa trattare: un ingresso senza buffer, che limita sempre al ritmo con cui
# arriva.
#
# E lega la geografia in una direzione nuova. Il deserto era il sito povero di tutto -- niente
# roccia, niente alberi, niente cibo -- e qui diventa il posto migliore del pianeta per il
# sole. Un luogo senza risorse ma pieno di energia e' una scelta, non uno scarto.
# Che cos'e' un'opera. Scritto, invece che lasciato indovinare.
#
# Senza, il tipo di `WORKS[kind]["hours"]` e' `object` -- perche' i valori sono di tipi
# diversi -- e ogni conto fatto su di essi e' un conto su un `object`. Funziona, e nessun
# controllo puo' dire se funzionera' ancora domani: e' esattamente il genere di cosa che
# marcisce in silenzio, come e' gia' successo a `colonyexport`.
#
# Nella forma con le virgolette e non con `class`, perche' una delle voci si chiama `from` e
# `from` e' una parola riservata: si puo' scrivere come chiave, non come attributo.
#
# `total=False` perche' le opere non hanno tutte le stesse voci: solo la fonderia trasforma
# (`inputs`/`outputs`) e consuma corrente (`draw`), e le centrali la producono (`power`,
# `from` -- da quale attitudine del sito dipende la resa). Le tre che ci sono sempre sono
# etichetta, costo e durata.
Work = TypedDict("Work", {
    "label": str,
    "cost": dict[str, int],
    "hours": int,
    "inputs": dict[str, int],
    "outputs": dict[str, int],
    "draw": int,
    "power": int,
    "from": str,
}, total=False)


WORKS: dict[str, Work] = {
    "smelter": {
        "label": "Fonderia",
        "inputs": {"ore": 10, "timber": 8},
        "outputs": {"alloy": 6},
        "draw": 14,                  # milli-corrente al secondo che pretende
        "cost": {"stone": 120_000, "timber": 120_000},
        "hours": 3,
    },
    "windfarm": {
        "label": "Eolico",
        "power": 30, "from": "wind",  # resa = power * attitudine del sito / 100
        "cost": {"stone": 60_000, "timber": 100_000},
        "hours": 2,
    },
    "solar": {
        "label": "Solare",
        "power": 26, "from": "sun",
        "cost": {"stone": 40_000, "alloy": 30_000},
        "hours": 2,
    },
    "hydro": {
        "label": "Idroelettrico",
        "power": 40, "from": "water",
        "cost": {"stone": 200_000, "timber": 80_000},
        "hours": 6,
    },
    "geothermal": {
        "label": "Geotermico",
        "power": 48, "from": "heat",
        "cost": {"stone": 160_000, "alloy": 60_000},
        "hours": 8,
    },
}
WORK_KINDS = tuple(WORKS)
POWER_SITES = ("wind", "sun", "water", "heat")

MAX_WORKS = 8           # per tipo: oltre, una colonia sarebbe una fabbrica e non un insediamento


def work_cost(kind: str) -> dict[str, int]:
    return dict(WORKS[kind]["cost"])


def work_duration(kind: str) -> timedelta:
    return timedelta(hours=WORKS[kind]["hours"])


def power_made(kind: str, site: int) -> int:
    """Milli-corrente al secondo che un impianto di questo tipo rende QUI. Un pannello in un
    deserto e uno sotto la pioggia sono lo stesso pannello e non sono la stessa centrale."""
    work = WORKS[kind]
    return work.get("power", 0) * site // 100


# Da questo livello in su un avanzamento vuole anche LEGA, che non si raccoglie: si fonde.
# Senza questo la catena produrrebbe un numero che nessuno spende -- lo stesso difetto che il
# cibo ha oggi, e che qui sarebbe stato voluto invece che ereditato.
ALLOY_FROM_LEVEL = 3
UPGRADE_ALLOY = 40_000


def store_cap(level: int) -> int:
    """Quanto ci sta, per risorsa. Cresce col livello: una colonia piu' grande ha magazzini
    piu' grandi, quindi crescere e' anche il modo di smettere di traboccare."""
    return STORE_BASE + STORE_PER_LEVEL * level


def time_to_full(stock: int, cap: int, rate: int) -> float | None:
    """Fra quanti secondi questa scorta smette di guadagnare. Zero se e' gia' ferma, None se
    non si fermera\' -- due stati diversi che sembrerebbero uguali se si confondessero: uno
    chiede di spendere, l'altro dice che quella risorsa qui non arriva.

    Il numero che rende lo stallo una strategia invece che una sorpresa: una colonia che si
    guarda da lontano deve poter dire quando smettera' di guadagnare, non scoprirlo tornando.
    """
    if stock >= cap:
        return 0.0          # gia' fermo: non e' la stessa cosa di "non si fermera' mai"
    if rate <= 0:
        return None
    return (cap - stock) / rate


def crowding(level: int, room: int | None) -> int:
    """How far past its room the colony is reaching. Zero while there is space.

    A soft ceiling, not a wall: landing is irreversible, so a colony that ran out of ground
    must get slower and dearer, never finished. `room=None` is a colony with no ground yet --
    it has not landed -- and it is not crowded by nothing.
    """
    if room is None:
        return 0
    return max(0, level + 1 - room // ROOM_PER_LEVEL)


# Si costruisce con pietra e legname. I numeri sono scelti perche' i siti si SERVANO a
# vicenda: una macchia arida arriva alla pietra in venticinque minuti e al legname in quattro
# ore, una foresta pluviale esattamente al contrario. Sono l'immagine speculare l'una
# dell'altra, ed e' li' che nascera' il commercio.
UPGRADE_STONE = 60_000
UPGRADE_TIMBER = 60_000


def upgrade_cost(level: int, room: int | None = None) -> dict[str, int]:
    """Cio' che costa l'avanzamento che si lascia alle spalle `level`, per risorsa."""
    factor = (level + 1) * (1 + crowding(level, room))
    cost = {"stone": UPGRADE_STONE * factor, "timber": UPGRADE_TIMBER * factor}
    if level + 1 >= ALLOY_FROM_LEVEL:
        cost["alloy"] = UPGRADE_ALLOY * factor
    return cost


def upgrade_duration(level: int, effort: int = 0, room: int | None = None) -> timedelta:
    """World time that upgrade occupies the city for.

    Whole seconds always, which the database requires: the hour is divisible by a hundred, so
    the effort multiplier can never introduce a fraction of a second.
    """
    stretched = UPGRADE_DURATION * (level + 1) * (100 + EFFORT_WEIGHT * effort) // 100
    return stretched * (1 + crowding(level, room))