/** Small runtime checks on API responses: a malformed body becomes a clear error instead of a silent NaN on screen. */
export class ApiShapeError extends Error {}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function expectObject(v: unknown, what: string): Record<string, unknown> {
  if (!isObj(v)) throw new ApiShapeError(`${what}: expected an object`);
  return v;
}
export function expectFields(o: Record<string, unknown>, fields: string[], what: string): void {
  const missing = fields.filter((f) => !(f in o));
  if (missing.length) throw new ApiShapeError(`${what}: missing ${missing.join(", ")}`);
}
export function expectFinite(v: unknown, what: string): number {
  if (!fin(v)) throw new ApiShapeError(`${what}: expected a finite number`);
  return v;
}
export function expectInterval(v: unknown, what: string): [number, number] {
  if (!Array.isArray(v) || v.length !== 2 || !fin(v[0]) || !fin(v[1]) || v[0] > v[1]) throw new ApiShapeError(`${what}: expected [low, high]`);
  return [v[0], v[1]];
}

export function checkModelForecast(v: unknown, what: string): void {
  const o = expectObject(v, what);
  expectFields(o, ["p_peak_at_least_180", "mean_rise_mg_dl", "sd_mg_dl", "interval90_rise_mg_dl"], what);
  const p = expectFinite(o.p_peak_at_least_180, `${what}.p`);
  if (p < 0 || p > 1) throw new ApiShapeError(`${what}.p: outside [0, 1]`);
  expectFinite(o.mean_rise_mg_dl, `${what}.mean`);
  if (expectFinite(o.sd_mg_dl, `${what}.sd`) <= 0) throw new ApiShapeError(`${what}.sd: must be positive`);
  expectInterval(o.interval90_rise_mg_dl, `${what}.interval`);
}
export function checkForecast(v: unknown): void {
  const o = expectObject(v, "forecast");
  expectFields(o, ["forecast_id", "event_id", "meal_time", "twin_version_at_forecast", "inputs", "model_b", "model_c", "status", "data_quality"], "forecast");
  checkModelForecast(o.model_b, "forecast.model_b");
  checkModelForecast(o.model_c, "forecast.model_c");
  const inp = expectObject(o.inputs, "forecast.inputs");
  expectFinite(inp.baseline_glucose, "forecast.inputs.baseline_glucose");
}
export function checkTwin(v: unknown): void {
  const o = expectObject(v, "twin");
  expectFields(o, ["twin_id", "label", "state", "prior_provenance", "config"], "twin");
  const st = expectObject(o.state, "twin.state");
  expectFields(st, ["historical_response_state", "personalized_parameters"], "twin.state");
}
export function checkHistory(v: unknown): void {
  const o = expectObject(v, "history");
  expectFields(o, ["versions", "parameter_history", "posterior_convergence"], "history");
  if (!Array.isArray(o.versions) || o.versions.length === 0) throw new ApiShapeError("history: no versions");
}
export function checkEnvelope(v: unknown): unknown {
  const o = expectObject(v, "response");
  expectFields(o, ["disclaimer", "data"], "response");
  return o.data;
}
export function checkUser(v: unknown): void {
  const o = expectObject(v, "auth");
  const u = expectObject(o.user, "auth.user");
  expectFields(u, ["id", "name", "is_guest"], "auth.user");
}
export function checkTwinList(v: unknown): void {
  const o = expectObject(v, "twins");
  if (!Array.isArray(o.twins)) throw new ApiShapeError("twins: expected a list");
  o.twins.forEach((t) => expectFields(expectObject(t, "twins[]"), ["twin_id", "label", "current_version"], "twins[]"));
}
