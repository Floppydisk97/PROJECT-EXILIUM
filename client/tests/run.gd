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
const Patience := preload("res://exilium/patience.gd")
const Api := preload("res://exilium/api.gd")
const Fmt := preload("res://exilium/format.gd")
const City := preload("res://exilium/city.gd")

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
	test_selection()
	test_area()
	await test_patience()
	test_format()
	test_city_screen()
	await test_api()
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


# Un orologio e un sonno finti, per provare novanta secondi di pazienza in zero secondi veri.
# Una pazienza che per essere verificata chiede novanta secondi, in pratica non si verifica.
class FakeClock extends RefCounted:
	var ms := 0
	var slept: Array[int] = []

	func now() -> int:
		return ms

	func sleep_for(pause: int) -> void:
		slept.append(pause)
		ms += pause


func test_patience() -> void:
	print("\nLa pazienza, contro un'istanza che dorme")
	var budget := Patience.Budget.new(90_000, 1500, 8000)

	# Se ogni rifiuto e' istantaneo, si bussa per TUTTO il budget. E' il difetto che questo
	# file porta scritto in cima: contando i tentativi, quattro rifiuti immediati spendevano
	# diciotto secondi di una pazienza che ne prometteva novanta.
	var clock := FakeClock.new()
	var knocked: Patience.Knocked = await Patience.keep_knocking(
		budget, func(_n): return null, clock.now, clock.sleep_for)
	check(knocked.value == null, "ha risposto qualcosa a chi non risponde mai")
	check(knocked.elapsed_ms >= 90_000,
		  "si e' arreso dopo %d ms invece dei 90.000 promessi" % knocked.elapsed_ms)

	# E non oltre: la scadenza e' una promessa su quando si smette, non un pavimento che
	# un'ultima pausa lunga possa sfondare.
	check(knocked.elapsed_ms == 90_000,
		  "ha dormito oltre la scadenza: %d ms" % knocked.elapsed_ms)

	# La pausa raddoppia ma si ferma al tetto: un'attesa lunga non deve essere anche un
	# martellamento, e nemmeno una resa lenta.
	check(clock.slept[0] == 1500 and clock.slept[1] == 3000 and clock.slept[2] == 6000,
		  "le prime pause non raddoppiano: %s" % [clock.slept.slice(0, 3)])
	check(clock.slept[3] == 8000 and clock.slept[4] == 8000,
		  "la pausa ha superato il tetto di 8 s: %s" % [clock.slept.slice(3, 5)])

	# Un risveglio dentro il budget si aspetta e si prende.
	clock = FakeClock.new()
	knocked = await Patience.keep_knocking(
		budget, func(n): return "sveglio" if n >= 5 else null, clock.now, clock.sleep_for)
	check(knocked.value == "sveglio", "non ha aspettato un risveglio dentro il budget")
	check(knocked.attempts == 5, "tentativi: %d invece di 5" % knocked.attempts)

	# Una risposta al primo colpo non spende niente: nessuna pausa, nessun tempo.
	clock = FakeClock.new()
	knocked = await Patience.keep_knocking(
		budget, func(_n): return "subito", clock.now, clock.sleep_for)
	check(knocked.attempts == 1 and knocked.elapsed_ms == 0 and clock.slept.is_empty(),
		  "ha speso qualcosa per una risposta immediata")


