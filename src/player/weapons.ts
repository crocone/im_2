import * as THREE from 'three';
import { WEAPON, PLAYER } from '../config';
import { G } from '../physics/world';
import { COL } from '../fx/effects';
import type { GameCtx, Target } from '../game/types';
import { isDamageable } from '../game/types';
import type { Player } from './player';
import { Targeting } from './targeting';
import type { MissileSpec } from '../weapons/projectiles';
import { rand } from '../core/rng';

const REPULSOR_MASK = G.WORLD | G.ENEMY | G.SHIELD | G.PROJ_ENEMY | G.DEBRIS;

export const MISSILE_SPEC: MissileSpec = {
  team: 'player',
  asset: 'missile',
  rootName: 'Missile',
  speed: WEAPON.missile.speed,
  launchSpeed: WEAPON.missile.launchSpeed,
  accel: WEAPON.missile.accel,
  turnRate: WEAPON.missile.turnRate,
  arcTime: WEAPON.missile.arcTime,
  blendTime: WEAPON.missile.blendTime,
  proximity: WEAPON.missile.proximity,
  damage: WEAPON.missile.damage,
  radius: WEAPON.missile.radius,
  kick: 26,
  life: WEAPON.missile.life,
  collideRadius: 0.28,
  trailScale: 1.0,
  explosionScale: 1.45,
  source: 'missile',
  fireColor: 'fire',
  spin: 6,
};

export const MINI_SPEC: MissileSpec = {
  team: 'player',
  asset: 'mini_missile',
  rootName: 'MiniMissile',
  speed: WEAPON.mini.speed,
  launchSpeed: WEAPON.mini.launchSpeed,
  accel: WEAPON.mini.accel,
  turnRate: WEAPON.mini.turnRate,
  arcTime: WEAPON.mini.arcTime,
  blendTime: WEAPON.mini.blendTime,
  proximity: WEAPON.mini.proximity,
  damage: WEAPON.mini.damage,
  radius: WEAPON.mini.radius,
  kick: 11,
  life: WEAPON.mini.life,
  collideRadius: 0.16,
  trailScale: 0.55,
  explosionScale: 0.72,
  source: 'mini',
  fireColor: 'fire',
  spin: 10,
};

const _o = new THREE.Vector3();
const _d = new THREE.Vector3();
const _ao = new THREE.Vector3();
const _lf1 = new THREE.Vector3();
const _lf2 = new THREE.Vector3();
const _ad = new THREE.Vector3();
const _e = new THREE.Vector3();
const _n = new THREE.Vector3();

interface QueuedMini {
  at: number;
  slot: number;
  target: Target | null;
}

/** Repulsors (hitscan), homing missiles and mini-missile salvos with finite ammo. */
export class PlayerWeapons {
  missiles: number = WEAPON.missile.max;
  minis: number = WEAPON.mini.max;
  readonly targeting: Targeting;
  dualFire = false;
  private hand: 'L' | 'R' = 'R';
  private repulsorTimer = 0;
  private missileCd = 0;
  private miniCd = 0;
  private missileSlot = 0;
  private queue: QueuedMini[] = [];
  private clock = 0;
  /** true while the trigger is held & energy available (drives arm aiming + HUD) */
  firing = false;
  lastFire = -10;
  noLockMsgCd = 0;

  constructor(private ctx: GameCtx, private player: Player) {
    this.targeting = new Targeting(ctx.physics);
  }

  reset() {
    this.missiles = WEAPON.missile.max;
    this.minis = WEAPON.mini.max;
    this.queue.length = 0;
    this.targeting.reset();
    this.repulsorTimer = this.missileCd = this.miniCd = 0;
  }

  addAmmo(missiles: number, minis: number) {
    this.missiles = Math.min(WEAPON.missile.max, this.missiles + missiles);
    this.minis = Math.min(WEAPON.mini.max, this.minis + minis);
    this.ctx.bus.emit('ammo', {});
  }

