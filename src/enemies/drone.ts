import * as THREE from 'three';
import { DRONE, SCORE } from '../config';
import { RAPIER, MASKS, G, Owner } from '../physics/world';
import type { GameCtx, HitInfo, Target } from '../game/types';
import { StateMachine } from './fsm';
import { clamp, damp, quatLookDir, wrapPi } from '../core/math';
import { rand } from '../core/rng';
import { COL } from '../fx/effects';
import { indexNodes, prepareMeshes } from '../assets/loader';
import type { BoltSpec } from '../weapons/projectiles';

const _v = new THREE.Vector3();
const _v2 = new THREE.Vector3();
const _v3 = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _des = new THREE.Vector3();
const _avoid = new THREE.Vector3();

let nextId = 1;
const BOLT: BoltSpec = { speed: DRONE.boltSpeed, damage: DRONE.boltDamage, life: 2.6, color: 'red', radius: 0.2, size: 0.32 };

/**
 * Aerial combat drone. Rapier dynamic ball body steered by forces/velocity, finite state machine AI:
 *   patrol -> chase -> attack (circle-strafe + burst fire) -> evade (missile dodge) -> wreck (falls, explodes)
 */
export class Drone implements Target {
  readonly id = nextId++;
  readonly kind = 'drone' as const;
  readonly label = 'DRONE';
  alive = true;
  hp = DRONE.hp;
  readonly maxHp = DRONE.hp;
  readonly radius = 1.0;
  readonly pos = new THREE.Vector3();
  readonly vel = new THREE.Vector3();
  private prevPos = new THREE.Vector3();
  readonly root = new THREE.Group();
  private model: THREE.Object3D;
  private rotors: THREE.Object3D[] = [];
  private muzzles: THREE.Object3D[] = [];
  private sensor: THREE.Object3D | null = null;
  private mats: THREE.MeshStandardMaterial[] = [];
  private baseEmissive: number[] = [];
  body!: RAPIER.RigidBody;
  collider!: RAPIER.Collider;
  readonly owner: Owner = { kind: 'enemy', ref: this };
  readonly fsm: StateMachine<Drone>;

  // AI state
  private patrolCenter = new THREE.Vector3();
  private waypoint = new THREE.Vector3();
  private orbitAngle = rand(0, 6.28);
  private orbitDir = rand(0, 1) < 0.5 ? -1 : 1;
  private orbitRadius = rand(34, 56);
  private orbitAlt = rand(-6, 14);
  private fireTimer = rand(0.5, 1.8);
  private burstLeft = 0;
  private burstTimer = 0;
  private muzzleIdx = 0;
  private evadeCd = rand(0, 2);
  private evadeDir = new THREE.Vector3();
  private face = new THREE.Vector3(0, 0, -1);
  private bank = 0;
  private hitFlash = 0;
  private spin = rand(0, 6);
  private wreckSpin = new THREE.Vector3();
  private wreckT = 0;
  private smokeT = 0;
  private aggressive = false;
  private seed = rand(0, 100);

