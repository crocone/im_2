import * as THREE from 'three';
import type { GameCtx, Target } from '../game/types';
import { WORLD } from '../config';
import { clamp, fmtInt } from '../core/math';

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

const _v = new THREE.Vector3();
const _vc = new THREE.Vector3();

interface MarkerEl {
  root: HTMLElement;
  info: HTMLElement;
  hp: HTMLElement;
  ring: SVGCircleElement;
  cache: string;
  shown: boolean;
}

/**
 * The tactical HUD: everything is plain HTML/CSS (frames, bars, gauges) driven every frame from the game state.
 * Target brackets and off-screen arrows are positioned by projecting the 3D positions through the Three.js camera.
 */
export class Hud {
  private el = {
    hud: $('hud'),
    speed: $('speed'), alt: $('alt'), speedFill: $('speed-fill'), boostFill: $('boost-fill'), mode: $('mode-label'), boostTag: $('boost-label'),
    armorVal: $('armor-val'), armorFill: $('armor-fill'), energyVal: $('energy-val'), energyFill: $('energy-fill'),
    missileCount: $('missile-count'), missileMax: $('missile-max'), missileBar: $('missile-bar'),
    miniCount: $('mini-count'), miniMax: $('mini-max'), miniBar: $('mini-bar'), repBar: $('rep-bar'), fireMode: $('fire-mode'),
    wave: $('wave-num'), score: $('score'), waveSub: $('wave-sub'),
    bossBlock: $('boss-block'), bossShield: $('boss-shield'), bossHull: $('boss-hull'), bossStatus: $('boss-status'), bossName: $('boss-name'),
    reticle: $('reticle'), lockText: $('lock-text'), hitmarker: $('hitmarker'),
    markers: $('markers'), arrows: $('arrows'), alerts: $('alerts'), messages: $('messages'),
    dmg: $('dmg-vignette'), lowhp: $('lowhp-vignette'),
    radar: $('radar') as HTMLCanvasElement, radarHdg: $('radar-hdg'),
    wpnMissile: $('wpn-missile'), wpnMini: $('wpn-mini'), wpnRep: $('wpn-repulsor'),
    suit: $('suit-parts'), suitCore: $('s-core'),
  };
  private radarCtx: CanvasRenderingContext2D;
  private markerPool: MarkerEl[] = [];
  private arrowPool: HTMLElement[] = [];
  private cache = new Map<HTMLElement, string>();
  private time = 0;
  private alertKey = '';
  private lastMissileCount = -1;
  private lastMiniCount = -1;
  private flashM = 0;
  private flashMini = 0;
  waveSub = '';
  waveNum = 1;
  kills = 0;
  private sweep = 0;

  constructor(private ctx: GameCtx) {
    this.radarCtx = this.el.radar.getContext('2d')!;
    for (let i = 0; i < 18; i++) this.markerPool.push(this.makeMarker());
    for (let i = 0; i < 8; i++) {
      const a = document.createElement('div');
      a.className = 'arrow';
      this.el.arrows.appendChild(a);
      this.arrowPool.push(a);
    }
    ctx.bus.on('message', (m) => this.pushMessage(m.text, m.kind, m.time ?? 2));
    ctx.bus.on('bossState', (b) => this.setText(this.el.bossStatus, b.text));
    ctx.bus.on('enemyKilled', () => {
      this.kills++;
      this.flashHit('kill');
    });
    ctx.bus.on('hit', (h) => this.flashHit(h.shield ? 'shield' : 'hit'));
  }

  private makeMarker(): MarkerEl {
    const root = document.createElement('div');
    root.className = 'marker';
    root.innerHTML =
      '<i></i><i></i><i></i><i></i><div class="m-info"></div><div class="m-hp"><b></b></div>' +
      '<svg class="m-lock" viewBox="0 0 100 100"><circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="289" stroke-dashoffset="289" transform="rotate(-90 50 50)"/></svg>';
    this.el.markers.appendChild(root);
    return {
      root,
      info: root.querySelector('.m-info') as HTMLElement,
      hp: root.querySelector('.m-hp b') as HTMLElement,
      ring: root.querySelector('circle') as SVGCircleElement,
      cache: '',
      shown: false,
    };
  }

