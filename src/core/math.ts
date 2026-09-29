import * as THREE from 'three';

export const TAU = Math.PI * 2;
export const DEG = Math.PI / 180;

export const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
export const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const invLerp = (a: number, b: number, v: number) => (a === b ? 0 : clamp01((v - a) / (b - a)));
export const remap = (v: number, a: number, b: number, c: number, d: number) => lerp(c, d, invLerp(a, b, v));
export const smoothstep = (a: number, b: number, v: number) => {
  const t = invLerp(a, b, v);
  return t * t * (3 - 2 * t);
};
/** Frame-rate independent exponential smoothing: moves `a` toward `b`. lambda ~ 1/time-constant. */
export const damp = (a: number, b: number, lambda: number, dt: number) => lerp(a, b, 1 - Math.exp(-lambda * dt));
export const wrapPi = (a: number) => {
  a = (a + Math.PI) % TAU;
  if (a < 0) a += TAU;
  return a - Math.PI;
};
export const sign = (v: number) => (v < 0 ? -1 : 1);

/** Critically damped vector smoothing (in place on `cur`). */
export function dampVec3(cur: THREE.Vector3, target: THREE.Vector3, lambda: number, dt: number) {
  const k = 1 - Math.exp(-lambda * dt);
  cur.x += (target.x - cur.x) * k;
  cur.y += (target.y - cur.y) * k;
  cur.z += (target.z - cur.z) * k;
  return cur;
}

export function dampQuat(cur: THREE.Quaternion, target: THREE.Quaternion, lambda: number, dt: number) {
  return cur.slerp(target, 1 - Math.exp(-lambda * dt));
}

const _q = new THREE.Quaternion();
const _lookM = new THREE.Matrix4();
const _zero = new THREE.Vector3();
const _Y = new THREE.Vector3(0, 1, 0);
const _X = new THREE.Vector3(1, 0, 0);
/** Quaternion that rotates model-forward (-Z) onto the unit vector `dir` (up hint = world Y). */
export function quatLookDir(out: THREE.Quaternion, dir: THREE.Vector3, up: THREE.Vector3 = _Y) {
  // Matrix4.lookAt builds a basis whose +Z points from `target` to `eye`, i.e. -Z looks at `dir`.
  const useUp = Math.abs(dir.y) > 0.999 ? _X : up;
  _lookM.lookAt(_zero, dir, useUp);
  return out.setFromRotationMatrix(_lookM);
}

/** Rotate `from` toward `to` by at most `maxAngle` radians. Both must be unit vectors. Returns result in `out`. */
export function rotateToward(out: THREE.Vector3, from: THREE.Vector3, to: THREE.Vector3, maxAngle: number) {
  const dot = clamp(from.dot(to), -1, 1);
  const angle = Math.acos(dot);
  if (angle < 1e-5) return out.copy(to);
  const t = Math.min(1, maxAngle / angle);
  // slerp on the sphere
  const sin = Math.sin(angle);
  if (sin < 1e-5) return out.copy(to);
  const a = Math.sin((1 - t) * angle) / sin;
  const b = Math.sin(t * angle) / sin;
  out.set(from.x * a + to.x * b, from.y * a + to.y * b, from.z * a + to.z * b);
  return out.normalize();
}

export const tmpQuat = () => _q;

/** Ease helpers */
export const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
export const easeInOutSine = (t: number) => -(Math.cos(Math.PI * t) - 1) / 2;

/** Format numbers with thousands separators for the HUD */
export const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US');
