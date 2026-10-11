import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type * as T from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { loadActive, saveActive } from "../lib/twinRegistry";

export interface ActionResult { kind: "forecast" | "observe" | "reconcile" | "create" | "whatif"; ok: boolean; message: string; at: number }
type Busy = Partial<Record<"load" | "create" | "forecast" | "observe" | "reconcile" | "whatif" | "twins", boolean>>;

export interface Workspace {
  health: T.Health | null; healthError: string | null;
  /** The signed-in user's own twins (GET /twins). Never anyone else's. */
  twins: T.TwinSummary[]; twinsLoaded: boolean; twinsError: ApiError | null; reloadTwins: () => Promise<void>;
  activeId: string | null;
  twin: T.Twin | null; forecasts: T.Forecast[]; history: T.History | null; recon: T.ReconciliationView | null;
  observations: Record<string, T.Observation>; lastReconciliation: T.Reconciliation | null;
  selectedForecastId: string | null; selectedVersion: number | null;
  busy: Busy; loadError: ApiError | null; lastAction: ActionResult | null; announce: string;
  selectForecast: (id: string | null) => void; selectVersion: (v: number | null) => void;
  selectTwin: (id: string) => void; refresh: () => Promise<void>;
  createTwin: (b: T.CreateTwinBody) => Promise<boolean>;
  requestForecast: (b: T.ForecastBody) => Promise<T.Forecast | null>;
  submitObservation: (b: T.ObserveBody) => Promise<T.Observation | null>;
  applyReconcile: (forecastId: string) => Promise<T.Reconciliation | null>;
}

