import * as THREE from 'three';
import { Particles } from './particles';
import { rand } from '../core/rng';

type C3 = readonly [number, number, number];

export const COL = {
  fire0: [3.4, 1.5, 0.4] as C3,
  fire1: [0.55, 0.13, 0.03] as C3,
  hot: [4.5, 3.2, 1.6] as C3,
  spark0: [4.0, 2.4, 0.9] as C3,
  spark1: [1.0, 0.28, 0.05] as C3,
  smokeDark: [0.2, 0.19, 0.19] as C3,
  smokeLight: [0.62, 0.6, 0.58] as C3,
  smokeEnd: [0.1, 0.1, 0.11] as C3,
  cyan: [0.5, 2.6, 4.0] as C3,
  flame: [0.22, 1.05, 1.8] as C3,
  flameBoost: [0.7, 1.5, 2.1] as C3,
  cyanDim: [0.05, 0.5, 1.4] as C3,
  white: [3, 3, 3] as C3,
  red: [4.0, 0.35, 0.2] as C3,
  redDim: [1.2, 0.05, 0.03] as C3,
  plasma: [3.6, 0.5, 2.6] as C3,
  amber: [3.4, 1.6, 0.25] as C3,
  dust: [0.42, 0.36, 0.3] as C3,
};

/** Pooled point lights for muzzle flashes / explosions (fixed count => no shader recompiles). */
class FlashLights {
  private lights: THREE.PointLight[] = [];
  private t: number[] = [];
  private dur: number[] = [];
  private peak: number[] = [];
  private next = 0;

  constructor(scene: THREE.Scene, count = 5) {
    for (let i = 0; i < count; i++) {
      const l = new THREE.PointLight(0xffaa55, 0, 90, 2);
      l.castShadow = false;
      scene.add(l);
      this.lights.push(l);
      this.t.push(1);
      this.dur.push(1);
      this.peak.push(0);
    }
  }

  flash(pos: THREE.Vector3, color: number, intensity: number, duration: number, distance = 90) {
    const i = this.next;
    this.next = (this.next + 1) % this.lights.length;
    const l = this.lights[i];
    l.position.copy(pos);
    l.color.setHex(color);
    l.distance = distance;
    this.peak[i] = intensity;
    this.t[i] = 0;
    this.dur[i] = duration;
    l.intensity = intensity;
  }

  update(dt: number) {
    for (let i = 0; i < this.lights.length; i++) {
      if (this.t[i] >= this.dur[i]) {
        this.lights[i].intensity = 0;
        continue;
      }
      this.t[i] += dt;
      const k = Math.max(0, 1 - this.t[i] / this.dur[i]);
      this.lights[i].intensity = this.peak[i] * k * k;
    }
  }
}

