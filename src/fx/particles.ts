import * as THREE from 'three';

export interface ParticleParams {
  x: number;
  y: number;
  z: number;
  vx?: number;
  vy?: number;
  vz?: number;
  life: number;
  size0: number;
  size1?: number;
  /** linear HDR colour at birth / death */
  c0: readonly [number, number, number];
  c1?: readonly [number, number, number];
  a0?: number;
  a1?: number;
  drag?: number;
  gravity?: number;
  rot?: number;
  rotVel?: number;
  /** >0 : stretch quad along its screen-space velocity (sparks / streaks) */
  stretch?: number;
}

const VERT = /* glsl */ `
attribute vec3 iPos;
attribute vec3 iVel;
attribute vec4 iData; // size, rot, alpha, stretch
attribute vec3 iColor;
varying vec2 vUv;
varying vec3 vColor;
varying float vAlpha;
varying float vSeed;
void main() {
  vUv = position.xy;
  vColor = iColor;
  vec4 mv = viewMatrix * vec4(iPos, 1.0);
  float size = iData.x;
  float rot = iData.y;
  float stretch = iData.w;
  vec2 p = position.xy;
  if (stretch > 0.0) {
    vec3 vv = (viewMatrix * vec4(iVel, 0.0)).xyz;
    float sp = length(vv.xy);
    vec2 dir = sp > 1e-3 ? vv.xy / sp : vec2(1.0, 0.0);
    float len = size * (1.0 + stretch * sp * 0.045);
    vec2 perp = vec2(-dir.y, dir.x);
    mv.xy += dir * p.x * len + perp * p.y * size * 0.45;
  } else {
    float c = cos(rot);
    float s = sin(rot);
    mv.xy += vec2(c * p.x - s * p.y, s * p.x + c * p.y) * size;
  }
  vAlpha = iData.z * smoothstep(0.4, 3.5, -mv.z);
  vSeed = rot * 7.13 + size;
  gl_Position = projectionMatrix * mv;
}
`;

const FRAG_ADD = /* glsl */ `
varying vec2 vUv;
varying vec3 vColor;
varying float vAlpha;
void main() {
  float d = length(vUv);
  if (d > 1.0) discard;
  float a = 1.0 - d;
  a = a * a * (1.0 + 1.6 * a);
  gl_FragColor = vec4(vColor, a * vAlpha);
}
`;

const FRAG_SMOKE = /* glsl */ `
varying vec2 vUv;
varying vec3 vColor;
varying float vAlpha;
varying float vSeed;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
void main() {
  float d = length(vUv);
  if (d > 1.0) discard;
  float n = vnoise(vUv * 2.6 + vSeed) * 0.65 + vnoise(vUv * 5.3 - vSeed * 1.7) * 0.35;
  float edge = 1.0 - smoothstep(0.25, 1.0, d + (n - 0.5) * 0.55);
  float shade = 0.72 + 0.5 * n;
  gl_FragColor = vec4(vColor * shade, edge * vAlpha);
}
`;

class Layer {
  readonly mesh: THREE.Mesh;
  readonly cap: number;
  count = 0;
  private pos: Float32Array;
  private vel: Float32Array;
  private age: Float32Array;
  private life: Float32Array;
  private s0: Float32Array;
  private s1: Float32Array;
  private c0: Float32Array;
  private c1: Float32Array;
  private a0: Float32Array;
  private a1: Float32Array;
  private drag: Float32Array;
  private grav: Float32Array;
  private rot: Float32Array;
  private rotV: Float32Array;
  private stretch: Float32Array;
  private gPos: THREE.InstancedBufferAttribute;
  private gVel: THREE.InstancedBufferAttribute;
  private gData: THREE.InstancedBufferAttribute;
  private gColor: THREE.InstancedBufferAttribute;
  private geometry: THREE.InstancedBufferGeometry;

