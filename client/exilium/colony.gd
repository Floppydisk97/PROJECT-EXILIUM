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

## I terreni su cui si puo' posare qualcosa. Sono gli stessi quattro che `citygen.economy_of`
## conta come `room`, e il perche' di questa costante e' che erano due elenchi: il numero
## promesso dal rilevamento e la risposta data a chi clicca devono essere la stessa idea di
## "edificabile", altrimenti si atterra su un posto che dice 86.000 caselle libere e poi
## nessuna di quelle su cui si prova e' libera davvero.
const BUILDABLE := ["sand", "soil", "gravel", "rock"]

var made: Dictionary
var terrain: ImageTexture
var camera: Camera2D
var readout: Label
var panel: Label

## L'esagono scelto, o (-1, -1) se nessuno. Non e' un indice: una coppia si legge, e a
## 2,36 milioni di celle un indice sbagliato di uno e' invisibile.
var selected := Vector2i(-1, -1)

## Da dove e' cominciata la pressione del tasto, per distinguere un CLIC da un TRASCINAMENTO.
## Senza, ogni spostamento della mappa finirebbe per scegliere la cella dove si e' lasciato il
## tasto, e la scelta cambierebbe da sola ogni volta che ci si guarda intorno.
var pressed_at := Vector2.ZERO
var dragged := false


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

	# Il pannello di cio' che si e' scelto, in basso a sinistra. Vuoto finche' non si clicca:
	# una riga che dice "nessuna casella" occupa lo stesso spazio e non dice niente.
	panel = Label.new()
	panel.add_theme_color_override("font_color", Color8(0xea, 0xf2, 0xf8))
	panel.add_theme_color_override("font_outline_color", Color8(0x06, 0x0a, 0x10))
	panel.add_theme_constant_override("outline_size", 6)
	panel.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	panel.position = Vector2(18, -96)
	panel.grow_vertical = Control.GROW_DIRECTION_BEGIN
	layer.add_child(panel)
	describe()
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


## Che cosa c'e' nell'esagono (col, row). Un dizionario e non del testo, perche' e' la stessa
## risposta che servira' a chi decidera' se un edificio ci sta: la frase e' `describe`, questi
## sono i FATTI.
func cell_facts(col: int, row: int) -> Dictionary:
	return facts_of(made, col, row)


## Gli stessi fatti, senza bisogno della scena: serve a `tests/run.gd`, che non ha una
## finestra e non puo' cliccare. Statica apposta -- una cosa che si puo' provare solo
## aprendo un visore, in pratica non si prova.
static func facts_of(made: Dictionary, col: int, row: int) -> Dictionary:
	if made.is_empty():
		return {}
	var size: int = made["size"]
	if col < 0 or row < 0 or col >= size or row >= size:
		return {}
	var index := row * size + col
	var names: Array = made["ground_names"]
	var cells: PackedByteArray = made["ground"]
	# Interi a 32 bit e non byte: un'altezza e' in METRI, e un byte finisce a 255. Era scritto
	# `PackedByteArray` e nessuno se n'era accorto finche' non e' esistita una prova.
	var heights: PackedInt32Array = made["height"]
	var fertility: PackedByteArray = made["fertility"]
	var vegetation: PackedByteArray = made["vegetation"]
	var kind: String = names[cells[index]]
	return {
		"col": col, "row": row, "index": index, "ground": kind,
		"height": heights[index], "fertility": fertility[index],
		"vegetation": vegetation[index], "buildable": kind in BUILDABLE,
	}


## Quale esagono sta sotto questo punto dello SCHERMO. Stesso nome e stessa firma del globo,
## cosi' chi sceglie -- l'utente o `tests/shot.gd` -- non deve sapere che cosa ha davanti.
func select_at_screen(point: Vector2) -> void:
	var here := to_hex_space(point)
	select(Hex.hex_at(here.x, here.y, size))


## Dal pixel sullo schermo all'unita' di disegno, cioe' all'esagono.
##
## Il conto si fa con la posizione e l'ingrandimento della telecamera, NON con
## `get_canvas_transform()`. Quella trasformazione la aggiorna la telecamera quando le tocca,
## e finche' non e' passato un fotogramma racconta ancora dov'era prima: spostare
## l'inquadratura e scegliere subito dava la cella di dov'era prima l'inquadratura -- che
## somiglia moltissimo a una scelta riuscita, perche' una cella la restituisce comunque. E'
## stato `tests/shot.gd` a scoprirlo, puntando a (232, 190) e ricevendo (191, 191).
func to_hex_space(point: Vector2) -> Vector2:
	return hex_space(point, camera.position, camera.zoom.x,
					 Vector2(get_viewport_rect().size))


