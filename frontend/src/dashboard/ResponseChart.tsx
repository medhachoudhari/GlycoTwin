import { useId } from "react";
import type { Forecast, ModelForecast } from "../api/types";
import { OUTCOME_THRESHOLD_MG_DL, OUTCOME_WINDOW_MIN } from "../lib/config";
import { densityPath, glucoseDomain, linear, niceTicks, type ChartInput } from "../lib/chartMath";
import { fmt, pct } from "../lib/format";
import { EmptyState } from "../components/ui/Status";

export type ModelChoice = "model_c" | "model_b" | "both";
interface Props {
  forecast: Forecast | null; observedPeak: number | null; observedExcluded?: boolean; models: ModelChoice; busy?: boolean;
}

const W = 960, H = 500, ML = 64, MR = 262, MT = 40, MB = 58;
const PLOT_W = W - ML - MR;
const T0 = -20, T1 = OUTCOME_WINDOW_MIN + 12;

const STYLE = {
  model_c: { color: "var(--coral-d)", mark: "◆", dash: "", name: "Model C (activity-conditioned)" },
  model_b: { color: "var(--ink-2)", mark: "■", dash: "7 5", name: "Model B (no activity term)" },
} as const;

/**
 * The signature view. It draws ONLY quantities the backend returned for this forecast:
 *  - the pre-meal glucose the caller supplied,
 *  - each model's mean rise and 90% predictive interval for the MAXIMUM glucose in (t0, t0+120 min]  (shown as a range across the window: the model does
 *    not say WHEN the maximum happens, so no time curve is drawn),
 *  - the Gaussian predictive distribution described by the reported mean and sd (right panel), with the backend's own P(maximum >= 180),
 *  - the observed maximum, once a real observation exists.
 */
