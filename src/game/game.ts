import * as THREE from 'three';
import { PHYS, SCORE } from '../config';
import { Physics } from '../physics/world';
import { Assets } from '../assets/loader';
import { Effects } from '../fx/effects';
import { PostFX, Quality } from '../fx/postfx';
import { SpeedLines } from '../fx/speedlines';
import { Sky } from '../world/sky';
import { Input } from '../core/input';
import { Emitter } from '../core/events';
import { AudioEngine } from '../audio/audio';
import { Player } from '../player/player';
import { ChaseCamera } from '../player/camera';
import { EnemyManager } from '../enemies/manager';
import { WaveManager } from '../enemies/waves';
import { ProjectileManager } from '../weapons/projectiles';
import { World } from '../world/world';
import { PickupManager } from '../world/pickups';
import { DebrisManager } from '../world/debris';
import { Hud } from '../ui/hud';
import { Overlays } from '../ui/overlays';
import { explode } from './explode';
import type { ExplosionOpts, GameCtx, GameEvents, Settings } from './types';
import { clamp } from '../core/math';

export type GameState = 'loading' | 'menu' | 'playing' | 'paused' | 'dead' | 'victory';

const SETTINGS_KEY = 'armored-flight-settings-v1';

function loadSettings(): Settings {
  const def: Settings = { sensitivity: 1, invertY: false, quality: 'high', difficulty: 'normal', volume: 0.7, showHelpOnStart: true };
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      const s = { ...def, ...(JSON.parse(raw) as Partial<Settings>) };
      if (s.difficulty !== 'easy' && s.difficulty !== 'normal' && s.difficulty !== 'hard') s.difficulty = 'normal';
      return s;
    }
  } catch {
    /* storage unavailable */
  }
  return def;
}

const _v = new THREE.Vector3();
const _r = new THREE.Vector3();

/** The whole game: renderer, simulation loop, systems wiring, state machine (menu / playing / paused / game over). */
export class Game {
  readonly canvas: HTMLCanvasElement;
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(68, 1, 0.15, 4200);
  readonly input: Input;
  readonly audio = new AudioEngine();
  readonly bus = new Emitter<GameEvents>();
  readonly settings: Settings = loadSettings();
  readonly ctx: GameCtx;
  state: GameState = 'loading';

  physics!: Physics;
  assets = new Assets();
  postfx!: PostFX;
  speedLines!: SpeedLines;
  sky!: Sky;
  chase!: ChaseCamera;
  hud!: Hud;
  waves!: WaveManager;
  overlays!: Overlays;