  constructor(private ctx: GameCtx, spawn: THREE.Vector3, aggressive = false) {
    this.aggressive = aggressive;
    this.pos.copy(spawn);
    this.prevPos.copy(spawn);
    this.patrolCenter.copy(spawn);
    this.waypoint.copy(spawn);

    this.model = ctx.assets.cloneNode('drone', 'Drone');
    prepareMeshes(this.model, { cast: true, receive: true, envIntensity: 1.1 });
    const n = indexNodes(this.model);
    this.rotors = ['Drone_Rotor_FL', 'Drone_Rotor_FR', 'Drone_Rotor_RL', 'Drone_Rotor_RR'].map((k) => n[k]);
    this.muzzles = [n.Muzzle_L, n.Muzzle_R];
    this.sensor = n.Drone_Sensor ?? null;
    // per-drone materials so hit flashes do not bleed across the fleet
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
    this.root.position.copy(spawn);
    ctx.scene.add(this.root);

    const desc = RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(spawn.x, spawn.y, spawn.z)
      .lockRotations()
      .setGravityScale(0)
      .setLinearDamping(0.05)
      .setCanSleep(false)
      .setAdditionalMass(DRONE.mass);
    this.body = ctx.physics.createBody(desc);
    const cd = RAPIER.ColliderDesc.ball(DRONE.radius)
      .setCollisionGroups(MASKS.enemy)
      .setRestitution(0.3)
      .setDensity(1);
    this.collider = ctx.physics.addCollider(cd, this.body, this.owner);

    this.fsm = new StateMachine<Drone>(this)
      .add({
        name: 'patrol',
        enter: (d) => d.pickWaypoint(),
        update: (d, dt) => d.updatePatrol(dt),
      })
      .add({
        name: 'chase',
        update: (d, dt) => d.updateChase(dt),
      })
      .add({
        name: 'attack',
        enter: (d) => {
          d.fireTimer = rand(0.4, 1.2);
          d.orbitDir = rand(0, 1) < 0.5 ? -1 : 1;
          d.orbitAngle = Math.atan2(d.pos.z - d.ctx.player.pos.z, d.pos.x - d.ctx.player.pos.x);
        },
        update: (d, dt) => d.updateAttack(dt),
      })
      .add({
        name: 'evade',
        enter: (d) => d.startEvade(),
        update: (d, dt, t) => d.updateEvade(dt, t),
      })
      .add({
        name: 'wreck',
        enter: (d) => d.startWreck(),
        update: (d, dt) => d.updateWreck(dt),
      });
    this.fsm.set(aggressive ? 'chase' : 'patrol');
  }

  // ------------------------------------------------------------------ Target
  healthFraction() {
    return clamp(this.hp / this.maxHp, 0, 1);
  }
  shieldFraction() {
    return -1;
  }
  kick(dir: THREE.Vector3, speed: number) {
    if (!this.alive && !this.fsm.is('wreck')) return;
    this.vel.addScaledVector(dir, speed);
    this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
  }

  takeDamage(amount: number, hit: HitInfo) {
    if (!this.alive) return;
    this.hp -= amount;
    this.hitFlash = 1;
    if (hit.kick) this.kick(hit.dir ?? _v3.set(0, 0, 0), hit.kick * 0.5);
    // getting shot wakes the drone up and may trigger a dodge
    if (this.fsm.is('patrol')) this.fsm.go('chase');
    if (this.hp <= 0) this.die(hit);
  }

  private die(hit: HitInfo) {
    this.alive = false;
    this.ctx.addScore(SCORE.drone, 'DRONE DESTROYED');
    this.ctx.bus.emit('enemyKilled', { kind: 'drone', pos: this.pos.clone() });
    // the Behemoth's escorts carry supplies: more drops while the boss is up
    this.ctx.pickups.maybeDrop(this.pos, this.ctx.enemies.bossJamming ? 0.6 : undefined);
    this.ctx.fx.impact(this.pos, hit.normal ?? null, COL.spark0, COL.spark1, 1.6);
    this.fsm.set('wreck');
  }

  // ------------------------------------------------------------------ helpers
  private get player() {
    return this.ctx.player;
  }

  private pickWaypoint() {
    const c = this.patrolCenter;
    this.waypoint.set(c.x + rand(-90, 90), clamp(c.y + rand(-12, 18), DRONE.minAlt + 8, DRONE.maxAlt), c.z + rand(-90, 90));
  }

  /** steer toward `dest` at `speed` with building avoidance; returns desired velocity in `_des` */
  private steer(dest: THREE.Vector3, speed: number, dt: number, arrive = 0) {
    _des.copy(dest).sub(this.pos);
    const dist = _des.length();
    if (dist > 1e-3) _des.multiplyScalar(1 / dist);
    let sp = speed;
    if (arrive > 0 && dist < arrive) sp *= clamp(dist / arrive, 0.2, 1);
    _des.multiplyScalar(sp);
    this.avoidObstacles(_des, sp);
    // altitude limits
    if (this.pos.y < DRONE.minAlt) _des.y += (DRONE.minAlt - this.pos.y) * 2.5;
    if (this.pos.y > DRONE.maxAlt) _des.y -= (this.pos.y - DRONE.maxAlt) * 2.5;
    this.accelerateTo(_des, dt);
  }

