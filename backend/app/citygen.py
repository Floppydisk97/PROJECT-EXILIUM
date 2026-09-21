"""The ground you actually land on.

The planet gives you one hexagon: a biome, a height, a rainfall, a temperature, a river. That
is the scale at which the shared world is decided. It is not the scale at which a colony is
played, so landing opens a second map -- a square of ground, generated for this colony and no
other.

RANDOM ONCE, THEN FOREVER. A map that is rolled afresh every time it is looked at cannot
belong to a persistent shared world: two players would see different places and what you built
yesterday would be somewhere else today. So the roll happens exactly once, at landing, and
what is kept is the SEED. Everything below is a pure function of that seed plus what the
planet says about the site, which means the map is reproducible for ever, identical for
everyone, and costs one short string per colony instead of six hundred thousand rows.

THE BIOME IS NOT DECORATION. Every knob a site turns lives in BIOME_RULES, as data: a desert
is dry, bright and bare, a rainforest is dense and wet, a tundra is stony and thin. Rainfall,
temperature and the planet's own elevation then move those defaults, so two deserts are not
the same desert. That is what makes choosing a landing site a decision rather than a formality.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from app.prng import Prng

SIZE = 768                  # cells per side: ~590k cells, about six kilometres across
CELL_METRES = 8

# How far a bank stays fertile, and by how much. A river or a shore is the strongest thing a
# site can have: it is what makes a desert worth landing on at all.
# How far the coastline wanders off its straight line, in half-map units: about
# twenty cells, which is a bay and not a fractal.
COAST_WANDER = 0.055

RIPARIAN_REACH = 260.0      # centimetres of height above the water line
RIPARIAN_GAIN = 55          # fertility added right at the water's edge
POOLING_CLIMATE = 0.40      # below this a climate does not fill its hollows, so no banks
RIPARIAN_COVER = 0.78       # vegetation right at the water's edge, whatever the biome
ALLUVIUM_REACH = 150.0

# Nessun posto e' del tutto morto. Una casella senza niente da raccogliere non e' un sito
# difficile, e' un sito che non si puo' giocare -- e il deserto e la roccia nuda erano
# esattamente quello. Queste quattro dicono il minimo che ogni terra asciutta porta comunque:
# un fondo bassissimo ovunque, piu' delle MACCHIE, che sono cio' che fa l'oasi, la radura in
# quota, la conca erbosa in mezzo alla ghiaia. A macchie e non uniforme di proposito: un
# deserto con un velo di verde dappertutto non e' un deserto, e' una steppa.
OASIS_FERTILITY_FLOOR = 12      # 0-100, su ogni cella asciutta che non sia roccia o ghiaccio
OASIS_FERTILITY_PEAK = 20       # quanto in piu' nel cuore di una macchia
OASIS_COVER_FLOOR = 0.18        # quota di suolo coperta comunque
OASIS_COVER_PEAK = 0.40
# Sopra questa forza la macchia rompe la roccia di superficie: pietraia con la terra fra i
# sassi invece di lastra nuda. E' cio' che da' da vivere a chi atterra su una vetta.
OASIS_BREAKS_ROCK = 0.55      # how far from water the ground itself becomes silt

# The ground a cell is made of. Order is the wire format, so append rather than insert.
GROUNDS = ("deep_water", "water", "marsh", "sand", "soil", "gravel", "rock", "ice")
DRY = frozenset(GROUNDS.index(name) for name in ("sand", "soil", "gravel", "rock"))
STONE = frozenset(GROUNDS.index(name) for name in ("rock", "gravel"))

# What a biome does to the ground it is made of. Data, not behaviour -- the same rule as
# `sim/config.py`, so tuning a world is reading one table instead of chasing literals.
#
#   ground      what the cell is when nothing else decides
#   fertility   0-100 before rainfall and temperature move it
#   cover       fraction of land cells carrying vegetation
#   roughness   how much the local relief departs from flat
#   wet         how readily hollows fill with water
@dataclass(frozen=True)
class BiomeRule:
    ground: str
    fertility: int
    cover: float
    roughness: float
    wet: float


BIOME_RULES = {
    "ice_sheet":          BiomeRule("ice",    0,  0.00, 0.35, 0.10),
    "snow_cap":           BiomeRule("ice",    0,  0.00, 1.40, 0.05),
    "bare_rock":          BiomeRule("rock",   4,  0.02, 1.30, 0.05),
    "tundra":             BiomeRule("gravel", 18, 0.12, 0.55, 0.35),
    "boreal_forest":      BiomeRule("soil",   42, 0.72, 0.70, 0.30),
    "temperate_forest":   BiomeRule("soil",   68, 0.80, 0.60, 0.25),
    "temperate_swamp":    BiomeRule("marsh",  74, 0.55, 0.20, 0.85),
    "arid_shrubland":     BiomeRule("gravel", 28, 0.22, 0.65, 0.10),
    "desert":             BiomeRule("sand",   8,  0.04, 0.45, 0.02),
    "tropical_rainforest":BiomeRule("soil",   88, 0.95, 0.75, 0.45),
    "tropical_swamp":     BiomeRule("marsh",  82, 0.70, 0.20, 0.90),
}
DEFAULT_RULE = BiomeRule("soil", 40, 0.40, 0.60, 0.30)


@dataclass(frozen=True)
class Site:
    """What the planet says about where the colony came down. Everything the local generator
    is allowed to know: no ids, no ownership, nothing about the database.

    `river_flow` is the flow of a river that REALLY crosses this tile, and zero when none
    does. That is not the same number the planet stores. Flow accumulation gives every land
    tile at least its own rainfall, so `world_tiles.river_flow` is above zero almost
    everywhere -- copied in raw, it drew a river across every colony on the planet, which is
    exactly what it did until somebody landed and looked. Whoever builds a Site compares the
    stored flow against `worldgen.river_min_flow` (the client reads the same number off the
    map file) and passes zero when it does not clear the bar. The globe has always drawn its
    rivers on that test; the ground now agrees with the globe."""
    biome: str
    elevation: int          # metres above sea level, from the planet tile
    temperature: float      # average degrees C
    rainfall: int           # mm/year
    river_flow: int         # 0 when no river reaches this tile
    coastal: bool           # a neighbouring planet tile is open water


@dataclass(frozen=True)
class CityMap:
    """A colony's ground, in columns -- the same shape the planet's render model uses, and for
    the same reason: one JSON object per cell would spend more bytes on field names than on
    the ground itself."""
    seed: str
    size: int
    cell_metres: int
    site: Site
    ground_names: tuple[str, ...]
    ground: tuple[int, ...]
    height: tuple[int, ...]         # centimetres above the map's own datum
    fertility: tuple[int, ...]      # 0-100
    vegetation: tuple[int, ...]     # 0-100
    # I filoni non sono una mappa per cella come gli altri: finche' non ci si costruisce
    # sopra un edificio, di un giacimento interessa QUANTO ce n'e', non dove. Il giorno in cui
    # una miniera andra' piazzata su una casella, questo diventera' uno strato come gli altri.
    ore: int = 0                    # 0-100: quota di terra asciutta che porta un filone
    heat: int = 0                   # 0-100: calore geotermico, anch'esso sotto la superficie

    @property
    def buildable(self) -> int:
        return sum(1 for g in self.ground if g in DRY)

    @property
    def economy(self) -> "SiteEconomy":
        """What this ground is worth, as three integers.

        Three, and computed HERE, because the economy must not carry a map around. A colony
        is 590.000 cells and takes seconds to grow; production is worked out every time
        somebody looks at a city. So the map is reduced once, at landing, to the only things
        the rules ask of it, and those are what the row keeps.

        Integers on purpose: a saved world has to replay identically, and the accrual is
        integer arithmetic from end to end.
        """
        cells = len(self.ground)
        # Yield is the quality of the land you can actually BUILD ON, not the average of the
        # whole map. Averaged over everything, a swamp full of water reads as middling -- it
        # is not middling, it is excellent ground you cannot put a city on, and those are two
        # different facts that the economy has to keep apart.
        usable = [f for g, f in zip(self.ground, self.fertility) if g in DRY]
        food = sum(usable) // len(usable) if usable else 0
        # Effort is what has to be cleared before anything can be built: standing growth, and
        # marsh, which has to be drained. It is what stops rich ground from being simply
        # better -- a rainforest pays more per level and takes far longer to reach the next.
        marsh = sum(1 for g in self.ground if g == GROUNDS.index("marsh"))
        greenery = sum(self.vegetation) // cells
        effort = greenery + 100 * marsh // cells
        # Timber is the standing growth ALONE. Effort adds the marsh to it, because a bog has
        # to be drained before anything can be built on it -- but a bog has no timber in it,
        # and the two would be the same number only by accident.
        stone = 100 * sum(1 for g in self.ground if g in STONE) // cells
        power = energy_potentials(self.site, self.heat)
        return SiteEconomy(food=food, timber=greenery, stone=stone, ore=self.ore,
                           effort=effort, room=self.buildable, **power)


def _clamp100(value: float) -> int:
    return int(max(0, min(100, value)))


def energy_potentials(site: Site, heat: int) -> dict[str, int]:
    """Quanta energia questo posto sa dare, per fonte. Zero-cento, come il resto.

    Non e' una quinta risorsa da raccogliere: e' l'attitudine del LUOGO, e serve a far contare
    la geografia in una direzione nuova. Il deserto era il sito povero di tutto -- niente
    roccia, niente alberi, niente cibo -- e qui diventa il posto migliore del pianeta per il
    sole. Un sito senza risorse ma pieno di energia e' una scelta, non uno scarto.
    """
    return {
        # Vento: aria che corre. Le creste e le coste, dove non c'e' niente a fermarla.
        "wind": _clamp100(18 + max(0, site.elevation) / 28.0 + (28 if site.coastal else 0)),
        # Sole: cielo sgombro e caldo. La piovosita' e' una misura di nuvole quanto d'acqua.
        "sun": _clamp100(96 - site.rainfall / 24.0 + (site.temperature - 10) / 1.8),
        # Acqua: la portata del fiume, e nient'altro. Senza fiume, niente.
        "water": _clamp100(site.river_flow / 34.0),
        # Calore: geologia nascosta, come i filoni. Non si vede dalla superficie, e per questo
        # e' l'unica delle quattro che il terreno deve dire invece di dedurre.
        "heat": heat,
    }


@dataclass(frozen=True)
class SiteEconomy:
    """What a landed colony keeps instead of its map.

    Three of these say what the ground GIVES and two what it COSTS, and no site is good at
    everything: a rainforest is food and timber with no stone under it, a gravel shrubland is
    stone with almost nothing to eat, and a desert is neither. That distribution is not
    decoration -- it is what will make one colony need another.
    """
    food: int       # 0-100: fertility of the buildable land
    timber: int     # 0-100: standing growth, the marsh excluded -- a bog has no timber
    stone: int      # 0-100: share of the map that is rock or gravel
    ore: int        # 0-100: share carrying a vein -- the only one that is not on the surface
    wind: int       # 0-100: quanto tira -- creste e coste
    sun: int        # 0-100: quanto splende -- cieli sgombri e caldo
    water: int      # 0-100: quanto scorre -- la portata del fiume
    heat: int       # 0-100: quanto scotta sotto -- geologia nascosta, come i filoni
    effort: int     # 0-200: growth AND marsh to clear -- drives how long an upgrade takes
    room: int       # buildable cells -- how far the colony grows before it starts to crowd


def seed_for(world_seed: str, tile_id: int) -> str:
    """The seed a tile's ground grows from.

    The TILE decides, not the colony that lands on it. An earlier version mixed the city id,
    so the ground was rolled at the moment of landing -- which meant nobody could ever know
    what they were landing on until they had landed. Scouting a site and then taking it is a
    better game than taking a site and then finding out, and it costs nothing: with one colony
    to a tile there is no case where two colonies would have wanted different ground from the
    same place.

    The world seed is in there so a regenerated planet does not hand out the old one's maps.
    """
    return hashlib.sha256(f"{world_seed}:{tile_id}".encode()).hexdigest()[:32]


def _rng(seed: str, salt: str) -> Prng:
    return Prng(f"{seed}:{salt}")


class PlaneNoise:
    """Band-limited noise: a sum of directional sinusoids with seeded directions, frequencies
    and phases. Continuous everywhere, so the plane this samples is valid two-dimensional
    noise.

    Its own, rather than `worldgen.BandNoise`, for one reason: this one has a twin in
    TypeScript and the two must agree number for number. That rules out anything built on a
    language's own generator, so the directions come from `Prng.direction` and the whole thing
    is spelled out in arithmetic both languages do identically.
    """

    __slots__ = ("terms", "total")

    def __init__(self, rng: Prng, octaves: int, base_freq: float):
        self.terms = []
        amp, freq, total = 1.0, base_freq, 0.0
        for _ in range(octaves):
            self.terms.append((rng.direction(), freq, rng.uniform(0.0, 2 * math.pi), amp))
            total += amp
            amp *= 0.55
            freq *= 1.9
        self.total = total

    def at(self, x: float, y: float) -> float:
        value = 0.0
        for (dx, dy, _dz), freq, phase, amp in self.terms:
            value += amp * math.sin(freq * (dx * x + dy * y) + phase)
        return value / self.total


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def generate(seed: str, site: Site, size: int = SIZE) -> CityMap:
    """The colony's ground, from a seed and what the planet said about the site."""
    rule = BIOME_RULES.get(site.biome, DEFAULT_RULE)

    # Relief. A tile high on the planet lands you somewhere steep; a coastal plain is a plain.
    # The planet's elevation is a real input, not flavour: it is why a mountain colony has to
    # be built around its rock and a delta colony does not.
    relief = PlaneNoise(_rng(seed, "relief"), 5, 3.2)
    detail = PlaneNoise(_rng(seed, "detail"), 3, 11.0)
    damp = PlaneNoise(_rng(seed, "damp"), 4, 4.5)
    grain = PlaneNoise(_rng(seed, "grain"), 3, 9.0)
    # I filoni. Un campo tutto suo, a frequenza alta perche' un giacimento e' stretto: se
    # seguisse il rilievo o il terreno di superficie non aggiungerebbe nessuna geografia --
    # sarebbe la pietra con un altro nome, e una macchia arida sarebbe ricca due volte.
    veins = PlaneNoise(_rng(seed, "veins"), 3, 13.0)
    deep = PlaneNoise(_rng(seed, "deep"), 3, 7.0)
    # The coastline wanders. Without this it is a ruled diagonal across the map --
    # at six kilometres that does not read as a coast, it reads as a canal wall.
    coast = PlaneNoise(_rng(seed, "coast"), 3, 5.5)
    # Le macchie fertili. Campo LARGO -- frequenza 2.6 contro le 9 della grana -- perche' cio'
    # che deve produrre e' un'oasi, non della polvere verde sparsa: una manciata di posti
    # buoni che si vedono da lontano e per cui vale la pena attraversare la sabbia.
    oasis = PlaneNoise(_rng(seed, "oasis"), 3, 2.6)

    altitude_roughness = 0.6 + min(2.0, max(0.0, site.elevation) / 2200.0)
    amplitude = 320.0 * rule.roughness * altitude_roughness

    # Where bare rock starts. It used to be a flat 0.62 of the relief, which is a fraction of
    # the map and so handed EVERY biome the same 16 per cent of naked stone: a rainforest with
    # continents of bare grey in it. What covers rock is vegetation, and the biome already says
    # how much it has, so the cover raises the line -- `bare_rock` (cover 0.02) keeps its stone
    # almost everywhere, a rainforest (0.95) shows it only on the real crests.
    bare_above = amplitude * (0.62 + 0.30 * rule.cover)

    # Quanto in alto si e', quanto e' probabile incontrare un filone: la roccia profonda
    # viene a giorno dove la crosta e' stata spinta su. Una foresta in quota puo' avere
    # minerale sotto, una macchia arida in pianura puo' non averne -- che e' cio' che rende
    # il minerale un asse NUOVO invece della pietra scritta due volte.
    vein_line = 0.62 - 0.30 * min(1.0, max(0, site.elevation) / 2500.0)
    heat_line = 0.30 - 0.20 * min(1.0, max(0, site.elevation) / 2500.0)

    # Where the water goes. A river on the planet becomes a river here; a coastal tile gets a
    # shore along one edge, its direction rolled from the seed so two coasts differ.
    has_river = site.river_flow > 0
    river_axis = _rng(seed, "river").uniform(0, math.pi)
    river_width = 3.0 + 9.0 * _smoothstep(math.log10(max(1, site.river_flow)) / 3.0)
    shore_angle = _rng(seed, "shore").uniform(0, 2 * math.pi)
    shore_dx, shore_dy = math.cos(shore_angle), math.sin(shore_angle)

    # Rainfall and temperature move the biome's defaults, so two deserts are not one desert.
    wetness = rule.wet + min(0.35, site.rainfall / 6000.0)
    warmth = _smoothstep((site.temperature + 15.0) / 45.0)
    fertility_base = rule.fertility * (0.55 + 0.75 * min(1.0, site.rainfall / 1800.0))
    frozen = site.temperature < -8.0

    ore_cells = 0
    heat_cells = 0
    ground: list[int] = []
    height: list[int] = []
    fertility: list[int] = []
    vegetation: list[int] = []
    water_index, deep_index = GROUNDS.index("water"), GROUNDS.index("deep_water")
    marsh_index, ice_index = GROUNDS.index("marsh"), GROUNDS.index("ice")

    for y in range(size):
        for x in range(size):
            # Normalised to [-1, 1] so the noise is sampled over a fixed patch whatever the
            # size, and a map rendered at a different resolution is the same place.
            u = (x / (size - 1)) * 2.0 - 1.0
            v = (y / (size - 1)) * 2.0 - 1.0
            h = relief.at(u, v) + 0.35 * detail.at(u, v)
            metres = h * amplitude

            # Shore: a signed distance from the map's edge in the rolled direction.
            bank = -1e9          # how close this cell is to water that REALLY exists
            depth_below = 0.0
            if site.coastal:
                toward_sea = u * shore_dx + v * shore_dy + COAST_WANDER * coast.at(u, v)
                shore_term = (toward_sea - 0.35) * 900.0
                depth_below = max(depth_below, shore_term)
                bank = max(bank, shore_term)

            # River: a channel across the map, wandering with the damp field so it is not a
            # ruled line. Width comes from the planet's own flow -- a great river is wide here.
            if has_river:
                across = (u * math.cos(river_axis) + v * math.sin(river_axis)) * 100.0
                across += 14.0 * damp.at(u, v)
                river_term = (river_width - abs(across)) * 26.0
                depth_below = max(depth_below, river_term)
                bank = max(bank, river_term)

            # Hollows fill, but only the ones deep enough for this climate to fill them.
            #
            # The floor is a fraction of the map's own relief, not a fixed depth: with a flat
            # threshold ANY positive result became water, so a desert whose wetness is three
            # hundredths still flooded its every hollow. It showed up the moment the maps were
            # looked at -- a desert with lakes down both sides -- and not before.
            pool_floor = amplitude * (0.90 - 0.65 * min(1.0, wetness))
            pool_term = (-metres - pool_floor) * (0.6 + wetness)
            depth_below = max(depth_below, pool_term)
            # A hollow only makes its banks fertile in a climate that actually fills hollows.
            # Counting it everywhere made a rainless desert bloom, because sitting just above
            # a water line that is never reached is not the same as sitting beside water.
            if wetness > POOLING_CLIMATE:
                bank = max(bank, pool_term)

            if depth_below > 0:
                metres -= depth_below
                kind = deep_index if depth_below > 260 else water_index
                if frozen:
                    kind = ice_index
                ground.append(kind)
                height.append(int(metres))
                fertility.append(0)
                vegetation.append(0)
                continue

            # Dry land. The biome decides what it is made of; height and grain decide where
            # the exceptions are -- bare rock on the tops, marsh in the damp hollows.
            name = rule.ground
            if frozen:
                name = "ice"
            elif metres > bare_above and rule.ground != "sand":
                name = "rock"
            elif metres < -amplitude * 0.30 and wetness > 0.55:
                name = "marsh"
            elif rule.ground == "soil" and grain.at(u, v) > 0.55:
                name = "gravel"
            # Quanto questa cella sta dentro una macchia fertile: 0 fuori, 1 nel cuore.
            patch = _smoothstep((oasis.at(u, v) - 0.05) * 2.4)
            # La macchia rompe la lastra: dove la terra si e' fatta strada fra i sassi il
            # terreno e' pietraia, non roccia viva, e su una pietraia qualcosa cresce. Vale
            # anche in cresta, di proposito: una palude d'alta quota aveva come unica terra
            # asciutta le sue creste di roccia nuda, quindi `food` zero su trecento celle
            # edificabili -- un sito che si puo' prendere e non si puo' giocare. E non toglie
            # niente alla montagna: la pietraia conta come pietra esattamente come la roccia.
            if name == "rock" and patch > OASIS_BREAKS_ROCK:
                name = "gravel"
            if name in ("sand", "gravel") and bank > -ALLUVIUM_REACH and not frozen:
                # What a river leaves on its banks is silt, not the desert it crossed. Without
                # this the bank kept the biome's sand, which halves fertility AFTER the bank
                # bonus is added -- so the one reason to land in a desert was quietly worth
                # less than half of what the rule said it was.
                name = "soil"

            if veins.at(u, v) > vein_line:
                ore_cells += 1
            # Il calore sta piu' in profondita' dei filoni, quindi il suo campo e' piu' largo:
            # un giacimento e' stretto, un'anomalia termica e' una regione.
            if deep.at(u, v) > heat_line:
                heat_cells += 1

            index = GROUNDS.index(name)
            slope_penalty = 1.0 - _smoothstep(abs(metres) / max(1.0, amplitude)) * 0.45
            # Water makes its banks fertile whatever the biome says. Without this a desert
            # river was a blue line through dead sand, when a river in a desert is the ONLY
            # reason to land there -- the site would have looked interesting on the planet
            # and been worthless on the ground. `depth_below` is already how far this cell
            # sits above the water that would have covered it, so the band comes free.
            riparian = _smoothstep(1.0 + bank / RIPARIAN_REACH)
            cell_fertility = 0
            if index not in (ice_index, GROUNDS.index("rock")):
                cell_fertility = int(fertility_base * slope_penalty * (0.6 + 0.6 * warmth))
                cell_fertility += int(RIPARIAN_GAIN * riparian * (0.4 + 0.6 * warmth))
                if index == marsh_index:
                    cell_fertility = int(cell_fertility * 1.15)
                if index == GROUNDS.index("sand"):
                    cell_fertility = int(cell_fertility * 0.45)
                # Il fondo, DOPO le penalita': una duna resta una duna, ma non e' sterile.
                cell_fertility = max(
                    cell_fertility,
                    int(OASIS_FERTILITY_FLOOR + OASIS_FERTILITY_PEAK * patch),
                )
            cell_fertility = max(0, min(100, cell_fertility))

            # Water brings cover as well as fertility. Without this a desert river was a
            # fertile strip nobody could see and nothing grew on: the biome's `cover` of four
            # hundredths applied right up to the water's edge.
            cover = rule.cover + (RIPARIAN_COVER - rule.cover) * riparian
            cover *= 0.5 + 0.5 * (0.5 + 0.5 * grain.at(u, v))
            # E il fondo anche qui, se no la fertilita' minima restava un numero che nessuno
            # vedeva: terra buona e pelata. Alberi dove la macchia e' forte, ciuffi altrove.
            cover = max(cover, OASIS_COVER_FLOOR + OASIS_COVER_PEAK * patch)
            cell_vegetation = 0
            if cell_fertility > 0:
                cell_vegetation = max(0, min(100, int(100 * cover * (cell_fertility / 100.0) ** 0.5)))

            ground.append(index)
            height.append(int(metres))
            fertility.append(cell_fertility)
            vegetation.append(cell_vegetation)

    return CityMap(
        seed=seed, size=size, cell_metres=CELL_METRES, site=site,
        ground_names=GROUNDS, ground=tuple(ground), height=tuple(height),
        fertility=tuple(fertility), vegetation=tuple(vegetation),
        ore=100 * ore_cells // (size * size),
        heat=100 * heat_cells // (size * size),
    )
