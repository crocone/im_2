import * as THREE from 'three';
import type { GameCtx, Target } from '../game/types';
import { Drone } from './drone';
import { Turret } from './turret';
import { Boss } from './boss';
import { G } from '../physics/world';
import { rand } from '../core/rng';
import { TURRET } from '../config';

/** Owns all hostile entities and exposes the live target list used by lock-on and HUD markers. */
export class EnemyManager {
  readonly drones: Drone[] = [];
  readonly turrets: Turret[] = [];
  boss: Boss | null = null;
  targets: Target[] = [];

  constructor(private ctx: GameCtx) {}

  spawnDrone(pos: THREE.Vector3, aggressive = false) {
    const d = new Drone(this.ctx, pos, aggressive);
    this.drones.push(d);
    this.rebuildTargets();
    return d;
  }

  spawnTurret(base: THREE.Vector3, yaw: number) {
    const t = new Turret(this.ctx, base, yaw);
    this.turrets.push(t);
    this.rebuildTargets();
    return t;
  }

  spawnBoss(home: THREE.Vector3) {
    this.boss = new Boss(this.ctx, home);
    this.rebuildTargets();
    return this.boss;
  }

  /** find a free point in the air at distance [rMin, rMax] from `around` (outside of buildings) */
  findAirSpawn(around: THREE.Vector3, rMin: number, rMax: number, yMin: number, yMax: number, out = new THREE.Vector3()) {
    for (let i = 0; i < 40; i++) {
      const a = rand(0, Math.PI * 2);
      const r = rand(rMin, rMax);
      out.set(around.x + Math.cos(a) * r, rand(yMin, yMax), around.z + Math.sin(a) * r);
      out.x = Math.max(-380, Math.min(380, out.x));
      out.z = Math.max(-380, Math.min(380, out.z));
      let free = true;
      this.ctx.physics.overlapSphere(out, 4, G.WORLD, () => {
        free = false;
        return false;
      });
      if (free) return out;
    }
    return out;
  }

  get aliveDrones() {
    let n = 0;
    for (const d of this.drones) if (d.alive) n++;
    return n;
  }
  get aliveTurrets() {
    let n = 0;
    for (const t of this.turrets) if (t.alive) n++;
    return n;
  }

  private rebuildTargets() {
    const list: Target[] = [];
    for (const d of this.drones) if (d.alive) list.push(d);
    for (const t of this.turrets) if (t.alive) list.push(t);
    if (this.boss && this.boss.alive) list.push(this.boss);
    this.targets = list;
  }

  private salvoLock = 0;

  /** turrets ask for permission before a salvo so that many turrets never fire in the same instant */
  requestTurretSalvo() {
    // the Behemoth's jamming field takes the rooftop turret network offline while it is alive
    if (this.salvoLock > 0 || this.bossJamming) return false;
    this.salvoLock = TURRET.salvoStagger * rand(0.8, 1.2);
    return true;
  }

  get bossJamming() {
    return !!this.boss && this.boss.alive;
  }

  preStep(dt: number) {
    this.salvoLock = Math.max(0, this.salvoLock - dt);
    for (const d of this.drones) d.preStep(dt);
    for (const t of this.turrets) t.preStep(dt);
    this.boss?.preStep(dt);
  }

  postStep() {
    for (const d of this.drones) d.postStep();
    this.boss?.postStep();
    // prune removed drones, refresh target list
    for (let i = this.drones.length - 1; i >= 0; i--) if (this.drones[i].removed) this.drones.splice(i, 1);
    if (this.boss?.removed) this.boss = null;
    this.rebuildTargets();
  }

  syncVisuals(dt: number, alpha: number) {
    for (const d of this.drones) d.syncVisual(dt, alpha);
    for (const t of this.turrets) t.syncVisual(dt);
    this.boss?.syncVisual(dt, alpha);
  }

  /** remove drones and the boss but keep the (static) turrets - used when retrying a wave */
  clearMobile() {
    for (const d of this.drones) if (!d.removed) d.dispose();
    this.boss?.dispose();
    this.drones.length = 0;
    this.boss = null;
    this.rebuildTargets();
  }

  clear() {
    for (const d of this.drones) if (!d.removed) d.dispose();
    for (const t of this.turrets) t.dispose();
    this.boss?.dispose();
    this.drones.length = 0;
    this.turrets.length = 0;
    this.boss = null;
    this.targets = [];
  }
}
