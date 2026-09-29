import * as THREE from 'three';
import type { ExplosionOpts, GameCtx } from './types';
import { G } from '../physics/world';
import { clamp } from '../core/math';

const _dir = new THREE.Vector3();
const _pt = new THREE.Vector3();

/**
 * Central explosion handler: visuals + audio + camera shake, radial damage to enemies (player explosions) or to the
 * player (enemy explosions), damage to destructibles/props, and velocity kicks on every dynamic body in range.
 */
export function explode(ctx: GameCtx, o: ExplosionOpts) {
  const scale = o.scale ?? 1;
  ctx.fx.explosion(o.pos, scale, { color: o.color });
  ctx.audio.explosion(scale, o.pos);
  const camD = o.pos.distanceTo(ctx.camera.position);
  ctx.shake(clamp((scale * 0.5) / (1 + camD / 26), 0, 1.2));

  const falloff = (d: number) => Math.pow(1 - clamp(d / o.radius, 0, 1), 1.4);

  if (o.team === 'player') {
    for (const t of ctx.enemies.targets) {
      if (o.ignore === t) continue;
      // the boss is hit on the surface of its shield/hull sphere, so its full radius counts; small targets get a margin
      const d = t.pos.distanceTo(o.pos) - t.radius * (t.kind === 'boss' ? 1 : 0.7);
      if (d >= o.radius) continue;
      const f = falloff(Math.max(0, d));
      _dir.copy(t.pos).sub(o.pos).normalize();
      _pt.copy(o.pos).addScaledVector(_dir, Math.min(t.pos.distanceTo(o.pos), t.radius));
      const shielded = t.shieldFraction() > 0;
      t.takeDamage(o.damage * f, { point: _pt.clone(), normal: _dir.clone().negate(), dir: _dir.clone(), source: o.source, kick: o.kick * f * 0.3 });
      ctx.bus.emit('hit', { shield: shielded });
      t.kick(_dir, o.kick * f);
    }
    // enemy missiles caught in the blast detonate (nice chain reactions)
    for (const m of ctx.projectiles.missiles) {
      if (!m.alive || m.spec.team !== 'enemy') continue;
      if (m.pos.distanceTo(o.pos) < o.radius * 0.7) m.takeDamage(999);
    }
    for (const b of ctx.projectiles.bolts) {
      if (b.alive && b.pos.distanceTo(o.pos) < o.radius * 0.7) b.takeDamage();
    }
  } else {
    const p = ctx.player;
    if (p.alive) {
      const d = p.pos.distanceTo(o.pos) - 0.6;
      if (d < o.radius) {
        const f = falloff(Math.max(0, d));
        _dir.copy(p.pos).sub(o.pos).normalize();
        p.takeDamage(o.damage * f, { point: p.pos.clone(), dir: _dir.clone(), normal: _dir.clone().negate(), source: o.source });
        p.kick(_dir, o.kick * f);
      }
    }
  }

  ctx.world.destructibles.blast(o.pos, o.radius * 1.15, o.damage * 1.2, o.kick);
  ctx.world.props.blast(o.pos, o.radius, o.damage, o.kick);

  // physical kick for debris / other free bodies (mass-independent velocity change)
  ctx.physics.overlapSphere(o.pos, o.radius, G.DEBRIS, (c) => {
    const body = c.parent();
    if (!body || !body.isDynamic()) return true;
    const t = body.translation();
    _dir.set(t.x - o.pos.x, t.y - o.pos.y + 0.5, t.z - o.pos.z);
    const d = _dir.length();
    if (d > 1e-3) _dir.multiplyScalar(1 / d);
    const f = falloff(d);
    const m = body.mass();
    body.applyImpulse({ x: _dir.x * o.kick * f * m, y: _dir.y * o.kick * f * m, z: _dir.z * o.kick * f * m }, true);
    return true;
  });
}
