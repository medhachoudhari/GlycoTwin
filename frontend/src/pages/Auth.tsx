import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { OrganicForm } from "../components/organic/OrganicForm";
import { Disclaimer } from "../components/ui/Disclaimer";
import { appHref, type AuthMode } from "../lib/router";

/**
 * Sign In and Create Account screens (visual design of the approved concept).
 *
 * IMPORTANT, and stated on screen: the backend has NO authentication (no users, passwords, sessions or per-user data ownership; see docs/BACKEND.md "Not included").
 * These forms therefore validate input locally and then say plainly that sign-in / account creation is not available. They send nothing over the network,
 * never show a signed-in or account-created state, and the demonstration path opens the existing workspace without pretending to authenticate anyone.
 */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export interface AuthErrors { name?: string; email?: string; password?: string; confirm?: string; ack?: string }
export function validateAuth(mode: AuthMode, v: { name: string; email: string; password: string; confirm: string; ack: boolean }): AuthErrors {
  const e: AuthErrors = {};
  if (mode === "register" && !v.name.trim()) e.name = "Enter your name.";
  if (!v.email.trim()) e.email = "Enter your email address.";
  else if (!EMAIL.test(v.email.trim())) e.email = "Enter a valid email address, such as name@example.com.";
  if (!v.password) e.password = mode === "login" ? "Enter your password." : "Choose a password.";
  if (mode === "register") {
    if (!v.confirm) e.confirm = "Confirm your password.";
    else if (v.confirm !== v.password) e.confirm = "The two passwords do not match.";
    if (!v.ack) e.ack = "Please acknowledge that GlycoTwin is a research prototype.";
  }
  return e;
}

const Icon = ({ d }: { d: string }) => (
  <svg className="f-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const ICON = {
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  mail: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zm0 1 8 6 8-6",
  lock: "M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1zm2 0V8a4 4 0 0 1 8 0v3",
  flask: "M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2.2h12.4a1.5 1.5 0 0 0 1.3-2.2L14 9V3",
};

