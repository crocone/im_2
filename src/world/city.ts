import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { WORLD } from '../config';
import { RAPIER, MASKS } from '../physics/world';
import type { GameCtx } from '../game/types';
import { Rng } from '../core/rng';
import { generateLayout, Layout, ModuleSummary, Plaza } from './layout';

export interface MeshPart {
  geometry: THREE.BufferGeometry;
  material: THREE.Material | THREE.Material[];
  matrix: THREE.Matrix4; // relative to the module root
}

export interface BuildingModule extends ModuleSummary {
  parts: MeshPart[];
  lodParts: MeshPart[];
  boxes: { center: THREE.Vector3; half: THREE.Vector3 }[];
  slots: THREE.Vector3[];
  /** free vertical space above every roof slot (metres; Infinity = open sky) - canopies and pavilions limit it */
  slotClear: number[];
}

export interface BuildingInstance {
  module: BuildingModule;
  pos: THREE.Vector3;
  rot: number; // quarter turns
  /** world-space roof slots (surface points) */
  slots: THREE.Vector3[];
  height: number;
}

export interface RoofSlot {
  pos: THREE.Vector3;
  building: number;
  height: number;
  /** free vertical space above the slot (metres) */
  clear: number;
}

const _m = new THREE.Matrix4();
const _p = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _s = new THREE.Vector3();
const _e = new THREE.Euler();

/** Extract mesh parts, collider boxes and roof slots of a named subtree, relative to that subtree's root. */
export function collectParts(scene: THREE.Object3D, rootName: string) {
  const root = scene.getObjectByName(rootName);
  if (!root) throw new Error(`asset node ${rootName} missing`);
  scene.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(root.matrixWorld).invert();
  const parts: MeshPart[] = [];
  const boxes: { center: THREE.Vector3; half: THREE.Vector3 }[] = [];
  const slots: THREE.Vector3[] = [];
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (mesh.isMesh) {
      parts.push({ geometry: mesh.geometry, material: mesh.material, matrix: new THREE.Matrix4().multiplyMatrices(inv, mesh.matrixWorld) });
    } else if (o.name.startsWith('COL_')) {
      const rel = new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld);
      const p = new THREE.Vector3();
      const q = new THREE.Quaternion();
      const s = new THREE.Vector3();
      rel.decompose(p, q, s);
      boxes.push({ center: p, half: new THREE.Vector3(Math.abs(s.x), Math.abs(s.y), Math.abs(s.z)) });
    } else if (o.name.startsWith('Roof_Slot_')) {
      const rel = new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld);
      slots.push(new THREE.Vector3().setFromMatrixPosition(rel));
    }
  });
  return { parts, boxes, slots, root };
}

/** vertical clearance above a point: the lowest vertex above it within a small radius (roof canopies, pavilions ...) */
function clearanceAbove(parts: MeshPart[], slot: THREE.Vector3, radius = 2.8) {
  let clear = Infinity;
  const v = new THREE.Vector3();
  for (const part of parts) {
    const pos = part.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(part.matrix);
      if (v.y <= slot.y + 0.4) continue;
      if (Math.hypot(v.x - slot.x, v.z - slot.z) < radius && v.y - slot.y < clear) clear = v.y - slot.y;
    }
  }
  return clear;
}

function partsBounds(parts: MeshPart[]) {
  const box = new THREE.Box3();
  const tmp = new THREE.Box3();
  for (const p of parts) {
    if (!p.geometry.boundingBox) p.geometry.computeBoundingBox();
    tmp.copy(p.geometry.boundingBox!).applyMatrix4(p.matrix);
    box.union(tmp);
  }
  return box;
}

/**
 * Static batching: bakes many placed copies of mesh parts into ONE merged geometry per material, so a chunk of the
 * city costs a handful of draw calls instead of hundreds (instance colour tints are baked into vertex colours).
 */
