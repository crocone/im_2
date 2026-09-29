import * as THREE from 'three';
import { SCORE, WORLD } from '../config';
import { RAPIER, MASKS, Owner } from '../physics/world';
import type { GameCtx, HitInfo } from '../game/types';
import { Rng, rand } from '../core/rng';
import { COL } from '../fx/effects';
import { collectParts, MeshPart, City, RoofSlot } from './city';

interface PropType {
  key: string;
  parts: MeshPart[];
  half: THREE.Vector3;
  centerY: number;
  mass: number;
  hp: number;
  burning: boolean;
  thin: boolean;
  /** metres from the camera within which instances are drawn */
  range: number;
  castShadow: boolean;
  tinted: boolean;
  meshes: THREE.InstancedMesh[];
  capacity: number;
}

interface CatalogEntry {
  key: string;
  mass: number;
  hp: number;
  range: number;
  burning?: boolean;
  thin?: boolean;
  shadow?: boolean;
  tinted?: boolean;
}

const CATALOG: CatalogEntry[] = [
  { key: 'Prop_StreetLamp', mass: 220, hp: 35, thin: true, range: 300 },
  { key: 'Prop_Car_A', mass: 1300, hp: 70, burning: true, range: 260, shadow: true, tinted: true },
  { key: 'Prop_Car_B', mass: 1700, hp: 80, burning: true, range: 260, shadow: true, tinted: true },
  { key: 'Prop_Car_C', mass: 1500, hp: 75, burning: true, range: 260, shadow: true, tinted: true },
  { key: 'Prop_Barrier_Jersey', mass: 900, hp: 90, range: 260, shadow: true },
  { key: 'Prop_Barrier_Striped', mass: 200, hp: 30, range: 260, shadow: true },
  { key: 'Prop_Antenna', mass: 500, hp: 45, thin: true, range: 650, shadow: true },
  { key: 'Prop_AC_Unit_A', mass: 300, hp: 40, range: 420, shadow: true },
  { key: 'Prop_AC_Unit_B', mass: 350, hp: 40, range: 420, shadow: true },
  { key: 'Prop_Vent_Stack', mass: 200, hp: 30, range: 420, shadow: true },
  { key: 'Prop_Roof_Access', mass: 900, hp: 90, range: 520, shadow: true },
  { key: 'Prop_Cooling_Tower', mass: 700, hp: 70, range: 520, shadow: true },
  { key: 'Prop_Solar_Array', mass: 250, hp: 30, range: 420, shadow: true },
  { key: 'Prop_Hydrant', mass: 120, hp: 30, range: 200 },
  { key: 'Prop_Bench', mass: 90, hp: 25, range: 220 },
  { key: 'Prop_BusShelter', mass: 420, hp: 60, range: 300 },
  { key: 'Prop_TrafficLight', mass: 180, hp: 35, thin: true, range: 240 },
  { key: 'Prop_Planter', mass: 300, hp: 40, range: 220 },
  { key: 'Prop_Dumpster', mass: 350, hp: 50, range: 220 },
  { key: 'Prop_Tree', mass: 400, hp: 45, thin: true, range: 300 },
];

interface Prop {
  type: PropType;
  pos: THREE.Vector3;
  yaw: number;
  matrix: THREE.Matrix4;
  color: THREE.Color | null;
  alive: boolean;
  hp: number;
  collider: RAPIER.Collider | null;
  owner: Owner;
  takeDamage(amount: number, hit: HitInfo): void;
  cell: number;
}

interface PendingProp {
  type: PropType;
  pos: THREE.Vector3;
  yaw: number;
  color?: THREE.Color;
}

const _m = new THREE.Matrix4();
const _m2 = new THREE.Matrix4();
const _p = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _s = new THREE.Vector3(1, 1, 1);
const _f = new THREE.Vector3();
const AY = new THREE.Vector3(0, 1, 0);
const CELL = 40;

/**
 * Street and rooftop props. Rendering uses "streaming instancing": one InstancedMesh per prop type whose instance list is
 * refreshed a few times per second with only the props near the camera (a handful of draw calls for thousands of props).
 * Colliders are streamed in around the player. Props are destructible: cars, lamps, barriers ... turn into real
 * dynamic rigid bodies with impulses when shot or caught in an explosion.
 */
export class PropManager {
  private types = new Map<string, PropType>();
  private cells = new Map<number, Prop[]>();
  private activeCells = new Set<number>();
  private timer = 0;
  private visTimer = 0;
  private root = new THREE.Group();
  private pending: PendingProp[] = [];
  private counts = new Map<PropType, number>();
  props: Prop[] = [];
  count = 0;
  visibleInstances = 0;

