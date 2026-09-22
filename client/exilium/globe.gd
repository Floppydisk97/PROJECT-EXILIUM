# Il pianeta, come si vede.
#
# Una maglia sola per tutte le 107.025 caselle disegnate, costruita una volta e consegnata
# alla scheda video. Non 107.025 nodi: un nodo per casella sarebbe mezzo milione di oggetti
# da attraversare a ogni fotogramma, e il motore passerebbe la vita a decidere se disegnarli
# invece di disegnarli.
#
# I colori NON stanno qui: arrivano dentro al file del pianeta, accanto ai nomi dei biomi.
# Per un po' sono stati trascritti da `biomes.ts` ed erano una copia-che-deve-coincidere;
# adesso chi disegna li legge. Non rimetterli qui: un elenco di tinte in ogni visore e'
# esattamente il difetto che questo progetto ha gia' pagato sette volte.
extends Node3D

# `preload` e non il nome globale della classe: girando con `--script`, il motore non ha
# sempre scandito il progetto, e un nome globale che a volte c'e' e a volte no e' peggio di
# uno che non c'e' mai. Il percorso invece e' vero in ogni modo di partire.
const PlanetData := preload("res://exilium/planet.gd")
const OrbitCamera := preload("res://exilium/orbit_camera.gd")

const SEA_RADIUS := 0.9982       # il guscio liscio dell'oceano aperto, sotto la piattaforma
const SHELF_RADIUS := 0.9988      # la piattaforma poco profonda attorno a ogni costa
const ICE_RADIUS := 0.9994        # la banchisa galleggia appena sopra l'acqua

const RIVER_LIFT := 1.0022        # appena sopra il terreno, o litigherebbero per la profondita'
const RIVER_MIN_HALF := 0.087     # in frazioni del passo fra due caselle
const RIVER_MAX_HALF := 0.278
const RIVER_FULL_FLOW := 240.0    # portata oltre la soglia alla quale un fiume e' al massimo