const BEAM_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
const BEAM_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uAlpha;
varying vec2 vUv;
void main() {
  float across = clamp(1.0 - abs(vUv.x * 2.0 - 1.0), 0.0, 1.0);
  float core = across * across * across;
  float glow = pow(across + 1e-4, 1.2);
  float ends = smoothstep(0.0, 0.03, vUv.y) * (1.0 - smoothstep(0.94, 1.0, vUv.y));
  vec3 col = uColor * (0.5 + 2.4 * core) + vec3(1.0) * core * 1.2;
  gl_FragColor = vec4(col, (glow * 0.85 + core) * uAlpha * ends);
}
`;

class BeamPool {
  private meshes: THREE.Mesh[] = [];
  private mats: THREE.ShaderMaterial[] = [];
  private life: number[] = [];
  private maxLife: number[] = [];
  private next = 0;

  constructor(scene: THREE.Scene, count = 24) {
    // two crossed quads along +Z from 0..1, so it reads from every angle
    const g = new THREE.BufferGeometry();
    const pos: number[] = [];
    const uv: number[] = [];
    const idx: number[] = [];
    const quad = (ax: 'x' | 'y', base: number) => {
      const a = ax === 'x' ? [-0.5, 0, 0] : [0, -0.5, 0];
      const b = ax === 'x' ? [0.5, 0, 0] : [0, 0.5, 0];
      pos.push(a[0], a[1], 0, b[0], b[1], 0, b[0], b[1], 1, a[0], a[1], 1);
      uv.push(0, 0, 1, 0, 1, 1, 0, 1);
      idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    };
    quad('x', 0);
    quad('y', 4);
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    for (let i = 0; i < count; i++) {
      const mat = new THREE.ShaderMaterial({
        vertexShader: BEAM_VERT,
        fragmentShader: BEAM_FRAG,
        uniforms: { uColor: { value: new THREE.Color(1, 1, 1) }, uAlpha: { value: 0 } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        toneMapped: false,
        fog: false,
      });
      const m = new THREE.Mesh(g, mat);
      m.visible = false;
      m.frustumCulled = false;
      m.renderOrder = 25;
      scene.add(m);
      this.meshes.push(m);
      this.mats.push(mat);
      this.life.push(0);
      this.maxLife.push(1);
    }
  }

  spawn(from: THREE.Vector3, to: THREE.Vector3, color: C3, width: number, life: number) {
    const i = this.next;
    this.next = (this.next + 1) % this.meshes.length;
    const m = this.meshes[i];
    m.visible = true;
    m.position.copy(from);
    m.lookAt(to);
    const len = from.distanceTo(to);
    m.scale.set(width, width, len);
    this.mats[i].uniforms.uColor.value.setRGB(color[0], color[1], color[2]);
    this.mats[i].uniforms.uAlpha.value = 1;
    this.life[i] = life;
    this.maxLife[i] = life;
  }

  update(dt: number) {
    for (let i = 0; i < this.meshes.length; i++) {
      if (!this.meshes[i].visible) continue;
      this.life[i] -= dt;
      if (this.life[i] <= 0) {
        this.meshes[i].visible = false;
        continue;
      }
      this.mats[i].uniforms.uAlpha.value = this.life[i] / this.maxLife[i];
    }
  }
}

const RING_FRAG = /* glsl */ `
uniform float uAlpha;
uniform vec3 uColor;
varying vec2 vUv;
void main() {
  float r = length(vUv - 0.5) * 2.0;
  float ring = smoothstep(0.72, 0.93, r) * (1.0 - smoothstep(0.94, 1.0, r));
  gl_FragColor = vec4(uColor, ring * uAlpha);
}
`;

class RingPool {
  private meshes: THREE.Mesh[] = [];
  private t: number[] = [];
  private dur: number[] = [];
  private radius: number[] = [];
  private next = 0;

  constructor(scene: THREE.Scene, private camera: THREE.Camera, count = 10) {
    const g = new THREE.PlaneGeometry(2, 2);
    for (let i = 0; i < count; i++) {
      const mat = new THREE.ShaderMaterial({
        vertexShader: BEAM_VERT,
        fragmentShader: RING_FRAG,
        uniforms: { uColor: { value: new THREE.Color(1, 1, 1) }, uAlpha: { value: 0 } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
        fog: false,
        side: THREE.DoubleSide,
      });
      const m = new THREE.Mesh(g, mat);
      m.visible = false;
      m.frustumCulled = false;
      m.renderOrder = 24;
      scene.add(m);
      this.meshes.push(m);
      this.t.push(0);
      this.dur.push(1);
      this.radius.push(1);
    }
  }

  spawn(pos: THREE.Vector3, radius: number, dur: number, color: C3) {
    const i = this.next;
    this.next = (this.next + 1) % this.meshes.length;
    const m = this.meshes[i];
    m.visible = true;
    m.position.copy(pos);
    this.t[i] = 0;
    this.dur[i] = dur;
    this.radius[i] = radius;
    (m.material as THREE.ShaderMaterial).uniforms.uColor.value.setRGB(color[0], color[1], color[2]);
  }

  update(dt: number) {
    for (let i = 0; i < this.meshes.length; i++) {
      const m = this.meshes[i];
      if (!m.visible) continue;
      this.t[i] += dt;
      const k = this.t[i] / this.dur[i];
      if (k >= 1) {
        m.visible = false;
        continue;
      }
      const e = 1 - Math.pow(1 - k, 3);
      m.quaternion.copy(this.camera.quaternion);
      m.scale.setScalar(this.radius[i] * (0.15 + 0.85 * e));
      (m.material as THREE.ShaderMaterial).uniforms.uAlpha.value = (1 - k) * 0.9;
    }
  }
}

export class Effects {
  readonly particles: Particles;
  readonly lights: FlashLights;
  readonly beams: BeamPool;
  readonly rings: RingPool;

  constructor(readonly scene: THREE.Scene, camera: THREE.Camera) {
    this.particles = new Particles(scene);
    this.lights = new FlashLights(scene);
    this.beams = new BeamPool(scene);
    this.rings = new RingPool(scene, camera);
  }

  update(dt: number) {
    this.particles.update(dt);
    this.lights.update(dt);
    this.beams.update(dt);
    this.rings.update(dt);
  }

  clear() {
    this.particles.clear();
  }

  // -------------------------------------------------------------------- emitters

  glow(p: THREE.Vector3, size: number, life: number, color: C3, alpha = 1, vel?: THREE.Vector3) {
    this.particles.add.emit({
      x: p.x, y: p.y, z: p.z, vx: vel?.x, vy: vel?.y, vz: vel?.z,
      life, size0: size, size1: size * 0.3, c0: color, c1: color, a0: alpha, a1: 0,
    });
  }

  sparks(p: THREE.Vector3, normal: THREE.Vector3 | null, count: number, speed: number, color0: C3 = COL.spark0, color1: C3 = COL.spark1, life = 0.6) {
    for (let i = 0; i < count; i++) {
      const dx = rand(-1, 1), dy = rand(-1, 1), dz = rand(-1, 1);
      let vx = dx, vy = dy, vz = dz;
      if (normal) {
        vx = normal.x * 1.4 + dx * 0.9;
        vy = normal.y * 1.4 + dy * 0.9;
        vz = normal.z * 1.4 + dz * 0.9;
      }
      const l = Math.hypot(vx, vy, vz) || 1;
      const sp = speed * rand(0.35, 1);
      this.particles.add.emit({
        x: p.x, y: p.y, z: p.z, vx: (vx / l) * sp, vy: (vy / l) * sp, vz: (vz / l) * sp,
        life: life * rand(0.6, 1.2), size0: 0.09, size1: 0.03, c0: color0, c1: color1, a0: 1, a1: 0,
        drag: 1.2, gravity: 9.8, stretch: 1.0,
      });
    }
  }

  /** small impact flash + sparks (repulsor hits, bullets) */
  impact(p: THREE.Vector3, normal: THREE.Vector3 | null, color0: C3 = COL.spark0, color1: C3 = COL.spark1, scale = 1) {
    this.particles.add.emit({ x: p.x, y: p.y, z: p.z, life: 0.12, size0: 0.9 * scale, size1: 0.25 * scale, c0: COL.hot, c1: color0, a0: 1, a1: 0 });
    this.sparks(p, normal, Math.round(7 * scale), 16 * scale, color0, color1, 0.45);
    this.particles.smoke.emit({
      x: p.x, y: p.y, z: p.z, vy: 1.2, life: 0.9, size0: 0.35 * scale, size1: 1.3 * scale,
      c0: COL.smokeLight, c1: COL.smokeEnd, a0: 0.35, a1: 0, drag: 1.5,
    });
  }

  muzzleFlash(p: THREE.Vector3, dir: THREE.Vector3, scale = 1, color: C3 = COL.cyan) {
    this.particles.add.emit({ x: p.x, y: p.y, z: p.z, life: 0.09, size0: 0.55 * scale, size1: 0.2 * scale, c0: COL.white, c1: color, a0: 1, a1: 0 });
    for (let i = 0; i < 4; i++) {
      this.particles.add.emit({
        x: p.x, y: p.y, z: p.z,
        vx: dir.x * rand(8, 22) + rand(-3, 3), vy: dir.y * rand(8, 22) + rand(-3, 3), vz: dir.z * rand(8, 22) + rand(-3, 3),
        life: rand(0.08, 0.16), size0: 0.1 * scale, size1: 0.02, c0: color, c1: COL.cyanDim, a0: 1, a1: 0, stretch: 1.4,
      });
    }
  }

  smokePuff(p: THREE.Vector3, vel: THREE.Vector3 | null, size: number, life: number, dark = false, alpha = 0.55, rise = 0.8) {
    this.particles.smoke.emit({
      x: p.x, y: p.y, z: p.z, vx: vel?.x ?? 0, vy: vel?.y ?? 0, vz: vel?.z ?? 0,
      life, size0: size * 0.5, size1: size * 1.6, c0: dark ? COL.smokeDark : COL.smokeLight, c1: COL.smokeEnd,
      a0: alpha, a1: 0, drag: 0.8, gravity: -rise, rotVel: rand(-0.6, 0.6),
    });
  }

  /** missile smoke-trail segment; call every frame per missile with several interpolated positions */
  trail(p: THREE.Vector3, vel: THREE.Vector3, scale = 1, hot = true) {
    this.particles.smoke.emit({
      x: p.x + rand(-0.05, 0.05), y: p.y + rand(-0.05, 0.05), z: p.z + rand(-0.05, 0.05),
      vx: vel.x * 0.02 + rand(-0.4, 0.4), vy: vel.y * 0.02 + rand(-0.2, 0.6), vz: vel.z * 0.02 + rand(-0.4, 0.4),
      life: rand(1.1, 1.7) * (0.6 + 0.4 * scale), size0: 0.28 * scale, size1: 1.5 * scale,
      c0: COL.smokeLight, c1: COL.smokeEnd, a0: 0.5, a1: 0, drag: 0.5, gravity: -0.35, rotVel: rand(-1, 1),
    });
    if (hot) {
      this.particles.add.emit({
        x: p.x, y: p.y, z: p.z, life: 0.16, size0: 0.55 * scale, size1: 0.12 * scale,
        c0: COL.amber, c1: COL.fire1, a0: 0.9, a1: 0,
      });
    }
  }

  /** thruster / exhaust flame from a nozzle along `dir` (unit, the direction the exhaust travels).
   *  Particles inherit the emitter velocity so the flame stays a compact cone attached to the nozzle. */
  flame(p: THREE.Vector3, dir: THREE.Vector3, power: number, color0: C3, color1: C3, size = 0.35, inheritVel?: THREE.Vector3) {
    const sp = (6 + 12 * power) * rand(0.75, 1.1);
    const ix = inheritVel?.x ?? 0;
    const iy = inheritVel?.y ?? 0;
    const iz = inheritVel?.z ?? 0;
    this.particles.add.emit({
      x: p.x + dir.x * rand(0, 0.1), y: p.y + dir.y * rand(0, 0.1), z: p.z + dir.z * rand(0, 0.1),
      vx: dir.x * sp + ix + rand(-0.5, 0.5), vy: dir.y * sp + iy + rand(-0.5, 0.5), vz: dir.z * sp + iz + rand(-0.5, 0.5),
      life: (0.07 + 0.1 * power) * rand(0.8, 1.2), size0: size * (0.9 + 0.5 * power), size1: size * 0.2,
      c0: color0, c1: color1, a0: 0.8, a1: 0, drag: 0.4,
    });
  }

  shockwave(p: THREE.Vector3, radius: number, color: C3 = COL.amber, dur = 0.5) {
    this.rings.spawn(p, radius, dur, color);
  }

  beam(from: THREE.Vector3, to: THREE.Vector3, color: C3, width: number, life: number) {
    this.beams.spawn(from, to, color, width, life);
  }

  /** big fiery explosion. scale 1 ~ a missile hit */
  explosion(p: THREE.Vector3, scale = 1, opts: { smoke?: boolean; light?: boolean; ring?: boolean; color?: 'fire' | 'plasma' | 'cyan' } = {}) {
    const P = this.particles;
    const s = scale;
    const kind = opts.color ?? 'fire';
    const c0 = kind === 'plasma' ? COL.plasma : kind === 'cyan' ? COL.cyan : COL.fire0;
    const c1 = kind === 'plasma' ? ([0.4, 0.05, 0.3] as C3) : kind === 'cyan' ? COL.cyanDim : COL.fire1;
    const hot: C3 = kind === 'cyan' ? [1.6, 2.6, 3.4] : [3.0, 2.2, 1.2];
    P.add.emit({ x: p.x, y: p.y, z: p.z, life: 0.16, size0: 2.2 * s, size1: 7 * s, c0: hot, c1: c0, a0: 0.85, a1: 0 });
    P.add.emit({ x: p.x, y: p.y, z: p.z, life: 0.4, size0: 2 * s, size1: 5.5 * s, c0: c0, c1: c1, a0: 0.6, a1: 0 });
    const nFire = Math.round(12 * Math.min(2, s + 0.4));
    for (let i = 0; i < nFire; i++) {
      const v = rand(3, 11) * s;
      const a = rand(0, 6.283);
      const b = rand(-0.5, 1);
      P.add.emit({
        x: p.x + rand(-0.3, 0.3) * s, y: p.y + rand(-0.3, 0.3) * s, z: p.z + rand(-0.3, 0.3) * s,
        vx: Math.cos(a) * v, vy: b * v + 1, vz: Math.sin(a) * v,
        life: rand(0.4, 0.95), size0: rand(0.9, 1.8) * s, size1: rand(2.4, 4.2) * s, c0: c0, c1: c1, a0: 0.6, a1: 0, drag: 2.4, rotVel: rand(-2, 2),
      });
    }
    this.sparks(p, null, Math.round(24 * Math.min(2, s)), 42 * s, kind === 'plasma' ? COL.plasma : COL.spark0, kind === 'plasma' ? c1 : COL.spark1, 0.9);
    if (opts.smoke !== false) {
      const nSmoke = Math.round(10 * Math.min(2, s + 0.3));
      for (let i = 0; i < nSmoke; i++) {
        const a = rand(0, 6.283);
        const v = rand(1, 4.5) * s;
        P.smoke.emit({
          x: p.x + rand(-0.6, 0.6) * s, y: p.y + rand(-0.4, 0.6) * s, z: p.z + rand(-0.6, 0.6) * s,
          vx: Math.cos(a) * v, vy: rand(1.5, 5) * s, vz: Math.sin(a) * v,
          life: rand(2.2, 4.2), size0: rand(1.6, 2.8) * s, size1: rand(5.5, 9) * s,
          c0: i % 3 === 0 ? COL.smokeLight : COL.smokeDark, c1: COL.smokeEnd, a0: 0.55, a1: 0, drag: 0.9, gravity: -0.6, rotVel: rand(-0.5, 0.5),
        });
      }
    }
    if (opts.ring !== false) this.shockwave(p, 9 * s, kind === 'fire' ? COL.amber : c0, 0.45);
    if (opts.light !== false) this.lights.flash(p, kind === 'plasma' ? 0xff44cc : kind === 'cyan' ? 0x55ccff : 0xff9a44, 3200 * Math.pow(s, 1.2), 0.45, 70 + 30 * s);
  }

  /** ground / rubble dust cloud (destruction) */
  dust(p: THREE.Vector3, radius: number, count = 10) {
    for (let i = 0; i < count; i++) {
      const a = rand(0, 6.283);
      const r = rand(0, radius);
      const v = rand(2, 8);
      this.particles.smoke.emit({
        x: p.x + Math.cos(a) * r, y: p.y + rand(0, radius * 0.4), z: p.z + Math.sin(a) * r,
        vx: Math.cos(a) * v, vy: rand(0.5, 4), vz: Math.sin(a) * v,
        life: rand(2.0, 4.0), size0: rand(0.6, 1.2) * Math.max(1.2, radius * 0.6), size1: rand(2.2, 3.8) * Math.max(1.2, radius * 0.6), c0: COL.dust, c1: COL.smokeEnd, a0: 0.32, a1: 0, drag: 1.3, gravity: -0.15, rotVel: rand(-0.4, 0.4),
      });
    }
  }
}
