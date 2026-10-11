import { useMemo, useState, type FormEvent } from "react";
import type { Forecast, Twin } from "../api/types";
import { Field, parseNumber } from "../components/ui/Field";
import { Notice, Spinner } from "../components/ui/Status";
import { OUTCOME_WINDOW_MIN } from "../lib/config";
import { addMinutesIso, inputToIso, newEventId, utcLabel } from "../lib/format";
import { useWorkspace } from "./workspace";

/** Same pattern the backend enforces on twin labels. */
export const LABEL_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
const nowLocalInput = (): string => new Date().toISOString().slice(0, 16);

/** Activity range the twin's prior was fitted on. The backend is the authority; this only catches obvious mistakes before a round trip. */
export function supportedActivityRange(t: Twin | null): [number, number] | null {
  const p = t?.prior_provenance;
  const r = p?.supported_activity_range ?? p?.activity_range;
  return t?.is_synthetic && r && r.length === 2 ? [r[0], r[1]] : null;
}

export function CreateTwinForm() {
  const ws = useWorkspace();
  const [label, setLabel] = useState("");
  const [source, setSource] = useState<"synthetic_demo" | "prior_file">("synthetic_demo");
  const [fileName, setFileName] = useState("");
  const [scheme, setScheme] = useState<"empirical_bayes" | "blueprint">("empirical_bayes");
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (label.toLowerCase().includes("cgmacros")) return setErr("Labels that look like research participant ids are not accepted.");
    if (!LABEL_RE.test(label.trim())) return setErr("Use 1 to 64 letters, digits, dots, dashes, colons or underscores, starting with a letter or digit (no spaces).");
    if (source === "prior_file" && !fileName.trim()) return setErr("Name the prior file the backend should load.");
    setErr(null);
    const ok = await ws.createTwin({ label: label.trim(), prior: { source, prior_scheme: scheme, ...(source === "prior_file" ? { name: fileName.trim() } : {}) } });
    if (ok) setLabel("");
  };
  return (
    <form className="form" onSubmit={submit} noValidate aria-label="Create a twin">
      <Field label="Twin label" value={label} onChange={setLabel} error={err} placeholder="e.g. demo-twin-a" maxLength={64} hint="Letters, digits, . _ : - only (no spaces)." />
      <div className="field"><label htmlFor="ct-src">Prior source</label>
        <select id="ct-src" className="input" value={source} onChange={(e) => setSource(e.target.value as typeof source)}>
          <option value="synthetic_demo">Synthetic demonstration prior (no real participants)</option>
          <option value="prior_file">Prior file already on the backend host</option>
        </select></div>
      {source === "prior_file" && <Field label="Prior file name" value={fileName} onChange={setFileName} hint="Resolved by the backend; participant-level data is never uploaded from the browser." />}
      <div className="field"><label htmlFor="ct-scheme">Prior scheme</label>
        <select id="ct-scheme" className="input" value={scheme} onChange={(e) => setScheme(e.target.value as typeof scheme)}>
          <option value="empirical_bayes">Empirical Bayes (default)</option>
          <option value="blueprint">Blueprint prior (opt-in)</option>
        </select></div>
      <button className="btn primary" type="submit" disabled={ws.busy.create}>{ws.busy.create ? "Creating…" : "Create twin"}</button>
    </form>
  );
}

export function OpenTwinForm() {
  const ws = useWorkspace();
  const [id, setId] = useState("");
  return (
    <form className="form" onSubmit={(e) => { e.preventDefault(); void ws.openTwinById(id); }} aria-label="Open an existing twin">
      <Field label="Twin id" value={id} onChange={setId} className="input mono" spellCheck={false} placeholder="UUID returned when the twin was created" />
      <button className="btn" type="submit" disabled={!id.trim()}>Open twin</button>
    </form>
  );
}

