// La luce, e cio' che l'acqua fa alla riva.
//
// Il terreno era dipinto piatto: un colore per cella e basta. Il generatore pero' scrive gia'
// l'ALTEZZA di ogni cella in metri, e nessuno la guardava -- una collina e una pianura
// uscivano dello stesso identico colore. Qui quella colonna diventa quello che dovrebbe
// essere: una superficie che prende luce da una parte e resta in ombra dall'altra.
//
// Tutto e' funzione pura delle celle: la stessa colonia deve accendersi allo stesso modo su
// ogni macchina, per sempre. Niente di casuale entra da qui.

import { WATER, type ColonyGround } from "./ground";

/** Da dove viene il sole. In alto a sinistra, come l'ombra sotto gli alberi dice gia': se le
 *  due cose non fossero d'accordo, il terreno e le cose che ci stanno sopra sembrerebbero
 *  ritagliati da due disegni diversi. */
const LX = -0.45, LY = -0.45, LZ = 0.77;

/** Quanto la pendenza schiarisce e scurisce, e quanto contano conche e dossi. Tenuti bassi di
 *  proposito: un rilievo esagerato trasforma una piana in una grattugia. */
const STRENGTH = 0.62;
const CAVITY = 0.12;
/* Gli estremi sono stretti di proposito. Con un tetto alto una cima di roccia chiara
   arrivava a centosettanta e passa di grigio piu' la tinta calda: in mezzo a un bosco si
   leggeva come una nuvola bianca appoggiata sul terreno, non come una rupe. */
const MIN_LIGHT = 0.52, MAX_LIGHT = 1.34;

/** Il passo della scala in cui la luce sta compressa: 160 e' "piano", cioe' 1.0. Un byte
 *  invece di un float perche' questi vettori hanno 590.000 posizioni e vivono quanto la
 *  colonia -- tre `Float32Array` sarebbero sette megabyte per una sfumatura che l'occhio
 *  non distingue a 1/160. */
const LIGHT_UNIT = 160;

export type Relief = {
  /** La luce su ogni cella, in unita' da 1/160: 160 e' terreno piano. */
  light: Uint8Array;
  /** Quanto e' fonda l'acqua, 0 sulla terra e 255 dove non si vede il fondo. */
  depth: Uint8Array;
  /** Quanto dista il confine fra acqua e terra, in trentaduesimi di cella (255 = otto celle
   *  o piu'). Una DISTANZA e non una comodita' gia' invertita: la schiuma la vuole corta e
   *  l'orlo bagnato cortissima, e due misure diverse dalla stessa passata sono possibili
   *  solo se quello che si conserva e' il numero grezzo. */
  shore: Uint8Array;
};

export function lightOf(relief: Relief, index: number): number {
  return relief.light[index] / LIGHT_UNIT;
}

/** Quanto dista la riva, in celle. */
export function shoreCells(relief: Relief, index: number): number {
  return relief.shore[index] / 32;
}

const CACHE = new WeakMap<ColonyGround, Relief>();

