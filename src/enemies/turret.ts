import * as THREE from 'three';
import { SCORE, TURRET } from '../config';
import { RAPIER, MASKS, G, Owner } from '../physics/world';
import type { GameCtx, HitInfo, Target } from '../game/types';
import { StateMachine } from './fsm';
import { clamp, wrapPi } from '../core/math';
import { rand } from '../core/rng';
import { COL } from '../fx/effects';
import { indexNodes, prepareMeshes } from '../assets/loader';
import type { MissileSpec } from '../weapons/projectiles';

let nextId = 5000;

export const TURRET_MISSILE: MissileSpec = {
  team: 'enemy',
  asset: 'missile',
  rootName: 'Missile',
  speed: TURRET.missileSpeed,
  launchSpeed: 22,
  accel: TURRET.missileAccel,
  turnRate: TURRET.missileTurn,
  arcTime: 0.25,
  blendTime: 0.5,
  proximity: 3.0,
  damage: TURRET.missileDamage,
  radius: TURRET.missileRadius,
  kick: 12,
  life: TURRET.missileLife,
  collideRadius: 0.8,
  trailScale: 0.9,
  explosionScale: 1.05,
  source: 'enemyMissile',
  fireColor: 'fire',
  spin: 4,
};

const _v = new THREE.Vector3();
const _v2 = new THREE.Vector3();
const _v3 = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _qi = new THREE.Quaternion();

/**
 * Rooftop missile turret. Yaw/pitch assemblies rotate toward the (predicted) player with finite turn rates - the very same
 * angles drive the visual nodes (Turret_Yaw about Y, Turret_Pitch about X) and the launch directions of the tube mouths.
 * FSM: dormant -> track -> fire (salvo) -> cooldown -> track ... -> dead
 */
export class Turret implements Target {
  readonly id = nextId++;
  readonly kind = 'turret' as const;
  readonly label = 'MISSILE TURRET';
  alive = true;
  hp = TURRET.hp;
  readonly maxHp = TURRET.hp;
  readonly radius = 2.0;
  readonly pos = new THREE.Vector3();
  readonly vel = new THREE.Vector3();
  readonly root = new THREE.Group();
  private model: THREE.Object3D;
  private yawNode: THREE.Object3D;
  private pitchNode: THREE.Object3D;
  private sensor: THREE.Object3D | null;
  private muzzles: THREE.Object3D[];
  private mats: THREE.MeshStandardMaterial[] = [];
  private baseEmissive: number[] = [];
  private yaw = 0;
  private pitch = 0;
  private pivot = new THREE.Vector3();
  private hitFlash = 0;
  private cooldown = rand(1, 3);
  private salvoLeft = 0;
  private salvoTimer = 0;
  private muzzleIdx = 0;
  private smokeT = 0;
  private recoil = 0;
  private scan = rand(0, 6.28);
  body!: RAPIER.RigidBody;
  collider!: RAPIER.Collider;
  readonly owner: Owner = { kind: 'enemy', ref: this };
  readonly fsm: StateMachine<Turret>;
  private burnT = 0;

