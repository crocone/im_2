import * as THREE from 'three';
import { SCORE } from '../config';
import { RAPIER, MASKS, Owner } from '../physics/world';
import type { GameCtx, HitInfo } from '../game/types';
import { AssetKey } from '../assets/loader';
import { collectParts } from './city';
import { COL } from '../fx/effects';
import { rand } from '../core/rng';
import { prepareMeshes } from '../assets/loader';

export type DestructKind = 'column' | 'citysign' | 'watertower' | 'smallbuilding';

interface Def {
  intact: AssetKey;
  fractured: AssetKey;
  intactNode: string;
  fracturedNode: string;
  hp: number;
  dust: number;
  sparks: boolean;
  density: number;
}

const DEFS: Record<DestructKind, Def> = {
  column: { intact: 'destructible_column_intact', fractured: 'destructible_column_fractured', intactNode: 'Column_Intact', fracturedNode: 'Column_Fractured', hp: 150, dust: 9, sparks: false, density: 0.55 },
  citysign: { intact: 'destructible_citysign_intact', fractured: 'destructible_citysign_fractured', intactNode: 'CitySign_Intact', fracturedNode: 'CitySign_Fractured', hp: 110, dust: 4, sparks: true, density: 0.4 },
  watertower: { intact: 'destructible_watertower_intact', fractured: 'destructible_watertower_fractured', intactNode: 'WaterTower_Intact', fracturedNode: 'WaterTower_Fractured', hp: 230, dust: 6, sparks: false, density: 0.4 },
  smallbuilding: { intact: 'destructible_smallbuilding_intact', fractured: 'destructible_smallbuilding_fractured', intactNode: 'SmallBuilding_Intact', fracturedNode: 'SmallBuilding_Fractured', hp: 420, dust: 16, sparks: false, density: 0.45 },
};

interface ChunkData {
  node: THREE.Object3D;
  points: Float32Array;
  localPos: THREE.Vector3;
  localQuat: THREE.Quaternion;
  size: number;
}

interface KindData {
  boxes: { center: THREE.Vector3; half: THREE.Vector3 }[];
  chunks: ChunkData[];
  radius: number;
  height: number;
}

const _m = new THREE.Matrix4();
const _v = new THREE.Vector3();
const _q = new THREE.Quaternion();
const AY = new THREE.Vector3(0, 1, 0);

/** One authored destructible object: intact visual + fixed colliders, shattering into real fractured chunks. */
export class Destructible {
  alive = true;
  hp: number;
  readonly maxHp: number;
  readonly owner: Owner;
  readonly colliders: RAPIER.Collider[] = [];
  readonly center = new THREE.Vector3();
  private flash = 0;

  constructor(
    private mgr: DestructibleManager,
    readonly kind: DestructKind,
    readonly pos: THREE.Vector3,
    readonly rotQ: number,
    readonly visual: THREE.Object3D,
    readonly radius: number,
    height: number,
  ) {
    this.def = DEFS[kind];
    this.hp = this.maxHp = this.def.hp;
    this.owner = { kind: 'destructible', ref: this };
    this.center.copy(pos).setY(pos.y + height / 2);
  }
  private def: Def;

  takeDamage(amount: number, hit: HitInfo) {
    if (!this.alive) return;
    this.hp -= amount;
    this.flash = 1;
    const fx = this.mgr.ctx.fx;
    fx.impact(hit.point, hit.normal ?? null, this.def.sparks ? COL.cyan : COL.spark0, this.def.sparks ? COL.cyanDim : COL.spark1, 0.7);
    if (this.hp <= 0) this.shatter(hit);
  }

  shatter(hit?: HitInfo) {
    if (!this.alive) return;
    this.alive = false;
    this.mgr.shatter(this, hit);
  }

  update(dt: number) {
    if (this.flash > 0) this.flash = Math.max(0, this.flash - dt * 5);
  }
}

export class DestructibleManager {
  readonly items: Destructible[] = [];
  private data = new Map<DestructKind, KindData>();

  constructor(readonly ctx: GameCtx) {}

