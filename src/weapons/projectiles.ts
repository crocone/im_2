import * as THREE from 'three';
import { RAPIER, MASKS, Owner } from '../physics/world';
import type { GameCtx, HitSource, Trackable } from '../game/types';
import { clamp, quatLookDir, rotateToward, smoothstep } from '../core/math';
import { COL } from '../fx/effects';
import { prepareMeshes } from '../assets/loader';
import { rand } from '../core/rng';

export interface MissileSpec {
  team: 'player' | 'enemy';
  asset: 'missile' | 'mini_missile';
  rootName: 'Missile' | 'MiniMissile';
  speed: number;
  launchSpeed: number;
  accel: number;
  turnRate: number;
  arcTime: number;
  blendTime: number;
  proximity: number;
  damage: number;
  radius: number;
  kick: number;
  life: number;
  collideRadius: number;
  trailScale: number;
  explosionScale: number;
  source: HitSource;
  fireColor: 'fire' | 'plasma';
  spin: number;
}

const _v = new THREE.Vector3();
const _d = new THREE.Vector3();
const _dd = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _qs = new THREE.Quaternion();
const AZ = new THREE.Vector3(0, 0, 1);

/** Homing missile / mini-missile with a Rapier body + ball collider, curved launch arc, finite turn rate. */
export class HomingMissile {
  alive = true;
  readonly pos = new THREE.Vector3();
  readonly vel = new THREE.Vector3();
  private prev = new THREE.Vector3();
  private dir = new THREE.Vector3();
  private speed: number;
  private age = 0;
  private roll = rand(0, 6.28);
  private lastDist = 1e9;
  readonly visual: THREE.Object3D;
  private tailOffset: number;
  body: RAPIER.RigidBody;
  collider: RAPIER.Collider;
  readonly owner: Owner = { kind: 'projectile', ref: this };
  pendingContact: Owner | null | undefined = undefined;
  /** damage flag so player repulsor can shoot down enemy missiles */
  hp = 12;

  constructor(
    private ctx: GameCtx,
    readonly spec: MissileSpec,
    pos: THREE.Vector3,
    launchDir: THREE.Vector3,
    inheritVel: THREE.Vector3,
    public target: Trackable | null,
    readonly shooter: object | null,
  ) {
    this.pos.copy(pos);
    this.prev.copy(pos);
    this.dir.copy(launchDir).normalize();
    this.speed = spec.launchSpeed;
    this.vel.copy(this.dir).multiplyScalar(this.speed).addScaledVector(inheritVel, 0.6);

    const root = ctx.assets.cloneNode(spec.asset, spec.rootName);
    prepareMeshes(root, { cast: false, receive: false, envIntensity: 1.0 });
    this.visual = new THREE.Group();
    this.visual.add(root);
    this.tailOffset = spec.asset === 'missile' ? 0.8 : 0.36;
    ctx.scene.add(this.visual);
    quatLookDir(this.visual.quaternion, this.dir);
    this.visual.position.copy(this.pos);

    const desc = RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(pos.x, pos.y, pos.z)
      .setLinvel(this.vel.x, this.vel.y, this.vel.z)
      .setGravityScale(0)
      .setCcdEnabled(true)
      .setLinearDamping(0)
      .setCanSleep(false);
    this.body = ctx.physics.createBody(desc);
    const cd = RAPIER.ColliderDesc.ball(spec.collideRadius)
      .setCollisionGroups(spec.team === 'player' ? MASKS.projPlayer : MASKS.projEnemy)
      .setActiveEvents(RAPIER.ActiveEvents.COLLISION_EVENTS)
      .setDensity(0.2)
      .setRestitution(0)
      .setFriction(0);
    this.collider = ctx.physics.addCollider(cd, this.body, this.owner);
  }

  /** guidance -> velocity (called before the physics step) */
  preStep(dt: number) {
    if (!this.alive) return;
    this.age += dt;
    const s = this.spec;
    // ---- guidance
    let homing = smoothstep(s.arcTime, s.arcTime + s.blendTime, this.age);
    if (this.target && this.target.alive) {
      // lead the target: solve a first-order intercept with the current closing speed
      _d.copy(this.target.pos).sub(this.pos);
      const dist = _d.length();
      const tLead = clamp(dist / Math.max(30, this.speed), 0, 1.4);
      _dd.copy(this.target.pos).addScaledVector(this.target.vel, tLead * 0.8).sub(this.pos);
      if (_dd.lengthSq() > 1e-4) {
        _dd.normalize();
        // terminal guidance: thrust-vectoring style turn-rate boost when close to the target
        const terminal = 1 + 0.6 * (1 - clamp(dist / 70, 0, 1));
        const maxTurn = s.turnRate * terminal * dt * homing;
        if (maxTurn > 0) rotateToward(this.dir, this.dir, _dd, maxTurn);
      }
      // proximity fuse (only once past the launch arc): direct proximity, or closest-approach detonation on a near miss
      if (this.age > s.arcTime * 0.8) {
        if (dist - 1.0 < s.proximity) this.pendingContact = null;
        else if (dist > this.lastDist && dist < s.proximity * 3.4 && this.lastDist < s.proximity * 3.4) this.pendingContact = null;
      }
      this.lastDist = dist;
    }
    this.speed = Math.min(s.speed, this.speed + s.accel * dt);
    this.vel.copy(this.dir).multiplyScalar(this.speed);
    if (this.age < s.arcTime * 0.9) this.vel.addScaledVector(this.ctx.player.vel, 0.6 * (1 - this.age / (s.arcTime * 0.9)));
    this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
    quatLookDir(_q, this.dir);
    this.body.setRotation({ x: _q.x, y: _q.y, z: _q.z, w: _q.w }, true);
    if (this.age > s.life) this.pendingContact = null;
  }

