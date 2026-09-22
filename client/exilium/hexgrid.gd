# La geometria della maglia esagonale: dove sta un esagono, chi gli sta accanto, e che forma
# ha il suo contorno. Una definizione sola per tutte e tre le cose, perche' sono la stessa
# cosa detta tre volte e se si allontanano il terreno finisce fuori dalle linee.
#
# Gemella di `frontend/app/colony/hexgrid.ts`. Non viaggia nel riferimento come fanno i
# generatori -- non ha celle da confrontare -- quindi cio' che la tiene onesta sta in
# `tests/run.gd`: ogni centro ritrova il proprio esagono, e il vicinato e' reciproco. Sono
# le stesse due affermazioni che prova `hexgrid.test.ts`, e sono quelle che si rompono per
# prime quando lo sfalsamento delle righe dispari viene scritto storto.
#
# PUNTA IN ALTO, righe dispari spinte di mezzo esagono a destra ("odd-r"). Le righe non
# distano 1 ma sqrt(3)/2: e' il rapporto fra l'altezza e la larghezza di un esagono con la
# punta in su, ed e' calcolato, mai trascritto.
class_name HexGridMath
extends RefCounted

# Calcolate, mai trascritte: una radice scritta a mano e' una radice che un giorno si copia
# con una cifra in meno. GDScript non ammette `sqrt` in una costante, quindi sono funzioni.
static func sqrt3() -> float:
	return sqrt(3.0)


static func row_ratio() -> float:
	return sqrt(3.0) / 2.0


## Quanto e' alta una mappa larga `size` esagoni. Non `size`: un rettangolo largo.
static func map_height(size: int) -> float:
	return size * row_ratio()


## Il centro dell'esagono (col, row), in unita'. Mezzo esagono di scostamento sulle righe
## dispari, e mezza unita' di margine perche' la mappa cominci a zero invece che a -0,5.
static func centre_x(col: int, row: int) -> float:
	return col + 0.5 * (row & 1) + 0.5


static func centre_y(row: int) -> float:
	return (row + 0.5) * row_ratio()


## Quale esagono sta sotto il punto (ux, uy), in unita'. Fuori mappa restituisce (-1, -1).
##
## Non e' un arrotondamento a griglia: gli esagoni non si incastrano a scacchiera, e troncare
## darebbe la cella sbagliata lungo tutti i bordi diagonali -- il terreno sembrerebbe sfalsato
## rispetto alle linee esattamente dove si guarda. Si passa in coordinate cubiche, dove
## l'esagono giusto e' quello con la somma zero piu' vicina.
static func hex_at(ux: float, uy: float, size: int) -> Vector2i:
	var px := ux - 0.5
	var py := uy - 0.5 * row_ratio()
	var xf := px - py / sqrt3()
	var zf := 2.0 * py / sqrt3()
	var yf := -xf - zf
	var x := int(round(xf))
	var y := int(round(yf))
	var z := int(round(zf))
	var dx := absf(x - xf)
	var dy := absf(y - yf)
	var dz := absf(z - zf)
	# Si ripara la coordinata su cui l'arrotondamento ha mentito di piu': x + y + z = 0 e'
	# l'invariante, e una sola delle tre puo' essere sbagliata.
	if dx > dy and dx > dz:
		x = -y - z
	elif dy > dz:
		y = -x - z
	else:
		z = -x - y

	var row := z
	var col := x + (z - (z & 1)) / 2
	if col < 0 or row < 0 or col >= size or row >= size:
		return Vector2i(-1, -1)
	return Vector2i(col, row)


## Il contorno di un esagono, in unita', attorno al suo centro. Sei vertici a partire dalla
## punta in alto. Serve alla griglia che si accende sopra il terreno.
static func corners() -> PackedVector2Array:
	var radius := 1.0 / sqrt3()          # dal centro alla punta, in larghezze
	var points := PackedVector2Array()
	for i in range(6):
		var angle := deg_to_rad(60.0 * i - 90.0)
		points.append(Vector2(radius * cos(angle), radius * sin(angle)))
	return points


## I sei vicini di (col, row). Su una griglia sfalsata non sono gli stessi per le righe pari e
## per le dispari, ed e' l'errore che si fa sempre.
static func neighbours(col: int, row: int) -> Array[Vector2i]:
	var lean := 0 if (row & 1) else -1
	return [
		Vector2i(col - 1, row), Vector2i(col + 1, row),
		Vector2i(col + lean, row - 1), Vector2i(col + lean + 1, row - 1),
		Vector2i(col + lean, row + 1), Vector2i(col + lean + 1, row + 1),
	]