  constructor(private ctx: GameCtx) {
    ctx.scene.add(this.root);
  }

  private loadTypes() {
    const scene = this.ctx.assets.get('city_props').scene;
    for (const c of CATALOG) {
      if (!scene.getObjectByName(c.key)) continue; // optional extras may be absent
      const { parts } = collectParts(scene, c.key);
      const box = new THREE.Box3();
      const tmp = new THREE.Box3();
      for (const p of parts) {
        if (!p.geometry.boundingBox) p.geometry.computeBoundingBox();
        tmp.copy(p.geometry.boundingBox!).applyMatrix4(p.matrix);
        box.union(tmp);
        const mats = Array.isArray(p.material) ? p.material : [p.material];
        for (const m of mats) if ((m as THREE.MeshStandardMaterial).isMeshStandardMaterial) (m as THREE.MeshStandardMaterial).envMapIntensity = 0.7;
      }
      const size = box.getSize(new THREE.Vector3());
      const half = size.clone().multiplyScalar(0.5);
      if (c.thin) {
        half.x = Math.min(half.x, 0.3);
        half.z = Math.min(half.z, 0.3);
      }
      this.types.set(c.key, {
        key: c.key, parts, half, centerY: (box.min.y + box.max.y) / 2, mass: c.mass, hp: c.hp, burning: !!c.burning, thin: !!c.thin,
        range: c.range, castShadow: !!c.shadow, tinted: !!c.tinted, meshes: [], capacity: 0,
      });
    }
  }

  private queue(key: string, pos: THREE.Vector3, yaw: number, color?: THREE.Color) {
    const type = this.types.get(key);
    if (!type) return;
    this.pending.push({ type, pos, yaw, color });
  }