  postStep(dt: number) {
    if (!this.alive) return;
    this.prev.copy(this.pos);
    const t = this.body.translation();
    this.pos.set(t.x, t.y, t.z);
    this.trailAndGlow(dt);
  }

  private trailAndGlow(dt: number) {
    const fx = this.ctx.fx;
    const seg = _v.copy(this.pos).sub(this.prev);
    const len = seg.length();
    const n = Math.min(7, Math.max(1, Math.ceil(len / (0.55 * (0.5 + this.spec.trailScale * 0.5)))));
    const tail = this.exhaustWorld();
    for (let i = 0; i < n; i++) {
      const k = (i + 0.5) / n;
      _d.copy(tail).addScaledVector(seg, k - 1);
      fx.trail(_d, this.vel, this.spec.trailScale, i === 0);
    }
    // bright exhaust flame
    fx.particles.add.emit({
      x: tail.x, y: tail.y, z: tail.z, life: 0.07, size0: 0.55 * this.spec.trailScale, size1: 0.2 * this.spec.trailScale,
      c0: this.spec.fireColor === 'plasma' ? COL.plasma : this.spec.team === 'enemy' ? COL.red : COL.amber, c1: COL.fire1, a0: 1, a1: 0,
    });
    void dt;
  }

  private exhaustWorld() {
    return _dd.copy(this.pos).addScaledVector(this.dir, -this.tailOffset);
  }

  syncVisual(alpha: number) {
    if (!this.alive) return;
    this.visual.position.lerpVectors(this.prev, this.pos, alpha);
    quatLookDir(_qs, this.dir);
    this.roll += this.spec.spin * 0.016;
    _q.setFromAxisAngle(AZ, this.roll);
    this.visual.quaternion.copy(_qs).multiply(_q);
  }

  /** shot down by repulsor fire */
  takeDamage(amount: number) {
    if (!this.alive || this.spec.team === 'player') return;
    this.hp -= amount;
    if (this.hp <= 0) this.pendingContact = null;
  }

  detonate() {
    if (!this.alive) return;
    this.alive = false;
    const s = this.spec;
    this.ctx.explode({
      pos: this.pos.clone(),
      radius: s.radius,
      damage: s.damage,
      kick: s.kick,
      team: s.team,
      scale: s.explosionScale,
      source: s.source,
      color: s.fireColor,
      ignore: this.shooter ?? undefined,
    });
    this.dispose();
  }

  dispose() {
    this.alive = false;
    this.ctx.scene.remove(this.visual);
    this.ctx.physics.removeBody(this.body);
  }
}

export interface BoltSpec {
  speed: number;
  damage: number;
  life: number;
  color: 'red' | 'plasma';
  radius: number;
  size: number;
}

/** Enemy plasma bolt: small fast Rapier body, rendered as stretched additive particles. */
export class Bolt {
  alive = true;
  readonly pos = new THREE.Vector3();
  readonly vel = new THREE.Vector3();
  private prev = new THREE.Vector3();
  private age = 0;
  body: RAPIER.RigidBody;
  readonly owner: Owner = { kind: 'projectile', ref: this };
  pendingContact: Owner | null | undefined = undefined;
  readonly isBolt = true;

  constructor(private ctx: GameCtx, readonly spec: BoltSpec, pos: THREE.Vector3, dir: THREE.Vector3) {
    this.pos.copy(pos);
    this.prev.copy(pos);
    this.vel.copy(dir).setLength(spec.speed);
    const desc = RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(pos.x, pos.y, pos.z)
      .setLinvel(this.vel.x, this.vel.y, this.vel.z)
      .setGravityScale(0)
      .setCcdEnabled(true)
      .setCanSleep(false);
    this.body = ctx.physics.createBody(desc);
    const cd = RAPIER.ColliderDesc.ball(spec.radius)
      .setCollisionGroups(MASKS.projEnemy)
      .setActiveEvents(RAPIER.ActiveEvents.COLLISION_EVENTS)
      .setDensity(0.05)
      .setRestitution(0);
    ctx.physics.addCollider(cd, this.body, this.owner);
  }

