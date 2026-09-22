# I test del client, senza finestra e senza editor:
#
#     godot --headless --path client --script res://tests/run.gd
#
# Nessun framework. Questo file vive per rispondere a una domanda sola -- il gemello GDScript
# del generatore da' le STESSE celle di quello Python e di quello TypeScript? -- e per quella
# domanda un framework sarebbe una dipendenza in piu' da tenere allineata a Godot.
#
# Il riferimento e' UNO: `frontend/app/colony/reference.json`, scritto da `python -m
# app.colonyref` e gia' usato da `citygen.test.ts`. Non ne viene fatta una copia qui dentro --
# due file di riferimento che devono coincidere sarebbero esattamente il difetto che il
# riferimento esiste per impedire.
extends SceneTree

const Citygen := preload("res://exilium/citygen.gd")
const Prng := preload("res://exilium/prng.gd")
const PlanetData := preload("res://exilium/planet.gd")
const Globe := preload("res://exilium/globe.gd")
const Colony := preload("res://exilium/colony.gd")
const Hex := preload("res://exilium/hexgrid.gd")

var failures := 0
var checks := 0


func fail(what: String) -> void:
	failures += 1
	printerr("  FALLITO  ", what)


func check(condition: bool, what: String) -> void:
	checks += 1
	if not condition:
		fail(what)


func _initialize() -> void:
	print("Project Exilium -- test del client (Godot ", Engine.get_version_info()["string"], ")")
	test_prng()
	test_hexgrid()
	test_reference()
	test_planet()
	print("")
	if failures == 0:
		print("OK: ", checks, " verifiche passate")
	else:
		printerr("ROTTO: ", failures, " su ", checks, " verifiche")
	quit(1 if failures > 0 else 0)


func test_prng() -> void:
	print("\nIl generatore su cui poggiano tutti e tre i gemelli")
	# Gli stessi numeri fissati in `citygen.test.ts`, stampati a suo tempo da `app.prng`.
	check(Prng.seed_int("prova") == 2042925649, "seed_int('prova')")
	var rng = Prng.new("prova")
	var want := [1041935993, 290468120, 3660437992, 3639609783, 1645382567]
	for i in range(want.size()):
		var got := rng.next_uint()
		check(got == want[i], "next_uint()[%d]: atteso %d, ottenuto %d" % [i, want[i], got])
	var direction = Prng.new("dir").direction()
	var expect := [-0.860781780089, 0.480693964957, 0.167296261527]
	for i in range(3):
		check(abs(direction[i] - expect[i]) < 1e-11,
			  "direction()[%d]: atteso %f, ottenuto %f" % [i, expect[i], direction[i]])