  private score = 0;
  private kills = 0;
  private acc = 0;
  private lastNow = 0;
  private menuAngle = 0;
  private deadTimer = 0;
  private victoryTimer = -1;
  private quality: Quality;
  private pixelRatio = 1;
  private fpsTimer = 0;
  private fpsFrames = 0;
  fps = 60;
  private lowFpsTime = 0;
  private showFps = false;
  private fpsEl: HTMLElement;
  private shadowsOn = true;
  private started = false;
  private lastKillTime = -10;
  private killStreak = 0;
  private noLockMode = false;
  /** pause automatically when the window loses focus (disabled by automated tests via window.__game.autoPause = false) */
  autoPause = !new URLSearchParams(location.search).has('nopause');

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance', stencil: false });
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.input = new Input(canvas);
    this.quality = this.settings.quality;
    this.fpsEl = document.getElementById('fps')!;
    const self = this;
    // the context object handed to every system; heavy members are filled in during init()
    this.ctx = {
      scene: this.scene,
      camera: this.camera,
      renderer: this.renderer,
      assets: this.assets,
      bus: this.bus,
      input: this.input,
      audio: this.audio,
      settings: this.settings,
      time: 0,
      explode: (o: ExplosionOpts) => explode(self.ctx, o),
      shake: (amount: number) => self.chase?.addShake(amount),
      recoil: (amount: number) => self.chase?.addRecoil(amount),
      addScore: (points: number, label?: string) => self.addScore(points, label),
    } as unknown as GameCtx;
    window.addEventListener('resize', () => this.resize());
    window.addEventListener('blur', () => {
      if (this.state === 'playing' && this.autoPause) this.pause();
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && this.state === 'playing' && this.autoPause) this.pause();
    });
    this.input.onLockChange = (locked) => {
      // losing a lock we really had (Esc) always pauses; environments that never grant the lock keep playing
      if (!locked && this.state === 'playing' && (!this.noLockMode || this.input.everLocked)) this.pause();
    };
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Escape' && this.state === 'playing' && this.noLockMode) this.pause();
      if (e.code === 'KeyM' && this.audio.ready) this.bus.emit('message', { text: this.audio.toggleMute() ? 'AUDIO MUTED' : 'AUDIO ON', kind: 'info', time: 1 });
      if (e.code === 'F3') {
        this.showFps = !this.showFps;
        this.fpsEl.classList.toggle('hidden', !this.showFps);
      }
    });
    document.addEventListener('pointerlockerror', () => {
      if (this.state === 'playing' || this.started) this.enableNoLockFallback();
    });
  }

  // ------------------------------------------------------------------------------------ init
  async init(progress: (fraction: number, label: string) => void) {
    progress(0.02, 'PHYSICS ENGINE');
    this.physics = await Physics.create();
    (this.ctx as { physics: Physics }).physics = this.physics;
    progress(0.06, 'LOADING ARMOUR & CITY ASSETS');
    await this.assets.loadAll((f, label) => progress(0.06 + f * 0.7, `LOADING ${label.toUpperCase()}`));

    progress(0.78, 'PAINTING THE SKY');
    this.sky = new Sky(this.scene);
    this.scene.environment = this.sky.buildEnvironment(this.renderer);
    (this.scene as THREE.Scene & { environmentIntensity: number }).environmentIntensity = 0.85;

    const ctx = this.ctx;
    ctx.fx = new Effects(this.scene, this.camera);
    ctx.debris = new DebrisManager(ctx);
    ctx.projectiles = new ProjectileManager(ctx);
    ctx.pickups = new PickupManager(ctx);
    ctx.enemies = new EnemyManager(ctx);
    ctx.world = new World(ctx);
    ctx.player = new Player(ctx);
    this.waves = new WaveManager(ctx);

    progress(0.84, 'GENERATING CITY');
    await new Promise((r) => setTimeout(r, 30));
    ctx.world.build();
    // ground the player on the spawn roof
    ctx.player.spawn(ctx.world.spawnPoint, ctx.world.spawnHeading);
    this.spawnTurrets();

    progress(0.94, 'POST PROCESSING');
    this.chase = new ChaseCamera(this.camera, this.physics);
    this.postfx = new PostFX(this.renderer, this.scene, this.camera);
    this.speedLines = new SpeedLines(this.scene);
    this.hud = new Hud(ctx);
    this.overlays = new Overlays(this);
    this.applyQuality(this.quality, true);
    this.resize();
    this.chase.reset(ctx.player);
    ctx.player.updateVisual(0.01, 1);

    this.bus.on('score', () => undefined);
    this.bus.on('playerDied', () => {
      this.state = 'dead';
      this.deadTimer = 2.6;
      this.audio.silenceFlight();
      this.input.exitLock();
    });
    this.bus.on('victory', () => {
      this.waves.onVictory();
      this.victoryTimer = 3.2;
    });
    this.bus.on('enemyKilled', (e) => {
      this.kills++;
      if (e.kind === 'drone' || e.kind === 'turret') {
        if (this.ctx.time - this.lastKillTime < 4) this.killStreak++;
        else this.killStreak = 1;
        this.lastKillTime = this.ctx.time;
        if (this.killStreak >= 3) this.addScore(this.killStreak * 25, `${this.killStreak}x STREAK`);
      }
    });

    (window as unknown as { __game: Game }).__game = this;
    this.state = 'menu';
    progress(1, 'READY');
    requestAnimationFrame(this.frame);
  }

  private spawnTurrets() {
    const ctx = this.ctx;
    for (const t of ctx.world.turretSlots) ctx.enemies.spawnTurret(t.pos, t.yaw);
  }

  // ------------------------------------------------------------------------------------ state
  addScore(points: number, label?: string) {
    this.score += points;
    this.hud.scoreValue = this.score;
    this.bus.emit('score', { points, total: this.score, label });
  }

  get currentScore() {
    return this.score;
  }
  get killCount() {
    return this.kills;
  }

  start() {
    this.audio.init();
    this.audio.setVolume(this.settings.volume);
    this.overlays.show(null);
    this.hud.setVisible(true);
    this.input.reset();
    this.input.enabled = true;
    this.input.requestLock();
    this.state = 'playing';
    this.started = true;
    this.acc = 0;
    this.chase.reset(this.ctx.player);
    if (this.waves.state === 'idle') this.waves.start(7);
    // if the pointer lock is refused (embedded browsers) fall back to free mouse look after a moment
    setTimeout(() => {
      if (this.state === 'playing' && !this.input.locked) this.enableNoLockFallback();
    }, 700);
    if (this.settings.showHelpOnStart) {
      this.bus.emit('message', { text: 'PRESS SPACE TO LIFT OFF  -  H FOR CONTROLS', kind: 'info', time: 5 });
    }
  }

  private enableNoLockFallback() {
    if (this.noLockMode) return;
    this.noLockMode = true;
    this.input.fallback = true; // accept mouse deltas without pointer lock
    this.canvas.style.cursor = 'none';
    this.bus.emit('message', { text: 'POINTER LOCK UNAVAILABLE - MOUSE LOOK ACTIVE IN WINDOW', kind: 'warn', time: 4 });
  }

  pause() {
    if (this.state !== 'playing') return;
    this.state = 'paused';
    this.input.enabled = false;
    this.input.reset();
    this.player.clearInput();
    this.audio.silenceFlight();
    this.audio.suspend();
    this.overlays.show('pause');
    this.input.exitLock();
  }

  resume() {
    if (this.state !== 'paused') return;
    this.audio.resume();
    this.overlays.show(null);
    this.input.reset();
    this.input.enabled = true;
    this.input.requestLock();
    this.state = 'playing';
    this.acc = 0;
  }

  restart() {
    const ctx = this.ctx;
    this.overlays.show(null);
    ctx.enemies.clear();
    ctx.projectiles.clear();
    ctx.debris.clear();
    ctx.pickups.clear();
    ctx.fx.clear();
    ctx.world.reset();
    this.spawnTurrets();
    this.score = 0;
    this.kills = 0;
    this.hud.scoreValue = 0;
    this.hud.kills = 0;
    this.hud.clearMessages();
    ctx.player.spawn(ctx.world.spawnPoint, ctx.world.spawnHeading);
    this.waves.reset();
    this.waves.start(7);
    this.victoryTimer = -1;
    this.chase.reset(ctx.player);
    this.input.reset();
    this.input.enabled = true;
    this.input.requestLock();
    this.state = 'playing';
    this.audio.init();
    this.audio.resume();
    this.hud.setVisible(true);
    this.acc = 0;
    this.audio.setMusicIntensity(0.2);
  }

  /** after a death: same wave again with a fresh suit; the city, kills and score are kept */
  retryWave() {
    const ctx = this.ctx;
    const wave = Math.max(1, this.waves.wave);
    if (wave <= 1 && this.score === 0) {
      this.restart();
      return;
    }
    this.overlays.show(null);
    ctx.enemies.clearMobile();
    ctx.projectiles.clear();
    ctx.pickups.clear();
    ctx.fx.clear();
    this.hud.clearMessages();
    ctx.player.spawn(ctx.world.spawnPoint, ctx.world.spawnHeading);
    this.waves.retry(wave);
    this.victoryTimer = -1;
    this.chase.reset(ctx.player);
    this.input.reset();
    this.input.enabled = true;
    this.input.requestLock();
    this.state = 'playing';
    this.audio.init();
    this.audio.resume();
    this.hud.setVisible(true);
    this.acc = 0;
    this.audio.setMusicIntensity(0.2);
    this.bus.emit('message', { text: `RETRYING WAVE ${wave}`, kind: 'info', time: 2.5 });
  }

  continueEndless() {
    this.overlays.show(null);
    this.waves.continueEndless();
    this.input.reset();
    this.input.enabled = true;
    this.input.requestLock();
    this.state = 'playing';
    this.hud.setVisible(true);
    this.acc = 0;
  }

  private get player() {
    return this.ctx.player;
  }

  // ------------------------------------------------------------------------------------ settings / quality
  saveSettings() {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings));
    } catch {
      /* ignore */
    }
  }

  setQuality(q: Quality) {
    this.settings.quality = q;
    this.applyQuality(q);
    this.saveSettings();
  }

  applyQuality(q: Quality, force = false) {
    if (q === this.quality && !force) return;
    this.quality = q;
    const dpr = window.devicePixelRatio || 1;
    this.pixelRatio = q === 'high' ? Math.min(dpr, 1.75) : q === 'medium' ? Math.min(dpr, 1.25) : 1;
    const shadows = q !== 'low';
    if (shadows !== this.shadowsOn || force) {
      this.shadowsOn = shadows;
      this.renderer.shadowMap.enabled = shadows;
      this.sky.sun.castShadow = shadows;
      this.scene.traverse((o) => {
        const m = (o as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
        if (!m) return;
        for (const mat of Array.isArray(m) ? m : [m]) mat.needsUpdate = true;
      });
    }
    this.sky.setShadowQuality(q === 'high' ? 2048 : 1024, q === 'high' ? 150 : 115);
    this.postfx.setQuality(q);
    this.resize();
  }

  private sizeW = 0;
  private sizeH = 0;

  resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    // a hidden / minimised window reports 0 x 0: keep the previous (valid) render target sizes
    if (w < 2 || h < 2) return;
    this.sizeW = w;
    this.sizeH = h;
    this.renderer.setPixelRatio(this.pixelRatio);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.postfx?.setSize(w, h, this.pixelRatio);
  }

  // ------------------------------------------------------------------------------------ loop
  private frame = (nowMs: number) => {
    requestAnimationFrame(this.frame);
    const now = nowMs / 1000;
    const dt = Math.min(0.1, Math.max(0, now - this.lastNow));
    this.lastNow = now;
    if (this.state === 'loading') return;
    if ((window.innerWidth !== this.sizeW || window.innerHeight !== this.sizeH) && window.innerWidth > 1 && window.innerHeight > 1) this.resize();
    this.trackFps(dt);
    const ctx = this.ctx;
    let alpha = 1;

    const simulating = this.state === 'playing' || this.state === 'dead' || this.state === 'victory';
    if (simulating) {
      if (this.state === 'playing') ctx.player.pollInput();
      this.acc += dt;
      let steps = 0;
      while (this.acc >= PHYS.dt && steps < PHYS.maxSteps) {
        this.fixedStep(PHYS.dt);
        this.acc -= PHYS.dt;
        steps++;
      }
      if (steps === PHYS.maxSteps) this.acc = 0;
      alpha = this.acc / PHYS.dt;
    }

    // ---- variable-rate visuals
    this.updateVisuals(dt, alpha);

    // ---- audio listener + engine sound
    if (this.audio.ready) {
      this.camera.getWorldDirection(_v);
      _r.set(1, 0, 0).applyQuaternion(this.camera.quaternion);
      this.audio.setListener(this.camera.position, _r);
      if (this.state === 'playing') {
        const p = ctx.player;
        this.audio.updateFlight(clamp(p.speed / 108, 0, 1), p.flight.mode === 'grounded' ? 0 : 0.25 + p.flight.thrust * 0.75, p.flight.boostAmount);
      }
    }

    // ---- HUD + overlays timers
    if (this.state !== 'menu') {
      this.hud.waveSub = this.waveStatus();
      this.hud.waveNum = Math.max(1, this.waves.wave);
      this.hud.update(dt);
    }
    if (this.state === 'dead') {
      this.deadTimer -= dt;
      if (this.deadTimer <= 0) {
        this.overlays.showGameOver(this.score, this.waves.wave, this.kills);
        this.state = 'paused';
        this.hud.setVisible(false);
      }
    }
    if (this.victoryTimer > 0) {
      this.victoryTimer -= dt;
      if (this.victoryTimer <= 0) {
        this.overlays.showVictory(this.score);
        this.state = 'paused';
        this.input.exitLock();
        this.input.enabled = false;
        this.hud.setVisible(false);
      }
    }

    // ---- render
    const p = ctx.player;
    this.postfx.update(now, clamp(p.speed / 108, 0, 1), p.flight.boostAmount, clamp(p.damageFlash / 0.35, 0, 1), p.weapons.targeting.locked ? 1 : 0);
    this.postfx.render(dt);
    this.input.endFrame();
  };

  /** everything that runs once per rendered frame (not per fixed step) except the final render */
  private updateVisuals(dt: number, alpha: number) {
    const ctx = this.ctx;
    if (this.state !== 'paused') {
      ctx.player.updateVisual(dt, alpha);
      ctx.enemies.syncVisuals(dt, alpha);
      ctx.projectiles.syncVisuals(alpha);
      ctx.debris.update(dt);
      ctx.pickups.update(dt);
      ctx.fx.update(dt);
    }
    if (this.state === 'menu') this.updateMenuCamera(dt);
    else if (this.state !== 'paused') this.chase.update(dt, ctx.player);
    this.camera.updateMatrixWorld(true);
    if (this.state === 'playing' || this.state === 'dead') {
      this.speedLines.update(this.camera.position, ctx.player.vel, clamp(ctx.player.speed / 108, 0, 1), ctx.player.flight.boostAmount);
    } else this.speedLines.mesh.visible = false;
    ctx.world.update(dt, this.camera.position, ctx.player.pos);
    this.sky.update(dt, this.camera, ctx.player.renderPos);
  }

  /**
   * Test / debug helper: run `seconds` of simulation immediately (fixed steps, reduced visual updates) without
   * rendering. Exposed as `window.__game.advance(s)` for automated checks.
   */
  advance(seconds: number) {
    const n = Math.round(seconds / PHYS.dt);
    for (let i = 0; i < n; i++) {
      if (this.state === 'playing') this.ctx.player.pollInput();
      this.fixedStep(PHYS.dt);
      this.input.endFrame();
      if (i % 4 === 3) this.updateVisuals(PHYS.dt * 4, 1);
    }
  }

  private fixedStep(dt: number) {
    const ctx = this.ctx;
    ctx.time += dt;
    ctx.player.preStep(dt);
    ctx.enemies.preStep(dt);
    ctx.projectiles.preStep(dt);
    this.waves.update(dt);
    ctx.physics.step();
    ctx.player.postStep(dt);
    ctx.enemies.postStep();
    ctx.projectiles.postStep(dt);
  }

  private waveStatus() {
    const w = this.waves;
    const e = this.ctx.enemies;
    if (w.state === 'intermission') return w.wave === 0 ? 'HOSTILES INBOUND' : 'RESUPPLY - NEXT WAVE INCOMING';
    if (w.state === 'victory') return 'CITY SECURED';
    const boss = e.boss;
    if (boss && boss.alive) return boss.shieldUp ? 'BREAK THE SHIELD' : 'CORE EXPOSED - FIRE!';
    return `HOSTILES: ${e.aliveDrones} DRONES  ${e.aliveTurrets} TURRETS`;
  }

  private updateMenuCamera(dt: number) {
    const p = this.ctx.player;
    this.menuAngle += dt * 0.18;
    const a = this.menuAngle + Math.PI * 0.75;
    _v.set(Math.sin(a) * 6.2, 1.5 + Math.sin(this.menuAngle * 0.7) * 0.4, Math.cos(a) * 6.2).add(p.renderPos);
    this.camera.position.lerp(_v, 1 - Math.exp(-4 * dt));
    _r.copy(p.renderPos).setY(p.renderPos.y + 0.2);
    this.camera.lookAt(_r);
    if (this.camera.fov !== 52) {
      this.camera.fov = 52;
      this.camera.updateProjectionMatrix();
    }
  }

  private trackFps(dt: number) {
    this.fpsTimer += dt;
    this.fpsFrames++;
    if (this.fpsTimer >= 0.5) {
      this.fps = this.fpsFrames / this.fpsTimer;
      this.fpsTimer = 0;
      this.fpsFrames = 0;
      if (this.showFps) {
        const r = this.renderer.info.render;
        this.fpsEl.textContent = `${this.fps.toFixed(0)} fps  ${this.quality}\ncalls ${r.calls}  tris ${(r.triangles / 1000).toFixed(0)}k\nparticles ${this.ctx.fx.particles.activeCount}  debris ${this.ctx.debris.count}\nbodies ${this.physics.world.bodies.len()}`;
      }
      // adaptive quality: sustained low frame rate lowers the quality tier
      if (this.state === 'playing') {
        if (this.fps < 34) this.lowFpsTime += 0.5;
        else this.lowFpsTime = Math.max(0, this.lowFpsTime - 0.5);
        if (this.lowFpsTime >= 5) {
          this.lowFpsTime = 0;
          const next: Quality | null = this.quality === 'high' ? 'medium' : this.quality === 'medium' ? 'low' : null;
          if (next) {
            // temporary downgrade: the player's saved preference is left untouched
            this.applyQuality(next);
            this.bus.emit('message', { text: `PERFORMANCE MODE: ${next.toUpperCase()}`, kind: 'warn', time: 3 });
          }
        }
      }
    }
  }

  /** score constants re-exported for the HUD */
  static readonly SCORE = SCORE;
}
