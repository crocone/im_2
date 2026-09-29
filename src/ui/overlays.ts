import type { Game } from '../game/game';
import type { Quality } from '../fx/postfx';
import type { Difficulty } from '../game/types';

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

export type OverlayName = 'loading' | 'menu' | 'pause' | 'help' | 'gameover' | 'victory';
const NAMES: OverlayName[] = ['loading', 'menu', 'pause', 'help', 'gameover', 'victory'];

/** Menu / pause / help / game-over / victory overlays and the settings widgets they contain. */
export class Overlays {
  private current: OverlayName | null = 'menu';
  private helpReturn: OverlayName | null = null;

  constructor(private game: Game) {
    const s = game.settings;
    const bindSettings = (q: string, sens: string, vol: string, inv: string, diff: string) => {
      const quality = $<HTMLSelectElement>(q);
      const difficulty = $<HTMLSelectElement>(diff);
      difficulty.value = s.difficulty;
      difficulty.addEventListener('change', () => {
        s.difficulty = difficulty.value as Difficulty;
        game.saveSettings();
        this.syncSettings();
      });
      const sensitivity = $<HTMLInputElement>(sens);
      const volume = $<HTMLInputElement>(vol);
      const invert = $<HTMLInputElement>(inv);
      quality.value = s.quality;
      sensitivity.value = String(s.sensitivity);
      volume.value = String(s.volume);
      invert.checked = s.invertY;
      quality.addEventListener('change', () => {
        game.setQuality(quality.value as Quality);
        this.syncSettings();
      });
      sensitivity.addEventListener('input', () => {
        s.sensitivity = parseFloat(sensitivity.value);
        game.saveSettings();
        this.syncSettings();
      });
      volume.addEventListener('input', () => {
        s.volume = parseFloat(volume.value);
        game.audio.setVolume(s.volume);
        game.saveSettings();
        this.syncSettings();
      });
      invert.addEventListener('change', () => {
        s.invertY = invert.checked;
        game.saveSettings();
        this.syncSettings();
      });
    };
    bindSettings('set-quality', 'set-sens', 'set-vol', 'set-invert', 'set-diff');
    bindSettings('set-quality2', 'set-sens2', 'set-vol2', 'set-invert2', 'set-diff2');

    $('btn-start').addEventListener('click', () => game.start());
    $('btn-resume').addEventListener('click', () => game.resume());
    $('btn-restart').addEventListener('click', () => game.restart());
    $('btn-retry').addEventListener('click', () => game.restart());
    $('btn-retry-wave').addEventListener('click', () => game.retryWave());
    $('btn-again').addEventListener('click', () => game.restart());
    $('btn-endless').addEventListener('click', () => game.continueEndless());
    $('btn-help').addEventListener('click', () => this.openHelp('pause'));
    $('btn-help-close').addEventListener('click', () => this.closeHelp());
    game.input.onHelpKey = () => {
      if (this.current === 'help') this.closeHelp();
      else if (game.state === 'playing') {
        game.pause();
        this.openHelp('pause');
      } else if (this.current === 'menu' || this.current === 'pause') this.openHelp(this.current);
    };
    // Enter starts / resumes from the menus
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Enter') {
        if (this.current === 'menu') game.start();
        else if (this.current === 'pause') game.resume();
        else if (this.current === 'gameover') game.retryWave();
      }
    });
    this.show('menu');
  }

  private syncSettings() {
    const s = this.game.settings;
    for (const [q, sens, vol, inv, diff] of [['set-quality', 'set-sens', 'set-vol', 'set-invert', 'set-diff'], ['set-quality2', 'set-sens2', 'set-vol2', 'set-invert2', 'set-diff2']]) {
      $<HTMLSelectElement>(q).value = s.quality;
      $<HTMLSelectElement>(diff).value = s.difficulty;
      $<HTMLInputElement>(sens).value = String(s.sensitivity);
      $<HTMLInputElement>(vol).value = String(s.volume);
      $<HTMLInputElement>(inv).checked = s.invertY;
    }
  }

  show(name: OverlayName | null) {
    this.current = name;
    for (const n of NAMES) $(n === 'gameover' ? 'gameover' : n).classList.toggle('hidden', n !== name);
    if (name) this.syncSettings();
  }

  private openHelp(back: OverlayName | null) {
    this.helpReturn = back;
    this.show('help');
  }

  private closeHelp() {
    this.show(this.helpReturn ?? 'menu');
  }

  showGameOver(score: number, wave: number, kills: number) {
    $('go-score').textContent = score.toLocaleString('en-US');
    $('go-wave').textContent = String(Math.max(1, wave));
    $('go-kills').textContent = String(kills);
    $('go-retry-wave').textContent = String(Math.max(1, wave));
    this.show('gameover');
  }

  showVictory(score: number) {
    $('vic-score').textContent = score.toLocaleString('en-US');
    this.show('victory');
  }

  setLoading(fraction: number, text: string) {
    $('load-fill').style.width = `${Math.round(fraction * 100)}%`;
    $('load-text').textContent = text;
  }
}