func test_format() -> void:
	# Gli stessi casi che prova il visore web, letti dallo stesso file. Non una copia: se
	# `format.ts` e `format.gd` si allontanano, uno dei due schermi dira' "fermo" dove
	# l'altro dice "pieno" -- due stati che chiedono a chi gioca due cose opposte.
	print("\nLe parole dei numeri, contro i casi condivisi")
	var root_path := ProjectSettings.globalize_path("res://")
	var path := root_path.path_join("../frontend/app/city/format.cases.json").simplify_path()
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		fail("casi non trovati: " + path)
		return
	var cases = JSON.parse_string(file.get_as_text())
	file.close()
	if cases == null:
		fail("casi illeggibili: " + path)
		return

	for entry in cases["units"]:
		check(Fmt.units(entry[0]) == entry[1],
			  "units(%s): atteso \"%s\", ottenuto \"%s\"" % [entry[0], entry[1], Fmt.units(entry[0])])
	for entry in cases["how_long"]:
		check(Fmt.how_long(float(entry[0])) == entry[1],
			  "how_long(%s): atteso \"%s\", ottenuto \"%s\""
			  % [entry[0], entry[1], Fmt.how_long(float(entry[0]))])
	for entry in cases["stall_note"]:
		check(Fmt.stall_note(entry[0]) == entry[1],
			  "stall_note(%s): atteso \"%s\", ottenuto \"%s\""
			  % [entry[0], entry[1], Fmt.stall_note(entry[0])])
	for entry in cases["stall_short"]:
		check(Fmt.stall_short(entry[0]) == entry[1],
			  "stall_short(%s): atteso \"%s\", ottenuto \"%s\""
			  % [entry[0], entry[1], Fmt.stall_short(entry[0])])
	for entry in cases["missing_for"]:
		var got := Fmt.missing_for(entry[0], entry[1])
		var want: Dictionary = entry[2]
		var same := got.size() == want.size()
		if same:
			for resource in want:
				if not got.has(resource) or absf(float(got[resource]) - float(want[resource])) > 1e-9:
					same = false
		check(same, "missing_for(%s, %s): atteso %s, ottenuto %s"
			  % [entry[0], entry[1], want, got])
	print("  ", cases["units"].size() + cases["how_long"].size() + cases["stall_note"].size()
		  + cases["stall_short"].size() + cases["missing_for"].size(),
		  " casi, gli stessi del visore web")


func test_city_screen() -> void:
	# Lo schermo della citta' legge una risposta VERA del server: `tests/city.sample.json` e'
	# uscito da `app.service.read_city` contro un Postgres con lo schema del progetto, non e'
	# stato scritto a mano. Cosi' "il client legge i campi che il server manda" e' una cosa
	# che si prova invece di una che si spera.
	print("\nLo schermo della citta'")
	var file := FileAccess.open("res://tests/city.sample.json", FileAccess.READ)
	if file == null:
		fail("istantanea non trovata")
		return
	var sample = JSON.parse_string(file.get_as_text())
	file.close()
	if sample == null or not sample.has("city"):
		fail("istantanea illeggibile")
		return
	var city: Dictionary = sample["city"]

	var text := City.describe(city, "prova")
	# I tre stati dello stallo, tutti e tre nella stessa istantanea: e' la ragione per cui
	# questa citta' e' stata costruita cosi' invece che appena fondata. Se due di loro si
	# scambiassero, chi gioca spenderebbe per una risorsa che li' non arrivera' mai.
	check(text.contains("food") and text.contains("pieno\n"),
		  "un magazzino pieno non e' detto pieno")
	check(text.contains("timber") and text.contains("fermo"),
		  "un magazzino che non si riempira' mai non e' detto fermo")
	check(text.contains("pieno fra"), "nessun magazzino dice fra quanto sara' pieno")

	# La corrente come flusso, gli impianti col loro nome dal catalogo del server -- non una
	# tabella di etichette scritta nel client, che sarebbe il nono elenco da tenere allineato.
	check(text.contains("60 prodotti") and text.contains("14 usati"),
		  "la corrente non e' letta come flusso")
	check(text.contains("2 × Eolico") and text.contains("1 × Fonderia"),
		  "gli impianti non prendono il nome dal catalogo del server")
	check(text.contains("livello 0 di 7 sostenibili"), "il livello non e' letto")

	# E i campi che lo schermo usa ci sono TUTTI nella risposta. Un campo che il server non
	# manda piu' si nota qui, e non su uno schermo che mostra uno zero plausibile.
	var needed := ["name", "level", "supported_level", "policy", "stock_milli",
				   "stalls_in_seconds", "power_made", "power_used", "work_permille",
				   "site_power", "catalogue", "works", "works_idle",
				   "next_upgrade_cost_milli", "next_upgrade_seconds", "busy_with"]
	var absent: Array[String] = []
	for field in needed:
		if not city.has(field):
			absent.append(field)
	check(absent.is_empty(), "campi che lo schermo usa e la risposta non ha: %s" % [absent])
	print("  ", needed.size(), " campi letti da una risposta vera del server")


