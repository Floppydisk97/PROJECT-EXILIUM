# Il terreno della colonia: 2,36 milioni di esagoni da un metro quadro.
#
# Non una maglia come il globo. Il globo ha 107.000 caselle e le disegna come triangoli; qui
# ce ne sono ventidue volte tante, e ventidue volte tanti triangoli sarebbero cinquanta
# milioni di vertici per una cosa PIATTA. Il terreno diventa un'IMMAGINE -- la stessa scelta
# del visore web, e per la stessa ragione.
#
# DUE PIXEL PER ESAGONO in orizzontale, e uno per riga. Non e' una scelta di qualita': e'
# l'unica coppia in cui mezzo esagono di sfalsamento e' un numero intero di pixel. Con un
# pixel per esagono le righe dispari tornerebbero dritte, e il colore starebbe mezza cella
# fuori dalle linee a righe alterne -- vedi `draw.ts`, dove la stessa cosa ha un test.
#
# QUEL CHE MANCA, detto invece che nascosto: qui non c'e' la schiuma sulla riva ne' l'orlo
# bagnato. Nel visore web vengono dalla distanza dal bordo dell'acqua, che e' un'altra
# passata su tutte le celle; senza di quelle il terreno e' giusto ma piu' povero di quello
# del browser. E' polish, non geografia.
#
# E una cosa che non manca ma e' APPROSSIMATA, detta perche' da vicino si vede: il terreno e'
# un buffer rettangolare, quindi ogni esagono e' dipinto come un rettangolo largo quanto la
# cella, non come un esagono. Ai quattro angoli il colore sconfina nelle punte del vicino. E'
# la stessa approssimazione del visore web -- stesso buffer, stessa scelta -- e si nota solo
# con le linee accese; il rimedio vero e' la maglia di triangoli scartata in cima a questo
# file, che per un terreno piatto costa cinquanta milioni di vertici.
extends Node2D

const Citygen := preload("res://exilium/citygen.gd")
const PlanetData := preload("res://exilium/planet.gd")
const Hex := preload("res://exilium/hexgrid.gd")

## Sotto questo ingrandimento le linee non si accendono. Non e' un capriccio: a meno di nove
## pixel per esagono sei tratti per cella non sono piu' una griglia, sono una retina grigia
## appoggiata sul terreno, e il terreno e' la cosa che si deve leggere.
const GRID_ZOOM := 9.0

# Le tinte del terreno. Sorgente: `citygen.GROUND_COLORS` e `citygen.PALETTE`, e viaggiano nel
# riferimento -- `tests/run.gd` verifica che questa tabella non se ne sia allontanata. Sono
# qui, e non lette a tempo di esecuzione, perche' il riferimento e' un attrezzo di prova e non
# va spedito con il gioco.
const GROUND_COLORS := {
	"deep_water": 0x162C42, "water": 0x2E5670, "marsh": 0x464E3A, "sand": 0xB2A07C,
	"soil": 0x604F3A, "gravel": 0x686358, "rock": 0x565451, "ice": 0xCEDBE5,
}
const MEADOW := 0x606E3E
const FOREST := 0x30442A

## Quanto e' grande la colonia da disegnare. La vera e' `Citygen.SIZE`; si puo' chiedere piu'
## piccola per guardarla in fretta, e il terreno e' LO STESSO POSTO -- il generatore normalizza
## le sue coordinate, quindi cambia il dettaglio, non la geografia.
@export var size := 384
@export var seed_text := ""
@export var grid := false

var made: Dictionary
var terrain: ImageTexture
var camera: Camera2D
var readout: Label


