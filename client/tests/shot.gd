# Una fotografia di una scena, senza schermo:
#
#     xvfb-run -a godot --rendering-driver opengl3 --path client \
#         --script res://tests/shot.gd -- res://scene.tscn /tmp/fuori.png
#
# Esiste perche' un visore e' l'unico posto dove sbagliare non si vede: viene fuori una cosa
# un po' strana, e una cosa un po' strana sembra una scelta. Finche' l'unico modo di
# guardare e' aprire l'editor, ogni verifica grafica e' un "fidati". Cosi' invece la si
# guarda -- e la si puo' anche mettere in un test, il giorno in cui serve.
#
# `--headless` no: quello non disegna affatto. Serve un server grafico finto (xvfb) e il
# disegno via OpenGL su Mesa, che e' lento ma vero.
extends SceneTree

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 2:
		printerr("uso: --script res://tests/shot.gd -- <scena.tscn> <fuori.png> [fotogrammi]")
		quit(2)
		return
	var scene := load(args[0])
	if scene == null:
		printerr("scena non caricabile: ", args[0])
		quit(2)
		return
	root.add_child(scene.instantiate())
	# Qualche fotogramma prima dello scatto: il primo non ha ancora niente dentro, e una
	# fotografia di una tela vuota e' il modo piu' rapido di credere che funzioni tutto.
	var frames := int(args[2]) if args.size() > 2 else 4
	for i in range(frames):
		await process_frame
	var image := root.get_texture().get_image()
	var error := image.save_png(args[1])
	if error != OK:
		printerr("non scritta: ", args[1])
		quit(1)
		return
	print("scritta ", args[1], " (", image.get_width(), "x", image.get_height(), ")")
	quit(0)
