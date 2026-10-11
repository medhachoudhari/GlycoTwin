import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Forecast, Sensitivity } from "../api/types";
import { Disclaimer } from "../components/ui/Disclaimer";
import { Field } from "../components/ui/Field";
import { EmptyState, ForecastStatusPill, Notice, Pill, Spinner } from "../components/ui/Status";
import { API_BASE_URL } from "../lib/config";
import { fmt, pct, shortId, utcLabel } from "../lib/format";
import { appHref } from "../lib/router";
import { CreateTwinForm, MealForm, ObservationForm, OpenTwinForm, supportedActivityRange } from "./forms";
import { ExplanationPanel, ForecastNumbers, ForecastTable, ParamEvolution, ParamTable, QualityNotices, SensitivityChart, Stat, TwinHeader, WhatIfPanel } from "./panels";
import { ResponseChart, type ModelChoice } from "./ResponseChart";
import { observedPeakFor, useWorkspace } from "./workspace";

function NoTwin({ why }: { why?: string }) {
  const ws = useWorkspace();
  if (ws.busy.load) return <Spinner label="Loading twin" />;
  return (
    <div className="stack">
      {ws.loadError && <Notice tone="err" title={ws.loadError.kind === "not_found" ? "Twin not found" : "Could not load the twin"}>{ws.loadError.message}</Notice>}
      <EmptyState title="No twin selected" action={<a className="btn primary" href={appHref("settings")}>Create or open a twin</a>}>
        {why ?? "A twin is a personal posterior over how this person's glucose rises after carbohydrate. Create one (a synthetic demonstration twin needs no personal data) or open an existing twin by id."}
      </EmptyState>
    </div>
  );
}

function ModelToggle({ value, onChange }: { value: ModelChoice; onChange: (m: ModelChoice) => void }) {
  const opts: Array<[ModelChoice, string]> = [["both", "Both models"], ["model_c", "Model C"], ["model_b", "Model B"]];
  return <div role="group" aria-label="Models shown" className="seg">{opts.map(([k, l]) => <button key={k} className="btn small" aria-pressed={value === k} onClick={() => onChange(k)}>{l}</button>)}</div>;
}

function selected(ws: ReturnType<typeof useWorkspace>): Forecast | null {
  return ws.forecasts.find((f) => f.forecast_id === ws.selectedForecastId) ?? null;
}

function ChartBlock({ models, setModels }: { models: ModelChoice; setModels: (m: ModelChoice) => void }) {
  const ws = useWorkspace();
  const f = selected(ws);
  const ob = observedPeakFor(ws, f?.forecast_id ?? null);
  return (
    <section aria-labelledby="chart-h" className="panel wide">
      <div className="panel-head"><h3 id="chart-h" className="display">Glucose response</h3><ModelToggle value={models} onChange={setModels} /></div>
      <ResponseChart forecast={f} observedPeak={ob.peak} observedExcluded={ob.excluded} models={models} busy={ws.busy.forecast} />
      {f && <div className="pills"><ForecastStatusPill status={f.status} />{f.data_quality.low_data_quality && <Pill tone="warn">Low data quality</Pill>}{f.data_quality.insufficient_history && <Pill tone="unc">Limited personal history</Pill>}</div>}
    </section>
  );
}

export function HomeView() {
  const ws = useWorkspace();
  const [models, setModels] = useState<ModelChoice>("both");
  if (!ws.twin) return <NoTwin />;
  const t = ws.twin, p = t.state.personalized_parameters, f = selected(ws);
  const activity = [
    ...ws.forecasts.map((x) => ({ at: x.created_at, text: `Forecast for ${x.inputs.carbs_g} g meal`, id: x.forecast_id })),
    ...(ws.recon?.reconciled ?? []).map((r) => ({ at: r.meal_time, text: `Twin updated to version ${r.twin_version_after_update}`, id: r.forecast_id + "r" })),
  ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 6);
  return (
    <div className="stack">
      <TwinHeader twin={t} />
      <div className="stats">
        <Stat label="Twin version" value={String(t.state.historical_response_state.version_number)} />
        <Stat label="Meals observed" value={String(p.n_meals_observed)} sub="used to update this twin" />
        <Stat label="Awaiting outcome" value={String(t.state.meal_state.forecasts_awaiting_reconciliation.length)} sub="forecasts" />
        <Stat label="Last forecast" value={f ? pct(f.model_c.p_peak_at_least_180) : "n/a"} sub={f ? "P(max ≥ 180), Model C" : "no forecast yet"} />
      </div>
      <ChartBlock models={models} setModels={setModels} />
      <div className="cols">
        <section className="panel" aria-labelledby="act-h"><h3 id="act-h" className="display">Recent activity</h3>
          {activity.length ? <ol className="timeline">{activity.map((a) => <li key={a.id}><span className="mono small">{utcLabel(a.at)}</span> {a.text}</li>)}</ol> : <p className="small muted">Nothing yet. Request a forecast from the Forecast screen.</p>}</section>
        <section className="panel" aria-labelledby="nx-h"><h3 id="nx-h" className="display">Next step</h3>
          {ws.forecasts.length === 0 ? <p>Request the first forecast. <a href={appHref("forecast")}>Go to Forecast</a></p>
            : t.state.meal_state.forecasts_awaiting_reconciliation.length ? <p>A forecast is waiting for its real outcome. <a href={appHref("observations")}>Record the outcome</a></p>
              : <p>Everything recorded has been applied. <a href={appHref("forecast")}>Forecast another meal</a></p>}</section>
      </div>
    </div>
  );
}