  preStep(dt: number) {
    this.age += dt;
    if (this.age > this.spec.life) this.pendingContact = null;
    this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, false);
  }

  postStep() {
    this.prev.copy(this.pos);
    const t = this.body.translation();
    this.pos.set(t.x, t.y, t.z);
    const fx = this.ctx.fx;
    const c = this.spec.color === 'plasma' ? COL.plasma : COL.red;
    const seg = _v.copy(this.pos).sub(this.prev);
    const n = Math.max(1, Math.min(4, Math.ceil(seg.length() / 1.2)));
    for (let i = 0; i < n; i++) {
      const k = (i + 0.5) / n;
      _d.copy(this.prev).addScaledVector(seg, k);
      fx.particles.add.emit({ x: _d.x, y: _d.y, z: _d.z, vx: this.vel.x, vy: this.vel.y, vz: this.vel.z, life: 0.05, size0: this.spec.size, size1: this.spec.size * 0.6, c0: c, c1: c, a0: 1, a1: 0.4, stretch: 2.4 });
    }
    fx.particles.add.emit({ x: this.pos.x, y: this.pos.y, z: this.pos.z, life: 0.05, size0: this.spec.size * 1.9, size1: this.spec.size, c0: c, c1: c, a0: 0.8, a1: 0 });
  }

  syncVisual() {
    /* particle rendered */
  }

  takeDamage() {
    this.pendingContact = null; // any hit pops the bolt
  }

  dispose() {
    this.alive = false;
    this.ctx.physics.removeBody(this.body);
  }
}

type AnyProjectile = HomingMissile | Bolt;

/** Owns every projectile; routes physics contacts into detonations / damage. */
export class ProjectileManager {
  readonly missiles: HomingMissile[] = [];
  readonly bolts: Bolt[] = [];

  constructor(private ctx: GameCtx) {
    ctx.physics.onContact((a, b) => {
      const pa = a?.kind === 'projectile' ? (a.ref as AnyProjectile) : null;
      const pb = b?.kind === 'projectile' ? (b.ref as AnyProjectile) : null;
      if (pa && pa.alive && pa.pendingContact === undefined) pa.pendingContact = b ?? null;
      if (pb && pb.alive && pb.pendingContact === undefined) pb.pendingContact = a ?? null;
    });
  }

  spawnMissile(spec: MissileSpec, pos: THREE.Vector3, dir: THREE.Vector3, inheritVel: THREE.Vector3, target: Trackable | null, shooter: object | null) {
    const m = new HomingMissile(this.ctx, spec, pos, dir, inheritVel, target, shooter);
    this.missiles.push(m);
    return m;
  }

  spawnBolt(spec: BoltSpec, pos: THREE.Vector3, dir: THREE.Vector3) {
    const b = new Bolt(this.ctx, spec, pos, dir);
    this.bolts.push(b);
    return b;
  }

  preStep(dt: number) {
    for (const m of this.missiles) m.preStep(dt);
    for (const b of this.bolts) b.preStep(dt);
  }

  postStep(dt: number) {
    for (const m of this.missiles) m.postStep(dt);
    for (const b of this.bolts) b.postStep();
    // resolve contacts (after the physics step, safe to mutate the world)
    for (const m of this.missiles) {
      if (m.alive && m.pendingContact !== undefined) m.detonate();
    }
    for (const b of this.bolts) {
      if (!b.alive || b.pendingContact === undefined) continue;
      this.boltHit(b, b.pendingContact);
    }
    for (let i = this.missiles.length - 1; i >= 0; i--) if (!this.missiles[i].alive) this.missiles.splice(i, 1);
    for (let i = this.bolts.length - 1; i >= 0; i--) if (!this.bolts[i].alive) this.bolts.splice(i, 1);
  }

  private boltHit(b: Bolt, other: Owner | null) {
    const ctx = this.ctx;
    const p = b.pos;
    if (other?.kind === 'player') {
      ctx.player.takeDamage(b.spec.damage, { point: p.clone(), dir: b.vel.clone().normalize(), source: 'bolt', kick: 1.5 });
    }
    ctx.fx.impact(p, _v.copy(b.vel).normalize().negate(), b.spec.color === 'plasma' ? COL.plasma : COL.red, COL.redDim, 0.9);
    ctx.audio.impact(p);
    b.dispose();
  }

  syncVisuals(alpha: number) {
    for (const m of this.missiles) m.syncVisual(alpha);
  }

  /** enemies chasing the player call this to know whether a missile is inbound */
  incomingThreat(target: Trackable, range: number): HomingMissile | null {
    let best: HomingMissile | null = null;
    let bestD = range;
    for (const m of this.missiles) {
      if (!m.alive || m.target !== target) continue;
      const d = m.pos.distanceTo(target.pos);
      if (d < bestD) {
        bestD = d;
        best = m;
      }
    }
    return best;
  }

  clear() {
    for (const m of this.missiles) m.dispose();
    for (const b of this.bolts) if (b.alive) b.dispose();
    this.missiles.length = 0;
    this.bolts.length = 0;
  }
}
