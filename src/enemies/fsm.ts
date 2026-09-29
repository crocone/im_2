/** Tiny finite state machine used by every enemy AI (drone, turret, boss). */
export interface State<T> {
  readonly name: string;
  enter?(owner: T, previous: string | null): void;
  update(owner: T, dt: number, timeInState: number): void;
  exit?(owner: T, next: string): void;
}

export class StateMachine<T> {
  private states = new Map<string, State<T>>();
  private current: State<T> | null = null;
  private t = 0;
  private pending: string | null = null;

  constructor(private owner: T) {}

  add(state: State<T>) {
    this.states.set(state.name, state);
    return this;
  }

  get name() {
    return this.current?.name ?? '';
  }

  get timeInState() {
    return this.t;
  }

  is(name: string) {
    return this.current?.name === name;
  }

  /** request a transition (applied at the start of the next update so states can call this freely) */
  go(name: string) {
    if (!this.states.has(name)) throw new Error(`unknown state ${name}`);
    this.pending = name;
  }

  /** immediate transition */
  set(name: string) {
    const next = this.states.get(name);
    if (!next) throw new Error(`unknown state ${name}`);
    const prev = this.current?.name ?? null;
    this.current?.exit?.(this.owner, name);
    this.current = next;
    this.t = 0;
    this.pending = null;
    next.enter?.(this.owner, prev);
  }

  update(dt: number) {
    if (this.pending && this.pending !== this.current?.name) this.set(this.pending);
    else this.pending = null;
    if (!this.current) return;
    this.t += dt;
    this.current.update(this.owner, dt, this.t);
  }
}
