import { API_BASE_URL } from "../lib/config";
import type * as T from "./types";
import { ApiShapeError, checkEnvelope, checkForecast, checkHistory, checkTwin, checkTwinList, checkUser, expectFields, expectObject } from "./validate";

export type ApiErrorKind = "network" | "validation" | "not_found" | "conflict" | "server" | "shape" | "unauthorized" | "forbidden" | "rate_limited";

/** Every failure becomes an ApiError with a readable message and a stable kind, so the UI never shows "[object Object]" or hides a failure. */
export class ApiError extends Error {
  constructor(public kind: ApiErrorKind, message: string, public status?: number, public retryAfter?: number) { super(message); }
}

/** Called when a NON-auth request comes back 401 (the session ended or was revoked). The auth layer uses it to sign the user out of the UI and explain why. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null): void { onUnauthorized = fn; }

function detailText(body: unknown): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((e) => {
      const x = e as { loc?: unknown[]; msg?: string };
      const field = (x.loc ?? []).filter((p) => p !== "body").join(".");
      return field ? `${field}: ${x.msg ?? "invalid"}` : (x.msg ?? "invalid");
    }).join("; ");
  }
  return "The request was rejected.";
}

async function request<R>(method: "GET" | "POST", path: string, body?: unknown, signal?: AbortSignal, validate?: (data: unknown) => void): Promise<R> {
  let res: Response;
  try {
    // credentials: the HttpOnly session cookie is sent to our own origin (the Vite proxy). The page never sees or stores the token or the password.
    res = await fetch(`${API_BASE_URL}${path}`, { method, signal, credentials: "same-origin", headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("network", "Cannot reach the GlycoTwin backend. Start it with: python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000");
  }
  let json: unknown = null;
  try { json = await res.json(); } catch { /* non-JSON error page */ }
  // The Vite proxy answers 500/502/503/504 with a plain page when the backend is not running at all, so that is "cannot reach", not "signed out" and not a bug in the request.
  if (!res.ok && (res.status === 502 || res.status === 503 || res.status === 504 || (res.status === 500 && json === null))) {
    throw new ApiError("network", "Cannot reach the GlycoTwin backend. Start it with: python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000", res.status);
  }
  if (!res.ok) {
    const msg = detailText(json);
    if (res.status === 401) {
      if (!path.startsWith("/auth/")) onUnauthorized?.();               // a wrong password on /auth/login is not an "expired session"
      throw new ApiError("unauthorized", msg, 401);
    }
    if (res.status === 403) throw new ApiError("forbidden", msg, 403);
    if (res.status === 429) throw new ApiError("rate_limited", msg, 429, Number(res.headers.get("Retry-After")) || undefined);
    if (res.status === 404) throw new ApiError("not_found", msg, 404);
    if (res.status === 409) throw new ApiError("conflict", msg, 409);
    if (res.status === 422) throw new ApiError("validation", msg, 422);
    throw new ApiError("server", res.status >= 500 ? "The backend failed to process the request; nothing was changed." : msg, res.status);
  }
  try {
    const data = path === "/health" ? json : checkEnvelope(json);
    validate?.(data);
    return data as R;
  } catch (e) {
    if (e instanceof ApiShapeError) throw new ApiError("shape", `Unexpected response from the backend (${e.message}).`, res.status);
    throw e;
  }
}

const enc = encodeURIComponent;

export const api = {
  register: (b: T.RegisterBody) => request<{ user: T.AuthUser }>("POST", "/auth/register", b, undefined, checkUser),
  login: (b: T.LoginBody) => request<{ user: T.AuthUser }>("POST", "/auth/login", b, undefined, checkUser),
  guest: () => request<{ user: T.AuthUser }>("POST", "/auth/guest", {}, undefined, checkUser),
  logout: () => request<{ signed_out: boolean }>("POST", "/auth/logout", {}),
  me: (signal?: AbortSignal) => request<{ user: T.AuthUser }>("GET", "/auth/me", undefined, signal, checkUser),
  listTwins: (signal?: AbortSignal) => request<{ twins: T.TwinSummary[] }>("GET", "/twins", undefined, signal, checkTwinList),
  health: (signal?: AbortSignal) => request<T.Health>("GET", "/health", undefined, signal, (d) => expectFields(expectObject(d, "health"), ["status", "database", "engine"], "health")),
  createTwin: (b: T.CreateTwinBody) => request<T.Twin>("POST", "/twins", b, undefined, checkTwin),
  getTwin: (id: string, signal?: AbortSignal) => request<T.Twin>("GET", `/twins/${enc(id)}`, undefined, signal, checkTwin),
  history: (id: string, signal?: AbortSignal) => request<T.History>("GET", `/twins/${enc(id)}/history`, undefined, signal, checkHistory),
  forecasts: (id: string, limit = 100, signal?: AbortSignal) => request<T.ForecastList>("GET", `/twins/${enc(id)}/forecasts?limit=${limit}`, undefined, signal,
    (d) => { const o = expectObject(d, "forecasts"); expectFields(o, ["forecasts", "total"], "forecasts"); (o.forecasts as unknown[]).forEach(checkForecast); }),
  forecast: (id: string, b: T.ForecastBody) => request<T.Forecast>("POST", `/twins/${enc(id)}/forecast`, b, undefined, checkForecast),
  observe: (id: string, b: T.ObserveBody) => request<T.Observation>("POST", `/twins/${enc(id)}/observe`, b, undefined,
    (d) => expectFields(expectObject(d, "observation"), ["observation_id", "forecast_id", "observed_through"], "observation")),
  reconcile: (id: string, forecast_id: string) => request<T.Reconciliation>("POST", `/twins/${enc(id)}/reconcile`, { forecast_id }, undefined,
    (d) => expectFields(expectObject(d, "reconciliation"), ["reconciliation_id", "outcome", "twin_version_before", "twin_version_after"], "reconciliation")),
  whatIf: (id: string, b: T.WhatIfBody) => request<T.WhatIf>("POST", `/twins/${enc(id)}/what-if`, b, undefined,
    (d) => expectFields(expectObject(d, "what-if"), ["comparison", "screen_label"], "what-if")),
  sensitivity: (id: string, activities: number[], signal?: AbortSignal) => request<T.Sensitivity>("GET", `/twins/${enc(id)}/sensitivity?activities=${activities.join(",")}`, undefined, signal,
    (d) => expectFields(expectObject(d, "sensitivity"), ["model_c_curve", "model_b"], "sensitivity")),
  explanation: (id: string, forecastId: string, model: "model_b" | "model_c", signal?: AbortSignal) =>
    request<T.Explanation>("GET", `/twins/${enc(id)}/forecasts/${enc(forecastId)}/explanation?model=${model}`, undefined, signal,
      (d) => expectFields(expectObject(d, "explanation"), ["terms", "plain_language"], "explanation")),
  reconciliations: (id: string, signal?: AbortSignal) => request<T.ReconciliationView>("GET", `/twins/${enc(id)}/reconciliations`, undefined, signal,
    (d) => expectFields(expectObject(d, "reconciliations"), ["reconciled", "pending", "summary"], "reconciliations")),
};
