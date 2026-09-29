import { DEG } from './core/math';

/** Central tuning file. Units: metres, seconds, radians (unless a name says deg). */

export const WORLD = {
  pitch: 100, // block pitch
  road: 20,
  sidewalk: 4,
  lot: 72,
  blocks: 8,
  half: 400, // playable half extent => 800 x 800 m
  lotY: 0.15,
  softBound: 410, // beyond this the suit is pushed back toward the combat zone
  ceiling: 420,
  seed: 0x5eed1234,
  /** buildings farther than this from the camera swap to their LOD1 mesh (chunk granularity) */
  lodDistance: 330,
  chunk: 200, // instancing chunk size (frustum culling granularity)
};

export const PHYS = {
  dt: 1 / 60,
  maxSteps: 5,
  gravity: 9.81,
};

export const PLAYER = {
  maxArmor: 100,
  maxEnergy: 100,
  capsuleHalf: 0.55,
  capsuleRadius: 0.42,
  bodyMass: 95,
  energyRegen: 16,
  energyRegenDelay: 0.55,
  armorFlashTime: 0.35,
  armorRegen: 0.8, // armour points per second after `armorRegenDelay` without damage
  armorRegenDelay: 6,
  impactSpeed: 14, // velocity change (m/s) above which a collision hurts
  impactDamageScale: 0.55,
};

/** difficulty presets (chosen in the menu): scale the damage the suit takes and how fast the armour self-repairs */
export const DIFFICULTY = {
  easy: { damageTaken: 0.6, regen: 2 },
  normal: { damageTaken: 1, regen: 1 },
  hard: { damageTaken: 1.35, regen: 0.6 },
} as const;

export const FLIGHT = {
  cruise: {
    maxSpeed: 52,
    accel: 46,
    backAccel: 30,
    backFactor: 0.45,
    strafeAccel: 30,
    strafeSpeed: 30,
    vertAccel: 34,
    vertSpeed: 30,
    drag: 0.2,
    align: 1.0, // how strongly velocity is pulled toward the nose direction
  },
  hover: {
    maxSpeed: 24,
    accel: 38,
    backAccel: 34,
    backFactor: 0.8,
    strafeAccel: 38,
    strafeSpeed: 22,
    vertAccel: 32,
    vertSpeed: 18,
    drag: 2.0,
    align: 0,
  },
  boost: {
    speed: 108,
    accel: 96,
    energyPerSec: 24,
    minEnergy: 8,
    fovAdd: 14,
    shake: 0.55,
  },
  mouseSens: 0.0021,
  mouseSmooth: 0.04, // seconds
  maxPitch: 82 * DEG,
  hoverMaxPitch: 45 * DEG,
  manualRollRate: 3.6,
  bankFromYaw: 0.16,
  bankFromStrafe: 0.16,
  maxBank: 0.62,
  levelRate: 4.2,
  transition: 0.55, // seconds to blend flight <-> hover poses
  landHeight: 1.06, // distance from body origin to the ground when standing
  landSpeed: 5,
};

export const CAMERA = {
  fov: 68,
  distance: 5.4,
  speedDistance: 3.6,
  height: 1.15,
  side: 0.95,
  lookAhead: 30,
  posLambda: 8.5,
  rotLambda: 16,
  rollFollow: 0.4,
  shakeDecay: 1.9,
  minDistance: 1.6,
};

export const WEAPON = {
  repulsor: {
    interval: 0.105,
    energy: 1.2,
    damage: 9,
    range: 450,
    impulse: 14,
    spread: 0.0035,
    flash: 1,
  },
  missile: {
    max: 8,
    cooldown: 0.55,
    launchSpeed: 26,
    speed: 135,
    accel: 92,
    turnRate: 5.0,
    arcTime: 0.3,
    blendTime: 0.2,
    proximity: 3.4,
    damage: 170,
    radius: 12,
    impulse: 420,
    life: 8,
  },
  mini: {
    max: 24,
    salvo: 6,
    interval: 0.075,
    cooldown: 1.7,
    launchSpeed: 26,
    speed: 118,
    accel: 100,
    turnRate: 6.6,
    arcTime: 0.2,
    blendTime: 0.16,
    proximity: 2.4,
    damage: 40,
    radius: 5.5,
    impulse: 95,
    life: 5,
    fan: 0.5,
  },
  lock: {
    acquireTime: 1.15,
    acquireCone: 11 * DEG,
    holdCone: 38 * DEG,
    range: 560,
    loseTime: 0.9,
    switchTime: 0.55,
    candidateCone: 65 * DEG,
  },
};

export const DRONE = {
  hp: 70,
  radius: 0.75,
  mass: 30,
  patrolSpeed: 15,
  chaseSpeed: 36,
  attackSpeed: 22,
  evadeSpeed: 52,
  aggroRange: 230,
  attackRange: 70,
  minAlt: 10,
  maxAlt: 220,
  fireInterval: [1.7, 2.9] as [number, number],
  burst: 3,
  burstGap: 0.13,
  boltSpeed: 100,
  boltDamage: 4.6,
  spread: 0.035,
  score: 100,
  accel: 30,
};

export const TURRET = {
  hp: 240,
  range: 330,
  minRange: 25,
  salvoStagger: 2.2, // global minimum time between two turret salvos (keeps the pressure bounded when many turrets see the player)
  yawRate: 1.6,
  pitchRate: 1.2,
  cooldown: [6.5, 9.5] as [number, number],
  salvo: 2,
  salvoGap: 0.55,
  missileSpeed: 66,
  missileAccel: 40,
  missileTurn: 1.35,
  missileDamage: 12,
  missileRadius: 6,
  missileLife: 9,
  score: 250,
  alignCone: 6 * DEG,
};

export const BOSS = {
  shieldHp: 1100,
  hullHp: 1800,
  shieldRadius: 9.6,
  hullRadius: 3.6,
  altitude: 190,
  orbitRadius: 95,
  orbitSpeed: 0.09,
  moveSpeed: 22,
  shieldRegenDelay: 14,
  vulnerableTime: 22,
  score: 5000,
};

export const SCORE = {
  drone: 100,
  turret: 250,
  destructible: 60,
  prop: 15,
  boss: 5000,
  wave: 500,
};

export const PICKUP = {
  dropChance: 0.3,
  radius: 3.4,
  life: 30,
};
