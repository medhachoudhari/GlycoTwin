import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { makeBackend } from "./fakeBackend";

let be: ReturnType<typeof makeBackend>;
beforeEach(() => {
  be = makeBackend();
  vi.spyOn(globalThis, "fetch").mockImplementation(be.fetch as typeof fetch);
  window.localStorage.clear(); window.sessionStorage.clear();
  window.location.hash = "";
  render(<App />);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const go = async (hash: string) => { await act(async () => { window.location.hash = hash; }); };
const field = (label: string | RegExp) => screen.getByLabelText(label, { selector: "input" }) as HTMLInputElement;
const type = (label: string | RegExp, value: string) => fireEvent.change(field(label), { target: { value } });
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const clickLogout = () => fireEvent.click(screen.getAllByRole("button", { name: "Log out" })[0]);          // the sidebar and the Settings page both have one

async function register(name = "Test Person", email = "test@example.com", password = "a-long-test-passphrase") {
  await go("#/register");
  await screen.findByRole("heading", { name: "Create account" });
  type("Full name", name); type("Email address", email);
  type(/^Password$/, password); type("Confirm password", password);
  fireEvent.click(screen.getByRole("checkbox"));
  click(/^create account/i);
}
async function signIn(email: string, password: string) {
  await go("#/login");
  await screen.findByRole("heading", { name: "Sign in" });
  type("Email address", email); type(/^Password$/, password);
  click(/^sign in/i);
}
/** The success notice (the same sentence is also copied into a hidden screen-reader region, so look at the visible notice). */
const created = () => waitFor(() => expect(document.querySelector(".notice.ok")).toHaveTextContent(/created at version 0/));
async function createTwin(label: string) {
  await go("#/app/settings");
  await screen.findByRole("heading", { name: "Create a twin" });
  type("Twin label", label);
  click("Create twin");
}

describe("registration through the UI", () => {
  it("creates the account at the backend, signs in, shows the name, and keeps no password or token in browser storage", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    const post = be.calls.find((c) => c.path === "/auth/register");
    expect(post?.method).toBe("POST");
    expect(post?.body).toEqual({ name: "Test Person", email: "test@example.com", password: "a-long-test-passphrase" });
    expect(window.location.hash).toBe("#/app/home");
    expect(screen.getByText("Test Person")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
    const stored = JSON.stringify({ ...window.localStorage }) + JSON.stringify({ ...window.sessionStorage }) + document.cookie;
    expect(stored).not.toContain("a-long-test-passphrase");
    expect(stored).not.toMatch(/tok-\d/);                                                       // the session token lives only in the (simulated) HttpOnly cookie
  });

  it("validates before sending anything and explains each problem next to its field", async () => {
    await go("#/register");
    await screen.findByRole("heading", { name: "Create account" });
    click(/^create account/i);
    ["Enter your name.", "Enter your email address.", "Choose a password.", "Confirm your password.", "Please acknowledge that GlycoTwin is a research prototype."].forEach((t) => expect(screen.getByText(t)).toBeInTheDocument());
    type("Full name", "A"); type("Email address", "a@b.co"); type(/^Password$/, "short"); type("Confirm password", "short"); fireEvent.click(screen.getByRole("checkbox"));
    click(/^create account/i);
    expect(screen.getByText("Use at least 10 characters.")).toBeInTheDocument();
    type(/^Password$/, "long-enough-pass"); type("Confirm password", "different-pass-1");
    click(/^create account/i);
    expect(screen.getByText("The two passwords do not match.")).toBeInTheDocument();
    expect(be.calls.filter((c) => c.path === "/auth/register")).toHaveLength(0);               // nothing was sent
  });

  it("says so when the email is already registered, and does not sign anyone in", async () => {
    be.users.push({ id: "u-x", name: "Existing", email: "test@example.com", password: "another-passphrase", guest: false });
    await register();
    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
    expect(window.location.hash).toBe("#/register");
    expect(screen.queryByRole("button", { name: "Log out" })).toBeNull();
  });
});

describe("sign in", () => {
  it("signs in with the right password and lands on the dashboard", async () => {
    be.users.push({ id: "u-1", name: "Alice Example", email: "alice@example.com", password: "alice-passphrase-1", guest: false });
    await signIn("Alice@Example.com", "alice-passphrase-1");
    await screen.findByRole("heading", { name: "Home" });
    expect(screen.getByText("Alice Example")).toBeInTheDocument();
  });

  it("shows 'Incorrect email or password.' for a wrong password and for an unknown email alike", async () => {
    be.users.push({ id: "u-1", name: "Alice", email: "alice@example.com", password: "alice-passphrase-1", guest: false });
    await signIn("alice@example.com", "wrong-password-x");
    expect(await screen.findByText("Incorrect email or password.")).toBeInTheDocument();
    expect(field(/^Password$/).value).toBe("");                                                 // the typed password is not kept
    cleanup(); window.location.hash = ""; render(<App />);
    await signIn("nobody@example.com", "wrong-password-x");
    expect(await screen.findByText("Incorrect email or password.")).toBeInTheDocument();
    expect(window.location.hash).toBe("#/login");
  });

  it("explains rate limiting", async () => {
    be.state.failedLogins = 5;
    await signIn("alice@example.com", "whatever-pass-1");
    expect(await screen.findByText(/too many attempts/i)).toBeInTheDocument();
  });

  it("reports an unreachable backend instead of pretending to sign in", async () => {
    await go("#/login");
    await screen.findByRole("heading", { name: "Sign in" });
    be.state.offline = true;
    type("Email address", "a@b.co"); type(/^Password$/, "some-password-1"); click(/^sign in/i);
    expect(await screen.findByText(/Cannot reach the GlycoTwin backend/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log out" })).toBeNull();
  });
});

describe("sessions, protected pages and logout", () => {
  it("sends signed-out visitors from any #/app/ page to #/login", async () => {
    await go("#/app/forecast");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(window.location.hash).toBe("#/login");
  });

  it("restores the session after a page reload (cookie + GET /auth/me)", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    cleanup();                                                                                  // "reload": a fresh app, same cookie jar
    be.calls.length = 0;
    render(<App />);
    await screen.findByRole("heading", { name: "Home" });
    expect(be.calls[0]).toMatchObject({ method: "GET", path: "/auth/me" });
    expect(screen.getByText("Test Person")).toBeInTheDocument();
  });

  it("logs out on the server and returns to the sign-in page; protected pages are closed again", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    clickLogout();
    await screen.findByRole("heading", { name: "Sign in" });
    expect(be.calls.some((c) => c.path === "/auth/logout" && c.method === "POST")).toBe(true);
    expect(be.jar.token).toBeNull();
    await go("#/app/home");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(window.location.hash).toBe("#/login");
  });

  it("an already signed-in user who opens the sign-in page goes straight to the dashboard", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    await go("#/login");
    await screen.findByRole("heading", { name: "Home" });
  });

  it("handles an expired session: back to sign-in with an explanation", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    await createTwin("first-twin");
    await created();
    be.expireSessions();                                                                        // the server no longer recognises the cookie
    type("Twin label", "second-twin"); click("Create twin");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(screen.getByText("Your session has ended. Please sign in again.")).toBeInTheDocument();
    expect(window.location.hash).toBe("#/login");
  });

  it("a backend that is down (the dev proxy answers an empty 500) is reported as unreachable, never as 'signed out'", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    cleanup(); be.state.proxyDown = true; window.location.hash = "#/app/home"; render(<App />);   // reload while the backend is stopped
    expect(await screen.findByText("Cannot reach the backend")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();                       // the person is not silently logged out by an outage
    be.state.proxyDown = false;
    click("Try again");
    await screen.findByRole("heading", { name: "Home" });                                        // the cookie is still valid: back in, nothing lost
  });

  it("shows a clear message with a retry when the backend cannot be reached while restoring the session", async () => {
    cleanup(); be.state.offline = true; window.location.hash = "#/app/home"; render(<App />);          // the backend is down at start-up
    expect(await screen.findByText("Cannot reach the backend")).toBeInTheDocument();
    be.state.offline = false;
    click("Try again");
    await screen.findByRole("heading", { name: "Sign in" });                                    // reachable now, nobody signed in
  });
});

