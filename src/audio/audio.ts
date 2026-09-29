import * as THREE from 'three';

/**
 * Fully procedural WebAudio sound engine (no audio files): engine hum, repulsor zaps, launches, explosions,
 * lock tones, warnings. Simple 3D: distance attenuation + stereo pan from the camera listener.
 */
export class AudioEngine {
  private ctx: AudioContext | null = null;
  private master!: GainNode;
  private sfx!: GainNode;
  private noise!: AudioBuffer;
  private engineGain!: GainNode;
  private engineOsc!: OscillatorNode;
  private engineOsc2!: OscillatorNode;
  private windFilter!: BiquadFilterNode;
  private windGain!: GainNode;
  private boostGain!: GainNode;
  private boostFilter!: BiquadFilterNode;
  private musicGain!: GainNode;
  volume = 0.7;
  muted = false;
  private listenerPos = new THREE.Vector3();
  private listenerRight = new THREE.Vector3(1, 0, 0);
  private lastLock = 0;

  get ready() {
    return this.ctx !== null;
  }

  /** Must be called from a user gesture (click / key). Safe to call repeatedly. */
  init() {
    if (this.ctx) {
      if (this.ctx.state === 'suspended') void this.ctx.resume();
      return;
    }
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    this.ctx = ctx;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -14;
    comp.ratio.value = 6;
    comp.attack.value = 0.004;
    comp.release.value = 0.2;
    this.master = ctx.createGain();
    this.master.gain.value = this.muted ? 0 : this.volume;
    this.master.connect(comp).connect(ctx.destination);
    this.sfx = ctx.createGain();
    this.sfx.gain.value = 1;
    this.sfx.connect(this.master);

    // 2 s of white noise reused by every noise voice
    const len = ctx.sampleRate * 2;
    this.noise = ctx.createBuffer(1, len, ctx.sampleRate);
    const d = this.noise.getChannelData(0);
    let seed = 12345;
    for (let i = 0; i < len; i++) {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      d[i] = (seed / 4294967296) * 2 - 1;
    }
    this.buildEngine();
    this.buildMusic();
  }

  setVolume(v: number) {
    this.volume = v;
    if (this.ctx) this.master.gain.setTargetAtTime(this.muted ? 0 : v, this.ctx.currentTime, 0.05);
  }

  toggleMute() {
    this.muted = !this.muted;
    if (this.ctx) this.master.gain.setTargetAtTime(this.muted ? 0 : this.volume, this.ctx.currentTime, 0.05);
    return this.muted;
  }

  suspend() {
    if (this.ctx && this.ctx.state === 'running') void this.ctx.suspend();
  }
  resume() {
    if (this.ctx && this.ctx.state === 'suspended') void this.ctx.resume();
  }

  // ------------------------------------------------------------------ continuous voices
  private buildEngine() {
    const ctx = this.ctx!;
    // low turbine: two detuned saws through a lowpass
    this.engineGain = ctx.createGain();
    this.engineGain.gain.value = 0;
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 420;
    this.engineOsc = ctx.createOscillator();
    this.engineOsc.type = 'sawtooth';
    this.engineOsc.frequency.value = 62;
    this.engineOsc2 = ctx.createOscillator();
    this.engineOsc2.type = 'sawtooth';
    this.engineOsc2.frequency.value = 63.7;
    this.engineOsc.connect(lp);
    this.engineOsc2.connect(lp);
    lp.connect(this.engineGain).connect(this.master);
    this.engineOsc.start();
    this.engineOsc2.start();

    // wind / air rush: band-passed noise, follows speed
    const wind = ctx.createBufferSource();
    wind.buffer = this.noise;
    wind.loop = true;
    this.windFilter = ctx.createBiquadFilter();
    this.windFilter.type = 'bandpass';
    this.windFilter.frequency.value = 500;
    this.windFilter.Q.value = 0.6;
    this.windGain = ctx.createGain();
    this.windGain.gain.value = 0;
    wind.connect(this.windFilter).connect(this.windGain).connect(this.master);
    wind.start();

    // boost roar: highpassed noise
    const boost = ctx.createBufferSource();
    boost.buffer = this.noise;
    boost.loop = true;
    this.boostFilter = ctx.createBiquadFilter();
    this.boostFilter.type = 'highpass';
    this.boostFilter.frequency.value = 900;
    this.boostGain = ctx.createGain();
    this.boostGain.gain.value = 0;
    boost.connect(this.boostFilter).connect(this.boostGain).connect(this.master);
    boost.start();
  }

