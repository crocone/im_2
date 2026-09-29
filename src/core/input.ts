/** Keyboard + mouse input with pointer lock. Edge-triggered queries are cleared by `endFrame()`. */
export class Input {
  private down = new Set<string>();
  private pressed = new Set<string>();
  private buttonsDown = new Set<number>();
  private buttonsPressed = new Set<number>();
  private buttonsReleased = new Set<number>();
  mouseDX = 0;
  mouseDY = 0;
  wheel = 0;
  /** real pointer-lock state */
  locked = false;
  /** true once the browser has granted the pointer lock at least once in this session */
  everLocked = false;
  /** mouse look without pointer lock (embedded browsers that refuse the lock) */
  fallback = false;
  enabled = false;
  onLockChange: ((locked: boolean) => void) | null = null;
  onPauseKey: (() => void) | null = null;
  onHelpKey: (() => void) | null = null;

  constructor(private canvas: HTMLElement) {
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Tab' || e.code === 'Space' || e.code.startsWith('Arrow') || e.code === 'F1') e.preventDefault();
      if (e.repeat) return;
      if (e.code === 'F1' || e.code === 'KeyH') this.onHelpKey?.();
      if (!this.enabled) return;
      this.down.add(e.code);
      this.pressed.add(e.code);
    });
    window.addEventListener('keyup', (e) => {
      this.down.delete(e.code);
    });
    window.addEventListener('blur', () => {
      this.down.clear();
      this.buttonsDown.clear();
    });
    window.addEventListener('mousemove', (e) => {
      if (!this.enabled || !(this.locked || this.fallback)) return;
      this.mouseDX += e.movementX;
      this.mouseDY += e.movementY;
    });
    window.addEventListener('mousedown', (e) => {
      // a click is a user gesture: use it to (re-)capture the mouse if the lock was lost or refused (e.g. Esc cool-down)
      if (this.enabled && !this.locked && (e.target as HTMLElement | null)?.tagName === 'CANVAS') this.requestLock();
      if (!this.enabled || !(this.locked || this.fallback)) return;
      this.buttonsDown.add(e.button);
      this.buttonsPressed.add(e.button);
    });
    window.addEventListener('mouseup', (e) => {
      if (this.buttonsDown.delete(e.button)) this.buttonsReleased.add(e.button);
    });
    window.addEventListener('wheel', (e) => {
      if (this.enabled && (this.locked || this.fallback)) this.wheel += Math.sign(e.deltaY);
    }, { passive: true });
    window.addEventListener('contextmenu', (e) => e.preventDefault());
    document.addEventListener('pointerlockchange', () => {
      this.locked = document.pointerLockElement === this.canvas;
      if (this.locked) this.everLocked = true;
      if (!this.locked) {
        this.down.clear();
        this.buttonsDown.clear();
      }
      this.onLockChange?.(this.locked);
    });
    document.addEventListener('pointerlockerror', () => {
      // the lock was refused: nothing changed, so this is not a "lock lost" event
      this.locked = false;
    });
  }

  requestLock() {
    try {
      const p = (this.canvas as HTMLCanvasElement).requestPointerLock() as unknown;
      if (p && typeof (p as Promise<void>).catch === 'function') (p as Promise<void>).catch(() => undefined);
    } catch {
      /* ignored: some embedded browsers refuse pointer lock */
    }
  }

  exitLock() {
    if (document.pointerLockElement) document.exitPointerLock();
  }

  isDown(code: string) {
    return this.down.has(code);
  }
  wasPressed(code: string) {
    return this.pressed.has(code);
  }
  mouseDown(button: number) {
    return this.buttonsDown.has(button);
  }
  mousePressed(button: number) {
    return this.buttonsPressed.has(button);
  }
  mouseReleased(button: number) {
    return this.buttonsReleased.has(button);
  }
  /** -1..1 axis from two keys (either of several codes per side). */
  axis(neg: string[], pos: string[]) {
    let v = 0;
    if (neg.some((k) => this.down.has(k))) v -= 1;
    if (pos.some((k) => this.down.has(k))) v += 1;
    return v;
  }

  /** Returns and resets accumulated mouse movement (called once per fixed simulation step). */
  takeMouse(out: { x: number; y: number }) {
    out.x = this.mouseDX;
    out.y = this.mouseDY;
    this.mouseDX = 0;
    this.mouseDY = 0;
  }

  endFrame() {
    this.pressed.clear();
    this.buttonsPressed.clear();
    this.buttonsReleased.clear();
    this.wheel = 0;
  }

  reset() {
    this.down.clear();
    this.pressed.clear();
    this.buttonsDown.clear();
    this.buttonsPressed.clear();
    this.buttonsReleased.clear();
    this.mouseDX = this.mouseDY = 0;
  }
}
