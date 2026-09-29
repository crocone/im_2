import RAPIER from '@dimforge/rapier3d-compat';
import * as THREE from 'three';
import { PHYS } from '../config';

export { RAPIER };

/** Collision categories. Rapier interaction groups = (memberships << 16) | filter. */
export const G = {
  WORLD: 1 << 0,
  PLAYER: 1 << 1,
  ENEMY: 1 << 2,
  PROJ_PLAYER: 1 << 3,
  PROJ_ENEMY: 1 << 4,
  DEBRIS: 1 << 5,
  PICKUP: 1 << 6,
  SHIELD: 1 << 7,
} as const;

/** Build an interaction-group word for a collider. */
export const gg = (member: number, filter: number) => (((member & 0xffff) << 16) | (filter & 0xffff)) >>> 0;
/** Query filter: matches every collider whose category is in `mask`. */
export const qg = (mask: number) => ((0xffff << 16) | (mask & 0xffff)) >>> 0;

export const MASKS = {
  world: gg(G.WORLD, G.PLAYER | G.ENEMY | G.PROJ_PLAYER | G.PROJ_ENEMY | G.DEBRIS),
  player: gg(G.PLAYER, G.WORLD | G.ENEMY | G.PROJ_ENEMY | G.DEBRIS | G.PICKUP | G.SHIELD),
  enemy: gg(G.ENEMY, G.WORLD | G.PLAYER | G.PROJ_PLAYER | G.ENEMY | G.DEBRIS),
  shield: gg(G.SHIELD, G.PLAYER | G.PROJ_PLAYER),
  projPlayer: gg(G.PROJ_PLAYER, G.WORLD | G.ENEMY | G.SHIELD | G.PROJ_ENEMY),
  projEnemy: gg(G.PROJ_ENEMY, G.WORLD | G.PLAYER | G.PROJ_PLAYER),
  debris: gg(G.DEBRIS, G.WORLD | G.PLAYER | G.ENEMY),
  pickup: gg(G.PICKUP, G.PLAYER),
};

export type OwnerKind =
  | 'world'
  | 'player'
  | 'enemy'
  | 'shield'
  | 'projectile'
  | 'debris'
  | 'destructible'
  | 'prop'
  | 'pickup';

export interface Owner {
  kind: OwnerKind;
  /** the gameplay object (Enemy, Destructible, Projectile ...) */
  ref?: unknown;
}

export interface RayHit {
  collider: RAPIER.Collider;
  owner: Owner | undefined;
  point: THREE.Vector3;
  normal: THREE.Vector3;
  distance: number;
}

export type Vec3 = { x: number; y: number; z: number };

const IDENT_ROT = { x: 0, y: 0, z: 0, w: 1 };

export class Physics {
  world!: RAPIER.World;
  events!: RAPIER.EventQueue;
  private owners = new Map<number, Owner>();
  private contactHandlers: Array<(a: Owner | undefined, b: Owner | undefined, ha: number, hb: number) => void> = [];
  readonly ballCache = new Map<number, RAPIER.Ball>();

  static async create(): Promise<Physics> {
    await RAPIER.init();
    const p = new Physics();
    p.world = new RAPIER.World({ x: 0, y: -PHYS.gravity, z: 0 });
    p.world.timestep = PHYS.dt;
    p.events = new RAPIER.EventQueue(true);
    return p;
  }

  register(collider: RAPIER.Collider, owner: Owner) {
    this.owners.set(collider.handle, owner);
    return collider;
  }
  unregister(collider: RAPIER.Collider) {
    this.owners.delete(collider.handle);
  }
  ownerOf(collider: RAPIER.Collider | number): Owner | undefined {
    return this.owners.get(typeof collider === 'number' ? collider : collider.handle);
  }

  onContact(fn: (a: Owner | undefined, b: Owner | undefined, ha: number, hb: number) => void) {
    this.contactHandlers.push(fn);
  }

  createBody(desc: RAPIER.RigidBodyDesc) {
    return this.world.createRigidBody(desc);
  }