  private avoidObstacles(des: THREE.Vector3, speed: number) {
    const physics = this.ctx.physics;
    const dir = _v2.copy(this.vel);
    if (dir.lengthSq() < 4) dir.copy(des);
    if (dir.lengthSq() < 1e-4) return;
    dir.normalize();
    const look = 12 + this.vel.length() * 0.9;
    _avoid.set(0, 0, 0);
    // forward + two angled whiskers + downward
    for (const [ax, ay] of [[0, 0], [0.5, 0], [-0.5, 0], [0, -0.45], [0, 0.4]] as const) {
      _v.copy(dir);
      if (ax !== 0) _v.applyAxisAngle(_up, ax);
      if (ay !== 0) _v.y += ay;
      _v.normalize();
      const hit = physics.raycast(this.pos, _v, look, G.WORLD, this.collider);
      if (hit) {
        const w = 1 - hit.distance / look;
        _avoid.addScaledVector(hit.normal, w * w * 3.2);
        _avoid.y += ay < 0 ? w * 1.2 : 0;
      }
    }
    if (_avoid.lengthSq() > 1e-4) des.addScaledVector(_avoid, speed);
  }

  private accelerateTo(des: THREE.Vector3, dt: number) {
    _v3.copy(des).sub(this.vel);
    const maxDv = DRONE.accel * dt;
    const len = _v3.length();
    if (len > maxDv) _v3.multiplyScalar(maxDv / len);
    this.vel.add(_v3);
    this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
  }

  private hasLos() {
    return !this.ctx.physics.blocked(this.pos, this.player.pos, G.WORLD);
  }

  // ------------------------------------------------------------------ states
  private updatePatrol(dt: number) {
    this.steer(this.waypoint, DRONE.patrolSpeed, dt, 8);
    if (this.pos.distanceTo(this.waypoint) < 10) this.pickWaypoint();
    const d = this.pos.distanceTo(this.player.pos);
    if (this.player.alive && (d < DRONE.aggroRange || this.aggressive)) this.fsm.go('chase');
    this.checkThreat();
  }

  private updateChase(dt: number) {
    const p = this.player;
    if (!p.alive) return this.steer(this.patrolCenter, DRONE.patrolSpeed, dt);
    const d = this.pos.distanceTo(p.pos);
    // approach a point a bit above the player so we come in from the front
    _v.copy(p.pos).addScaledVector(p.vel, 0.6).setY(p.pos.y + 4);
    this.steer(_v, DRONE.chaseSpeed, dt, 20);
    if (d < DRONE.attackRange && this.hasLos()) this.fsm.go('attack');
    this.checkThreat();
  }

  private updateAttack(dt: number) {
    const p = this.player;
    if (!p.alive) return this.fsm.go('patrol');
    const d = this.pos.distanceTo(p.pos);
    // circle-strafe around the player
    this.orbitAngle += this.orbitDir * (DRONE.attackSpeed / Math.max(20, this.orbitRadius)) * dt;
    const bob = Math.sin(this.ctx.time * 0.7 + this.seed) * 4;
    _v.set(
      p.pos.x + Math.cos(this.orbitAngle) * this.orbitRadius,
      p.pos.y + this.orbitAlt + bob,
      p.pos.z + Math.sin(this.orbitAngle) * this.orbitRadius,
    );
    this.steer(_v, DRONE.attackSpeed + 6, dt, 6);

    // burst fire with prediction
    this.fireTimer -= dt;
    if (this.burstLeft > 0) {
      this.burstTimer -= dt;
      if (this.burstTimer <= 0) {
        this.fireBolt();
        this.burstLeft--;
        this.burstTimer = DRONE.burstGap;
      }
    } else if (this.fireTimer <= 0 && d < DRONE.attackRange * 1.5 && this.hasLos()) {
      this.burstLeft = DRONE.burst;
      this.burstTimer = 0;
      this.fireTimer = rand(DRONE.fireInterval[0], DRONE.fireInterval[1]);
    }
    if (d > DRONE.attackRange * 1.9 || (!this.hasLos() && this.fsm.timeInState > 3)) this.fsm.go('chase');
    this.checkThreat();
  }