  private kindData(kind: DestructKind): KindData {
    let d = this.data.get(kind);
    if (d) return d;
    const def = DEFS[kind];
    const intact = this.ctx.assets.get(def.intact).scene;
    const { boxes } = collectParts(intact, def.intactNode);
    const ib = new THREE.Box3().setFromObject(this.ctx.assets.node(def.intact, def.intactNode));
    const fracRoot = this.ctx.assets.node(def.fractured, def.fracturedNode);
    fracRoot.updateMatrixWorld(true);
    const rootInv = new THREE.Matrix4().copy(fracRoot.matrixWorld).invert();
    const chunks: ChunkData[] = [];
    for (const child of fracRoot.children) {
      if (!child.name.startsWith('chunk_')) continue;
      child.updateMatrixWorld(true);
      // vertices of all meshes inside this chunk, expressed in the chunk node's local frame
      const chunkInv = new THREE.Matrix4().copy(child.matrixWorld).invert();
      const pts: number[] = [];
      const box = new THREE.Box3();
      child.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh) return;
        const pos = mesh.geometry.attributes.position;
        _m.multiplyMatrices(chunkInv, mesh.matrixWorld);
        for (let i = 0; i < pos.count; i++) {
          _v.fromBufferAttribute(pos, i).applyMatrix4(_m);
          pts.push(_v.x, _v.y, _v.z);
          box.expandByPoint(_v);
        }
      });
      const rel = new THREE.Matrix4().multiplyMatrices(rootInv, child.matrixWorld);
      const p = new THREE.Vector3();
      const q = new THREE.Quaternion();
      const s = new THREE.Vector3();
      rel.decompose(p, q, s);
      chunks.push({ node: child, points: new Float32Array(pts), localPos: p, localQuat: q, size: box.getSize(new THREE.Vector3()).length() });
    }
    if (chunks.length < 6) throw new Error(`${def.fractured} has too few chunk_* children`);
    d = { boxes, chunks, radius: Math.max(ib.max.x - ib.min.x, ib.max.z - ib.min.z) / 2, height: ib.max.y - ib.min.y };
    this.data.set(kind, d);
    return d;
  }

  place(kind: DestructKind, pos: THREE.Vector3, quarterTurns = 0) {
    const def = DEFS[kind];
    const data = this.kindData(kind);
    const visual = this.ctx.assets.cloneNode(def.intact, def.intactNode);
    prepareMeshes(visual, { cast: true, receive: true, envIntensity: 0.9 });
    // the COL_ helper empties are not renderable but keep them out of the way
    visual.traverse((o) => {
      if (o.name.startsWith('COL_')) o.visible = false;
    });
    visual.position.copy(pos);
    visual.rotation.y = (quarterTurns * Math.PI) / 2;
    this.ctx.scene.add(visual);
    const item = new Destructible(this, kind, pos.clone(), quarterTurns, visual, data.radius, data.height);
    const rotM = new THREE.Matrix4().makeRotationY((quarterTurns * Math.PI) / 2);
    const swap = quarterTurns % 2 === 1;
    for (const b of data.boxes) {
      _v.copy(b.center).applyMatrix4(rotM).add(pos);
      const hx = swap ? b.half.z : b.half.x;
      const hz = swap ? b.half.x : b.half.z;
      const cd = RAPIER.ColliderDesc.cuboid(hx, b.half.y, hz).setTranslation(_v.x, _v.y, _v.z).setCollisionGroups(MASKS.world | 0).setFriction(0.6);
      // destructibles are shootable: give them the enemy-like category so player projectiles/rays hit them
      cd.setCollisionGroups(MASKS.world);
      item.colliders.push(this.ctx.physics.addCollider(cd, undefined, item.owner));
    }
    this.items.push(item);
    return item;
  }

  /** Replace an intact object by its fractured chunks (real bodies + convex hull colliders). */
  shatter(item: Destructible, hit?: HitInfo) {
    const ctx = this.ctx;
    const def = DEFS[item.kind];
    const data = this.kindData(item.kind);
    for (const c of item.colliders) ctx.physics.removeCollider(c);
    item.colliders.length = 0;
    ctx.scene.remove(item.visual);
    ctx.addScore(SCORE.destructible, `${item.kind.toUpperCase()} DESTROYED`);

    const yaw = (item.rotQ * Math.PI) / 2;
    const yawQ = new THREE.Quaternion().setFromAxisAngle(AY, yaw);
    const origin = hit?.point ?? item.center;
    const centre = item.center;
    for (const ch of data.chunks) {
      const mesh = ch.node.clone(true);
      mesh.position.set(0, 0, 0);
      mesh.quaternion.identity();
      mesh.scale.set(1, 1, 1);
      prepareMeshes(mesh, { cast: true, receive: true, envIntensity: 0.9 });
      const wp = ch.localPos.clone().applyQuaternion(yawQ).add(item.pos);
      const wq = yawQ.clone().multiply(ch.localQuat);
      // velocity: outward from the impact point with a bias away from the object centre, plus a little lift
      const out = _v.copy(wp).sub(origin);
      if (out.lengthSq() < 0.01) out.set(rand(-1, 1), 0.2, rand(-1, 1));
      out.normalize();
      const away = wp.clone().sub(centre).setY(0).normalize();
      const kick = (hit?.kick ?? 4) * 0.4 + 5;
      const sp = rand(0.35, 1.0) * kick;
      const vel = out.multiplyScalar(sp).addScaledVector(away, rand(0.5, 3)).add(new THREE.Vector3(0, rand(1, 5), 0));
      if (hit?.dir) vel.addScaledVector(hit.dir, rand(1, 4));
      ctx.debris.add({
        mesh,
        pos: wp,
        quat: wq,
        points: ch.points,
        vel,
        ang: new THREE.Vector3(rand(-5, 5), rand(-5, 5), rand(-5, 5)),
        density: def.density,
        life: rand(14, 22),
      });
    }
    // effects
    const p = item.center.clone();
    ctx.fx.dust(item.pos.clone().setY(item.pos.y + 1), data.radius * 1.4, def.dust);
    ctx.fx.explosion(p, 0.9 + data.radius * 0.12, { smoke: false, color: def.sparks ? 'cyan' : 'fire', light: true });
    ctx.audio.explosion(1.1 + data.radius * 0.05, p);
    ctx.shake(0.35, p);
    // splash: neighbours are shaken/damaged a little (chain reactions look great)
    this.blast(p, data.radius + 6, 40, 4, item);
    const idx = this.items.indexOf(item);
    if (idx >= 0) this.items.splice(idx, 1);
  }

  /** area damage from explosions (missiles, dying enemies, boss beam) */
  blast(pos: THREE.Vector3, radius: number, damage: number, kick: number, except?: Destructible) {
    for (let i = this.items.length - 1; i >= 0; i--) {
      const d = this.items[i];
      if (!d.alive || d === except) continue;
      const dist = d.center.distanceTo(pos) - d.radius * 0.6;
      if (dist > radius) continue;
      const f = Math.pow(1 - Math.max(0, dist) / radius, 1.2);
      d.takeDamage(damage * f, { point: pos.clone(), normal: _v.copy(d.center).sub(pos).normalize().clone(), dir: _v.clone(), source: 'explosion', kick });
    }
  }

  private visTimer = 0;

  update(dt: number, camPos?: THREE.Vector3) {
    for (const d of this.items) d.update(dt);
    // distance visibility: destructibles far away are not drawn at all
    this.visTimer -= dt;
    if (camPos && this.visTimer <= 0) {
      this.visTimer = 0.5;
      for (const d of this.items) d.visual.visible = d.pos.distanceTo(camPos) < 560;
    }
  }

  get remaining() {
    return this.items.length;
  }

  clear() {
    for (const d of this.items) {
      for (const c of d.colliders) this.ctx.physics.removeCollider(c);
      this.ctx.scene.remove(d.visual);
    }
    this.items.length = 0;
  }
}