func test_api() -> void:
	print("\nIl discorso col server")

	# L'indirizzo si pulisce come lo pulisce chi lo legge a occhio: senza, un percorso
	# diventa `https://host//cities` e il server risponde 404 a una richiesta giusta.
	check(Api.clean_base("https://esempio.it/") == "https://esempio.it",
		  "la barra finale non e' stata tolta")
	check(Api.clean_base("  https://esempio.it///  ") == "https://esempio.it",
		  "spazi e barre multiple non sono stati tolti")
	check(Api.clean_base("") == "", "un indirizzo vuoto non e' rimasto vuoto")

	# Che cosa significa uno stato. E' la decisione su cui poggia tutta la pazienza: se un
	# 401 finisse fra quelli su cui insistere, un token sbagliato terrebbe lo schermo fermo
	# novanta secondi per poi dire la stessa cosa che poteva dire subito.
	check(Api.verdict(200) == Api.Verdict.ANSWERED, "un 200 non e' una risposta")
	check(Api.verdict(201) == Api.Verdict.ANSWERED, "un 201 non e' una risposta")
	check(Api.verdict(401) == Api.Verdict.UNAUTHORISED, "un 401 non e' un token rifiutato")
	check(Api.verdict(403) == Api.Verdict.UNAUTHORISED, "un 403 non e' un token rifiutato")
	check(Api.verdict(422) == Api.Verdict.REFUSED, "un 422 non e' un rifiuto")
	check(Api.verdict(404) == Api.Verdict.REFUSED, "un 404 non e' un rifiuto")
	check(Api.verdict(429) == Api.Verdict.KEEP_KNOCKING, "su un 429 non si insiste")
	check(Api.verdict(500) == Api.Verdict.KEEP_KNOCKING, "su un 500 non si insiste")
	check(Api.verdict(503) == Api.Verdict.KEEP_KNOCKING, "su un 503 non si insiste")

	# La chiave di idempotenza: un UUID versione 4, e soprattutto DIVERSA ogni volta. Una
	# chiave che si ripete e' un ordine che il server considera gia' eseguito e non esegue.
	var seen := {}
	var malformed := 0
	for i in range(500):
		var key := Api.random_uuid()
		if key.length() != 36 or key[14] != "4" or not (key[19] in ["8", "9", "a", "b"]):
			malformed += 1
		seen[key] = true
	check(malformed == 0, "chiavi malformate: %d su 500" % malformed)
	check(seen.size() == 500, "chiavi ripetute: %d distinte su 500" % seen.size())

	# Senza server e senza token non si chiama affatto, e si dice quale delle due cose manca:
	# "errore" non dice a chi guarda che cosa deve fare.
	# Senza annotazione di tipo: sotto `--script` i nomi di classe non sono registrati, e
	# `ExiliumApi` qui non esisterebbe. Stessa ragione dei preload in cima a questo file.
	var api := Api.new()
	# Nell'albero anche qui, e un fotogramma dopo: altrimenti si proverebbe il rifiuto
	# sbagliato -- quello di un client non montato invece di quello di un server mancante.
	root.add_child(api)
	await process_frame
	api.base = ""
	api.token = "qualcosa"
	var reply: Api.Reply = await api.call_api("/world")
	check(reply.why == Api.Why.NO_SERVER, "senza server non ha detto che manca il server")
	api.base = "https://esempio.it"
	api.token = ""
	reply = await api.call_api("/world")
	check(reply.why == Api.Why.NO_TOKEN, "senza token non ha detto che manca il token")
	api.queue_free()

	# E contro un server vero, se ce n'e' uno da provare. Il resto di questo file non tocca
	# la rete apposta; questo pezzo si', perche' le coroutine e le intestazioni sono la parte
	# che si rompe in silenzio e che nessuna prova pura vede.
	if OS.has_environment("EXILIUM_TEST_API"):
		await test_api_live(OS.get_environment("EXILIUM_TEST_API"))
	else:
		print("  (salto la prova contro un server vero: EXILIUM_TEST_API non e' impostata)")


