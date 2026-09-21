# Il terzo gemello di `backend/app/prng.py` e `frontend/app/colony/prng.ts`.
#
# Mulberry32, scritto per intero: una parola di stato e aritmetica intera a 32 bit, e niente
# altro. La ragione per cui esiste in tre lingue invece di essere il generatore di una di
# esse e' la stessa di sempre -- il terreno della colonia viene calcolato dal server, dal
# browser e adesso da qui, e le tre copie devono dare gli STESSI numeri. Reimplementare il
# Mersenne Twister di CPython sarebbe stato prendere il problema dalla parte sbagliata.
#
# UNA DIFFERENZA VERA rispetto alle altre due copie, ed e' l'unica: qui la moltiplicazione a
# 32 bit e' spezzata a mano in due meta' da 16 bit. Python ha interi di precisione arbitraria
# e JavaScript ha `Math.imul`; GDScript ha interi con segno a 64 bit, e il prodotto di due
# numeri da 32 bit arriva a 1,8e19 -- oltre il massimo rappresentabile. In pratica andrebbe
# comunque in overflow con complemento a due e i 32 bit bassi resterebbero giusti, ma
# "in pratica" non e' il modo di decidere da che pianeta esce un mondo condiviso.
class_name ExiliumPrng
extends RefCounted

const MASK := 0xFFFFFFFF

## FNV-1a a 32 bit. Scritto per esteso come il resto del file.
static func seed_int(text: String) -> int:
	var h := 2166136261
	for byte in text.to_utf8_buffer():
		h = mul32(h ^ byte, 16777619)
	return h

## Il prodotto di due numeri a 32 bit, troncato a 32 bit, senza mai passare per un valore
## che un intero con segno a 64 bit non sappia rappresentare.
static func mul32(a: int, b: int) -> int:
	var lo := a & 0xFFFF
	var hi := (a >> 16) & 0xFFFF
	return (lo * b + (((hi * b) & 0xFFFF) << 16)) & MASK

var state: int

func _init(seed_value) -> void:
	if seed_value is String:
		state = seed_int(seed_value)
	else:
		state = int(seed_value) & MASK

func next_uint() -> int:
	state = (state + 0x6D2B79F5) & MASK
	var t := state
	t = mul32(t ^ (t >> 15), t | 1)
	t = (t ^ ((t + mul32(t ^ (t >> 7), t | 61)) & MASK)) & MASK
	return (t ^ (t >> 14)) & MASK

func random() -> float:
	return float(next_uint()) / 4294967296.0

func uniform(low: float, high: float) -> float:
	return low + (high - low) * random()

## Un punto preso a caso sulla sfera unitaria. Niente logaritmo: ogni chiamata
## trascendentale e' un posto in piu' dove due librerie matematiche possono discordare
## sull'ultimo bit, e adesso le librerie sono tre.
func direction() -> Array:
	var z := 2.0 * random() - 1.0
	var phi := 2.0 * PI * random()
	var r := sqrt(max(0.0, 1.0 - z * z))
	return [r * cos(phi), r * sin(phi), z]
