import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Health } from "../api/types";
import { OrganicForm } from "../components/organic/OrganicForm";
import { ParticleWave } from "../components/organic/ParticleWave";
import { Disclaimer } from "../components/ui/Disclaimer";
import { appHref } from "../lib/router";

const REPO = "https://github.com/medhachoudhari/GlycoTwin";
const DOCS = `${REPO}/tree/claude/glycotwin-initial-scaffold-gegpzd/docs`;

const NAV: Array<[string, string]> = [["Product", "#/product"], ["Research", "#/research"], ["How it works", "#/how"], ["Documentation", "#/docs"]];

function useHealth() {
  const [state, setState] = useState<{ kind: "loading" } | { kind: "ok"; h: Health } | { kind: "offline" }>({ kind: "loading" });
  useEffect(() => {
    const ac = new AbortController();
    api.health(ac.signal).then((h) => setState({ kind: "ok", h })).catch((e) => { if ((e as Error).name !== "AbortError") setState({ kind: "offline" }); });
    return () => ac.abort();
  }, []);
  return state;
}

export function Landing({ section }: { section?: string }) {
  const [open, setOpen] = useState(false);
  const health = useHealth();

  useEffect(() => {
    if (section) document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" });
    else window.scrollTo({ top: 0 });
  }, [section]);

  return (
    <div className="landing">
      <a className="skip" href="#main">Skip to content</a>
      <header className="l-nav">
        <a className="brand" href="#/" aria-label="GlycoTwin home">
          <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#14170f" /><path d="M5 19c4-9 8 5 11-3s6-6 11-3" fill="none" stroke="#d9a441" strokeWidth="2.4" strokeLinecap="round" /><circle cx="23" cy="13" r="2.2" fill="#e8573d" /></svg>
          <span className="display">GlycoTwin</span>
        </a>
        <button className="menu-btn" aria-expanded={open} aria-controls="l-links" onClick={() => setOpen((o) => !o)}>{open ? "Close" : "Menu"}</button>
        <nav id="l-links" className={open ? "open" : ""} aria-label="Primary">
          {NAV.map(([label, href]) => <a key={href} href={href} onClick={() => setOpen(false)}>{label}</a>)}
          <a className="btn primary sm" href={appHref("home")}>Launch App</a>
        </nav>
      </header>

      <main id="main">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow">Living intelligence · research prototype</p>
            <h1 id="hero-title" className="display">Your metabolism has a <em>story.</em> Let’s model&nbsp;it.</h1>
            <p className="lede">
              GlycoTwin explores personalised post-meal glucose responses. It learns from real continuous-glucose, meal and activity data with Bayesian updating,
              forecasts the next meal with its uncertainty, then checks the forecast against what was observed.
            </p>
            <div className="cta">
              <a className="btn primary" href={appHref("home")}>Open the application</a>
              <a className="btn" href="#/research">Explore the research</a>
            </div>
            <dl className="meta" aria-label="Project metadata">
              <div><dt>Model family</dt><dd>Bayesian linear · Models B and C</dd></div>
              <div><dt>Engine</dt><dd className="mono">{health.kind === "ok" ? `v${health.h.engine.package_version ?? "dev"} · ${health.h.engine.git_commit?.slice(0, 7) ?? "n/a"}` : health.kind === "loading" ? "checking backend…" : "backend offline"}</dd></div>
              <div><dt>Backend</dt><dd>{health.kind === "ok" ? (health.h.status === "ok" ? "online · database ok" : "degraded") : health.kind === "loading" ? "checking…" : "not running"}</dd></div>
            </dl>
          </div>
          <div className="hero-art" aria-hidden="true">
            <OrganicForm />
            <span className="note n1"><b>01 Forecast</b>a probability and a 90% interval before the outcome is known</span>
            <span className="note n2"><b>02 Observe</b>the maximum glucose in the two hours after the meal</span>
            <span className="note n3"><b>03 Update</b>a new, versioned twin state: nothing is overwritten</span>
          </div>
        </section>

        <section id="product" className="product" aria-labelledby="product-title">
          <div className="sec-head"><p className="eyebrow">The product</p><h2 id="product-title" className="display">A twin that keeps its history.</h2></div>
          <div className="product-grid">
            <article><h3>Personal, not population-average</h3><p>Each twin holds a posterior over how strongly <em>this person’s</em> glucose rises per gram of carbohydrate, and how activity before the meal shifts it.</p></article>
            <article><h3>Honest about what it does not know</h3><p>Every forecast carries the model’s own uncertainty. Data-quality and short-history warnings are shown, never hidden, and never used to invent a wider band.</p></article>
            <article><h3>Auditable</h3><p>Every update creates a new version linked to the observation that caused it. Excluded observations leave the twin untouched. Repeating a request never double-counts.</p></article>
          </div>
        </section>

        <section id="how" className="how on-dark" aria-labelledby="how-title">
          <ParticleWave className="how-wave" height={300} />
          <div className="how-inner">
            <div className="sec-head"><p className="eyebrow">How it works</p><h2 id="how-title" className="display">From real data to a living model.</h2></div>
            <ol className="flow">
              <li><span className="mono">01</span><h3>Real data</h3><p>Continuous glucose, meals and wearable activity from the CGMacros research dataset. The data stays on the researcher’s machine; this app never loads it.</p></li>
              <li><span className="mono">02</span><h3>Model</h3><p>Rise = (β + γ · activity) × carbohydrate. β and γ are learned per person from a population prior fitted on training participants only.</p></li>
              <li><span className="mono">03</span><h3>Forecast</h3><p>The probability that the glucose maximum in the next two hours reaches 180&nbsp;mg/dL, with a 90% predictive interval.</p></li>
              <li><span className="mono">04</span><h3>Observation</h3><p>Once the two-hour window has closed, the observed maximum is recorded. If the sensor data are not trustworthy, the meal is excluded.</p></li>
              <li><span className="mono">05</span><h3>Update</h3><p>A closed-form Bayesian update writes a new twin version. The posterior narrows as evidence accumulates.</p></li>
            </ol>
            <p className="eq mono" aria-label="Model equation">rise = (β<sub>i</sub> + γ<sub>i</sub>·a<sub>i</sub>) · c<sub>i</sub> + ε<sub>i</sub></p>
          </div>
        </section>

        <section id="research" className="research" aria-labelledby="research-title">
          <div className="sec-head"><p className="eyebrow">Research</p><h2 id="research-title" className="display">What is established, and what is not.</h2></div>
          <div className="research-grid">
            <div>
              <h3>Hypothesis</h3>
              <p>Conditioning a person’s carbohydrate sensitivity on their recent activity (Model C) might improve calibration over an otherwise identical personalised model without activity (Model B).</p>
              <h3>Evidence so far</h3>
              <p>A first matched comparison on 963 meals from 34 participants was <strong>inconclusive</strong>: nearly every paired interval contained zero, and calibration did not improve. No claim of superiority is made. Further analyses are pre-specified and pending.</p>
            </div>
            <div>
              <h3>Limitations</h3>
              <ul>
                <li>Small cohort and short recordings; one dataset.</li>
                <li>Self-reported macronutrients; wrist-device activity.</li>
                <li>The outcome is a lower bound: the maximum <em>observed</em> glucose.</li>
                <li>Gaussian, constant-variance rise model; known noise variance.</li>
                <li>The activity coefficient may be weakly identified.</li>
                <li>Not clinically validated. Not a diagnostic or dosing tool.</li>
              </ul>
            </div>
          </div>
        </section>

        <section id="docs" className="docs" aria-labelledby="docs-title">
          <div className="sec-head"><p className="eyebrow">Documentation</p><h2 id="docs-title" className="display">Read the method.</h2></div>
          <ul className="doc-links">
            <li><a href={`${DOCS}/model_b_vs_c_report.md`} rel="noreferrer noopener" target="_blank">Model B vs Model C report</a><span>results and limitations</span></li>
            <li><a href={`${DOCS}/BACKEND.md`} rel="noreferrer noopener" target="_blank">Backend architecture</a><span>lifecycle, tables, guarantees</span></li>
            <li><a href={`${DOCS}/REAL_DATA_RUNBOOK.md`} rel="noreferrer noopener" target="_blank">Real-data runbook</a><span>reproducible protocol</span></li>
            <li><a href={`${DOCS}/BLUEPRINT_CONFORMANCE.md`} rel="noreferrer noopener" target="_blank">Blueprint conformance</a><span>implemented vs pending</span></li>
          </ul>
        </section>
      </main>

      <footer className="l-foot">
        <div><a className="brand" href="#/"><span className="display">GlycoTwin</span></a><a href={REPO} rel="noreferrer noopener" target="_blank">Source repository</a></div>
        <Disclaimer variant="block" />
      </footer>
    </div>
  );
}
