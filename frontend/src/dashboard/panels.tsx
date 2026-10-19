import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Explanation, Forecast, History, Sensitivity, Twin, WhatIf } from "../api/types";
import { Field, parseNumber } from "../components/ui/Field";
import { ForecastStatusPill, Notice, Pill, Spinner } from "../components/ui/Status";
import { fmt, pct, shortId, signed, utcLabel } from "../lib/format";
import { linear, niceTicks } from "../lib/chartMath";
import { supportedActivityRange } from "./forms";
import { useWorkspace } from "./workspace";

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="stat"><span className="eyebrow">{label}</span><strong className="display">{value}</strong>{sub && <small>{sub}</small>}</div>;
}

export function TwinHeader({ twin }: { twin: Twin }) {
  const v = twin.state.historical_response_state.version_number;
  return (
    <header className="twin-head">
      <div><span className="eyebrow">Twin</span><h2 className="display">{twin.label}</h2>
        <p className="mono small">{shortId(twin.twin_id)} · version {v} · created {utcLabel(twin.created_at)}</p></div>
      <div className="pills">
        {twin.is_synthetic ? <Pill tone="unc">Synthetic demonstration prior</Pill> : <Pill tone="muted">Prior: {twin.prior_source}</Pill>}
        <Pill tone="muted">Scheme: {twin.prior_scheme}</Pill>
      </div>
    </header>
  );
}

export function ParamTable({ twin }: { twin: Twin }) {
  const p = twin.state.personalized_parameters;
  const c = p.carb_sensitivity_model_c_at_reference_activity;
  const sd = (m: { variance: number }) => Math.sqrt(m.variance);
  return (
    <table className="tbl">
      <caption>Posterior of the carbohydrate sensitivity (mg/dL rise per g), from the current twin version. n = {p.n_meals_observed} meals observed.</caption>
      <thead><tr><th scope="col">Parameter</th><th scope="col">Mean</th><th scope="col">SD</th></tr></thead>
      <tbody>
        <tr><th scope="row">Model B · β</th><td className="mono">{fmt(p.carb_sensitivity_model_b.mean, 3)}</td><td className="mono">{fmt(sd(p.carb_sensitivity_model_b), 3)}</td></tr>
        {c && <tr><th scope="row">Model C · β + γ·a at reference activity {fmt(c.reference_activity, 2)}</th><td className="mono">{fmt(c.mean, 3)}</td><td className="mono">{fmt(sd(c), 3)}</td></tr>}
        <tr><th scope="row">Model C · β</th><td className="mono">{fmt(p.beta_model_c.mean, 3)}</td><td className="mono">{fmt(sd(p.beta_model_c), 3)}</td></tr>
        <tr><th scope="row">Model C · γ (activity interaction)</th><td className="mono">{fmt(p.activity_interaction_coefficient.mean, 3)}</td><td className="mono">{fmt(sd(p.activity_interaction_coefficient), 3)}</td></tr>
      </tbody>
    </table>
  );
}

export function QualityNotices({ f }: { f: Forecast }) {
  const q = f.data_quality;
  const items = [...(q.warnings ?? []), ...(q.reasons ?? [])];
  if (!q.low_data_quality && !q.insufficient_history && !items.length && !q.interval_adjusted) return <Notice tone="ok" title="No data-quality flags for this forecast.">{q.note}</Notice>;
  return (
    <Notice tone="warn" title="Data-quality flags (from the backend)">
      <ul>{q.insufficient_history && <li>Insufficient personal history: {q.n_personal_observations} observed meals so far.</li>}
        {q.interval_adjusted && <li>The interval was widened because of data quality.</li>}
        {[...new Set(items)].map((w) => <li key={w}>{w}</li>)}</ul><p className="small">{q.note}</p>
    </Notice>
  );
}

export function ForecastTable({ forecasts, selected, onSelect }: { forecasts: Forecast[]; selected: string | null; onSelect: (id: string) => void }) {
  if (!forecasts.length) return null;
  return (
    <div className="tbl-wrap" tabIndex={0} role="region" aria-label="Forecast history">
      <table className="tbl">
        <thead><tr><th scope="col">Meal (UTC)</th><th scope="col">Carbs g</th><th scope="col">P(max ≥ 180) C / B</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Select</span></th></tr></thead>
        <tbody>{[...forecasts].reverse().map((f) => (
          <tr key={f.forecast_id} aria-current={f.forecast_id === selected ? "true" : undefined}>
            <th scope="row">{utcLabel(f.meal_time)}</th><td className="mono">{f.inputs.carbs_g}</td>
            <td className="mono">{pct(f.model_c.p_peak_at_least_180)} / {pct(f.model_b.p_peak_at_least_180)}</td>
            <td><ForecastStatusPill status={f.status} /></td>
            <td><button className="btn small" onClick={() => onSelect(f.forecast_id)} aria-label={`Show forecast for ${utcLabel(f.meal_time)}`}>{f.forecast_id === selected ? "Shown" : "Show"}</button></td>
          </tr>))}</tbody>
      </table>
    </div>
  );
}

