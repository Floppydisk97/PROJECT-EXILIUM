// The twin of `backend/app/prng.py`. Both produce the same numbers, and
// `citygen.test.ts` holds them to it against a reference the Python side wrote.
//
// Mulberry32: one word of state, thirty-two-bit integer arithmetic and nothing else. Chosen
// over reimplementing CPython's Mersenne Twister and its `gauss`, which is where this would
// otherwise have had to start -- reimplementing a language's standard library is the wrong
// end to pick up.

const MASK = 0xffffffff;

/** FNV-1a, 32 bit. Spelled out, like the rest of this file. */
export function seedInt(text: string): number {
  let h = 2166136261 >>> 0;
  const bytes = new TextEncoder().encode(text);
  for (const byte of bytes) h = Math.imul(h ^ byte, 16777619) >>> 0;
  return h >>> 0;
}

export class Prng {
  private state: number;

  constructor(seed: number | string) {
    this.state = (typeof seed === "string" ? seedInt(seed) : seed) >>> 0;
  }

  nextUint(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
    t = (t ^ (t + (Math.imul(t ^ (t >>> 7), t | 61) >>> 0))) >>> 0;
    return (t ^ (t >>> 14)) >>> 0;
  }

  random(): number {
    return this.nextUint() / 4294967296;
  }

  uniform(low: number, high: number): number {
    return low + (high - low) * this.random();
  }

  /** Inclusive at both ends, matching Python's `randint`. */
  randint(low: number, high: number): number {
    return low + Math.floor(this.random() * (high - low + 1));
  }

  /** A point picked uniformly on the unit sphere -- no logarithm, so one fewer place where
   *  two maths libraries can disagree in the last bit. */
  direction(): [number, number, number] {
    const z = 2 * this.random() - 1;
    const phi = 2 * Math.PI * this.random();
    const r = Math.sqrt(Math.max(0, 1 - z * z));
    return [r * Math.cos(phi), r * Math.sin(phi), z];
  }
}
