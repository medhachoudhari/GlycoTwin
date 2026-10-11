import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, setUnauthorizedHandler } from "../api/client";
import type { AuthUser, LoginBody, RegisterBody } from "../api/types";

/**
 * Who is signed in. The session is an HttpOnly cookie set by the backend; this layer only remembers the user object it gets back from /auth/me, /auth/login,
 * /auth/register or /auth/guest (in memory). Passwords are sent once and never kept; nothing secret is written to localStorage or sessionStorage.
 */
export type AuthStatus = "loading" | "signedIn" | "signedOut" | "unreachable";
export interface Auth {
  status: AuthStatus;
  user: AuthUser | null;
  notice: string | null;                 // e.g. "Your session has ended" after an expired or revoked session
  unreachableMessage: string | null;
  clearNotice: () => void;
  retry: () => void;
  register: (b: RegisterBody) => Promise<void>;
  login: (b: LoginBody) => Promise<void>;
  guest: () => Promise<void>;
  logout: () => Promise<void>;
}

const SIGNED_OUT: Auth = { status: "signedOut", user: null, notice: null, unreachableMessage: null, clearNotice: () => {}, retry: () => {},
  register: async () => { throw new Error("no AuthProvider"); }, login: async () => { throw new Error("no AuthProvider"); }, guest: async () => { throw new Error("no AuthProvider"); }, logout: async () => {} };
const Ctx = createContext<Auth>(SIGNED_OUT);
export const useAuth = (): Auth => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [unreachableMessage, setUnreachable] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Restore the session after a reload: the browser still holds the cookie, so ask the backend who it belongs to.
  useEffect(() => {
    const ac = new AbortController();
    setStatus("loading");
    api.me(ac.signal)
      .then(({ user: u }) => { setUser(u); setStatus("signedIn"); setUnreachable(null); })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        // Only a 401 means "nobody is signed in". Any other failure (backend down, broken reply) must NOT look like a sign-out, or a hiccup would silently log people out.
        if (e instanceof ApiError && e.kind === "unauthorized") { setUser(null); setStatus("signedOut"); return; }
        setUser(null); setUnreachable(e.message); setStatus("unreachable");
      });
    return () => ac.abort();
  }, [attempt]);

  // A protected request came back 401 while we thought we were signed in: the session expired or was revoked.
  useEffect(() => {
    setUnauthorizedHandler(() => { setUser((cur) => { if (cur) setNotice("Your session has ended. Please sign in again."); return null; }); setStatus((s) => (s === "signedIn" ? "signedOut" : s)); });
    return () => setUnauthorizedHandler(null);
  }, []);

  const finish = (u: AuthUser) => { setUser(u); setStatus("signedIn"); setNotice(null); };
  const register = useCallback(async (b: RegisterBody) => { finish((await api.register(b)).user); }, []);
  const login = useCallback(async (b: LoginBody) => { finish((await api.login(b)).user); }, []);
  const guest = useCallback(async () => { finish((await api.guest()).user); }, []);
  const logout = useCallback(async () => {
    try { await api.logout(); } catch { /* even if the call fails, leave the signed-in screens; the cookie expires on its own */ }
    setUser(null); setStatus("signedOut"); setNotice(null);
  }, []);

  const value = useMemo<Auth>(() => ({ status, user, notice, unreachableMessage, clearNotice: () => setNotice(null), retry: () => setAttempt((n) => n + 1), register, login, guest, logout }),
    [status, user, notice, unreachableMessage, register, login, guest, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
