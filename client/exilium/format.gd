# Mettere in parole i numeri del server.
#
# Gemello di `frontend/app/city/format.ts`, e tenuto separato dal disegno per la stessa
# ragione: queste sono DECISIONI, non grafica. Quando una colonia si ferma e quanto le manca
# per il livello dopo sono le due domande a cui la schermata esiste per rispondere, e sono
# aritmetica -- che sbagliata dentro un pannello non si vede, perche' si legge come un numero
# plausibile.
#
# I casi di prova stanno in `frontend/app/city/format.cases.json`, uno solo per tutti e due:
# senza, questo file e quello sarebbero due elenchi di regole che si giurano uguali. In questo
# progetto due copie della stessa regola hanno gia' mentito cinque volte.
class_name Format
extends RefCounted


## Milli-unita' -> unita', come le legge una persona.
##
## L'italiano NON raggruppa le quattro cifre: duemila si scrive 2000, non 2.000. E' il genere
## di cosa che qualcuno "corregge" credendo sia un difetto, quindi e' scritto qui e provato.
static func units(milli: Variant) -> String:
	var value := float(str(milli).to_float())
	var whole := int(floor(value / 1000.0))
	var negative := whole < 0
	var digits := str(absi(whole))
	if digits.length() >= 5:
		var grouped := ""
		var count := 0
		for i in range(digits.length() - 1, -1, -1):
			grouped = digits[i] + grouped
			count += 1
			if count % 3 == 0 and i > 0:
				grouped = "." + grouped
		digits = grouped
	return ("-" if negative else "") + digits


## Una durata in parole brevi. Sopra il giorno le ore non interessano piu' a nessuno.
static func how_long(seconds: float) -> String:
	if seconds < 60.0:
		return "%d s" % maxi(1, roundi(seconds))
	var minutes := roundi(seconds / 60.0)
	if minutes < 60:
		return "%d min" % minutes
	var hours := seconds / 3600.0
	if hours < 48.0:
		return ("%.1f h" % hours) if hours < 10.0 else ("%d h" % roundi(hours))
	return "%d giorni" % roundi(hours / 24.0)


## Quando questo magazzino smettera' di guadagnare, detto a chi guarda.
##
## E' la meta' che rende accettabile lo stallo in un mondo che cammina mentre dormi: fermarsi
## e' la tensione voluta, fermarsi a sorpresa e' una punizione per chi ha un lavoro.
static func stall_note(seconds: Variant) -> String:
	if seconds == null:
		return "fermo"
	if float(seconds) <= 0.0:
		return "pieno"
	return "pieno fra " + how_long(float(seconds))


## Lo stesso, per la pastiglia stretta. Tre stati e non due: "pieno" a zero, "fermo" quando
## non si sa, il tempo altrimenti. Confonderne due e' dire a chi gioca di spendere una
## risorsa che li' non arrivera' mai.
static func stall_short(seconds: Variant) -> String:
	if seconds == null:
		return "fermo"
	if float(seconds) <= 0.0:
		return "pieno"
	return "fra " + how_long(float(seconds))


## Cosa manca per cominciare il livello dopo, o un dizionario vuoto se si puo' gia'. Solo cio'
## che manca DAVVERO: un messaggio che elenca anche cio' che c'e' costringe chi legge a fare
## la sottrazione a mente.
static func missing_for(cost: Dictionary, held: Dictionary) -> Dictionary:
	var short := {}
	for resource in cost:
		var gap := str(cost[resource]).to_float() - str(held.get(resource, "0")).to_float()
		if gap > 0.0:
			short[resource] = gap
	return short
