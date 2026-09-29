import * as THREE from 'three';

const VERT = /* glsl */ `
varying vec3 vObjDir;
varying vec3 vWorldNormal;
varying vec3 vViewDir;
void main() {
  vObjDir = normalize(position);
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorldNormal = normalize(mat3(modelMatrix) * normal);
  vViewDir = normalize(cameraPosition - wp.xyz);
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`;

const FRAG = /* glsl */ `
uniform float uTime;
uniform float uIntegrity;   // 0..1 (drives flicker + opacity)
uniform float uBreak;       // 0..1 dissolve when breaking
uniform float uPulse;       // extra flash 0..1
uniform float uAppear;      // 0..1 fade in when (re)generating
uniform vec4 uHit[4];       // xyz = object-space direction, w = age (s), <0 inactive
varying vec3 vObjDir;
varying vec3 vWorldNormal;
varying vec3 vViewDir;

vec3 hash3(vec3 p) {
  p = vec3(dot(p, vec3(127.1, 311.7, 74.7)), dot(p, vec3(269.5, 183.3, 246.1)), dot(p, vec3(113.5, 271.9, 124.6)));
  return fract(sin(p) * 43758.5453123);
}
// returns vec2(F1, F2) distance to nearest / second nearest feature point
vec2 worley(vec3 x) {
  vec3 p = floor(x);
  vec3 f = fract(x);
  float f1 = 8.0;
  float f2 = 8.0;
  for (int k = -1; k <= 1; k++)
    for (int j = -1; j <= 1; j++)
      for (int i = -1; i <= 1; i++) {
        vec3 b = vec3(float(i), float(j), float(k));
        vec3 r = b + hash3(p + b) - f;
        float d = dot(r, r);
        if (d < f1) { f2 = f1; f1 = d; }
        else if (d < f2) { f2 = d; }
      }
  return sqrt(vec2(f1, f2));
}
float noise3(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float n = mix(mix(mix(hash3(i).x, hash3(i + vec3(1,0,0)).x, f.x), mix(hash3(i + vec3(0,1,0)).x, hash3(i + vec3(1,1,0)).x, f.x), f.y),
                mix(mix(hash3(i + vec3(0,0,1)).x, hash3(i + vec3(1,0,1)).x, f.x), mix(hash3(i + vec3(0,1,1)).x, hash3(i + vec3(1,1,1)).x, f.x), f.y), f.z);
  return n;
}

void main() {
  vec3 d = normalize(vObjDir);
  vec3 n = normalize(vWorldNormal);
  vec3 v = normalize(vViewDir);
  float ndv = abs(dot(n, v));
  float fres = pow(max(1.0 - ndv, 0.0), 2.4);

  // hex-ish cracked cells on the sphere (voronoi edges)
  vec2 w = worley(d * 5.2 + vec3(0.0, uTime * 0.03, 0.0));
  float edge = 1.0 - smoothstep(0.0, 0.085, w.y - w.x);
  float cell = hash3(floor(d * 5.2 * 0.0 + vec3(w.x * 13.0, w.y * 7.0, 1.0))).x;

  // hit ripples
  float ripple = 0.0;
  for (int i = 0; i < 4; i++) {
    vec4 h = uHit[i];
    if (h.w >= 0.0) {
      float ang = acos(clamp(dot(d, normalize(h.xyz)), -1.0, 1.0));
      float ring = sin(ang * 16.0 - h.w * 16.0) * 0.5 + 0.5;
      float fade = exp(-ang * 2.6) * exp(-h.w * 2.2);
      ripple += ring * fade + exp(-ang * 7.0) * exp(-h.w * 5.0) * 1.6;
      edge += exp(-ang * 4.0) * exp(-h.w * 2.0) * 0.9;
    }
  }

  float flicker = 1.0;
  if (uIntegrity < 0.35) flicker = 0.55 + 0.45 * step(0.35, noise3(d * 6.0 + vec3(uTime * 14.0)));
  float sweep = 0.5 + 0.5 * sin(d.y * 9.0 - uTime * 1.6);

  vec3 base = vec3(0.10, 0.42, 1.0);
  vec3 hot = vec3(0.55, 1.35, 2.6);
  float body = 0.05 + fres * 0.55 + sweep * 0.04;
  vec3 col = base * body + hot * (edge * (0.5 + 0.6 * uIntegrity) + ripple * 0.9) + vec3(0.5, 0.9, 1.6) * uPulse * (0.25 + fres * 0.6);
  col += vec3(1.0, 0.55, 0.25) * (1.0 - uIntegrity) * edge * 0.6;   // cracks turn orange as it fails
  float alpha = (0.07 + fres * 0.42 + edge * 0.45 + ripple * 0.5 + uPulse * 0.22) * flicker * uAppear;

  // breaking: noise dissolve with a bright edge
  if (uBreak > 0.0) {
    float nz = noise3(d * 7.0) * 0.6 + noise3(d * 17.0) * 0.4;
    float cut = uBreak * 1.15;
    if (nz < cut) discard;
    float rim = 1.0 - smoothstep(0.0, 0.08, nz - cut);
    col += vec3(1.4, 2.0, 3.0) * rim * 2.0;
    alpha = max(alpha, rim);
  }
  gl_FragColor = vec4(col, clamp(alpha, 0.0, 1.0));
}
`;

