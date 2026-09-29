import * as THREE from 'three';
import { FLIGHT } from '../config';
import { TAU, clamp, damp } from '../core/math';

export type FlightMode = 'flight' | 'hover' | 'grounded';

export interface FlightInput {
  forward: number; // W/S  (-1..1)
  strafe: number; // A/D
  vertical: number; // Space / C
  roll: number; // E (+1) / Q (-1)
  boost: boolean;
  mouseDX: number;
  mouseDY: number;
  invertY: boolean;
  sensitivity: number;
}

const _f = new THREE.Vector3();
const _r = new THREE.Vector3();
const _a = new THREE.Vector3();
const _perp = new THREE.Vector3();
const _qYaw = new THREE.Quaternion();
const _qPitch = new THREE.Quaternion();
const _qRoll = new THREE.Quaternion();
const AX = new THREE.Vector3(1, 0, 0);
const AY = new THREE.Vector3(0, 1, 0);
const AZ = new THREE.Vector3(0, 0, 1);

const cap = (x: number, max: number) => clamp(1 - Math.max(0, x) / max, 0, 1);

/**
 * 6-DoF style powered flight: acceleration + inertia + drag, soft speed caps, separate acceleration
 * characteristics for cruise flight, hover and boost. Orientation = yaw * pitch * roll with automatic
 * banking into turns / strafes, manual barrel roll (Q/E) and auto-levelling.
 * Pure maths - the caller owns the physics body and feeds/reads its velocity.
 */
export class FlightModel {
  mode: FlightMode = 'grounded';
  heading = 0; // yaw about world +Y
  pitch = 0;
  roll = 0;
  private rollRate = 0;
  private pendYaw = 0;
  private pendPitch = 0;
  yawRate = 0;
  pitchRate = 0;
  boosting = false;
  boostAmount = 0;
  thrust = 0; // 0..1 how hard the engines work (drives flames)
  readonly forward = new THREE.Vector3(0, 0, -1); // nose direction (yaw+pitch)
  readonly right = new THREE.Vector3(1, 0, 0); // horizontal right
  readonly aimQuat = new THREE.Quaternion();
  readonly quat = new THREE.Quaternion();
  readonly accel = new THREE.Vector3(); // last applied acceleration (for lean / camera lag)

  reset(heading = 0) {
    this.heading = heading;
    this.pitch = 0;
    this.roll = 0;
    this.rollRate = 0;
    this.pendYaw = this.pendPitch = 0;
    this.yawRate = this.pitchRate = 0;
    this.boosting = false;
    this.boostAmount = 0;
    this.thrust = 0;
    this.accel.set(0, 0, 0);
    this.updateBasis();
  }

  private updateBasis() {
    _qYaw.setFromAxisAngle(AY, this.heading);
    _qPitch.setFromAxisAngle(AX, this.pitch);
    _qRoll.setFromAxisAngle(AZ, this.roll);
    this.aimQuat.copy(_qYaw).multiply(_qPitch);
    this.quat.copy(this.aimQuat).multiply(_qRoll);
    this.forward.set(0, 0, -1).applyQuaternion(this.aimQuat);
    this.right.set(1, 0, 0).applyQuaternion(_qYaw);
  }

  /** Rotate only (used while grounded / during cinematics). */
  rotate(dt: number, input: FlightInput) {
    const k = 1 - Math.exp(-dt / FLIGHT.mouseSmooth);
    const sens = FLIGHT.mouseSens * input.sensitivity;
    this.pendYaw += -input.mouseDX * sens;
    this.pendPitch += (input.invertY ? input.mouseDY : -input.mouseDY) * sens;
    const yawStep = this.pendYaw * k;
    const pitchStep = this.pendPitch * k;
    this.pendYaw -= yawStep;
    this.pendPitch -= pitchStep;
    this.heading += yawStep;
    const maxP = this.mode === 'hover' || this.mode === 'grounded' ? FLIGHT.hoverMaxPitch : FLIGHT.maxPitch;
    const before = this.pitch;
    this.pitch = clamp(this.pitch + pitchStep, -maxP, maxP);
    if (this.pitch !== before + pitchStep) this.pendPitch = 0;
    this.yawRate = damp(this.yawRate, dt > 0 ? yawStep / dt : 0, 14, dt);
    this.pitchRate = damp(this.pitchRate, dt > 0 ? pitchStep / dt : 0, 14, dt);
    // keep heading bounded
    if (this.heading > Math.PI) this.heading -= TAU;
    else if (this.heading < -Math.PI) this.heading += TAU;
  }

