import * as THREE from 'three';
import { RAPIER, MASKS, Owner } from '../physics/world';
import type { GameCtx } from '../game/types';
import { COL } from '../fx/effects';
import { rand } from '../core/rng';

interface Piece {
  mesh: THREE.Object3D;
  body: RAPIER.RigidBody;
  life: number;
  fade: number;
  scale0: number;
  smoke: boolean;
  smokeT: number;
  owner: Owner;
}

const MAX_PIECES = 190;

/**
 * Pool of physical debris: every piece is a real Rapier dynamic body with a convex-hull (or box) collider and a mesh cloned
 * from the authored fractured assets. Pieces fade out at the end of their life; the oldest are recycled when over budget.
 */
export class DebrisManager {
  private pieces: Piece[] = [];
  private tmpQ = new THREE.Quaternion();

  constructor(private ctx: GameCtx) {}

  get count() {
    return this.pieces.length;
  }

  /**
   * @param points  vertex cloud (local to `mesh`) used to build a convex hull collider; falls back to a box from `half`
   */
  add(opts: {
    mesh: THREE.Object3D;
    pos: THREE.Vector3;
    quat: THREE.Quaternion;
    points?: Float32Array;
    half?: THREE.Vector3;
    vel: THREE.Vector3;
    ang: THREE.Vector3;
    life?: number;
    density?: number;
    mass?: number;
    smoke?: boolean;
  }) {
    while (this.pieces.length >= MAX_PIECES) this.remove(0);
    const desc = RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(opts.pos.x, opts.pos.y, opts.pos.z)
      .setRotation({ x: opts.quat.x, y: opts.quat.y, z: opts.quat.z, w: opts.quat.w })
      .setLinvel(opts.vel.x, opts.vel.y, opts.vel.z)
      .setAngvel({ x: opts.ang.x, y: opts.ang.y, z: opts.ang.z })
      .setLinearDamping(0.08)
      .setAngularDamping(0.35)
      .setCanSleep(true);
    const body = this.ctx.physics.createBody(desc);
    let cd: RAPIER.ColliderDesc | null = null;
    if (opts.points && opts.points.length >= 12) cd = RAPIER.ColliderDesc.convexHull(opts.points);
    if (!cd) {
      const h = opts.half ?? new THREE.Vector3(0.4, 0.4, 0.4);
      cd = RAPIER.ColliderDesc.cuboid(Math.max(0.05, h.x), Math.max(0.05, h.y), Math.max(0.05, h.z));
    }
    cd.setCollisionGroups(MASKS.debris).setRestitution(0.25).setFriction(0.8);
    if (opts.mass) cd.setMass(opts.mass);
    else cd.setDensity(opts.density ?? 0.5);
    const owner: Owner = { kind: 'debris' };
    this.ctx.physics.addCollider(cd, body, owner);
    opts.mesh.position.copy(opts.pos);
    opts.mesh.quaternion.copy(opts.quat);
    this.ctx.scene.add(opts.mesh);
    this.pieces.push({
      mesh: opts.mesh,
      body,
      life: (opts.life ?? 16) * rand(0.85, 1.15),
      fade: 1.6,
      scale0: opts.mesh.scale.x,
      smoke: opts.smoke ?? false,
      smokeT: 0,
      owner,
    });
  }

  private remove(i: number) {
    const p = this.pieces[i];
    this.ctx.scene.remove(p.mesh);
    this.ctx.physics.removeBody(p.body);
    this.pieces.splice(i, 1);
  }

  update(dt: number) {
    for (let i = this.pieces.length - 1; i >= 0; i--) {
      const p = this.pieces[i];
      p.life -= dt;
      const t = p.body.translation();
      const r = p.body.rotation();
      p.mesh.position.set(t.x, t.y, t.z);
      this.tmpQ.set(r.x, r.y, r.z, r.w);
      p.mesh.quaternion.copy(this.tmpQ);
      if (p.life < p.fade) p.mesh.scale.setScalar(Math.max(0.001, (p.life / p.fade) * p.scale0));
      if (p.smoke && p.life > 2) {
        p.smokeT += dt;
        if (p.smokeT > 0.1) {
          p.smokeT = 0;
          this.ctx.fx.smokePuff(p.mesh.position, null, 1.1, 1.8, true, 0.5, 1.0);
          if (Math.random() < 0.25) this.ctx.fx.glow(p.mesh.position, 1.2, 0.2, COL.fire0, 0.6);
        }
      }
      if (p.life <= 0 || t.y < -20) this.remove(i);
    }
  }

  clear() {
    for (let i = this.pieces.length - 1; i >= 0; i--) this.remove(i);
  }
}