  populate(city: City, reserved: Set<RoofSlot>) {
    this.loadTypes();
    const rng = new Rng(WORLD.seed ^ 0xa11ce);
    const N = WORLD.blocks;
    const P = WORLD.pitch;

    // ---- street lamps: one per block edge, arm over the road
    for (const b of city.layout.blocks) {
      const off = 38.8;
      const jitter = () => rng.range(-20, 20);
      this.queue('Prop_StreetLamp', new THREE.Vector3(b.x - off, WORLD.lotY, b.z + jitter()), Math.PI / 2);
      this.queue('Prop_StreetLamp', new THREE.Vector3(b.x + off, WORLD.lotY, b.z + jitter()), -Math.PI / 2);
      this.queue('Prop_StreetLamp', new THREE.Vector3(b.x + jitter(), WORLD.lotY, b.z - off), 0);
      this.queue('Prop_StreetLamp', new THREE.Vector3(b.x + jitter(), WORLD.lotY, b.z + off), Math.PI);
    }

    // ---- sidewalk furniture: trees, hydrants, benches, bus shelters, planters, dumpsters, traffic lights
    const edgePos = (b: { x: number; z: number }, edge: number, t: number, off: number) => {
      // edge: 0 west, 1 east, 2 north, 3 south; yaw makes the local -Z face the road
      if (edge === 0) return { x: b.x - off, z: b.z + t, yaw: Math.PI / 2 };
      if (edge === 1) return { x: b.x + off, z: b.z + t, yaw: -Math.PI / 2 };
      if (edge === 2) return { x: b.x + t, z: b.z - off, yaw: 0 };
      return { x: b.x + t, z: b.z + off, yaw: Math.PI };
    };
    for (const b of city.layout.blocks) {
      for (let edge = 0; edge < 4; edge++) {
        for (const t of [-26, 0, 26]) {
          if (rng.chance(0.33)) {
            const e = edgePos(b, edge, t + rng.range(-4, 4), 38.9);
            this.queue('Prop_Tree', new THREE.Vector3(e.x, WORLD.lotY, e.z), rng.range(0, 6.28));
          }
        }
        if (rng.chance(0.14)) {
          const e = edgePos(b, edge, rng.range(-28, 28), 39.0);
          this.queue('Prop_Hydrant', new THREE.Vector3(e.x, WORLD.lotY, e.z), e.yaw);
        }
        if (rng.chance(0.07)) {
          const e = edgePos(b, edge, rng.range(-24, 24), 38.2);
          this.queue('Prop_Bench', new THREE.Vector3(e.x, WORLD.lotY, e.z), e.yaw);
        }
        if (rng.chance(0.05)) {
          const e = edgePos(b, edge, rng.range(-20, 20), 38.4);
          this.queue('Prop_BusShelter', new THREE.Vector3(e.x, WORLD.lotY, e.z), e.yaw);
        }
        if (rng.chance(0.09)) {
          const e = edgePos(b, edge, rng.range(-30, 30), 37.4);
          this.queue('Prop_Planter', new THREE.Vector3(e.x, WORLD.lotY, e.z), e.yaw);
        }
        if (rng.chance(0.05)) {
          const e = edgePos(b, edge, rng.range(-30, 30), 37.6);
          this.queue('Prop_Dumpster', new THREE.Vector3(e.x, WORLD.lotY, e.z), e.yaw + Math.PI);
        }
      }
    }
    for (let n = 0; n < 46; n++) {
      const ix = rng.int(0, N);
      const iz = rng.int(0, N);
      const sx = rng.sign();
      const sz = rng.sign();
      this.queue('Prop_TrafficLight', new THREE.Vector3((ix - N / 2) * P + sx * 10.6, WORLD.lotY, (iz - N / 2) * P + sz * 10.6), sx > 0 ? -Math.PI / 2 : Math.PI / 2);
    }

    // ---- parked cars along the roads (two parking lanes per road segment)
    const carKeys = ['Prop_Car_A', 'Prop_Car_B', 'Prop_Car_C'];
    let cars = 0;
    for (let i = 0; i <= N && cars < 240; i++) {
      const line = (i - N / 2) * P;
      for (let j = 0; j < N; j++) {
        const seg = (j - (N - 1) / 2) * P;
        for (const side of [-1, 1]) {
          for (let k = -3; k <= 3; k++) {
            if (!rng.chance(0.13)) continue;
            const along = seg + k * 10.5 + rng.range(-1.2, 1.2);
            const lane = line + side * 7.4;
            const c = rng.range(0.55, 1.0);
            const col = new THREE.Color(c, c * rng.range(0.7, 1.05), c * rng.range(0.7, 1.1));
            this.queue(rng.pick(carKeys), new THREE.Vector3(lane, 0, along), side > 0 ? 0 : Math.PI, col);
            const along2 = seg + k * 10.5 + rng.range(-1.2, 1.2);
            this.queue(rng.pick(carKeys), new THREE.Vector3(along2, 0, lane), side > 0 ? -Math.PI / 2 : Math.PI / 2, col);
            cars += 2;
          }
        }
      }
    }

    // ---- road-blocks at some intersections
    for (let n = 0; n < 34; n++) {
      const ix = rng.int(0, N);
      const iz = rng.int(0, N);
      const cx = (ix - N / 2) * P;
      const cz = (iz - N / 2) * P;
      const vertical = rng.chance(0.5);
      for (let k = -1; k <= 1; k++) {
        const key = rng.chance(0.55) ? 'Prop_Barrier_Jersey' : 'Prop_Barrier_Striped';
        if (vertical) this.queue(key, new THREE.Vector3(cx + k * 3.6, 0, cz + 11.5), Math.PI / 2);
        else this.queue(key, new THREE.Vector3(cx + 11.5, 0, cz + k * 3.6), 0);
      }
    }

    // ---- rooftop clutter on every roof slot that is not reserved for turrets / destructibles
    const roofKeys = [
      ['Prop_Antenna', 0.16], ['Prop_AC_Unit_A', 0.2], ['Prop_AC_Unit_B', 0.18], ['Prop_Vent_Stack', 0.1],
      ['Prop_Roof_Access', 0.1], ['Prop_Cooling_Tower', 0.1], ['Prop_Solar_Array', 0.16],
    ] as const;
    for (const slot of city.roofSlots) {
      if (reserved.has(slot)) continue;
      if (!rng.chance(0.75)) continue;
      let r = rng.next();
      let key = 'Prop_AC_Unit_A';
      for (const [k, w] of roofKeys) {
        if ((r -= w) <= 0) {
          key = k;
          break;
        }
      }
      // keep tall props out from under canopies: fall back to a low AC unit
      const t = this.types.get(key);
      if (t && t.half.y * 2 + 0.4 > slot.clear) key = 'Prop_AC_Unit_A';
      const low = this.types.get(key);
      if (low && low.half.y * 2 + 0.2 > slot.clear) continue;
      this.queue(key, slot.pos.clone(), rng.int(0, 3) * (Math.PI / 2));
    }
    this.build();
  }

