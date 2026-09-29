// Dev-only autopilot for automated playtests (not part of the shipped game).
// Usage in the browser console of the dev server:
//   const { bot } = await import('/tools/dev/bot.js'); bot.attach(); bot.run(60);
// It drives the real game through synthetic keyboard/mouse events and only steers the nose directly.

const kd = (code) => window.dispatchEvent(new KeyboardEvent('keydown', { code, bubbles: true }));
const ku = (code) => window.dispatchEvent(new KeyboardEvent('keyup', { code, bubbles: true }));
const md = (b) => window.dispatchEvent(new MouseEvent('mousedown', { button: b, bubbles: true }));
const mu = (b) => window.dispatchEvent(new MouseEvent('mouseup', { button: b, bubbles: true }));
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

export const bot = {
  g: null,
  events: [],
  stats: { kills: { drone: 0, turret: 0, boss: 0 }, missilesFired: 0, minisFired: 0, damageTaken: 0, minArmor: 100 },
  held: new Set(),
  god: false,
  lockOn: false,
  missileTimer: 0,
  miniTimer: 0,
  turnRate: 3.0,
  prefer: 'any', // 'drone' | 'turret' | 'boss' | 'any'
  attached: false,
  expert: false,
  evadeTime: 0,
  evadeDirKey: null,
  evadeVert: 'Space',
  strafeTimer: 0,
  strafeDir: 'KeyA',

  attach() {
    const g = (this.g = window.__game);
    g.noLockMode = true;
    g.input.fallback = true;
    g.autoPause = false;
    if (this.attached) return this;
    this.attached = true;
    g.bus.on('enemyKilled', (e) => {
      this.stats.kills[e.kind]++;
      this.events.push(`t=${g.ctx.time.toFixed(1)} kill ${e.kind}`);
    });
    g.bus.on('wave', (e) => this.events.push(`t=${g.ctx.time.toFixed(1)} wave ${e.wave} ${e.phase}`));
    g.bus.on('message', (e) => this.events.push(`t=${g.ctx.time.toFixed(1)} msg[${e.kind}] ${e.text}`));
    g.bus.on('playerDamaged', (e) => {
      this.stats.damageTaken += e.amount;
      this.stats.minArmor = Math.min(this.stats.minArmor, g.ctx.player.armor);
    });
    g.bus.on('playerDied', () => this.events.push(`t=${g.ctx.time.toFixed(1)} PLAYER DIED`));
    g.bus.on('victory', () => this.events.push(`t=${g.ctx.time.toFixed(1)} VICTORY`));
    return this;
  },

  hold(code, on) {
    if (on && !this.held.has(code)) {
      kd(code);
      this.held.add(code);
    } else if (!on && this.held.has(code)) {
      ku(code);
      this.held.delete(code);
    }
  },
  releaseAll() {
    for (const c of [...this.held]) ku(c);
    this.held.clear();
    mu(0);
  },

  pickTarget() {
    const ctx = this.g.ctx;
    const P = ctx.player;
    let best = null;
    let bd = 1e9;
    if (this.prefer === 'smart') {
      // boss fight: swat nearby escorts first, otherwise hit the boss
      for (const t of ctx.enemies.targets) {
        if (t.kind === 'drone' && t.pos.distanceTo(P.pos) < 85) {
          const d = t.pos.distanceTo(P.pos);
          if (d < bd) {
            bd = d;
            best = t;
          }
        }
      }
      if (best) return best;
      if (ctx.enemies.boss && ctx.enemies.boss.alive) return ctx.enemies.boss;
      for (const t of ctx.enemies.targets) {
        if (t.kind !== 'drone') continue;
        const d = t.pos.distanceTo(P.pos);
        if (d < bd) {
          bd = d;
          best = t;
        }
      }
      return best;
    }
    for (const t of ctx.enemies.targets) {
      if (!t.alive) continue;
      if (this.prefer !== 'any' && t.kind !== this.prefer) continue;
      const d = t.pos.distanceTo(P.pos) - (t.kind === 'boss' ? 30 : 0);
      if (d < bd) {
        bd = d;
        best = t;
      }
    }
    if (!best && this.prefer !== 'any') return null;
    return best;
  },

  wantPickup() {
    const ctx = this.g.ctx;
    const P = ctx.player;
    let best = null;
    let bd = 140;
    // never fly for supplies while a hostile is close, nor during the boss's vulnerable window (unless nearly dead)
    for (const t of ctx.enemies.targets) if (t.kind === 'drone' && t.pos.distanceTo(P.pos) < 75) return null;
    const boss = ctx.enemies.boss;
    if (boss && boss.alive && !boss.shieldUp && P.armor > 35) return null;
    for (const k of ctx.pickups.items) {
      const need =
        (k.kind === 'armor' && P.armor < 75) ||
        (k.kind === 'missiles' && P.weapons.missiles < 6) ||
        (k.kind === 'mini' && P.weapons.minis < 14) ||
        (k.kind === 'energy' && P.energy < 45);
      if (!need || k.life < 4) continue;
      const d = k.pos.distanceTo(P.pos);
      if (d < bd) {
        bd = d;
        best = k;
      }
    }
    return best;
  },

  /** one control tick of `dt` seconds (the caller then advances the simulation by dt) */
  tick(dt) {
    const g = this.g;
    const ctx = g.ctx;
    const P = ctx.player;
    if (!P.alive) return;
    if (this.god) P.invulnerable = 5;
    // collect useful supply canisters that are close by
    const pk = this.wantPickup();
    if (pk) {
      const to = pk.pos.clone().sub(P.pos);
      const f = to.clone().normalize();
      const fl = P.flight;
      const dy = wrap(Math.atan2(-f.x, -f.z) - fl.heading);
      const step = this.turnRate * dt;
      fl.heading += clamp(dy, -step, step);
      fl.pitch = clamp(fl.pitch + clamp(Math.asin(clamp(f.y, -1, 1)) - fl.pitch, -step, step), -1.2, 1.2);
      this.hold('KeyW', true);
      this.hold('KeyS', false);
      this.hold('ShiftLeft', to.length() > 80 && P.energy > 30);
      this.hold('KeyA', false);
      this.hold('KeyD', false);
      if (this.held.has('mouse0')) {
        mu(0);
        this.held.delete('mouse0');
      }
      return;
    }
    const t = this.pickTarget();
    if (!t) {
      this.hold('KeyW', false);
      this.hold('ShiftLeft', false);
      mu(0);
      // stay airborne, hover
      this.hold('Space', P.pos.y < 60 && P.flight.mode !== 'grounded');
      return;
    }
    const to = t.pos.clone().sub(P.pos);
    // the repulsor is a hitscan beam: aim straight at the target
    const dist = to.length();
    const f = to.clone().normalize();
    const wantYaw = Math.atan2(-f.x, -f.z);
    const wantPitch = Math.asin(clamp(f.y, -1, 1));
    const fl = P.flight;
    const dy = wrap(wantYaw - fl.heading);
    const dp = wantPitch - fl.pitch;
    const maxStep = this.turnRate * dt;
    fl.heading += clamp(dy, -maxStep, maxStep);
    fl.pitch = clamp(fl.pitch + clamp(dp, -maxStep, maxStep), -1.2, 1.2);
    const err = Math.hypot(dy, dp);

    const keepOff = t.kind === 'boss' ? (this.expert ? 135 : 70) : t.kind === 'turret' ? 90 : 45;
    // missile defence: break away (boost + strafe + climb/dive) while an enemy missile homes in on us
    const threat = ctx.projectiles.incomingThreat(P, this.expert ? 170 : 95);
    const boss = ctx.enemies.boss;
    const attacking = this.expert && boss && boss.alive && boss.attack && boss.attack.t < 0.4;
    if ((threat || attacking) && this.evadeTime <= 0) {
      this.evadeTime = 1.1;
      this.evadeDirKey = Math.random() < 0.5 ? 'KeyA' : 'KeyD';
      this.evadeVert = Math.random() < 0.5 ? 'Space' : 'KeyC';
    }
    this.evadeTime -= dt;
    const evading = this.evadeTime > 0 && !!this.evadeDirKey;
    this.hold('KeyW', dist > keepOff && !evading);
    this.hold('KeyS', dist < keepOff * 0.6 && !evading);
    this.hold('ShiftLeft', (evading && P.energy > 15) || (dist > 220 && P.energy > 45));
    // strafe randomly to dodge fire (or hard while evading)
    this.strafeTimer = (this.strafeTimer ?? 0) - dt;
    if (this.strafeTimer <= 0) {
      this.strafeTimer = 0.8 + Math.random() * 1.2;
      this.strafeDir = Math.random() < 0.5 ? 'KeyA' : 'KeyD';
    }
    const side = evading ? this.evadeDirKey : this.strafeDir;
    this.hold('KeyA', side === 'KeyA');
    this.hold('KeyD', side === 'KeyD');
    const wantUp = evading ? this.evadeVert === 'Space' : P.flight.mode === 'grounded' || P.pos.y < 30;
    this.hold('Space', wantUp);
    this.hold('KeyC', evading && this.evadeVert === 'KeyC' && P.pos.y > 40);
    // repulsor when tightly aligned (the beam is hitscan) and there is energy left
    const wantFire = err < 0.015 + 1.2 / Math.max(dist, 20) && dist < 220 && P.energy > 6;
    if (wantFire && !this.held.has('mouse0')) {
      md(0);
      this.held.add('mouse0');
    } else if (!wantFire && this.held.has('mouse0')) {
      mu(0);
      this.held.delete('mouse0');
    }
    // lock + missiles
    if (!this.lockOn) {
      md(2);
      mu(2);
      this.lockOn = true;
    }
    this.missileTimer -= dt;
    this.miniTimer -= dt;
    const w = P.weapons;
    const spendOk = !this.expert || (t.kind === 'boss' && ctx.enemies.boss && ctx.enemies.boss.shieldUp);
    if (w.targeting.locked && this.missileTimer <= 0 && dist > 40 && spendOk) {
      kd('Digit1');
      ku('Digit1');
      this.missileTimer = 1.0;
      this.stats.missilesFired++;
    }
    if (this.miniTimer <= 0 && dist < 260 && dist > 30 && err < 0.4 && spendOk) {
      kd('Digit2');
      ku('Digit2');
      this.miniTimer = 4;
      this.stats.minisFired++;
    }
  },

  /** run `seconds` of game time in 1/15 s control ticks */
  run(seconds, until) {
    const g = this.g;
    const dt = 1 / 15;
    const n = Math.round(seconds / dt);
    for (let i = 0; i < n; i++) {
      if (g.state !== 'playing' || !g.ctx.player.alive) break;
      this.tick(dt);
      g.advance(dt);
      if (until && until()) break;
    }
    this.releaseAll();
  },

  /** fresh mission -> takeoff -> jump straight to the boss wave -> fight for up to `maxSeconds` */
  bossTrial(maxSeconds = 150, { keepEscorts = true, turrets = true } = {}) {
    const g = this.g;
    const ctx = g.ctx;
    g.restart();
    g.state = 'playing';
    if (!turrets) {
      for (const t of ctx.enemies.turrets) if (t.alive) t.takeDamage(9999, { point: t.pos.clone(), source: 'explosion' });
      ctx.pickups.clear();
    }
    this.events.length = 0;
    this.stats = { kills: { drone: 0, turret: 0, boss: 0 }, missilesFired: 0, minisFired: 0, damageTaken: 0, minArmor: 100 };
    this.lockOn = false;
    this.prefer = 'smart';
    this.evadeTime = 0;
    this.hold('Space', true);
    g.advance(1.5);
    this.hold('Space', false);
    g.waves.wave = 2;
    g.waves.state = 'intermission';
    g.waves.timer = 0.5;
    g.advance(1.0);
    if (!keepEscorts) {
      for (const d of ctx.enemies.drones) d.takeDamage(999, { point: d.pos.clone(), source: 'explosion' });
      g.waves.escortTimer = 1e9;
    }
    this.run(maxSeconds, () => g.waves.state === 'victory' || (!ctx.enemies.boss && g.waves.wave === 3 && this.stats.kills.boss > 0));
    const out = this.summary();
    g.state = 'paused';
    return out;
  },

  summary() {
    const g = this.g;
    const ctx = g.ctx;
    const P = ctx.player;
    const e = ctx.enemies;
    return {
      state: g.state,
      time: +ctx.time.toFixed(1),
      wave: g.waves.wave,
      waveState: g.waves.state,
      armor: +P.armor.toFixed(1),
      energy: +P.energy.toFixed(1),
      ammo: { missiles: P.weapons.missiles, minis: P.weapons.minis },
      score: g.currentScore,
      drones: e.aliveDrones,
      turrets: e.aliveTurrets,
      boss: e.boss ? { hp: +e.boss.healthFraction().toFixed(2), shield: +e.boss.shieldFraction().toFixed(2) } : null,
      pos: P.pos.toArray().map((v) => +v.toFixed(0)),
      stats: this.stats,
    };
  },
};

export default bot;