export function ForecastNumbers({ f }: { f: Forecast }) {
  const row = (name: string, m: Forecast["model_c"]) => (
    <tr><th scope="row">{name}</th><td className="mono">{pct(m.p_peak_at_least_180)}</td><td className="mono">{signed(m.mean_rise_mg_dl)} ± {fmt(m.sd_mg_dl)}</td>
      <td className="mono">{fmt(f.inputs.baseline_glucose + m.interval90_rise_mg_dl[0], 0)} to {fmt(f.inputs.baseline_glucose + m.interval90_rise_mg_dl[1], 0)}</td></tr>);
  return (
    <table className="tbl">
      <caption>Forecast for the maximum glucose within 120 minutes after the meal. Twin version {f.twin_version_at_forecast}, model {f.model_version}.</caption>
      <thead><tr><th scope="col">Model</th><th scope="col">P(max ≥ 180 mg/dL)</th><th scope="col">Rise mean ± SD (mg/dL)</th><th scope="col">90% interval of the maximum (mg/dL)</th></tr></thead>
      <tbody>{row("Model C", f.model_c)}{row("Model B", f.model_b)}</tbody>
    </table>
  );
}

/** Loads a backend-computed explanation; shows nothing it did not get. */
export function ExplanationPanel({ twinId, forecast }: { twinId: string; forecast: Forecast }) {
  const [model, setModel] = useState<"model_b" | "model_c">("model_c");
  const [ex, setEx] = useState<Explanation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController(); setEx(null); setErr(null);
    api.explanation(twinId, forecast.forecast_id, model, ac.signal).then(setEx).catch((e: Error) => { if (e.name !== "AbortError") setErr(e.message); });
    return () => ac.abort();
  }, [twinId, forecast.forecast_id, model]);
  return (
    <section aria-labelledby="ex-h" className="panel">
      <div className="panel-head"><h3 id="ex-h" className="display">Why this forecast?</h3>
        <div role="group" aria-label="Model" className="seg">
          <button className="btn small" aria-pressed={model === "model_c"} onClick={() => setModel("model_c")}>Model C</button>
          <button className="btn small" aria-pressed={model === "model_b"} onClick={() => setModel("model_b")}>Model B</button></div></div>
      {err && <Notice tone="err" title="Explanation unavailable">{err}</Notice>}
      {!ex && !err && <Spinner label="Loading explanation" />}
      {ex && (<>
        <ul className="plain">{ex.plain_language.map((t) => <li key={t}>{t}</li>)}</ul>
        <table className="tbl"><caption>Contribution of each term to the predicted rise (mg/dL)</caption>
          <thead><tr><th scope="col">Term</th><th scope="col">Contribution</th><th scope="col">± SD</th></tr></thead>
          <tbody>{Object.entries(ex.terms).map(([k, t]) => <tr key={k}><th scope="row">{k}</th><td className="mono">{signed(t.contribution_mg_dl)}</td><td className="mono">{fmt(t.contribution_sd_mg_dl)}</td></tr>)}</tbody></table>
        <p className="small">Share of predictive variance due to parameter uncertainty: {pct(ex.variance.share_parameter_uncertainty)}.</p>
      </>)}
    </section>
  );
}

