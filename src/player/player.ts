import * as THREE from 'three';
import { DIFFICULTY, FLIGHT, PLAYER, WORLD } from '../config';
import { RAPIER, MASKS, G, Owner } from '../physics/world';
import type { GameCtx, HitInfo, Trackable } from '../game/types';
import { ArmorRig, PoseName } from './rig';
import { FlightInput, FlightMode, FlightModel } from './flight';
import { PlayerWeapons } from './weapons';
import { COL } from '../fx/effects';
import { clamp, damp, smoothstep } from '../core/math';
import { rand } from '../core/rng';

const _v = new THREE.Vector3();
const _v2 = new THREE.Vector3();
const _v3 = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _mouse = { x: 0, y: 0 };
const DOWN = { x: 0, y: -1, z: 0 };
const AX = new THREE.Vector3(1, 0, 0);

interface Queued {
  hover: boolean;
  cycle: boolean;
  missile: boolean;
  mini: boolean;
  lock: boolean;
  dual: boolean;
}

/**
 * The armoured hero: Rapier dynamic body (capsule that follows the pose lean), 6-DoF flight model,
 * Blender-authored rig with pose blending, weapons, damage and energy.
 */
export class Player implements Trackable {
  alive = true;
  readonly pos = new THREE.Vector3();
  readonly vel = new THREE.Vector3();
  private prevPos = new THREE.Vector3();
  private prevQuat = new THREE.Quaternion();
  private curQuat = new THREE.Quaternion();
  /** interpolated render transform (camera follows this) */
  readonly renderPos = new THREE.Vector3();
  readonly renderQuat = new THREE.Quaternion();
  readonly root = new THREE.Group();
  readonly rig: ArmorRig;
  readonly flight = new FlightModel();
  readonly weapons: PlayerWeapons;
  readonly owner: Owner = { kind: 'player', ref: this };
  body!: RAPIER.RigidBody;
  collider!: RAPIER.Collider;

  armor = PLAYER.maxArmor;
  energy = PLAYER.maxEnergy;
  private energyDelay = 0;
  private boostLocked = false;
  private wasBoosting = false;
  private flightTipShown = false;
  /** seconds since last damage (HUD flash) */
  damageFlash = 0;
  lastDamageTime = -10;

  private intent = { forward: 0, strafe: 0, vertical: 0, roll: 0, boost: false, fire: false };
  private queued: Queued = { hover: false, cycle: false, missile: false, mini: false, lock: false, dual: false };
  private setVel = new THREE.Vector3();
  private soleOffset = 1.0;
  private lastLean = 0;
  private wantVisual = true;
  outsideBounds = false;
  aimPoint = new THREE.Vector3();
  speed = 0;
  /** spent per frame by the HUD */
  altitude = 0;
  groundDistance = 100;
  private groundTimer = 0;
  private impactCooldown = 0;
  invulnerable = 0;

  constructor(private ctx: GameCtx) {
    this.rig = new ArmorRig(ctx.assets);
    this.root.add(this.rig.root);
    ctx.scene.add(this.root);
    this.weapons = new PlayerWeapons(ctx, this);
    this.measureSole();
    this.createBody(new THREE.Vector3(0, 200, 0));
  }

  private measureSole() {
    this.rig.root.updateMatrixWorld(true);
    const box = new THREE.Box3();
    for (const n of ['Boot_L', 'Boot_R']) box.expandByObject(this.rig.nodes[n]);
    this.soleOffset = clamp(-box.min.y, 0.8, 1.3); // distance from PlayerRoot origin down to the soles at rest
  }

  private createBody(at: THREE.Vector3) {
    const desc = RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(at.x, at.y, at.z)
      .lockRotations()
      .setGravityScale(0)
      .setLinearDamping(0)
      .setCanSleep(false)
      .setCcdEnabled(true);
    this.body = this.ctx.physics.createBody(desc);
    const cd = RAPIER.ColliderDesc.capsule(PLAYER.capsuleHalf, PLAYER.capsuleRadius)
      .setCollisionGroups(MASKS.player)
      .setRestitution(0.12)
      .setFriction(0.15)
      .setMass(PLAYER.bodyMass);
    this.collider = this.ctx.physics.addCollider(cd, this.body, this.owner);
  }