func test_hexgrid() -> void:
	# La maglia non viaggia nel riferimento: non ha celle da confrontare. Quel che la tiene
	# onesta sono due affermazioni, le stesse che prova `hexgrid.test.ts` -- e sono quelle
	# che si rompono per prime quando lo sfalsamento delle righe dispari viene scritto storto.
	print("\nLa maglia esagonale")
	var side := 32

	# Uno: ogni centro ritrova il PROPRIO esagono. Se questa cade, il terreno e' disegnato
	# mezza cella fuori dalle sue linee a righe alterne, ed e' invisibile finche' non ci si
	# costruisce sopra.
	var strays := 0
	for row in range(side):
		for col in range(side):
			var back := Hex.hex_at(Hex.centre_x(col, row), Hex.centre_y(row), side)
			if back != Vector2i(col, row):
				if strays == 0:
					fail("centro di (%d,%d) ritrovato come (%d,%d)" % [col, row, back.x, back.y])
				strays += 1
	checks += 1
	if strays == 0:
		print("  ", side * side, " centri ritrovano il proprio esagono")

	# E anche da un punto qualunque DENTRO l'esagono, non solo dal centro esatto: e' li' che
	# un arrotondamento a scacchiera sbaglierebbe, lungo i bordi diagonali.
	var inside := 0
	var rng := Prng.new(Prng.seed_int("maglia"))
	for i in range(400):
		var col := int(rng.random() * side)
		var row := int(rng.random() * side)
		var angle := rng.random() * TAU
		var far := rng.random() * 0.40          # dentro il raggio, 1/sqrt(3) = 0,577
		var back := Hex.hex_at(Hex.centre_x(col, row) + cos(angle) * far,
							   Hex.centre_y(row) + sin(angle) * far, side)
		if back == Vector2i(col, row):
			inside += 1
	check(inside == 400, "punti dentro l'esagono ritrovati: %d su 400" % inside)

	# Due: il vicinato e' RECIPROCO. Se a e' vicino di b, b e' vicino di a -- altrimenti la
	# distanza dalla riva, che si propaga di vicino in vicino, cola da una parte sola.
	var broken := 0
	for row in range(side):
		for col in range(side):
			for other in Hex.neighbours(col, row):
				if other.x < 0 or other.y < 0 or other.x >= side or other.y >= side:
					continue
				if not Hex.neighbours(other.x, other.y).has(Vector2i(col, row)):
					if broken == 0:
						fail("(%d,%d) vicino di (%d,%d) ma non viceversa"
							 % [col, row, other.x, other.y])
					broken += 1
	checks += 1
	if broken == 0:
		print("  vicinato reciproco su tutte e ", side * side, " le celle")

	# E i sei vicini stanno davvero a un esagono di distanza: un vicino a due passi sarebbe
	# un vicinato che sembra giusto e propaga il doppio.
	var far_off := 0
	for row in range(1, side - 1):
		for col in range(1, side - 1):
			# A mano e non con `Vector2`: quello tiene numeri a 32 bit, e a 32 bit una
			# distanza che vale esattamente uno arriva con sette cifre giuste invece di
			# quindici -- la prova passerebbe solo allargando la tolleranza fino a non
			# provare piu' granche'.
			var hx := Hex.centre_x(col, row)
			var hy := Hex.centre_y(row)
			for other in Hex.neighbours(col, row):
				var dx := Hex.centre_x(other.x, other.y) - hx
				var dy := Hex.centre_y(other.y) - hy
				if absf(sqrt(dx * dx + dy * dy) - 1.0) > 1e-12:
					far_off += 1
	check(far_off == 0, "vicini a distanza diversa da un esagono: %d" % far_off)

	# Il contorno: sei vertici, il primo dritto in su. E' la punta in alto dell'immagine di
	# riferimento, ed e' cio' che distingue questa maglia da quella ruotata di 30 gradi.
	var corners := Hex.corners()
	check(corners.size() == 6, "il contorno ha %d vertici invece di 6" % corners.size())
	check(absf(corners[0].x) < 1e-12 and corners[0].y < 0.0,
		  "il primo vertice non e' la punta in alto: %s" % corners[0])

	# E la mappa e' un rettangolo largo, non un quadrato: le righe distano sqrt(3)/2.
	check(absf(Hex.map_height(side) - side * Citygen.row_ratio()) < 1e-12,
		  "l'altezza della mappa non segue il rapporto fra le righe")


func test_reference() -> void:
	# Il riferimento sta fuori da `res://`: e' condiviso con il frontend e ne esiste una copia
	# sola. Godot apre percorsi assoluti, quindi si risale dal progetto invece di duplicarlo.
	var root := ProjectSettings.globalize_path("res://")
	var path := root.path_join("../frontend/app/colony/reference.json").simplify_path()
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		fail("riferimento non trovato: " + path)
		return
	var reference = JSON.parse_string(file.get_as_text())
	file.close()
	if reference == null:
		fail("riferimento illeggibile: " + path)
		return

	var size: int = reference["size"]
	print("\nI tre gemelli, cella per cella (", size, "x", size, ")")
	for testcase in reference["cases"]:
		var made := Citygen.generate(testcase["seed"], testcase["site"], size)
		var name: String = testcase["name"]
		compare_column(name, "ground", made["ground"], testcase["ground"])
		compare_column(name, "height", made["height"], testcase["height"])
		compare_column(name, "fertility", made["fertility"], testcase["fertility"])
		compare_column(name, "vegetation", made["vegetation"], testcase["vegetation"])
		# E quanto VALE quel terreno, non solo che aspetto ha: e' il numero che il visore
		# promette prima di un atterraggio e che il server scrive dopo.
		var economy := Citygen.economy_of(made)
		var want: Dictionary = testcase["economy"]
		for key in want.keys():
			checks += 1
			if economy.get(key) != want[key]:
				fail("%s: economia %s -- atteso %s, ottenuto %s"
					 % [name, key, want[key], economy.get(key)])

	# Le tinte. `colony.gd` le tiene scritte in casa -- il riferimento e' un attrezzo di prova
	# e non va spedito col gioco -- quindi l'unica cosa che impedisce alla copia di staccarsi
	# dalla sorgente Python e' questo confronto. E' la nona volta che due elenchi devono
	# coincidere: qui non si spera, si verifica.
	print("\nLe tinte del terreno, contro il riferimento")
	var want_grounds: Array = reference["ground_colors"]
	checks += 1
	if want_grounds.size() != Citygen.GROUNDS.size():
		fail("ground_colors ha %d tinte invece di %d"
			 % [want_grounds.size(), Citygen.GROUNDS.size()])
	else:
		for i in range(Citygen.GROUNDS.size()):
			var name: String = Citygen.GROUNDS[i]
			check(Colony.GROUND_COLORS.get(name) == int(want_grounds[i]),
				  "tinta %s: attesa %d, ottenuta %s" % [name, int(want_grounds[i]),
														Colony.GROUND_COLORS.get(name)])
	var want_palette: Dictionary = reference["palette"]
	check(Colony.MEADOW == int(want_palette["meadow"]),
		  "prato: atteso %d, ottenuto %d" % [int(want_palette["meadow"]), Colony.MEADOW])
	check(Colony.FOREST == int(want_palette["forest"]),
		  "bosco: atteso %d, ottenuto %d" % [int(want_palette["forest"]), Colony.FOREST])

	print("\nIl seme, che attraversa il filo fra le copie")
	for entry in reference["seeds"]:
		var got := Citygen.seed_for(entry["world"], entry["tile"])
		check(got == entry["seed"],
			  "seed_for(%s, %d): atteso %s, ottenuto %s"
			  % [entry["world"], entry["tile"], entry["seed"], got])


