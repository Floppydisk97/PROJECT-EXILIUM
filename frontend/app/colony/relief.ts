// Cosa l'acqua fa alla riva.
//
// Qui c'era anche la LUCE: una sfumatura calcolata dalla pendenza di ogni cella, che accendeva
// i fianchi rivolti a nordovest e spegneva gli altri. E' stata tolta, non spenta con una
// costante a zero -- il codice morto e' peggio del difetto che nascondeva.
//
// Il motivo e' che il rilievo di una colonia viene da un rumore a poche armoniche, quindi le
// sue pendenze sono larghe e regolari: ombreggiarle non produceva colline, produceva fasce
// diagonali chiare e scure lunghe tutta la mappa, sempre nella stessa direzione. Una pianura
// sembrava stoffa a righe. Il rilievo vero si legge dall'acqua che si raccoglie nelle conche e
// dalla roccia che affiora sulle creste, e quelle due cose il generatore le scrive gia'.
//
// Tutto e' funzione pura delle celle: la stessa colonia deve disegnarsi allo stesso modo su
// ogni macchina, per sempre. Niente di casuale entra da qui.

import { WATER, type ColonyGround } from "./ground";

export type Relief = {
  /** Quanto e' fonda l'acqua, 0 sulla terra e 255 dove non si vede il fondo. */
  depth: Uint8Array;
  /** Quanto dista il confine fra acqua e terra, in trentaduesimi di cella (255 = otto celle
   *  o piu'). Una DISTANZA e non una comodita' gia' invertita: la schiuma la vuole corta e
   *  l'orlo bagnato cortissima, e due misure diverse dalla stessa passata sono possibili
   *  solo se quello che si conserva e' il numero grezzo. */
  shore: Uint8Array;
};

/** Quanto dista la riva, in celle. */
export function shoreCells(relief: Relief, index: number): number {
  return relief.shore[index] / 32;
}

const CACHE = new WeakMap<ColonyGround, Relief>();

/** Il rilievo di una colonia. Calcolato una volta sola: lo vogliono sia la tela grande sia la
 *  minimappa, e sono 590.000 celle. */
export function reliefOf(ground: ColonyGround): Relief {
  const found = CACHE.get(ground);
  if (found) return found;
  const made = computeRelief(ground);
  CACHE.set(ground, made);
  return made;
}

export function computeRelief(ground: ColonyGround): Relief {
  const size = ground.size;
  const total = size * size;
  const height = ground.cells.height;

  const wet = new Uint8Array(total);
  for (let i = 0; i < total; i++) {
    wet[i] = WATER.has(ground.ground_names[ground.cells.ground[i]]) ? 1 : 0;
  }

  // L'acqua: quanto e' fonda, con una curva senza scala. Un rapporto sul fondo piu' basso
  // avrebbe reso ogni colonia diversa da se stessa -- una pozza sarebbe stata nera quanto un
  // oceano solo perche' era la cosa piu' fonda che c'era.
  const depth = new Uint8Array(total);
  for (let i = 0; i < total; i++) {
    if (!wet[i]) continue;
    const below = Math.max(0, -height[i]);
    depth[i] = Math.round(255 * (1 - Math.exp(-below / 95)));
  }

  return { depth, shore: shoreDistance(wet, size) };
}

/** Quanto dista il confine acqua/terra, in celle, fino a REACH. Due passate di chamfer: una
 *  in avanti e una all'indietro, che e' tutto cio' che serve quando la distanza e' corta. */
const REACH = 8;

function shoreDistance(wet: Uint8Array, size: number): Uint8Array {
  const far = REACH + 1;
  const distance = new Float32Array(size * size).fill(far);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = y * size + x;
      const here = wet[i];
      const edge =
        (x > 0 && wet[i - 1] !== here) || (x < size - 1 && wet[i + 1] !== here) ||
        (y > 0 && wet[i - size] !== here) || (y < size - 1 && wet[i + size] !== here);
      if (edge) distance[i] = 0;
    }
  }
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = y * size + x;
      if (x > 0) distance[i] = Math.min(distance[i], distance[i - 1] + 1);
      if (y > 0) distance[i] = Math.min(distance[i], distance[i - size] + 1);
    }
  }
  const shore = new Uint8Array(size * size);
  for (let y = size - 1; y >= 0; y--) {
    for (let x = size - 1; x >= 0; x--) {
      const i = y * size + x;
      if (x < size - 1) distance[i] = Math.min(distance[i], distance[i + 1] + 1);
      if (y < size - 1) distance[i] = Math.min(distance[i], distance[i + size] + 1);
      shore[i] = Math.min(255, Math.round(distance[i] * 32));
    }
  }
  return shore;
}
