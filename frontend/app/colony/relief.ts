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
import { neighbours } from "./hexgrid";

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
 *  in avanti e una all'indietro, che e' tutto cio' che serve quando la distanza e' corta.
 *
 *  I vicini sono quelli dell'ESAGONO, non del quadrato. Con i quattro vicini di una
 *  scacchiera la distanza sarebbe storta di mezza cella su una riga sì e una no, e la
 *  schiuma lungo una riva obliqua uscirebbe a denti di sega. Su una griglia sfalsata i sei
 *  vicini non sono gli stessi per le righe pari e per le dispari: e' esattamente lo scarto
 *  che `hexgrid.neighbours` tiene in un posto solo. */
const REACH = 8;

function shoreDistance(wet: Uint8Array, size: number): Uint8Array {
  const far = REACH + 1;
  const distance = new Float32Array(size * size).fill(far);
  const at = (col: number, row: number) =>
    (col < 0 || row < 0 || col >= size || row >= size) ? -1 : row * size + col;

  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      const i = row * size + col;
      const here = wet[i];
      for (const [nc, nr] of neighbours(col, row)) {
        const j = at(nc, nr);
        if (j >= 0 && wet[j] !== here) { distance[i] = 0; break; }
      }
    }
  }
  // In avanti: i tre vicini gia' visitati in ordine di scansione.
  for (let row = 0; row < size; row++) {
    const lean = (row & 1) ? 0 : -1;
    for (let col = 0; col < size; col++) {
      const i = row * size + col;
      for (const [nc, nr] of [[col - 1, row], [col + lean, row - 1], [col + lean + 1, row - 1]]) {
        const j = at(nc, nr);
        if (j >= 0 && distance[j] + 1 < distance[i]) distance[i] = distance[j] + 1;
      }
    }
  }
  const shore = new Uint8Array(size * size);
  for (let row = size - 1; row >= 0; row--) {
    const lean = (row & 1) ? 0 : -1;
    for (let col = size - 1; col >= 0; col--) {
      const i = row * size + col;
      for (const [nc, nr] of [[col + 1, row], [col + lean, row + 1], [col + lean + 1, row + 1]]) {
        const j = at(nc, nr);
        if (j >= 0 && distance[j] + 1 < distance[i]) distance[i] = distance[j] + 1;
      }
      shore[i] = Math.min(255, Math.round(distance[i] * 32));
    }
  }
  return shore;
}