describe("guest (demonstration) mode", () => {
  it("creates a temporary guest account through the backend and labels it clearly", async () => {
    await go("#/login");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(screen.getByText(/temporary guest account/i)).toBeInTheDocument();                   // explained before it is used
    click("Continue as demo");
    await screen.findByRole("heading", { name: "Home" });
    expect(be.calls.some((c) => c.path === "/auth/guest" && c.method === "POST")).toBe(true);
    expect(screen.getByText("Guest", { selector: ".guest-badge" })).toBeInTheDocument();
    expect(screen.getByText(/Guest mode: a temporary account/)).toBeInTheDocument();
    expect(be.users.at(-1)).toMatchObject({ guest: true, email: null, password: null });
  });

  it("a guest never sees a registered user's twins", async () => {
    await register("Alice", "alice@example.com");
    await screen.findByRole("heading", { name: "Home" });
    await createTwin("alice-private-twin");
    await created();
    clickLogout();
    await screen.findByRole("heading", { name: "Sign in" });
    click("Continue as demo");
    await screen.findByRole("heading", { name: "Home" });
    await go("#/app/settings");
    await screen.findByText("You have no twins yet. Create one with the form.");
    expect(screen.queryByText(/alice-private-twin/)).toBeNull();
  });
});

describe("my twins", () => {
  it("creating a twin adds it to My twins, and it is still there after a reload", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    await go("#/app/settings");
    await screen.findByText("You have no twins yet. Create one with the form.");
    await createTwin("my-first-twin");
    await created();
    const mine = screen.getByRole("heading", { name: "My twins" }).closest("section")!;
    expect(within(mine).getByText(/my-first-twin/)).toBeInTheDocument();
    expect(within(mine).getByText("Open", { selector: ".pill" })).toBeInTheDocument();
    cleanup(); render(<App />);                                                                 // reload
    await screen.findByRole("heading", { name: "Create a twin" });
    await waitFor(() => expect(within(screen.getByRole("heading", { name: "My twins" }).closest("section")!).getByText(/my-first-twin/)).toBeInTheDocument());
  });

  it("lists only the signed-in user's own twins", async () => {
    await register("Alice", "alice@example.com");
    await screen.findByRole("heading", { name: "Home" });
    await createTwin("alice-twin");
    await created();
    clickLogout(); await screen.findByRole("heading", { name: "Sign in" });
    await register("Bob", "bob@example.com");
    await screen.findByRole("heading", { name: "Home" });
    await go("#/app/settings");
    await screen.findByText("You have no twins yet. Create one with the form.");
    await createTwin("bob-twin");
    await created();
    const mine = screen.getByRole("heading", { name: "My twins" }).closest("section")!;
    expect(within(mine).getByText(/bob-twin/)).toBeInTheDocument();
    expect(within(mine).queryByText(/alice-twin/)).toBeNull();
    // and the API request that produced the list was the owner-scoped GET /twins
    expect(be.calls.filter((c) => c.path === "/twins" && c.method === "GET").length).toBeGreaterThan(0);
  });

  it("shows an error with a retry when the twin list cannot be loaded", async () => {
    await register();
    await screen.findByRole("heading", { name: "Home" });
    be.state.listFails = true;
    cleanup(); render(<App />);                                                                 // reload so the list is requested again
    await go("#/app/settings");
    expect(await screen.findByText("Could not load your twins")).toBeInTheDocument();
    be.state.listFails = false;
    fireEvent.click(screen.getAllByRole("button", { name: "Try again" })[0]);
    await screen.findByText("You have no twins yet. Create one with the form.");
  });
});
