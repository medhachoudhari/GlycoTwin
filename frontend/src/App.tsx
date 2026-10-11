import { useEffect, type ReactElement } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Landing } from "./pages/Landing";
import { Auth } from "./pages/Auth";
import { Shell } from "./dashboard/Shell";
import { WorkspaceProvider } from "./dashboard/workspace";
import { ForecastView, HistoryView, HomeView, InsightsView, ObservationsView, SettingsView, TwinView } from "./dashboard/views";
import { appHref, useRoute, type View } from "./lib/router";
import { Notice, Spinner } from "./components/ui/Status";

const VIEW: Record<View, () => ReactElement> = { home: HomeView, twin: TwinView, forecast: ForecastView, observations: ObservationsView, history: HistoryView, insights: InsightsView, settings: SettingsView };

function Splash({ children }: { children: ReactElement }) {
  return <div className="theme-dark" style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>{children}</div>;
}

/** Replace (not push) the address so the Back button does not bounce between a protected page and the sign-in page. */
function Redirect({ to }: { to: string }) {
  useEffect(() => { if (window.location.hash !== to) window.location.replace(to); }, [to]);
  return <Splash><Spinner label="Redirecting…" /></Splash>;
}

/** Everything under #/app/ needs a signed-in user. The session is restored from the HttpOnly cookie via GET /auth/me before anything is decided. */
function Protected({ view }: { view: View }) {
  const auth = useAuth();
  if (auth.status === "loading") return <Splash><Spinner label="Checking your session…" /></Splash>;
  if (auth.status === "unreachable") {
    return <Splash><div style={{ maxWidth: 520 }}><Notice tone="err" title="Cannot reach the backend">{auth.unreachableMessage} <button className="btn small" onClick={auth.retry}>Try again</button></Notice></div></Splash>;
  }
  if (auth.status === "signedOut" || !auth.user) return <Redirect to="#/login" />;
  const Body = VIEW[view];
  return <WorkspaceProvider key={auth.user.id}><Shell view={view}><Body /></Shell></WorkspaceProvider>;
}

function Routes() {
  const route = useRoute();
  const auth = useAuth();
  if (route.page === "landing") return <Landing section={route.section} />;
  if (route.page === "auth") {
    if (auth.status === "signedIn") return <Redirect to={appHref("home")} />;           // already signed in: no need for the forms
    return <Auth mode={route.mode} />;
  }
  return <Protected view={route.view} />;
}

export default function App() {
  return <AuthProvider><Routes /></AuthProvider>;
}