  // ------------------------------------------------------------------------------------------
  /** Place the player standing on a surface (roof) and reset state. `surface` is the ground point. */
  spawn(surface: THREE.Vector3, heading: number) {
    this.alive = true;
    this.armor = PLAYER.maxArmor;
    this.energy = PLAYER.maxEnergy;
    this.boostLocked = false;
    this.flight.mode = 'grounded';
    this.flight.reset(heading);
    this.setPosition(_v.copy(surface).setY(surface.y + this.soleOffset + 0.02));
    this.vel.set(0, 0, 0);
    this.body.setLinvel({ x: 0, y: 0, z: 0 }, true);
    this.weapons.reset();
    this.root.visible = true;
    this.impactCooldown = 0;
    this.invulnerable = 2.5;
    this.rig.update(0.001, { standing: 1, flight: 0, hover: 0 }, 100);
    this.commitTransform();
    this.renderPos.copy(this.pos);
    this.renderQuat.copy(this.curQuat);
  }

  setPosition(p: THREE.Vector3) {
    this.pos.copy(p);
    this.prevPos.copy(p);
    this.body.setTranslation({ x: p.x, y: p.y, z: p.z }, true);
  }

  get mode(): FlightMode {
    return this.flight.mode;
  }

  canShoot() {
    return this.alive;
  }

  spendEnergy(v: number) {
    this.energy = Math.max(0, this.energy - v);
    this.energyDelay = PLAYER.energyRegenDelay;
  }

  addEnergy(v: number) {
    this.energy = Math.min(PLAYER.maxEnergy, this.energy + v);
  }
  repair(v: number) {
    this.armor = Math.min(PLAYER.maxArmor, this.armor + v);
  }

  // ------------------------------------------------------------------------------------------
  /** once per rendered frame: sample continuous input + latch edge events for the fixed steps */
  pollInput() {
    const inp = this.ctx.input;
    const i = this.intent;
    i.forward = inp.axis(['KeyS'], ['KeyW']);
    i.strafe = inp.axis(['KeyA'], ['KeyD']);
    i.vertical = inp.axis(['KeyC'], ['Space']); // (Ctrl is deliberately not bound: Ctrl+W closes the browser tab)
    i.roll = inp.axis(['KeyQ'], ['KeyE']);
    i.boost = inp.isDown('ShiftLeft') || inp.isDown('ShiftRight');
    i.fire = inp.mouseDown(0);
    const q = this.queued;
    if (inp.wasPressed('KeyF')) q.hover = true;
    if (inp.wasPressed('Tab')) q.cycle = true;
    if (inp.wasPressed('Digit1')) q.missile = true;
    if (inp.wasPressed('Digit2')) q.mini = true;
    if (inp.mousePressed(2)) q.lock = true;
    if (inp.wasPressed('KeyX')) q.dual = true;
  }

  clearInput() {
    this.intent = { forward: 0, strafe: 0, vertical: 0, roll: 0, boost: false, fire: false };
    this.queued = { hover: false, cycle: false, missile: false, mini: false, lock: false, dual: false };
  }