  private setText(el: HTMLElement, text: string) {
    if (this.cache.get(el) !== text) {
      this.cache.set(el, text);
      el.textContent = text;
    }
  }
  private setStyle(el: HTMLElement, prop: 'width' | 'opacity', value: string) {
    const key = `${prop}:${value}`;
    const k = (el as unknown as { __s?: Record<string, string> });
    k.__s ??= {};
    if (k.__s[prop] !== key) {
      k.__s[prop] = key;
      el.style[prop] = value;
    }
  }

  setVisible(v: boolean) {
    this.el.hud.classList.toggle('hidden', !v);
  }

  pushMessage(text: string, kind: 'info' | 'warn' | 'good' | 'bad', time: number) {
    const host = this.el.messages;
    // collapse duplicates
    for (const c of Array.from(host.children) as HTMLElement[]) if (c.textContent === text) c.remove();
    const d = document.createElement('div');
    d.className = `msg ${kind === 'info' ? '' : kind}`;
    d.textContent = text;
    host.appendChild(d);
    while (host.children.length > 3) host.firstElementChild?.remove();
    setTimeout(() => d.classList.add('fade'), Math.max(200, time * 1000 - 400));
    setTimeout(() => d.remove(), time * 1000);
  }

  /** restart the hit-marker animation at the reticle (kill = red, shield = cyan, plain hit = white) */
  private flashHit(kind: 'hit' | 'shield' | 'kill') {
    const el = this.el.hitmarker;
    // a kill marker is not overwritten by the plain hit of the same instant
    if (kind !== 'kill' && el.classList.contains('kill') && el.classList.contains('on') && this.time - this.lastKillFlash < 0.12) return;
    if (kind === 'kill') this.lastKillFlash = this.time;
    el.className = `hitmarker ${kind}`;
    void el.offsetWidth; // force a reflow so the CSS animation restarts
    el.classList.add('on');
  }
  private lastKillFlash = -10;

  clearMessages() {
    this.el.messages.innerHTML = '';
  }