  private buildMusic() {
    // very quiet evolving pad so the city is never dead silent
    const ctx = this.ctx!;
    this.musicGain = ctx.createGain();
    this.musicGain.gain.value = 0.05;
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 700;
    lp.Q.value = 2;
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 0.07;
    const lfoGain = ctx.createGain();
    lfoGain.gain.value = 300;
    lfo.connect(lfoGain).connect(lp.frequency);
    lfo.start();
    for (const [f, det] of [[55, 0], [82.4, 4], [110, -5], [164.8, 3]] as const) {
      const o = ctx.createOscillator();
      o.type = 'sawtooth';
      o.frequency.value = f;
      o.detune.value = det;
      const g = ctx.createGain();
      g.gain.value = f < 100 ? 0.5 : 0.22;
      o.connect(g).connect(lp);
      o.start();
    }
    lp.connect(this.musicGain).connect(this.master);
  }

  setMusicIntensity(v: number) {
    if (!this.ctx) return;
    this.musicGain.gain.setTargetAtTime(0.035 + 0.06 * v, this.ctx.currentTime, 1.0);
  }

  /** per-frame: flight sound follows speed / thrust / boost */
  updateFlight(speed01: number, thrust01: number, boost01: number) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    const base = 58 + 34 * thrust01 + 30 * boost01 + 10 * speed01;
    this.engineOsc.frequency.setTargetAtTime(base, t, 0.08);
    this.engineOsc2.frequency.setTargetAtTime(base * 1.027, t, 0.08);
    this.engineGain.gain.setTargetAtTime(0.05 + 0.085 * thrust01 + 0.06 * boost01, t, 0.1);
    this.windGain.gain.setTargetAtTime(0.008 + 0.16 * speed01 * speed01, t, 0.15);
    this.windFilter.frequency.setTargetAtTime(350 + 1800 * speed01, t, 0.15);
    this.boostGain.gain.setTargetAtTime(0.11 * boost01, t, 0.08);
    this.boostFilter.frequency.setTargetAtTime(700 + 800 * boost01, t, 0.1);
  }

  silenceFlight() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.engineGain.gain.setTargetAtTime(0, t, 0.1);
    this.windGain.gain.setTargetAtTime(0, t, 0.1);
    this.boostGain.gain.setTargetAtTime(0, t, 0.1);
  }

  setListener(pos: THREE.Vector3, right: THREE.Vector3) {
    this.listenerPos.copy(pos);
    this.listenerRight.copy(right);
  }

  // ------------------------------------------------------------------ one shots
  /** returns [gain, pan] for a 3D source, or null if inaudible */
  private spatial(at?: THREE.Vector3, refDist = 45): [number, number] | null {
    if (!at) return [1, 0];
    const dx = at.x - this.listenerPos.x;
    const dy = at.y - this.listenerPos.y;
    const dz = at.z - this.listenerPos.z;
    const d = Math.hypot(dx, dy, dz);
    const g = 1 / (1 + (d / refDist) * (d / refDist) * 0.6);
    if (g < 0.02) return null;
    const pan = d > 0.5 ? Math.max(-1, Math.min(1, (dx * this.listenerRight.x + dy * this.listenerRight.y + dz * this.listenerRight.z) / d)) : 0;
    return [g, pan * 0.85];
  }

  private out(gainNode: GainNode, pan: number) {
    const ctx = this.ctx!;
    if (pan !== 0 && ctx.createStereoPanner) {
      const p = ctx.createStereoPanner();
      p.pan.value = pan;
      gainNode.connect(p).connect(this.sfx);
    } else gainNode.connect(this.sfx);
  }

  private tone(type: OscillatorType, f0: number, f1: number, dur: number, gain: number, at?: THREE.Vector3, delay = 0, refDist = 45) {
    if (!this.ctx) return;
    const sp = this.spatial(at, refDist);
    if (!sp) return;
    const ctx = this.ctx;
    const t = ctx.currentTime + delay;
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain * sp[0], t + Math.min(0.01, dur * 0.2));
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g);
    this.out(g, sp[1]);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  private burst(
    filterType: BiquadFilterType, f0: number, f1: number, dur: number, gain: number, q = 0.8, at?: THREE.Vector3,
    delay = 0, attack = 0.005, refDist = 45,
  ) {
    if (!this.ctx) return;
    const sp = this.spatial(at, refDist);
    if (!sp) return;
    const ctx = this.ctx;
    const t = ctx.currentTime + delay;
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    src.loop = true;
    const f = ctx.createBiquadFilter();
    f.type = filterType;
    f.Q.value = q;
    f.frequency.setValueAtTime(f0, t);
    f.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain * sp[0], t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g);
    this.out(g, sp[1]);
    src.start(t, Math.random() * 1.5);
    src.stop(t + dur + 0.05);
  }

  repulsor(at?: THREE.Vector3) {
    this.tone('sawtooth', 1500, 260, 0.09, 0.22, at);
    this.tone('square', 700, 180, 0.07, 0.08, at);
    this.burst('highpass', 3000, 6000, 0.05, 0.12, 0.7, at);
  }

  missileLaunch(at?: THREE.Vector3) {
    this.burst('bandpass', 500, 3200, 0.7, 0.5, 0.9, at, 0, 0.02);
    this.tone('sine', 120, 45, 0.3, 0.4, at);
  }

  miniLaunch(at?: THREE.Vector3) {
    this.burst('bandpass', 900, 4200, 0.35, 0.28, 1.0, at, 0, 0.01);
    this.tone('sine', 200, 70, 0.14, 0.2, at);
  }

  enemyFire(at?: THREE.Vector3) {
    this.tone('square', 900, 220, 0.11, 0.13, at, 0, 70);
    this.burst('highpass', 2500, 5000, 0.06, 0.06, 0.7, at, 0, 0.005, 70);
  }

  enemyMissile(at?: THREE.Vector3) {
    this.burst('bandpass', 350, 1800, 0.6, 0.36, 0.9, at, 0, 0.03, 90);
    this.tone('sine', 90, 40, 0.35, 0.3, at, 0, 90);
  }

  explosion(scale = 1, at?: THREE.Vector3) {
    const s = Math.min(2.5, scale);
    this.burst('lowpass', 2600, 90, 0.5 + 0.8 * s, 0.9, 0.7, at, 0, 0.004, 90 * s);
    this.tone('sine', 95, 26, 0.4 + 0.5 * s, 0.85, at, 0, 90 * s);
    this.burst('highpass', 2500, 700, 0.18, 0.28, 0.7, at, 0, 0.002, 90 * s);
  }

  impact(at?: THREE.Vector3) {
    this.burst('bandpass', 2600, 1200, 0.07, 0.16, 1.2, at);
  }

  playerHit(severity = 1) {
    this.tone('sine', 140, 40, 0.28, 0.6 * severity);
    this.burst('lowpass', 1800, 200, 0.3, 0.55 * severity, 0.8);
  }

  shieldHit(at?: THREE.Vector3) {
    this.tone('sine', 1100, 700, 0.35, 0.16, at, 0, 200);
    this.tone('sine', 1650, 1000, 0.3, 0.1, at, 0, 200);
    this.burst('bandpass', 3800, 2200, 0.15, 0.1, 2.0, at, 0, 0.005, 200);
  }

  shieldBreak(at?: THREE.Vector3) {
    this.burst('lowpass', 4000, 150, 1.6, 0.85, 0.8, at, 0, 0.01, 400);
    this.tone('sawtooth', 900, 60, 1.2, 0.35, at, 0, 400);
    this.tone('sine', 70, 30, 1.4, 0.7, at, 0, 400);
  }

  shieldUp(at?: THREE.Vector3) {
    this.tone('sine', 200, 1200, 0.9, 0.22, at, 0, 400);
  }

  bossRoar(at?: THREE.Vector3) {
    this.tone('sawtooth', 48, 38, 2.4, 0.5, at, 0, 500);
    this.tone('sawtooth', 72, 52, 2.2, 0.28, at, 0, 500);
    this.burst('lowpass', 300, 90, 2.4, 0.4, 0.8, at, 0, 0.4, 500);
  }

  lockTick(progress: number) {
    const now = performance.now();
    if (now - this.lastLock < 90) return;
    this.lastLock = now;
    this.tone('sine', 700 + progress * 900, 700 + progress * 900, 0.045, 0.16);
  }

  lockConfirm() {
    this.tone('square', 1500, 1500, 0.08, 0.16);
    this.tone('square', 2000, 2000, 0.14, 0.16, undefined, 0.09);
  }

  lockLost() {
    this.tone('sawtooth', 500, 200, 0.2, 0.14);
  }

  noAmmo() {
    this.tone('square', 240, 200, 0.07, 0.14);
  }

  warning() {
    this.tone('square', 880, 880, 0.1, 0.13);
    this.tone('square', 660, 660, 0.1, 0.13, undefined, 0.12);
  }

  pickup() {
    this.tone('sine', 660, 660, 0.09, 0.18);
    this.tone('sine', 880, 880, 0.09, 0.18, undefined, 0.07);
    this.tone('sine', 1320, 1320, 0.16, 0.18, undefined, 0.14);
  }

  ui() {
    this.tone('sine', 900, 700, 0.05, 0.12);
  }

  boostStart() {
    this.burst('bandpass', 300, 3000, 0.6, 0.45, 0.7, undefined, 0, 0.05);
  }

  modeSwitch(toHover: boolean) {
    this.tone('sine', toHover ? 500 : 300, toHover ? 300 : 600, 0.25, 0.2);
    this.burst('bandpass', 600, toHover ? 300 : 1200, 0.25, 0.15, 0.9);
  }

  waveStart() {
    this.tone('sawtooth', 110, 110, 0.5, 0.25);
    this.tone('sawtooth', 165, 165, 0.5, 0.2, undefined, 0.15);
    this.tone('sawtooth', 220, 220, 0.9, 0.22, undefined, 0.3);
  }

  waveClear() {
    for (let i = 0; i < 4; i++) this.tone('sine', 523 * Math.pow(1.26, i), 523 * Math.pow(1.26, i), 0.25, 0.2, undefined, i * 0.11);
  }
}