  // ------------------------------------------------------------------------------------------
  /** fixed-step logic BEFORE physics.step */
  preStep(dt: number) {
    const ctx = this.ctx;
    if (!this.alive) {
      // wreck keeps drifting to a stop
      this.vel.multiplyScalar(Math.exp(-2 * dt));
      this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
      return;
    }
    ctx.input.takeMouse(_mouse);
    const set = ctx.settings;
    const it = this.intent;
    const fin: FlightInput = {
      forward: it.forward,
      strafe: it.strafe,
      vertical: it.vertical,
      roll: it.roll,
      boost: it.boost,
      mouseDX: _mouse.x,
      mouseDY: _mouse.y,
      invertY: set.invertY,
      sensitivity: set.sensitivity,
    };
    const q = this.queued;
    this.invulnerable = Math.max(0, this.invulnerable - dt);
    this.impactCooldown -= dt;

    // ---- discrete actions
    if (q.hover) {
      q.hover = false;
      if (this.flight.mode === 'flight') {
        this.flight.mode = 'hover';
        ctx.audio.modeSwitch(true);
        ctx.bus.emit('message', { text: 'HOVER MODE', kind: 'info', time: 1.0 });
      } else if (this.flight.mode === 'hover') {
        this.flight.mode = 'flight';
        ctx.audio.modeSwitch(false);
        ctx.bus.emit('message', { text: 'FLIGHT MODE', kind: 'info', time: 1.0 });
      }
    }
    if (q.lock) {
      q.lock = false;
      const on = this.weapons.targeting.toggleLockMode();
      ctx.bus.emit('message', { text: on ? 'TARGET LOCK ENABLED' : 'TARGET LOCK OFF', kind: 'info', time: 0.9 });
      if (!on) ctx.audio.lockLost();
    }
    if (q.cycle) {
      q.cycle = false;
      if (this.weapons.targeting.cycle(this.pos, this.flight.forward, ctx.enemies.targets)) ctx.audio.ui();
    }
    if (q.dual) {
      q.dual = false;
      this.weapons.dualFire = !this.weapons.dualFire;
      ctx.bus.emit('message', { text: this.weapons.dualFire ? 'REPULSORS: DUAL FIRE' : 'REPULSORS: ALTERNATING', kind: 'info', time: 1.0 });
    }
    if (q.missile) {
      q.missile = false;
      this.weapons.fireMissile();
    }
    if (q.mini) {
      q.mini = false;
      this.weapons.fireMiniSalvo();
    }

    // ---- energy / boost
    if (this.boostLocked && this.energy > FLIGHT.boost.minEnergy * 2) this.boostLocked = false;
    const canBoost = !this.boostLocked && this.energy > 1;

    // ---- flight
    const mode = this.flight.mode;
    this.vel.copy(this.setVelFromBody());
    if (mode === 'grounded') {
      this.flight.stepGrounded(dt, fin);
      const wantsUp = it.vertical > 0 || it.forward !== 0 || it.strafe !== 0 || it.boost;
      this.vel.set(0, 0, 0);
      if (wantsUp) {
        this.flight.mode = 'hover';
        this.vel.y = 4.5;
        this.groundTimer = 0.4;
        ctx.audio.boostStart();
        ctx.fx.dust(_v.copy(this.pos).setY(this.pos.y - this.soleOffset), 3.5, 8);
        if (!this.flightTipShown) {
          this.flightTipShown = true;
          ctx.bus.emit('message', { text: 'PRESS F FOR CRUISE FLIGHT  -  SHIFT TO BOOST', kind: 'info', time: 4.5 });
        }
      }
    } else {
      this.flight.step(dt, fin, this.vel, canBoost);
      this.groundTimer = Math.max(0, this.groundTimer - dt);
      if (this.flight.boosting) {
        this.spendEnergy(FLIGHT.boost.energyPerSec * dt);
        if (this.energy <= 0.5) this.boostLocked = true;
        if (!this.wasBoosting) {
          ctx.audio.boostStart();
          ctx.bus.emit('message', { text: 'BOOST', kind: 'info', time: 0.6 });
        }
      }
      this.wasBoosting = this.flight.boosting;
      this.landingCheck(fin);
      this.boundary(dt);
    }

    // ---- slow armour self-repair when left alone
    if (this.armor < PLAYER.maxArmor && ctx.time - this.lastDamageTime > PLAYER.armorRegenDelay) {
      this.armor = Math.min(PLAYER.maxArmor, this.armor + PLAYER.armorRegen * DIFFICULTY[ctx.settings.difficulty].regen * dt);
    }

    // ---- energy regeneration
    this.energyDelay -= dt;
    if (this.energyDelay <= 0 && !this.flight.boosting) {
      this.energy = Math.min(PLAYER.maxEnergy, this.energy + PLAYER.energyRegen * dt * (this.weapons.firing ? 0.65 : 1));
    }

    // ---- weapons
    this.weapons.update(dt, it.fire);
    this.weapons.targeting.update(dt, this.pos, this.flight.forward, ctx.enemies.targets);

    // ---- hand over to physics
    this.setVel.copy(this.vel);
    this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
    const fq = this.flight.quat;
    this.body.setRotation({ x: fq.x, y: fq.y, z: fq.z, w: fq.w }, true);
    // the capsule follows the visual lean (horizontal in flight, vertical when hovering/standing)
    _q.setFromAxisAngle(AX, this.lastLean);
    this.collider.setRotationWrtParent({ x: _q.x, y: _q.y, z: _q.z, w: _q.w });
  }

  private setVelFromBody() {
    const v = this.body.linvel();
    return _v3.set(v.x, v.y, v.z);
  }

  private landingCheck(fin: FlightInput) {
    const hit = this.ctx.physics.raycast(this.pos, DOWN, 40, G.WORLD | G.DEBRIS, this.collider);
    this.groundDistance = hit ? hit.distance : 100;
    if (!hit) return;
    const want = this.soleOffset + 0.12;
    if (this.groundTimer <= 0 && fin.vertical < 0 && hit.distance < want + 0.5 && this.vel.length() < FLIGHT.landSpeed + 6) {
      // touch down
      this.flight.mode = 'grounded';
      this.vel.set(0, 0, 0);
      this.body.setTranslation({ x: this.pos.x, y: hit.point.y + this.soleOffset + 0.02, z: this.pos.z }, true);
      this.ctx.bus.emit('message', { text: 'LANDED', kind: 'info', time: 0.8 });
      this.ctx.fx.dust(hit.point, 3.5, 6);
    }
  }