export function WhatIfPanel({ twinId, twin, baselineDefault }: { twinId: string; twin: Twin; baselineDefault: number | null }) {
  const range = supportedActivityRange(twin);
  const ws = useWorkspace();
  const [base, setBase] = useState(baselineDefault !== null ? String(baselineDefault) : "");
  const [rows, setRows] = useState([{ carbs: "60", act: "0.3" }, { carbs: "60", act: "0.8" }]);
  const [res, setRes] = useState<WhatIf | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    const b = parseNumber(base, "Pre-meal glucose", 20, 600);
    const sc = rows.map((r, i) => ({ c: parseNumber(r.carbs, `Scenario ${i + 1} carbohydrate`, 0, 500), a: parseNumber(r.act, `Scenario ${i + 1} activity`, range ? range[0] : 0, range ? range[1] : 25) }));
    const first = b.error ?? sc.map((s) => s.c.error ?? s.a.error).find(Boolean) ?? null;
    if (first || b.value === undefined) return setErr(first);
    setErr(null); setBusy(true);
    try { setRes(await api.whatIf(twinId, { baseline_glucose: b.value, scenarios: sc.map((s, i) => ({ label: `Scenario ${i + 1}`, carbs_g: s.c.value as number, activity_level: s.a.value as number })) })); }
    catch (e) { setRes(null); setErr(e instanceof ApiError ? e.message : "The comparison failed."); } finally { setBusy(false); }
    void ws;
  };
  return (
    <section aria-labelledby="wi-h" className="panel">
      <h3 id="wi-h" className="display">Compare scenarios</h3>
      <p className="small">Compares model forecasts for alternative meals and activity levels. These are statistical comparisons, not advice, and nothing is stored on the twin.</p>
      <Field label="Pre-meal glucose" unit="mg/dL" value={base} onChange={setBase} inputMode="decimal" />
      {rows.map((r, i) => (
        <div className="row2" key={i}>
          <Field label={`Scenario ${i + 1} carbohydrate (g)`} value={r.carbs} onChange={(v) => setRows(rows.map((x, j) => (j === i ? { ...x, carbs: v } : x)))} inputMode="decimal" />
          <Field label={`Scenario ${i + 1} activity`} value={r.act} onChange={(v) => setRows(rows.map((x, j) => (j === i ? { ...x, act: v } : x)))} inputMode="decimal" hint={range ? `${range[0]} to ${range[1]}` : undefined} />
        </div>))}
      <div className="actions">
        {rows.length < 10 && <button className="btn" onClick={() => setRows([...rows, { carbs: "60", act: rows[0].act }])}>Add scenario</button>}
        <button className="btn primary" onClick={run} disabled={busy}>{busy ? "Comparing…" : "Compare"}</button></div>
      {err && <Notice tone="err" title="Cannot compare">{err}</Notice>}
      {res && (
        <table className="tbl"><caption>{res.comparison.note}</caption>
          <thead><tr><th scope="col">Scenario</th><th scope="col">Carbs g</th><th scope="col">Activity</th><th scope="col">P(max ≥ 180) C</th><th scope="col">P B</th></tr></thead>
          <tbody>{res.comparison.rows.map((r) => <tr key={r.label}><th scope="row">{r.label}{r.is_reference ? " (reference)" : ""}</th><td className="mono">{r.carbs_g}</td><td className="mono">{r.activity_level}</td>
            <td className="mono">{pct(r.model_c.p_peak_at_least_180)}{r.model_c.delta_p_vs_reference !== undefined && ` (${signed(r.model_c.delta_p_vs_reference * 100, 0)} pts)`}</td><td className="mono">{pct(r.model_b.p_peak_at_least_180)}</td></tr>)}</tbody></table>)}
      {res?.prior_support_warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
    </section>
  );
}