class Batcher {
  private groups = new Map<THREE.Material, THREE.BufferGeometry[]>();
  private static tinted = new Map<THREE.Material, THREE.Material>();
  triangles = 0;

  private static tintMaterial(m: THREE.Material) {
    let t = Batcher.tinted.get(m);
    if (!t) {
      t = m.clone();
      (t as THREE.MeshStandardMaterial).vertexColors = true;
      Batcher.tinted.set(m, t);
    }
    return t;
  }

  add(part: MeshPart, placement: THREE.Matrix4, color?: THREE.Color) {
    const src = part.geometry;
    const g = new THREE.BufferGeometry();
    const pos = src.attributes.position;
    g.setAttribute('position', pos.clone());
    g.setAttribute('normal', src.attributes.normal ? src.attributes.normal.clone() : new THREE.BufferAttribute(new Float32Array(pos.count * 3), 3));
    g.setAttribute('uv', src.attributes.uv ? src.attributes.uv.clone() : new THREE.BufferAttribute(new Float32Array(pos.count * 2), 2));
    const col = new Float32Array(pos.count * 3);
    const cr = color ? color.r : 1;
    const cg = color ? color.g : 1;
    const cb = color ? color.b : 1;
    for (let i = 0; i < pos.count; i++) {
      col[i * 3] = cr;
      col[i * 3 + 1] = cg;
      col[i * 3 + 2] = cb;
    }
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    if (src.index) g.setIndex(src.index.clone());
    g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(placement, part.matrix));
    const mat = Array.isArray(part.material) ? part.material[0] : part.material;
    const list = this.groups.get(mat) ?? [];
    list.push(g);
    this.groups.set(mat, list);
  }

  build(target: THREE.Object3D, cast: boolean, receive: boolean) {
    for (const [mat, list] of this.groups) {
      // ensure uniform index presence for the merge
      const merged = list.length === 1 ? list[0] : mergeGeometries(list, false);
      if (!merged) {
        console.warn('static batch merge failed for', mat.name);
        continue;
      }
      if (list.length > 1) for (const g of list) g.dispose();
      merged.computeBoundingSphere();
      merged.computeBoundingBox();
      const mesh = new THREE.Mesh(merged, Batcher.tintMaterial(mat));
      mesh.castShadow = cast;
      mesh.receiveShadow = receive;
      mesh.matrixAutoUpdate = false;
      target.add(mesh);
      this.triangles += (merged.index ? merged.index.count : merged.attributes.position.count) / 3;
    }
    this.groups.clear();
  }
}

interface Chunk {
  cx: number;
  cz: number;
  minX: number;
  minZ: number;
  maxX: number;
  maxZ: number;
  high: THREE.Group;
  low: THREE.Group;
  ground: THREE.Group;
  bHigh: Batcher;
  bLow: Batcher;
  bGround: Batcher;
  shadows: boolean;
}

/**
 * The city: layout of building modules on a 8x8 block grid (plus a decorative low-detail ring), instanced per 200 m
 * chunk (frustum culling + LOD1 swap by distance), fixed Rapier colliders built from the authored COL_ boxes.
 */
export class City {
  modules: BuildingModule[] = [];
  layout!: Layout;
  buildings: BuildingInstance[] = [];
  roofSlots: RoofSlot[] = [];
  plazas: Plaza[] = [];
  readonly group = new THREE.Group();
  private chunks = new Map<string, Chunk>();
  private lodTimer = 0;
  private groundParts = new Map<string, MeshPart[]>();
  colliderCount = 0;
  triangleCount = 0;

  constructor(private ctx: GameCtx) {
    ctx.scene.add(this.group);
  }

