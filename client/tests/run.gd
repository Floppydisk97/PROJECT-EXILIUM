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
	test_reference()
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
