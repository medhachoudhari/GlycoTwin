import { useEffect, useState } from "react";

/** Minimal hash router: "#/" is the landing page, "#/app/<view>" the research workspace. No dependency, works from any static host. */
export type View = "home" | "twin" | "forecast" | "observations" | "history" | "insights" | "settings";
export const VIEWS: View[] = ["home", "twin", "forecast", "observations", "history", "insights", "settings"];
export type Route = { page: "landing"; section?: string } | { page: "app"; view: View };

export function parseHash(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  if (h.startsWith("app")) {
    const v = h.split("/")[1] as View | undefined;
    return { page: "app", view: v && VIEWS.includes(v) ? v : "home" };
  }
  return { page: "landing", section: h || undefined };
}
export const appHref = (v: View = "home"): string => `#/app/${v}`;

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function usePrefersReducedMotion(): boolean {
  const q = "(prefers-reduced-motion: reduce)";
  const [reduce, setReduce] = useState(() => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(q).matches : false));
  useEffect(() => {
    if (!window.matchMedia) return;
    const m = window.matchMedia(q);
    const on = () => setReduce(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return reduce;
}