  // ---------------------------------------------------------------------------------- per frame
  update(dt: number) {
    this.time += dt;
    const ctx = this.ctx;
    const p = ctx.player;
    const e = this.el;

    // ---- flight instruments
    const kmh = p.speed * 3.6;
    this.setText(e.speed, String(Math.round(kmh)));
    this.setText(e.alt, String(Math.max(0, Math.round(p.altitude))));
    this.setStyle(e.speedFill, 'width', '');
    e.speedFill.style.height = `${clamp(p.speed / 108, 0, 1) * 100}%`;
    e.boostFill.style.height = `${clamp(p.energy / 100, 0, 1) * 100}%`;
    const mode = p.flight.mode === 'grounded' ? 'LANDED' : p.flight.mode === 'hover' ? 'HOVER' : 'FLIGHT';
    this.setText(e.mode, mode);
    e.boostTag.classList.toggle('on', p.flight.boosting);

    // ---- armor / energy
    const armor = Math.round(p.armor);
    const energy = Math.round(p.energy);
    this.setText(e.armorVal, `${armor}%`);
    this.setText(e.energyVal, `${energy}%`);
    e.armorFill.style.width = `${clamp(p.armor, 0, 100)}%`;
    e.energyFill.style.width = `${clamp(p.energy, 0, 100)}%`;
    e.armorFill.parentElement!.classList.toggle('low', armor < 30);
    e.energyFill.parentElement!.classList.toggle('low', energy < 20);

    // ---- weapons
    const w = p.weapons;
    this.setText(e.missileCount, String(w.missiles));
    this.setText(e.missileMax, String(w.missilesMax));
    this.setText(e.miniCount, String(w.minis));
    this.setText(e.miniMax, String(w.minisMax));
    e.missileBar.style.width = `${(w.missiles / w.missilesMax) * 100}%`;
    e.miniBar.style.width = `${(w.minis / w.minisMax) * 100}%`;
    e.repBar.style.width = `${clamp(p.energy, 0, 100)}%`;
    this.setText(e.fireMode, w.dualFire ? 'DUAL' : 'ALT');
    e.wpnMissile.classList.toggle('empty', w.missiles === 0);
    e.wpnMini.classList.toggle('empty', w.minis === 0);
    e.wpnRep.classList.toggle('empty', p.energy < 3);
    if (this.lastMissileCount !== w.missiles) {
      if (this.lastMissileCount >= 0) this.flashM = 0.25;
      this.lastMissileCount = w.missiles;
    }
    if (this.lastMiniCount !== w.minis) {
      if (this.lastMiniCount >= 0) this.flashMini = 0.25;
      this.lastMiniCount = w.minis;
    }
    this.flashM = Math.max(0, this.flashM - dt);
    this.flashMini = Math.max(0, this.flashMini - dt);
    e.wpnMissile.classList.toggle('flash', this.flashM > 0);
    e.wpnMini.classList.toggle('flash', this.flashMini > 0);
    e.wpnRep.classList.toggle('flash', w.firing);

    // ---- wave / score / boss
    this.setText(e.score, fmtInt(this.ctx.player ? this.scoreValue : 0));
    this.setText(e.wave, String(this.waveNum));
    this.setText(e.waveSub, this.waveSub);
    const boss = ctx.enemies.boss;
    e.bossBlock.classList.toggle('hidden', !boss);
    if (boss) {
      this.setText(e.bossName, boss.label);
      e.bossShield.style.width = `${boss.shieldFraction() * 100}%`;
      e.bossHull.style.width = `${boss.healthFraction() * 100}%`;
    }

    // ---- reticle + lock
    this.updateReticle();
    this.updateMarkers();
    this.drawRadar(dt);
    this.updateAlerts();
    this.updateSuit();

    // ---- damage overlays
    const flash = clamp(p.damageFlash / 0.35, 0, 1);
    e.dmg.style.opacity = String(flash * 0.85);
    const low = armor < 30 && p.alive ? 0.35 + 0.25 * Math.sin(this.time * 6) : 0;
    e.lowhp.style.opacity = String(Math.max(0, low));
  }

  scoreValue = 0;

  private updateReticle() {
    const ctx = this.ctx;
    const p = ctx.player;
    const cam = ctx.camera;
    const W = window.innerWidth;
    const H = window.innerHeight;
    _v.copy(p.renderPos).addScaledVector(p.flight.forward, 150);
    _vc.copy(_v).applyMatrix4(cam.matrixWorldInverse);
    const r = this.el.reticle;
    if (_vc.z > 0) {
      r.style.display = 'none';
      return;
    }
    r.style.display = '';
    _v.project(cam);
    const x = (_v.x * 0.5 + 0.5) * W;
    const y = (-_v.y * 0.5 + 0.5) * H;
    r.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
    const t = p.weapons.targeting;
    const enemyUnder = t.candidate !== null;
    r.classList.toggle('enemy', enemyUnder && !t.locked);
    r.classList.toggle('locked', t.locked);
    let txt = '';
    if (t.lockMode) {
      if (t.state === 'searching') txt = 'SEARCHING';
      else if (t.state === 'acquiring') txt = `ACQUIRING ${Math.round(t.progress * 100)}%`;
      else txt = 'LOCKED';
    }
    this.setText(this.el.lockText, txt);
    this.el.lockText.classList.toggle('locked', t.state === 'locked' && t.lockMode);
  }

