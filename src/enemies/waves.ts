import * as THREE from 'three';
import type { GameCtx } from '../game/types';
import { SCORE } from '../config';

export type WaveState = 'idle' | 'intermission' | 'active' | 'victory';

const _v = new THREE.Vector3();

/**
 * Wave director: wave 1 and 2 are drone raids on top of the rooftop turrets, wave 3 brings the boss with escort drones.
 * After the boss falls the player may continue into endless drone waves.
 */
export class WaveManager {
  wave = 0;
  state: WaveState = 'idle';
  private timer = 0;
  private escortTimer = 0;
  endless = false;
  totalToKill = 0;
  private bossWave = 3;

  constructor(private ctx: GameCtx) {}

  reset() {
    this.wave = 0;
    this.state = 'idle';
    this.timer = 0;
    this.endless = false;
    this.escortTimer = 0;
  }

  start(delay = 5) {
    this.wave = 0;
    this.state = 'intermission';
    this.timer = delay;
  }

  /** restart wave `n` after the player was lost (the wave counter is set so that the next wave to begin is `n`) */
  retry(n: number, delay = 4) {
    this.wave = Math.max(0, n - 1);
    this.state = 'intermission';
    this.timer = delay;
    this.escortTimer = 0;
  }

  continueEndless() {
    this.endless = true;
    this.state = 'intermission';
    this.timer = 6;
    this.ctx.bus.emit('message', { text: 'ENDLESS MODE - HOLD THE CITY', kind: 'info', time: 3 });
  }

  update(dt: number) {
    const e = this.ctx.enemies;
    switch (this.state) {
      case 'intermission':
        this.timer -= dt;
        if (this.timer <= 0) this.beginWave(this.wave + 1);
        break;
      case 'active':
        if (this.wave === this.bossWave && !this.endless) {
          // boss wave: keep a few escorts alive
          this.escortTimer -= dt;
          if (e.boss && e.boss.alive && e.aliveDrones < 2 && this.escortTimer <= 0) {
            this.escortTimer = 30;
            this.spawnDrones(2, true);
          }
        } else if (e.aliveDrones === 0) {
          this.waveClear();
        }
        break;
      default:
        break;
    }
  }

  private beginWave(n: number) {
    const ctx = this.ctx;
    this.wave = n;
    this.state = 'active';
    ctx.bus.emit('wave', { wave: n, phase: 'start' });
    ctx.audio.waveStart();
    if (n === this.bossWave && !this.endless) {
      ctx.bus.emit('message', { text: `WAVE ${n} - ARMORED BEHEMOTH`, kind: 'bad', time: 3.5 });
      ctx.bus.emit('message', { text: 'BEHEMOTH JAMMING FIELD - ROOFTOP TURRETS OFFLINE', kind: 'info', time: 3.5 });
      ctx.enemies.spawnBoss(_v.set(0, 0, 0));
      this.spawnDrones(3, true);
      this.escortTimer = 24;
    } else {
      const count = this.endless ? Math.min(22, 8 + 2 * (n - this.bossWave)) : n === 1 ? 5 : 8;
      ctx.bus.emit('message', { text: `WAVE ${n} - ${count} HOSTILE DRONES`, kind: 'bad', time: 3 });
      this.spawnDrones(count, n >= 2);
    }
  }

  private spawnDrones(count: number, someAggressive: boolean) {
    const ctx = this.ctx;
    for (let i = 0; i < count; i++) {
      const p = ctx.enemies.findAirSpawn(ctx.player.pos, 170, 280, 45, 150, new THREE.Vector3());
      ctx.enemies.spawnDrone(p, someAggressive && i % 2 === 0);
    }
  }

  private waveClear() {
    const ctx = this.ctx;
    this.state = 'intermission';
    this.timer = 8;
    ctx.bus.emit('wave', { wave: this.wave, phase: 'clear' });
    ctx.addScore(SCORE.wave, 'WAVE CLEARED');
    // resupply: some armour, energy and ammunition - a full one before the boss
    const bossNext = !this.endless && this.wave + 1 === this.bossWave;
    ctx.bus.emit('message', { text: bossNext ? `WAVE ${this.wave} CLEARED - FULL RESUPPLY` : `WAVE ${this.wave} CLEARED - RESUPPLY`, kind: 'good', time: 3 });
    if (bossNext) ctx.bus.emit('message', { text: 'SAVE MISSILES FOR THE BEHEMOTH SHIELD', kind: 'info', time: 4 });
    ctx.audio.waveClear();
    ctx.player.repair(bossNext ? 100 : 25);
    ctx.player.addEnergy(bossNext ? 100 : 60);
    ctx.player.weapons.addAmmo(bossNext ? 99 : 3, bossNext ? 99 : 8);
  }

  /** boss defeated */
  onVictory() {
    this.state = 'victory';
  }
}
