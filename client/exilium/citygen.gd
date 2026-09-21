# Il terzo gemello di `backend/app/citygen.py`, riga per riga.
#
# Due copie di una regola sola sono il modo in cui questo progetto si e' gia' fatto male sei
# volte; tre sarebbero peggio, se non fosse che la terza entra sotto la stessa disciplina
# delle prime due. Il lato Python scrive `frontend/app/colony/reference.json` -- cinque siti,
# ogni cella -- e `tests/run.gd` li rigenera qui e li confronta. Una cella di scarto fa
# fallire il test.
#
# Perche' una copia in GDScript: il client diventa un'applicazione, e chiedere al server che
# aspetto ha il terreno rimetterebbe un'istanza addormentata sulla strada del semplice
# guardare. Il SERVER resta l'autorita' su tutto cio' che viene DECISO -- cosa si costruisce,
# di chi e' cosa. Questa copia serve per guardare.
class_name Citygen
extends RefCounted

const Prng := preload("res://exilium/prng.gd")

const GROUNDS := ["deep_water", "water", "marsh", "sand", "soil", "gravel", "rock", "ice"]

const SIZE := 1536
const HEX_AREA_M2 := 1.0
const SURVEY_SIZE := 768

const COAST_WANDER := 0.055
const RIPARIAN_REACH := 260.0
const RIPARIAN_GAIN := 55
const POOLING_CLIMATE := 0.40
const RIPARIAN_COVER := 0.78
const ALLUVIUM_REACH := 150.0

const OASIS_FERTILITY_FLOOR := 12
const OASIS_FERTILITY_PEAK := 20
const OASIS_COVER_FLOOR := 0.18
const OASIS_COVER_PEAK := 0.40
const OASIS_BREAKS_ROCK := 0.55

# Calcolate e non trascritte, esattamente come nelle altre due copie: una costante scritta a
# mano in tre lingue e' la forma piu' pura del difetto da cui tutto questo ci difende.
static func hex_side_m() -> float:
	return sqrt(2.0 / (3.0 * sqrt(3.0)))

static func hex_width_m() -> float:
	return sqrt(3.0) * hex_side_m()

static func row_ratio() -> float:
	return sqrt(3.0) / 2.0

# ground, fertility, cover, roughness, wet
const BIOME_RULES := {
	"ice_sheet":           ["ice",    0,  0.00, 0.35, 0.10],
	"snow_cap":            ["ice",    0,  0.00, 1.40, 0.05],
	"bare_rock":           ["rock",   4,  0.02, 1.30, 0.05],
	"tundra":              ["gravel", 18, 0.12, 0.55, 0.35],
	"boreal_forest":       ["soil",   42, 0.72, 0.70, 0.30],
	"temperate_forest":    ["soil",   68, 0.80, 0.60, 0.25],
	"temperate_swamp":     ["marsh",  74, 0.55, 0.20, 0.85],
	"arid_shrubland":      ["gravel", 28, 0.22, 0.65, 0.10],
	"desert":              ["sand",   8,  0.04, 0.45, 0.02],
	"tropical_rainforest": ["soil",   88, 0.95, 0.75, 0.45],
	"tropical_swamp":      ["marsh",  82, 0.70, 0.20, 0.90],
}
const DEFAULT_RULE := ["soil", 40, 0.40, 0.60, 0.30]


static func smoothstep_(t: float) -> float:
	var c := clampf(t, 0.0, 1.0)
	return c * c * (3.0 - 2.0 * c)


static func clamp100(value: float) -> int:
	return int(clampf(value, 0.0, 100.0))


## Rumore a banda limitata: somma di sinusoidi con direzione, frequenza e fase prese dal seme.
class PlaneNoise extends RefCounted:
	var dirs_x := PackedFloat64Array()
	var dirs_y := PackedFloat64Array()
	var freqs := PackedFloat64Array()
	var phases := PackedFloat64Array()
	var amps := PackedFloat64Array()
	var total := 0.0

	func _init(rng, octaves: int, base_freq: float) -> void:
		var amp := 1.0
		var freq := base_freq
		for i in range(octaves):
			var d = rng.direction()
			dirs_x.append(d[0])
			dirs_y.append(d[1])
			freqs.append(freq)
			phases.append(rng.uniform(0.0, 2.0 * PI))
			amps.append(amp)
			total += amp
			amp *= 0.55
			freq *= 1.9

	func at(x: float, y: float) -> float:
		var value := 0.0
		for i in range(amps.size()):
			value += amps[i] * sin(freqs[i] * (dirs_x[i] * x + dirs_y[i] * y) + phases[i])
		return value / total


static func rng_for(seed_text: String, salt: String):
	return Prng.new("%s:%s" % [seed_text, salt])


## Il seme da cui cresce il terreno di una casella. Lo decide la CASELLA, non chi ci atterra
## sopra, cosi' un sito si puo' valutare prima di prenderlo. Gemello di `citygen.seed_for`.
static func seed_for(world_seed: String, tile_id: int) -> String:
	var digest := ("%s:%d" % [world_seed, tile_id]).to_utf8_buffer()
	var ctx := HashingContext.new()
	ctx.start(HashingContext.HASH_SHA256)
	ctx.update(digest)
	return ctx.finish().hex_encode().substr(0, 32)


