# Il pianeta, come si vede.
#
# Una maglia sola per tutte le 107.025 caselle disegnate, costruita una volta e consegnata
# alla scheda video. Non 107.025 nodi: un nodo per casella sarebbe mezzo milione di oggetti
# da attraversare a ogni fotogramma, e il motore passerebbe la vita a decidere se disegnarli
# invece di disegnarli.
#
# I colori sono gli stessi del visore web (`frontend/app/globe/biomes.ts`). Per adesso sono
# trascritti: e' la sesta copia-che-deve-coincidere di questo progetto, e va chiusa -- il
# posto giusto e' il file del pianeta, che gia' porta i NOMI dei biomi e potrebbe portare
# anche le tinte. Segnato come debito, non nascosto.
extends Node3D

# `preload` e non il nome globale della classe: girando con `--script`, il motore non ha
# sempre scandito il progetto, e un nome globale che a volte c'e' e a volte no e' peggio di
# uno che non c'e' mai. Il percorso invece e' vero in ogni modo di partire.
const PlanetData := preload("res://exilium/planet.gd")

const SEA_RADIUS := 0.9982       # il guscio liscio dell'oceano aperto, sotto la piattaforma
const SHELF_RADIUS := 0.9988      # la piattaforma poco profonda attorno a ogni costa
const ICE_RADIUS := 0.9994        # la banchisa galleggia appena sopra l'acqua

const BIOME_COLORS := {
	"ocean": Color8(0x2a, 0x5a, 0x86),
	"lake": Color8(0x3d, 0x84, 0xbd),
	"sea_ice": Color8(0xd3, 0xe3, 0xef),
	"ice_sheet": Color8(0xe9, 0xf0, 0xf6),
	"snow_cap": Color8(0xe0, 0xe8, 0xf0),
	"bare_rock": Color8(0x9a, 0x92, 0x87),
	"tundra": Color8(0x9e, 0xa0, 0x89),
	"boreal_forest": Color8(0x54, 0x8a, 0x62),
	"temperate_forest": Color8(0x6d, 0x9a, 0x4e),
	"temperate_swamp": Color8(0x59, 0x88, 0x6d),
	"arid_shrubland": Color8(0xb3, 0xa2, 0x63),
	"desert": Color8(0xdc, 0xc0, 0x84),
	"tropical_rainforest": Color8(0x54, 0x9f, 0x45),
	"tropical_swamp": Color8(0x56, 0x8f, 0x6f),
}
const SHELF_SHALLOW := Color8(0x6b, 0xa3, 0xc4)
const OCEAN_DEEP := Color8(0x35, 0x68, 0x8f)

var planet


