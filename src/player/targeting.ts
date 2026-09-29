import * as THREE from 'three';
import { WEAPON } from '../config';
import type { Physics } from '../physics/world';
import { G } from '../physics/world';
import type { Target } from '../game/types';
import { clamp } from '../core/math';

export type LockState = 'searching' | 'acquiring' | 'locked';

const _d = new THREE.Vector3();

/**
 * Target selection + lock-on state machine.
 *   SEARCHING -> ACQUIRING (progress fills while the target stays inside the acquisition cone,
 *   in range and in line of sight) -> LOCKED (kept while inside the wider hold cone).
 * Breaking angle / range / LOS drains progress or cancels the lock. Tab cycles targets.
 */
export class Targeting {
  lockMode = false;
  state: LockState = 'searching';
  progress = 0;
  current: Target | null = null;
  /** best candidate under the reticle even when not locking (HUD hint) */
  candidate: Target | null = null;
  private lostTimer = 0;
  private losTimer = 0;
  private fastAcquire = 0;

  constructor(private physics: Physics) {}

  reset() {
    this.lockMode = false;
    this.state = 'searching';
    this.progress = 0;
    this.current = null;
    this.candidate = null;
    this.lostTimer = 0;
  }

  toggleLockMode() {
    this.lockMode = !this.lockMode;
    if (!this.lockMode) {
      this.state = 'searching';
      this.progress = 0;
      this.current = null;
    }
    return this.lockMode;
  }

  /** angle (rad) between the aim direction and the direction to `t` */
  private angleTo(origin: THREE.Vector3, aim: THREE.Vector3, t: Target) {
    _d.copy(t.pos).sub(origin);
    const dist = _d.length();
    if (dist < 1e-3) return { angle: 0, dist };
    return { angle: Math.acos(clamp(_d.dot(aim) / dist, -1, 1)), dist };
  }

  private visible(origin: THREE.Vector3, t: Target) {
    // line of sight against the world only (buildings); the target's own collider is not in the WORLD mask
    return !this.physics.blocked(origin, t.pos, G.WORLD);
  }

  /** Sorted candidate list: by angle to the reticle (closest first) */
  sorted(origin: THREE.Vector3, aim: THREE.Vector3, targets: Target[]) {
    const cone = WEAPON.lock.candidateCone;
    const out: { t: Target; angle: number; dist: number }[] = [];
    for (const t of targets) {
      if (!t.alive) continue;
      const { angle, dist } = this.angleTo(origin, aim, t);
      if (angle > cone || dist > WEAPON.lock.range) continue;
      out.push({ t, angle, dist });
    }
    out.sort((a, b) => a.angle - b.angle);
    return out;
  }

  /** Tab: switch to the next candidate (wraps). Restarts acquisition quickly. */
  cycle(origin: THREE.Vector3, aim: THREE.Vector3, targets: Target[]) {
    const list = this.sorted(origin, aim, targets);
    if (list.length === 0) return false;
    let idx = list.findIndex((e) => e.t === this.current);
    idx = (idx + 1) % list.length;
    this.current = list[idx].t;
    this.state = 'acquiring';
    this.progress = 0;
    this.fastAcquire = WEAPON.lock.acquireTime / WEAPON.lock.switchTime;
    this.lockMode = true;
    return true;
  }

  update(dt: number, origin: THREE.Vector3, aim: THREE.Vector3, targets: Target[]) {
    const L = WEAPON.lock;
    const list = this.sorted(origin, aim, targets);
    this.candidate = list.length ? list[0].t : null;

    if (!this.lockMode) {
      this.state = 'searching';
      this.progress = 0;
      this.current = null;
      return;
    }

    if (this.current && !this.current.alive) {
      this.current = null;
      this.state = 'searching';
      this.progress = 0;
    }

    if (!this.current) {
      this.state = 'searching';
      this.progress = 0;
      if (list.length) {
        this.current = list[0].t;
        this.state = 'acquiring';
        this.fastAcquire = 1;
      }
      return;
    }

    const { angle, dist } = this.angleTo(origin, aim, this.current);
    const inRange = dist <= L.range;
    const los = this.visible(origin, this.current);

    if (this.state === 'acquiring') {
      if (angle <= L.acquireCone && inRange && los) {
        this.progress += (dt / L.acquireTime) * this.fastAcquire;
        if (this.progress >= 1) {
          this.progress = 1;
          this.state = 'locked';
          this.lostTimer = 0;
          this.losTimer = 0;
        }
      } else {
        this.progress -= dt * 1.4;
        // a better candidate under the reticle takes over while we are not close to locking
        if (this.progress <= 0) {
          this.progress = 0;
          if (list.length && list[0].t !== this.current) {
            this.current = list[0].t;
            this.fastAcquire = 1;
          } else if (angle > L.candidateCone || !inRange) {
            this.current = null;
            this.state = 'searching';
          }
        }
      }
    } else if (this.state === 'locked') {
      const good = angle <= L.holdCone && inRange;
      this.losTimer = los ? 0 : this.losTimer + dt;
      if (!good || this.losTimer > 1.0) {
        this.lostTimer += dt;
        this.progress = Math.max(0, 1 - this.lostTimer / L.loseTime);
        if (this.lostTimer >= L.loseTime) {
          this.state = 'acquiring';
          this.progress = 0;
          this.lostTimer = 0;
          this.losTimer = 0;
          this.fastAcquire = 1;
        }
      } else {
        this.lostTimer = 0;
        this.progress = 1;
      }
    }
  }

  get locked() {
    return this.state === 'locked' && this.current !== null && this.current.alive;
  }

  /** Targets a mini-missile salvo should chase: locked one first, then others near the reticle */
  salvoTargets(origin: THREE.Vector3, aim: THREE.Vector3, targets: Target[], max: number): Target[] {
    const out: Target[] = [];
    if (this.locked && this.current) out.push(this.current);
    const cone = 62 * (Math.PI / 180);
    const list = this.sorted(origin, aim, targets).filter((e) => e.angle <= cone && e.dist < 380 && e.t !== this.current);
    for (const e of list) {
      if (out.length >= max) break;
      out.push(e.t);
    }
    return out;
  }
}
