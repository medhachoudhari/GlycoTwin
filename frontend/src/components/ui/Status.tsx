import type { ReactNode } from "react";
import type { ForecastStatus } from "../../api/types";

export type Tone = "forecast" | "observed" | "ok" | "warn" | "err" | "muted" | "unc";
const MARK: Record<Tone, string> = { forecast: "◆", observed: "●", ok: "✓", warn: "▲", err: "✕", muted: "○", unc: "▒" };

/** Status is always label + symbol + colour, never colour alone. */
export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`pill ${tone}`}><span aria-hidden="true">{MARK[tone]}</span>{children}</span>;
}

export function ForecastStatusPill({ status }: { status: ForecastStatus }) {
  switch (status) {
    case "pending": return <Pill tone="forecast">Forecast · awaiting outcome</Pill>;
    case "observed": return <Pill tone="observed">Observed · not yet applied</Pill>;
    case "reconciled": return <Pill tone="ok">Reconciled · twin updated</Pill>;
    case "excluded": return <Pill tone="warn">Excluded · no update</Pill>;
  }
}

export function Notice({ tone, title, children }: { tone: "err" | "warn" | "ok" | "info"; title?: string; children: ReactNode }) {
  const role = tone === "err" ? "alert" : "status";
  return (
    <div className={`notice ${tone}`} role={role}>
      <span aria-hidden="true">{{ err: "✕", warn: "▲", ok: "✓", info: "i" }[tone]}</span>
      <div>{title && <strong>{title}</strong>}{children}</div>
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return <span role="status" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><span className="spinner" aria-hidden="true" />{label}</span>;
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty" role="status">
      <svg width="54" height="54" viewBox="0 0 54 54" aria-hidden="true"><path d="M4 36c8-22 14 10 22-4s12-12 24-8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 4" strokeLinecap="round" /><circle cx="42" cy="24" r="3" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
      <div><h3>{title}</h3><p>{children}</p>{action && <div className="empty-action">{action}</div>}</div>
    </div>
  );
}
