import { useState, type ReactNode } from "react";
import { Disclaimer } from "../components/ui/Disclaimer";
import { Pill } from "../components/ui/Status";
import { appHref, type View } from "../lib/router";
import { useWorkspace } from "./workspace";

const NAV: Array<[View, string]> = [["home", "Home"], ["twin", "My Twin"], ["forecast", "Forecast"], ["observations", "Observations"], ["history", "History"], ["insights", "Insights"], ["settings", "Settings"]];

export function Shell({ view, children }: { view: View; children: ReactNode }) {
  const ws = useWorkspace();
  const [open, setOpen] = useState(false);
  const title = NAV.find(([v]) => v === view)?.[1] ?? "";
  return (
    <div className="app">
      <a className="skip" href="#app-main">Skip to content</a>
      <aside className={`side ${open ? "open" : ""}`}>
        <div className="side-top">
          <a className="brand" href="#/" aria-label="GlycoTwin, back to home page"><span className="display">GlycoTwin</span></a>
          <button className="btn small menu-btn" aria-expanded={open} aria-controls="app-nav" onClick={() => setOpen(!open)}>{open ? "Close" : "Menu"}</button>
        </div>
        <nav id="app-nav" aria-label="Workspace">
          <ul>{NAV.map(([v, l]) => <li key={v}><a href={appHref(v)} aria-current={v === view ? "page" : undefined} onClick={() => setOpen(false)}>{l}</a></li>)}</ul>
        </nav>
        <div className="side-foot">
          <p className="eyebrow">Backend</p>
          {ws.health ? <Pill tone={ws.health.status === "ok" ? "ok" : "warn"}>{ws.health.status}</Pill> : ws.healthError ? <Pill tone="err">Unreachable</Pill> : <Pill tone="muted">Checking</Pill>}
          {ws.twin && <p className="small">Active twin<br /><strong>{ws.twin.label}</strong></p>}
          <p className="small demo-note">Demonstration mode: no account. Twins are not private to a user.</p>
        </div>
      </aside>
      <div className="main-col">
        <Disclaimer variant="bar" />
        <main id="app-main" tabIndex={-1}>
          <h1 className="display page-title">{title}</h1>
          {ws.healthError && <div className="notice err" role="alert"><span aria-hidden="true">✕</span><div><strong>Backend not reachable.</strong> {ws.healthError}</div></div>}
          {children}
        </main>
        <div className="sr-only" aria-live="polite" role="status" data-testid="announcer">{ws.announce}</div>
      </div>
    </div>
  );
}
