# Lo schermo della citta': cio' che il server dice, messo in parole.
#
# E' l'unica schermata che ha bisogno di qualcosa di acceso. Il pianeta e' un file e il
# terreno della colonia e' una funzione di quel file; le scorte, il livello e cio' a cui la
# citta' e' occupata li decide il server, e qui non si possono calcolare senza inventarli.
#
# Senza server si mostra un'ISTANTANEA, e lo DICE. Uno schermo di prova che si spaccia per
# collegato e' peggio di uno schermo vuoto: fa credere che il gioco funzioni quando non c'e'
# nessuno dall'altra parte.
#
# Le parole dei numeri stanno in `format.gd`, che e' gemello di `format.ts` e prova gli stessi
# casi: "fermo" e "pieno" sono due stati che chiedono a chi gioca due cose opposte, e su due
# schermi diversi devono dire la stessa cosa.
extends Node2D

const Api := preload("res://exilium/api.gd")
const Fmt := preload("res://exilium/format.gd")

## L'istantanea da mostrare quando non c'e' un server. Vuota significa "nessun ripiego": si
## dice che manca il server e basta.
@export_file("*.json") var sample := "res://tests/city.sample.json"

## La citta' da chiedere. Vuota: si prende la prima di `/me/cities`, che e' quel che fa un
## giocatore che ne ha una sola -- cioe' tutti, adesso.
@export var city_id := ""

# Senza annotazione di tipo: sotto `--script` i nomi di classe non sono registrati, e
# `ExiliumApi` qui non esisterebbe. Stessa ragione dei preload in cima al file.
var api: Node
var view: Dictionary
var source := ""
var body: Label
var title: Label


func _ready() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	title = _label(layer, Vector2(28, 22), 26)
	body = _label(layer, Vector2(28, 74), 17)
	# NON il nome di una citta': non si sa ancora quale sia, e uno schermo che mostra un nome
	# mentre non ha ancora nessuna citta' e' uno schermo che mente per un minuto e mezzo.
	title.text = "Colonia"
	# E quanto durera' l'attesa: un'istanza gratuita ci mette una cinquantina di secondi a
	# svegliarsi, e "chiedo al server..." fermo li' senza altro e' indistinguibile da un
	# gioco bloccato -- che e' esattamente come lo legge chi guarda.
	body.text = "chiedo al server... puo' volerci fino a %d secondi, se dormiva." % (
		Api.BUDGET_MS / 1000)

	api = Api.new()
	add_child(api)
	await show_city()


func _label(layer: CanvasLayer, where: Vector2, size: int) -> Label:
	var label := Label.new()
	label.position = where
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", Color8(0xea, 0xf2, 0xf8))
	label.add_theme_color_override("font_outline_color", Color8(0x06, 0x0a, 0x10))
	label.add_theme_constant_override("outline_size", 5)
	layer.add_child(label)
	return label


## Prende la citta' dal server, o dall'istantanea se non c'e' nessuno da chiedere.
func show_city() -> void:
	var reply: Api.Reply = await fetch()
	if reply.ok():
		view = reply.value
		source = "dal server"
	elif sample != "":
		var file := FileAccess.open(sample, FileAccess.READ)
		if file != null:
			var parsed: Variant = JSON.parse_string(file.get_as_text())
			file.close()
			if parsed is Dictionary and parsed.has("city"):
				view = parsed["city"]
				# La ragione per cui non c'e' il server viaggia con l'istantanea: "senza
				# server" e "token rifiutato" chiedono due cose diverse a chi guarda.
				source = "ISTANTANEA -- %s" % reply.detail
	if view.is_empty():
		title.text = "Nessuna citta'"
		body.text = reply.detail
		return
	title.text = str(view["name"])
	body.text = describe(view, source)


## La chiamata. Nessuna scorciatoia per "manca il server" o "manca il token": quei due casi
## li decide gia' `call_api`, e deciderli anche qui significava perdere la differenza fra i
## due -- lo schermo diceva "nessun server" a chi il server ce l'aveva e il token no, cioe'
## mandava a cercare il problema dalla parte sbagliata.
func fetch() -> Api.Reply:
	if city_id == "":
		var mine: Api.Reply = await api.my_cities()
		if not mine.ok():
			return mine
		var cities: Array = mine.value
		if cities.is_empty():
			var empty := Api.Reply.new()
			empty.why = Api.Why.REFUSAL
			empty.detail = "Questo token non ha nessuna citta'."
			return empty
		city_id = str(cities[0]["id"])
	return await api.read_city(city_id)


## Tutto lo schermo in una stringa. Separato dal disegno apposta: e' cio' che si puo' provare
## contro un'istantanea vera, e un pannello si prova solo guardandolo.
static func describe(city: Dictionary, where: String) -> String:
	var lines: Array[String] = []
	lines.append("livello %d di %d sostenibili · politica %s · %s" % [
		int(city["level"]), int(city["supported_level"]), str(city["policy"]), where])

	# I magazzini, ognuno con QUANDO smette di guadagnare. E' la meta' che rende accettabile
	# lo stallo in un mondo che cammina mentre dormi: fermarsi e' la tensione voluta,
	# fermarsi a sorpresa e' una punizione per chi ha un lavoro.
	lines.append("")
	lines.append("magazzini")
	var stalls: Dictionary = city["stalls_in_seconds"]
	for resource in city["stock_milli"]:
		lines.append("  %-8s %10s   %s" % [
			resource, Fmt.units(city["stock_milli"][resource]),
			Fmt.stall_note(stalls.get(resource))])

	# La corrente e' un FLUSSO, due numeri al secondo, non una scorta. Mostrarla come un
	# magazzino farebbe chiedere "quanta ne ho da parte", e non se ne ha mai.
	lines.append("")
	lines.append("corrente  %d prodotti · %d usati%s" % [
		int(city["power_made"]), int(city["power_used"]),
		"" if int(city["work_permille"]) >= 1000
		else "  ·  impianti al %d%%" % (int(city["work_permille"]) / 10)])
	var powers: Array[String] = []
	for kind in city["site_power"]:
		powers.append("%s %d" % [kind, int(city["site_power"][kind])])
	lines.append("il sito offre  " + " · ".join(powers))

	lines.append("")
	lines.append("impianti")
	var catalogue: Dictionary = city["catalogue"]
	var works: Dictionary = city["works"]
	var idle: Dictionary = city["works_idle"]
	if works.is_empty():
		lines.append("  nessuno")
	for kind in works:
		var label: String = catalogue[kind]["label"] if catalogue.has(kind) else kind
		var spare := int(idle.get(kind, 0))
		lines.append("  %d × %s%s" % [int(works[kind]), label,
									  "" if spare == 0 else "  (%d fermi)" % spare])

	lines.append("")
	var missing := Fmt.missing_for(city["next_upgrade_cost_milli"], city["stock_milli"])
	if missing.is_empty():
		lines.append("livello %d: si puo' cominciare, ci vogliono %s" % [
			int(city["level"]) + 1, Fmt.how_long(float(city["next_upgrade_seconds"]))])
	else:
		# Solo cio' che MANCA: un messaggio che elenca anche cio' che c'e' costringe chi
		# legge a fare la sottrazione a mente.
		var short: Array[String] = []
		for resource in missing:
			short.append("%s %s" % [resource, Fmt.units(missing[resource])])
		lines.append("livello %d: mancano %s" % [int(city["level"]) + 1, ", ".join(short)])

	if city.get("busy_with") != null:
		lines.append("occupata: %s" % str(city["busy_with"]))
	return "\n".join(lines)
