import * as THREE from 'three';
import { PICKUP } from '../config';
import type { GameCtx } from '../game/types';
import { rand } from '../core/rng';
import { COL } from '../fx/effects';
import { prepareMeshes } from '../assets/loader';

export type PickupKind = 'armor' | 'energy' | 'missiles' | 'mini';

const NODE: Record<PickupKind, string> = {
  armor: 'Pickup_Armor',
  energy: 'Pickup_Energy',
  missiles: 'Pickup_Missiles',
  mini: 'Pickup_Mini',
};

const LABEL: Record<PickupKind, string> = {
  armor: 'ARMOR REPAIRED',
  energy: 'ENERGY CELL',
  missiles: 'MISSILES RESUPPLIED',
  mini: 'MINI-MISSILES RESUPPLIED',
};

const GLOW: Record<PickupKind, readonly [number, number, number]> = {
  armor: [0.6, 3.0, 1.2],
  energy: COL.cyan,
  missiles: [4.0, 0.7, 0.3],
  mini: COL.amber,
};

export interface Pickup {
  kind: PickupKind;
  obj: THREE.Object3D;
  pos: THREE.Vector3;
  vel: THREE.Vector3;
  life: number;
  t: number;
}

const _v = new THREE.Vector3();

/** Floating supply canisters dropped by destroyed enemies: armour, energy, missiles, mini-missiles. */
export class PickupManager {
  private list: Pickup[] = [];

  /** live supply canisters (read-only use: radar, autopilot tests) */
  get items(): readonly Pickup[] {
    return this.list;
  }

  constructor(private ctx: GameCtx) {}

  private chooseKind(): PickupKind {
    const p = this.ctx.player;
    const w: [PickupKind, number][] = [
      ['armor', 1 + Math.max(0, 1 - p.armor / 100) * 5],
      ['energy', 1 + Math.max(0, 1 - p.energy / 100) * 2],
      ['missiles', 0.6 + Math.max(0, 1 - p.weapons.missiles / p.weapons.missilesMax) * 4],
      ['mini', 0.6 + Math.max(0, 1 - p.weapons.minis / p.weapons.minisMax) * 4],
    ];
    let sum = 0;
    for (const [, k] of w) sum += k;
    let r = rand(0, sum);
    for (const [kind, k] of w) if ((r -= k) <= 0) return kind;
    return 'armor';
  }

  maybeDrop(pos: THREE.Vector3, chance = PICKUP.dropChance) {
    if (Math.random() < chance) this.spawn(this.chooseKind(), pos);
  }

  drop(pos: THREE.Vector3, count: number) {
    for (let i = 0; i < count; i++) {
      _v.set(rand(-6, 6), rand(-2, 4), rand(-6, 6)).add(pos);
      this.spawn(this.chooseKind(), _v);
    }
  }

  spawn(kind: PickupKind, pos: THREE.Vector3) {
    const obj = this.ctx.assets.cloneNode('pickups', NODE[kind]);
    prepareMeshes(obj, { cast: false, receive: false, envIntensity: 1.2 });
    this.ctx.scene.add(obj);
    obj.position.copy(pos);
    this.list.push({
      kind, obj, pos: pos.clone(), vel: new THREE.Vector3(rand(-3, 3), rand(2, 6), rand(-3, 3)), life: PICKUP.life, t: rand(0, 6),
    });
  }

  update(dt: number) {
    const p = this.ctx.player;
    for (let i = this.list.length - 1; i >= 0; i--) {
      const k = this.list[i];
      k.life -= dt;
      k.t += dt;
      // drift, then bob
      k.vel.multiplyScalar(Math.exp(-2.2 * dt));
      k.pos.addScaledVector(k.vel, dt);
      const d = k.pos.distanceTo(p.pos);
      if (p.alive && d < PICKUP.radius * 3.4) {
        // magnet
        _v.copy(p.pos).sub(k.pos).normalize();
        k.pos.addScaledVector(_v, (1 - d / (PICKUP.radius * 3.4)) * 26 * dt + 4 * dt);
      }
      k.obj.position.set(k.pos.x, k.pos.y + Math.sin(k.t * 2.2) * 0.25, k.pos.z);
      k.obj.rotation.y += dt * 1.6;
      const blink = k.life < 6 ? (Math.sin(k.life * 14) > 0 ? 1 : 0.2) : 1;
      k.obj.visible = blink > 0.5;
      if (Math.random() < 0.5) this.ctx.fx.glow(k.obj.position, 1.6, 0.25, GLOW[k.kind], 0.5 * blink);
      if (p.alive && d < 2.6) {
        this.collect(k);
        this.list.splice(i, 1);
      } else if (k.life <= 0) {
        this.ctx.scene.remove(k.obj);
        this.list.splice(i, 1);
      }
    }
  }

  private collect(k: Pickup) {
    const p = this.ctx.player;
    switch (k.kind) {
      case 'armor':
        p.repair(30);
        break;
      case 'energy':
        p.addEnergy(65);
        break;
      case 'missiles':
        p.weapons.addAmmo(2, 0);
        break;
      case 'mini':
        p.weapons.addAmmo(0, 6);
        break;
    }
    this.ctx.fx.glow(k.pos, 3.5, 0.3, GLOW[k.kind], 0.9);
    this.ctx.fx.sparks(k.pos, null, 10, 12, GLOW[k.kind], GLOW[k.kind], 0.6);
    this.ctx.audio.pickup();
    this.ctx.bus.emit('message', { text: LABEL[k.kind], kind: 'good', time: 1.6 });
    this.ctx.scene.remove(k.obj);
  }

  clear() {
    for (const k of this.list) this.ctx.scene.remove(k.obj);
    this.list.length = 0;
  }
}