  /** called once per fixed step */
  update(dt: number, trigger: boolean) {
    this.clock += dt;
    this.noLockMsgCd -= dt;
    this.repulsorTimer -= dt;
    this.missileCd -= dt;
    this.miniCd -= dt;

    const p = this.player;
    this.firing = false;
    if (trigger && p.alive && p.canShoot()) {
      const cost = WEAPON.repulsor.energy;
      if (p.energy >= cost) {
        this.firing = true;
        if (this.repulsorTimer <= 0) {
          this.repulsorTimer = WEAPON.repulsor.interval * (this.dualFire ? 1.6 : 1);
          if (this.dualFire) {
            this.shootRepulsor('L');
            this.shootRepulsor('R');
            p.spendEnergy(cost * 2);
          } else {
            this.shootRepulsor(this.hand);
            this.hand = this.hand === 'R' ? 'L' : 'R';
            p.spendEnergy(cost);
          }
        }
      } else if (this.repulsorTimer <= 0) {
        this.repulsorTimer = 0.25;
        this.ctx.audio.noAmmo();
        this.ctx.bus.emit('message', { text: 'ENERGY DEPLETED', kind: 'warn', time: 1 });
      }
    }

    // queued mini-missiles
    while (this.queue.length && this.queue[0].at <= this.clock) {
      const q = this.queue.shift()!;
      this.launchMini(q);
    }
  }

  /** aim point: where the suit's nose ray hits (converging shots), min 18 m so the palms do not cross */
  aimPoint(out: THREE.Vector3): THREE.Vector3 {
    const p = this.player;
    _ao.copy(p.pos);
    _ad.copy(p.flight.forward);
    const hit = this.ctx.physics.raycast(_ao, _ad, 700, G.WORLD | G.ENEMY | G.SHIELD | G.DEBRIS, p.collider);
    const dist = hit ? Math.max(18, hit.distance) : 260;
    return out.copy(_ao).addScaledVector(_ad, dist);
  }

  private shootRepulsor(hand: 'L' | 'R') {
    const p = this.player;
    const ctx = this.ctx;
    const muzzle = hand === 'L' ? p.rig.muzzleL : p.rig.muzzleR;
    p.rig.aimWeight[hand] = 1;
    p.rig.worldPos(muzzle, _o);
    this.aimPoint(_e);
    _d.copy(_e).sub(_o).normalize();
    const sp = WEAPON.repulsor.spread;
    _d.x += rand(-sp, sp);
    _d.y += rand(-sp, sp);
    _d.z += rand(-sp, sp);
    _d.normalize();
    const R = WEAPON.repulsor;
    const hit = ctx.physics.raycast(_o, _d, R.range, REPULSOR_MASK, p.collider);
    const end = hit ? hit.point : _e.copy(_o).addScaledVector(_d, R.range);
    // visible beam from the actual palm reactor
    ctx.fx.beam(_o, end, COL.cyan, 0.34, 0.075);
    ctx.fx.muzzleFlash(_o, _d, 1.0, COL.cyan);
    ctx.fx.lights.flash(_o, 0x66ddff, 260, 0.07, 14);
    ctx.audio.repulsor(_o);
    ctx.recoil(0.03);
    this.lastFire = this.clock;
    if (hit) {
      _n.copy(hit.normal);
      ctx.fx.impact(hit.point, _n, COL.cyan, COL.cyanDim, 0.9);
      ctx.audio.impact(hit.point);
      const owner = hit.owner;
      if (owner) {
        const ref = owner.ref;
        if (isDamageable(ref)) {
          ref.takeDamage(R.damage, { point: hit.point.clone(), normal: hit.normal.clone(), dir: _d.clone(), source: 'repulsor', kick: 0.6 });
          if (owner.kind === 'enemy' || owner.kind === 'shield' || owner.kind === 'projectile') ctx.bus.emit('hit', { shield: owner.kind === 'shield' });
        }
        // physical impulse on dynamic bodies (debris, props ...)
        const body = hit.collider.parent();
        if (body && body.isDynamic() && owner.kind !== 'enemy') {
          body.applyImpulseAtPoint({ x: _d.x * R.impulse, y: _d.y * R.impulse, z: _d.z * R.impulse }, { x: hit.point.x, y: hit.point.y, z: hit.point.z }, true);
        }
      }
    }
  }

