/** Geometry helpers for the response chart. Nothing here estimates a clinical quantity: it only maps numbers the backend returned onto pixels. */

export interface Scale { (v: number): number; domain: [number, number]; range: [number, number] }
export function linear(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain, [r0, r1] = range;
  const f = ((v: number) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0)) as Scale;
  f.domain = domain; f.range = range;
  return f;
}

/** Tick values at "nice" multiples that fit [lo, hi]. */
export function niceTicks(lo: number, hi: number, target = 6): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / target, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.round(v * 1e6) / 1e6);
  return out;
}

/** Density of the Gaussian predictive distribution the backend describes by (mean, sd). Used only to DRAW that stated distribution. */
export const normalPdf = (x: number, mean: number, sd: number): number => Math.exp(-0.5 * ((x - mean) / sd) ** 2) / (sd * Math.sqrt(2 * Math.PI));

export interface ChartInput {
  baseline: number;
  models: Array<{ key: "model_b" | "model_c"; mean: number; sd: number; lo: number; hi: number; p: number }>;
  observedPeak: number | null;
}
/** Glucose axis that always contains the threshold, baseline, every interval and the observed value, with padding. */
export function glucoseDomain(c: ChartInput, threshold: number): [number, number] {
  const vals = [threshold, c.baseline, ...c.models.flatMap((m) => [c.baseline + m.lo, c.baseline + m.hi]), ...(c.observedPeak !== null ? [c.observedPeak] : [])];
  const lo = Math.min(...vals), hi = Math.max(...vals), pad = Math.max(12, (hi - lo) * 0.12);
  return [Math.floor((lo - pad) / 10) * 10, Math.ceil((hi + pad) / 10) * 10];
}

export function densityPath(mean: number, sd: number, y: Scale, x0: number, maxWidth: number, steps = 80): { line: string; area: string; peak: number } {
  const [g0, g1] = y.domain;
  const pts: Array<[number, number]> = [];
  const peak = normalPdf(mean, mean, sd);
  for (let i = 0; i <= steps; i++) {
    const g = g0 + ((g1 - g0) * i) / steps;
    pts.push([x0 + (normalPdf(g, mean, sd) / peak) * maxWidth, y(g)]);
  }
  const line = pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
  return { line, area: `${line}L${x0},${y(g1).toFixed(1)}L${x0},${y(g0).toFixed(1)}Z`, peak };
}