## Lo stesso conto senza la scena, perche' sia provabile. Una telecamera 2D senza rotazione
## ne' scostamento guarda il proprio centro: il pixel di mezzo e' `where`, e ogni altro pixel
## e' distante da quello quanto dice l'ingrandimento.
static func hex_space(point: Vector2, where: Vector2, zoom: float, window: Vector2) -> Vector2:
	return where + (point - window * 0.5) / zoom


func select(cell: Vector2i) -> void:
	selected = cell
	describe()
	queue_redraw()


## La frase che il pannello mostra. Separata dai fatti perche' un giorno la stessa cella
## dovra' rispondere a una domanda diversa -- "ci sta una fattoria?" -- e quella domanda non
## si fa a una stringa.
func describe() -> void:
	if panel == null:
		return
	var facts := cell_facts(selected.x, selected.y)
	if facts.is_empty():
		panel.text = "clicca un esagono"
		return
	panel.text = "esagono %d, %d · %s · %d m\nfertilita' %d · vegetazione %d · %s" % [
		facts["col"], facts["row"], String(facts["ground"]).replace("_", " "),
		facts["height"], facts["fertility"], facts["vegetation"],
		"edificabile" if facts["buildable"] else "non edificabile"]


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode == KEY_G:
			grid = not grid
			queue_redraw()
		elif event.keycode == KEY_F:
			fit()
			camera.position = Vector2(size * 0.5, Hex.map_height(size) * 0.5)
			queue_redraw()
	elif event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed:
			pressed_at = event.position
			dragged = false
		elif not dragged:
			# Si sceglie al RILASCIO e solo se il mouse non si e' mosso: premere per
			# trascinare e scegliere sono lo stesso gesto fino all'ultimo istante.
			select_at_screen(event.position)
	elif event is InputEventMouseButton and event.pressed:
		var step := 0.0
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			step = 1.15
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			step = 1.0 / 1.15
		if step > 0.0:
			# Si ingrandisce VERSO IL PUNTATORE: quel che sta sotto il mouse ci resta. Con
			# l'ingrandimento sul centro, avvicinarsi a un fiume e' una caccia.
			var before := to_hex_space(event.position)
			var zoom := clampf(camera.zoom.x * step, 0.05, 64.0)
			camera.zoom = Vector2(zoom, zoom)
			camera.position += before - to_hex_space(event.position)
			queue_redraw()
	elif event is InputEventMouseMotion and (event.button_mask & MOUSE_BUTTON_MASK_LEFT):
		# Qualche pixel di tolleranza: una mano che clicca si muove sempre un po', e senza
		# questa soglia scegliere un esagono riuscirebbe una volta su tre.
		if event.position.distance_to(pressed_at) > 4.0:
			dragged = true
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
	draw_selection()


## Il contorno dell'esagono scelto. Si disegna SEMPRE, anche con la griglia spenta e anche da
## lontano dove le linee non si accendono: la griglia e' un aiuto che si puo' togliere, la
## scelta e' una risposta e non si puo' perdere di vista. Da lontano l'esagono e' meno di un
## pixel, quindi sotto un certo ingrandimento il contorno si allarga a mirino -- un puntino
## di un pixel su un terreno mosso non si trova piu'.
func draw_selection() -> void:
	if selected.x < 0 or selected.y < 0:
		return
	var scale := camera.zoom.x
	var centre := Vector2(Hex.centre_x(selected.x, selected.y), Hex.centre_y(selected.y))
	var ink := Color(0.98, 0.93, 0.58)
	var thickness := 2.0 / scale
	var outline := PackedVector2Array()
	outline.resize(7)
	var corners := Hex.corners()
	# Sotto i sei pixel per cella il contorno diventa un mirino largo abbastanza da vedersi:
	# non e' piu' la forma dell'esagono, ma dice dove si e' scelto, che e' cio' che serve.
	var span := maxf(1.0, 12.0 / scale)
	for i in range(6):
		outline[i] = centre + corners[i] * span
	outline[6] = outline[0]
	draw_polyline(outline, ink, thickness, true)


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
	# Gli angoli dell'inquadratura passano dalla stessa funzione che usa chi clicca. Erano
	# due volte la stessa aritmetica, e due volte la stessa aritmetica e' una volta di
	# troppo: il giorno in cui la telecamera prende uno scostamento, una delle due resta
	# indietro e le linee si disegnano dove nessuno sta guardando.
	var window := Vector2(get_viewport_rect().size)
	var top_left := to_hex_space(Vector2.ZERO)
	var bottom_right := to_hex_space(window)
	var col0 := maxi(0, int(floor(top_left.x)) - 2)
	var col1 := mini(size - 1, int(ceil(bottom_right.x)) + 1)
	var row0 := maxi(0, int(floor(top_left.y / Hex.row_ratio())) - 1)
	var row1 := mini(size - 1, int(ceil(bottom_right.y / Hex.row_ratio())) + 1)

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