func test_api_live(where: String) -> void:
	# Senza annotazione di tipo: sotto `--script` i nomi di classe non sono registrati, e
	# `ExiliumApi` qui non esisterebbe. Stessa ragione dei preload in cima a questo file.
	var api := Api.new()
	# La scena serve: `HTTPRequest` e' un nodo, e un nodo fuori dall'albero non manda niente.
	# E UN FOTOGRAMMA DOPO, prima di chiamare: e' la stessa trappola gia' scritta in
	# `shot.gd`. Senza, la prima richiesta falliva con ERR_UNCONFIGURED, il client la
	# prendeva per un server addormentato, aspettava una pausa e riusciva alla seconda -- e
	# la prova "ha aspettato almeno 1,5 secondi" passava per il motivo sbagliato.
	root.add_child(api)
	await process_frame
	api.base = Api.clean_base(where)
	api.token = "prova"

	# Il percorso che il finto server fa dormire due volte prima di rispondere: e' la
	# partenza a freddo, ed e' il caso per cui `patience.gd` esiste.
	var reply: Api.Reply = await api.call_api("/sveglia")
	check(reply.ok() and reply.value is Dictionary and reply.value["status"] == "ok",
		  "non ha aspettato il risveglio: %s" % reply.detail)
	check(reply.waited_ms >= 1500, "ha risposto senza aspettare: %d ms" % reply.waited_ms)

	# Un token rifiutato NON si ribussa: deve tornare subito.
	reply = await api.call_api("/rifiuto-token")
	check(reply.why == Api.Why.BAD_TOKEN, "un 401 non e' diventato un token rifiutato")
	check(reply.waited_ms < 1000, "ha insistito su un 401 per %d ms" % reply.waited_ms)

	# E la ragione del server si riporta invece di inventarne una.
	reply = await api.call_api("/rifiuto")
	check(reply.why == Api.Why.REFUSAL, "un 422 non e' diventato un rifiuto")
	check(reply.detail == "tile already taken",
		  "la ragione del server non e' arrivata: \"%s\"" % reply.detail)

	# Un POST porta il token e una chiave di idempotenza. Il finto server rimanda indietro
	# cio' che ha ricevuto, cosi' non ci si fida di cio' che il client crede di aver mandato.
	reply = await api.call_api("/eco", HTTPClient.METHOD_POST, {"kind": "farm"})
	check(reply.ok(), "il POST non e' riuscito: %s" % reply.detail)
	if reply.ok():
		var echoed: Dictionary = reply.value
		check(echoed["authorization"] == "Bearer prova",
			  "il POST non ha portato il token: %s" % echoed["authorization"])
		check(String(echoed["idempotency_key"]).length() == 36,
			  "il POST non ha portato una chiave di idempotenza")
		check(echoed["body"] == "{\"kind\":\"farm\"}",
			  "il corpo del POST e' arrivato diverso: %s" % echoed["body"])
	print("  contro un server vero: tutto quanto sopra, sulla rete")
	api.queue_free()