export function TwinView() {
  const ws = useWorkspace();
  if (!ws.twin) return <NoTwin />;
  const t = ws.twin;
  return (
    <div className="stack">
      <TwinHeader twin={t} />
      <section className="panel" aria-labelledby="pt-h"><h3 id="pt-h" className="display">Personalised parameters</h3><ParamTable twin={t} />
        <p className="small">Posterior band width (90%): Model B {fmt(t.state.uncertainty.posterior_band_width_90.model_b, 3)} mg/dL per g.</p></section>
      <section className="panel" aria-labelledby="pv-h"><h3 id="pv-h" className="display">Version history</h3>
        {ws.history ? <ol className="timeline">{[...ws.history.versions].reverse().map((v) => (
          <li key={v.version}><strong>Version {v.version}</strong> <span className="mono small">{utcLabel(v.created_at)}</span> · {v.n_observations} observed meals{v.parent_version !== null ? ` · from v${v.parent_version}` : " · initial prior"}</li>))}</ol> : <Spinner label="Loading" />}</section>
      <section className="panel" aria-labelledby="prv-h"><h3 id="prv-h" className="display">Provenance</h3>
        <dl className="kv"><dt>Prior source</dt><dd>{t.prior_source}</dd><dt>Prior scheme</dt><dd>{t.prior_scheme}</dd>
          <dt>Participant-level data in prior</dt><dd>{t.prior_provenance.contains_participant_level_data ? "yes" : "no"}</dd>
          <dt>Reference activity</dt><dd>{t.config.reference_activity}</dd></dl>
        {t.state.unavailable.length > 0 && <Notice tone="info" title="Not available from this backend">{t.state.unavailable.join("; ")}</Notice>}</section>
    </div>
  );
}

export function ForecastView() {
  const ws = useWorkspace();
  const [models, setModels] = useState<ModelChoice>("both");
  if (!ws.twin) return <NoTwin />;
  const f = selected(ws);
  return (
    <div className="stack">
      <div className="split">
        <section className="panel" aria-labelledby="mf-h"><h3 id="mf-h" className="display">Meal</h3><MealForm />
          {ws.lastAction?.kind === "forecast" && <Notice tone={ws.lastAction.ok ? "ok" : "err"}>{ws.lastAction.message}</Notice>}</section>
        <ChartBlock models={models} setModels={setModels} />
      </div>
      {f && (<>
        <section className="panel" aria-labelledby="fn-h"><h3 id="fn-h" className="display">Numbers behind the chart</h3><ForecastNumbers f={f} /><QualityNotices f={f} /></section>
        <ExplanationPanel twinId={ws.twin.twin_id} forecast={f} />
      </>)}
      <WhatIfPanel key={ws.twin.twin_id} twinId={ws.twin.twin_id} twin={ws.twin} baselineDefault={f ? f.inputs.baseline_glucose : null} />
    </div>
  );
}