## Il terreno di una colonia, dal seme e da quel che il pianeta ha detto del sito.
##
## `site` e' un dizionario con biome, elevation, temperature, rainfall, river_flow, coastal.
static func generate(seed_text: String, site: Dictionary, size: int = SIZE) -> Dictionary:
	var rule = BIOME_RULES.get(site["biome"], DEFAULT_RULE)
	var rule_ground: String = rule[0]
	var rule_fertility: float = float(rule[1])
	var rule_cover: float = rule[2]
	var rule_roughness: float = rule[3]
	var rule_wet: float = rule[4]

	var relief := PlaneNoise.new(rng_for(seed_text, "relief"), 5, 3.2)
	var detail := PlaneNoise.new(rng_for(seed_text, "detail"), 3, 11.0)
	var damp := PlaneNoise.new(rng_for(seed_text, "damp"), 4, 4.5)
	var grain := PlaneNoise.new(rng_for(seed_text, "grain"), 3, 9.0)
	var veins := PlaneNoise.new(rng_for(seed_text, "veins"), 3, 13.0)
	var deep := PlaneNoise.new(rng_for(seed_text, "deep"), 3, 7.0)
	var coast := PlaneNoise.new(rng_for(seed_text, "coast"), 3, 5.5)
	var oasis := PlaneNoise.new(rng_for(seed_text, "oasis"), 3, 2.6)

	var elevation := float(site["elevation"])
	var altitude_roughness: float = 0.6 + minf(2.0, maxf(0.0, elevation) / 2200.0)
	var amplitude: float = 320.0 * rule_roughness * altitude_roughness
	var bare_above: float = amplitude * (0.62 + 0.30 * rule_cover)
	var vein_line: float = 0.62 - 0.30 * minf(1.0, maxf(0.0, elevation) / 2500.0)
	var heat_line: float = 0.30 - 0.20 * minf(1.0, maxf(0.0, elevation) / 2500.0)

	var river_flow := float(site["river_flow"])
	var has_river := river_flow > 0
	var river_axis: float = rng_for(seed_text, "river").uniform(0.0, PI)
	var river_width: float = 3.0 + 9.0 * smoothstep_(log(maxf(1.0, river_flow)) / log(10.0) / 3.0)
	var shore_angle: float = rng_for(seed_text, "shore").uniform(0.0, 2.0 * PI)
	var shore_dx := cos(shore_angle)
	var shore_dy := sin(shore_angle)
	var river_cos := cos(river_axis)
	var river_sin := sin(river_axis)

	var rainfall := float(site["rainfall"])
	var temperature := float(site["temperature"])
	var wetness: float = rule_wet + minf(0.35, rainfall / 6000.0)
	var warmth := smoothstep_((temperature + 15.0) / 45.0)
	var fertility_base: float = rule_fertility * (0.55 + 0.75 * minf(1.0, rainfall / 1800.0))
	var frozen := temperature < -8.0
	var coastal: bool = site["coastal"]

	var cells := size * size
	var ground := PackedByteArray()
	var height := PackedInt32Array()
	var fertility := PackedByteArray()
	var vegetation := PackedByteArray()
	ground.resize(cells)
	height.resize(cells)
	fertility.resize(cells)
	vegetation.resize(cells)

	var i_water := GROUNDS.find("water")
	var i_deep := GROUNDS.find("deep_water")
	var i_marsh := GROUNDS.find("marsh")
	var i_ice := GROUNDS.find("ice")
	var i_rock := GROUNDS.find("rock")
	var i_sand := GROUNDS.find("sand")
	var pool_floor: float = amplitude * (0.90 - 0.65 * minf(1.0, wetness))

	var ore_cells := 0
	var heat_cells := 0
	var half := float(size - 1) / 2.0
	var ratio := row_ratio()

	for y in range(size):
		var shift := 0.5 * float(y & 1)
		var v := (float(y) - half) * ratio / half
		for x in range(size):
			var u := (float(x) + shift - half) / half
			var at := y * size + x
			var metres: float = (relief.at(u, v) + 0.35 * detail.at(u, v)) * amplitude

			var bank: float = -1e9
			var depth_below: float = 0.0
			if coastal:
				var toward_sea: float = u * shore_dx + v * shore_dy + COAST_WANDER * coast.at(u, v)
				var shore_term: float = (toward_sea - 0.35) * 900.0
				depth_below = maxf(depth_below, shore_term)
				bank = maxf(bank, shore_term)
			if has_river:
				var across: float = (u * river_cos + v * river_sin) * 100.0 + 14.0 * damp.at(u, v)
				var river_term: float = (river_width - absf(across)) * 26.0
				depth_below = maxf(depth_below, river_term)
				bank = maxf(bank, river_term)
			var pool_term: float = (-metres - pool_floor) * (0.6 + wetness)
			depth_below = maxf(depth_below, pool_term)
			if wetness > POOLING_CLIMATE:
				bank = maxf(bank, pool_term)

			if depth_below > 0:
				metres -= depth_below
				var kind := i_deep if depth_below > 260 else i_water
				if frozen:
					kind = i_ice
				ground[at] = kind
				height[at] = int(metres)
				continue

			var name := rule_ground
			if frozen:
				name = "ice"
			elif metres > bare_above and rule_ground != "sand":
				name = "rock"
			elif metres < -amplitude * 0.30 and wetness > 0.55:
				name = "marsh"
			elif rule_ground == "soil" and grain.at(u, v) > 0.55:
				name = "gravel"
			var patch: float = smoothstep_((oasis.at(u, v) - 0.05) * 2.4)
			if name == "rock" and patch > OASIS_BREAKS_ROCK:
				name = "gravel"
			if (name == "sand" or name == "gravel") and bank > -ALLUVIUM_REACH and not frozen:
				name = "soil"

			if veins.at(u, v) > vein_line:
				ore_cells += 1
			if deep.at(u, v) > heat_line:
				heat_cells += 1

			var index := GROUNDS.find(name)
			var slope_penalty: float = 1.0 - smoothstep_(absf(metres) / maxf(1.0, amplitude)) * 0.45
			var riparian: float = smoothstep_(1.0 + bank / RIPARIAN_REACH)
			var cell_fertility := 0
			if index != i_ice and index != i_rock:
				cell_fertility = int(fertility_base * slope_penalty * (0.6 + 0.6 * warmth))
				cell_fertility += int(RIPARIAN_GAIN * riparian * (0.4 + 0.6 * warmth))
				if index == i_marsh:
					cell_fertility = int(float(cell_fertility) * 1.15)
				if index == i_sand:
					cell_fertility = int(float(cell_fertility) * 0.45)
				cell_fertility = maxi(
					cell_fertility,
					int(OASIS_FERTILITY_FLOOR + OASIS_FERTILITY_PEAK * patch))
			cell_fertility = clampi(cell_fertility, 0, 100)

			var cover: float = rule_cover + (RIPARIAN_COVER - rule_cover) * riparian
			cover *= 0.5 + 0.5 * (0.5 + 0.5 * grain.at(u, v))
			cover = maxf(cover, OASIS_COVER_FLOOR + OASIS_COVER_PEAK * patch)
			var cell_vegetation := 0
			if cell_fertility > 0:
				cell_vegetation = clampi(
					int(100.0 * cover * sqrt(float(cell_fertility) / 100.0)), 0, 100)

			ground[at] = index
			height[at] = int(metres)
			fertility[at] = cell_fertility
			vegetation[at] = cell_vegetation

	return {
		"seed": seed_text, "size": size, "hex_width_m": hex_width_m(), "site": site,
		"ground_names": GROUNDS, "ground": ground, "height": height,
		"fertility": fertility, "vegetation": vegetation,
		"ore": 100 * ore_cells / cells, "heat": 100 * heat_cells / cells,
	}


