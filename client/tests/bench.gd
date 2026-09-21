# Quanto costa generare un terreno in GDScript, e se i thread veri lo recuperano.
#
#     godot --headless --path client --script res://tests/bench.gd
#
# Non e' un test: non ha un verdetto e non fa cadere niente. Ma la risposta decide
# l'architettura del client, quindi il numero deve venire da una macchina vera. Quella su cui
# questo file e' stato scritto e' limitata sulla CPU -- anche quattro PROCESSI separati ci
# scalavano solo 1,5 volte -- quindi la misura del parallelismo li' non valeva niente. Gira
# in CI, dove i core sono quattro e non strozzati.
#
# Il confronto che conta: 0,59 M celle sono 0,62 s in JavaScript e ~2,8 s qui. Se il
# parallelismo non recupera quel divario, a 2,36 milioni di esagoni siamo a una decina di
# secondi, e le vie sono C# (Godot .NET) o una GDExtension, in quest'ordine.
extends SceneTree

const Citygen := preload("res://exilium/citygen.gd")

const SITE := {"biome": "temperate_forest", "elevation": 220, "temperature": 12.0,
			   "rainfall": 1100, "river_flow": 0, "coastal": false}
const BLOCK := 384          # 0,15 M celle: un quarto del lavoro di riferimento

func one(index: int) -> void:
	# Semi diversi, se no un motore furbo potrebbe accorgersi che e' lo stesso lavoro.
	Citygen.generate("bench-%d" % index, SITE, BLOCK)

func _initialize() -> void:
	print("core dichiarati dal sistema: ", OS.get_processor_count())

	var t := Time.get_ticks_msec()
	Citygen.generate("m", SITE, 768)
	print("una sola passata, 0,59 M celle -> %.2f s" % [(Time.get_ticks_msec() - t) / 1000.0])

	t = Time.get_ticks_msec()
	for i in range(4):
		one(i)
	var serial := float(Time.get_ticks_msec() - t) / 1000.0

	t = Time.get_ticks_msec()
	var group := WorkerThreadPool.add_group_task(one, 4, 4)
	WorkerThreadPool.wait_for_group_task_completion(group)
	var parallel := float(Time.get_ticks_msec() - t) / 1000.0

	print("quattro blocchi in fila        -> %.2f s" % serial)
	print("gli stessi quattro in parallelo -> %.2f s   (%.1fx)" % [parallel, serial / parallel])
	print("proiezione a 2,36 M esagoni: %.1f s da solo, %.1f s sui thread"
		  % [serial * 4.0, parallel * 4.0])
	quit(0)