export function ResponseChart({ forecast, observedPeak, observedExcluded, models, busy }: Props) {
  const uid = useId().replace(/:/g, "");
  if (!forecast) {
    return (
      <div className="chart-wrap">
        <EmptyState title={busy ? "Requesting a forecast…" : "No forecast to draw yet"}>
          {busy ? "The backend is computing the posterior-predictive distribution for this meal."
            : "Enter a meal (carbohydrate, pre-meal activity and glucose) and request a forecast. The chart shows only what the backend returns: nothing is drawn from placeholder values."}
        </EmptyState>
      </div>
    );
  }
  const base = forecast.inputs.baseline_glucose;
  const shown = (models === "both" ? ["model_b", "model_c"] : [models]) as Array<"model_b" | "model_c">;
  const input: ChartInput = {
    baseline: base, observedPeak,
    models: shown.map((k) => { const m: ModelForecast = forecast[k]; return { key: k, mean: m.mean_rise_mg_dl, sd: m.sd_mg_dl, lo: m.interval90_rise_mg_dl[0], hi: m.interval90_rise_mg_dl[1], p: m.p_peak_at_least_180 }; }),
  };
  const [g0, g1] = glucoseDomain(input, OUTCOME_THRESHOLD_MG_DL);
  const x = linear([T0, T1], [ML, ML + PLOT_W]);
  const y = linear([g0, g1], [H - MB, MT]);
  const yTicks = niceTicks(g0, g1, 7);
  const xTicks = [0, 30, 60, 90, 120];
  const dens0 = ML + PLOT_W + 22, densW = MR - 56;
  const xWin0 = x(0), xWin1 = x(OUTCOME_WINDOW_MIN);

  return (
    <figure className="chart-wrap" aria-labelledby={`${uid}-cap`}>
      <svg className={`rchart reveal`} key={forecast.forecast_id} viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`${uid}-cap ${uid}-desc`}>
        <title id={`${uid}-cap`}>Forecast of the post-meal glucose maximum</title>
        <desc id={`${uid}-desc`}>
          Pre-meal glucose {fmt(base, 0)} mg/dL. {shown.map((k) => `${STYLE[k].name}: expected maximum ${fmt(base + forecast[k].mean_rise_mg_dl, 0)} mg/dL, 90% interval ${fmt(base + forecast[k].interval90_rise_mg_dl[0], 0)} to ${fmt(base + forecast[k].interval90_rise_mg_dl[1], 0)}, probability of reaching 180 mg/dL ${pct(forecast[k].p_peak_at_least_180)}.`).join(" ")}
          {observedPeak !== null ? ` Observed maximum ${fmt(observedPeak, 0)} mg/dL.` : observedExcluded ? " Outcome excluded." : " No observation yet."}
        </desc>
        <defs>
          <pattern id={`hatchC-${uid}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="rgba(226,85,59,.07)" /><line x1="0" y1="0" x2="0" y2="7" stroke="rgba(184,61,39,.55)" strokeWidth="1.6" /></pattern>
          <pattern id={`dotB-${uid}`} width="7" height="7" patternUnits="userSpaceOnUse"><rect width="7" height="7" fill="rgba(43,48,34,.05)" /><circle cx="3.5" cy="3.5" r="1.1" fill="rgba(43,48,34,.55)" /></pattern>
          <clipPath id={`above-${uid}`}><rect x={dens0} y={MT - 6} width={densW + 30} height={y(OUTCOME_THRESHOLD_MG_DL) - MT + 6} /></clipPath>
        </defs>

        {/* grid + axes */}
        <g className="grid">{yTicks.map((t) => <g key={t}><line x1={ML} x2={ML + PLOT_W} y1={y(t)} y2={y(t)} /><text x={ML - 10} y={y(t) + 4} textAnchor="end">{t}</text></g>)}</g>
        <text className="axis-title" transform={`translate(16 ${(MT + H - MB) / 2}) rotate(-90)`} textAnchor="middle">glucose (mg/dL)</text>
        <rect className="win" x={xWin0} y={MT} width={xWin1 - xWin0} height={H - MB - MT} />
        <g className="xaxis">{xTicks.map((t) => <g key={t}><line x1={x(t)} x2={x(t)} y1={H - MB} y2={H - MB + 6} /><text x={x(t)} y={H - MB + 22} textAnchor="middle">{t}</text></g>)}
          <line x1={ML} x2={ML + PLOT_W} y1={H - MB} y2={H - MB} /></g>
        <text className="axis-title" x={(xWin0 + xWin1) / 2} y={H - 10} textAnchor="middle">minutes after the meal (t0) · outcome window (t0, t0 + 120 min]</text>

        {/* meal marker, baseline */}
        <line className="meal" x1={x(0)} x2={x(0)} y1={MT - 14} y2={H - MB} />
        <text className="meal-label" x={x(0)} y={MT - 20} textAnchor="middle">meal · t0</text>
        <line className="baseline-pre" x1={x(T0)} x2={x(0)} y1={y(base)} y2={y(base)} />
        <line className="baseline-ref" x1={x(0)} x2={xWin1} y1={y(base)} y2={y(base)} />
        <circle cx={x(0)} cy={y(base)} r="4.5" className="baseline-dot" />
        <text className="note" x={x(0) - 8} y={y(base) - 8} textAnchor="end">pre-meal {fmt(base, 0)}</text>

        {/* forecast bands + means (revealed left to right) */}
        <g className="fc-reveal">
          {shown.map((k) => {
            const m = forecast[k], s = STYLE[k], lo = base + m.interval90_rise_mg_dl[0], hi = base + m.interval90_rise_mg_dl[1], mean = base + m.mean_rise_mg_dl;
            return (
              <g key={k} tabIndex={0} aria-label={`${s.name}: expected maximum ${fmt(mean, 0)} mg/dL, 90% interval ${fmt(lo, 0)} to ${fmt(hi, 0)}`}>
                <rect x={xWin0} y={y(hi)} width={xWin1 - xWin0} height={Math.max(1, y(lo) - y(hi))} fill={`url(#${k === "model_c" ? "hatchC" : "dotB"}-${uid})`} stroke={s.color} strokeOpacity=".5" strokeDasharray={s.dash || undefined} />
                <line x1={xWin0} x2={xWin1} y1={y(mean)} y2={y(mean)} stroke={s.color} strokeWidth="2.4" strokeDasharray={s.dash || undefined} />
                <text className="mark-label" x={xWin0 + 8} y={MT + 18 + shown.indexOf(k) * 18} fill={s.color}>{s.mark} {k === "model_c" ? "C" : "B"} · expected max {fmt(mean, 0)} · 90% {fmt(lo, 0)}–{fmt(hi, 0)}</text>
              </g>
            );
          })}
        </g>

        {/* threshold */}
        <line className="thr" x1={ML} x2={ML + PLOT_W} y1={y(OUTCOME_THRESHOLD_MG_DL)} y2={y(OUTCOME_THRESHOLD_MG_DL)} />
        <text className="thr-label" x={ML + PLOT_W - 6} y={y(OUTCOME_THRESHOLD_MG_DL) - 7} textAnchor="end">{OUTCOME_THRESHOLD_MG_DL} mg/dL outcome threshold</text>

        {/* observed */}
        {observedPeak !== null && (
          <g className="obs" tabIndex={0} aria-label={`Observed maximum ${fmt(observedPeak, 0)} mg/dL`}>
            <line x1={xWin0} x2={xWin1} y1={y(observedPeak)} y2={y(observedPeak)} />
            <circle cx={xWin1} cy={y(observedPeak)} r="6.5" />
            <text x={xWin1 - 10} y={y(observedPeak) + 20} textAnchor="end">● observed max {fmt(observedPeak, 0)}</text>
          </g>
        )}
        {observedExcluded && <text className="note" x={xWin0 + 8} y={H - MB - 12}>▲ outcome excluded (sensor data not trusted): no observed value</text>}

        {/* right panel: Gaussian predictive distribution of the window maximum */}
        <text className="panel-title" x={dens0} y={MT - 14}>distribution of the max</text>
        <line className="dens-axis" x1={dens0} x2={dens0} y1={MT} y2={H - MB} />
        {shown.map((k) => {
          const m = forecast[k], s = STYLE[k], d = densityPath(base + m.mean_rise_mg_dl, m.sd_mg_dl, y, dens0, densW);
          return (
            <g key={k} className="dens">
              <path d={d.area} fill={s.color} opacity=".13" />
              <path d={d.area} fill={s.color} opacity=".34" clipPath={`url(#above-${uid})`} />
              <path d={d.line} fill="none" stroke={s.color} strokeWidth="1.8" strokeDasharray={s.dash || undefined} />
            </g>
          );
        })}
        <line className="thr dens-thr" x1={dens0} x2={dens0 + densW + 30} y1={y(OUTCOME_THRESHOLD_MG_DL)} y2={y(OUTCOME_THRESHOLD_MG_DL)} />
        {shown.map((k, i) => (
          <text key={k} className="mark-label" x={dens0 + 8} y={MT + 14 + i * 16} fill={STYLE[k].color}>{STYLE[k].mark} P(max ≥ 180) = {pct(forecast[k].p_peak_at_least_180, 1)}</text>
        ))}
        {observedPeak !== null && <circle cx={dens0} cy={y(observedPeak)} r="5" className="obs-dot" />}
      </svg>
      <figcaption>
        <ul className="legend" aria-label="Legend">
          {shown.map((k) => <li key={k}><span style={{ color: STYLE[k].color }} aria-hidden="true">{STYLE[k].mark}</span> {STYLE[k].name}: hatched/dotted band = 90% predictive interval of the window maximum; line = expected maximum</li>)}
          <li><span style={{ color: "var(--role-observed)" }} aria-hidden="true">●</span> observed maximum (real observation only)</li>
          <li><span aria-hidden="true">┈</span> 180 mg/dL outcome threshold · shaded tail = probability of reaching it</li>
        </ul>
        <p className="chart-note">
          Forecast from twin version <span className="mono">v{forecast.twin_version_at_forecast}</span> · {forecast.model_version}. The interval describes the <em>maximum</em> over the window; the model does not predict when it occurs, so no time course is drawn.
          Experimental research output, not a clinical prediction.
        </p>
      </figcaption>
    </figure>
  );
}