/** Posterior of the carbohydrate sensitivity across twin versions, from /history. Only real versions are plotted. */
export function ParamEvolution({ history }: { history: History }) {
  const v = history.parameter_history.versions;
  if (v.length < 2) return <p className="small muted">Only one twin version exists. The parameter trajectory appears after the first reconciliation.</p>;
  const W = 640, H = 240, ml = 52, mr = 16, mt = 16, mb = 38;
  const all = v.flatMap((p) => [p.c_sensitivity_at_reference_mean - 1.645 * p.c_sensitivity_at_reference_sd, p.c_sensitivity_at_reference_mean + 1.645 * p.c_sensitivity_at_reference_sd, p.b_sensitivity_mean - 1.645 * p.b_sensitivity_sd, p.b_sensitivity_mean + 1.645 * p.b_sensitivity_sd]);
  const lo = Math.min(...all), hi = Math.max(...all);
  const y = linear([lo - (hi - lo) * 0.08, hi + (hi - lo) * 0.08], [H - mb, mt]);
  const x = linear([v[0].version, v[v.length - 1].version], [ml, W - mr]);
  const band = (m: (p: (typeof v)[0]) => [number, number]) => `${v.map((p, i) => `${i ? "L" : "M"}${x(p.version)},${y(m(p)[1])}`).join("")}${[...v].reverse().map((p) => `L${x(p.version)},${y(m(p)[0])}`).join("")}Z`;
  const line = (m: (p: (typeof v)[0]) => number) => v.map((p, i) => `${i ? "L" : "M"}${x(p.version)},${y(m(p))}`).join("");
  return (
    <figure className="fig">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="pe-t" className="chart-svg">
        <title id="pe-t">Carbohydrate sensitivity (mg/dL per g) with 90% credible band for Model B and Model C across {v.length} twin versions</title>
        {niceTicks(y.domain[0], y.domain[1], 5).map((t) => <g key={t}><line x1={ml} x2={W - mr} y1={y(t)} y2={y(t)} className="grid" /><text x={ml - 8} y={y(t) + 4} textAnchor="end" className="tick">{t.toFixed(2)}</text></g>)}
        {v.map((p) => <text key={p.version} x={x(p.version)} y={H - 14} textAnchor="middle" className="tick">v{p.version}</text>)}
        <path d={band((p) => [p.b_sensitivity_mean - 1.645 * p.b_sensitivity_sd, p.b_sensitivity_mean + 1.645 * p.b_sensitivity_sd])} fill="var(--ink-3)" opacity="0.14" />
        <path d={band((p) => [p.c_sensitivity_at_reference_mean - 1.645 * p.c_sensitivity_at_reference_sd, p.c_sensitivity_at_reference_mean + 1.645 * p.c_sensitivity_at_reference_sd])} fill="var(--coral)" opacity="0.18" />
        <path d={line((p) => p.b_sensitivity_mean)} stroke="var(--ink-2)" strokeDasharray="6 4" fill="none" strokeWidth="1.8" />
        <path d={line((p) => p.c_sensitivity_at_reference_mean)} stroke="var(--coral-d)" fill="none" strokeWidth="2.2" />
        <text x={ml} y={10} className="tick">mg/dL per g</text>
      </svg>
      <figcaption>◆ Model C at reference activity (solid) · ■ Model B (dashed). Bands are ±1.645 SD of the reported posterior. Narrowing bands mean the model is becoming more certain, not necessarily more accurate.</figcaption>
    </figure>
  );
}

