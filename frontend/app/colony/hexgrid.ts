// La geometria della griglia: dove sta un esagono, e quale esagono sta sotto un punto.
//
// Una sola definizione, perche' a questa domanda rispondono in tre -- il pittore del terreno,
// il puntatore che dice cosa c'e' sotto il mouse, e la griglia che si accende sopra. Tre
// risposte che devono essere d'accordo sono, in questo progetto, il modo noto di sbagliare:
// basta mezzo esagono di scarto fra il colore e il bordo perche' il terreno sembri scollato
// dalle linee, e nessun test lo vedrebbe.
//
// UNITA'. Tutto qui dentro e' in LARGHEZZE DI ESAGONO -- un'unita' e' 1,075 m, cioe' un
// esagono da piatto a piatto. Non in metri: la telecamera, il buffer del terreno e le
// coordinate delle celle diventano cosi' la stessa scala, e convertire in metri e' una
// moltiplicazione che riguarda solo chi deve SCRIVERE una distanza.
//
// DISPOSIZIONE. Punta in alto, righe sfalsate ("odd-r"): le righe dispari stanno mezzo
// esagono a destra. E' la disposizione dell'immagine di riferimento, ed e' anche quella che
// lascia le celle in un vettore rettangolare -- colonna e riga -- invece che in una mappa.

import { ROW_RATIO } from "./citygen";

export { ROW_RATIO };

/** Quanto e' alta una mappa di `size` righe, in larghezze di esagono. La mappa NON e'
 *  quadrata: righe distanti 0,866 fanno un rettangolo largo, e chi inquadra deve saperlo. */
export function mapHeight(size: number): number {
  return size * ROW_RATIO;
}

/** Il centro dell'esagono (col, row), in unita'. Mezzo esagono di scostamento sulle righe
 *  dispari, e mezza unita' di margine perche' la mappa cominci a zero invece che a -0,5. */
export function centreX(col: number, row: number): number {
  return col + 0.5 * (row & 1) + 0.5;
}

export function centreY(row: number): number {
  return (row + 0.5) * ROW_RATIO;
}

const SQRT3 = Math.sqrt(3);

/** Quale esagono sta sotto il punto (ux, uy), in unita'. Fuori mappa restituisce null.
 *
 *  Non e' un arrotondamento a griglia: gli esagoni non si incastrano a scacchiera, e
 *  troncare darebbe la cella sbagliata lungo tutti i bordi diagonali -- il terreno
 *  sembrerebbe sfalsato rispetto alle linee esattamente dove si guarda. Si passa in
 *  coordinate cubiche, dove l'esagono giusto e' quello con la somma zero piu' vicina.
 */
export function hexAt(ux: number, uy: number, size: number): [number, number] | null {
  const px = ux - 0.5;
  const py = uy - 0.5 * ROW_RATIO;
  const qf = px - py / SQRT3;
  const rf = (2 * py) / SQRT3;

  // Arrotondamento cubico: x + y + z = 0 e' l'invariante, e si ripara la coordinata che si e'
  // spostata di piu' -- quella su cui l'arrotondamento ha mentito di piu'.
  const xf = qf;
  const zf = rf;
  const yf = -xf - zf;
  let x = Math.round(xf);
  let y = Math.round(yf);
  let z = Math.round(zf);
  const dx = Math.abs(x - xf);
  const dy = Math.abs(y - yf);
  const dz = Math.abs(z - zf);
  if (dx > dy && dx > dz) x = -y - z;
  else if (dy > dz) y = -x - z;
  else z = -x - y;

  const row = z;
  const col = x + (z - (z & 1)) / 2;
  if (col < 0 || row < 0 || col >= size || row >= size) return null;
  return [col, row];
}

/** Il contorno di un esagono, in unita', attorno al suo centro. Sei vertici a partire dalla
 *  punta in alto. Serve alla griglia che si accende sopra il terreno. */
export const CORNERS: [number, number][] = (() => {
  const radius = 1 / SQRT3;                  // dal centro alla punta, in larghezze
  const points: [number, number][] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 180) * (60 * i - 90);
    points.push([radius * Math.cos(angle), radius * Math.sin(angle)]);
  }
  return points;
})();

/** I sei vicini di (col, row). Su una griglia sfalsata non sono gli stessi per le righe pari
 *  e per le dispari, ed e' l'errore che si fa sempre: con i vicini del quadrato la distanza
 *  dalla riva verrebbe storta di mezza cella su una riga sì e una no. */
export function neighbours(col: number, row: number): [number, number][] {
  const lean = (row & 1) ? 0 : -1;
  return [
    [col - 1, row], [col + 1, row],
    [col + lean, row - 1], [col + lean + 1, row - 1],
    [col + lean, row + 1], [col + lean + 1, row + 1],
  ];
}
