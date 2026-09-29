import * as THREE from 'three';
import { CAMERA, FLIGHT } from '../config';
import { G, Physics } from '../physics/world';
import { clamp, damp, dampQuat } from '../core/math';
import type { Player } from './player';

const _pivot = new THREE.Vector3();
const _off = new THREE.Vector3();
const _want = new THREE.Vector3();
const _dir = new THREE.Vector3();
const _target = new THREE.Vector3();
const _up = new THREE.Vector3();
const _m = new THREE.Matrix4();
const _q = new THREE.Quaternion();
const _qTarget = new THREE.Quaternion();
const _qRoll = new THREE.Quaternion();
const AZ = new THREE.Vector3(0, 0, 1);

/**
 * Third-person chase camera: damped follow (lags under acceleration and turning), speed dependent distance and FOV,
 * boost vibration, trauma based shake, weapon recoil and building collision avoidance.
 */
export class ChaseCamera {
  private quat = new THREE.Quaternion();
  private offset = new THREE.Vector3(CAMERA.side, CAMERA.height, CAMERA.distance);
  private trauma = 0;
  private recoilKick = 0;
  private fov: number = CAMERA.fov;
  private clearance = 1;
  private time = 0;
  private started = false;
  private shakeOffset = new THREE.Vector3();
  private shakeRoll = 0;

  constructor(private camera: THREE.PerspectiveCamera, private physics: Physics) {}

  reset(player: Player) {
    this.started = false;
    this.trauma = 0;
    this.recoilKick = 0;
    this.clearance = 1;
    this.snap(player);
  }

  /** teleport the camera behind the player without smoothing */
  snap(player: Player) {
    this.quat.copy(player.flight.aimQuat);
    this.offset.set(CAMERA.side, CAMERA.height, CAMERA.distance);
    _off.copy(this.offset).applyQuaternion(this.quat);
    this.camera.position.copy(player.renderPos).add(_off);
    this.camera.quaternion.copy(this.quat);
    this.started = true;
  }

  addShake(amount: number) {
    this.trauma = Math.min(1.2, this.trauma + amount);
  }

  addRecoil(amount: number) {
    this.recoilKick = Math.min(1.2, this.recoilKick + amount * 3);
  }

  update(dt: number, player: Player) {
    if (!this.started) this.snap(player);
    this.time += dt;
    const speed01 = clamp(player.speed / FLIGHT.boost.speed, 0, 1);
    const boost = player.flight.boostAmount;

    // ---- orientation: follows the suit's yaw/pitch with a little lag; roll only partially
    _qTarget.copy(player.flight.aimQuat);
    _qRoll.setFromAxisAngle(AZ, player.flight.roll * CAMERA.rollFollow);
    _qTarget.multiply(_qRoll);
    dampQuat(this.quat, _qTarget, CAMERA.rotLambda * (player.mode === 'flight' ? 1 : 1.25), dt);

    // ---- offset in the (smoothed) camera frame: distance grows with speed, shrinks with weapon recoil
    this.recoilKick = damp(this.recoilKick, 0, 9, dt);
    const dist = CAMERA.distance + speed01 * CAMERA.speedDistance + boost * 1.0 - this.recoilKick * 0.35;
    const lagBack = clamp(-player.flight.accel.dot(_dir.set(0, 0, -1).applyQuaternion(this.quat)) * 0.022, -1.2, 2.4);
    const wantOffset = _off.set(CAMERA.side * (1 - speed01 * 0.35), CAMERA.height - speed01 * 0.15, dist + lagBack);
    this.offset.lerp(wantOffset, 1 - Math.exp(-CAMERA.posLambda * dt));

    // ---- world position
    _pivot.copy(player.renderPos).addScaledVector(_up.set(0, 1, 0).applyQuaternion(this.quat), 0.55);
    _want.copy(this.offset).applyQuaternion(this.quat).add(player.renderPos);
    _dir.copy(_want).sub(_pivot);
    const len = _dir.length();
    if (len > 1e-3) {
      _dir.multiplyScalar(1 / len);
      const hit = this.physics.raycast(_pivot, _dir, len + 0.3, G.WORLD, player.collider);
      const k = hit ? clamp((hit.distance - 0.45) / len, CAMERA.minDistance / len, 1) : 1;
      this.clearance = k < this.clearance ? k : damp(this.clearance, k, 2.2, dt);
      _want.copy(_pivot).addScaledVector(_dir, len * this.clearance);
    }

    // ---- shake + boost vibration
    this.trauma = Math.max(0, this.trauma - CAMERA.shakeDecay * dt);
    const vib = boost * FLIGHT.boost.shake * 0.16 + speed01 * 0.02;
    const tr = Math.min(1, this.trauma);
    const amp = tr * tr * 0.55 + vib * 0.1;
    const t = this.time;
    this.shakeOffset.set(
      Math.sin(t * 47.1) * 0.6 + Math.sin(t * 91.7) * 0.4,
      Math.sin(t * 53.3 + 1.3) * 0.6 + Math.sin(t * 83.9) * 0.4,
      Math.sin(t * 39.7 + 2.1) * 0.5,
    ).multiplyScalar(amp);
    this.shakeRoll = (Math.sin(t * 61.3) * 0.6 + Math.sin(t * 27.1 + 0.7) * 0.4) * (tr * tr * 0.05 + vib * 0.006);
    _want.add(this.shakeOffset);
    this.camera.position.copy(_want);

    // ---- look at a point far ahead along the suit's aim so the reticle matches where shots converge
    const look = _target.copy(player.renderPos).addScaledVector(_dir.set(0, 0, -1).applyQuaternion(this.quat), CAMERA.lookAhead);
    look.y += 0.15;
    _up.set(0, 1, 0).applyQuaternion(this.quat);
    _m.lookAt(this.camera.position, look, _up);
    _q.setFromRotationMatrix(_m);
    _qRoll.setFromAxisAngle(AZ, this.shakeRoll);
    this.camera.quaternion.copy(_q).multiply(_qRoll);

    // ---- FOV
    const targetFov = CAMERA.fov + boost * FLIGHT.boost.fovAdd + speed01 * 4 + this.recoilKick * 0.4;
    this.fov = damp(this.fov, targetFov, 6, dt);
    if (Math.abs(this.camera.fov - this.fov) > 0.01) {
      this.camera.fov = this.fov;
      this.camera.updateProjectionMatrix();
    }
  }
}