  private fireBolt() {
    const p = this.player;
    const m = this.muzzles[this.muzzleIdx++ % this.muzzles.length];
    m.getWorldPosition(_v);
    // lead the target
    const dist = _v.distanceTo(p.pos);
    const tHit = dist / DRONE.boltSpeed;
    _v2.copy(p.pos).addScaledVector(p.vel, tHit * 0.85);
    _v2.x += rand(-1, 1) * DRONE.spread * dist;
    _v2.y += rand(-1, 1) * DRONE.spread * dist;
    _v2.z += rand(-1, 1) * DRONE.spread * dist;
    _v2.sub(_v).normalize();
    this.ctx.projectiles.spawnBolt(BOLT, _v, _v2);
    this.ctx.fx.muzzleFlash(_v, _v2, 0.8, COL.red);
    this.ctx.audio.enemyFire(_v);
  }

  private checkThreat() {
    this.evadeCd -= 1 / 60;
    if (this.evadeCd > 0 || !this.ctx.player.alive) return;
    const m = this.ctx.projectiles.incomingThreat(this, 55);
    if (m && rand(0, 1) < 0.4) {
      this.fsm.go('evade');
      this.evadeCd = 3.5;
    } else if (m) this.evadeCd = 0.6;
  }

  private startEvade() {
    // dodge perpendicular to the incoming missile's path
    const m = this.ctx.projectiles.incomingThreat(this, 80);
    const from = m ? _v.copy(m.vel).normalize() : _v.copy(this.vel).normalize();
    _v2.set(rand(-1, 1), rand(-0.6, 0.9), rand(-1, 1)).normalize();
    this.evadeDir.copy(_v2).addScaledVector(from, -_v2.dot(from)).normalize();
    if (this.evadeDir.lengthSq() < 0.1) this.evadeDir.set(1, 0.3, 0).normalize();
    this.ctx.fx.glow(this.pos, 2.2, 0.3, COL.amber, 0.7);
    // chaff sparks
    this.ctx.fx.sparks(this.pos, null, 14, 22, COL.amber, COL.fire1, 0.9);
  }

  private updateEvade(dt: number, t: number) {
    _des.copy(this.evadeDir).multiplyScalar(DRONE.evadeSpeed);
    this.avoidObstacles(_des, DRONE.evadeSpeed);
    this.accelerateTo(_des, dt * 2.2);
    if (t > 0.85) this.fsm.go(this.pos.distanceTo(this.player.pos) < DRONE.attackRange ? 'attack' : 'chase');
  }

  private startWreck() {
    this.body.setGravityScale(1, true);
    this.body.setLinearDamping(0.2);
    this.wreckSpin.set(rand(-6, 6), rand(-4, 4), rand(-6, 6));
    this.wreckT = rand(1.1, 1.9);
    this.collider.setCollisionGroups(MASKS.debris);
    this.collider.setActiveEvents(RAPIER.ActiveEvents.COLLISION_EVENTS);
    this.hitFlash = 0;
  }

  private updateWreck(dt: number) {
    this.wreckT -= dt;
    this.smokeT += dt;
    if (this.smokeT > 0.03) {
      this.smokeT = 0;
      this.ctx.fx.smokePuff(this.pos, null, 1.2, 1.6, true, 0.6, 0.4);
      this.ctx.fx.particles.add.emit({ x: this.pos.x, y: this.pos.y, z: this.pos.z, life: 0.25, size0: 0.9, size1: 0.2, c0: COL.fire0, c1: COL.fire1, a0: 0.9, a1: 0 });
    }
    const t = this.body.translation();
    this.pos.set(t.x, t.y, t.z);
    const v = this.body.linvel();
    this.vel.set(v.x, v.y, v.z);
    if (this.wreckT <= 0 || this.pos.y < 1.5) this.explodeWreck();
  }