func _ready() -> void:
	var site := site_to_draw()
	if seed_text == "":
		seed_text = "colonia-di-prova"
	var started := Time.get_ticks_msec()
	made = Citygen.generate(seed_text, site, size)
	var grown := Time.get_ticks_msec() - started

	started = Time.get_ticks_msec()
	terrain = ImageTexture.create_from_image(paint(made))
	var painted := Time.get_ticks_msec() - started
	print("colonia %s: %d esagoni in %.1f s, dipinti in %.1f s"
		  % [site["biome"], size * size, grown / 1000.0, painted / 1000.0])

	camera = Camera2D.new()
	add_child(camera)
	camera.make_current()
	# Al centro della colonia, non nell'angolo: un terreno che si apre sul bordo sembra un
	# terreno che non si e' caricato.
	camera.position = Vector2(size * 0.5, Hex.map_height(size) * 0.5)
	# Il disegno e' in ESAGONI, non in pixel: un'unita' e' un esagono, e l'ingrandimento
	# della telecamera e' quanti pixel vale un esagono. E' la stessa scelta del visore web,
	# e serve a far combaciare le linee col terreno senza conversioni a mano in tre posti.
	fit()
	# Lo stesso gancio del globo, cosi' `tests/shot.gd` sa inquadrare anche qui senza sapere
	# che cosa sta fotografando. Il significato dei numeri e' diverso -- qui sono esagoni e
	# pixel per esagono, non una direzione nello spazio -- ed e' detto su `aim`.
	add_to_group("picker")
	# NESSUNA SFUMATURA fra un esagono e il suo vicino. Il filtro liscio e' il difetto
	# dell'immagine precedente: a venti pixel per esagono spalmava il colore di una cella
	# oltre il proprio contorno, e il terreno finiva mezza cella fuori dalle linee proprio
	# nell'inquadratura in cui si costruisce. Una cella e' un colore, e il bordo e' netto.
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST

	var layer := CanvasLayer.new()
	add_child(layer)
	readout = Label.new()
	readout.position = Vector2(18, 16)
	readout.add_theme_color_override("font_color", Color8(0xea, 0xf2, 0xf8))
	readout.add_theme_color_override("font_outline_color", Color8(0x06, 0x0a, 0x10))
	readout.add_theme_constant_override("outline_size", 6)
	var economy: Dictionary = Citygen.economy_of(made)
	readout.text = "%s · %d m · %d esagoni da un metro quadro\ncibo %d · legname %d · pietra %d · edificabili %d" % [
		String(site["biome"]).replace("_", " "), int(site["elevation"]), size * size,
		economy["food"], economy["timber"], economy["stone"], economy["room"]]
	readout.text += "\nG griglia · F tutta · rotella ingrandisce · trascina sposta"
	layer.add_child(readout)
	queue_redraw()


## Su che sito si atterra. Se c'e' un pianeta accanto al progetto si prende una casella VERA --
## il terreno di una colonia e' quel che il pianeta ha detto di quella casella, non un posto
## inventato. Senza pianeta si ripiega su un sito di prova, cosi' la scena si apre comunque.
func site_to_draw() -> Dictionary:
	var path: String = PlanetData.find_file()
	if path == "":
		return {"biome": "temperate_forest", "elevation": 220, "temperature": 12.0,
				"rainfall": 1100, "river_flow": 0, "coastal": false}
	var planet = PlanetData.load_from(path)
	if planet == null:
		return {"biome": "temperate_forest", "elevation": 220, "temperature": 12.0,
				"rainfall": 1100, "river_flow": 0, "coastal": false}
	# Una casella con un fiume vero, se c'e': e' il sito che mostra piu' cose in una volta --
	# acqua, sponde fertili, e il resto attorno.
	var chosen := 0
	for index in range(planet.drawn_count()):
		if planet.elevation[index] < 0:
			continue
		chosen = index
		if planet.river_flow[index] >= planet.river_min_flow:
			break
	seed_text = Citygen.seed_for(planet.seed_text, planet.ids[chosen])
	return {
		"biome": planet.biome_of(chosen),
		"elevation": planet.elevation[chosen],
		"temperature": planet.temperature[chosen],
		"rainfall": planet.rainfall[chosen],
		# La portata memorizzata e' deflusso accumulato: un fiume c'e' solo sopra la soglia.
		"river_flow": planet.river_flow[chosen] if planet.river_flow[chosen] >= planet.river_min_flow else 0,
		"coastal": planet.coastal[chosen] == 1,
	}