  /** create the prop records + one InstancedMesh per part of every prop type */
  private build() {
    for (const p of this.pending) this.counts.set(p.type, (this.counts.get(p.type) ?? 0) + 1);
    for (const [type, n] of this.counts) {
      type.capacity = n;
      type.meshes = type.parts.map((part) => {
        const im = new THREE.InstancedMesh(part.geometry, part.material, n);
        im.count = 0;
        im.frustumCulled = false; // the instance list is already restricted to the neighbourhood of the camera
        im.castShadow = type.castShadow;
        im.receiveShadow = true;
        im.matrixAutoUpdate = false;
        if (type.tinted) im.setColorAt(0, new THREE.Color(1, 1, 1));
        this.root.add(im);
        return im;
      });
    }
    for (const pd of this.pending) this.props.push(this.makeProp(pd));
    this.count = this.props.length;
    this.pending = [];
    this.refreshVisible(new THREE.Vector3(0, 100, 0), new THREE.Vector3(0, 0, -1));
  }

  private makeProp(pd: PendingProp): Prop {
    const cell = this.cellKey(pd.pos.x, pd.pos.z);
    const mgr = this;
    const prop: Prop = {
      type: pd.type, pos: pd.pos.clone(), yaw: pd.yaw,
      matrix: new THREE.Matrix4().compose(pd.pos, new THREE.Quaternion().setFromAxisAngle(AY, pd.yaw), new THREE.Vector3(1, 1, 1)),
      color: pd.color ?? null, alive: true, hp: pd.type.hp, collider: null, cell,
      owner: { kind: 'prop' },
      takeDamage(amount: number, hit: HitInfo) {
        mgr.damageProp(prop, amount, hit);
      },
    };
    prop.owner.ref = prop;
    const list = this.cells.get(cell) ?? [];
    list.push(prop);
    this.cells.set(cell, list);
    return prop;
  }

  private cellKey(x: number, z: number) {
    const ix = Math.floor(x / CELL) + 200;
    const iz = Math.floor(z / CELL) + 200;
    return ix * 1000 + iz;
  }

  private ensureCollider(p: Prop) {
    if (p.collider || !p.alive) return;
    const h = p.type.half;
    _p.set(0, p.type.centerY, 0).applyAxisAngle(AY, p.yaw).add(p.pos);
    _q.setFromAxisAngle(AY, p.yaw);
    const cd = RAPIER.ColliderDesc.cuboid(h.x, h.y, h.z)
      .setTranslation(_p.x, _p.y, _p.z)
      .setRotation({ x: _q.x, y: _q.y, z: _q.z, w: _q.w })
      .setCollisionGroups(MASKS.world)
      .setFriction(0.5);
    p.collider = this.ctx.physics.addCollider(cd, undefined, p.owner);
  }

  private dropCollider(p: Prop) {
    if (!p.collider) return;
    this.ctx.physics.removeCollider(p.collider);
    p.collider = null;
  }

