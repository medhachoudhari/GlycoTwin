import { useId } from "react";
import { blobPath, ribbonPath } from "../../lib/organic";

/**
 * Original sculptural artwork for the hero: stacked translucent "cellular" lobes, contour lines and one flowing ribbon.
 * Pure SVG + CSS transforms (cheap, scalable, no external assets). Purely decorative: aria-hidden, no data is implied by its shapes.
 */
export function OrganicForm({ className = "" }: { className?: string }) {
  const uid = useId().replace(/:/g, "");
  const lobes = [
    { r: 250, seed: 11, c: `url(#g1-${uid})`, o: 0.9, cls: "drift-a" },
    { r: 210, seed: 23, c: `url(#g2-${uid})`, o: 0.78, cls: "drift-b" },
    { r: 160, seed: 37, c: `url(#g3-${uid})`, o: 0.82, cls: "drift-c" },
    { r: 104, seed: 53, c: `url(#g4-${uid})`, o: 0.9, cls: "drift-a" },
  ];
  const contours = [290, 322, 354, 386, 418].map((r, i) => blobPath(450, 420, r, 70 + i * 3, 0.1 + i * 0.012, 6));
  return (
    <svg className={`organic ${className}`} viewBox="0 0 900 820" role="presentation" aria-hidden="true" focusable="false">
      <defs>
        <radialGradient id={`g1-${uid}`} cx="35%" cy="30%"><stop offset="0" stopColor="#c9d4b9" /><stop offset=".6" stopColor="#8da184" /><stop offset="1" stopColor="#5c6b3a" /></radialGradient>
        <radialGradient id={`g2-${uid}`} cx="60%" cy="35%"><stop offset="0" stopColor="#f2dfa6" /><stop offset=".55" stopColor="#c99a3b" /><stop offset="1" stopColor="#8a6a1a" /></radialGradient>
        <radialGradient id={`g3-${uid}`} cx="40%" cy="40%"><stop offset="0" stopColor="#d7e3cf" /><stop offset=".6" stopColor="#6d8264" /><stop offset="1" stopColor="#2e3a22" /></radialGradient>
        <radialGradient id={`g4-${uid}`} cx="45%" cy="35%"><stop offset="0" stopColor="#fff1c9" /><stop offset=".5" stopColor="#d98b2b" /><stop offset="1" stopColor="#e2553b" /></radialGradient>
        <linearGradient id={`rb-${uid}`} x1="0" x2="1"><stop offset="0" stopColor="currentColor" stopOpacity="0" /><stop offset=".25" stopColor="currentColor" /><stop offset=".7" stopColor="#e2553b" /><stop offset="1" stopColor="#e2553b" stopOpacity="0" /></linearGradient>
        <filter id={`soft-${uid}`} x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="14" /></filter>
      </defs>
      <g fill="none" stroke="currentColor" strokeOpacity=".22" strokeWidth="1">{contours.map((d, i) => <path key={i} d={d} />)}</g>
      <ellipse cx="450" cy="760" rx="260" ry="26" fill="currentColor" opacity=".16" filter={`url(#soft-${uid})`} />
      <g style={{ transformOrigin: "450px 420px" }}>
        {lobes.map((l, i) => (
          <g key={i} className={l.cls} style={{ transformOrigin: "450px 420px" }}>
            <path d={blobPath(450, 420, l.r, l.seed, 0.2, 7)} fill={l.c} opacity={l.o} />
            <path d={blobPath(450, 420, l.r, l.seed, 0.2, 7)} fill="none" stroke="#fbf9f3" strokeOpacity=".5" strokeWidth="1.2" />
          </g>
        ))}
      </g>
      <g className="drift-b" style={{ transformOrigin: "450px 420px" }}>
        {[0, 1, 2, 3, 4, 5].map((i) => <circle key={i} cx={450 + Math.cos(i * 1.05) * 58} cy={420 + Math.sin(i * 1.05) * 58} r={5 + (i % 3) * 3} fill="#fbf9f3" opacity={0.55 - i * 0.05} />)}
      </g>
      <path className="ribbon" d={ribbonPath(20, 880, 420, 70, 5, 2)} fill="none" stroke={`url(#rb-${uid})`} strokeWidth="3.2" strokeLinecap="round" />
      <path className="ribbon ribbon-2" d={ribbonPath(60, 860, 468, 52, 9, 2)} fill="none" stroke="currentColor" strokeOpacity=".5" strokeWidth="1.2" strokeDasharray="2 7" strokeLinecap="round" />
    </svg>
  );
}
