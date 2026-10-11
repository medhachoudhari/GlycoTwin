import { API_BASE_URL } from "../lib/config";
import type * as T from "./types";
import { ApiShapeError, checkEnvelope, checkForecast, checkHistory, checkTwin, expectFields, expectObject } from "./validate";

export type ApiErrorKind = "network" | "validation" | "not_found" | "conflict" | "server" | "shape";

/** Every failure becomes an ApiError with a readable message and a stable kind, so the UI never shows "[object Object]" or hides a failure. */
export class ApiError extends Error {
  constructor(public kind: ApiErrorKind, message: string, public status?: number) { super(message); }
}

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
    res = await fetch(`${API_BASE_URL}${path}`, { method, signal, headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("network", "Cannot reach the GlycoTwin backend. Start it with: python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000");
  }
  let json: unknown = null;
  try { json = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const msg = detailText(json);
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