  private updateMarkers() {
    const ctx = this.ctx;
    const cam = ctx.camera;
    const W = window.innerWidth;
    const H = window.innerHeight;
    const targets = ctx.enemies.targets;
    const t = ctx.player.weapons.targeting;
    const pos = ctx.player.pos;
    const list: { t: Target; d: number }[] = [];
    for (const tg of targets) {
      const d = tg.pos.distanceTo(pos);
      if (d < 950) list.push({ t: tg, d });
    }
    list.sort((a, b) => a.d - b.d);
    let mi = 0;
    let ai = 0;
    for (const { t: tg, d } of list) {
      _vc.copy(tg.pos).applyMatrix4(cam.matrixWorldInverse);
      const behind = _vc.z > 0;
      _v.copy(tg.pos).project(cam);
      let sx = (_v.x * 0.5 + 0.5) * W;
      let sy = (-_v.y * 0.5 + 0.5) * H;
      const onScreen = !behind && Math.abs(_v.x) < 0.98 && Math.abs(_v.y) < 0.96;
      const tracked = t.current === tg && t.lockMode;
      const locked = tracked && t.state === 'locked';
      if (onScreen) {
        if (mi >= this.markerPool.length) continue;
        const m = this.markerPool[mi++];
        const focal = H / (2 * Math.tan((cam.fov * Math.PI) / 360));
        const size = clamp((tg.radius * 2.4 * focal) / Math.max(1, -_vc.z), tracked ? 44 : 22, 170);
        const minor = !tracked && t.candidate !== tg;
        const key = `${tg.id}|${Math.round(d)}|${tracked ? t.state : ''}|${Math.round(t.progress * 20)}|${Math.round(tg.healthFraction() * 50)}|${minor}`;
        m.root.style.display = 'block';
        m.root.style.width = `${size.toFixed(0)}px`;
        m.root.style.height = `${size.toFixed(0)}px`;
        m.root.style.transform = `translate3d(${(sx - size / 2).toFixed(1)}px, ${(sy - size / 2).toFixed(1)}px, 0)`;
        if (m.cache !== key) {
          m.cache = key;
          m.root.className = `marker${tracked ? ' tracked' : ''}${locked ? ' locked' : ''}${minor ? ' minor' : ''}${tg.kind === 'boss' ? ' boss' : ''}`;
          let line1 = '';
          if (tracked) line1 = t.state === 'locked' ? 'LOCKED' : `LOCK ${Math.round(t.progress * 100)}%`;
          else if (!minor) line1 = tg.label;
          m.info.innerHTML = `${line1 ? `<div>${line1}</div>` : ''}<div>${fmtInt(d)} m</div>`;
          m.hp.style.width = `${tg.healthFraction() * 100}%`;
          m.hp.parentElement!.style.display = minor ? 'none' : '';
          const prog = tracked ? (t.state === 'locked' ? 1 : t.progress) : 0;
          m.ring.style.strokeDashoffset = String(289 * (1 - prog));
        }
        m.shown = true;
      } else if (ai < this.arrowPool.length && tg.kind !== 'turret' && d < 700) {
        // off-screen: arrow at the edge pointing toward the target
        let dx = _v.x;
        let dy = _v.y;
        if (behind) {
          dx = -dx;
          dy = -dy;
          if (Math.abs(dx) < 0.05 && Math.abs(dy) < 0.05) dy = -1;
        }
        const ang = Math.atan2(-dy, dx);
        const cx = W / 2;
        const cy = H / 2;
        const rx = W / 2 - 46;
        const ry = H / 2 - 46;
        const k = 1 / Math.max(Math.abs(Math.cos(ang)) / rx, Math.abs(Math.sin(ang)) / ry);
        sx = cx + Math.cos(ang) * k;
        sy = cy + Math.sin(ang) * k;
        const a = this.arrowPool[ai++];
        a.style.display = 'block';
        a.className = 'arrow';
        a.style.transform = `translate3d(${sx.toFixed(1)}px, ${sy.toFixed(1)}px, 0) rotate(${(ang + Math.PI / 2).toFixed(3)}rad)`;
      }
    }
    for (let i = mi; i < this.markerPool.length; i++) {
      const m = this.markerPool[i];
      if (m.shown) {
        m.shown = false;
        m.root.style.display = 'none';
        m.cache = '';
      }
    }
    // inbound enemy missiles get amber arrows too
    const player = ctx.player;
    for (const m of ctx.projectiles.missiles) {
      if (!m.alive || m.spec.team !== 'enemy' || m.target !== player) continue;
      if (ai >= this.arrowPool.length) break;
      const d = m.pos.distanceTo(pos);
      if (d > 260) continue;
      _vc.copy(m.pos).applyMatrix4(cam.matrixWorldInverse);
      const behind = _vc.z > 0;
      _v.copy(m.pos).project(cam);
      let dx = _v.x;
      let dy = _v.y;
      const onScreen = !behind && Math.abs(dx) < 0.98 && Math.abs(dy) < 0.96;
      if (onScreen) continue;
      if (behind) {
        dx = -dx;
        dy = -dy;
        if (Math.abs(dx) < 0.05 && Math.abs(dy) < 0.05) dy = -1;
      }
      const ang = Math.atan2(-dy, dx);
      const rx = W / 2 - 70;
      const ry = H / 2 - 70;
      const k = 1 / Math.max(Math.abs(Math.cos(ang)) / rx, Math.abs(Math.sin(ang)) / ry);
      const a = this.arrowPool[ai++];
      a.style.display = 'block';
      a.className = 'arrow missile';
      a.style.transform = `translate3d(${(W / 2 + Math.cos(ang) * k).toFixed(1)}px, ${(H / 2 + Math.sin(ang) * k).toFixed(1)}px, 0) rotate(${(ang + Math.PI / 2).toFixed(3)}rad)`;
    }
    for (let i = ai; i < this.arrowPool.length; i++) this.arrowPool[i].style.display = 'none';
  }

