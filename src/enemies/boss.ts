import * as THREE from 'three';
import { BOSS, SCORE } from '../config';
import { RAPIER, MASKS, G, Owner } from '../physics/world';
import type { GameCtx, HitInfo, Target } from '../game/types';
import { StateMachine } from './fsm';
import { clamp, damp, wrapPi } from '../core/math';
import { rand } from '../core/rng';
import { COL } from '../fx/effects';
import { indexNodes, prepareMeshes } from '../assets/loader';
import type { BoltSpec, MissileSpec } from '../weapons/projectiles';
import { ShieldFx } from '../fx/shield';

let nextId = 9000;

const BOSS_MISSILE: MissileSpec = {
  team: 'enemy',
  asset: 'missile',
  rootName: 'Missile',
  speed: 74,
  launchSpeed: 20,
  accel: 52,
  turnRate: 1.35,
  arcTime: 0.45,
  blendTime: 0.5,
  proximity: 3.2,
  damage: 10,
  radius: 7,
  kick: 14,
  life: 7.5,
  collideRadius: 0.8,
  trailScale: 1.1,
  explosionScale: 1.2,
  source: 'enemyMissile',
  fireColor: 'fire',
  spin: 4,
};

const BOSS_BOLT: BoltSpec = { speed: 88, damage: 5.5, life: 3.5, color: 'plasma', radius: 0.4, size: 0.85 };

const _v = new THREE.Vector3();
const _v2 = new THREE.Vector3();
const _v3 = new THREE.Vector3();
const _q = new THREE.Quaternion();
const UP = new THREE.Vector3(0, 1, 0);

type AttackType = 'missiles' | 'plasma' | 'shockwave' | 'beam';

interface Attack {
  type: AttackType;
  t: number;
  n: number;
  dur: number;
}

/** Owner of the shield collider: routes hits/impacts to the boss shield. */
class ShieldRef {
  alive = true;
  constructor(private boss: Boss) {}
  takeDamage(amount: number, hit: HitInfo) {
    this.boss.damageShield(amount, hit);
  }
}

/**
 * The Armored Behemoth: hovering boss with an energy shield (separate mesh + collider) that pulses, flashes on hits,
 * flickers when weak and dissolves when broken; then the hull/core is vulnerable.
 * FSM: entering -> shielded <-> vulnerable -> (enraged) -> dying
 */
export class Boss implements Target {
  readonly id = nextId++;
  readonly kind = 'boss' as const;
  readonly label = 'ARMORED BEHEMOTH';
  alive = true;
  hull = BOSS.hullHp;
  readonly hullMax = BOSS.hullHp;
  shield = BOSS.shieldHp;
  readonly shieldMax = BOSS.shieldHp;
  shieldUp = true;
  enraged = false;
  readonly radius = BOSS.shieldRadius;
  readonly pos = new THREE.Vector3();
  readonly vel = new THREE.Vector3();
  private prevPos = new THREE.Vector3();
  readonly root = new THREE.Group();
  private model: THREE.Object3D;
  private nodes: Record<string, THREE.Object3D>;
  private hardpoints: THREE.Object3D[] = [];
  private nozzles: THREE.Object3D[] = [];
  private core: THREE.Object3D;
  private coreMats: THREE.MeshStandardMaterial[] = [];
  private coreBase: number[] = [];
  private mats: THREE.MeshStandardMaterial[] = [];
  private baseEmissive: number[] = [];
  private shieldFx: ShieldFx;
  private shieldOwner = new ShieldRef(this);
  private shieldCollider!: RAPIER.Collider;
  body!: RAPIER.RigidBody;
  hullCollider!: RAPIER.Collider;
  readonly owner: Owner = { kind: 'enemy', ref: this };
  readonly fsm: StateMachine<Boss>;