  build() {
    const assets = this.ctx.assets;
    const bScene = assets.get('city_buildings').scene;
    const roots: THREE.Object3D[] = [];
    bScene.traverse((o) => {
      if (!/^Bld_\d+/.test(o.name) || o.name.endsWith('_LOD1')) return;
      // only the outermost node of a module (sub-meshes may carry the same prefix)
      for (let p = o.parent; p; p = p.parent) if (/^Bld_\d+/.test(p.name)) return;
      roots.push(o);
    });
    roots.sort((a, b) => a.name.localeCompare(b.name));
    roots.forEach((r, index) => {
      const main = collectParts(bScene, r.name);
      const lodRoot = bScene.getObjectByName(`${r.name}_LOD1`);
      const lod = lodRoot ? collectParts(bScene, `${r.name}_LOD1`) : main;
      const bounds = partsBounds(main.parts);
      let w = 0;
      let d = 0;
      let h = 0;
      if (main.boxes.length) {
        const bb = new THREE.Box3();
        for (const b of main.boxes) bb.union(new THREE.Box3(b.center.clone().sub(b.half), b.center.clone().add(b.half)));
        w = bb.max.x - bb.min.x;
        d = bb.max.z - bb.min.z;
        h = bb.max.y;
      } else {
        w = bounds.max.x - bounds.min.x;
        d = bounds.max.z - bounds.min.z;
        h = bounds.max.y;
      }
      // materials: modest env reflections so facades do not glow
      for (const p of main.parts.concat(lod.parts)) {
        const mats = Array.isArray(p.material) ? p.material : [p.material];
        for (const m of mats) if ((m as THREE.MeshStandardMaterial).isMeshStandardMaterial) (m as THREE.MeshStandardMaterial).envMapIntensity = 0.7;
      }
      const slotClear = main.slots.map((sl) => clearanceAbove(main.parts, sl));
      this.modules.push({ index, name: r.name, w, d, h, parts: main.parts, lodParts: lod.parts, boxes: main.boxes, slots: main.slots, slotClear });
    });
    if (this.modules.length < 8) throw new Error(`city_buildings.glb must contain >= 8 building modules (found ${this.modules.length})`);

    this.layout = generateLayout(this.modules);
    this.plazas = this.layout.plazas;
    this.placeBuildings();
    this.buildGround();
    this.buildFarRing();
    this.buildColliders();
    this.pickSpawnRoof();
  }

  // ------------------------------------------------------------------ placement
  private rotMatrix(rot: number) {
    return _m.makeRotationY((rot * Math.PI) / 2);
  }

  private placeBuildings() {
    for (const b of this.layout.buildings) {
      const mod = this.modules[b.module];
      const pos = new THREE.Vector3(b.x, WORLD.lotY, b.z);
      const rotM = new THREE.Matrix4().makeRotationY((b.rot * Math.PI) / 2);
      const slots = mod.slots.map((s) => s.clone().applyMatrix4(rotM).add(pos));
      this.buildings.push({ module: mod, pos, rot: b.rot, slots, height: mod.h });
    }
    this.buildings.forEach((b, i) => {
      b.slots.forEach((s, k) => this.roofSlots.push({ pos: s, building: i, height: b.height, clear: b.module.slotClear[k] }));
    });
  }

  private chunkFor(x: number, z: number) {
    const n = Math.ceil((WORLD.half * 2) / WORLD.chunk);
    const cx = Math.max(0, Math.min(n - 1, Math.floor((x + WORLD.half) / WORLD.chunk)));
    const cz = Math.max(0, Math.min(n - 1, Math.floor((z + WORLD.half) / WORLD.chunk)));
    const key = `${cx},${cz}`;
    let c = this.chunks.get(key);
    if (!c) {
      c = {
        cx, cz,
        minX: cx * WORLD.chunk - WORLD.half, minZ: cz * WORLD.chunk - WORLD.half,
        maxX: (cx + 1) * WORLD.chunk - WORLD.half, maxZ: (cz + 1) * WORLD.chunk - WORLD.half,
        high: new THREE.Group(), low: new THREE.Group(), ground: new THREE.Group(),
        bHigh: new Batcher(), bLow: new Batcher(), bGround: new Batcher(), shadows: true,
      };
      c.low.visible = false;
      this.group.add(c.high, c.low, c.ground);
      this.chunks.set(key, c);
    }
    return c;
  }

