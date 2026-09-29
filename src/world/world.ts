import * as THREE from 'three';
import type { GameCtx } from '../game/types';
import { Rng } from '../core/rng';
import { WORLD } from '../config';
import { City, RoofSlot } from './city';
import { DestructibleManager } from './destructibles';
import { PropManager } from './props';

export interface TurretSlot {
  pos: THREE.Vector3;
  yaw: number;
}

/** Aggregates the static city, its destructible objects and props, and picks gameplay anchor points. */
export class World {
  readonly city: City;
  readonly destructibles: DestructibleManager;
  readonly props: PropManager;
  turretSlots: TurretSlot[] = [];
  spawnPoint = new THREE.Vector3(0, 60, 0);
  spawnHeading = 0;
  private reserved = new Set<RoofSlot>();

  constructor(private ctx: GameCtx) {
    this.city = new City(ctx);
    this.destructibles = new DestructibleManager(ctx);
    this.props = new PropManager(ctx);
  }

  build() {
    const city = this.city;
    city.build();
    const rng = new Rng(WORLD.seed ^ 0xbeef);
    const reserved = this.reserved;
    this.spawnPoint.copy(city.spawnRoof);
    for (const s of city.roofSlots) if (s.building === city.spawnBuilding) reserved.add(s);
    // face the middle of the city
    this.spawnHeading = Math.atan2(this.spawnPoint.x, this.spawnPoint.z);

    // ---- turrets: spread over the roofs, away from the spawn roof
    const free = city.roofSlots.filter((s) => !reserved.has(s) && s.height >= 22 && s.clear > 5.5);
    rng.shuffle(free);
    const chosen: RoofSlot[] = [];
    for (const s of free) {
      if (chosen.length >= 11) break;
      if (Math.hypot(s.pos.x - this.spawnPoint.x, s.pos.z - this.spawnPoint.z) < 150) continue;
      if (chosen.some((c) => Math.hypot(c.pos.x - s.pos.x, c.pos.z - s.pos.z) < 110)) continue;
      chosen.push(s);
    }
    for (const s of chosen) {
      reserved.add(s);
      this.turretSlots.push({ pos: s.pos.clone(), yaw: rng.range(0, Math.PI * 2) });
    }
    this.placeDestructibles();
    this.props.populate(city, reserved);
  }

  /** (re)place the destructible objects: water towers / signs on roofs, columns / kiosks / signs in plazas */
  placeDestructibles() {
    const city = this.city;
    const rng = new Rng(WORLD.seed ^ 0xd35);
    const used = new Set<RoofSlot>();
    // slots under a canopy / pavilion cannot host the tall objects
    const roofPool = city.roofSlots.filter((s) => (!this.reserved.has(s) || this.destructibleSlots.has(s)) && s.clear > 10.6);
    rng.shuffle(roofPool);
    let towers = 0;
    let signs = 0;
    this.destructibleSlots.clear();
    for (const s of roofPool) {
      if (this.turretSlots.some((t) => t.pos.equals(s.pos))) continue;
      if (towers < 9 && s.height < 90 && rng.chance(0.55)) {
        this.destructibles.place('watertower', s.pos, rng.int(0, 3));
        used.add(s);
        towers++;
      } else if (signs < 6 && s.height > 30 && s.clear > 12.5 && rng.chance(0.4)) {
        this.destructibles.place('citysign', s.pos, rng.int(0, 3));
        used.add(s);
        signs++;
      }
      if (towers >= 9 && signs >= 6) break;
    }
    for (const s of used) {
      this.reserved.add(s);
      this.destructibleSlots.add(s);
    }
    const plazas = [...city.plazas];
    rng.shuffle(plazas);
    let kiosks = 0;
    plazas.forEach((pl, i) => {
      const c = new THREE.Vector3(pl.x, WORLD.lotY, pl.z);
      if (kiosks < 6 && i % 2 === 0) {
        this.destructibles.place('smallbuilding', c, rng.int(0, 3));
        kiosks++;
        this.destructibles.place('column', c.clone().add(new THREE.Vector3(pl.w / 2 - 6, 0, pl.d / 2 - 6)), 0);
        this.destructibles.place('column', c.clone().add(new THREE.Vector3(-(pl.w / 2 - 6), 0, -(pl.d / 2 - 6))), 0);
      } else {
        const n = 4;
        for (let k = 0; k < n; k++) this.destructibles.place('column', c.clone().add(new THREE.Vector3((k - (n - 1) / 2) * 11, 0, rng.range(-3, 3))), 0);
        if (i % 3 === 1) this.destructibles.place('citysign', c.clone().add(new THREE.Vector3(0, 0, pl.d / 2 - 5)), rng.int(0, 3));
      }
    });
  }
  private destructibleSlots = new Set<RoofSlot>();

  /** restore the city for a new mission */
  reset() {
    this.destructibles.clear();
    this.placeDestructibles();
    this.props.reset();
  }

  update(dt: number, camPos: THREE.Vector3, playerPos: THREE.Vector3) {
    this.city.update(dt, camPos, playerPos);
    this.props.update(dt, playerPos, camPos);
    this.destructibles.update(dt, camPos);
  }
}
