import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Auth, validateAuth } from "../pages/Auth";
import { parseHash } from "../lib/router";
import { DISCLAIMER } from "../lib/config";

afterEach(() => vi.restoreAllMocks());
const type = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label, { selector: "input" }), { target: { value } });

describe("auth routes", () => {
  it("login and register use the existing hash router", () => {
    expect(parseHash("#/login")).toEqual({ page: "auth", mode: "login" });
    expect(parseHash("#/register")).toEqual({ page: "auth", mode: "register" });
    expect(parseHash("#/app/forecast")).toEqual({ page: "app", view: "forecast" });
    expect(parseHash("#/research")).toEqual({ page: "landing", section: "research" });
  });
});

describe("validation (the same rules the backend enforces, checked before anything is sent)", () => {
  const ok = { name: "A", email: "a@b.co", password: "long-enough-pass", confirm: "long-enough-pass", ack: true };
  it("sign in needs a well-formed email and a password", () => {
    expect(validateAuth("login", { ...ok, email: "nope", password: "" })).toEqual({ email: expect.stringMatching(/valid email/), password: expect.stringMatching(/password/i) });
    expect(validateAuth("login", { ...ok, password: "short" })).toEqual({});                       // an existing account is never told off about length at sign-in
  });
  it("create account also needs a name, 10 to 128 characters, matching passwords and the prototype acknowledgement", () => {
    expect(validateAuth("register", { ...ok, name: " ", confirm: "y", ack: false })).toMatchObject({ name: expect.any(String), confirm: expect.stringMatching(/match/), ack: expect.any(String) });
    expect(validateAuth("register", { ...ok, password: "short", confirm: "short" }).password).toMatch(/at least 10/);
    expect(validateAuth("register", { ...ok, password: "x".repeat(129), confirm: "x".repeat(129) }).password).toMatch(/at most 128/);
    expect(validateAuth("register", ok)).toEqual({});
  });
});

describe("the forms", () => {
  it("never offer forgot-password or remember-me (not implemented), always show the disclaimer, and link between the pages", () => {
    const { container, unmount } = render(<Auth mode="login" />);
    expect(screen.queryByText(/forgot password/i)).toBeNull();
    expect(screen.queryByText(/remember me/i)).toBeNull();
    expect(screen.getByTestId("disclaimer")).toHaveTextContent(DISCLAIMER);
    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "#/register");
    expect(container.textContent).toMatch(/temporary guest account/i);
    expect(container.textContent).not.toMatch(/preview/i);                                       // the "not connected" banner is gone: this is real now
    unmount();
    render(<Auth mode="register" />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "#/login");
  });

  it("invalid input is explained inline, linked to its field, and sends no request", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<Auth mode="login" />);
    fireEvent.click(screen.getByRole("button", { name: /^sign in/i }));
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument();
    const email = screen.getByLabelText("Email address");
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(document.getElementById(email.getAttribute("aria-describedby")!)).toHaveTextContent("Enter your email address.");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("password visibility toggle changes the input type and its accessible name", () => {
    const { container } = render(<Auth mode="login" />);
    const btn = screen.getByRole("button", { name: "Show password" });
    expect(container.querySelector("#" + CSS.escape(btn.getAttribute("aria-controls")!))).toHaveAttribute("type", "password");
    fireEvent.click(btn);
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector("#" + CSS.escape(btn.getAttribute("aria-controls")!))).toHaveAttribute("type", "text");
  });

  it("the create-account form requires the password rule before it sends anything", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { container } = render(<Auth mode="register" />);
    type("Full name", "Demo Person"); type("Email address", "demo@example.com");
    const pw = container.querySelectorAll('input[type="password"]');
    fireEvent.change(pw[0], { target: { value: "short" } }); fireEvent.change(pw[1], { target: { value: "short" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /^create account/i }));
    expect(screen.getByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