  private boundary(dt: number) {
    const b = WORLD.softBound;
    const p = this.pos;
    this.outsideBounds = Math.abs(p.x) > b || Math.abs(p.z) > b || p.y > WORLD.ceiling;
    if (!this.outsideBounds) return;
    // push back toward the combat zone, stronger the farther out
    const over = Math.max(Math.abs(p.x) - b, Math.abs(p.z) - b, p.y - WORLD.ceiling, 0);
    const k = clamp(over / 60, 0, 1);
    _v2.set(-p.x, p.y > WORLD.ceiling ? -(p.y - 200) : 0, -p.z).normalize();
    this.vel.addScaledVector(_v2, (30 + 70 * k) * dt);
  }

  // ------------------------------------------------------------------------------------------
  /** fixed-step logic AFTER physics.step */
  postStep(dt: number) {
    this.prevPos.copy(this.pos);
    this.prevQuat.copy(this.curQuat);
    const t = this.body.translation();
    this.pos.set(t.x, t.y, t.z);
    const v = this.body.linvel();
    this.vel.set(v.x, v.y, v.z);
    this.curQuat.copy(this.alive ? this.flight.quat : this.curQuat);
    this.speed = this.vel.length();
    this.altitude = this.pos.y - this.soleOffset * (this.flight.mode === 'grounded' ? 1 : 0);
    this.damageFlash = Math.max(0, this.damageFlash - dt);

    if (!this.alive) return;
    // collision damage: unexpected velocity change vs the velocity we handed to the solver
    if (this.flight.mode !== 'grounded') {
      _v.copy(this.vel).sub(this.setVel);
      const dv = _v.length();
      if (dv > PLAYER.impactSpeed && this.impactCooldown <= 0 && this.invulnerable <= 0) {
        this.impactCooldown = 0.25;
        const dmg = (dv - PLAYER.impactSpeed) * PLAYER.impactDamageScale;
        _v2.copy(_v).normalize();
        this.takeDamage(dmg, { point: this.pos.clone().addScaledVector(_v2, -0.5), normal: _v2.clone(), source: 'collision' });
        this.ctx.fx.impact(this.pos.clone().addScaledVector(_v2, -0.45), _v2, COL.spark0, COL.spark1, 1.6);
      } else if (dv > 6 && this.impactCooldown <= 0) {
        this.impactCooldown = 0.15;
        _v2.copy(_v).normalize();
        this.ctx.fx.impact(this.pos.clone().addScaledVector(_v2, -0.45), _v2, COL.spark0, COL.spark1, 0.7);
        this.ctx.shake(0.12);
      }
    }
  }

  private commitTransform() {
    this.prevPos.copy(this.pos);
    this.prevQuat.copy(this.flight.quat);
    this.curQuat.copy(this.flight.quat);
  }

  // ------------------------------------------------------------------------------------------
  /** once per frame (variable dt) after the fixed steps: visuals, pose blending, FX */
  updateVisual(dt: number, alpha: number) {
    const ctx = this.ctx;
    this.renderPos.lerpVectors(this.prevPos, this.pos, alpha);
    this.renderQuat.slerpQuaternions(this.prevQuat, this.curQuat, alpha);
    this.root.position.copy(this.renderPos);
    this.root.quaternion.copy(this.renderQuat);
    this.root.updateMatrixWorld(true);
    if (!this.alive) return;

    // pose weights: standing on the ground, hover pose in hover mode, flight pose blends in with speed
    const mode = this.flight.mode;
    const w: Record<PoseName, number> = { standing: 0, flight: 0, hover: 0 };
    if (mode === 'grounded') w.standing = 1;
    else if (mode === 'hover') {
      const f = smoothstep(26, 44, this.speed) * 0.35;
      w.flight = f;
      w.hover = 1 - f;
    } else {
      const f = smoothstep(7, 26, this.speed + this.flight.boostAmount * 20);
      w.flight = f;
      w.hover = 1 - f;
    }
    this.rig.update(dt, w, mode === 'grounded' ? 4 : 3.2);
    this.lastLean = damp(this.lastLean, this.rig.measureLean(), 12, dt);

    // aim arms while firing (after the pose was evaluated)
    this.aimPoint = this.weapons.aimPoint(this.aimPoint);
    for (const side of ['L', 'R'] as const) {
      if (this.rig.aimWeight[side] > 0.001) {
        const muzzle = side === 'L' ? this.rig.muzzleL : this.rig.muzzleR;
        this.rig.worldPos(muzzle, _v);
        _v2.copy(this.aimPoint).sub(_v).normalize();
        this.rig.aimArm(side, _v2);
      }
    }

    // thruster flames from the boots and palms (world dirs read from the posed empties)
    this.emitThrusters(dt);
    this.rig.setGlow(this.flight.boostAmount, 1);
  }

