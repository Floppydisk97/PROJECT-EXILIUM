# Quanto costa generare un terreno in GDScript. Non e' un test -- non ha un verdetto -- ma
# vive accanto a quelli perche' la risposta decide l'architettura del client:
#
#     godot --headless --path client --script res://tests/bench.gd
#
# Misurato a suo tempo, sulla stessa macchina che misurava 0,62 s per lo stesso lavoro in
# JavaScript: GDScript e' circa quattro volte e mezzo piu' lento. A 2,36 milioni di esagoni
# sono una decina di secondi, che per uno schermo di caricamento e' troppo.
#
# La via d'uscita naturale e' il parallelismo -- il generatore e' puro e ogni cella e'
# indipendente -- e un'applicazione desktop ha thread veri. NON e' stato possibile misurarlo:
# la macchina su cui e' stato scritto questo file e' limitata sulla CPU, e anche quattro
# processi separati ci scalavano solo 1,5 volte. Va rimisurato su una macchina vera prima di
# costruirci sopra.
extends SceneTree

const Citygen := preload("res://exilium/citygen.gd")

func _initialize() -> void:
	var site := {"biome": "temperate_forest", "elevation": 220, "temperature": 12.0,
				 "rainfall": 1100, "river_flow": 0, "coastal": false}
	print("core dichiarati dal sistema: ", OS.get_processor_count())
	for size in [384, 768]:
		var t := Time.get_ticks_msec()
		Citygen.generate("m", site, size)
		var d := Time.get_ticks_msec() - t
		print("generate %5d di lato (%.2f M celle) -> %.2f s"
			  % [size, size * size / 1e6, d / 1000.0])
	quit(0)