  private explodeWreck() {
    if (!this.root.parent) return;
    this.ctx.explode({ pos: this.pos.clone(), radius: 6, damage: 9, kick: 6, team: 'enemy', scale: 0.85, source: 'explosion', ignore: this });
    this.dispose();
  }

  // ------------------------------------------------------------------ per frame
  /** fixed step before physics */
  preStep(dt: number) {
    if (!this.root.parent) return;
    this.fsm.update(dt);
    this.evadeCd -= 0; // (timer is advanced in checkThreat)
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
    this.hitFlash = Math.max(0, this.hitFlash - dt * 6);
    const wreck = this.fsm.is('wreck');
    if (wreck) {
      this.model.rotation.x += this.wreckSpin.x * dt;
      this.model.rotation.y += this.wreckSpin.y * dt;
      this.model.rotation.z += this.wreckSpin.z * dt;
    } else {
      // face the player while attacking, otherwise the direction of travel
      const p = this.ctx.player;
      const attacking = this.fsm.is('attack') || this.fsm.is('evade');
      if (attacking && p.alive) _v.copy(p.pos).sub(this.pos);
      else _v.copy(this.vel);
      if (_v.lengthSq() > 0.5) {
        _v.normalize();
        const k = 1 - Math.exp(-6 * dt);
        this.face.lerp(_v, k).normalize();
      }
      quatLookDir(_q, this.face);
      // bank into lateral acceleration, pitch with vertical speed
      const side = _v2.set(this.face.z, 0, -this.face.x); // right vector (horizontal)
      const lat = this.vel.dot(side);
      this.bank = damp(this.bank, clamp(-lat * 0.03, -0.5, 0.5), 5, dt);
      this.model.quaternion.copy(_q);
      this.model.rotateZ(this.bank);
      this.model.rotateX(clamp(this.vel.y * 0.01, -0.3, 0.3));
    }
    // rotors
    this.spin += dt * (wreck ? 40 : 60);
    for (let i = 0; i < this.rotors.length; i++) this.rotors[i].rotation.y = this.spin * (i % 2 ? 1 : -1);
    // sensor / hit flash
    const attackGlow = this.fsm.is('attack') ? 1.5 : 1;
    for (let i = 0; i < this.mats.length; i++) {
      const m = this.mats[i];
      const base = this.baseEmissive[i];
      if (base > 0) m.emissiveIntensity = base * attackGlow * (wreck ? 0.4 + 0.6 * Math.random() : 1) + this.hitFlash * 3;
      else if (this.hitFlash > 0.01) {
        m.emissive.setRGB(1, 0.85, 0.7);
        m.emissiveIntensity = this.hitFlash * 1.6;
      } else if (m.emissiveIntensity !== 0) m.emissiveIntensity = 0;
    }
    // engine exhaust
    if (!wreck && this.ctx.fx) {
      const sp = clamp(this.vel.length() / DRONE.chaseSpeed, 0, 1);
      if (Math.random() < 0.6) {
        _v.copy(this.pos).addScaledVector(this.face, -0.9);
        this.ctx.fx.flame(_v, _v2.copy(this.face).negate(), 0.2 + 0.5 * sp, COL.redDim, COL.redDim, 0.18, this.vel);
      }
    }
    this.mods();
  }

  private mods() {
    void wrapPi;
  }

  dispose() {
    this.alive = false;
    this.ctx.scene.remove(this.root);
    this.ctx.physics.removeBody(this.body);
    for (const m of this.mats) m.dispose();
    this.root.clear();
  }

  get removed() {
    return !this.root.parent;
  }
}

const _up = new THREE.Vector3(0, 1, 0);
