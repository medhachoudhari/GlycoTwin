import type { ReactElement } from "react";
import { Landing } from "./pages/Landing";
import { Shell } from "./dashboard/Shell";
import { WorkspaceProvider } from "./dashboard/workspace";
import { ForecastView, HistoryView, HomeView, InsightsView, ObservationsView, SettingsView, TwinView } from "./dashboard/views";
import { useRoute, type View } from "./lib/router";

const VIEW: Record<View, () => ReactElement> = { home: HomeView, twin: TwinView, forecast: ForecastView, observations: ObservationsView, history: HistoryView, insights: InsightsView, settings: SettingsView };

export default function App() {
  const route = useRoute();
  if (route.page === "landing") return <Landing section={route.section} />;
  const Body = VIEW[route.view];
  return <WorkspaceProvider><Shell view={route.view}><Body /></Shell></WorkspaceProvider>;
}
