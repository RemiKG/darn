/**
 * EventSource wrapper with auto-reconnect (backoff 1s → 10s).
 *
 * - `getGlobalEvents()` returns the ONE app-wide connection to /api/events.
 * - `incidentEvents(id)` builds a fresh per-incident channel for
 *   /api/incidents/{id}/events — callers own it and must `close()` it.
 *
 * SSE format per contract: `event: <name>\ndata: <json>\n\n` with a heartbeat
 * comment every 15s (comments keep the connection warm; no handler fires).
 */

export type SseHandler = (data: unknown) => void;
export type Unsubscribe = () => void;

const BACKOFF_MIN_MS = 1_000;
const BACKOFF_MAX_MS = 10_000;

export class SseChannel {
  private readonly url: string;
  private es: EventSource | null = null;
  private handlers = new Map<string, Set<SseHandler>>();
  /** event names already attached to the CURRENT EventSource instance */
  private attached = new Set<string>();
  private backoffMs = BACKOFF_MIN_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(url: string) {
    this.url = url;
  }

  /** Register a handler for a named SSE event. Opens the connection lazily. */
  subscribe(eventName: string, handler: SseHandler): Unsubscribe {
    if (this.closed) {
      throw new Error(`SseChannel(${this.url}) is closed`);
    }
    let set = this.handlers.get(eventName);
    if (!set) {
      set = new Set();
      this.handlers.set(eventName, set);
    }
    set.add(handler);
    this.ensureOpen();
    this.attach(eventName);
    return () => {
      const s = this.handlers.get(eventName);
      if (s) {
        s.delete(handler);
        if (s.size === 0) {
          this.handlers.delete(eventName);
        }
      }
    };
  }

  /** Permanently close the channel (per-incident channels on unmount). */
  close(): void {
    this.closed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.es?.close();
    this.es = null;
    this.handlers.clear();
    this.attached.clear();
  }

  // ---------------------------------------------------------------- internal

  private ensureOpen(): void {
    if (this.es || this.closed) {
      return;
    }
    const es = new EventSource(this.url, { withCredentials: true });
    this.es = es;
    this.attached.clear();

    es.onopen = () => {
      this.backoffMs = BACKOFF_MIN_MS;
    };
    es.onerror = () => {
      // EventSource has built-in retry, but we manage backoff ourselves so a
      // dead server doesn't hot-loop the tab.
      es.close();
      if (this.es === es) {
        this.es = null;
        this.attached.clear();
        this.scheduleReconnect();
      }
    };
    for (const name of this.handlers.keys()) {
      this.attach(name);
    }
  }

  private attach(eventName: string): void {
    const es = this.es;
    if (!es || this.attached.has(eventName)) {
      return;
    }
    this.attached.add(eventName);
    es.addEventListener(eventName, (ev: MessageEvent<string>) => {
      let data: unknown = null;
      try {
        data = JSON.parse(ev.data);
      } catch {
        data = ev.data;
      }
      const set = this.handlers.get(eventName);
      if (set) {
        for (const handler of [...set]) {
          handler(data);
        }
      }
    });
  }

  private scheduleReconnect(): void {
    if (this.closed || this.reconnectTimer !== null) {
      return;
    }
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, BACKOFF_MAX_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.ensureOpen();
    }, delay);
  }
}

// ---------------------------------------------------------------- factories

let globalChannel: SseChannel | null = null;

/** The single app-wide connection to GET /api/events (events: state, health, incident, presence, cooldown). */
export function getGlobalEvents(): SseChannel {
  if (!globalChannel) {
    globalChannel = new SseChannel("/api/events");
  }
  return globalChannel;
}

/** A fresh per-incident channel for GET /api/incidents/{id}/events (events: incident, presence, medic). Caller must close(). */
export function incidentEvents(incidentId: string): SseChannel {
  return new SseChannel(`/api/incidents/${incidentId}/events`);
}