func compare_column(name: String, what: String, got, want: Array) -> void:
	checks += 1
	if got.size() != want.size():
		fail("%s: %s ha %d celle invece di %d" % [name, what, got.size(), want.size()])
		return
	for i in range(want.size()):
		if got[i] != want[i]:
			fail("%s: %s alla cella %d (riga %d) -- atteso %s, ottenuto %s"
				 % [name, what, i, i / 64, want[i], got[i]])
			return
	print("  ", name, " / ", what, ": ", want.size(), " celle identiche")


func test_planet() -> void:
	# Il pianeta e' un FILE, non una cosa che il client inventa: 231.042 caselle generate una
	# volta sola dal server. Qui si verifica solo che questa copia lo sappia leggere e che la
	# maglia ne esca coerente -- che sia il pianeta GIUSTO lo dice il seme, e quello viaggia
	# dentro al file insieme a tutto il resto.
	print("\nIl pianeta, letto dal file spedito col visore")
	var path: String = PlanetData.find_file()
	if path == "":
		fail("nessun pianeta cotto accanto al progetto")
		return
	var planet = PlanetData.load_from(path)
	if planet == null:
		fail("pianeta illeggibile: " + path)
		return
	check(planet.seed_text != "", "il pianeta porta il suo seme")
	check(planet.tile_count > planet.drawn_count(),
		  "si disegna meno di tutto: l'oceano aperto non viaggia (%d su %d)"
		  % [planet.drawn_count(), planet.tile_count])
	check(planet.ring_offset.size() == planet.drawn_count() + 1,
		  "gli indici degli anelli hanno una voce in piu' delle caselle")
	check(planet.corners.size() % 3 == 0, "i vertici stanno a tre a tre")

	# La maglia: tre vertici per triangolo, e un triangolo per ogni lato di ogni casella.
	var mesh: ArrayMesh = Globe.build_mesh(planet)
	var arrays := mesh.surface_get_arrays(0)
	var points: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var expected := 0
	for i in range(planet.drawn_count()):
		var sides: int = planet.ring_offset[i + 1] - planet.ring_offset[i]
		if sides >= 3:
			expected += sides
	check(points.size() == expected * 3,
		  "triangoli attesi %d, ottenuti %d" % [expected, points.size() / 3])
	# E stanno tutti sulla sfera: un vertice che scappa via e' una casella disegnata nel
	# vuoto, e a 107.000 caselle nessuno la troverebbe guardando.
	var worst := 0.0
	for i in range(0, points.size(), 997):
		worst = maxf(worst, absf(points[i].length() - 1.0))
	check(worst < 0.01, "il vertice piu' lontano dalla sfera sta a %f" % worst)
	print("  ", planet.name_, ": ", planet.drawn_count(), " caselle disegnate, ",
		  points.size() / 3, " triangoli")
