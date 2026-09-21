# Il pianeta, letto dal file che il generatore ha cotto.
#
# LO STESSO file che legge il visore web: `frontend/public/map/planet-*.bin`, cioe' JSON
# compresso con gzip. Non ne viene fatta una copia qui dentro. Due pianeti che devono
# coincidere sono il difetto che questo progetto ha gia' avuto sei volte, e uno di quelli --
# il database contro il file -- e' costato una giornata di diagnosi.
#
# Il pianeta e' IMMUTABILE e viene generato una volta sola dal server: 231.042 caselle,
# seme "Erebo-01". Il client non lo genera e non lo puo' contraddire; lo guarda.
class_name Planet
extends RefCounted

# Il file si carica da se'. Sembra strano e non lo e': girando con `--script`, il motore non
# ha sempre scandito il progetto, quindi il nome globale della classe a volte non esiste
# ancora -- e un nome che a volte c'e' e a volte no e' peggio di uno che non c'e' mai. Il
# percorso invece e' vero in ogni modo di partire.
const PlanetData := preload("res://exilium/planet.gd")

var name_: String
var seed_text: String
var frequency: int
var sea_level: float
var tile_count: int
var land_count: int
var river_min_flow: int
var biome_names: PackedStringArray
var corners: PackedFloat64Array      # tre per vertice, condivisi fra le caselle
var ids: PackedInt32Array
var center: PackedFloat64Array       # tre per casella
var elevation: PackedInt32Array
var biome: PackedByteArray
var ring: PackedInt32Array           # indici dentro `corners`
var ring_offset: PackedInt32Array    # una voce in piu' del numero di caselle


## Dove sta il pianeta cotto, cercandolo accanto al progetto. In sviluppo il file vive con il
## visore web; quando ci sara' un'esportazione vera entrera' nel pacchetto e questo diventera'
## un `res://`. Finche' sono due strade per lo stesso file, e' una sola copia.
static func find_file() -> String:
	var root := ProjectSettings.globalize_path("res://")
	var folder := root.path_join("../frontend/public/map").simplify_path()
	var manifest_path := folder.path_join("manifest.json")
	var manifest_file := FileAccess.open(manifest_path, FileAccess.READ)
	if manifest_file == null:
		return ""
	var manifest = JSON.parse_string(manifest_file.get_as_text())
	manifest_file.close()
	if manifest == null or not manifest.has("file"):
		return ""
	return folder.path_join(manifest["file"])


static func load_from(path: String):
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("pianeta non trovato: " + path)
		return null
	var packed := file.get_buffer(file.get_length())
	file.close()
	# `decompress_dynamic` e non `decompress`: la dimensione vera non la sappiamo prima di
	# guardarla, e il tetto serve solo a impedire che un file rotto mangi la memoria.
	var raw := packed.decompress_dynamic(512 * 1024 * 1024, FileAccess.COMPRESSION_GZIP)
	var data = JSON.parse_string(raw.get_string_from_utf8())
	if data == null:
		push_error("pianeta illeggibile: " + path)
		return null

	var planet := PlanetData.new()
	planet.name_ = data["name"]
	planet.seed_text = data["seed"]
	planet.frequency = int(data["frequency"])
	planet.sea_level = float(data["sea_level"])
	planet.tile_count = int(data["tile_count"])
	planet.land_count = int(data["land_count"])
	planet.river_min_flow = int(data["river_min_flow"])
	planet.biome_names = PackedStringArray(data["biome_names"])
	planet.corners = PackedFloat64Array(data["corners"])
	var tiles: Dictionary = data["tiles"]
	planet.ids = PackedInt32Array(tiles["id"])
	planet.center = PackedFloat64Array(tiles["center"])
	planet.elevation = PackedInt32Array(tiles["elevation"])
	planet.biome = PackedByteArray(tiles["biome"])
	planet.ring = PackedInt32Array(tiles["ring"])
	planet.ring_offset = PackedInt32Array(tiles["ring_offset"])
	return planet


func drawn_count() -> int:
	return ids.size()


func biome_of(index: int) -> String:
	return biome_names[biome[index]]


func corner_at(corner_index: int) -> Vector3:
	var at := corner_index * 3
	return Vector3(corners[at], corners[at + 1], corners[at + 2])


func center_of(index: int) -> Vector3:
	var at := index * 3
	return Vector3(center[at], center[at + 1], center[at + 2])
