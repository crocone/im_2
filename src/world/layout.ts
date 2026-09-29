import { WORLD } from '../config';
import { Rng } from '../core/rng';

/** Summary of one building module used by the layout generator (dimensions in the module's own frame). */
export interface ModuleSummary {
  index: number;
  name: string;
  w: number; // footprint X extent
  d: number; // footprint Z extent
  h: number; // height
}

export interface BuildingPlacement {
  module: number;
  x: number;
  z: number;
  rot: number; // 0..3 quarter turns
  block: number;
  /** size of the lot the building stands on */
  lotW: number;
  lotD: number;
}

export interface Plaza {
  x: number;
  z: number;
  w: number;
  d: number;
}

export interface Layout {
  buildings: BuildingPlacement[];
  far: BuildingPlacement[];
  plazas: Plaza[];
  /** block centres of the playable area (8 x 8) */
  blocks: { x: number; z: number; ix: number; iz: number }[];
  /** block centres of the decorative far ring */
  farBlocks: { x: number; z: number }[];
}

const FAR_RINGS = 3;

interface Lot {
  x: number;
  z: number;
  w: number;
  d: number;
}

function subdivide(rng: Rng, district: number): Lot[] {
  const L = WORLD.lot;
  const half = L / 2;
  const gap = 4;
  const q = (L - gap) / 2; // 34
  // pattern probabilities depend on the district (0 = outskirts .. 1 = downtown)
  const r = rng.next();
  // most module footprints are 30-64 m wide, so full lots must dominate to get a varied skyline
  const big = 0.42 + 0.3 * district;
  if (r < big) return [{ x: 0, z: 0, w: L, d: L }];
  if (r < big + 0.2) {
    // two slabs
    return rng.chance(0.5)
      ? [{ x: -(q / 2 + gap / 2), z: 0, w: q, d: L }, { x: q / 2 + gap / 2, z: 0, w: q, d: L }]
      : [{ x: 0, z: -(q / 2 + gap / 2), w: L, d: q }, { x: 0, z: q / 2 + gap / 2, w: L, d: q }];
  }
  if (r < big + 0.3) {
    // one long slab + two squares
    const flip = rng.chance(0.5) ? 1 : -1;
    const sz = flip * (q / 2 + gap / 2);
    return [
      { x: 0, z: -sz, w: L, d: q },
      { x: -(q / 2 + gap / 2), z: sz, w: q, d: q },
      { x: q / 2 + gap / 2, z: sz, w: q, d: q },
    ];
  }
  void half;
  // four squares
  const o = q / 2 + gap / 2;
  return [
    { x: -o, z: -o, w: q, d: q },
    { x: o, z: -o, w: q, d: q },
    { x: -o, z: o, w: q, d: q },
    { x: o, z: o, w: q, d: q },
  ];
}

function pickModule(rng: Rng, modules: ModuleSummary[], lot: Lot, district: number): { module: number; rot: number } | null {
  const targetH = 24 + 105 * district * district + rng.range(-10, 20);
  const cands: { module: number; rot: number; weight: number }[] = [];
  for (const m of modules) {
    for (const rot of [0, 1]) {
      const w = rot === 0 ? m.w : m.d;
      const d = rot === 0 ? m.d : m.w;
      if (w <= lot.w - 1.5 && d <= lot.d - 1.5) {
        const fill = (w * d) / (lot.w * lot.d);
        const weight = Math.exp(-Math.abs(m.h - targetH) / 38) * (0.35 + fill);
        cands.push({ module: m.index, rot, weight });
      }
    }
  }
  if (!cands.length) return null;
  let sum = 0;
  for (const c of cands) sum += c.weight;
  let r = rng.next() * sum;
  for (const c of cands) {
    r -= c.weight;
    if (r <= 0) return { module: c.module, rot: c.rot + (rng.chance(0.5) ? 2 : 0) };
  }
  const c = cands[cands.length - 1];
  return { module: c.module, rot: c.rot };
}

/** Deterministic city layout: 8x8 blocks of 100 m with subdivided lots, plus a decorative ring of low-detail blocks. */
export function generateLayout(modules: ModuleSummary[], seed = WORLD.seed): Layout {
  const rng = new Rng(seed);
  const layout: Layout = { buildings: [], far: [], plazas: [], blocks: [], farBlocks: [] };
  const N = WORLD.blocks;
  const pitch = WORLD.pitch;
  const total = N + 2 * FAR_RINGS;
  let blockId = 0;
  for (let iz = -FAR_RINGS; iz < N + FAR_RINGS; iz++) {
    for (let ix = -FAR_RINGS; ix < N + FAR_RINGS; ix++) {
      const bx = (ix - (N - 1) / 2) * pitch;
      const bz = (iz - (N - 1) / 2) * pitch;
      const inner = ix >= 0 && ix < N && iz >= 0 && iz < N;
      const dist = Math.hypot(bx, bz);
      const district = Math.max(0, 1 - dist / 470);
      const lots = subdivide(rng, inner ? district : district * 0.6);
      if (inner) layout.blocks.push({ x: bx, z: bz, ix, iz });
      else layout.farBlocks.push({ x: bx, z: bz });
      // keep a few lots free as plazas (in the playable area only)
      for (const lot of lots) {
        const plaza = inner && rng.chance(lot.w < 40 && lot.d < 40 ? 0.2 : 0.06);
        if (plaza) {
          layout.plazas.push({ x: bx + lot.x, z: bz + lot.z, w: lot.w, d: lot.d });
          continue;
        }
        const pick = pickModule(rng, modules, lot, district);
        if (!pick) {
          if (inner) layout.plazas.push({ x: bx + lot.x, z: bz + lot.z, w: lot.w, d: lot.d });
          continue;
        }
        const b: BuildingPlacement = { module: pick.module, x: bx + lot.x, z: bz + lot.z, rot: pick.rot, block: blockId, lotW: lot.w, lotD: lot.d };
        (inner ? layout.buildings : layout.far).push(b);
      }
      blockId++;
    }
  }
  void total;
  ensureVariety(layout.buildings, modules, rng, 4);
  return layout;
}

/**
 * Every module must appear a few times in the playable area (the signature towers are only used on full lots and would
 * otherwise be rare): the most common module gives up a lot that is big enough for the missing one.
 */
function ensureVariety(list: BuildingPlacement[], modules: ModuleSummary[], rng: Rng, minCount: number) {
  const count = new Map<number, number>();
  for (const b of list) count.set(b.module, (count.get(b.module) ?? 0) + 1);
  // tall modules first: they are the ones that define the skyline
  const order = [...modules].sort((a, b) => b.h - a.h);
  for (const m of order) {
    let guard = 0;
    while ((count.get(m.index) ?? 0) < minCount && guard++ < 12) {
      const cands: { b: BuildingPlacement; rot: number }[] = [];
      for (const b of list) {
        // only take lots away from modules that have plenty of instances
        if ((count.get(b.module) ?? 0) <= minCount + 1) continue;
        for (const rot of [0, 1]) {
          const w = rot === 0 ? m.w : m.d;
          const d = rot === 0 ? m.d : m.w;
          if (w <= b.lotW - 1.5 && d <= b.lotD - 1.5) cands.push({ b, rot });
        }
      }
      if (!cands.length) break;
      const pick = rng.pick(cands);
      count.set(pick.b.module, (count.get(pick.b.module) ?? 1) - 1);
      pick.b.module = m.index;
      pick.b.rot = pick.rot + (rng.chance(0.5) ? 2 : 0);
      count.set(m.index, (count.get(m.index) ?? 0) + 1);
    }
  }
}