  private addBatch(batch: Batcher, parts: MeshPart[], placements: THREE.Matrix4[], colors?: THREE.Color[]) {
    for (let i = 0; i < placements.length; i++) for (const part of parts) batch.add(part, placements[i], colors?.[i]);
  }

  private buildGround() {
    const gScene = this.ctx.assets.get('city_ground').scene;
    const tiles: Record<string, MeshPart[]> = {};
    for (const name of ['Road_Straight', 'Road_Intersection', 'Sidewalk_Straight', 'Sidewalk_Corner', 'Lot_Ground']) {
      tiles[name] = collectParts(gScene, name).parts;
      this.groundParts.set(name, tiles[name]);
      for (const p of tiles[name]) {
        const mats = Array.isArray(p.material) ? p.material : [p.material];
        for (const mat of mats) if ((mat as THREE.MeshStandardMaterial).isMeshStandardMaterial) (mat as THREE.MeshStandardMaterial).envMapIntensity = 0.5;
      }
    }
    // gather placements per chunk and per tile type (near area + far ring blocks use the same tiles)
    const per = new Map<string, Record<string, THREE.Matrix4[]>>();
    const add = (name: string, x: number, z: number, rotY: number) => {
      const c = this.chunkFor(x, z);
      let rec = per.get(`${c.cx},${c.cz}`);
      if (!rec) per.set(`${c.cx},${c.cz}`, (rec = {}));
      (rec[name] ??= []).push(new THREE.Matrix4().compose(new THREE.Vector3(x, 0, z), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), rotY), new THREE.Vector3(1, 1, 1)));
    };
    const N = WORLD.blocks;
    const P = WORLD.pitch;
    const half = 38; // sidewalk centre offset from block centre
    for (const b of this.layout.blocks) {
      add('Lot_Ground', b.x, b.z, 0);
      add('Sidewalk_Straight', b.x - half, b.z, 0); // west: curb faces -X
      add('Sidewalk_Straight', b.x + half, b.z, Math.PI); // east
      add('Sidewalk_Straight', b.x, b.z - half, -Math.PI / 2); // north: curb faces -Z
      add('Sidewalk_Straight', b.x, b.z + half, Math.PI / 2); // south
      add('Sidewalk_Corner', b.x - half, b.z - half, 0);
      add('Sidewalk_Corner', b.x + half, b.z - half, -Math.PI / 2);
      add('Sidewalk_Corner', b.x + half, b.z + half, Math.PI);
      add('Sidewalk_Corner', b.x - half, b.z + half, Math.PI / 2);
    }
    // roads: N+1 lines each way, N straight segments per line, (N+1)^2 intersections
    for (let i = 0; i <= N; i++) {
      const line = (i - N / 2) * P;
      for (let j = 0; j < N; j++) {
        const seg = (j - (N - 1) / 2) * P;
        add('Road_Straight', line, seg, 0); // runs along Z
        add('Road_Straight', seg, line, Math.PI / 2); // runs along X
      }
      for (let j = 0; j <= N; j++) add('Road_Intersection', line, (j - N / 2) * P, 0);
    }
    for (const [key, rec] of per) {
      const c = this.chunks.get(key)!;
      for (const [name, mats] of Object.entries(rec)) this.addBatch(c.bGround, tiles[name], mats);
    }
    // far ring ground: same tiles, one group, no chunking
    const far = new THREE.Group();
    const farRec: Record<string, THREE.Matrix4[]> = {};
    const addFar = (name: string, x: number, z: number, rotY: number) => {
      (farRec[name] ??= []).push(new THREE.Matrix4().compose(new THREE.Vector3(x, 0, z), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), rotY), new THREE.Vector3(1, 1, 1)));
    };
    for (const b of this.layout.farBlocks) {
      addFar('Lot_Ground', b.x, b.z, 0);
      addFar('Sidewalk_Straight', b.x - half, b.z, 0);
      addFar('Sidewalk_Straight', b.x + half, b.z, Math.PI);
      addFar('Sidewalk_Straight', b.x, b.z - half, -Math.PI / 2);
      addFar('Sidewalk_Straight', b.x, b.z + half, Math.PI / 2);
    }
    const R = 3;
    for (let i = -R; i <= N + R; i++) {
      const line = (i - N / 2) * P;
      for (let j = -R; j < N + R; j++) {
        const seg = (j - (N - 1) / 2) * P;
        const inner = i >= 0 && i <= N && j >= 0 && j < N;
        if (!inner) {
          addFar('Road_Straight', line, seg, 0);
          addFar('Road_Straight', seg, line, Math.PI / 2);
        }
      }
      for (let j = -R; j <= N + R; j++) {
        const inner = i >= 0 && i <= N && j >= 0 && j <= N;
        if (!inner) addFar('Road_Intersection', line, (j - N / 2) * P, 0);
      }
    }
    const farB = new Batcher();
    for (const [name, mats] of Object.entries(farRec)) this.addBatch(farB, tiles[name], mats);
    farB.build(far, false, true);
    this.triangleCount += farB.triangles;
    this.group.add(far);
  }

  private buildFarRing() {
    const rng = new Rng(7);
    const perModule = new Map<number, THREE.Matrix4[]>();
    const cols = new Map<number, THREE.Color[]>();
    for (const b of this.layout.far) {
      const arr = perModule.get(b.module) ?? [];
      arr.push(new THREE.Matrix4().compose(new THREE.Vector3(b.x, WORLD.lotY, b.z), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), (b.rot * Math.PI) / 2), new THREE.Vector3(1, 1, 1)));
      perModule.set(b.module, arr);
      const carr = cols.get(b.module) ?? [];
      const g = rng.range(0.75, 1.0);
      carr.push(new THREE.Color(g, g * rng.range(0.95, 1.02), g * rng.range(0.98, 1.08)));
      cols.set(b.module, carr);
    }
    const far = new THREE.Group();
    const farB = new Batcher();
    for (const [mi, mats] of perModule) this.addBatch(farB, this.modules[mi].lodParts, mats, cols.get(mi));
    farB.build(far, false, false);
    this.triangleCount += farB.triangles;
    this.group.add(far);
  }

  private buildColliders() {
    const phys = this.ctx.physics;
    const owner = { kind: 'world' as const };
    // ground slab (top at y = 0)
    phys.addCollider(RAPIER.ColliderDesc.cuboid(4000, 5, 4000).setTranslation(0, -5, 0).setCollisionGroups(MASKS.world).setFriction(0.8), undefined, owner);
    const rng = new Rng(11);
    const perModule = new Map<number, { m: THREE.Matrix4; c: THREE.Color }[]>();
    this.buildings.forEach((b, i) => {
      const rotM = new THREE.Matrix4().makeRotationY((b.rot * Math.PI) / 2);
      const swap = b.rot % 2 === 1;
      for (const box of b.module.boxes) {
        _p.copy(box.center).applyMatrix4(rotM).add(b.pos);
        const hx = swap ? box.half.z : box.half.x;
        const hz = swap ? box.half.x : box.half.z;
        phys.addCollider(RAPIER.ColliderDesc.cuboid(hx, box.half.y, hz).setTranslation(_p.x, _p.y, _p.z).setCollisionGroups(MASKS.world).setFriction(0.6).setRestitution(0.1), undefined, owner);
        this.colliderCount++;
      }
      const list = perModule.get(b.module.index) ?? [];
      const g = rng.range(0.8, 1.0);
      list.push({ m: new THREE.Matrix4().compose(b.pos, _q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), (b.rot * Math.PI) / 2), _s.set(1, 1, 1)), c: new THREE.Color(g, g * rng.range(0.96, 1.02), g * rng.range(0.98, 1.08)) });
      perModule.set(b.module.index, list);
      void i;
    });
    // visible instances, per chunk and module
    const byChunk = new Map<string, Map<number, { m: THREE.Matrix4; c: THREE.Color }[]>>();
    for (const b of this.buildings) {
      const ck = this.chunkFor(b.pos.x, b.pos.z);
      const key = `${ck.cx},${ck.cz}`;
      const rec = byChunk.get(key) ?? new Map();
      const list = rec.get(b.module.index) ?? [];
      const g = rng.range(0.82, 1.0);
      list.push({ m: new THREE.Matrix4().compose(b.pos, new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), (b.rot * Math.PI) / 2), new THREE.Vector3(1, 1, 1)), c: new THREE.Color(g, g * rng.range(0.96, 1.02), g * rng.range(0.98, 1.08)) });
      rec.set(b.module.index, list);
      byChunk.set(key, rec);
    }
    for (const [key, rec] of byChunk) {
      const c = this.chunks.get(key)!;
      for (const [mi, list] of rec) {
        const mod = this.modules[mi];
        const mats = list.map((x) => x.m);
        const cs = list.map((x) => x.c);
        this.addBatch(c.bHigh, mod.parts, mats, cs);
        this.addBatch(c.bLow, mod.lodParts, mats, cs);
      }
    }
    // bake every chunk's batches into merged meshes (one draw call per chunk and material)
    for (const c of this.chunks.values()) {
      c.bHigh.build(c.high, true, true);
      c.bLow.build(c.low, false, false);
      c.bGround.build(c.ground, false, true);
      this.triangleCount += c.bHigh.triangles + c.bGround.triangles;
    }
  }

  private pickSpawnRoof() {
    // start on a mid-height roof close to the centre so the whole battlefield is in view
    let best = -1;
    let bestScore = -1e9;
    let bestSlot = 0;
    this.buildings.forEach((b, i) => {
      // the suit needs open sky above the take-off spot
      const k = b.module.slotClear.findIndex((c) => c > 14);
      if (k < 0) return;
      const d = Math.hypot(b.pos.x + 60, b.pos.z + 60);
      const score = -Math.abs(b.height - 70) * 1.2 - d * 0.5 + (b.slots.length > 1 ? 10 : 0);
      if (score > bestScore) {
        bestScore = score;
        best = i;
        bestSlot = k;
      }
    });
    if (best < 0) throw new Error('no building with an open roof slot found');
    this.spawnBuilding = best;
    this.spawnRoof = this.buildings[best].slots[bestSlot].clone();
  }
  spawnBuilding = -1;
  spawnRoof = new THREE.Vector3();

  /** swap chunks between full-detail and LOD1 meshes by camera distance; only nearby chunks cast shadows */
  update(dt: number, camPos: THREE.Vector3, playerPos?: THREE.Vector3) {
    this.lodTimer -= dt;
    if (this.lodTimer > 0) return;
    this.lodTimer = 0.25;
    const ref = playerPos ?? camPos;
    for (const c of this.chunks.values()) {
      const dx = Math.max(c.minX - camPos.x, 0, camPos.x - c.maxX);
      const dz = Math.max(c.minZ - camPos.z, 0, camPos.z - c.maxZ);
      const dist = Math.hypot(dx, dz);
      const near = dist < WORLD.lodDistance;
      if (c.high.visible !== near) {
        c.high.visible = near;
        c.low.visible = !near;
      }
      const px = Math.max(c.minX - ref.x, 0, ref.x - c.maxX);
      const pz = Math.max(c.minZ - ref.z, 0, ref.z - c.maxZ);
      const shadows = Math.hypot(px, pz) < 230;
      if (c.shadows !== shadows) {
        c.shadows = shadows;
        for (const m of c.high.children) m.castShadow = shadows;
      }
    }
  }
}