  constructor(private ctx: GameCtx, base: THREE.Vector3, yawRot: number) {
    this.model = ctx.assets.cloneNode('turret', 'Turret');
    prepareMeshes(this.model, { cast: true, receive: true, envIntensity: 1.1 });
    const n = indexNodes(this.model);
    this.yawNode = n.Turret_Yaw;
    this.pitchNode = n.Turret_Pitch;
    this.sensor = n.Turret_Sensor ?? null;
    this.muzzles = [n.Muzzle_1, n.Muzzle_2, n.Muzzle_3, n.Muzzle_4];
    const cloned = new Map<THREE.Material, THREE.MeshStandardMaterial>();
    this.model.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const arr = Array.isArray(m.material) ? m.material : [m.material];
      const out = arr.map((mat) => {
        let c = cloned.get(mat);
        if (!c) {
          c = (mat as THREE.MeshStandardMaterial).clone();
          cloned.set(mat, c);
          this.mats.push(c);
          this.baseEmissive.push(c.emissiveIntensity);
        }
        return c;
      });
      m.material = Array.isArray(m.material) ? out : out[0];
    });
    this.root.add(this.model);
    this.root.position.copy(base);
    this.root.rotation.y = yawRot;
    ctx.scene.add(this.root);
    this.root.updateMatrixWorld(true);
    this.yawNode.getWorldPosition(this.pivot);
    this.pos.copy(this.pivot);

    // fixed body with a box collider around the pedestal + head
    const desc = RAPIER.RigidBodyDesc.fixed().setTranslation(base.x, base.y + 1.4, base.z);
    this.body = ctx.physics.createBody(desc);
    const cd = RAPIER.ColliderDesc.cuboid(1.3, 1.5, 1.3).setCollisionGroups(MASKS.world | 0).setRestitution(0.1);
    // turrets are shootable enemies: use the enemy group, but never move
    cd.setCollisionGroups(MASKS.enemy);
    this.collider = ctx.physics.addCollider(cd, this.body, this.owner);
    void G;

    this.fsm = new StateMachine<Turret>(this)
      .add({ name: 'dormant', update: (t, dt) => t.updateDormant(dt) })
      .add({ name: 'track', update: (t, dt) => t.updateTrack(dt) })
      .add({ name: 'fire', enter: (t) => t.startSalvo(), update: (t, dt) => t.updateFire(dt) })
      .add({ name: 'cooldown', enter: (t) => (t.cooldown = rand(TURRET.cooldown[0], TURRET.cooldown[1])), update: (t, dt) => t.updateCooldown(dt) })
      .add({ name: 'dead', enter: (t) => t.onDead(), update: (t, dt) => t.updateDead(dt) });
    this.fsm.set('dormant');
  }

  // ---------------------------------------------------------------- Target
  healthFraction() {
    return clamp(this.hp / this.maxHp, 0, 1);
  }
  shieldFraction() {
    return -1;
  }
  kick() {
    /* fixed */
  }

  takeDamage(amount: number, hit: HitInfo) {
    if (!this.alive) return;
    this.hp -= amount;
    this.hitFlash = 1;
    this.ctx.fx.impact(hit.point, hit.normal ?? null, COL.spark0, COL.spark1, 0.8);
    if (this.fsm.is('dormant')) this.fsm.go('track');
    if (this.hp <= 0) {
      this.alive = false;
      this.ctx.addScore(SCORE.turret, 'TURRET DESTROYED');
      this.ctx.bus.emit('enemyKilled', { kind: 'turret', pos: this.pos.clone() });
      this.ctx.pickups.maybeDrop(this.pos, 0.85);
      this.fsm.set('dead');
    }
  }

  // ---------------------------------------------------------------- aiming
  /** rotate yaw/pitch toward the point `aim`; returns the remaining angular error (radians) */
  private aimAt(aim: THREE.Vector3, dt: number) {
    // aim point expressed in the turret root's local frame
    _qi.copy(this.root.quaternion).invert();
    _v.copy(aim).sub(this.pivot).applyQuaternion(_qi);
    const yawDes = Math.atan2(-_v.x, -_v.z);
    const pitchDes = clamp(Math.atan2(_v.y, Math.hypot(_v.x, _v.z)), -0.12, 1.45);
    const dyaw = wrapPi(yawDes - this.yaw);
    const dpitch = pitchDes - this.pitch;
    this.yaw += clamp(dyaw, -TURRET.yawRate * dt, TURRET.yawRate * dt);
    this.pitch += clamp(dpitch, -TURRET.pitchRate * dt, TURRET.pitchRate * dt);
    this.applyRotation();
    return Math.hypot(dyaw, dpitch);
  }

  private applyRotation() {
    this.yawNode.rotation.y = this.yaw;
    this.pitchNode.rotation.x = this.pitch;
    this.root.updateMatrixWorld(true);
  }

  private predicted(out: THREE.Vector3, missileSpeed: number) {
    const p = this.ctx.player;
    const d = this.pivot.distanceTo(p.pos);
    return out.copy(p.pos).addScaledVector(p.vel, clamp(d / missileSpeed, 0, 2.5) * 0.6);
  }

  private playerInRange() {
    const p = this.ctx.player;
    if (!p.alive) return false;
    const d = this.pivot.distanceTo(p.pos);
    return d < TURRET.range && d > TURRET.minRange;
  }

  private hasLos() {
    const m = this.muzzles[0];
    m.getWorldPosition(_v3);
    return !this.ctx.physics.blocked(_v3, this.ctx.player.pos, G.WORLD);
  }

  // ---------------------------------------------------------------- states
  private updateDormant(dt: number) {
    // idle scan: slow sweep
    this.scan += dt * 0.5;
    this.yaw += Math.sin(this.scan) * dt * 0.35;
    this.pitch = damp0(this.pitch, 0.12, dt);
    this.applyRotation();
    if (this.ctx.enemies.bossJamming) return;
    if (this.playerInRange() && this.pivot.distanceTo(this.ctx.player.pos) < TURRET.range * 0.85) this.fsm.go('track');
  }

  private updateTrack(dt: number) {
    if (this.ctx.enemies.bossJamming) return this.fsm.go('dormant');
    if (!this.playerInRange()) {
      if (!this.ctx.player.alive || this.fsm.timeInState > 4) return this.fsm.go('dormant');
    }
    const aim = this.predicted(_v2, TURRET.missileSpeed);
    const err = this.aimAt(aim, dt);
    this.cooldown -= dt;
    if (this.cooldown <= 0 && err < TURRET.alignCone && this.playerInRange() && this.hasLos() && this.ctx.enemies.requestTurretSalvo()) this.fsm.go('fire');
  }

  private startSalvo() {
    this.salvoLeft = TURRET.salvo;
    this.salvoTimer = 0.35; // wind-up
    this.ctx.audio.enemyMissile(this.pivot);
  }

  private updateFire(dt: number) {
    const aim = this.predicted(_v2, TURRET.missileSpeed);
    this.aimAt(aim, dt);
    this.salvoTimer -= dt;
    if (this.salvoTimer <= 0 && this.salvoLeft > 0) {
      this.launch();
      this.salvoLeft--;
      this.salvoTimer = TURRET.salvoGap;
    }
    if (this.salvoLeft <= 0 && this.salvoTimer <= 0.05) this.fsm.go('cooldown');
  }

  private launch() {
    const m = this.muzzles[this.muzzleIdx++ % this.muzzles.length];
    m.getWorldPosition(_v);
    _q.identity();
    m.getWorldQuaternion(_q);
    _v3.set(0, 0, -1).applyQuaternion(_q);
    this.ctx.projectiles.spawnMissile(TURRET_MISSILE, _v, _v3, this.vel, this.ctx.player, this);
    this.ctx.fx.muzzleFlash(_v, _v3, 1.6, COL.red);
    this.ctx.fx.smokePuff(_v, _v2.copy(_v3).multiplyScalar(3), 1.6, 1.4, false, 0.6);
    this.ctx.fx.lights.flash(_v, 0xff6633, 700, 0.12, 40);
    this.ctx.audio.enemyMissile(_v);
    this.recoil = 1;
  }

  private updateCooldown(dt: number) {
    this.cooldown -= dt;
    const aim = this.predicted(_v2, TURRET.missileSpeed);
    if (this.playerInRange()) this.aimAt(aim, dt * 0.6);
    if (this.cooldown <= 0) this.fsm.go(this.playerInRange() ? 'track' : 'dormant');
  }

  private onDead() {
    const p = this.pivot;
    this.ctx.explode({ pos: p.clone(), radius: 8, damage: 12, kick: 8, team: 'enemy', scale: 1.5, source: 'explosion', ignore: this });
    this.ctx.world.destructibles.blast(p, 9, 60, 10);
    this.yawNode.visible = false;
    // the pedestal keeps burning
    this.mats.forEach((m, i) => {
      m.color.multiplyScalar(0.35);
      this.baseEmissive[i] = 0;
      m.emissiveIntensity = 0;
    });
    this.collider.setEnabled(false);
    this.ctx.physics.unregister(this.collider);
    this.burnT = 22;
  }

  private updateDead(dt: number) {
    this.burnT -= dt;
    this.smokeT += dt;
    if (this.smokeT > 0.12 && this.burnT > 0) {
      this.smokeT = 0;
      _v.copy(this.root.position).setY(this.root.position.y + 1.4);
      this.ctx.fx.smokePuff(_v, null, 1.8, 2.6, true, 0.6, 1.2);
      if (Math.random() < 0.5) this.ctx.fx.glow(_v, 1.6, 0.25, COL.fire0, 0.7);
    }
  }

  // ---------------------------------------------------------------- per frame
  preStep(dt: number) {
    this.fsm.update(dt);
  }

  syncVisual(dt: number) {
    if (this.recoil > 0) {
      this.recoil = Math.max(0, this.recoil - dt * 5);
      this.pitchNode.position.z = this.recoil * 0.22;
    } else if (this.pitchNode.position.z !== 0) this.pitchNode.position.z = 0;
    this.hitFlash = Math.max(0, this.hitFlash - dt * 6);
    const tracking = this.ctx.enemies.bossJamming ? 0.25 : this.fsm.is('track') || this.fsm.is('fire') ? 1.6 : 1;
    for (let i = 0; i < this.mats.length; i++) {
      const m = this.mats[i];
      const base = this.baseEmissive[i];
      if (base > 0) m.emissiveIntensity = base * tracking + this.hitFlash * 3;
      else if (this.hitFlash > 0.01) {
        m.emissive.setRGB(1, 0.85, 0.7);
        m.emissiveIntensity = this.hitFlash * 1.5;
      } else if (m.emissiveIntensity !== 0 && this.alive) m.emissiveIntensity = 0;
    }
    if (this.alive && this.hp < this.maxHp * 0.45 && Math.random() < 0.15) {
      this.pivot.y += 0; // keep TS happy about unused
      this.ctx.fx.smokePuff(_v.copy(this.pivot).add(_v2.set(rand(-0.6, 0.6), 0.4, rand(-0.6, 0.6))), null, 0.9, 1.5, true, 0.5, 1.0);
    }
    void this.sensor;
  }

  postStep() {
    /* static */
  }

  dispose() {
    this.ctx.scene.remove(this.root);
    this.ctx.physics.removeBody(this.body);
    for (const m of this.mats) m.dispose();
  }
}

function damp0(a: number, b: number, dt: number) {
  return a + (b - a) * (1 - Math.exp(-2 * dt));
}