  /**
   * Advance one fixed step. `vel` is read and written (m/s). Returns nothing; use fields for feedback.
   * `canBoost` is false when energy is depleted.
   */
  step(dt: number, input: FlightInput, vel: THREE.Vector3, canBoost: boolean) {
    this.rotate(dt, input);

    const hover = this.mode === 'hover';
    const cfg = hover ? FLIGHT.hover : FLIGHT.cruise;

    // ---- roll: banking into turns/strafes, manual barrel roll, auto-level
    const manual = input.roll;
    const bankTarget = clamp(
      (this.yawRate * FLIGHT.bankFromYaw + input.strafe * -FLIGHT.bankFromStrafe) * (hover ? 0.55 : 1),
      -FLIGHT.maxBank,
      FLIGHT.maxBank,
    );
    this.rollRate = damp(this.rollRate, -manual * FLIGHT.manualRollRate, 9, dt);
    if (Math.abs(manual) > 0.01) {
      this.roll += this.rollRate * dt;
    } else {
      // return to the nearest upright orientation (shortest way) plus the bank
      const target = Math.round(this.roll / TAU) * TAU + bankTarget;
      this.roll = damp(this.roll, target, FLIGHT.levelRate, dt) + this.rollRate * dt;
    }
    this.updateBasis();

    // ---- boost bookkeeping
    this.boosting = input.boost && canBoost && (this.mode !== 'grounded');
    this.boostAmount = damp(this.boostAmount, this.boosting ? 1 : 0, this.boosting ? 6 : 3.2, dt);

    // ---- thrust
    const f = _f.copy(this.forward);
    if (hover) {
      f.y = 0;
      if (f.lengthSq() < 1e-4) f.set(0, 0, -1).applyQuaternion(_qYaw);
      f.normalize();
    }
    const r = _r.copy(this.right);
    const a = _a.set(0, 0, 0);
    const vf = vel.dot(f);
    const vr = vel.dot(r);
    if (input.forward > 0) a.addScaledVector(f, cfg.accel * input.forward * cap(vf, cfg.maxSpeed));
    else if (input.forward < 0) a.addScaledVector(f, cfg.backAccel * input.forward * cap(-vf, cfg.maxSpeed * cfg.backFactor));
    if (input.strafe !== 0) a.addScaledVector(r, cfg.strafeAccel * input.strafe * cap(vr * Math.sign(input.strafe), cfg.strafeSpeed));
    if (input.vertical !== 0) a.y += cfg.vertAccel * input.vertical * cap(vel.y * Math.sign(input.vertical), cfg.vertSpeed);
    if (this.boosting) {
      const bf = this.forward;
      a.addScaledVector(bf, FLIGHT.boost.accel * cap(vel.dot(bf), FLIGHT.boost.speed));
    }

    // ---- drag + aerodynamic alignment (velocity is pulled toward the nose)
    a.addScaledVector(vel, -cfg.drag * (this.boosting ? 0.3 : 1));
    const noLateralInput = input.strafe === 0 && input.vertical === 0;
    if (cfg.align > 0 && noLateralInput && !this.boosting) {
      const speed = vel.length();
      if (speed > 1) {
        _perp.copy(vel).addScaledVector(this.forward, -vel.dot(this.forward));
        const along = vel.dot(this.forward);
        // only when moving broadly forward; reverse thrust should not be fought
        if (along > -1) a.addScaledVector(_perp, -cfg.align);
      }
    }
    // idle hover brake: extra damping when no input at all
    if (hover && input.forward === 0 && noLateralInput) a.addScaledVector(vel, -1.4);

    vel.addScaledVector(a, dt);
    this.accel.copy(a);

    const limit = Math.max(cfg.maxSpeed, this.boosting ? FLIGHT.boost.speed : 0) * 1.6 + 20;
    if (vel.lengthSq() > limit * limit) vel.setLength(limit);

    const want = Math.max(Math.abs(input.forward), Math.abs(input.strafe) * 0.6, Math.abs(input.vertical) * 0.6, this.boosting ? 1 : 0);
    this.thrust = damp(this.thrust, want, 8, dt);
  }

  /** Grounded: only rotation; thrust decays. */
  stepGrounded(dt: number, input: FlightInput) {
    this.rotate(dt, input);
    this.roll = damp(this.roll, Math.round(this.roll / TAU) * TAU, 8, dt);
    this.boosting = false;
    this.boostAmount = damp(this.boostAmount, 0, 6, dt);
    this.thrust = damp(this.thrust, 0, 6, dt);
    this.accel.set(0, 0, 0);
    this.updateBasis();
  }
}