/** Il rilievo di una colonia. Calcolato una volta sola: lo vogliono sia la tela grande sia la
 *  minimappa, e sono 590.000 celle per tre passate. */
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
  const metres = ground.cell_metres || 8;

  const wet = new Uint8Array(total);
  for (let i = 0; i < total; i++) {
    wet[i] = WATER.has(ground.ground_names[ground.cells.ground[i]]) ? 1 : 0;
  }

  // 1. Le altezze sono INTERI di metri, e derivare una scala a gradini da' gradini: la prima
  //    versione aveva le curve di livello stampate addosso alla sabbia, come un'impronta
  //    digitale: con celle da otto metri, un gradino di un metro vale 0,125 di pendenza, che
  //    in una piana e' PIU' della pendenza vera. Sette celle di media -- una cinquantina di
  //    metri -- sciolgono il gradino e non toccano un rilievo che e' largo centinaia.
  const smooth = boxBlur(height, size, 3);

  // 2. La pendenza, in metri per metro, con le differenze centrali. Ai bordi la differenza e'
  //    di un lato solo: una colonia ha un confine e li' non c'e' niente da interpolare.
  const gx = new Float32Array(total);
  const gy = new Float32Array(total);
  let slopeSum = 0;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = y * size + x;
      const left = x > 0 ? i - 1 : i;
      const right = x < size - 1 ? i + 1 : i;
      const up = y > 0 ? i - size : i;
      const down = y < size - 1 ? i + size : i;
      const spanX = Math.max(1, (x > 0 ? 1 : 0) + (x < size - 1 ? 1 : 0)) * metres;
      const spanY = Math.max(1, (y > 0 ? 1 : 0) + (y < size - 1 ? 1 : 0)) * metres;
      const dx = (smooth[right] - smooth[left]) / spanX;
      const dy = (smooth[down] - smooth[up]) / spanY;
      gx[i] = dx;
      gy[i] = dy;
      slopeSum += Math.abs(dx) + Math.abs(dy);
    }
  }

  // 3. La scala della pendenza la decide il sito, non una costante. Un deserto piatto e una
  //    valle alpina hanno lo stesso diritto di vedersi: se il rilievo fosse tarato in assoluto,
  //    uno sarebbe carta bianca e l'altro carbone.
  const typical = Math.max(0.004, slopeSum / (2 * total));
  const steepen = 1 / (typical * 2.6);

  // 4. Conche e dossi: l'altezza contro la sua media larga. E' cio' che da' fondo a una valle,
  //    che la sola pendenza non sa dire -- un fianco regolare ha pendenza costante ovunque.
  const broad = boxBlur(height, size, 7);
  let cavitySum = 0;
  for (let i = 0; i < total; i++) cavitySum += Math.abs(smooth[i] - broad[i]);
  const cavityScale = Math.max(0.5, cavitySum / total) * 2.2;

  const light = new Uint8Array(total);
  for (let i = 0; i < total; i++) {
    const nx = -gx[i] * steepen;
    const ny = -gy[i] * steepen;
    const length = Math.sqrt(nx * nx + ny * ny + 1);
    const lambert = (nx * LX + ny * LY + LZ) / length;
    const cavity = Math.max(-1, Math.min(1, (smooth[i] - broad[i]) / cavityScale));
    // Il piano vale ESATTAMENTE 1: sotto un cielo senza rilievo il colore della cella resta
    // quello che la tavolozza dice, e la luce aggiunge solo cio' che il terreno fa davvero.
    let value = 1 + STRENGTH * ((lambert - LZ) / LZ) + CAVITY * cavity;
    if (wet[i]) value = 1 + 0.16 * ((lambert - LZ) / LZ);   // l'acqua e' una superficie, non un fianco
    value = Math.max(MIN_LIGHT, Math.min(MAX_LIGHT, value));
    light[i] = Math.round(value * LIGHT_UNIT);
  }

  // 5. L'acqua: quanto e' fonda, con una curva senza scala. Un rapporto sul fondo piu' basso
  //    avrebbe reso ogni colonia diversa da se stessa -- una pozza sarebbe stata nera quanto
  //    un oceano solo perche' era la cosa piu' fonda che c'era.
  const depth = new Uint8Array(total);
  for (let i = 0; i < total; i++) {
    if (!wet[i]) continue;
    const below = Math.max(0, -height[i]);
    depth[i] = Math.round(255 * (1 - Math.exp(-below / 95)));
  }

  return { light, depth, shore: shoreDistance(wet, size) };
}

/** Media mobile quadrata, separabile: due passate invece di una finestra per cella. */
function boxBlur(source: ArrayLike<number>, size: number, radius: number): Float32Array {
  const pass = new Float32Array(size * size);
  const out = new Float32Array(size * size);
  const span = radius * 2 + 1;
  for (let y = 0; y < size; y++) {
    let sum = 0;
    for (let k = -radius; k <= radius; k++) sum += source[y * size + clampIndex(k, size)];
    for (let x = 0; x < size; x++) {
      pass[y * size + x] = sum / span;
      sum -= source[y * size + clampIndex(x - radius, size)];
      sum += source[y * size + clampIndex(x + radius + 1, size)];
    }
  }
  for (let x = 0; x < size; x++) {
    let sum = 0;
    for (let k = -radius; k <= radius; k++) sum += pass[clampIndex(k, size) * size + x];
    for (let y = 0; y < size; y++) {
      out[y * size + x] = sum / span;
      sum -= pass[clampIndex(y - radius, size) * size + x];
      sum += pass[clampIndex(y + radius + 1, size) * size + x];
    }
  }
  return out;
}

function clampIndex(value: number, size: number): number {
  return value < 0 ? 0 : value >= size ? size - 1 : value;
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