  addCollider(desc: RAPIER.ColliderDesc, body: RAPIER.RigidBody | undefined, owner: Owner) {
    const c = this.world.createCollider(desc, body);
    this.owners.set(c.handle, owner);
    return c;
  }

  removeBody(body: RAPIER.RigidBody) {
    for (let i = 0; i < body.numColliders(); i++) this.owners.delete(body.collider(i).handle);
    this.world.removeRigidBody(body);
  }

  removeCollider(c: RAPIER.Collider) {
    this.owners.delete(c.handle);
    this.world.removeCollider(c, true);
  }

  step() {
    this.world.step(this.events);
    this.events.drainCollisionEvents((h1, h2, started) => {
      if (!started) return;
      const a = this.owners.get(h1);
      const b = this.owners.get(h2);
      for (const fn of this.contactHandlers) fn(a, b, h1, h2);
    });
  }

  /** Closest ray hit against colliders in `mask` (see G). */
  raycast(
    origin: Vec3,
    dir: Vec3,
    maxDist: number,
    mask: number,
    exclude?: RAPIER.Collider,
    excludeBody?: RAPIER.RigidBody,
    solid = true,
  ): RayHit | null {
    const ray = new RAPIER.Ray({ x: origin.x, y: origin.y, z: origin.z }, { x: dir.x, y: dir.y, z: dir.z });
    const hit = this.world.castRayAndGetNormal(ray, maxDist, solid, undefined, qg(mask), exclude, excludeBody);
    if (!hit) return null;
    const t = hit.timeOfImpact;
    return {
      collider: hit.collider,
      owner: this.owners.get(hit.collider.handle),
      point: new THREE.Vector3(origin.x + dir.x * t, origin.y + dir.y * t, origin.z + dir.z * t),
      normal: new THREE.Vector3(hit.normal.x, hit.normal.y, hit.normal.z),
      distance: t,
    };
  }

  /** Cheap boolean: is anything in `mask` between a and b? */
  blocked(a: Vec3, b: Vec3, mask: number, exclude?: RAPIER.Collider): boolean {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dz = b.z - a.z;
    const len = Math.hypot(dx, dy, dz);
    if (len < 1e-4) return false;
    const ray = new RAPIER.Ray({ x: a.x, y: a.y, z: a.z }, { x: dx / len, y: dy / len, z: dz / len });
    const hit = this.world.castRay(ray, len, true, undefined, qg(mask), exclude);
    return hit !== null;
  }

  ball(radius: number) {
    // quantise to 5 cm so the cache stays small
    const key = Math.round(radius * 20);
    let b = this.ballCache.get(key);
    if (!b) {
      b = new RAPIER.Ball(key / 20);
      this.ballCache.set(key, b);
    }
    return b;
  }

  /** Visit every collider (in `mask`) overlapping a sphere. Callback returns false to stop. */
  overlapSphere(center: Vec3, radius: number, mask: number, cb: (c: RAPIER.Collider, owner: Owner | undefined) => boolean | void) {
    this.world.intersectionsWithShape(
      center,
      IDENT_ROT,
      this.ball(radius),
      (c) => cb(c, this.owners.get(c.handle)) !== false,
      undefined,
      qg(mask),
    );
  }

  /** Sweep a sphere from a along dir. Returns hit distance and normal or null. */
  sphereCast(origin: Vec3, dir: Vec3, dist: number, radius: number, mask: number, exclude?: RAPIER.Collider) {
    const hit = this.world.castShape(
      origin,
      IDENT_ROT,
      dir,
      this.ball(radius),
      0,
      dist,
      true,
      undefined,
      qg(mask),
      exclude,
    );
    if (!hit) return null;
    return { distance: hit.time_of_impact, normal: new THREE.Vector3(hit.normal1.x, hit.normal1.y, hit.normal1.z), collider: hit.collider };
  }
}

export const tmpV = { x: 0, y: 0, z: 0 };