export function MealForm({ onDone }: { onDone?: (f: Forecast) => void }) {
  const ws = useWorkspace();
  const range = supportedActivityRange(ws.twin);
  const [carbs, setCarbs] = useState("60");
  const [activity, setActivity] = useState("0.3");
  const [baseline, setBaseline] = useState("");
  const [mealTime, setMealTime] = useState(nowLocalInput);
  const [eventId, setEventId] = useState(newEventId);
  const [errs, setErrs] = useState<Record<string, string | null>>({});

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const c = parseNumber(carbs, "Carbohydrate", 0, 500);
    const a = parseNumber(activity, "Activity level", range ? range[0] : 0, range ? range[1] : 25);
    const b = parseNumber(baseline, "Pre-meal glucose", 20, 600);
    const next = { carbs: c.error, activity: a.error, baseline: b.error, time: mealTime ? null : "Meal time is required." };
    setErrs(next);
    if (c.error || a.error || b.error || next.time || c.value === undefined || a.value === undefined || b.value === undefined) return;
    const f = await ws.requestForecast({ event_id: eventId, meal_time: inputToIso(mealTime), carbs_g: c.value, activity_level: a.value, baseline_glucose: b.value });
    if (f) { setEventId(newEventId()); onDone?.(f); }
  };
  return (
    <form className="form" onSubmit={submit} noValidate aria-label="Request a forecast for a meal">
      <Field label="Carbohydrate" unit="g" inputMode="decimal" value={carbs} onChange={setCarbs} error={errs.carbs} />
      <Field label="Pre-meal activity" unit={range ? "simulated scale" : "as fitted for this prior"} inputMode="decimal" value={activity} onChange={setActivity} error={errs.activity}
        hint={range ? `This demonstration twin accepts ${range[0]} to ${range[1]} (a simulated scale, not METs).` : "Mean METs over the 4 hours before the meal (0 to 25), on the scale this twin's prior was fitted with. The backend flags out-of-range values."} />
      <Field label="Pre-meal glucose" unit="mg/dL" inputMode="decimal" value={baseline} onChange={setBaseline} error={errs.baseline} hint="Your own reading just before the meal. Nothing is pre-filled." />
      <div className="field"><label htmlFor="meal-time">Meal time (UTC)</label>
        <input id="meal-time" type="datetime-local" className="input" value={mealTime} onChange={(e) => setMealTime(e.target.value)} aria-invalid={errs.time ? true : undefined} />
        {errs.time && <span className="err">{errs.time}</span>}
        <span className="hint">The backend refuses forecasts dated before the twin's latest recorded event.</span></div>
      <button className="btn primary" type="submit" disabled={ws.busy.forecast || !ws.twin}>{ws.busy.forecast ? "Forecasting…" : "Request forecast"}</button>
      {ws.busy.forecast && <Spinner label="Computing posterior-predictive forecast" />}
    </form>
  );
}

export function ObservationForm({ forecasts }: { forecasts: Forecast[] }) {
  const ws = useWorkspace();
  const open = useMemo(() => forecasts.filter((f) => f.status === "pending"), [forecasts]);
  const [fid, setFid] = useState("");
  const chosen = open.find((f) => f.forecast_id === fid) ?? open[open.length - 1] ?? null;
  const [through, setThrough] = useState("");
  const [peak, setPeak] = useState("");
  const [completeness, setCompleteness] = useState("1");
  const [exclude, setExclude] = useState(false);
  const [reason, setReason] = useState("");
  const [errs, setErrs] = useState<Record<string, string | null>>({});

  if (!open.length) return <Notice tone="info" title="No forecast is waiting for an outcome.">Request a forecast first. An outcome can be entered once the 120-minute window after the meal has closed.</Notice>;
  const windowEnd = chosen ? addMinutesIso(chosen.meal_time, OUTCOME_WINDOW_MIN) : "";
  const throughValue = through || windowEnd.slice(0, 16);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!chosen) return;
    const p = exclude ? { value: undefined, error: null } : parseNumber(peak, "Observed maximum glucose", 20, 600);
    const w = exclude ? { value: undefined, error: null } : parseNumber(completeness, "Window completeness", 0, 1, false);
    const rt = reason.trim();
    const r = exclude && (rt.length < 3 || rt.length > 200) ? "Give a reason of 3 to 200 characters." : null;
    setErrs({ peak: p.error, comp: w.error, reason: r });
    if (p.error || w.error || r) return;
    await ws.submitObservation({ forecast_id: chosen.forecast_id, observed_through: inputToIso(throughValue),
      ...(exclude ? { excluded_reason: reason.trim() } : { peak_glucose_mg_dl: p.value, ...(w.value !== undefined ? { window_completeness: w.value } : {}) }) });
  };
  return (
    <form className="form" onSubmit={submit} noValidate aria-label="Record an observed outcome">
      <div className="field"><label htmlFor="obs-f">Forecast</label>
        <select id="obs-f" className="input" value={chosen?.forecast_id ?? ""} onChange={(e) => setFid(e.target.value)}>
          {open.map((f) => <option key={f.forecast_id} value={f.forecast_id}>{utcLabel(f.meal_time)} · {f.inputs.carbs_g} g</option>)}
        </select></div>
      <div className="field"><label htmlFor="obs-t">Observed through (UTC)</label>
        <input id="obs-t" type="datetime-local" className="input" value={throughValue} onChange={(e) => setThrough(e.target.value)} />
        <span className="hint">Must be at least {OUTCOME_WINDOW_MIN} minutes after the meal ({utcLabel(windowEnd)}); the backend rejects earlier values.</span></div>
      <label className="check"><input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} /> Exclude this meal (data unusable)</label>
      {exclude ? (
        <Field label="Reason" value={reason} onChange={setReason} error={errs.reason} hint="Excluded meals never update the twin." />
      ) : (<>
        <Field label="Observed maximum glucose in the window" unit="mg/dL" inputMode="decimal" value={peak} onChange={setPeak} error={errs.peak} />
        <Field label="Window completeness" unit="0 to 1" inputMode="decimal" value={completeness} onChange={setCompleteness} error={errs.comp} hint="Fraction of the window with glucose readings. Low completeness is flagged by the backend." />
      </>)}
      <button className="btn primary" type="submit" disabled={ws.busy.observe}>{ws.busy.observe ? "Recording…" : "Record outcome"}</button>
    </form>
  );
}
