import { useEffect, useRef } from "react";
import { usePrefersReducedMotion } from "../../lib/router";
import { mulberry32 } from "../../lib/organic";

const DEFAULT_PALETTE = ["#c99a3b", "#8da184", "#e2553b", "#f4efe3"];
interface Props { palette?: string[]; rows?: number; density?: number; className?: string; height?: number }

/**
 * Generative particle wave on a small canvas. Deliberately light: capped particle count, device-pixel-ratio capped at 2, paused when off screen or the
 * tab is hidden, and a single static frame when the user prefers reduced motion. Decorative only (aria-hidden); it encodes no data.
 */
export function ParticleWave({ palette = DEFAULT_PALETTE, rows = 7, density = 5, className = "", height = 240 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const reduce = usePrefersReducedMotion();

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let raf = 0, visible = true, w = 0, h = 0;
    const rnd = mulberry32(2026);
    const seeds = Array.from({ length: 4000 }, () => ({ u: rnd(), v: rnd(), s: rnd() }));
    const resize = () => {
      const r = canvas.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1);
      w = Math.max(1, Math.floor(r.width)); h = Math.max(1, Math.floor(r.height));
      canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      const count = Math.min(seeds.length, Math.floor((w / density) * rows));
      for (let i = 0; i < count; i++) {
        const p = seeds[i], row = i % rows, x = ((i / rows) * density) % w;
        const phase = row * 0.55 + x * 0.011 + t * 0.00045 * (0.6 + p.s * 0.8);
        const y = h * (0.18 + 0.64 * (row / (rows - 1))) + Math.sin(phase) * h * 0.13 + Math.sin(phase * 2.3 + p.u * 6) * h * 0.04 + (p.v - 0.5) * 7;
        ctx.globalAlpha = 0.25 + 0.6 * p.s;
        ctx.fillStyle = palette[i % palette.length];
        ctx.beginPath(); ctx.arc(x, y, 0.7 + p.s * 1.5, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
    };
    const loop = (t: number) => { if (visible && !document.hidden) draw(t); raf = requestAnimationFrame(loop); };
    resize();
    draw(3000);
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; });
    io.observe(canvas);
    const ro = new ResizeObserver(() => { resize(); draw(3000); });
    ro.observe(canvas);
    if (!reduce) raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); io.disconnect(); ro.disconnect(); };
  }, [reduce, palette, rows, density]);

  return <canvas ref={ref} className={`particles ${className}`} style={{ width: "100%", height }} aria-hidden="true" />;
}