export function ObservationsView() {
  const ws = useWorkspace();
  if (!ws.twin) return <NoTwin />;
  const toApply = ws.forecasts.filter((f) => f.status === "observed");
  return (
    <div className="stack">
      <div className="split">
        <section className="panel" aria-labelledby="ob-h"><h3 id="ob-h" className="display">Record an outcome</h3><ObservationForm forecasts={ws.forecasts} />
          {ws.lastAction?.kind === "observe" && <Notice tone={ws.lastAction.ok ? "ok" : "err"}>{ws.lastAction.message}</Notice>}</section>
        <section className="panel" aria-labelledby="ap-h"><h3 id="ap-h" className="display">Apply to the twin</h3>
          <p className="small">Recording an outcome does not change the twin. Applying it creates a new twin version. Excluded meals never change the twin.</p>
          {toApply.length === 0 ? <p className="small muted">No recorded outcome is waiting to be applied.</p> : (
            <ul className="plain">{toApply.map((f) => {
              const ob = ws.observations[f.forecast_id];
              return <li key={f.forecast_id} className="apply-row"><span>{utcLabel(f.meal_time)} · {f.inputs.carbs_g} g{ob?.excluded_reason ? ` · excluded: ${ob.excluded_reason}` : ob?.peak_glucose_mg_dl != null ? ` · observed max ${fmt(ob.peak_glucose_mg_dl, 0)} mg/dL` : ""}</span>
                <button className="btn primary small" disabled={ws.busy.reconcile} onClick={() => void ws.applyReconcile(f.forecast_id)}>{ws.busy.reconcile ? "Applying…" : "Apply"}</button></li>;
            })}</ul>)}
          {ws.lastAction && (ws.lastAction.kind === "reconcile") && <Notice tone={ws.lastAction.ok ? "ok" : "err"}>{ws.lastAction.message}</Notice>}
          {ws.lastReconciliation?.outcome === "updated" && ws.lastReconciliation.parameter_change && (
            <p className="small">Model C β: {fmt(ws.lastReconciliation.parameter_change.model_c.beta_mean_before, 3)} → {fmt(ws.lastReconciliation.parameter_change.model_c.beta_mean_after, 3)}; its SD ratio {fmt(ws.lastReconciliation.parameter_change.model_c.beta_sd_ratio, 2)}.</p>)}</section>
      </div>
    </div>
  );
}

export function HistoryView() {
  const ws = useWorkspace();
  if (!ws.twin) return <NoTwin />;
  const h = ws.history;
  return (
    <div className="stack">
      <section className="panel" aria-labelledby="fh-h"><h3 id="fh-h" className="display">Forecasts</h3>
        {ws.forecasts.length ? <ForecastTable forecasts={ws.forecasts} selected={ws.selectedForecastId} onSelect={ws.selectForecast} /> : <p className="small muted">No forecasts yet.</p>}</section>
      <section className="panel" aria-labelledby="pe-h"><h3 id="pe-h" className="display">How the twin's parameters changed</h3>{h ? <ParamEvolution history={h} /> : <Spinner label="Loading" />}</section>
      {h && (
        <section className="panel" aria-labelledby="hr-h"><h3 id="hr-h" className="display">Hit rate so far</h3>
          <p>Reconciled meals: {h.hit_rate_trend.n_reconciled}. Model C {pct(h.hit_rate_trend.model_c.overall_hit_rate)} · Model B {pct(h.hit_rate_trend.model_b.overall_hit_rate)}</p>
          <p className="small">{h.hit_rate_trend.note}</p>
          {h.exclusions.length > 0 && <><h4>Excluded meals</h4><ul>{h.exclusions.map((e) => <li key={e.forecast_id}><span className="mono">{shortId(e.forecast_id)}</span>: {e.reason}</li>)}</ul></>}</section>)}
    </div>
  );
}

