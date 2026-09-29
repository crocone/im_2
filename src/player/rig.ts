import * as THREE from 'three';
import { Assets, indexNodes, prepareMeshes } from '../assets/loader';
import { clamp, damp } from '../core/math';

export type PoseName = 'standing' | 'flight' | 'hover';

const CLIP_NAMES: Record<PoseName, string> = {
  standing: 'Pose_Standing',
  flight: 'Pose_Flight',
  hover: 'Pose_Hover',
};

const _q1 = new THREE.Quaternion();
const _q2 = new THREE.Quaternion();
const _q3 = new THREE.Quaternion();
const _q4 = new THREE.Quaternion();
const _v1 = new THREE.Vector3();
const _fwd = new THREE.Vector3(0, 0, -1);

/**
 * The player's armour: the Blender-authored PlayerRoot hierarchy + the three glTF pose clips
 * (Pose_Standing / Pose_Flight / Pose_Hover) blended by weights, plus procedural arm aiming.
 */
export class ArmorRig {
  readonly root: THREE.Object3D;
  readonly nodes: Record<string, THREE.Object3D>;
  private mixer: THREE.AnimationMixer;
  private actions: Record<PoseName, THREE.AnimationAction>;
  /** current blend weights (sum = 1) */
  readonly weights: Record<PoseName, number> = { standing: 1, flight: 0, hover: 0 };
  private glow: { mat: THREE.MeshStandardMaterial; base: number }[] = [];
  /** aim override strength per arm (0..1), decays when not firing */
  aimWeight = { L: 0, R: 0 };
  /** unit lean of the Pelvis about X in radians (negative = leaning forward) */
  lean = 0;
  readonly muzzleL: THREE.Object3D;
  readonly muzzleR: THREE.Object3D;
  readonly footNozzleL: THREE.Object3D;
  readonly footNozzleR: THREE.Object3D;
  readonly missileLaunchers: THREE.Object3D[];
  readonly miniLaunchers: THREE.Object3D[];
  private hit = 0;