var planet
var camera: Camera3D
var world: Node3D
var highlight: MeshInstance3D
var readout: Label
var pressed_at := Vector2.ZERO
var selected := -1


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
	world = Node3D.new()
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
	water_material.albedo_color = planet.palette["ocean_deep"]
	water_material.roughness = 0.55
	water_material.specular_mode = BaseMaterial3D.SPECULAR_DISABLED
	water.material_override = water_material
	world.add_child(water)

	var rivers := MeshInstance3D.new()
	rivers.mesh = build_rivers(planet)
	print("  fiumi: %d tratti" % planet.river_reach_flow.size())
	var river_material := StandardMaterial3D.new()
	river_material.vertex_color_use_as_albedo = true
	# Non illuminati, come il contorno della casella scelta. Non e' una scorciatoia: un fiume
	# su una mappa strategica deve LEGGERSI, e un nastro largo dieci pixel preso in pieno da
	# un'ombra diventa una riga nera indistinguibile da una crepa. Illuminati venivano quasi
	# neri -- e infatti la prima versione sembrava avere delle crepe invece che dei fiumi.
	river_material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	# Senza facce da scartare: un nastro e' piatto e non ha un dietro. Con lo scarto attivo
	# dipendeva da come erano girati i vertici, e girati male sparivano -- il che si vede
	# esattamente come dei fiumi che non ci sono.
	river_material.cull_mode = BaseMaterial3D.CULL_DISABLED
	rivers.material_override = river_material
	world.add_child(rivers)

	var environment := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color8(0x05, 0x08, 0x0e)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color8(0x3a, 0x4c, 0x66)
	env.ambient_light_energy = 0.55
	environment.environment = env
	add_child(environment)

	camera = Camera3D.new()
	camera.set_script(OrbitCamera)
	add_child(camera)
	# Nel gruppo DOPO essere entrata nell'albero: un nodo iscritto prima non viene
	# restituito da chi cerca per gruppo, e cercarlo dava zero telecamere senza dirlo.
	camera.add_to_group("camera_rig")

	# Il sole sta dietro la spalla di chi guarda, appeso alla telecamera. Non si sta
	# simulando il giorno e la notte: si sta leggendo una mappa, e meta' di una mappa al buio
	# e' meta' mappa. Con la luce fissa, appena la telecamera si sposta sul lato in ombra il
	# pianeta diventa una palla nera -- ed e' esattamente quello che ha fatto al primo
	# tentativo. Di sbieco e non frontale, se no il rilievo sparisce insieme alle ombre.
	var light := DirectionalLight3D.new()
	light.light_energy = 1.15
	camera.add_child(light)
	light.rotation_degrees = Vector3(-22.0, 26.0, 0.0)
	# Si apre guardando la TERRA, non un punto qualunque. Il primo tentativo apriva in mezzo
	# all'oceano aperto -- che su questo pianeta sono nove decimi della superficie -- e un
	# pianeta che si apre su una tinta blu uniforme sembra un pianeta che non si e' caricato.
	camera.aim(biggest_landmass(planet), 2.30)

	# Il contorno della casella scelta, e una riga che dice cosa c'e'. Sono la meta' di quel
	# che serve per atterrare: l'altra meta' -- prendere la casella -- la decide il server,
	# ed e' giusto cosi', se no chiunque si dichiarerebbe su una casella d'oro.
	highlight = MeshInstance3D.new()
	var outline := StandardMaterial3D.new()
	outline.vertex_color_use_as_albedo = true
	outline.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	outline.cull_mode = BaseMaterial3D.CULL_DISABLED
	highlight.material_override = outline
	world.add_child(highlight)

	var layer := CanvasLayer.new()
	add_child(layer)
	readout = Label.new()
	readout.position = Vector2(18, 16)
	readout.add_theme_color_override("font_color", Color8(0xea, 0xf2, 0xf8))
	readout.add_theme_color_override("font_outline_color", Color8(0x06, 0x0a, 0x10))
	readout.add_theme_constant_override("outline_size", 6)
	readout.text = "%s · seme %s · %s caselle\nTrascina per girare, rotella per avvicinarti, clic per scegliere" % [
		planet.name_, planet.seed_text, comma(planet.tile_count)]
	layer.add_child(readout)
	add_to_group("picker")


## Guarda da questa direzione, a questa distanza. Passa dal globo invece che dalla telecamera
## perche' il globo e' la cosa che qualcuno tiene in mano: chi vuole inquadrare un posto non
## deve prima sapere come si chiama il nodo che ci guarda.
func aim(direction: Vector3, distance: float) -> void:
	camera.aim(direction, distance)


## Un numero con i punti, come si scrive in italiano. 231042 diventa 231.042: a sei cifre,
## senza separatore, non si legge quanto e' grande un pianeta.
static func comma(value: int) -> String:
	var text := str(value)
	var out := ""
	for i in range(text.length()):
		if i > 0 and (text.length() - i) % 3 == 0:
			out += "."
		out += text[i]
	return out


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventMouseButton):
		return
	var button := event as InputEventMouseButton
	if button.button_index != MOUSE_BUTTON_LEFT:
		return
	if button.pressed:
		pressed_at = button.position
	# Un clic e' un clic solo se il mouse non si e' mosso: senza questo, ogni trascinamento
	# per girare il pianeta finirebbe per scegliere la casella su cui il dito si e' fermato.
	elif button.position.distance_to(pressed_at) < 6.0:
		select_at_screen(button.position)


## Quale casella sta sotto questo punto dello schermo.
func select_at_screen(point: Vector2) -> void:
	var origin := camera.project_ray_origin(point)
	var direction := camera.project_ray_normal(point)
	var hit := sphere_hit(origin, direction)
	if hit == Vector3.ZERO:
		return
	# Dalla direzione nel mondo a quella del pianeta: la maglia sta dentro un nodo ruotato di
	# un quarto di giro, e cercare la casella piu' vicina senza disfare quella rotazione
	# darebbe sempre una casella a novanta gradi da dove si e' cliccato.
	select(nearest_tile(world.global_transform.basis.inverse() * hit))