const Ctx = createContext<Workspace | null>(null);
export const useWorkspace = (): Workspace => { const w = useContext(Ctx); if (!w) throw new Error("useWorkspace outside provider"); return w; };

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<T.Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const { user } = useAuth();
  const userId = user?.id ?? "";
  const [twins, setTwins] = useState<T.TwinSummary[]>([]);
  const [twinsLoaded, setTwinsLoaded] = useState(false);
  const [twinsError, setTwinsError] = useState<ApiError | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [twin, setTwin] = useState<T.Twin | null>(null);
  const [forecasts, setForecasts] = useState<T.Forecast[]>([]);
  const [history, setHistory] = useState<T.History | null>(null);
  const [recon, setRecon] = useState<T.ReconciliationView | null>(null);
  const [observations, setObservations] = useState<Record<string, T.Observation>>({});
  const [lastReconciliation, setLastReconciliation] = useState<T.Reconciliation | null>(null);
  const [selectedForecastId, setSelectedForecastId] = useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [busy, setBusy] = useState<Busy>({});
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [lastAction, setLastAction] = useState<ActionResult | null>(null);
  const [announce, setAnnounce] = useState("");
  const loadSeq = useRef(0);

  const setFlag = (k: keyof Busy, v: boolean) => setBusy((b) => ({ ...b, [k]: v }));
  const note = useCallback((kind: ActionResult["kind"], ok: boolean, message: string) => { setLastAction({ kind, ok, message, at: Date.now() }); setAnnounce(message); }, []);

  useEffect(() => {
    const ac = new AbortController();
    api.health(ac.signal).then((h) => { setHealth(h); setHealthError(null); }).catch((e: Error) => { if (e.name !== "AbortError") setHealthError(e.message); });
    return () => ac.abort();
  }, []);

  const loadTwin = useCallback(async (id: string) => {
    const seq = ++loadSeq.current;
    setFlag("load", true); setLoadError(null);
    try {
      const [tw, fl, hi, rc] = await Promise.all([api.getTwin(id), api.forecasts(id), api.history(id), api.reconciliations(id)]);
      if (seq !== loadSeq.current) return;
      setTwin(tw); setForecasts(fl.forecasts); setHistory(hi); setRecon(rc);
      setSelectedForecastId((cur) => (cur && fl.forecasts.some((f) => f.forecast_id === cur) ? cur : fl.forecasts.length ? fl.forecasts[fl.forecasts.length - 1].forecast_id : null));
    } catch (e) {
      if (seq !== loadSeq.current) return;
      const err = e instanceof ApiError ? e : new ApiError("server", (e as Error).message);
      setLoadError(err); setTwin(null); setForecasts([]); setHistory(null); setRecon(null);
      if (err.kind === "not_found") { saveActive(userId, null); setActiveId(null); }      // a remembered twin that is no longer yours / no longer exists
    } finally { if (seq === loadSeq.current) setFlag("load", false); }
  }, [userId]);

  useEffect(() => {
    if (userId) saveActive(userId, activeId);
    setSelectedVersion(null); setLastReconciliation(null); setObservations({});
    if (activeId) void loadTwin(activeId); else { setTwin(null); setForecasts([]); setHistory(null); setRecon(null); setSelectedForecastId(null); }
  }, [activeId, loadTwin, userId]);

  const reloadTwins = useCallback(async (): Promise<void> => {
    setFlag("twins", true);
    try {
      const { twins: list } = await api.listTwins();
      setTwins(list); setTwinsError(null); setTwinsLoaded(true);
      // keep the open twin if it is still in the list, else the remembered one, else the newest
      setActiveId((cur) => (cur && list.some((t) => t.twin_id === cur) ? cur : (() => { const m = loadActive(userId); return m && list.some((t) => t.twin_id === m) ? m : list[0]?.twin_id ?? null; })()));
    } catch (e) {
      setTwinsError(e instanceof ApiError ? e : new ApiError("server", (e as Error).message)); setTwinsLoaded(true);
    } finally { setFlag("twins", false); }
  }, [userId]);
  useEffect(() => { if (userId) void reloadTwins(); }, [userId, reloadTwins]);

  const refresh = useCallback(async () => { if (activeId) await loadTwin(activeId); }, [activeId, loadTwin]);
  const fail = (kind: ActionResult["kind"], e: unknown, fallback: string) => note(kind, false, e instanceof ApiError ? e.message : fallback);

  const createTwin = useCallback(async (b: T.CreateTwinBody) => {
    setFlag("create", true);
    try { const tw = await api.createTwin(b); await reloadTwins(); setActiveId(tw.twin_id); note("create", true, `Twin “${tw.label}” created at version ${tw.state.historical_response_state.version_number}.`); return true; }
    catch (e) { fail("create", e, "Could not create the twin."); return false; } finally { setFlag("create", false); }
  }, [note, reloadTwins]);

  const requestForecast = useCallback(async (b: T.ForecastBody) => {
    if (!activeId) return null;
    setFlag("forecast", true);
    try {
      const f = await api.forecast(activeId, b);
      note("forecast", true, f.created === false ? "This meal was already forecast; the stored forecast is shown (nothing new was computed)." : `Forecast stored from twin version ${f.twin_version_at_forecast}.`);
      await loadTwin(activeId); setSelectedForecastId(f.forecast_id); return f;
    } catch (e) { fail("forecast", e, "The forecast failed."); return null; } finally { setFlag("forecast", false); }
  }, [activeId, loadTwin, note]);

  const submitObservation = useCallback(async (b: T.ObserveBody) => {
    if (!activeId) return null;
    setFlag("observe", true);
    try {
      const o = await api.observe(activeId, b);
      setObservations((m) => ({ ...m, [o.forecast_id]: o }));
      note("observe", true, o.created === false ? "This observation was already recorded." : o.excluded_reason ? "Exclusion recorded. Applying it will leave the twin unchanged." : "Observation recorded. The twin has not been updated yet.");
      await loadTwin(activeId); return o;
    } catch (e) { fail("observe", e, "The observation was not recorded."); return null; } finally { setFlag("observe", false); }
  }, [activeId, loadTwin, note]);

  const applyReconcile = useCallback(async (forecastId: string) => {
    if (!activeId) return null;
    setFlag("reconcile", true);
    try {
      const r = await api.reconcile(activeId, forecastId);
      setLastReconciliation(r);
      note("reconcile", true, r.outcome === "excluded" ? "Excluded: the twin was not changed." : r.created === false ? `Already applied: twin is at version ${r.twin_version_after}.` : `Twin updated: version ${r.twin_version_before} → ${r.twin_version_after}.`);
      await loadTwin(activeId); return r;
    } catch (e) { fail("reconcile", e, "The twin was not updated."); return null; } finally { setFlag("reconcile", false); }
  }, [activeId, loadTwin, note]);

  const value = useMemo<Workspace>(() => ({
    health, healthError, twins, twinsLoaded, twinsError, reloadTwins, activeId, twin, forecasts, history, recon, observations, lastReconciliation, selectedForecastId, selectedVersion, busy, loadError, lastAction, announce,
    selectForecast: setSelectedForecastId, selectVersion: setSelectedVersion, selectTwin: setActiveId,
    refresh, createTwin, requestForecast, submitObservation, applyReconcile,
  }), [health, healthError, twins, twinsLoaded, twinsError, reloadTwins, activeId, twin, forecasts, history, recon, observations, lastReconciliation, selectedForecastId, selectedVersion, busy, loadError, lastAction, announce,
    refresh, createTwin, requestForecast, submitObservation, applyReconcile]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Observed window maximum (mg/dL) for a forecast, from real data only: the observation submitted in this session, or a reconciled outcome stored by the backend. */
export function observedPeakFor(ws: Pick<Workspace, "observations" | "recon" | "forecasts">, forecastId: string | null): { peak: number | null; excluded: boolean; source: "session" | "backend" | null } {
  if (!forecastId) return { peak: null, excluded: false, source: null };
  const o = ws.observations[forecastId];
  if (o?.excluded_reason) return { peak: null, excluded: true, source: "session" };
  if (o?.peak_glucose_mg_dl != null) return { peak: o.peak_glucose_mg_dl, excluded: false, source: "session" };
  const f = ws.forecasts.find((x) => x.forecast_id === forecastId);
  const r = ws.recon?.reconciled.find((x) => x.forecast_id === forecastId);
  if (f && r) return { peak: f.inputs.baseline_glucose + r.observed.peak_rise_mg_dl, excluded: false, source: "backend" };
  return { peak: null, excluded: f?.status === "excluded", source: null };
}
