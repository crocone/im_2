/** Small deterministic PRNG (mulberry32) so the city layout and asset-driven content are reproducible. */
export class Rng {
  private s: number;
  constructor(seed = 1) {
    this.s = seed >>> 0;
  }
  next(): number {
    this.s = (this.s + 0x6d2b79f5) >>> 0;
    let t = this.s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  range(a: number, b: number) {
    return a + (b - a) * this.next();
  }
  int(a: number, b: number) {
    return Math.floor(this.range(a, b + 1));
  }
  chance(p: number) {
    return this.next() < p;
  }
  pick<T>(arr: readonly T[]): T {
    return arr[Math.floor(this.next() * arr.length) % arr.length];
  }
  sign() {
    return this.next() < 0.5 ? -1 : 1;
  }
  gauss() {
    let u = 0;
    let v = 0;
    while (u === 0) u = this.next();
    while (v === 0) v = this.next();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }
  /** Fisher-Yates */
  shuffle<T>(arr: T[]): T[] {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(this.next() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }
}

/** Shared non-deterministic-ish generator for gameplay effects (seeded once per session). */
export const fxRng = new Rng((Date.now() ^ 0x9e3779b9) >>> 0);
export const rand = (a = 0, b = 1) => a + (b - a) * fxRng.next();
export const randSign = () => (fxRng.next() < 0.5 ? -1 : 1);