func test_area() -> void:
	# Un edificio non occupa un esagono: ne occupa un pezzo di maglia. Qui si prova la
	# misura con cui quel pezzo si conta, perche' e' quella che dira' "ci sta" o "non ci sta"
	# e un "ci sta" sbagliato si scopre solo dopo aver posato.
	print("\nL'area attorno a un esagono")
	var side := 64

	# La distanza e' simmetrica, vale zero solo su se stessi, e fra due vicini e' uno. Sono
	# le tre cose che rendono una distanza una distanza; senza la terza, un raggio di uno
	# prenderebbe celle che non si toccano.
	var wrong := 0
	for row in range(4, 12):
		for col in range(4, 12):
			var here := Vector2i(col, row)
			if Hex.distance(here, here) != 0:
				wrong += 1
			for other in Hex.neighbours(col, row):
				if Hex.distance(here, other) != 1:
					wrong += 1
				if Hex.distance(other, here) != Hex.distance(here, other):
					wrong += 1
	check(wrong == 0, "distanze sbagliate: %d" % wrong)

	# Un raggio prende i NUMERI ESAGONALI CENTRATI: 1, 7, 19, 37, 61. Se ne prendesse di
	# piu' si starebbe contando un rombo, che ha le punte lunghe il doppio, e un edificio
	# "da 19 caselle" ne occuperebbe 25 delle quali sei in fila da una parte sola.
	var centre := Vector2i(32, 32)
	for r in range(6):
		var cells := Hex.within(centre, r, side)
		check(cells.size() == 3 * r * (r + 1) + 1,
			  "raggio %d: %d celle invece di %d" % [r, cells.size(), 3 * r * (r + 1) + 1])

	# E sono davvero tutte e sole quelle entro quel raggio: il conto giusto con le celle
	# sbagliate e' esattamente l'errore che un conto non vede.
	var outside := 0
	var missing := 0
	var inside := Hex.within(centre, 3, side)
	for cell in inside:
		if Hex.distance(centre, cell) > 3:
			outside += 1
	for row in range(side):
		for col in range(side):
			if Hex.distance(centre, Vector2i(col, row)) <= 3 and not inside.has(Vector2i(col, row)):
				missing += 1
	check(outside == 0 and missing == 0,
		  "area a raggio tre: %d celle di troppo, %d mancanti" % [outside, missing])

	# Contro il bordo l'area si TAGLIA e non sborda ne' gira dall'altra parte. Una mappa che
	# si richiude sarebbe una colonia in cui il nord confina col sud.
	for cell in Hex.within(Vector2i(0, 0), 3, side):
		if cell.x < 0 or cell.y < 0 or cell.x >= side or cell.y >= side:
			outside += 1
	check(outside == 0, "l'area al bordo esce dalla mappa: %d celle" % outside)
	check(Hex.within(Vector2i(0, 0), 3, side).size() < 37,
		  "l'area contro l'angolo non si e' tagliata")

	# Le frecce si muovono di un esagono esatto, e le due direzioni orizzontali sono davvero
	# opposte: su una maglia sfalsata e' l'unica coppia di cui ci si possa fidare.
	var from := Vector2i(20, 21)
	var left: Vector2i = Hex.neighbours(from.x, from.y)[Colony.ARROWS[KEY_LEFT]]
	var right: Vector2i = Hex.neighbours(from.x, from.y)[Colony.ARROWS[KEY_RIGHT]]
	check(left == Vector2i(from.x - 1, from.y) and right == Vector2i(from.x + 1, from.y),
		  "le frecce orizzontali non si muovono di una colonna")
	for key in Colony.ARROWS:
		var step: Vector2i = Hex.neighbours(from.x, from.y)[Colony.ARROWS[key]]
		check(Hex.distance(from, step) == 1,
			  "la freccia %d salta %d celle" % [key, Hex.distance(from, step)])


