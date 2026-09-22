# Parlare col server che comanda.
#
# Il pianeta e' un file e il terreno della colonia e' una funzione di quel file: nessuno dei
# due ha bisogno di qualcosa di sveglio. Una CITTA' si': le sue scorte, il suo livello e cio'
# a cui e' occupata li decide il server e qui non si possono calcolare senza inventarli. Per
# questo l'unica parte del client che dipende da un'istanza accesa e' questa, apposta e solo
# qui.
#
# Il che vuol dire che deve sopravvivere alla partenza a freddo di un'istanza gratuita:
# `patience.gd` conta l'attesa con l'orologio e non con i tentativi, e il perche' sta scritto
# li'.
#
# Gemello di `frontend/app/lib/api.ts`, e le decisioni che contano -- che cosa significa uno
# stato HTTP, che aspetto ha un indirizzo pulito -- sono statiche apposta: si provano senza
# rete, e una decisione che per essere verificata chiede un server acceso non si verifica.
class_name ExiliumApi
extends Node

const Patience := preload("res://exilium/patience.gd")

## Che cosa si e' deciso di una risposta. Non eccezioni -- GDScript non ne ha -- ma un verdetto
## esplicito, che e' anche cio' che rende provabile la decisione senza fare la chiamata.
## Due elenchi senza nome nello stesso file avrebbero entrambi uno zero, e lo zero di uno
## sarebbe indistinguibile da quello dell'altro. Hanno un nome apposta.
enum Verdict { KEEP_KNOCKING, ANSWERED, REFUSED, UNAUTHORISED }

## Perche' non si e' ottenuto niente. Serve allo schermo: "il server dorme" e "il tuo token e'
## sbagliato" chiedono due cose diverse a chi guarda, e un solo "errore" non ne chiede nessuna.
enum Why { NONE, NO_SERVER, NO_TOKEN, BAD_TOKEN, REFUSAL, ASLEEP }

const SETTINGS_PATH := "user://exilium.cfg"

## Novanta secondi: un'istanza gratuita di Render ne chiede una cinquantina per svegliarsi, e
## il margine e' per la volta in cui ne chiede di piu'.
const BUDGET_MS := 90_000
const GAP_MS := 1500
const MAX_GAP_MS := 8000


## Il risultato di una chiamata. `value` e' cio' che ha risposto il server, o `null`; `why`
## dice perche' no, e `detail` e' la ragione DEL SERVER quando ce n'e' una -- riportata e non
## reinventata, perche' il server sa cose che il client non sa.
class Reply extends RefCounted:
	var value: Variant = null
	var why := Why.NONE
	var detail := ""
	var waited_ms := 0

	func ok() -> bool:
		return why == Why.NONE


## Dove sta il server e con che token. Si legge da un file di impostazioni, e si puo'
## scavalcare dall'ambiente: la stessa copia scaricata deve poter parlare con un server sulla
## propria macchina senza essere ricompilata -- che e' la differenza fra provare una modifica
## in dieci secondi e in tre minuti.
var base := ""
var token := ""

var _pending: HTTPRequest


func _ready() -> void:
	load_settings()


## L'indirizzo senza barra finale, cosi' non si raddoppia nei percorsi. La stessa pulizia che
## fa chi legge un indirizzo a occhio, e che va fatta qui perche' nessuno la fa altrove.
static func clean_base(raw: String) -> String:
	var text := raw.strip_edges()
	while text.ends_with("/"):
		text = text.substr(0, text.length() - 1)
	return text


func load_settings() -> void:
	var file := ConfigFile.new()
	if file.load(SETTINGS_PATH) == OK:
		base = clean_base(str(file.get_value("server", "base", "")))
		token = str(file.get_value("server", "token", "")).strip_edges()
	# L'ambiente vince sul file: e' il modo di puntare una copia gia' installata a un server
	# diverso per una sessione sola, senza toccare cio' che e' stato salvato.
	if OS.has_environment("EXILIUM_API"):
		base = clean_base(OS.get_environment("EXILIUM_API"))
	if OS.has_environment("EXILIUM_TOKEN"):
		token = OS.get_environment("EXILIUM_TOKEN").strip_edges()


func save_settings() -> void:
	var file := ConfigFile.new()
	file.set_value("server", "base", base)
	file.set_value("server", "token", token)
	file.save(SETTINGS_PATH)


## Che cosa significa questo stato HTTP.
##
## 429 e 5xx sono cio' che dice un'istanza che si sta svegliando o che e' sovraccarica:
## esattamente i casi in cui insistere e' la risposta giusta. Un 401 NO: un token sbagliato
## resta sbagliato per quanto a lungo si bussi, e bussarci novanta secondi non dice al
## giocatore nient'altro che "il gioco e' rotto".
static func verdict(status: int) -> int:
	if status == 401 or status == 403:
		return Verdict.UNAUTHORISED
	if status == 429 or status >= 500:
		return Verdict.KEEP_KNOCKING
	if status >= 200 and status < 300:
		return Verdict.ANSWERED
	return Verdict.REFUSED


## Una chiave di idempotenza: un UUID versione 4, come lo vuole il server. Da byte casuali
## veri e non dal generatore del gioco -- quello e' seminato apposta per dare sempre la stessa
## sequenza, e una chiave di idempotenza che si ripete e' un ordine che non viene eseguito.
static func random_uuid() -> String:
	var bytes := Crypto.new().generate_random_bytes(16)
	bytes[6] = (bytes[6] & 0x0F) | 0x40          # versione 4
	bytes[8] = (bytes[8] & 0x3F) | 0x80          # variante RFC 4122
	var hex := bytes.hex_encode()
	return "%s-%s-%s-%s-%s" % [hex.substr(0, 8), hex.substr(8, 4), hex.substr(12, 4),
							   hex.substr(16, 4), hex.substr(20, 12)]