  private flameTimer = 0;
  private emitThrusters(dt: number) {
    const mode = this.flight.mode;
    if (mode === 'grounded') return;
    this.flameTimer += dt;
    const steps = Math.min(3, Math.floor(this.flameTimer / 0.016));
    if (steps <= 0) return;
    this.flameTimer -= steps * 0.016;
    const speed01 = clamp(this.speed / FLIGHT.boost.speed, 0, 1);
    const thrust = this.flight.thrust;
    const boost = this.flight.boostAmount;
    const base = mode === 'hover' ? 0.42 : 0.3 + 0.35 * speed01;
    const power = clamp(base + thrust * 0.4 + boost * 0.9, 0, 1.6);
    const fx = this.ctx.fx;
    const fireL = this.rig.aimWeight.L > 0.05;
    const fireR = this.rig.aimWeight.R > 0.05;
    const nozzles: [THREE.Object3D, number][] = [
      [this.rig.footNozzleL, 1],
      [this.rig.footNozzleR, 1],
      [this.rig.muzzleL, fireL ? 0 : 0.7],
      [this.rig.muzzleR, fireR ? 0 : 0.7],
    ];
    for (const [node, k] of nozzles) {
      if (k <= 0) continue;
      this.rig.worldPos(node, _v);
      this.rig.worldDir(node, _v2);
      for (let i = 0; i < steps; i++) {
        fx.flame(_v, _v2, power * k, boost > 0.2 ? COL.flameBoost : COL.flame, COL.cyanDim, 0.2 + 0.1 * power * k, this.vel);
      }
    }
    if (boost > 0.3 && Math.random() < 0.5) {
      // boost shock ring occasionally behind the suit
      _v.copy(this.pos).addScaledVector(this.flight.forward, -1.5);
    }
  }

  // ------------------------------------------------------------------------------------------
  takeDamage(amount: number, hit: HitInfo) {
    if (!this.alive || this.invulnerable > 0) return;
    amount *= DIFFICULTY[this.ctx.settings.difficulty].damageTaken;
    // energy shield: a fraction of damage drains energy instead of armour
    const absorbed = Math.min(this.energy * 0.25, amount * 0.25);
    this.energy -= absorbed;
    const dmg = amount - absorbed;
    this.armor = Math.max(0, this.armor - dmg);
    this.damageFlash = PLAYER.armorFlashTime;
    this.lastDamageTime = this.ctx.time;
    this.rig.flashHit();
    this.ctx.shake(clamp(0.12 + dmg * 0.04, 0.1, 0.9));
    this.ctx.audio.playerHit(clamp(dmg / 12, 0.3, 1.4));
    this.ctx.bus.emit('playerDamaged', { amount: dmg, source: hit.source });
    if (hit.kick) {
      const d = hit.dir ?? _v2.set(0, 0, 0);
      this.vel.addScaledVector(d, hit.kick);
      this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
    }
    if (this.armor <= 0) this.die(hit);
  }

  /** apply an explosion / impulse velocity change */
  kick(dir: THREE.Vector3, speed: number) {
    this.vel.addScaledVector(dir, speed);
    this.body.setLinvel({ x: this.vel.x, y: this.vel.y, z: this.vel.z }, true);
    if (this.flight.mode === 'grounded') this.flight.mode = 'hover';
  }

  private die(hit: HitInfo) {
    this.alive = false;
    this.root.visible = false;
    const ctx = this.ctx;
    ctx.fx.explosion(this.pos.clone(), 2.4, { color: 'fire' });
    ctx.audio.explosion(2.2, this.pos);
    ctx.shake(1.6);
    // scatter armour plates as debris
    for (let i = 0; i < 26; i++) {
      ctx.fx.sparks(this.pos, null, 3, rand(20, 60), COL.spark0, COL.spark1, 1.6);
    }
    ctx.bus.emit('playerDied', {});
    void hit;
  }

  dispose() {
    this.ctx.scene.remove(this.root);
    this.ctx.physics.removeBody(this.body);
  }

  get visible() {
    return this.wantVisual;
  }
}

