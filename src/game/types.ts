import type * as THREE from 'three';
import type { Physics } from '../physics/world';
import type { Assets } from '../assets/loader';
import type { Effects } from '../fx/effects';
import type { Emitter } from '../core/events';
import type { Input } from '../core/input';
import type { Player } from '../player/player';
import type { EnemyManager } from '../enemies/manager';
import type { ProjectileManager } from '../weapons/projectiles';
import type { World } from '../world/world';
import type { PickupManager } from '../world/pickups';
import type { DebrisManager } from '../world/debris';
import type { AudioEngine } from '../audio/audio';

export type HitSource = 'repulsor' | 'missile' | 'mini' | 'bolt' | 'enemyMissile' | 'explosion' | 'collision' | 'beam';

export interface HitInfo {
  point: THREE.Vector3;
  normal?: THREE.Vector3;
  dir?: THREE.Vector3;
  source: HitSource;
  /** velocity change (m/s) the hit should impart on physical bodies */
  kick?: number;
}

export interface Damageable {
  alive: boolean;
  takeDamage(amount: number, hit: HitInfo): void;
}

export const isDamageable = (x: unknown): x is Damageable =>
  !!x && typeof (x as Damageable).takeDamage === 'function';

/** Something the player can target / lock onto (drones, turrets, the boss). */
export interface Target extends Damageable {
  readonly id: number;
  readonly kind: 'drone' | 'turret' | 'boss';
  readonly label: string;
  /** live world centre */
  readonly pos: THREE.Vector3;
  readonly vel: THREE.Vector3;
  /** visual/lock radius in metres */
  readonly radius: number;
  /** 0..1 */
  healthFraction(): number;
  /** shield fraction for the boss, else -1 */
  shieldFraction(): number;
  /** apply a physical velocity change (explosion / impact) */
  kick(dir: THREE.Vector3, speed: number): void;
}

/** anything a missile can chase */
export interface Trackable {
  readonly pos: THREE.Vector3;
  readonly vel: THREE.Vector3;
  alive: boolean;
}

export interface GameEvents {
  score: { points: number; total: number; label?: string };
  message: { text: string; kind: 'info' | 'warn' | 'good' | 'bad'; time?: number };
  enemyKilled: { kind: 'drone' | 'turret' | 'boss'; pos: THREE.Vector3 };
  /** the player's weapons damaged an enemy / shield / enemy missile (drives the hit marker) */
  hit: { shield: boolean };
  playerDamaged: { amount: number; source: string };
  playerDied: Record<string, never>;
  lockState: { state: 'searching' | 'acquiring' | 'locked'; progress: number };
  wave: { wave: number; phase: 'start' | 'clear' };
  bossState: { text: string };
  victory: Record<string, never>;
  ammo: Record<string, never>;
}

export type Difficulty = 'easy' | 'normal' | 'hard';

export interface Settings {
  sensitivity: number; // multiplier
  invertY: boolean;
  quality: 'low' | 'medium' | 'high';
  difficulty: Difficulty;
  volume: number;
  showHelpOnStart: boolean;
}

export interface GameCtx {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  physics: Physics;
  assets: Assets;
  fx: Effects;
  bus: Emitter<GameEvents>;
  input: Input;
  audio: AudioEngine;
  settings: Settings;
  player: Player;
  enemies: EnemyManager;
  projectiles: ProjectileManager;
  world: World;
  pickups: PickupManager;
  debris: DebrisManager;
  /** simulation clock in seconds */
  time: number;
  explode(opts: ExplosionOpts): void;
  shake(amount: number, at?: THREE.Vector3): void;
  recoil(amount: number): void;
  addScore(points: number, label?: string): void;
}

export interface ExplosionOpts {
  pos: THREE.Vector3;
  radius: number;
  damage: number;
  /** velocity change at the centre for physical bodies */
  kick: number;
  /** who fired it: enemy explosions hurt the player, player explosions hurt enemies/props */
  team: 'player' | 'enemy';
  /** visual scale (1 = missile) */
  scale?: number;
  source: HitSource;
  color?: 'fire' | 'plasma' | 'cyan';
  /** what should NOT receive damage (e.g. the shooter) */
  ignore?: object;
}
