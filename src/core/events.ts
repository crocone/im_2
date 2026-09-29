/** Minimal typed event bus used to decouple gameplay systems (HUD, audio, score, waves). */
type Handler<T> = (payload: T) => void;

export class Emitter<Events extends object> {
  private handlers = new Map<keyof Events, Set<Handler<never>>>();

  on<K extends keyof Events>(type: K, fn: Handler<Events[K]>): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(fn as Handler<never>);
    return () => set!.delete(fn as Handler<never>);
  }

  emit<K extends keyof Events>(type: K, payload: Events[K]) {
    const set = this.handlers.get(type);
    if (!set) return;
    for (const fn of [...set]) (fn as Handler<Events[K]>)(payload);
  }

  clear() {
    this.handlers.clear();
  }
}