  private updateAlerts() {
    const ctx = this.ctx;
    const p = ctx.player;
    const alerts: [string, boolean][] = [];
    if (p.alive) {
      if (p.armor < 25) alerts.push(['ARMOR CRITICAL', true]);
      if (p.energy < 12 && p.flight.mode !== 'grounded') alerts.push(['LOW ENERGY', false]);
      let inbound = 0;
      for (const m of ctx.projectiles.missiles) {
        if (m.alive && m.spec.team === 'enemy' && m.target === p && m.pos.distanceTo(p.pos) < 220) inbound++;
      }
      if (inbound > 0) {
        alerts.push([`MISSILE INBOUND${inbound > 1 ? ' x' + inbound : ''}`, true]);
        if (Math.floor(this.time * 3) !== Math.floor((this.time - 0.016) * 3)) ctx.audio.warning();
      }
      if (p.outsideBounds) alerts.push(['LEAVING COMBAT ZONE - RETURN', false]);
    }
    const key = alerts.map((a) => a.join('|')).join('#');
    if (key !== this.alertKey) {
      this.alertKey = key;
      this.el.alerts.innerHTML = alerts.map(([t, red]) => `<div class="alert${red ? ' red' : ''}">${t}</div>`).join('');
    }
  }

  private updateSuit() {
    const p = this.ctx.player;
    const a = clamp(p.armor / 100, 0, 1);
    const flash = p.damageFlash > 0;
    const color = (h: number) => {
      if (flash) return '#ff5a44';
      if (h > 0.66) return '#4de3ff';
      if (h > 0.33) return '#ffb13b';
      return `hsl(${8 + (Math.sin(this.time * 9) > 0 ? 0 : 6)}, 100%, ${52 + (h < 0.15 ? 10 * Math.sin(this.time * 10) : 0)}%)`;
    };
    const parts = this.el.suit.children;
    // limbs degrade first, the core last
    const health = [a * 1.15, a * 1.05, a * 1.35 - 0.1, a * 1.35 - 0.1, a * 1.45 - 0.2, a * 1.45 - 0.2];
    for (let i = 0; i < parts.length; i++) {
      const c = color(clamp(health[i] ?? a, 0, 1));
      const el = parts[i] as SVGElement;
      if (el.getAttribute('stroke') !== c) el.setAttribute('stroke', c);
    }
    this.el.suitCore.setAttribute('fill', color(a));
  }