## Quanto vale un posto: la stessa risposta che da' il server, alla stessa risoluzione fissa.
static func survey(seed_text: String, site: Dictionary) -> Dictionary:
	return economy_of(generate(seed_text, site, SURVEY_SIZE))


## I numeri che una colonia tiene al posto della sua mappa. Gemello di `CityMap.economy`.
static func economy_of(made: Dictionary) -> Dictionary:
	var ground: PackedByteArray = made["ground"]
	var fertility: PackedByteArray = made["fertility"]
	var vegetation: PackedByteArray = made["vegetation"]
	var cells := ground.size()
	var i_marsh := GROUNDS.find("marsh")
	var dry := [GROUNDS.find("sand"), GROUNDS.find("soil"),
				GROUNDS.find("gravel"), GROUNDS.find("rock")]
	var stone_kinds := [GROUNDS.find("rock"), GROUNDS.find("gravel")]

	var usable_total := 0
	var usable_count := 0
	var greenery := 0
	var marsh := 0
	var stone := 0
	for i in range(cells):
		var kind := ground[i]
		if kind in dry:
			usable_total += fertility[i]
			usable_count += 1
		if kind == i_marsh:
			marsh += 1
		if kind in stone_kinds:
			stone += 1
		greenery += vegetation[i]

	var green_average := greenery / cells
	var site: Dictionary = made["site"]
	return {
		"food": (usable_total / usable_count) if usable_count > 0 else 0,
		"timber": green_average,
		"stone": 100 * stone / cells,
		"ore": made["ore"],
		"wind": clamp100(18.0 + maxf(0.0, float(site["elevation"])) / 28.0
						 + (28.0 if site["coastal"] else 0.0)),
		"sun": clamp100(96.0 - float(site["rainfall"]) / 24.0
						+ (float(site["temperature"]) - 10.0) / 1.8),
		"water": clamp100(float(site["river_flow"]) / 34.0),
		"heat": made["heat"],
		"effort": green_average + 100 * marsh / cells,
		"room": usable_count,
	}