## Una chiamata autenticata, che aspetta una partenza a freddo invece di fallirci dentro.
func call_api(path: String, method := HTTPClient.METHOD_GET, body: Variant = null) -> Reply:
	var reply := Reply.new()
	# `HTTPRequest` e' un nodo, e un nodo fuori dall'albero non manda niente: `request()`
	# restituisce ERR_UNCONFIGURED. Senza questo controllo quel caso finiva fra i "riprova",
	# e un errore di programmazione si travestiva da server che dorme -- novanta secondi di
	# attesa e poi una frase sbagliata. E' successo mentre si scrivevano queste prove.
	if not is_inside_tree():
		reply.why = Why.NO_SERVER
		reply.detail = "Il client non e' nell'albero della scena: non puo' chiamare nessuno."
		push_error(reply.detail)
		return reply
	if base == "":
		reply.why = Why.NO_SERVER
		reply.detail = "Nessun server configurato."
		return reply
	if token == "":
		reply.why = Why.NO_TOKEN
		reply.detail = "Serve un token per parlare con il server."
		return reply

	var headers := PackedStringArray(["Authorization: Bearer " + token])
	if body != null:
		headers.append("Content-Type: application/json")
	if method == HTTPClient.METHOD_POST:
		headers.append("Idempotency-Key: " + random_uuid())
	var payload := "" if body == null else JSON.stringify(body)

	var budget := Patience.Budget.new(BUDGET_MS, GAP_MS, MAX_GAP_MS)
	# La bussata restituisce `null` per "non ancora" e un array per "ecco la risposta": e'
	# `patience.gd` a decidere quando smettere, e questa funzione non ripete quel conto.
	var knocked: Patience.Knocked = await Patience.keep_knocking(
		budget, func(_attempt): return await _knock(path, method, headers, payload))
	reply.waited_ms = knocked.elapsed_ms

	if knocked.value == null:
		reply.why = Why.ASLEEP
		reply.detail = "Il server non ha risposto in %d secondi." % roundi(knocked.elapsed_ms / 1000.0)
		return reply

	var answer: Array = knocked.value
	var outcome: int = answer[0]
	if outcome == Verdict.UNAUTHORISED:
		reply.why = Why.BAD_TOKEN
		reply.detail = "Il server non riconosce questo token."
	elif outcome == Verdict.REFUSED:
		reply.why = Why.REFUSAL
		reply.detail = answer[1] if answer[1] != "" else "Il server ha rifiutato."
	else:
		reply.value = answer[1]
	return reply


## Una singola bussata. `null` significa "riprova": rete assente, istanza che dorme, o
## sovraccarico. Tutto il resto e' una decisione, e la decisione la prende `verdict`.
func _knock(path: String, method: int, headers: PackedStringArray, payload: String) -> Variant:
	if _pending != null:
		_pending.queue_free()
	_pending = HTTPRequest.new()
	add_child(_pending)
	var sent := _pending.request(base + path, headers, method, payload)
	if sent != OK:
		_pending.queue_free()
		_pending = null
		return null
	var result: Array = await _pending.request_completed
	_pending.queue_free()
	_pending = null

	# `result` e' [risultato, stato, intestazioni, corpo]. Un risultato diverso da OK e' una
	# rete che non c'e' -- e una rete che non c'e' e' proprio il caso in cui insistere serve.
	if result[0] != HTTPRequest.RESULT_SUCCESS:
		return null
	var status: int = result[1]
	var text := (result[3] as PackedByteArray).get_string_from_utf8()
	var outcome := verdict(status)
	if outcome == Verdict.KEEP_KNOCKING:
		return null
	if outcome == Verdict.ANSWERED:
		return [Verdict.ANSWERED, JSON.parse_string(text)]
	# La ragione del server, se l'ha data. Inventarne una al posto suo vuol dire nascondere
	# l'unica frase che sa perche' la richiesta non andava bene.
	var detail := ""
	var parsed: Variant = JSON.parse_string(text)
	if parsed is Dictionary and parsed.has("detail"):
		detail = str(parsed["detail"])
	return [outcome, detail]


func my_cities() -> Reply:
	return await call_api("/me/cities")


func read_city(id: String) -> Reply:
	return await call_api("/cities/%s" % id)


func read_world() -> Reply:
	return await call_api("/world")


func build_work(id: String, kind: String) -> Reply:
	return await call_api("/cities/%s/works" % id, HTTPClient.METHOD_POST, {"kind": kind})


func set_running(id: String, kind: String, running: int) -> Reply:
	return await call_api("/cities/%s/works/%s" % [id, kind], HTTPClient.METHOD_PUT,
						  {"running": running})


func demolish(id: String, kind: String) -> Reply:
	return await call_api("/cities/%s/works/%s" % [id, kind], HTTPClient.METHOD_DELETE)


func upgrade(id: String) -> Reply:
	return await call_api("/cities/%s/upgrade" % id, HTTPClient.METHOD_POST)


func vote(id: String, choice: String) -> Reply:
	return await call_api("/cities/%s/vote" % id, HTTPClient.METHOD_PUT, {"choice": choice})