function AuthField(p: { label: string; icon: string; type: string; value: string; onChange: (v: string) => void; error?: string; autoComplete: string; placeholder: string; toggle?: boolean }) {
  const id = useId();
  const [shown, setShown] = useState(false);
  const err = p.error ? `${id}-e` : undefined;
  return (
    <div className="a-field">
      <label htmlFor={id}>{p.label}</label>
      <div className="a-control">
        <Icon d={p.icon} />
        <input id={id} name={p.label} className="a-input" type={p.toggle && shown ? "text" : p.type} value={p.value} onChange={(e) => p.onChange(e.target.value)} autoComplete={p.autoComplete}
          placeholder={p.placeholder} aria-invalid={p.error ? true : undefined} aria-describedby={err} spellCheck={false} autoCapitalize="none" />
        {p.toggle && (
          <button type="button" className="a-eye" aria-label={shown ? `Hide ${p.label.toLowerCase()}` : `Show ${p.label.toLowerCase()}`} aria-pressed={shown} aria-controls={id} onClick={() => setShown((s) => !s)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />{shown && <path d="M3 3l18 18" />}
            </svg>
          </button>
        )}
      </div>
      {p.error && <p className="a-err" id={err}>{p.error}</p>}
    </div>
  );
}

export function Auth({ mode }: { mode: AuthMode }) {
  const login = mode === "login";
  const [v, setV] = useState({ name: "", email: "", password: "", confirm: "", ack: false });
  const [errors, setErrors] = useState<AuthErrors>({});
  const [unavailable, setUnavailable] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const set = <K extends keyof typeof v>(k: K) => (val: (typeof v)[K]) => setV((s) => ({ ...s, [k]: val }));

  useEffect(() => {
    const prev = document.title;
    document.title = `${login ? "Sign in" : "Create account"} · GlycoTwin (research prototype)`;
    window.scrollTo({ top: 0 });
    return () => { document.title = prev; };
  }, [login]);
  useEffect(() => { setErrors({}); setUnavailable(false); setV({ name: "", email: "", password: "", confirm: "", ack: false }); }, [mode]);

  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    const e = validateAuth(mode, v);
    setErrors(e);
    setUnavailable(false);
    if (Object.keys(e).length) {
      // move focus to the first field with a problem so keyboard and screen-reader users land on it
      requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
      return;
    }
    // No network call: there is no account system to talk to. Do not keep the typed password around.
    setV((s) => ({ ...s, password: "", confirm: "" }));
    setUnavailable(true);
  };

  const demo = (
    <>
      <div className="a-or" aria-hidden="true"><span>or</span></div>
      <a className="btn a-demo" href={appHref("home")}><Icon d={ICON.flask} />Continue as demo</a>
      <p className="a-demo-note">Demonstration mode opens the research workspace <strong>without an account</strong>. Nothing is tied to you, and twins are not private to a user.</p>
    </>
  );

  return (
    <div className="auth theme-dark">
      <a className="skip" href="#main">Skip to content</a>
      <header className="auth-top">
        <a className="brand" href="#/" aria-label="GlycoTwin, back to home page">
          <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#f4ecd8" /><path d="M5 19c4-9 8 5 11-3s6-6 11-3" fill="none" stroke="#c9452d" strokeWidth="2.4" strokeLinecap="round" /></svg>
          <span className="display">GlycoTwin</span>
        </a>
        <a className="back" href="#/"><span aria-hidden="true">←</span> Back to home</a>
      </header>

      <main id="main" className="auth-main">
        <section className="auth-intro" aria-labelledby="auth-title">
          <h1 id="auth-title" className="display">{login ? "Welcome back" : <>Create your <br />account</>}</h1>
          <p>{login ? "Continue your research journey with GlycoTwin." : "Start exploring personalised glucose responses with GlycoTwin."}</p>
          <div className="auth-art" aria-hidden="true"><OrganicForm /><i className="orb o1" /><i className="orb o2" /><i className="orb o3" /></div>
        </section>

        <section className="auth-panel" aria-labelledby="panel-title">
          <h2 id="panel-title" className="display">{login ? "Sign in" : "Create account"}</h2>
          <p className="a-sub">{login ? "Access your GlycoTwin account" : "Join GlycoTwin and start modelling."}</p>
          <p className="a-preview" role="note"><span className="pill unc">Preview</span> Accounts are not available yet: this research prototype has no account system, so nothing you type here is sent or stored.</p>

          <form ref={formRef} onSubmit={submit} noValidate aria-label={login ? "Sign in form" : "Create account form"}>
            {!login && <AuthField label="Full name" icon={ICON.user} type="text" value={v.name} onChange={set("name")} error={errors.name} autoComplete="name" placeholder="Your name" />}
            <AuthField label="Email address" icon={ICON.mail} type="email" value={v.email} onChange={set("email")} error={errors.email} autoComplete="email" placeholder="you@example.com" />
            <AuthField label="Password" icon={ICON.lock} type="password" toggle value={v.password} onChange={set("password")} error={errors.password} autoComplete={login ? "current-password" : "new-password"} placeholder={login ? "Enter your password" : "Create a password"} />
            {!login && <AuthField label="Confirm password" icon={ICON.lock} type="password" toggle value={v.confirm} onChange={set("confirm")} error={errors.confirm} autoComplete="new-password" placeholder="Confirm your password" />}
            {!login && (
              <div className="a-check">
                <label><input type="checkbox" checked={v.ack} onChange={(e) => set("ack")(e.target.checked)} aria-invalid={errors.ack ? true : undefined} aria-describedby={errors.ack ? "ack-e" : undefined} />
                  <span>I understand GlycoTwin is an investigational research prototype, not a medical device.</span></label>
                {errors.ack && <p className="a-err" id="ack-e">{errors.ack}</p>}
              </div>
            )}
            <button className="btn primary a-submit" type="submit">{login ? "Sign in" : "Create account"} <span aria-hidden="true">→</span></button>
          </form>

          <div className="a-status" role="status" aria-live="polite">
            {unavailable && (
              <p className="a-unavail"><strong>{login ? "Sign-in isn’t available yet." : "Account creation isn’t available yet."}</strong> This prototype has no account system, so nothing was sent or saved and you are <strong>not</strong> {login ? "signed in" : "registered"}. Use demonstration mode below to explore the workspace.</p>
            )}
          </div>

          {demo}
          <p className="a-switch">{login ? <>Don’t have an account? <a href="#/register">Create one</a></> : <>Already have an account? <a href="#/login">Sign in</a></>}</p>
        </section>
      </main>
      <footer className="auth-foot"><Disclaimer variant="bar" /></footer>
    </div>
  );
}
