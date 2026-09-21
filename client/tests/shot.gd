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
	# Dove guardare, se il chiamante lo dice: quattro numeri, una direzione e una distanza.
	# Serve a fotografare un posto PRECISO -- un fiume, una costa -- invece di sperare che
	# quel che interessa capiti davanti all'obiettivo. Un fiume largo mezzo pixel inquadrato
	# in mezzo all'oceano si legge come un fiume che non c'e'.
	# UN FOTOGRAMMA PRIMA DI CERCARE QUALUNQUE COSA NELL'ALBERO. I gruppi a cui un nodo si
	# iscrive dentro `_ready` non si possono ancora interrogare, e la telecamera non e'
	# ancora quella attiva: subito dopo `add_child` la scena esiste ma non si e' ancora
	# sistemata. Senza questa riga la ricerca restituiva zero, in silenzio, e l'inquadratura
	# restava quella di partenza -- il che somiglia moltissimo a una fotografia riuscita.
	await process_frame
	if args.size() >= 7:
		# Si chiede al GLOBO di guardare da li', non alla telecamera: e' il globo la cosa che
		# si tiene in mano, e chi inquadra non deve sapere come si chiama il nodo che guarda.
		for rig in get_nodes_in_group("picker"):
			rig.aim(Vector3(float(args[3]), float(args[4]), float(args[5])), float(args[6]))
	# Un ottavo argomento chiede di scegliere la casella al centro dello schermo, cosi' si
	# puo' fotografare anche cio' che succede DOPO un clic. Senza, l'unico modo di vedere la
	# selezione sarebbe fidarsi.
	if args.size() >= 8 and args[7] == "seleziona":
		var middle := Vector2(root.size) * 0.5
		for picker in get_nodes_in_group("picker"):
			picker.select_at_screen(middle)
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