func test_selection() -> void:
	# Scegliere un esagono e' la prima cosa che il giocatore fa, ed e' la piu' facile da
	# sbagliare in silenzio: se la cella scelta non e' quella disegnata, il terreno e' giusto,
	# le linee sono giuste, e il gioco risponde su un'altra casella. Qui si legano insieme le
	# due cose che devono coincidere -- dove il PENNELLO mette il colore e dove la SCELTA
	# cerca l'esagono -- senza aprire nessuna finestra.
	print("\nLa scelta di un esagono")
	var side := 48

	# Uno: il pennello e la maglia parlano dello stesso posto. Ogni cella occupa due pixel in
	# larghezza, a `col * 2 + dispari`, e una riga in altezza. Il centro di quella coppia di
	# pixel deve cadere esattamente sul centro dell'esagono, e quel punto deve ritrovare
	# l'esagono da cui si e' partiti.
	var off := 0
	for row in range(side):
		var odd := row & 1
		for col in range(side):
			# Il centro della coppia di pixel, in unita': due pixel per esagono, quindi un
			# pixel vale mezza unita'.
			var middle := (col * 2 + odd + 1) * 0.5
			if absf(middle - Hex.centre_x(col, row)) > 1e-12:
				off += 1
			elif Hex.hex_at(middle, Hex.centre_y(row), side) != Vector2i(col, row):
				off += 1
	check(off == 0, "celle in cui il pennello e la scelta non concordano: %d" % off)

	# Due: "edificabile" e' una sola idea. `Colony.BUILDABLE` risponde a chi clicca,
	# `economy_of` promette un numero prima di atterrare, e sono due elenchi degli stessi
	# quattro terreni. Se si allontanano, il rilevamento promette caselle libere che poi non
	# lo sono -- e il giocatore se ne accorge solo dopo aver scelto dove vivere.
	var made := Citygen.generate("scelta-di-prova", {
		"biome": "temperate_forest", "elevation": 220, "temperature": 12.0,
		"rainfall": 1100, "river_flow": 0, "coastal": false,
	}, side)
	var buildable := 0
	for row in range(side):
		for col in range(side):
			if Colony.facts_of(made, col, row)["buildable"]:
				buildable += 1
	var economy := Citygen.economy_of(made)
	check(buildable == economy["room"],
		  "edificabili: la scelta ne conta %d, il rilevamento %d" % [buildable, economy["room"]])

	# E i fatti sono quelli delle colonne, non inventati: una cella a caso, confrontata con
	# gli array da cui e' disegnata.
	var cells: PackedByteArray = made["ground"]
	var names: Array = made["ground_names"]
	var heights: PackedInt32Array = made["height"]
	var facts := Colony.facts_of(made, 17, 23)
	var at := 23 * side + 17
	check(facts["ground"] == names[cells[at]] and facts["height"] == heights[at]
		  and facts["index"] == at,
		  "i fatti della cella (17, 23) non sono quelli delle sue colonne")

	# Tre: il pixel di mezzo dello schermo e' il punto che la telecamera sta guardando, e un
	# pixel scelto a caso torna al suo posto. E' il conto che traduce un clic in un esagono, e
	# ha gia' sbagliato una volta: `select_at_screen` chiedeva la trasformazione alla tela,
	# che racconta dov'era l'inquadratura il fotogramma prima. Spostare lo sguardo e scegliere
	# subito dava la cella di dov'era prima -- e una cella la restituiva comunque, quindi
	# sembrava funzionare. Qui il conto e' uno, esplicito, e si prova.
	var window := Vector2(1152, 648)
	var where := Vector2(232.5, 164.6)
	var zoom := 26.0
	check(Colony.hex_space(window * 0.5, where, zoom, window) == where,
		  "il pixel di mezzo non e' il punto guardato")
	var somewhere := Vector2(311.0, 92.0)
	var back := (Colony.hex_space(somewhere, where, zoom, window) - where) * zoom + window * 0.5
	# Un millesimo di pixel, non zero: `Vector2` tiene numeri a 32 bit, e il giro di andata e
	# ritorno ne consuma qualche cifra. La tolleranza e' scelta su cio' che conta -- un
	# esagono qui vale ventisei pixel, quindi un millesimo di pixel non ha mai scelto una
	# cella diversa -- e non su cio' che fa passare la prova.
	check(back.distance_to(somewhere) < 1e-3,
		  "un pixel qualunque non torna al suo posto: %s invece di %s" % [back, somewhere])

	# Fuori mappa non si sceglie niente. Un dizionario vuoto e non una cella al bordo: chi
	# clicca sul cielo non deve ritrovarsi a costruire sull'ultima riga.
	check(Colony.facts_of(made, side, 0).is_empty(), "una colonna fuori mappa ha risposto")
	check(Colony.facts_of(made, 0, -1).is_empty(), "una riga negativa ha risposto")
	check(Hex.hex_at(-0.1, 1.0, side) == Vector2i(-1, -1), "un punto a sinistra della mappa ha risposto")


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