  fireMissile() {
    const p = this.player;
    const t = this.targeting;
    if (!p.alive || !p.canShoot()) return;
    if (this.missileCd > 0) return;
    if (this.missiles <= 0) {
      this.ctx.bus.emit('message', { text: 'MISSILES DEPLETED', kind: 'warn', time: 1.2 });
      this.ctx.audio.noAmmo();
      return;
    }
    if (!t.locked || !t.current) {
      if (this.noLockMsgCd <= 0) {
        this.noLockMsgCd = 0.8;
        this.ctx.bus.emit('message', { text: t.lockMode ? 'NO LOCK - HOLD TARGET IN RETICLE' : 'NO LOCK - PRESS RMB TO ACQUIRE', kind: 'warn', time: 1.4 });
        this.ctx.audio.noAmmo();
      }
      return;
    }
    const launcher = p.rig.missileLaunchers[this.missileSlot % 2];
    this.missileSlot++;
    p.rig.worldPos(launcher, _o);
    p.rig.worldDir(launcher, _d);
    this.ctx.projectiles.spawnMissile(MISSILE_SPEC, _o, _d, p.vel, t.current, p);
    this.missiles--;
    this.missileCd = WEAPON.missile.cooldown;
    this.launchFx(_o, _d, 1.0);
    this.ctx.audio.missileLaunch(_o);
    this.ctx.recoil(0.16);
    this.ctx.shake(0.12);
    this.lastFire = this.clock;
    this.ctx.bus.emit('ammo', {});
  }

  fireMiniSalvo() {
    const p = this.player;
    if (!p.alive || !p.canShoot()) return;
    if (this.miniCd > 0 || this.queue.length) return;
    if (this.minis <= 0) {
      this.ctx.bus.emit('message', { text: 'MINI-MISSILES DEPLETED', kind: 'warn', time: 1.2 });
      this.ctx.audio.noAmmo();
      return;
    }
    const n = Math.min(WEAPON.mini.salvo, this.minis);
    const targets = this.targeting.salvoTargets(p.pos, p.flight.forward, this.ctx.enemies.targets, 4);
    for (let i = 0; i < n; i++) {
      this.queue.push({
        at: this.clock + i * WEAPON.mini.interval,
        slot: i,
        target: targets.length ? targets[i % targets.length] : null,
      });
    }
    this.minis -= n;
    this.miniCd = WEAPON.mini.cooldown;
    this.ctx.bus.emit('ammo', {});
  }

  private launchMini(q: QueuedMini) {
    const p = this.player;
    if (!p.alive) return;
    const launcher = p.rig.miniLaunchers[q.slot % p.rig.miniLaunchers.length];
    p.rig.worldPos(launcher, _o);
    p.rig.worldDir(launcher, _d);
    // fan outward: random spread around the tube axis, wider for later shots
    const f = WEAPON.mini.fan;
    _d.x += rand(-f, f) * 0.8;
    _d.y += rand(-f * 0.3, f * 1.1);
    _d.z += rand(-f, f) * 0.8;
    _d.normalize();
    const tgt = q.target && q.target.alive ? q.target : null;
    this.ctx.projectiles.spawnMissile(MINI_SPEC, _o, _d, p.vel, tgt, p);
    this.launchFx(_o, _d, 0.55);
    this.ctx.audio.miniLaunch(_o);
    this.ctx.recoil(0.05);
    this.lastFire = this.clock;
  }

  private launchFx(pos: THREE.Vector3, dir: THREE.Vector3, scale: number) {
    const fx = this.ctx.fx;
    fx.particles.add.emit({ x: pos.x, y: pos.y, z: pos.z, life: 0.14, size0: 1.3 * scale, size1: 0.4 * scale, c0: COL.hot, c1: COL.amber, a0: 1, a1: 0 });
    for (let i = 0; i < 5; i++) {
      _lf1.copy(pos).addScaledVector(dir, i * 0.25);
      _lf2.copy(dir).multiplyScalar(-2);
      _lf2.x += rand(-1, 1);
      _lf2.y += rand(0, 2);
      _lf2.z += rand(-1, 1);
      fx.smokePuff(_lf1, _lf2, 0.7 * scale, rand(0.8, 1.4), false, 0.5);
    }
    fx.lights.flash(pos, 0xffaa55, 900 * scale, 0.15, 30);
  }

  /** for HUD */
  get missilesMax() {
    return WEAPON.missile.max;
  }
  get minisMax() {
    return WEAPON.mini.max;
  }
  get energyCostLabel() {
    return `${WEAPON.repulsor.energy}`;
  }
  /** touch PLAYER to keep the import used for tuning helpers */
  static readonly maxEnergy = PLAYER.maxEnergy;
}