  // ---------------------------------------------------------------------------------- radar
  private drawRadar(dt: number) {
    const c = this.radarCtx;
    const S = this.el.radar.width;
    const cx = S / 2;
    const R = S / 2 - 8;
    const ctx = this.ctx;
    const p = ctx.player;
    this.sweep = (this.sweep + dt * 1.6) % (Math.PI * 2);
    c.clearRect(0, 0, S, S);
    // disc
    const g = c.createRadialGradient(cx, cx, R * 0.1, cx, cx, R);
    g.addColorStop(0, 'rgba(8, 40, 58, 0.55)');
    g.addColorStop(1, 'rgba(3, 16, 28, 0.78)');
    c.fillStyle = g;
    c.beginPath();
    c.arc(cx, cx, R, 0, Math.PI * 2);
    c.fill();
    c.strokeStyle = 'rgba(77,227,255,0.55)';
    c.lineWidth = 2;
    c.stroke();
    c.lineWidth = 1;
    c.strokeStyle = 'rgba(77,227,255,0.22)';
    for (const k of [0.33, 0.66]) {
      c.beginPath();
      c.arc(cx, cx, R * k, 0, Math.PI * 2);
      c.stroke();
    }
    c.beginPath();
    c.moveTo(cx - R, cx);
    c.lineTo(cx + R, cx);
    c.moveTo(cx, cx - R);
    c.lineTo(cx, cx + R);
    c.stroke();
    // sweep
    const sg = c.createConicGradient(this.sweep - Math.PI / 2, cx, cx);
    sg.addColorStop(0, 'rgba(77,227,255,0.0)');
    sg.addColorStop(0.9, 'rgba(77,227,255,0.0)');
    sg.addColorStop(1, 'rgba(77,227,255,0.28)');
    c.fillStyle = sg;
    c.beginPath();
    c.arc(cx, cx, R, 0, Math.PI * 2);
    c.fill();

    const h = p.flight.heading;
    const sinH = Math.sin(h);
    const cosH = Math.cos(h);
    // compass letters (bearing clockwise from north = -Z)
    const bearing = -h;
    c.font = 'bold 15px Bahnschrift, Segoe UI, sans-serif';
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    const letters: [string, number][] = [['N', 0], ['E', 90], ['S', 180], ['W', 270]];
    for (const [l, deg] of letters) {
      const a = (deg * Math.PI) / 180 - bearing;
      c.fillStyle = l === 'N' ? '#ff8a6a' : 'rgba(166,243,255,0.9)';
      c.fillText(l, cx + Math.sin(a) * (R - 12), cx - Math.cos(a) * (R - 12));
    }
    let hdg = ((-h * 180) / Math.PI) % 360;
    if (hdg < 0) hdg += 360;
    this.setText(this.el.radarHdg, String(Math.round(hdg)).padStart(3, '0'));

    const RANGE = 430;
    const plot = (wx: number, wz: number, dy: number, draw: (x: number, y: number, a: number, edge: boolean) => void) => {
      const dx = wx - p.pos.x;
      const dz = wz - p.pos.z;
      const f = dx * -sinH + dz * -cosH;
      const r = dx * cosH + dz * -sinH;
      let x = (r / RANGE) * R;
      let y = (-f / RANGE) * R;
      const len = Math.hypot(x, y);
      let edge = false;
      if (len > R - 6) {
        x *= (R - 6) / len;
        y *= (R - 6) / len;
        edge = true;
      }
      const alt = clamp(1 - Math.abs(dy) / 160, 0.35, 1);
      draw(cx + x, cx + y, alt, edge);
    };
    // supply canisters: small diamonds in the colour of their kind
    const pickupColor = { armor: '#7dff9a', energy: '#4de3ff', missiles: '#ff7a3a', mini: '#ffb13b' } as const;
    for (const k of ctx.pickups.items) {
      plot(k.pos.x, k.pos.z, k.pos.y - p.pos.y, (x, y, a) => {
        c.globalAlpha = a;
        c.fillStyle = pickupColor[k.kind];
        c.beginPath();
        c.moveTo(x, y - 4);
        c.lineTo(x + 3.5, y);
        c.lineTo(x, y + 4);
        c.lineTo(x - 3.5, y);
        c.closePath();
        c.fill();
        c.globalAlpha = 1;
      });
    }
    // enemies
    for (const t of ctx.enemies.targets) {
      plot(t.pos.x, t.pos.z, t.pos.y - p.pos.y, (x, y, a, edge) => {
        c.globalAlpha = edge ? a * 0.55 : a;
        c.fillStyle = '#ff4a3a';
        c.strokeStyle = '#ff4a3a';
        if (t.kind === 'drone') {
          c.beginPath();
          c.arc(x, y, 4, 0, Math.PI * 2);
          c.fill();
        } else if (t.kind === 'turret') {
          c.fillRect(x - 4, y - 4, 8, 8);
        } else {
          c.beginPath();
          for (let i = 0; i < 6; i++) c.lineTo(x + Math.cos((i * Math.PI) / 3) * 10, y + Math.sin((i * Math.PI) / 3) * 10);
          c.closePath();
          c.fill();
        }
        if (ctx.player.weapons.targeting.current === t) {
          c.strokeStyle = '#ffb13b';
          c.lineWidth = 2;
          c.beginPath();
          c.arc(x, y, 9, 0, Math.PI * 2);
          c.stroke();
          c.lineWidth = 1;
        }
        c.globalAlpha = 1;
      });
    }
    // inbound missiles
    for (const m of ctx.projectiles.missiles) {
      if (!m.alive || m.spec.team !== 'enemy') continue;
      plot(m.pos.x, m.pos.z, m.pos.y - p.pos.y, (x, y) => {
        c.fillStyle = '#ffb13b';
        c.fillRect(x - 2, y - 2, 4, 4);
      });
    }
    // player arrow (always up)
    c.fillStyle = '#4de3ff';
    c.strokeStyle = '#a6f3ff';
    c.beginPath();
    c.moveTo(cx, cx - 11);
    c.lineTo(cx + 8, cx + 9);
    c.lineTo(cx, cx + 4);
    c.lineTo(cx - 8, cx + 9);
    c.closePath();
    c.fill();
    c.stroke();
    // combat zone edge indicator (dashed amber rectangle, clipped to the radar disc)
    const half = WORLD.half;
    c.save();
    c.beginPath();
    c.arc(cx, cx, R - 1, 0, Math.PI * 2);
    c.clip();
    c.strokeStyle = 'rgba(255,177,59,0.4)';
    c.setLineDash([4, 6]);
    c.beginPath();
    const corners: [number, number][] = [[-half, -half], [half, -half], [half, half], [-half, half]];
    corners.forEach(([wx, wz], i) => {
      const dx = wx - p.pos.x;
      const dz = wz - p.pos.z;
      const f = dx * -sinH + dz * -cosH;
      const r = dx * cosH + dz * -sinH;
      const x = cx + (r / RANGE) * R;
      const y = cx + (-f / RANGE) * R;
      if (i === 0) c.moveTo(x, y);
      else c.lineTo(x, y);
    });
    c.closePath();
    c.stroke();
    c.restore();
    c.setLineDash([]);
  }
}
