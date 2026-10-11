/**
 * A tiny in-memory stand-in for the backend's account and twin endpoints, used only by the UI tests. It mimics the behaviours the UI depends on:
 * an HttpOnly session cookie (held in `jar`, invisible to page code), 401 when signed out, ownership (each user sees only their own twins), 409/401/422/429 errors.
 * It is NOT the real backend: the real backend's rules are proven by tests/test_auth.py and tests/test_ownership.py.
 */
interface U { id: string; name: string; email: string | null; password: string | null; guest: boolean }
interface Tw { owner: string; id: string; label: string; version: number }

export function fixtureTwin(t: { id: string; label: string; version: number }) {
  return {
    twin_id: t.id, label: t.label, created_at: "2026-01-01T00:00:00", prior_source: "synthetic_demo", prior_scheme: "empirical_bayes", gamma_relative_sd: null,
    prior_provenance: { source: "synthetic", SYNTHETIC: true, prior_scheme: "empirical_bayes", gamma_relative_sd: null, contains_participant_level_data: false, supported_activity_range: [0, 1] },
    profile: {}, config: { reference_activity: 1, outcome_window_minutes: 120, threshold_mg_dl: 180 }, is_synthetic: true, insight: {},
    state: {
      kind: "x", as_of: null, current_glucose_state: { last_value_mg_dl: null, as_of: null, basis: "" }, recent_activity_state: { rolling_mets_4h: null, activity_label: "", as_of: null, step_count_today: null },
      meal_state: { open_meal_windows: [], forecasts_awaiting_reconciliation: [], carbs_in_open_outcome_windows_g: 0 },
      personalized_parameters: { carb_sensitivity_model_b: { mean: 0.7, variance: 0.03 }, carb_sensitivity_model_c_at_reference_activity: { mean: 0.6, variance: 0.04, reference_activity: 1 },
        beta_model_c: { mean: 0.8, variance: 0.03, note: "" }, activity_interaction_coefficient: { mean: -0.2, variance: 0.001 }, n_meals_observed: 0 },
      uncertainty: { posterior_band_width_90: { model_b: 0.6, model_c_at_reference_activity: 0.7, unit: "mg/dL per g" }, calibration_score_rolling: { window: 5, n_reconciled_in_window: 0, model_b: null, model_c: null } },
      prediction_state: { last_forecast_id: null }, historical_response_state: { version_number: t.version, parent_version_id: null, created_at: "2026-01-01T00:00:00", reconciliation_log_ref: [] }, unavailable: [],
    },
  };
}

export function makeBackend() {
  const users: U[] = []; const sessions = new Map<string, string>(); const twins: Tw[] = [];
  const jar = { token: null as string | null };                // the browser's cookie jar (HttpOnly: page code never reads it)
  const calls: Array<{ method: string; path: string; body: any }> = [];
  const state = { offline: false, proxyDown: false, listFails: false, failedLogins: 0, n: 0 };
  const env = (data: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify({ disclaimer: "x", data }), { status, headers: { "content-type": "application/json", ...headers } });
  const err = (status: number, detail: string, headers: Record<string, string> = {}) => new Response(JSON.stringify({ detail, disclaimer: "x" }), { status, headers: { "content-type": "application/json", ...headers } });
  const pub = (u: U) => ({ id: u.id, name: u.name, email: u.email, is_guest: u.guest, created_at: "2026-01-01T00:00:00" });
  const who = (): U | null => { const id = jar.token ? sessions.get(jar.token) : undefined; return id ? users.find((u) => u.id === id) ?? null : null; };
  const open = (u: U) => { const t = `tok-${++state.n}`; sessions.set(t, u.id); jar.token = t; };

  const fetchFn = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    if (state.offline) throw new TypeError("Failed to fetch");
    if (state.proxyDown) return new Response("", { status: 500 });                // what the Vite dev proxy answers when nothing is listening on the backend port
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, ""); const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
    if (path === "/health") return new Response(JSON.stringify({ status: "ok", database: "ok", tables: [], engine: { package_version: "0", git_commit: "abc", working_tree_dirty: false, engine: "e" } }));
    if (path === "/auth/register" && method === "POST") {
      if (users.some((u) => u.email === body.email.toLowerCase())) return err(409, "an account with this email already exists");
      if (body.password.length < 10) return err(422, "password must be at least 10 characters");
      const u = { id: `u-${users.length + 1}`, name: body.name, email: body.email.toLowerCase(), password: body.password, guest: false }; users.push(u); open(u); return env({ user: pub(u) }, 201);
    }
    if (path === "/auth/login" && method === "POST") {
      if (state.failedLogins >= 5) return err(429, "too many failed sign-in attempts; try again later", { "Retry-After": "600" });
      const u = users.find((x) => x.email === body.email.toLowerCase());
      if (!u || u.password !== body.password) { state.failedLogins++; return err(401, "incorrect email or password"); }
      open(u); return env({ user: pub(u) });
    }
    if (path === "/auth/guest" && method === "POST") { const u = { id: `g-${users.length + 1}`, name: "Guest", email: null, password: null, guest: true }; users.push(u); open(u); return env({ user: pub(u) }, 201); }
    if (path === "/auth/logout" && method === "POST") { if (jar.token) sessions.delete(jar.token); jar.token = null; return env({ signed_out: true }); }
    if (path === "/auth/me") { const u = who(); return u ? env({ user: pub(u) }) : err(401, "not signed in"); }
    const u = who();
    if (!u) return err(401, "not signed in");
    if (path === "/twins" && method === "GET") { if (state.listFails) return err(500, "boom"); return env({ twins: twins.filter((t) => t.owner === u.id).map((t) => ({ twin_id: t.id, label: t.label, created_at: "2026-01-01T00:00:00", prior_source: "synthetic_demo", prior_scheme: "empirical_bayes", is_synthetic: true, current_version: t.version })) }); }
    if (path === "/twins" && method === "POST") {
      if (twins.some((t) => t.label === body.label)) return err(409, "a twin with this label already exists");
      const t = { owner: u.id, id: `123e4567-e89b-12d3-a456-4266141740${String(twins.length).padStart(2, "0")}`, label: body.label, version: 0 }; twins.push(t); return env(fixtureTwin(t), 201);
    }
    const m = path.match(/^\/twins\/([^/]+)(\/.*)?$/);
    if (m) {
      const t = twins.find((x) => x.id === m[1] && x.owner === u.id);
      if (!t) return err(404, "twin not found");
      const rest = m[2] ?? "";
      if (rest === "") return env(fixtureTwin(t));
      if (rest === "/forecasts") return env({ twin_id: t.id, total: 0, limit: 100, offset: 0, forecasts: [] });
      if (rest === "/history") return env({ twin_id: t.id, reference_activity: 1, versions: [{ version: 0, parent_version: null, created_at: "2026-01-01T00:00:00", n_observations: 0, reconciliation_id: null, parameters: {} }],
        parameter_history: { versions: [] }, posterior_convergence: { n_observations: [], sd: {}, monotone_non_increasing: {}, current_over_prior: {} }, hit_rate_trend: { n_reconciled: 0, model_b: { overall_hit_rate: null }, model_c: { overall_hit_rate: null }, note: "" }, exclusions: [] });
      if (rest === "/reconciliations") return env({ reconciled: [], pending: [], summary: { n_reconciled: 0, n_pending: 0 } });
    }
    return err(404, "not found");
  };
  return { fetch: fetchFn, jar, calls, state, users, twins, expireSessions: () => sessions.clear() };
}