  /** rebuild the per-type instance lists for props near the camera (behind-camera props are skipped) */
  private refreshVisible(camPos: THREE.Vector3, camFwd: THREE.Vector3) {
    for (const type of this.counts.keys()) {
      for (const im of type.meshes) im.count = 0;
    }
    const idx = new Map<PropType, number>();
    let total = 0;
    for (const p of this.props) {
      if (!p.alive) continue;
      const dx = p.pos.x - camPos.x;
      const dy = p.pos.y - camPos.y;
      const dz = p.pos.z - camPos.z;
      const t = p.type;
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 > t.range * t.range) continue;
      if (dx * camFwd.x + dy * camFwd.y + dz * camFwd.z < -45 && d2 > 2500) continue;
      const i = idx.get(t) ?? 0;
      idx.set(t, i + 1);
      total++;
      for (let k = 0; k < t.parts.length; k++) {
        const im = t.meshes[k];
        _m2.multiplyMatrices(p.matrix, t.parts[k].matrix);
        im.setMatrixAt(i, _m2);
        if (p.color) im.setColorAt(i, p.color);
      }
    }
    for (const [t, n] of idx) {
      for (const im of t.meshes) {
        im.count = n;
        im.instanceMatrix.needsUpdate = true;
        if (im.instanceColor) im.instanceColor.needsUpdate = true;
      }
    }
    this.visibleInstances = total;
  }

  /** stream colliders in a radius around the player; refresh the visible instance lists around the camera */
  update(dt: number, playerPos: THREE.Vector3, camPos: THREE.Vector3) {
    this.visTimer -= dt;
    if (this.visTimer <= 0) {
      this.visTimer = 0.2;
      this.ctx.camera.getWorldDirection(_f);
      this.refreshVisible(camPos, _f);
    }
    this.timer -= dt;
    if (this.timer > 0) return;
    this.timer = 0.3;
    const on = 95;
    const off = 140;
    const cx0 = Math.floor(playerPos.x / CELL);
    const cz0 = Math.floor(playerPos.z / CELL);
    const R = Math.ceil(off / CELL);
    const want = new Set<number>();
    for (let dx = -R; dx <= R; dx++) {
      for (let dz = -R; dz <= R; dz++) {
        const wx = (cx0 + dx + 0.5) * CELL;
        const wz = (cz0 + dz + 0.5) * CELL;
        const d = Math.hypot(wx - playerPos.x, wz - playerPos.z);
        const key = this.cellKey(wx, wz);
        if (d < on || (this.activeCells.has(key) && d < off)) want.add(key);
      }
    }
    for (const key of want) {
      if (!this.activeCells.has(key)) {
        const list = this.cells.get(key);
        if (list) for (const p of list) this.ensureCollider(p);
      }
    }
    for (const key of this.activeCells) {
      if (!want.has(key)) {
        const list = this.cells.get(key);
        if (list) for (const p of list) this.dropCollider(p);
      }
    }
    this.activeCells = want;
  }

  private damageProp(p: Prop, amount: number, hit: HitInfo) {
    if (!p.alive) return;
    p.hp -= amount;
    this.ctx.fx.impact(hit.point, hit.normal ?? null, COL.spark0, COL.spark1, 0.7);
    if (p.hp <= 0) this.destroy(p, hit);
  }

  /** turn a static instance into a real dynamic rigid body (visual clone + cuboid collider) and launch it */
  private destroy(p: Prop, hit: HitInfo) {
    p.alive = false;
    this.dropCollider(p);
    this.visTimer = 0; // refresh the instance lists next frame (the prop disappears from the instanced mesh)
    const ctx = this.ctx;
    ctx.addScore(SCORE.prop, p.type.burning ? 'VEHICLE DESTROYED' : undefined);
    const group = new THREE.Group();
    for (const part of p.type.parts) {
      const mesh = new THREE.Mesh(part.geometry, part.material);
      part.matrix.decompose(mesh.position, mesh.quaternion, mesh.scale);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    // shift so the group origin is the collider centre
    group.children.forEach((c) => (c.position.y -= p.type.centerY));
    const pos = _p.set(0, p.type.centerY, 0).applyAxisAngle(AY, p.yaw).add(p.pos).clone();
    const quat = new THREE.Quaternion().setFromAxisAngle(AY, p.yaw);
    const dir = hit.dir ? hit.dir.clone() : new THREE.Vector3(rand(-1, 1), 0.3, rand(-1, 1));
    const away = pos.clone().sub(hit.point).setY(0);
    if (away.lengthSq() > 0.01) away.normalize();
    const kick = (hit.kick ?? 5) * 0.8 + 4;
    const vel = dir.multiplyScalar(0.4).addScaledVector(away, kick).add(new THREE.Vector3(0, rand(3, 9), 0));
    ctx.debris.add({
      mesh: group,
      pos,
      quat,
      half: p.type.half,
      vel,
      ang: new THREE.Vector3(rand(-4, 4), rand(-3, 3), rand(-4, 4)),
      mass: p.type.mass,
      life: p.type.burning ? 14 : 9,
      smoke: p.type.burning,
    });
    if (p.type.burning) {
      ctx.fx.explosion(pos, 0.9, { smoke: true });
      ctx.audio.explosion(0.8, pos);
    } else {
      ctx.fx.sparks(pos, null, 10, 20);
    }
  }

  /** area damage (explosions) */
  blast(center: THREE.Vector3, radius: number, damage: number, kick: number) {
    const R = Math.ceil(radius / CELL) + 1;
    const cx0 = Math.floor(center.x / CELL);
    const cz0 = Math.floor(center.z / CELL);
    for (let dx = -R; dx <= R; dx++) {
      for (let dz = -R; dz <= R; dz++) {
        const list = this.cells.get((cx0 + dx + 200) * 1000 + (cz0 + dz + 200));
        if (!list) continue;
        for (const p of list) {
          if (!p.alive) continue;
          const d = _p.copy(p.pos).setY(p.pos.y + p.type.centerY).distanceTo(center);
          if (d > radius) continue;
          const f = Math.pow(1 - d / radius, 1.1);
          const n = _p.clone().sub(center).normalize();
          this.damageProp(p, damage * f * 1.1, { point: center.clone(), normal: n.clone(), dir: n.clone(), source: 'explosion', kick: kick * f });
        }
      }
    }
  }

  /** bring every destroyed prop back (new mission) */
  reset() {
    for (const p of this.props) {
      p.alive = true;
      p.hp = p.type.hp;
      this.dropCollider(p);
    }
    this.activeCells.clear();
    this.visTimer = 0;
  }

  get destroyed() {
    let n = 0;
    for (const p of this.props) if (!p.alive) n++;
    return n;
  }
}
