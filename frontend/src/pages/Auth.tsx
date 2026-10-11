import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { OrganicForm } from "../components/organic/OrganicForm";
import { Disclaimer } from "../components/ui/Disclaimer";
import { appHref, type AuthMode } from "../lib/router";

/**
 * Sign In and Create Account screens, connected to the real backend (POST /auth/register, /auth/login, /auth/guest).
 * Success is only shown after the backend confirms it: the user object comes back from the API and the session lives in an HttpOnly cookie.
 * The password is sent once over the same-origin proxy and is cleared from the form afterwards; nothing secret is written to browser storage.
 */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export interface AuthErrors { name?: string; email?: string; password?: string; confirm?: string; ack?: string }
export function validateAuth(mode: AuthMode, v: { name: string; email: string; password: string; confirm: string; ack: boolean }): AuthErrors {
  const e: AuthErrors = {};
  if (mode === "register" && !v.name.trim()) e.name = "Enter your name.";
  if (!v.email.trim()) e.email = "Enter your email address.";
  else if (!EMAIL.test(v.email.trim())) e.email = "Enter a valid email address, such as name@example.com.";
  if (!v.password) e.password = mode === "login" ? "Enter your password." : "Choose a password.";
  else if (mode === "register" && v.password.length < 10) e.password = "Use at least 10 characters.";
  else if (mode === "register" && v.password.length > 128) e.password = "Use at most 128 characters.";
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
  const auth = useAuth();
  const [v, setV] = useState({ name: "", email: "", password: "", confirm: "", ack: false });
  const [errors, setErrors] = useState<AuthErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"submit" | "guest" | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const set = <K extends keyof typeof v>(k: K) => (val: (typeof v)[K]) => setV((s) => ({ ...s, [k]: val }));

  useEffect(() => {
    const prev = document.title;
    document.title = `${login ? "Sign in" : "Create account"} · GlycoTwin (research prototype)`;
    window.scrollTo({ top: 0 });
    return () => { document.title = prev; };
  }, [login]);
  useEffect(() => { setErrors({}); setFormError(null); setV({ name: "", email: "", password: "", confirm: "", ack: false }); }, [mode]);

  /** Turn an API failure into text next to the right field, or a message above the buttons. */
  const explain = (e: unknown): void => {
    const err = e instanceof ApiError ? e : new ApiError("server", (e as Error).message);
    if (err.kind === "unauthorized") setFormError("Incorrect email or password.");
    else if (err.kind === "conflict") setErrors({ email: "An account with this email already exists. Try signing in instead." });
    else if (err.kind === "validation") {
      const m = err.message;
      if (/password/i.test(m)) setErrors({ password: m.replace(/^password:\s*/i, "").replace(/^Value error,\s*/i, "") });
      else if (/email/i.test(m)) setErrors({ email: m.replace(/^email:\s*/i, "").replace(/^Value error,\s*/i, "") });
      else setFormError(m);
    } else if (err.kind === "rate_limited") setFormError(`Too many attempts. Please wait${err.retryAfter ? ` about ${Math.ceil(err.retryAfter / 60)} minute(s)` : " a few minutes"} and try again.`);
    else setFormError(err.message);
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (busy) return;
    const e = validateAuth(mode, v);
    setErrors(e);
    setFormError(null);
    if (Object.keys(e).length) {
      // move focus to the first field with a problem so keyboard and screen-reader users land on it
      requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
      return;
    }
    setBusy("submit");
    try {
      if (login) await auth.login({ email: v.email.trim(), password: v.password });
      else await auth.register({ name: v.name.trim(), email: v.email.trim(), password: v.password });
      setV((s) => ({ ...s, password: "", confirm: "" }));
      window.location.hash = appHref("home");                          // only after the backend confirmed the account / session
    } catch (err) {
      setV((s) => ({ ...s, password: "", confirm: "" }));              // never keep a typed password after a failed attempt either
      explain(err);
      requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
    } finally { setBusy(null); }
  };

  const startGuest = async () => {
    if (busy) return;
    setBusy("guest"); setFormError(null); setErrors({});
    try { await auth.guest(); window.location.hash = appHref("home"); } catch (err) { explain(err); } finally { setBusy(null); }
  };

  const demo = (
    <>
      <div className="a-or" aria-hidden="true"><span>or</span></div>
      <button type="button" className="btn a-demo" onClick={() => void startGuest()} disabled={busy !== null} aria-busy={busy === "guest" || undefined}><Icon d={ICON.flask} />{busy === "guest" ? "Starting demo…" : "Continue as demo"}</button>
      <p className="a-demo-note">Demo mode creates a <strong>temporary guest account</strong>. Its twins belong only to that guest and are never visible to any other account, but you cannot sign back in to it later. Do not enter personal health data.</p>
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
          {auth.notice && <p className="a-unavail" role="status">{auth.notice}</p>}

          <form ref={formRef} onSubmit={submit} noValidate aria-label={login ? "Sign in form" : "Create account form"}>
            {!login && <AuthField label="Full name" icon={ICON.user} type="text" value={v.name} onChange={set("name")} error={errors.name} autoComplete="name" placeholder="Your name" />}
            <AuthField label="Email address" icon={ICON.mail} type="email" value={v.email} onChange={set("email")} error={errors.email} autoComplete="email" placeholder="you@example.com" />
            <AuthField label="Password" icon={ICON.lock} type="password" toggle value={v.password} onChange={set("password")} error={errors.password} autoComplete={login ? "current-password" : "new-password"} placeholder={login ? "Enter your password" : "At least 10 characters"} />
            {!login && <AuthField label="Confirm password" icon={ICON.lock} type="password" toggle value={v.confirm} onChange={set("confirm")} error={errors.confirm} autoComplete="new-password" placeholder="Confirm your password" />}
            {!login && (
              <div className="a-check">
                <label><input type="checkbox" checked={v.ack} onChange={(e) => set("ack")(e.target.checked)} aria-invalid={errors.ack ? true : undefined} aria-describedby={errors.ack ? "ack-e" : undefined} />
                  <span>I understand GlycoTwin is an investigational research prototype, not a medical device.</span></label>
                {errors.ack && <p className="a-err" id="ack-e">{errors.ack}</p>}
              </div>
            )}
            <button className="btn primary a-submit" type="submit" disabled={busy !== null} aria-busy={busy === "submit" || undefined}>{busy === "submit" ? <><span className="spinner" aria-hidden="true" />{login ? "Signing in…" : "Creating account…"}</> : <>{login ? "Sign in" : "Create account"} <span aria-hidden="true">→</span></>}</button>
          </form>

          <div className="a-status" role="alert" aria-live="assertive">{formError && <p className="a-formerr">{formError}</p>}</div>

          {demo}
          <p className="a-switch">{login ? <>Don’t have an account? <a href="#/register">Create one</a></> : <>Already have an account? <a href="#/login">Sign in</a></>}</p>
        </section>
      </main>
      <footer className="auth-foot"><Disclaimer variant="bar" /></footer>
    </div>
  );
}