export function SensitivityChart({ data }: { data: Sensitivity }) {
  const c = data.model_c_curve;
  const W = 640, H = 260, ml = 52, mr = 16, mt = 16, mb = 42;
  const vals = [...c.flatMap((p) => p.interval90), ...data.model_b.interval90];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y = linear([lo - (hi - lo) * 0.08, hi + (hi - lo) * 0.08], [H - mb, mt]);
  const x = linear([c[0].activity_level, c[c.length - 1].activity_level], [ml, W - mr]);
  const area = `${c.map((p, i) => `${i ? "L" : "M"}${x(p.activity_level)},${y(p.interval90[1])}`).join("")}${[...c].reverse().map((p) => `L${x(p.activity_level)},${y(p.interval90[0])}`).join("")}Z`;
  return (
    <figure className="fig">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="sc-t" className="chart-svg">
        <title id="sc-t">Personal carbohydrate sensitivity (mg/dL of peak rise per gram) against activity level: Model C with 90% interval, and Model B</title>
        {niceTicks(y.domain[0], y.domain[1], 5).map((t) => <g key={t}><line x1={ml} x2={W - mr} y1={y(t)} y2={y(t)} className="grid" /><text x={ml - 8} y={y(t) + 4} textAnchor="end" className="tick">{t.toFixed(2)}</text></g>)}
        {c.map((p) => <text key={p.activity_level} x={x(p.activity_level)} y={H - 20} textAnchor="middle" className="tick">{p.activity_level}</text>)}
        <text x={(ml + W - mr) / 2} y={H - 3} textAnchor="middle" className="tick">activity level (units of this twin's prior)</text>
        <path d={area} fill="var(--coral)" opacity="0.18" />
        <path d={c.map((p, i) => `${i ? "L" : "M"}${x(p.activity_level)},${y(p.mean)}`).join("")} stroke="var(--coral-d)" strokeWidth="2.2" fill="none" />
        <line x1={ml} x2={W - mr} y1={y(data.model_b.mean)} y2={y(data.model_b.mean)} stroke="var(--ink-2)" strokeDasharray="6 4" strokeWidth="1.8" />
      </svg>
      <figcaption>Sensitivity (mg/dL per g) as reported by the backend. ◆ Model C (solid, band = 90% interval) · ■ Model B (dashed, no activity term).</figcaption>
    </figure>
  );
}

export function PrototypeScopePanel({ twin }: { twin: Twin }) {
  const cal = twin.state.uncertainty?.calibration_score_rolling;
  const nReconciled = typeof cal?.n_reconciled_in_window === "number" ? cal.n_reconciled_in_window : null;
  const hasCalibration = cal?.model_b !== null && cal?.model_b !== undefined;
  const unavailable = twin.state.unavailable || [];

  return (
    <section className="panel" aria-labelledby="scope-h">
      <div className="panel-head">
        <h3 id="scope-h" className="display">Prototype Scope &amp; Diagnostics</h3>
        <Pill tone="muted">Research boundary</Pill>
      </div>
      <p className="small muted">
        GlycoTwin operates strictly within the CGMacros research dataset and Bayesian formulation. To prevent misleading claims, features outside the study design or lacking validated models are explicitly excluded rather than simulated.
      </p>

      <div className="stack" style={{ gap: 14 }}>
        <article className="scope-group">
          <h4 style={{ margin: "0 0 6px", fontSize: 15, fontWeight: 600 }}>Outside Current Dataset &amp; Model Scope</h4>
          <ul className="plain" style={{ gap: 6, fontSize: "13.5px" }}>
            <li>
              <strong>Clinical Lab Biomarkers:</strong> Blood lab panels (HbA1c, fasting glucose, fasting insulin, HOMA-IR, lipid panel) and static clinical attributes (BMI, glycaemic group, age, sex) are not linked into real-time twin state to protect participant anonymity and adhere to study boundaries.
            </li>
            <li>
              <strong>Continuous Heart-Rate Telemetry:</strong> Continuous heart-rate monitoring and HR-deviation features are not present in the CGMacros event dataset.
            </li>
            <li>
              <strong>Step Count &amp; Pedometry:</strong> Step counts are not captured in the meal event table. Activity is represented via wrist-worn MET estimations where recorded.
            </li>
            <li>
              <strong>Carbohydrate Absorption Kinetics:</strong> Continuous &ldquo;carbs on board&rdquo; curves require a validated gut pharmacokinetic absorption model. The research engine evaluates post-meal glucose rise directly from meal carb amounts without assuming an arbitrary absorption formula.
            </li>
          </ul>
        </article>

        <article className="scope-group" style={{ borderTop: "1px solid var(--line-s)", paddingTop: 12 }}>
          <h4 style={{ margin: "0 0 6px", fontSize: 15, fontWeight: 600 }}>Observational Lifecycle &amp; Calibration</h4>
          <p style={{ margin: "0 0 6px", fontSize: "13.5px" }}>
            <strong>Rolling Uncertainty Calibration:</strong> Requires a minimum of 3 closed outcome windows with reconciled post-meal observations to compute rolling Brier scores.
          </p>
          <div>
            {hasCalibration ? (
              <Pill tone="ok">Rolling calibration active (Model B: {fmt(cal?.model_b, 4)}, Model C: {fmt(cal?.model_c, 4)})</Pill>
            ) : nReconciled !== null ? (
              <Notice tone="info" title="Awaiting Reconciled Observations">
                Progress: {nReconciled} of 3 required reconciled meals recorded. Once at least 3 post-meal outcomes have been observed and applied to the twin, rolling calibration scores will display automatically.
              </Notice>
            ) : (
              <Notice tone="info" title="Insufficient Reconciled Forecasts">
                Rolling calibration will become available once 3 post-meal forecasts have been reconciled with observed glucose outcomes.
              </Notice>
            )}
          </div>
        </article>

        {unavailable.length > 0 && (
          <details className="technical-diagnostics" style={{ borderTop: "1px solid var(--line-s)", paddingTop: 10 }}>
            <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--ink-3)", fontWeight: 500 }}>
              Technical Blueprint Audit ({unavailable.length} unavailable keys)
            </summary>
            <div style={{ marginTop: 8 }}>
              <p className="small muted" style={{ margin: "0 0 6px" }}>
                Internal developer verification audit verifying Blueprint Section 4 contract completeness:
              </p>
              <ul className="plain" style={{ gap: 4, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--ink-2)" }}>
                {unavailable.map((item) => (
                  <li key={item} style={{ background: "var(--paper-2)", padding: "4px 8px", borderRadius: 4 }}>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}
