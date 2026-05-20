/**
 * App-wide live state: React context + hooks.
 *
 * - <AppStateProvider> fetches GET /api/state once and keeps it live via the
 *   global SSE bus (events: state, health, incident, presence, cooldown).
 * - useAppState() — the snapshot + the live incident (for the live strip).
 * - useIncident(id) — fetch + per-incident SSE + a presence heartbeat POST
 *   every 20s while mounted (paused while document.hidden).
 * - useNow/useElapsed/useCountdown — session time helpers for ticking
 *   mono numerals (content swap, never fades).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  type AppStateSnapshot,
  type CooldownEvent,
  type HealthCard,
  type Incident,
  type MedicTrace,
  type PresenceEvent,
  type PresenceInfo,
} from "./api";
import { getGlobalEvents, incidentEvents } from "./sse";

// ------------------------------------------------------------------ context

export interface AppStore {
  /** Snapshot of GET /api/state, kept live over SSE. Null until first load. */
  state: AppStateSnapshot | null;
  /** The currently-live incident (drives the live strip), null when idle. */
  liveIncident: Incident | null;
  /** Non-null when the initial state fetch failed (server unreachable). */
  error: string | null;
  /** Re-fetch the snapshot on demand. */
  reload: () => void;
}

const AppStateContext = createContext<AppStore | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppStateSnapshot | null>(null);
  const [liveIncident, setLiveIncident] = useState<Incident | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api
      .getState()
      .then((s) => {
        setState(s);
        setError(null);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
      });
  }, []);

  useEffect(() => {
    reload();
    const bus = getGlobalEvents();
    const subs = [
      bus.subscribe("state", (data) => {
        setState(data as AppStateSnapshot);
        setError(null);
      }),
      bus.subscribe("health", (data) => {
        setState((prev) => (prev ? { ...prev, health: data as HealthCard } : prev));
      }),
      bus.subscribe("cooldown", (data) => {
        const ev = data as CooldownEvent;
        setState((prev) => (prev ? { ...prev, cooldown_until: ev.until } : prev));
      }),
      bus.subscribe("incident", (data) => {
        const inc = data as Incident;
        setLiveIncident((prev) => {
          if (inc.status === "live") {
            return inc;
          }
          return prev && prev.id === inc.id ? null : prev;
        });
      }),
      bus.subscribe("presence", (data) => {
        const ev = data as PresenceEvent;
        setLiveIncident((prev) =>
          prev && ev.incident_id === prev.id ? { ...prev, watching: ev.watching } : prev
        );
      }),
    ];
    return () => {
      for (const unsub of subs) {
        unsub();
      }
      // the global channel itself stays open for the app's lifetime
    };
  }, [reload]);

  // first load: if an incident is already live, fetch it for the live strip
  const liveId = state?.live_incident_id ?? null;
  useEffect(() => {
    if (!liveId) {
      setLiveIncident((prev) => (prev && prev.status === "live" ? null : prev));
      return;
    }
    let stale = false;
    api
      .getIncident(liveId)
      .then((inc) => {
        if (!stale && inc.status === "live") {
          setLiveIncident(inc);
        }
      })
      .catch(() => {
        /* the strip simply doesn't render without it */
      });
    return () => {
      stale = true;
    };
  }, [liveId]);

  return (
    <AppStateContext.Provider value={{ state, liveIncident, error, reload }}>
      {children}
    </AppStateContext.Provider>
  );
}

/** Snapshot of /api/state kept live via SSE. Must be used under <AppStateProvider>. */
export function useAppState(): AppStore {
  const ctx = useContext(AppStateContext);
  if (!ctx) {
    throw new Error("useAppState must be used within <AppStateProvider>");
  }
  return ctx;
}

// ------------------------------------------------------------------ incident

export interface IncidentStore {
  incident: Incident | null;
  /** Latest presence info (from the heartbeat POST and SSE presence events). */
  presence: PresenceInfo | null;
  /** Medic trace — live-updated by the per-incident SSE "medic" event. */
  medic: MedicTrace | null;
  /** Non-null when the incident could not be loaded (e.g. 404). */
  error: string | null;
  /** Re-fetch the incident on demand. */
  reload: () => void;
}

const HEARTBEAT_MS = 20_000;

/**
 * Live view of one incident: initial fetch + per-incident SSE channel +
 * presence heartbeat every 20s while mounted (paused when document.hidden;
 * an immediate beat fires when the tab becomes visible again).
 */
export function useIncident(id: string | undefined): IncidentStore {
  const [incident, setIncident] = useState<Incident | null>(null);
  const [presence, setPresence] = useState<PresenceInfo | null>(null);
  const [medic, setMedic] = useState<MedicTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const idRef = useRef(id);
  idRef.current = id;

  const reload = useCallback(() => {
    const current = idRef.current;
    if (!current) {
      return;
    }
    api
      .getIncident(current)
      .then((inc) => {
        setIncident(inc);
        if (inc.medic) {
          setMedic(inc.medic);
        }
        setError(null);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
      });
  }, []);

  useEffect(() => {
    setIncident(null);
    setPresence(null);
    setMedic(null);
    setError(null);
    if (!id) {
      return;
    }

    reload();

    const channel = incidentEvents(id);
    const subs = [
      channel.subscribe("incident", (data) => {
        const inc = data as Incident;
        setIncident(inc);
        if (inc.medic) {
          setMedic(inc.medic);
        }
      }),
      channel.subscribe("presence", (data) => {
        const ev = data as PresenceEvent;
        setPresence((prev) => ({
          watching: ev.watching,
          holder: ev.holder ?? prev?.holder ?? false,
          holder_label: ev.holder_label ?? prev?.holder_label ?? "",
          can_pickup: ev.can_pickup ?? prev?.can_pickup ?? false,
        }));
        setIncident((prev) => (prev ? { ...prev, watching: ev.watching } : prev));
      }),
      channel.subscribe("medic", (data) => {
        setMedic(data as MedicTrace);
      }),
    ];

    const beat = () => {
      if (document.hidden) {
        return;
      }
      api
        .postPresence(id)
        .then(setPresence)
        .catch(() => {
          /* presence is best-effort */
        });
    };
    beat();
    const interval = setInterval(beat, HEARTBEAT_MS);
    const onVisibility = () => {
      if (!document.hidden) {
        beat();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      for (const unsub of subs) {
        unsub();
      }
      channel.close();
    };
  }, [id, reload]);

  return { incident, presence, medic, error, reload };
}

// ------------------------------------------------------------------ session/time helpers

/** Epoch seconds, ticking every `periodMs` (default 1s). Powers mm:ss tickers. */
export function useNow(periodMs = 1_000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), periodMs);
    return () => clearInterval(t);
  }, [periodMs]);
  return now;
}

/** Whole seconds elapsed since `sinceEpochS` (null in → null out). Ticks every second. */
export function useElapsed(sinceEpochS: number | null | undefined): number | null {
  const now = useNow();
  if (sinceEpochS === null || sinceEpochS === undefined) {
    return null;
  }
  return Math.max(0, Math.floor(now - sinceEpochS));
}

/** Whole seconds remaining until `untilEpochS` (0 once passed; null in → null out). */
export function useCountdown(untilEpochS: number | null | undefined): number | null {
  const now = useNow();
  if (untilEpochS === null || untilEpochS === undefined) {
    return null;
  }
  return Math.max(0, Math.ceil(untilEpochS - now));
}