export function InsightsView() {
  const ws = useWorkspace();
  const twin = ws.twin;
  const range = supportedActivityRange(twin);
  const [text, setText] = useState(range ? "0, 0.25, 0.5, 0.75, 1" : "");
  const [data, setData] = useState<Sensitivity | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const twinId = twin?.twin_id ?? null;
  const version = twin?.state.historical_response_state.version_number;
  const load = async (raw: string) => {
    if (!twinId) return;
    const xs = raw.split(",").map((s) => s.trim()).filter(Boolean).map(Number);
    if (!xs.length || xs.length > 25 || xs.some((x) => !Number.isFinite(x) || x < 0 || x > 25)) return setErr("Enter between 1 and 25 numeric activity values from 0 to 25, separated by commas.");
    setBusy(true); setErr(null);
    try { setData(await api.sensitivity(twinId, xs)); } catch (e) { setData(null); setErr((e as Error).message); } finally { setBusy(false); }
  };
  useEffect(() => { setData(null); if (range) void load("0, 0.25, 0.5, 0.75, 1"); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [twinId, version]);
  if (!twin) return <NoTwin />;
  const rec = ws.recon;
  return (
    <div className="stack">
      <section className="panel" aria-labelledby="se-h"><h3 id="se-h" className="display">How activity changes this twin's carbohydrate sensitivity</h3>
        <p className="small">A description of the fitted posterior, not a causal claim about exercise.</p>
        <form className="row2" onSubmit={(e) => { e.preventDefault(); void load(text); }}>
          <Field label="Activity values" value={text} onChange={setText} hint={range ? `Demonstration twin range ${range[0]} to ${range[1]}.` : "Mean METs, 0 to 25."} />
          <button className="btn" type="submit" disabled={busy}>{busy ? "Loading…" : "Update"}</button></form>
        {err && <Notice tone="err" title="Sensitivity unavailable">{err}</Notice>}
        {data && <SensitivityChart data={data} />}
        {data?.prior_support_warnings.map((w) => <Notice key={w} tone="warn">{w}</Notice>)}
        {!data && !err && !busy && <p className="small muted">Enter activity values to compute the curve.</p>}</section>
      <section className="panel" aria-labelledby="rc-h"><h3 id="rc-h" className="display">Forecast versus outcome</h3>
        {rec && rec.reconciled.length ? (
          <table className="tbl"><thead><tr><th scope="col">Meal (UTC)</th><th scope="col">Observed rise</th><th scope="col">P given, C / B</th><th scope="col">Inside 90% C / B</th></tr></thead>
            <tbody>{rec.reconciled.map((r) => <tr key={r.forecast_id}><th scope="row">{utcLabel(r.meal_time)}</th><td className="mono">{fmt(r.observed.peak_rise_mg_dl)} mg/dL</td>
              <td className="mono">{pct(r.model_c.forecast_p_peak_at_least_180)} / {pct(r.model_b.forecast_p_peak_at_least_180)}</td><td>{r.model_c.observed_inside_interval90 ? "yes" : "no"} / {r.model_b.observed_inside_interval90 ? "yes" : "no"}</td></tr>)}</tbody></table>
        ) : <p className="small muted">No reconciled meals yet. Few meals per person cannot establish calibration, and none of this has been clinically validated.</p>}</section>
    </div>
  );
}

export function SettingsView() {
  const ws = useWorkspace();
  return (
    <div className="stack">
      <div className="split">
        <section className="panel" aria-labelledby="c1-h"><h3 id="c1-h" className="display">Create a twin</h3><CreateTwinForm />
          {ws.lastAction?.kind === "create" && <Notice tone={ws.lastAction.ok ? "ok" : "err"}>{ws.lastAction.message}</Notice>}</section>
        <section className="panel" aria-labelledby="c2-h"><h3 id="c2-h" className="display">Open an existing twin</h3><OpenTwinForm />
          <p className="small">The backend has no endpoint that lists twins, so this browser remembers the ones you created or opened. Clearing site data forgets the list, not the twins.</p></section>
      </div>
      <section className="panel" aria-labelledby="rg-h"><h3 id="rg-h" className="display">Twins in this browser</h3>
        {ws.registry.length ? <ul className="plain">{ws.registry.map((e) => (
          <li key={e.id} className="apply-row"><span>{e.label} <span className="mono small">{shortId(e.id)}</span>{e.id === ws.activeId && <Pill tone="ok">Active</Pill>}</span>
            <span className="actions"><button className="btn small" onClick={() => ws.selectTwin(e.id)} disabled={e.id === ws.activeId}>Use</button><button className="btn small" onClick={() => ws.forgetTwin(e.id)} aria-label={`Forget ${e.label} in this browser`}>Forget</button></span></li>))}</ul>
          : <p className="small muted">None yet.</p>}</section>
      <section className="panel" aria-labelledby="bk-h"><h3 id="bk-h" className="display">Backend</h3>
        <dl className="kv"><dt>API base URL</dt><dd className="mono">{API_BASE_URL}</dd>
          <dt>Status</dt><dd>{ws.health ? <Pill tone={ws.health.status === "ok" ? "ok" : "warn"}>{ws.health.status}</Pill> : ws.healthError ? <Pill tone="err">unreachable</Pill> : "checking…"}</dd>
          {ws.health && <><dt>Engine</dt><dd className="mono">{ws.health.engine.package_version ?? "n/a"} · {ws.health.engine.git_commit?.slice(0, 8) ?? "n/a"}{ws.health.engine.working_tree_dirty ? " (uncommitted changes)" : ""}</dd></>}</dl>
        {ws.healthError && <Notice tone="err" title="Backend not reachable">{ws.healthError}</Notice>}</section>
      <Disclaimer variant="block" />
    </div>
  );
}