  constructor(assets: Assets) {
    this.root = assets.cloneNode('player', 'PlayerRoot');
    prepareMeshes(this.root, { cast: true, receive: true, envIntensity: 1.25 });
    this.nodes = indexNodes(this.root);
    const n = this.nodes;
    this.muzzleL = n.Muzzle_L;
    this.muzzleR = n.Muzzle_R;
    this.footNozzleL = n.Nozzle_FootL;
    this.footNozzleR = n.Nozzle_FootR;
    this.missileLaunchers = [n.Launcher_Missile_L, n.Launcher_Missile_R];
    this.miniLaunchers = [
      n.Launcher_Mini_L_1, n.Launcher_Mini_R_1, n.Launcher_Mini_L_2, n.Launcher_Mini_R_2, n.Launcher_Mini_L_3, n.Launcher_Mini_R_3,
    ];

    // clone materials of the glowing parts so intensity can be animated without touching the shared asset
    const seen = new Map<THREE.Material, THREE.MeshStandardMaterial>();
    this.root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const mats = Array.isArray(m.material) ? m.material : [m.material];
      const out = mats.map((mat) => {
        if (!mat.name.startsWith('glow_')) return mat;
        let c = seen.get(mat);
        if (!c) {
          c = (mat as THREE.MeshStandardMaterial).clone();
          seen.set(mat, c);
          this.glow.push({ mat: c, base: c.emissiveIntensity });
        }
        return c;
      });
      m.material = Array.isArray(m.material) ? out : out[0];
    });

    this.mixer = new THREE.AnimationMixer(this.root);
    const clips = assets.get('player').animations;
    const find = (name: string) => {
      const c = clips.find((k) => k.name === name);
      if (!c) throw new Error(`player.glb is missing animation ${name}`);
      return c;
    };
    this.actions = {
      standing: this.mixer.clipAction(find(CLIP_NAMES.standing)),
      flight: this.mixer.clipAction(find(CLIP_NAMES.flight)),
      hover: this.mixer.clipAction(find(CLIP_NAMES.hover)),
    };
    (Object.keys(this.actions) as PoseName[]).forEach((k, i) => {
      const a = this.actions[k];
      a.setLoop(THREE.LoopRepeat, Infinity);
      a.play();
      a.time = i * 0.37; // de-phase idle loops
      a.setEffectiveWeight(this.weights[k]);
    });
  }

  /** Move the current pose weights toward the targets (they should sum to 1). */
  update(dt: number, target: Record<PoseName, number>, blendSpeed = 5) {
    let sum = 0;
    for (const k of Object.keys(this.weights) as PoseName[]) {
      this.weights[k] = damp(this.weights[k], target[k], blendSpeed, dt);
      sum += this.weights[k];
    }
    if (sum < 1e-4) sum = 1;
    for (const k of Object.keys(this.weights) as PoseName[]) {
      this.actions[k].setEffectiveWeight(this.weights[k] / sum);
    }
    this.mixer.update(dt);
    this.aimWeight.L = Math.max(0, this.aimWeight.L - dt * 3.2);
    this.aimWeight.R = Math.max(0, this.aimWeight.R - dt * 3.2);
    this.root.updateMatrixWorld(true);
  }

  /** After update(): rotate an arm about the shoulder so that its palm muzzle points along `dirWorld`. */
  aimArm(side: 'L' | 'R', dirWorld: THREE.Vector3, maxAngle = 2.6) {
    const w = this.aimWeight[side] > 0.001 ? Math.min(1, this.aimWeight[side] * 2.2) : 0;
    if (w <= 0) return;
    const arm = this.nodes[`Arm_${side}`];
    const muzzle = side === 'L' ? this.muzzleL : this.muzzleR;
    const parent = arm.parent!;
    muzzle.getWorldQuaternion(_q1);
    const now = _v1.copy(_fwd).applyQuaternion(_q1);
    const delta = _q4.setFromUnitVectors(now, dirWorld); // turns the palm normal onto the aim direction
    const ang = 2 * Math.acos(clamp(delta.w, -1, 1));
    const ease = w * w * (3 - 2 * w);
    const t = ang > 1e-4 ? Math.min(ease, (maxAngle / ang) * ease) : 0;
    _q2.identity().slerp(delta, t);
    arm.getWorldQuaternion(_q3);
    _q3.premultiply(_q2);
    parent.getWorldQuaternion(_q1);
    arm.quaternion.copy(_q1.invert().multiply(_q3));
    arm.updateMatrixWorld(true);
  }

  /** Read the lean of the pelvis (rad, negative forward) for the physics capsule / camera. */
  measureLean() {
    const p = this.nodes.Pelvis;
    const q = p.quaternion;
    // rotation about X: angle = 2*atan2(x, w)
    let a = 2 * Math.atan2(q.x, q.w);
    if (a > Math.PI) a -= Math.PI * 2;
    this.lean = a;
    return a;
  }

  /** boost 0..1 brightens the cyan glow; hit flash pulses white */
  setGlow(boost: number, intensityScale = 1) {
    this.hit = Math.max(0, this.hit - 0.06);
    for (const g of this.glow) {
      g.mat.emissiveIntensity = g.base * (1 + boost * 0.9) * intensityScale + this.hit * 4;
    }
  }

  flashHit() {
    this.hit = 1;
  }

  worldPos(node: THREE.Object3D, out = new THREE.Vector3()) {
    return node.getWorldPosition(out);
  }

  /** world direction a Muzzle/Nozzle/Launcher empty emits along (three.js local -Z) */
  worldDir(node: THREE.Object3D, out = new THREE.Vector3()) {
    node.getWorldQuaternion(_q1);
    return out.copy(_fwd).applyQuaternion(_q1).normalize();
  }
}