## Dove un raggio incontra la sfera unitaria, o zero se la manca. Si cerca la superficie del
## TERRENO (raggio uno), non il guscio del mare: cliccare sull'oceano deve dare la casella
## d'oceano che sta li', non nessuna casella.
static func sphere_hit(origin: Vector3, direction: Vector3) -> Vector3:
	var b := origin.dot(direction)
	var c := origin.length_squared() - 1.0
	var discriminant := b * b - c
	if discriminant < 0.0:
		return Vector3.ZERO
	var t := -b - sqrt(discriminant)
	if t < 0.0:
		return Vector3.ZERO
	return (origin + direction * t).normalized()


## La casella il cui centro e' piu' vicino a questa direzione. Cento e passa mila prodotti
## scalari per un clic: si potrebbe indicizzare, e un giorno con un pianeta dieci volte piu'
## grande si dovra'. Per adesso e' un decimo di secondo su un gesto che l'utente fa una volta
## ogni tanto, e un indice e' una struttura in piu' da tenere giusta.
func nearest_tile(direction: Vector3) -> int:
	var best := -1
	var best_dot := -2.0
	for index in range(planet.drawn_count()):
		var dot: float = planet.center_of(index).dot(direction)
		if dot > best_dot:
			best_dot = dot
			best = index
	return best


func select(index: int) -> void:
	selected = index
	if index < 0:
		highlight.mesh = null
		return
	highlight.mesh = outline_of(planet, index)
	var here: String = planet.biome_of(index)
	var lines := [
		"%s · casella %d" % [planet.name_, planet.ids[index]],
		"%s · %d m · %.1f °C · %d mm" % [
			here.replace("_", " "), planet.elevation[index],
			planet.temperature[index], planet.rainfall[index]],
	]
	if planet.river_flow[index] >= planet.river_min_flow:
		lines.append("corso d'acqua, portata %d" % planet.river_flow[index])
	if planet.coastal[index] == 1:
		lines.append("sul mare")
	readout.text = "\n".join(lines)


## Il contorno di una casella, appena sopra il terreno. Un anello di quadrilateri sottili e
## non una linea: le linee di Godot hanno spessore di un pixel a qualunque distanza, quindi
## da vicino la casella scelta sparirebbe invece di risaltare.
static func outline_of(source, index: int) -> ArrayMesh:
	var points := PackedVector3Array()
	var colors := PackedColorArray()
	var from: int = source.ring_offset[index]
	var to: int = source.ring_offset[index + 1]
	if to - from < 3:
		return ArrayMesh.new()
	var lift := 1.004
	var thickness: float = source.tile_spacing() * 0.12
	var ink := Color8(0xff, 0xe9, 0x8a)
	for corner in range(from, to):
		var next: int = from if corner == to - 1 else corner + 1
		var a: Vector3 = source.corner_at(source.ring[corner]).normalized()
		var b: Vector3 = source.corner_at(source.ring[next]).normalized()
		var middle: Vector3 = source.center_of(index).normalized()
		# Il nastro si allarga verso il CENTRO della casella, cosi' il contorno sta dentro e
		# non scavalca la casella accanto.
		var a_in: Vector3 = (a + (middle - a).normalized() * thickness).normalized()
		var b_in: Vector3 = (b + (middle - b).normalized() * thickness).normalized()
		for corner_point in [a * lift, b * lift, b_in * lift, a * lift, b_in * lift, a_in * lift]:
			points.append(corner_point)
			colors.append(ink)
	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = points
	arrays[Mesh.ARRAY_COLOR] = colors
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh



## Da che parte guardare per vedere la terra: il centro della casella che appartiene al
## continente piu' grande. Non la media di tutte le terre -- con i continenti sparsi la media
## cade dentro al pianeta, e "dentro" non e' una direzione.
##
## Il ghiaccio non conta, ed e' una correzione fatta GUARDANDO: su questo pianeta la massa di
## terra piu' estesa e' la calotta polare, quindi la versione senza questa riga apriva la
## vista su una lastra bianca. Tecnicamente giusto e praticamente inutile -- quel che si vuole
## vedere aprendo un pianeta e' un posto dove si potrebbe vivere.
const FROZEN := ["ice_sheet", "snow_cap", "sea_ice"]