func _ready() -> void:
	var path: String = PlanetData.find_file()
	if path == "":
		push_error("nessun pianeta cotto accanto al progetto")
		return
	planet = PlanetData.load_from(path)
	if planet == null:
		return
	print("%s -- seme %s, freq %d, %d caselle (%d disegnate)"
		  % [planet.name_, planet.seed_text, planet.frequency,
			 planet.tile_count, planet.drawn_count()])

	# Il generatore tiene l'asse polare su Z -- la latitudine si legge dalla terza
	# componente del centro di una casella -- mentre in Godot l'alto e' Y. Senza questo
	# quarto di giro la telecamera guarda dritta in faccia al polo nord, e si vede una
	# calotta di ghiaccio grande mezzo pianeta invece dell'equatore. E' successo.
	var world := Node3D.new()
	world.rotate_x(-PI / 2.0)
	add_child(world)

	var mesh := build_mesh(planet)
	var instance := MeshInstance3D.new()
	instance.mesh = mesh
	var material := StandardMaterial3D.new()
	# Il colore lo porta ogni vertice: una tinta per casella, decisa dal bioma.
	material.vertex_color_use_as_albedo = true
	material.roughness = 0.95
	material.specular_mode = BaseMaterial3D.SPECULAR_DISABLED
	instance.material_override = material
	world.add_child(instance)

	# Il mare e' una SFERA, non delle caselle. Il file cotto porta solo la terra e la
	# piattaforma attorno alle coste -- l'oceano aperto e' nove decimi del pianeta e
	# spedirne i poligoni sarebbe spedire nove decimi di niente. Senza questo guscio la
	# terra galleggia nel vuoto, ed e' esattamente come si vedeva al primo tentativo.
	var sea := SphereMesh.new()
	sea.radius = SEA_RADIUS
	sea.height = SEA_RADIUS * 2.0
	sea.radial_segments = 128
	sea.rings = 96
	var water := MeshInstance3D.new()
	water.mesh = sea
	var water_material := StandardMaterial3D.new()
	water_material.albedo_color = OCEAN_DEEP
	water_material.roughness = 0.55
	water_material.specular_mode = BaseMaterial3D.SPECULAR_DISABLED
	water.material_override = water_material
	world.add_child(water)

	var light := DirectionalLight3D.new()
	light.look_at_from_position(Vector3(2.2, 1.6, 2.4), Vector3.ZERO, Vector3.UP)
	light.light_energy = 1.25
	add_child(light)

	var environment := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color8(0x05, 0x08, 0x0e)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color8(0x3a, 0x4c, 0x66)
	env.ambient_light_energy = 0.55
	environment.environment = env
	add_child(environment)

	var camera := Camera3D.new()
	camera.near = 0.01
	# Prima dentro la scena, poi puntata: `look_at` vuole sapere dove si e', e un nodo che
	# non e' ancora appeso a niente non lo sa.
	add_child(camera)
	camera.look_at_from_position(Vector3(0.0, 0.35, 2.30), Vector3.ZERO, Vector3.UP)


## La maglia del pianeta: un ventaglio di triangoli per casella, attorno al suo centro.
##
## Vertici non condivisi fra caselle di proposito. Condividerli farebbe sfumare il colore da
## una casella all'altra, e queste caselle NON sono una sfumatura: sono il posto dove si
## atterra, e il loro confine e' una decisione.
static func build_mesh(source) -> ArrayMesh:
	var points := PackedVector3Array()
	var colors := PackedColorArray()
	var normals := PackedVector3Array()

	for index in range(source.drawn_count()):
		var name: String = source.biome_of(index)
		var elevation: int = source.elevation[index]
		var radius := 1.0
		if elevation < 0:
			radius = ICE_RADIUS if name == "sea_ice" else SHELF_RADIUS
		var color: Color = BIOME_COLORS.get(name, Color8(0x77, 0x77, 0x77))
		if name == "ocean":
			# Il mare e' una rampa sola, dalla battigia all'abisso: una tinta piatta grande
			# quanto un oceano si legge come una toppa, non come acqua.
			var deep := clampf(float(-elevation) / 4000.0, 0.0, 1.0)
			color = SHELF_SHALLOW.lerp(OCEAN_DEEP, deep)

		var from: int = source.ring_offset[index]
		var to: int = source.ring_offset[index + 1]
		if to - from < 3:
			continue
		var middle: Vector3 = source.center_of(index).normalized() * radius
		for corner in range(from, to):
			var next: int = from if corner == to - 1 else corner + 1
			var a: Vector3 = source.corner_at(source.ring[corner]).normalized() * radius
			var b: Vector3 = source.corner_at(source.ring[next]).normalized() * radius
			# L'ordine dei vertici decide da che parte guarda la faccia; al contrario il
			# pianeta si vedrebbe dall'interno, cioe' non si vedrebbe.
			points.append(middle); points.append(b); points.append(a)
			var facing: Vector3 = middle.normalized()
			for i in range(3):
				colors.append(color)
				normals.append(facing)

	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = points
	arrays[Mesh.ARRAY_COLOR] = colors
	arrays[Mesh.ARRAY_NORMAL] = normals
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
