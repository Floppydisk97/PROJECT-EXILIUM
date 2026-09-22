# Aspettare che un'istanza gratuita si svegli, contato come il tempo passa davvero.
#
# Gemella di `frontend/app/lib/patience.ts`, e porta con se' la lezione che ha imparato quella:
# la prima versione contava i TENTATIVI e misurava la pazienza con un timeout per tentativo.
# Quel ragionamento regge solo se un tentativo fallito e' lento. Non lo e': l'instradatore di
# Render risponde subito con un 5xx a una richiesta per un servizio che dorme, quindi ogni
# tentativo costava due secondi invece dei venticinque concessi, e quattro tentativi si
# spendevano in diciotto secondi. Il commento prometteva un minuto e mezzo di pazienza; il
# codice ne dava diciotto secondi, contro un risveglio che ne chiede cinquanta.
#
# Quindi il budget qui e' l'OROLOGIO e nient'altro. Per quanto in fretta l'altro capo dica di
# no, si continua a bussare finche' il tempo che si e' detto di aspettare non e' passato.
#
# `now` e `sleep` si possono sostituire, ed e' per questo che questo file si prova senza rete
# e senza aspettare: una pazienza che per essere verificata chiede novanta secondi veri, in
# pratica non si verifica.
class_name Patience
extends RefCounted


## Quanto aspettare in tutto, quanto fermarsi dopo il primo rifiuto, e fin dove puo'
## raddoppiare quella pausa -- cosi' un'attesa lunga non e' anche un martellamento.
class Budget extends RefCounted:
	var total_ms: int
	var gap_ms: int
	var max_gap_ms: int

	func _init(total: int, gap: int, max_gap: int) -> void:
		total_ms = total
		gap_ms = gap
		max_gap_ms = max_gap


## Il risultato di una bussata: `value` e' `null` se il tempo e' finito senza risposta, e
## `elapsed_ms` dice quanto si e' aspettato -- che e' la sola cosa onesta da mostrare a chi
## guarda uno schermo fermo.
class Knocked extends RefCounted:
	var value: Variant = null
	var attempts := 0
	var elapsed_ms := 0


## Chiama `probe` finche' non risponde o finche' il tempo non finisce. Bussa sempre almeno
## una volta. `probe` riceve il numero del tentativo e restituisce `null` per "non ancora",
## o qualunque altra cosa per "ecco la risposta".
##
## `now` restituisce millisecondi; `sleep` riceve millisecondi. Sostituibili entrambi, e
## quando non si sostituiscono sono l'orologio di sistema e un'attesa vera.
static func keep_knocking(budget: Budget, probe: Callable,
						  now := Callable(), sleep_for := Callable()) -> Knocked:
	if not now.is_valid():
		now = Time.get_ticks_msec
	var started: int = now.call()
	var gap := budget.gap_ms
	var knocked := Knocked.new()

	while true:
		knocked.attempts += 1
		# `await` e non una chiamata secca: `probe` di solito FA qualcosa che richiede
		# tempo -- una richiesta HTTP -- e senza questo si riceverebbe la coroutine invece
		# della risposta, cioe' un valore diverso da `null` che sembra un successo.
		# Su una sonda che risponde subito `await` restituisce il valore e basta, ed e'
		# quello che rende provabile questo file senza rete.
		var answer: Variant = await probe.call(knocked.attempts)
		if answer != null:
			knocked.value = answer
			knocked.elapsed_ms = now.call() - started
			return knocked

		# Mai dormire oltre la scadenza: il budget e' una promessa su QUANDO si smette, non
		# un pavimento che un'ultima pausa lunga possa sfondare.
		var remaining: int = budget.total_ms - (now.call() - started)
		if remaining <= 0:
			knocked.elapsed_ms = now.call() - started
			return knocked
		var pause: int = mini(gap, remaining)
		if sleep_for.is_valid():
			sleep_for.call(pause)
		else:
			await Engine.get_main_loop().create_timer(pause / 1000.0).timeout
		gap = mini(gap * 2, budget.max_gap_ms)

	return knocked
