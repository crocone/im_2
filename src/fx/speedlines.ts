import * as THREE from 'three';
import { rand } from '../core/rng';

const VERT = /* glsl */ `
attribute vec4 aData;   // xyz = world position of the streak centre, w = length
attribute float aSeed;
uniform vec3 uDir;      // unit direction the streaks are stretched along
uniform float uWidth;
uniform float uAlpha;
varying float vA;
varying vec2 vUv;
void main() {
  vec3 centre = aData.xyz;
  vec3 toCam = normalize(cameraPosition - centre);
  vec3 side = normalize(cross(uDir, toCam));
  vec3 p = centre + uDir * (position.y * aData.w) + side * (position.x * uWidth);
  vUv = vec2(position.x * 2.0 + 0.5, position.y + 0.5);
  float distFade = smoothstep(90.0, 30.0, length(cameraPosition - centre)) * smoothstep(2.5, 8.0, length(cameraPosition - centre));
  vA = uAlpha * distFade * (0.45 + 0.55 * fract(aSeed * 7.31));
  gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
}
`;

const FRAG = /* glsl */ `
varying float vA;
varying vec2 vUv;
void main() {
  float across = 1.0 - abs(vUv.x - 0.5) * 2.0;
  float along = 1.0 - abs(vUv.y - 0.5) * 2.0;
  float a = clamp(across, 0.0, 1.0) * clamp(along, 0.0, 1.0);
  gl_FragColor = vec4(vec3(0.75, 0.92, 1.0) * 1.4, a * vA);
}
`;

/**
 * 3D speed streaks: thin additive ribbons that stay fixed in the world around the player and are stretched
 * along the velocity, so flying fast gives strong parallax and a sense of speed (and altitude/scale).
 */
export class SpeedLines {
  readonly mesh: THREE.Mesh;
  private data: Float32Array;
  private seed: Float32Array;
  private attr: THREE.InstancedBufferAttribute;
  private material: THREE.ShaderMaterial;
  private dir = new THREE.Vector3(0, 0, -1);
  private readonly n = 110;
  private _r = new THREE.Vector3();
  private _u = new THREE.Vector3();
  private _v = new THREE.Vector3();

  constructor(scene: THREE.Scene) {
    const g = new THREE.InstancedBufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-0.5, -0.5, 0, 0.5, -0.5, 0, 0.5, 0.5, 0, -0.5, 0.5, 0]), 3));
    g.setIndex([0, 1, 2, 0, 2, 3]);
    this.data = new Float32Array(this.n * 4);
    this.seed = new Float32Array(this.n);
    for (let i = 0; i < this.n; i++) this.seed[i] = Math.random();
    this.attr = new THREE.InstancedBufferAttribute(this.data, 4).setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('aData', this.attr);
    g.setAttribute('aSeed', new THREE.InstancedBufferAttribute(this.seed, 1));
    g.instanceCount = this.n;
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: { uDir: { value: this.dir }, uWidth: { value: 0.045 }, uAlpha: { value: 0 } },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      toneMapped: false,
      fog: false,
    });
    this.mesh = new THREE.Mesh(g, this.material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 18;
    this.mesh.visible = false;
    scene.add(this.mesh);
    for (let i = 0; i < this.n; i++) this.data[i * 4 + 3] = 0;
  }

  update(camPos: THREE.Vector3, velocity: THREE.Vector3, speed01: number, boost01: number) {
    const speed = velocity.length();
    const strength = Math.max(0, (speed - 22) / 60) + boost01 * 0.5;
    if (strength < 0.02) {
      this.mesh.visible = false;
      return;
    }
    this.mesh.visible = true;
    this.dir.copy(velocity).multiplyScalar(1 / Math.max(speed, 1e-3));
    // basis perpendicular to the flight direction for spawning
    this._r.set(0, 1, 0).cross(this.dir);
    if (this._r.lengthSq() < 1e-4) this._r.set(1, 0, 0);
    this._r.normalize();
    this._u.copy(this.dir).cross(this._r).normalize();
    const len = 1.6 + speed * 0.055;
    for (let i = 0; i < this.n; i++) {
      const o = i * 4;
      this._v.set(this.data[o] - camPos.x, this.data[o + 1] - camPos.y, this.data[o + 2] - camPos.z);
      const along = this._v.dot(this.dir);
      const dist = this._v.length();
      if (this.data[o + 3] === 0 || along < -14 || dist > 85) {
        // respawn ahead of the camera in a ring around the flight path (never inside the suit)
        const a = rand(0, Math.PI * 2);
        const r = rand(3.6, 30);
        const f = rand(24, 78);
        this.data[o] = camPos.x + this.dir.x * f + (this._r.x * Math.cos(a) + this._u.x * Math.sin(a)) * r;
        this.data[o + 1] = camPos.y + this.dir.y * f + (this._r.y * Math.cos(a) + this._u.y * Math.sin(a)) * r;
        this.data[o + 2] = camPos.z + this.dir.z * f + (this._r.z * Math.cos(a) + this._u.z * Math.sin(a)) * r;
      }
      this.data[o + 3] = len * (0.6 + 0.8 * this.seed[i]);
    }
    this.attr.needsUpdate = true;
    this.material.uniforms.uAlpha.value = Math.min(0.55, strength * 0.5) * (0.6 + speed01 * 0.4);
    this.material.uniforms.uWidth.value = 0.035 + 0.03 * boost01;
  }
}
