import './style.css';
import { Game } from './game/game';

const $ = (id: string) => document.getElementById(id)!;

async function boot() {
  const canvas = $('game') as HTMLCanvasElement;
  const loadingEl = $('loading');
  const menuEl = $('menu');
  const fill = $('load-fill');
  const text = $('load-text');
  const err = $('load-error');
  try {
    const game = new Game(canvas);
    await game.init((fraction, label) => {
      fill.style.width = `${Math.round(fraction * 100)}%`;
      text.textContent = label;
    });
    loadingEl.classList.add('hidden');
    menuEl.classList.remove('hidden');
  } catch (e) {
    console.error(e);
    err.classList.remove('hidden');
    err.textContent = e instanceof Error ? `${e.message}\n${e.stack ?? ''}` : String(e);
    text.textContent = 'STARTUP FAILED';
  }
}

void boot();