static func biggest_landmass(source) -> Vector3:
	var widest := 0
	for index in range(source.drawn_count()):
		if source.elevation[index] >= 0 and source.landmass_size[index] > widest:
			widest = source.landmass_size[index]
	# Il BARICENTRO delle sue terre abitabili, non una sua casella qualunque. Prendere la
	# prima che capita dava sempre un punto sul bordo -- due tentativi di fila hanno aperto
	# sulla calotta polare, che e' attaccata allo stesso continente.
	var sum := Vector3.ZERO
	var counted := 0
	for index in range(source.drawn_count()):
		if source.elevation[index] < 0 or source.landmass_size[index] != widest:
			continue
		if source.biome_of(index) in FROZEN:
			continue
		sum += source.center_of(index)
		counted += 1
	if counted == 0 or sum.length_squared() < 1e-9:
		# Un continente tutto ghiacciato, o sparso cosi' bene attorno al pianeta che la media
		# cade nel centro: "dentro" non e' una direzione, quindi si ripiega su una casella.
		for index in range(source.drawn_count()):
			if source.elevation[index] >= 0:
				return source.center_of(index)
		return Vector3.UP
	return sum.normalized()


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
		var color: Color = source.color_of(index)
		if name == "ocean":
			# Il mare e' una rampa sola, dalla battigia all'abisso: una tinta piatta grande
			# quanto un oceano si legge come una toppa, non come acqua.
			var deep := clampf(float(-elevation) / 4000.0, 0.0, 1.0)
			color = source.palette["shelf_shallow"].lerp(source.palette["ocean_deep"], deep)

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


## I fiumi: un nastro per tratto, largo in proporzione a quanto porta.
##
## Gemello di `terrain.buildRivers`. Le costanti sono le stesse e per la stessa ragione: la
## larghezza e' una FRAZIONE del passo fra due caselle, non un numero assoluto -- su un
## pianeta piu' fitto un numero assoluto darebbe fiumi larghi come una regione.
static func build_rivers(source) -> ArrayMesh:
	var points := PackedVector3Array()
	var colors := PackedColorArray()
	var normals := PackedVector3Array()

	var span: float = source.tile_spacing()
	var min_half := span * RIVER_MIN_HALF
	var max_half := span * RIVER_MAX_HALF
	var lift := RIVER_LIFT

	for i in range(source.river_reach_flow.size()):
		var at := i * 3
		var head := Vector3(source.river_a[at], source.river_a[at + 1], source.river_a[at + 2]) * lift
		var foot := Vector3(source.river_b[at], source.river_b[at + 1], source.river_b[at + 2]) * lift
		var along := foot - head
		if along.length_squared() < 1e-12:
			continue
		along = along.normalized()
		var across := along.cross(head.normalized())
		if across.length_squared() < 1e-12:
			continue
		var grade := clampf(
			float(source.river_reach_flow[i] - source.river_min_flow) / RIVER_FULL_FLOW, 0.0, 1.0)
		var half := min_half + (max_half - min_half) * grade
		across = across.normalized() * half
		# Ogni tratto sborda di mezza larghezza da tutti e due i capi, se no fra un tratto e
		# il successivo resterebbe una tacca e un fiume sembrerebbe una catena di trattini.
		head -= along * half
		foot += along * half
		var color: Color = source.palette["river_minor"].lerp(source.palette["river_major"], grade)
		var facing := head.normalized()
		for corner in [head - across, head + across, foot + across,
					   head - across, foot + across, foot - across]:
			points.append(corner)
			colors.append(color)
			normals.append(facing)

	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = points
	arrays[Mesh.ARRAY_COLOR] = colors
	arrays[Mesh.ARRAY_NORMAL] = normals
	var mesh := ArrayMesh.new()
	if points.size() > 0:
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