  private yaw = 0;
  private home = new THREE.Vector3(0, BOSS.altitude, 0);
  private orbit = rand(0, 6.28);
  private attack: Attack | null = null;
  private attackCd = 4;
  private hitFlash = 0;
  private vulnTimer = 0;
  private regenCount = 0;
  private dyingT = 0;
  private time = 0;
  private beamDir = new THREE.Vector3(0, 0, -1);
  private beamTick = 0;
  private charge = 0;
  private lastMsg = '';
  private ramCooldown = 0;

  constructor(private ctx: GameCtx, home: THREE.Vector3) {
    this.home.copy(home).setY(BOSS.altitude);
    this.model = ctx.assets.cloneNode('boss', 'Boss');
    prepareMeshes(this.model, { cast: true, receive: true, envIntensity: 1.2 });
    this.nodes = indexNodes(this.model);
    this.hardpoints = ['Hardpoint_L1', 'Hardpoint_R1', 'Hardpoint_L2', 'Hardpoint_R2', 'Hardpoint_L3', 'Hardpoint_R3'].map((k) => this.nodes[k]);
    this.nozzles = ['Nozzle_1', 'Nozzle_2', 'Nozzle_3', 'Nozzle_4'].map((k) => this.nodes[k]);
    this.core = this.nodes.Boss_Core;

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
          if (c.name.startsWith('glow_core')) {
            this.coreMats.push(c);
            this.coreBase.push(c.emissiveIntensity);
          }
        }
        return c;
      });
      m.material = Array.isArray(m.material) ? out : out[0];
    });
    this.root.add(this.model);

    // shield: separate mesh from boss_shield.glb, driven by a custom shader
    const shieldGeo = (ctx.assets.node('boss_shield', 'BossShield') as THREE.Mesh).geometry;
    this.shieldFx = new ShieldFx(shieldGeo, BOSS.shieldRadius);
    this.root.add(this.shieldFx.mesh);

    // start high above the arena
    const start = this.home.clone().setY(BOSS.altitude + 190);
    this.pos.copy(start);
    this.prevPos.copy(start);
    this.root.position.copy(start);
    ctx.scene.add(this.root);

    const desc = RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(start.x, start.y, start.z)
      .lockRotations()
      .setGravityScale(0)
      .setLinearDamping(0)
      .setCanSleep(false)
      .setAdditionalMass(9000);
    this.body = ctx.physics.createBody(desc);
    // hull: torso + two arm blobs
    const hull = (r: number, x: number, y: number, z: number) => {
      const cd = RAPIER.ColliderDesc.ball(r).setTranslation(x, y, z).setCollisionGroups(MASKS.enemy).setRestitution(0.2);
      return ctx.physics.addCollider(cd, this.body, this.owner);
    };
    this.hullCollider = hull(BOSS.hullRadius, 0, 0, 0);
    hull(1.9, 3.5, -0.2, 0);
    hull(1.9, -3.5, -0.2, 0);
    hull(1.6, 0, -1.6, 1.2);
    // shield: solid sphere the player/missiles/repulsor rays bounce off
    const sd = RAPIER.ColliderDesc.ball(BOSS.shieldRadius).setCollisionGroups(MASKS.shield).setRestitution(0.35).setFriction(0);
    this.shieldCollider = ctx.physics.addCollider(sd, this.body, { kind: 'shield', ref: this.shieldOwner });

    this.fsm = new StateMachine<Boss>(this)
      .add({ name: 'entering', enter: (b) => b.onEnter(), update: (b, dt, t) => b.updateEntering(dt, t) })
      .add({ name: 'shielded', enter: (b) => b.say('SHIELD ONLINE'), update: (b, dt) => b.updateCombat(dt, false) })
      .add({ name: 'vulnerable', enter: (b) => b.onVulnerable(), update: (b, dt) => b.updateCombat(dt, true) })
      .add({ name: 'dying', enter: (b) => b.onDying(), update: (b, dt) => b.updateDying(dt) });
    this.fsm.set('entering');
  }

  // ---------------------------------------------------------------- Target
  healthFraction() {
    return clamp(this.hull / this.hullMax, 0, 1);
  }
  shieldFraction() {
    return this.shieldUp ? clamp(this.shield / this.shieldMax, 0, 1) : 0;
  }
  kick() {
    /* far too heavy */
  }

  private say(text: string) {
    if (text === this.lastMsg) return;
    this.lastMsg = text;
    this.ctx.bus.emit('bossState', { text });
  }

  // ---------------------------------------------------------------- damage
  takeDamage(amount: number, hit: HitInfo) {
    if (!this.alive || this.fsm.is('entering') || this.fsm.is('dying')) return;
    if (this.shieldUp) {
      this.damageShield(amount, hit);
      return;
    }
    // the exposed core is the weak point: repulsor beams do extra damage to it
    this.hull -= hit.source === 'repulsor' ? amount * 1.8 : amount;
    this.hitFlash = 1;
    this.ctx.fx.impact(hit.point, hit.normal ?? null, COL.spark0, COL.spark1, 1.1);
    if (!this.enraged && this.hull < this.hullMax * 0.35) this.enrage();
    if (this.hull <= 0) this.fsm.go('dying');
  }

  damageShield(amount: number, hit: HitInfo) {
    if (!this.shieldUp || !this.alive || this.fsm.is('entering') || this.fsm.is('dying')) return;
    this.shield -= amount;
    this.root.updateMatrixWorld(true);
    this.shieldFx.hit(hit.point, hit.source === 'repulsor' ? 0.12 : 0.5);
    this.shieldFx.setIntegrity(clamp(this.shield / this.shieldMax, 0, 1));
    this.ctx.audio.shieldHit(hit.point);
    this.ctx.fx.particles.add.emit({ x: hit.point.x, y: hit.point.y, z: hit.point.z, life: 0.16, size0: 1.4, size1: 0.4, c0: COL.cyan, c1: COL.cyanDim, a0: 0.8, a1: 0 });
    if (this.shield <= 0) this.breakShield();
  }

  private breakShield() {
    this.shieldUp = false;
    this.shield = 0;
    this.shieldCollider.setEnabled(false);
    this.shieldFx.startBreak();
    this.ctx.audio.shieldBreak(this.pos);
    this.ctx.shake(1.0, this.pos);
    this.ctx.fx.explosion(this.pos.clone(), 3.2, { color: 'cyan', smoke: false });
    this.ctx.fx.shockwave(this.pos, 40, COL.cyan, 0.9);
    // the collapsing shield shakes loose supply canisters (ammo / armour depending on what the player needs)
    this.ctx.pickups.drop(_v.copy(this.pos).setY(this.pos.y - 4), 3);
    this.attack = null;
    this.fsm.go('vulnerable');
  }

  private enrage() {
    this.enraged = true;
    this.say('BEHEMOTH ENRAGED - CORE OVERLOAD');
    this.ctx.audio.bossRoar(this.pos);
    this.ctx.shake(0.8);
  }

  // ---------------------------------------------------------------- states
  private onEnter() {
    this.say('ARMORED BEHEMOTH INBOUND');
    this.ctx.audio.bossRoar(this.pos);
    this.ctx.audio.setMusicIntensity(1);
  }

  private updateEntering(dt: number, t: number) {
    // slow controlled descent to the arena
    _v.copy(this.home);
    this.moveToward(_v, 34, dt, 0.8);
    this.faceTarget(dt, 0.6);
    if (t > 3 && this.pos.y < BOSS.altitude + 12) this.fsm.go('shielded');
  }

  private onVulnerable() {
    this.vulnTimer = BOSS.vulnerableTime;
    this.say(this.enraged ? 'SHIELD DOWN - FINISH IT!' : 'SHIELD BROKEN - ATTACK THE CORE!');
    this.ctx.bus.emit('message', { text: 'SHIELD BROKEN - HIT THE CORE', kind: 'good', time: 2.5 });
    this.attackCd = 2.0;
  }

  private onDying() {
    this.alive = false;
    this.attack = null;
    this.dyingT = 0;
    this.say('BEHEMOTH DESTROYED');
    this.ctx.addScore(BOSS.score, 'BEHEMOTH DESTROYED');
    this.ctx.bus.emit('enemyKilled', { kind: 'boss', pos: this.pos.clone() });
    this.hullCollider.setCollisionGroups(0);
    this.body.setGravityScale(0.35, true);
  }

  private updateDying(dt: number) {
    this.dyingT += dt;
    // chain of explosions across the hull while it falls
    if (Math.random() < dt * 9) {
      _v.set(rand(-4, 4), rand(-3, 4), rand(-3, 3)).applyQuaternion(this.root.quaternion).add(this.pos);
      this.ctx.fx.explosion(_v, rand(1.2, 2.4));
      this.ctx.audio.explosion(1.6, _v);
      this.ctx.shake(0.5, _v);
    }
    const t = this.body.translation();
    this.pos.set(t.x, t.y, t.z);
    if (this.dyingT > 4.2) {
      this.ctx.explode({ pos: this.pos.clone(), radius: 40, damage: 30, kick: 30, team: 'enemy', scale: 6, source: 'explosion', ignore: this });
      this.ctx.fx.shockwave(this.pos, 90, COL.amber, 1.2);
      this.ctx.pickups.drop(this.pos, 6);
      this.ctx.bus.emit('victory', {});
      this.dispose();
    }
  }

  // ---------------------------------------------------------------- combat
  private updateCombat(dt: number, vulnerable: boolean) {
    const p = this.ctx.player;
    // regen / vulnerability window
    if (vulnerable) {
      this.vulnTimer -= dt;
      if (this.vulnTimer <= 0 && !this.enraged && this.regenCount < 2) {
        this.regenCount++;
        this.shieldUp = true;
        this.shield = this.shieldMax * 0.35;
        this.shieldCollider.setEnabled(true);
        this.shieldFx.regenerate();
        this.shieldFx.setIntegrity(0.35);
        this.ctx.audio.shieldUp(this.pos);
        this.fsm.go('shielded');
        return;
      }
    }

    // ---- movement: drift toward the player's side of the arena, keep height, orbit slowly
    this.orbit += BOSS.orbitSpeed * dt * (this.enraged ? 1.6 : 1);
    const toP = _v.copy(p.pos).sub(this.home).setY(0);
    const lim = 110;
    if (toP.length() > lim) toP.setLength(lim);
    _v2.copy(this.home).addScaledVector(toP, 0.55);
    _v2.x += Math.cos(this.orbit) * 46;
    _v2.z += Math.sin(this.orbit) * 46;
    _v2.y = BOSS.altitude + Math.sin(this.time * 0.35) * 9;
    this.moveToward(_v2, vulnerable ? 12 : this.enraged ? 30 : 22, dt, 0.9);
    this.faceTarget(dt, this.enraged ? 1.3 : 0.9);

    // ---- attacks
    if (this.attack) this.updateAttack(dt);
    else if (p.alive) {
      this.attackCd -= dt;
      if (this.attackCd <= 0) this.pickAttack();
    }

    // ---- shield contact: ramming into the dome hurts and pushes the suit away
    this.ramCooldown -= dt;
    if (this.shieldUp && p.alive && this.ramCooldown <= 0) {
      const d = this.pos.distanceTo(p.pos);
      if (d < BOSS.shieldRadius + 1.4) {
        this.ramCooldown = 0.6;
        _v3.copy(p.pos).sub(this.pos).normalize();
        p.kick(_v3, 22);
        p.takeDamage(4, { point: p.pos.clone(), dir: _v3.clone(), source: 'explosion' });
        this.shieldFx.hit(p.pos, 0.4);
        this.ctx.audio.shieldHit(p.pos);
      }
    }
  }

  private pickAttack() {
    const p = this.ctx.player;
    const d = this.pos.distanceTo(p.pos);
    const w: [AttackType, number][] = [
      ['missiles', 3],
      ['plasma', 3],
      ['shockwave', d < BOSS.shieldRadius + 28 ? 4 : 0.6],
    ];
    if (this.enraged) w.push(['beam', 2.6]);
    let sum = 0;
    for (const [, k] of w) sum += k;
    let r = rand(0, sum);
    let type: AttackType = 'missiles';
    for (const [t, k] of w) {
      if ((r -= k) <= 0) {
        type = t;
        break;
      }
    }
    if (this.attack === null && type === this.lastAttack) {
      type = w[(w.findIndex((x) => x[0] === type) + 1) % w.length][0];
    }
    this.lastAttack = type;
    const dur: Record<AttackType, number> = { missiles: 2.4, plasma: 2.6, shockwave: 1.5, beam: 3.6 };
    this.attack = { type, t: 0, n: 0, dur: dur[type] };
    if (type === 'beam') {
      this.say('CORE BEAM CHARGING');
      this.ctx.bus.emit('message', { text: 'WARNING - CORE BEAM', kind: 'warn', time: 2 });
      this.ctx.audio.warning();
      this.beamDir.copy(this.ctx.player.pos).sub(this.pos).normalize();
    }
  }
  private lastAttack: AttackType | null = null;

  private updateAttack(dt: number) {
    const a = this.attack!;
    a.t += dt;
    const p = this.ctx.player;
    if (a.type === 'missiles') {
      const total = this.enraged ? 6 : 5;
      const gap = 0.36;
      while (a.n < total && a.t >= 0.5 + a.n * gap) {
        this.fireMissile(a.n);
        a.n++;
      }
    } else if (a.type === 'plasma') {
      const volleys = this.enraged ? 4 : 3;
      while (a.n < volleys && a.t >= 0.5 + a.n * 0.65) {
        this.fireVolley(a.n);
        a.n++;
      }
    } else if (a.type === 'shockwave') {
      if (a.n === 0 && a.t > 0.05) {
        a.n = 1;
        this.ctx.fx.shockwave(this.pos, 30, COL.cyan, 1.1);
        this.ctx.audio.warning();
      }
      if (a.n === 1 && a.t > 1.15) {
        a.n = 2;
        this.ctx.fx.shockwave(this.pos, 62, COL.white, 0.55);
        this.ctx.fx.explosion(this.pos.clone(), 2.6, { color: 'cyan', smoke: false, light: true });
        this.ctx.audio.explosion(2, this.pos);
        this.ctx.shake(0.7, this.pos);
        if (p.alive) {
          const d = this.pos.distanceTo(p.pos);
          if (d < 62) {
            _v3.copy(p.pos).sub(this.pos).normalize();
            p.kick(_v3, 60 * (1 - d / 80));
            if (d < 48) p.takeDamage(10 * (1 - d / 62) + 3, { point: p.pos.clone(), dir: _v3.clone(), source: 'explosion' });
          }
        }
      }
    } else if (a.type === 'beam') {
      this.updateBeam(dt, a);
    }
    if (a.t >= a.dur) {
      this.attack = null;
      this.charge = 0;
      this.attackCd = this.enraged ? rand(2.0, 3.2) : rand(3.2, 5.0);
      this.say(this.shieldUp ? 'SHIELD ONLINE' : 'CORE EXPOSED');
    }
  }

  private fireMissile(i: number) {
    const hp = this.hardpoints[i % this.hardpoints.length];
    hp.getWorldPosition(_v);
    hp.getWorldQuaternion(_q);
    _v2.set(0, 0, -1).applyQuaternion(_q);
    // arc up and out so the salvo blooms before it homes in
    _v2.y += 0.35;
    _v2.x += rand(-0.25, 0.25);
    _v2.normalize();
    this.ctx.projectiles.spawnMissile(BOSS_MISSILE, _v, _v2, this.vel, this.ctx.player, this);
    this.ctx.fx.muzzleFlash(_v, _v2, 2.2, COL.plasma);
    this.ctx.fx.smokePuff(_v, _v2.clone().multiplyScalar(4), 2.2, 1.6, false, 0.6);
    this.ctx.audio.enemyMissile(_v);
  }

  private fireVolley(v: number) {
    const p = this.ctx.player;
    const n = 5;
    for (let i = 0; i < n; i++) {
      const hp = this.hardpoints[(i + v) % this.hardpoints.length];
      hp.getWorldPosition(_v);
      const dist = _v.distanceTo(p.pos);
      _v2.copy(p.pos).addScaledVector(p.vel, clamp(dist / BOSS_BOLT.speed, 0, 2) * 0.9).sub(_v).normalize();
      const fan = (i - (n - 1) / 2) * 0.07;
      _v2.applyAxisAngle(UP, fan);
      _v2.y += rand(-0.02, 0.02);
      _v2.normalize();
      this.ctx.projectiles.spawnBolt(BOSS_BOLT, _v, _v2);
      this.ctx.fx.muzzleFlash(_v, _v2, 1.6, COL.plasma);
    }
    this.ctx.audio.enemyFire(this.pos);
  }

  private updateBeam(dt: number, a: Attack) {
    const p = this.ctx.player;
    this.core.getWorldPosition(_v);
    const CHARGE = 1.8;
    if (a.t < CHARGE) {
      this.charge = a.t / CHARGE;
      // charging: particles converge on the core, telegraph line toward the target
      for (let i = 0; i < 2; i++) {
        _v2.set(rand(-1, 1), rand(-1, 1), rand(-1, 1)).normalize().multiplyScalar(rand(4, 8));
        this.ctx.fx.particles.add.emit({
          x: _v.x + _v2.x, y: _v.y + _v2.y, z: _v.z + _v2.z, vx: -_v2.x * 3.5, vy: -_v2.y * 3.5, vz: -_v2.z * 3.5,
          life: 0.32, size0: 0.9, size1: 0.2, c0: COL.amber, c1: COL.red, a0: 0.9, a1: 0, stretch: 1.2,
        });
      }
      this.beamDir.lerp(_v2.copy(p.pos).sub(_v).normalize(), 1 - Math.exp(-3 * dt)).normalize();
      _v3.copy(_v).addScaledVector(this.beamDir, 200);
      this.ctx.fx.beam(_v, _v3, COL.redDim, 0.25, 0.05);
      return;
    }
    // firing: the beam slowly tracks the player
    const track = this.enraged ? 0.8 : 0.55;
    _v2.copy(p.pos).sub(_v).normalize();
    // rotate toward the player at a limited rate
    const ang = Math.acos(clamp(this.beamDir.dot(_v2), -1, 1));
    if (ang > 1e-3) this.beamDir.lerp(_v2, Math.min(1, (track * dt) / ang)).normalize();
    const hit = this.ctx.physics.raycast(_v, this.beamDir, 420, G.WORLD | G.PLAYER, undefined);
    const end = hit ? hit.point : _v3.copy(_v).addScaledVector(this.beamDir, 420);
    this.ctx.fx.beam(_v, end, COL.amber, 3.4, 0.07);
    this.ctx.fx.beam(_v, end, COL.white, 1.3, 0.07);
    if (hit) this.ctx.fx.impact(hit.point, hit.normal, COL.amber, COL.fire1, 1.6);
    this.ctx.shake(0.06);
    this.beamTick -= dt;
    if (hit?.owner?.kind === 'player' && this.beamTick <= 0) {
      this.beamTick = 0.12;
      p.takeDamage(4.2, { point: hit.point.clone(), dir: this.beamDir.clone(), source: 'beam', kick: 1.2 });
    }
    // the beam scours the city too
    if (hit && hit.owner?.kind !== 'player' && Math.random() < dt * 8) {
      this.ctx.world.destructibles.blast(hit.point, 8, 80, 12);
    }
  }

  // ---------------------------------------------------------------- movement
  private moveToward(target: THREE.Vector3, speed: number, dt: number, accel: number) {
    _v3.copy(target).sub(this.pos);
    const dist = _v3.length();
    if (dist > 1e-3) _v3.multiplyScalar(1 / dist);
    const want = _v3.multiplyScalar(speed * clamp(dist / 30, 0.15, 1));
    this.vel.lerp(want, 1 - Math.exp(-accel * dt));
    this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
  }

  private faceTarget(dt: number, rate: number) {
    const p = this.ctx.player;
    _v.copy(p.pos).sub(this.pos);
    const want = Math.atan2(-_v.x, -_v.z);
    this.yaw += clamp(wrapPi(want - this.yaw), -rate * dt, rate * dt);
    _q.setFromAxisAngle(UP, this.yaw);
    this.body.setRotation({ x: _q.x, y: _q.y, z: _q.z, w: _q.w }, true);
  }

  // ---------------------------------------------------------------- per frame
  preStep(dt: number) {
    if (!this.root.parent) return;
    this.time += dt;
    if (this.alive) this.fsm.update(dt);
    else this.fsm.update(dt);
  }

  postStep() {
    if (!this.root.parent) return;
    this.prevPos.copy(this.pos);
    const t = this.body.translation();
    this.pos.set(t.x, t.y, t.z);
    const v = this.body.linvel();
    this.vel.set(v.x, v.y, v.z);
  }

  syncVisual(dt: number, alpha: number) {
    if (!this.root.parent) return;
    this.root.position.lerpVectors(this.prevPos, this.pos, alpha);
    this.root.rotation.set(clamp(this.vel.y * 0.004, -0.15, 0.15), this.yaw, clamp(-this.vel.x * 0.003, -0.15, 0.15), 'YXZ');
    this.root.updateMatrixWorld(true);
    this.shieldFx.update(dt, this.time);
    // idle motion of the heavy arms
    const t = this.time;
    if (this.nodes.Boss_Arm_L) this.nodes.Boss_Arm_L.rotation.x = Math.sin(t * 0.7) * 0.05 + (this.attack?.type === 'missiles' ? -0.25 : 0);
    if (this.nodes.Boss_Arm_R) this.nodes.Boss_Arm_R.rotation.x = Math.sin(t * 0.7 + 1.5) * 0.05 + (this.attack?.type === 'missiles' ? -0.25 : 0);
    if (this.nodes.Boss_Forearm_L) this.nodes.Boss_Forearm_L.rotation.x = Math.sin(t * 0.9 + 0.5) * 0.06;
    if (this.nodes.Boss_Forearm_R) this.nodes.Boss_Forearm_R.rotation.x = Math.sin(t * 0.9 + 2.0) * 0.06;
    // glow: core pulses, brighter when exposed / charging
    this.hitFlash = Math.max(0, this.hitFlash - dt * 6);
    const exposed = !this.shieldUp ? 1.7 : 1;
    const pulse = 0.85 + 0.25 * Math.sin(t * (this.enraged ? 9 : 3.2));
    for (let i = 0; i < this.coreMats.length; i++) {
      this.coreMats[i].emissiveIntensity = this.coreBase[i] * exposed * pulse * (1 + this.charge * 1.6) + this.hitFlash * 5;
    }
    // thrusters
    if (this.alive || this.dyingT < 3) {
      const power = 0.7 + clamp(this.vel.length() / 30, 0, 0.6) + (this.enraged ? 0.3 : 0);
      for (const nz of this.nozzles) {
        nz.getWorldPosition(_v);
        _q.identity();
        nz.getWorldQuaternion(_q);
        _v2.set(0, 0, -1).applyQuaternion(_q);
        this.ctx.fx.flame(_v, _v2, power, COL.red, COL.redDim, 0.95, this.vel);
        if (Math.random() < 0.25) this.ctx.fx.flame(_v, _v2, power, COL.amber, COL.redDim, 1.3, this.vel);
      }
    }
    void damp;
  }

  dispose() {
    this.alive = false;
    this.ctx.scene.remove(this.root);
    this.ctx.physics.removeBody(this.body);
    for (const m of this.mats) m.dispose();
  }

  get removed() {
    return !this.root.parent;
  }
}
