/** Deterministic generators for the organic artwork (no Math.random: the picture is identical on every load and in tests). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Closed smooth blob around (cx, cy): radius r perturbed by `wobble` (0..1) at `lobes` angular frequencies. Catmull-Rom -> cubic Bézier. */
export function blobPath(cx: number, cy: number, r: number, seed: number, wobble = 0.22, lobes = 7): string {
  const rnd = mulberry32(seed), n = lobes * 2;
  const pts: Array<[number, number]> = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2, rr = r * (1 + (rnd() - 0.5) * 2 * wobble);
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]);
  }
  const p = (i: number) => pts[(i + n) % n];
  let d = `M${p(0)[0].toFixed(1)},${p(0)[1].toFixed(1)}`;
  for (let i = 0; i < n; i++) {
    const [p0, p1, p2, p3] = [p(i - 1), p(i), p(i + 1), p(i + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return `${d}Z`;
}

/** A flowing open ribbon across [x0, x1] with a few smooth undulations: the abstract "metabolic journey" line. */
export function ribbonPath(x0: number, x1: number, y: number, amp: number, seed: number, waves = 3): string {
  const rnd = mulberry32(seed), pts: Array<[number, number]> = [];
  const n = waves * 4 + 1;
  for (let i = 0; i < n; i++) pts.push([x0 + ((x1 - x0) * i) / (n - 1), y + Math.sin((i / (n - 1)) * waves * Math.PI * 2) * amp * (0.6 + rnd() * 0.7)]);
  let d = `M${pts[0][0]},${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const [px, py] = pts[i - 1], [cx, cy] = pts[i], mx = (px + cx) / 2;
    d += `C${mx.toFixed(1)},${py.toFixed(1)} ${mx.toFixed(1)},${cy.toFixed(1)} ${cx.toFixed(1)},${cy.toFixed(1)}`;
  }
  return d;
}