## Il terreno come immagine. Un `PackedByteArray` riempito in un colpo e non un milione di
## `set_pixel`: a 2,36 milioni di esagoni la differenza fra i due non e' una sfumatura.
static func paint(ground: Dictionary) -> Image:
	var side: int = ground["size"]
	var names: Array = ground["ground_names"]
	var cells: PackedByteArray = ground["ground"]
	var fertility: PackedByteArray = ground["fertility"]
	var vegetation: PackedByteArray = ground["vegetation"]

	var width := side * 2
	var pixels := PackedByteArray()
	pixels.resize(width * side * 3)

	# Le tinte, preparate una volta per indice di terreno invece che cercate per nome a ogni
	# cella: due milioni di ricerche in un dizionario sono due milioni di ricerche.
	var base := PackedInt32Array()
	var watery := PackedByteArray()
	for name in names:
		base.append(GROUND_COLORS.get(name, 0x777777))
		watery.append(1 if (name == "water" or name == "deep_water" or name == "ice") else 0)

	for row in range(side):
		var odd := row & 1
		for col in range(side):
			var index := row * side + col
			var kind: int = cells[index]
			var color: int = base[kind]
			var r := (color >> 16) & 0xFF
			var g := (color >> 8) & 0xFF
			var b := color & 0xFF
			if watery[kind] == 0:
				# Il verde ha DUE fermate e non una: con una sola, un bosco e' un prato scuro.
				var veg: int = vegetation[index]
				var green := minf(1.0, veg / 85.0) * 0.82
				var wood := smoothstep(0.0, 1.0, (veg - 42) / 48.0) * 0.78
				var rich := 1.0 - minf(1.0, fertility[index] / 140.0) * 0.16
				r = int((lerpf(lerpf(r, (MEADOW >> 16) & 0xFF, green), (FOREST >> 16) & 0xFF, wood)) * rich)
				g = int((lerpf(lerpf(g, (MEADOW >> 8) & 0xFF, green), (FOREST >> 8) & 0xFF, wood)) * rich)
				b = int((lerpf(lerpf(b, MEADOW & 0xFF, green), FOREST & 0xFF, wood)) * rich)
			for half in range(2):
				# Mezzo esagono di scostamento sulle righe dispari: qui e' un pixel esatto.
				var sx := col * 2 + half + odd
				if sx >= width:
					continue
				var at := (row * width + sx) * 3
				pixels[at] = r
				pixels[at + 1] = g
				pixels[at + 2] = b
		if odd:
			# Il primo pixel di una riga dispari resterebbe nero: lo sfalsamento ha spinto
			# tutto di uno. Prende il colore del vicino -- un bordo scuro lungo una riga sì e
			# una no si vedrebbe da qualunque distanza.
			var to := row * width * 3
			var from := (row * width + 1) * 3
			pixels[to] = pixels[from]
			pixels[to + 1] = pixels[from + 1]
			pixels[to + 2] = pixels[from + 2]

	return Image.create_from_data(width, side, false, Image.FORMAT_RGB8, pixels)


## Guarda l'esagono (x, y) da vicino cosi': `distance` pixel per esagono. Firma uguale a
## quella del globo perche' chi fotografa non deve sapere che cosa ha davanti; `direction.z`
## non serve e viene ignorato. Con `distance` sopra `GRID_ZOOM` le linee si vedono.
func aim(direction: Vector3, distance: float) -> void:
	var zoom := clampf(distance, 0.05, 64.0)
	camera.zoom = Vector2(zoom, zoom)
	camera.position = Vector2(Hex.centre_x(int(direction.x), int(direction.y)),
							  Hex.centre_y(int(direction.y)))
	queue_redraw()


