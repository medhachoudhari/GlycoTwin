"""Dependency-free reliability (calibration) diagram as SVG, from AGGREGATE bin data only (counts, mean predicted, mean observed).

No participant identifiers, timestamps or per-event values are involved, so the output is safe to share like any other aggregate summary.
Model series use different marker shapes and line styles as well as colours, so the chart does not rely on colour alone.
"""

from __future__ import annotations

from typing import Dict, List
from xml.sax.saxutils import escape

import numpy as np

from glycotwin.models.evaluation import expected_calibration_error

_STYLES = [("#1b6ca8", "circle", ""), ("#c4511f", "square", "6 3"), ("#4a7c3a", "diamond", "2 3")]


def reliability_bins(y, p, n_bins: int = 10) -> List[dict]:
    """Equal-width reliability bins of pooled predictions: [{lower, upper, n, mean_predicted, mean_observed}] (empty bins keep n = 0)."""
    _ece, bins = expected_calibration_error(np.asarray(y, dtype=int), np.asarray(p, dtype=float), n_bins)
    return [{"lower": b.bin_lower, "upper": b.bin_upper, "n": b.n_samples, "mean_predicted": b.mean_predicted, "mean_observed": b.mean_observed} for b in bins]


def _marker(shape: str, x: float, y: float, r: float, colour: str) -> str:
    if shape == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{colour}" fill-opacity="0.85" stroke="white" stroke-width="1"/>'
    if shape == "square":
        return f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" fill="{colour}" fill-opacity="0.85" stroke="white" stroke-width="1"/>'
    return (f'<polygon points="{x:.1f},{y - r:.1f} {x + r:.1f},{y:.1f} {x:.1f},{y + r:.1f} {x - r:.1f},{y:.1f}" fill="{colour}" '
            f'fill-opacity="0.85" stroke="white" stroke-width="1"/>')


def reliability_svg(series: Dict[str, List[dict]], title: str = "Reliability diagram", subtitle: str = "") -> str:
    """One SVG document. `series` maps a model name to its bins (from `reliability_bins`). Marker area grows with the bin's event count."""
    W = H = 520
    L, R, T, B = 70, 20, 60, 70
    pw, ph = W - L - R, H - T - B
    px = lambda v: L + v * pw
    py = lambda v: T + (1 - v) * ph
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d" font-family="sans-serif" font-size="12">',
           f'<title id="t">{escape(title)}</title>',
           f'<desc id="d">Observed frequency against mean predicted probability for {", ".join(escape(k) for k in series)}; the diagonal is perfect calibration. {escape(subtitle)}</desc>',
           f'<rect width="{W}" height="{H}" fill="white"/>',
           f'<text x="{W / 2}" y="24" text-anchor="middle" font-size="15" font-weight="bold">{escape(title)}</text>']
    if subtitle:
        out.append(f'<text x="{W / 2}" y="42" text-anchor="middle" fill="#444">{escape(subtitle)}</text>')
    for k in range(6):
        v = k / 5
        out.append(f'<line x1="{px(v):.1f}" y1="{py(0):.1f}" x2="{px(v):.1f}" y2="{py(1):.1f}" stroke="#e5e5e5"/>')
        out.append(f'<line x1="{px(0):.1f}" y1="{py(v):.1f}" x2="{px(1):.1f}" y2="{py(v):.1f}" stroke="#e5e5e5"/>')
        out.append(f'<text x="{px(v):.1f}" y="{py(0) + 16:.1f}" text-anchor="middle">{v:.1f}</text>')
        out.append(f'<text x="{px(0) - 8:.1f}" y="{py(v) + 4:.1f}" text-anchor="end">{v:.1f}</text>')
    out.append(f'<rect x="{px(0)}" y="{py(1)}" width="{pw}" height="{ph}" fill="none" stroke="#333"/>')
    out.append(f'<line x1="{px(0):.1f}" y1="{py(0):.1f}" x2="{px(1):.1f}" y2="{py(1):.1f}" stroke="#888" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{px(0.5):.1f}" y="{H - 28}" text-anchor="middle">Mean predicted probability</text>')
    out.append(f'<text transform="translate(18 {py(0.5):.1f}) rotate(-90)" text-anchor="middle">Observed frequency</text>')
    nmax = max([b["n"] for bins in series.values() for b in bins] + [1])
    for i, (name, bins) in enumerate(series.items()):
        colour, shape, dash = _STYLES[i % len(_STYLES)]
        pts = [(b["mean_predicted"], b["mean_observed"], b["n"]) for b in bins if b["n"] > 0 and b["mean_predicted"] is not None]
        if len(pts) > 1:
            d = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y, _ in pts)
            out.append(f'<polyline points="{d}" fill="none" stroke="{colour}" stroke-width="1.5"' + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")
        for x, y, n in pts:
            out.append(_marker(shape, px(x), py(y), 3 + 6 * np.sqrt(n / nmax), colour))
        ly = T + 14 + 18 * i
        out.append(_marker(shape, L + 12, ly, 5, colour))
        out.append(f'<text x="{L + 24}" y="{ly + 4}">{escape(name)}</text>')
    out.append(f'<text x="{W - R}" y="{H - 8}" text-anchor="end" fill="#555" font-size="10">Marker size = events in the bin. Aggregate bins only. Research prototype; not clinically validated.</text>')
    out.append("</svg>")
    return "\n".join(out)