  constructor(cap: number, additive: boolean) {
    this.cap = cap;
    const f = (n: number) => new Float32Array(cap * n);
    this.pos = f(3);
    this.vel = f(3);
    this.age = f(1);
    this.life = f(1);
    this.s0 = f(1);
    this.s1 = f(1);
    this.c0 = f(3);
    this.c1 = f(3);
    this.a0 = f(1);
    this.a1 = f(1);
    this.drag = f(1);
    this.grav = f(1);
    this.rot = f(1);
    this.rotV = f(1);
    this.stretch = f(1);

    const g = new THREE.InstancedBufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
    g.setIndex([0, 1, 2, 0, 2, 3]);
    this.gPos = new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3).setUsage(THREE.DynamicDrawUsage);
    this.gVel = new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3).setUsage(THREE.DynamicDrawUsage);
    this.gData = new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4).setUsage(THREE.DynamicDrawUsage);
    this.gColor = new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3).setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('iPos', this.gPos);
    g.setAttribute('iVel', this.gVel);
    g.setAttribute('iData', this.gData);
    g.setAttribute('iColor', this.gColor);
    g.instanceCount = 0;
    this.geometry = g;
    const mat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: additive ? FRAG_ADD : FRAG_SMOKE,
      transparent: true,
      depthWrite: false,
      depthTest: true,
      blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
      toneMapped: false,
      fog: false,
    });
    this.mesh = new THREE.Mesh(g, mat);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = additive ? 20 : 10;
  }

  emit(p: ParticleParams) {
    let i: number;
    if (this.count < this.cap) i = this.count++;
    else i = Math.floor(Math.random() * this.cap); // overwrite a random old one when saturated
    const i3 = i * 3;
    this.pos[i3] = p.x;
    this.pos[i3 + 1] = p.y;
    this.pos[i3 + 2] = p.z;
    this.vel[i3] = p.vx ?? 0;
    this.vel[i3 + 1] = p.vy ?? 0;
    this.vel[i3 + 2] = p.vz ?? 0;
    this.age[i] = 0;
    this.life[i] = p.life;
    this.s0[i] = p.size0;
    this.s1[i] = p.size1 ?? p.size0;
    const c1 = p.c1 ?? p.c0;
    this.c0[i3] = p.c0[0];
    this.c0[i3 + 1] = p.c0[1];
    this.c0[i3 + 2] = p.c0[2];
    this.c1[i3] = c1[0];
    this.c1[i3 + 1] = c1[1];
    this.c1[i3 + 2] = c1[2];
    this.a0[i] = p.a0 ?? 1;
    this.a1[i] = p.a1 ?? 0;
    this.drag[i] = p.drag ?? 0;
    this.grav[i] = p.gravity ?? 0;
    this.rot[i] = p.rot ?? Math.random() * 6.283;
    this.rotV[i] = p.rotVel ?? 0;
    this.stretch[i] = p.stretch ?? 0;
  }

  private moveLast(dst: number) {
    const s = --this.count;
    if (dst === s) return;
    const copy = (a: Float32Array, n: number) => {
      for (let k = 0; k < n; k++) a[dst * n + k] = a[s * n + k];
    };
    copy(this.pos, 3);
    copy(this.vel, 3);
    copy(this.age, 1);
    copy(this.life, 1);
    copy(this.s0, 1);
    copy(this.s1, 1);
    copy(this.c0, 3);
    copy(this.c1, 3);
    copy(this.a0, 1);
    copy(this.a1, 1);
    copy(this.drag, 1);
    copy(this.grav, 1);
    copy(this.rot, 1);
    copy(this.rotV, 1);
    copy(this.stretch, 1);
  }

  update(dt: number) {
    const gp = this.gPos.array as Float32Array;
    const gv = this.gVel.array as Float32Array;
    const gd = this.gData.array as Float32Array;
    const gc = this.gColor.array as Float32Array;
    let i = 0;
    while (i < this.count) {
      const age = (this.age[i] += dt);
      const life = this.life[i];
      if (age >= life) {
        this.moveLast(i);
        continue;
      }
      const i3 = i * 3;
      const damp = Math.exp(-this.drag[i] * dt);
      this.vel[i3] *= damp;
      this.vel[i3 + 1] = this.vel[i3 + 1] * damp - this.grav[i] * dt;
      this.vel[i3 + 2] *= damp;
      this.pos[i3] += this.vel[i3] * dt;
      this.pos[i3 + 1] += this.vel[i3 + 1] * dt;
      this.pos[i3 + 2] += this.vel[i3 + 2] * dt;
      this.rot[i] += this.rotV[i] * dt;
      const t = age / life;
      const inv = 1 - t;
      const fadeIn = Math.min(1, age * 40);
      gp[i3] = this.pos[i3];
      gp[i3 + 1] = this.pos[i3 + 1];
      gp[i3 + 2] = this.pos[i3 + 2];
      gv[i3] = this.vel[i3];
      gv[i3 + 1] = this.vel[i3 + 1];
      gv[i3 + 2] = this.vel[i3 + 2];
      const i4 = i * 4;
      gd[i4] = this.s0[i] * inv + this.s1[i] * t;
      gd[i4 + 1] = this.rot[i];
      gd[i4 + 2] = (this.a0[i] * inv + this.a1[i] * t) * fadeIn;
      gd[i4 + 3] = this.stretch[i];
      gc[i3] = this.c0[i3] * inv + this.c1[i3] * t;
      gc[i3 + 1] = this.c0[i3 + 1] * inv + this.c1[i3 + 1] * t;
      gc[i3 + 2] = this.c0[i3 + 2] * inv + this.c1[i3 + 2] * t;
      i++;
    }
    this.geometry.instanceCount = this.count;
    this.gPos.needsUpdate = true;
    this.gVel.needsUpdate = true;
    this.gData.needsUpdate = true;
    this.gColor.needsUpdate = true;
  }

  clear() {
    this.count = 0;
    this.geometry.instanceCount = 0;
  }
}

/** Two pooled instanced-billboard layers: additive (glow, fire, sparks) and alpha-blended (smoke, dust). */
export class Particles {
  readonly add: Layer;
  readonly smoke: Layer;

  constructor(scene: THREE.Scene, capAdd = 9000, capSmoke = 6000) {
    this.add = new Layer(capAdd, true);
    this.smoke = new Layer(capSmoke, false);
    scene.add(this.smoke.mesh, this.add.mesh);
  }

  update(dt: number) {
    this.add.update(dt);
    this.smoke.update(dt);
  }

  clear() {
    this.add.clear();
    this.smoke.clear();
  }

  get activeCount() {
    return this.add.count + this.smoke.count;
  }
}