/** Boss energy shield: hex/voronoi energy dome with pulse, hit ripples, damage flicker and a dissolve on break. */
export class ShieldFx {
  readonly mesh: THREE.Mesh;
  readonly material: THREE.ShaderMaterial;
  private hits: THREE.Vector4[] = [new THREE.Vector4(0, 1, 0, -1), new THREE.Vector4(0, 1, 0, -1), new THREE.Vector4(0, 1, 0, -1), new THREE.Vector4(0, 1, 0, -1)];
  private nextHit = 0;
  private breaking = false;
  private breakT = 0;
  private pulse = 0;
  private appear = 1;
  private appearTarget = 1;

  constructor(geometry: THREE.BufferGeometry, radius: number) {
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: {
        uTime: { value: 0 },
        uIntegrity: { value: 1 },
        uBreak: { value: 0 },
        uPulse: { value: 0 },
        uAppear: { value: 1 },
        uHit: { value: this.hits },
      },
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
      toneMapped: false,
      fog: false,
    });
    this.mesh = new THREE.Mesh(geometry, this.material);
    this.mesh.scale.setScalar(radius);
    this.mesh.renderOrder = 15;
    this.mesh.frustumCulled = false;
  }

  /** register an impact at a world point (mesh must have an up-to-date matrixWorld) */
  hit(worldPoint: THREE.Vector3, pulse = 0.35) {
    const local = worldPoint.clone();
    this.mesh.worldToLocal(local);
    local.normalize();
    const h = this.hits[this.nextHit];
    h.set(local.x, local.y, local.z, 0);
    this.nextHit = (this.nextHit + 1) % this.hits.length;
    this.pulse = Math.min(1, this.pulse + pulse);
  }

  setIntegrity(v: number) {
    this.material.uniforms.uIntegrity.value = v;
  }

  startBreak() {
    this.breaking = true;
    this.breakT = 0;
    this.pulse = 1;
  }

  /** shield comes back (regeneration) */
  regenerate() {
    this.breaking = false;
    this.breakT = 0;
    this.material.uniforms.uBreak.value = 0;
    this.appear = 0;
    this.appearTarget = 1;
    this.mesh.visible = true;
    this.pulse = 0.8;
  }

  get broken() {
    return this.breaking && this.breakT >= 1;
  }

  update(dt: number, time: number) {
    const u = this.material.uniforms;
    u.uTime.value = time;
    this.pulse = Math.max(0, this.pulse - dt * 2.6);
    u.uPulse.value = this.pulse;
    for (const h of this.hits) if (h.w >= 0) h.w = h.w > 3 ? -1 : h.w + dt;
    if (this.breaking) {
      this.breakT = Math.min(1, this.breakT + dt / 1.1);
      u.uBreak.value = this.breakT;
      if (this.breakT >= 1) this.mesh.visible = false;
    }
    if (this.appear < this.appearTarget) {
      this.appear = Math.min(this.appearTarget, this.appear + dt * 1.2);
      u.uAppear.value = this.appear;
    }
  }
}