## L'ingrandimento che fa entrare tutta la colonia nella finestra, con un dito di margine.
func fit() -> void:
	var window := Vector2(get_viewport_rect().size)
	var scale := minf(window.x / float(size), window.y / Hex.map_height(size)) * 0.94
	camera.zoom = Vector2(scale, scale)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_G:
			grid = not grid
			queue_redraw()
		elif event.keycode == KEY_F:
			fit()
			camera.position = Vector2(size * 0.5, Hex.map_height(size) * 0.5)
			queue_redraw()
	elif event is InputEventMouseButton and event.pressed:
		var step := 0.0
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			step = 1.15
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			step = 1.0 / 1.15
		if step > 0.0:
			# Si ingrandisce VERSO IL PUNTATORE: quel che sta sotto il mouse ci resta. Con
			# l'ingrandimento sul centro, avvicinarsi a un fiume e' una caccia.
			var before := get_global_mouse_position()
			var zoom := clampf(camera.zoom.x * step, 0.05, 64.0)
			camera.zoom = Vector2(zoom, zoom)
			camera.position += before - get_global_mouse_position()
			queue_redraw()
	elif event is InputEventMouseMotion and (event.button_mask & MOUSE_BUTTON_MASK_LEFT):
		camera.position -= event.relative / camera.zoom
		queue_redraw()


func _draw() -> void:
	if terrain == null:
		return
	# Il buffer ha due pixel per esagono in larghezza e una riga per riga: steso a 0,866 di
	# altezza, le righe cadono esattamente dove cadono gli esagoni.
	draw_texture_rect(terrain, Rect2(0, 0, size, Hex.map_height(size)), false)
	if grid:
		draw_grid()


## Le linee della griglia, sopra il terreno.
##
## Disegnate come VETTORI e non cotte dentro il buffer del terreno: e' quello che le rende
## accendibili e spegnibili senza rigenerare niente, e anche quello che le tiene nitide a
## qualunque ingrandimento -- un contorno cotto nel buffer, a due pixel per esagono, sarebbe
## una sbavatura grigia.
##
## Solo gli esagoni INQUADRATI. Due milioni e trecentomila contorni sarebbero quattordici
## milioni di segmenti per mostrarne diecimila.
func draw_grid() -> int:
	var scale := camera.zoom.x
	if scale < GRID_ZOOM:
		return 0
	var window := Vector2(get_viewport_rect().size) / scale
	var top_left := camera.position - window * 0.5
	var col0 := maxi(0, int(floor(top_left.x)) - 2)
	var col1 := mini(size - 1, int(ceil(top_left.x + window.x)) + 1)
	var row0 := maxi(0, int(floor(top_left.y / Hex.row_ratio())) - 1)
	var row1 := mini(size - 1, int(ceil((top_left.y + window.y) / Hex.row_ratio())) + 1)

	# Piu' si sta vicini, piu' la linea si fa vedere: da lontano una griglia satura copre il
	# terreno, da vicino serve che si legga su cosa si costruisce.
	var closeness := minf(1.0, (scale - GRID_ZOOM) / 16.0)
	var ink := Color(0.063, 0.086, 0.118, 0.16 + 0.26 * closeness)
	# La larghezza e' in unita' di disegno, e un'unita' e' un esagono: divisa per
	# l'ingrandimento, la linea resta spessa uguale sullo schermo a ogni distanza.
	var thickness := maxf(0.6, scale * 0.035) / scale
	var corners := Hex.corners()

	var drawn := 0
	var outline := PackedVector2Array()
	outline.resize(7)
	for row in range(row0, row1 + 1):
		var cy := Hex.centre_y(row)
		for col in range(col0, col1 + 1):
			var cx := Hex.centre_x(col, row)
			for i in range(6):
				outline[i] = Vector2(cx, cy) + corners[i]
			outline[6] = outline[0]
			draw_polyline(outline, ink, thickness, true)
			drawn += 1
	return drawn
