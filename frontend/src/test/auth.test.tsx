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

describe("validation", () => {
  const ok = { name: "A", email: "a@b.co", password: "x", confirm: "x", ack: true };
  it("login needs a well-formed email and a password", () => {
    expect(validateAuth("login", { ...ok, email: "nope", password: "" })).toEqual({ email: expect.stringMatching(/valid email/), password: expect.stringMatching(/password/i) });
    expect(validateAuth("login", ok)).toEqual({});
  });
  it("register also needs a name, matching passwords and the prototype acknowledgement", () => {
    expect(validateAuth("register", { ...ok, name: " ", confirm: "y", ack: false })).toMatchObject({ name: expect.any(String), confirm: expect.stringMatching(/match/), ack: expect.any(String) });
    expect(validateAuth("register", ok)).toEqual({});
  });
});

describe("sign in screen is honest about having no account system", () => {
  it("never calls the network, never shows a signed-in state, has no forgot-password or remember-me, and offers an explicit demo path", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { container } = render(<Auth mode="login" />);
    expect(screen.queryByText(/forgot password/i)).toBeNull();
    expect(screen.queryByText(/remember me/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^sign in/i }));
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email address")).toHaveAttribute("aria-invalid", "true");
    type("Email address", "demo@example.com");
    fireEvent.change(container.querySelector('input[type="password"]')!, { target: { value: "not-a-real-password" } });
    fireEvent.click(screen.getByRole("button", { name: /^sign in/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/isn’t available yet/);
    expect(screen.getByRole("status")).toHaveTextContent(/not signed in/);
    expect(container.textContent).not.toMatch(/welcome,|signed in as|you are signed in/i);
    expect((container.querySelector('input[type="password"]') as HTMLInputElement).value).toBe("");   // the typed password is not kept
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /continue as demo/i })).toHaveAttribute("href", "#/app/home");
    expect(container.textContent).toContain("without an account");
    expect(screen.getByTestId("disclaimer")).toHaveTextContent(DISCLAIMER);
  });

  it("password visibility toggle changes the input type and its accessible name", () => {
    const { container } = render(<Auth mode="login" />);
    const btn = screen.getByRole("button", { name: "Show password" });
    expect(container.querySelector("#" + CSS.escape(btn.getAttribute("aria-controls")!))).toHaveAttribute("type", "password");
    fireEvent.click(btn);
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-pressed", "true");
    expect(container.querySelector("#" + CSS.escape(btn.getAttribute("aria-controls")!))).toHaveAttribute("type", "text");
  });
});

describe("create account screen", () => {
  it("validates, then says no account was created", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { container } = render(<Auth mode="register" />);
    fireEvent.click(screen.getByRole("button", { name: /^create account/i }));
    ["Enter your name.", "Enter your email address.", "Choose a password.", "Confirm your password."].forEach((t) => expect(screen.getByText(t)).toBeInTheDocument());
    type("Full name", "Demo Person"); type("Email address", "demo@example.com");
    const pw = container.querySelectorAll('input[type="password"]');
    fireEvent.change(pw[0], { target: { value: "abc12345" } }); fireEvent.change(pw[1], { target: { value: "different" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /^create account/i }));
    expect(screen.getByText("The two passwords do not match.")).toBeInTheDocument();
    fireEvent.change(pw[1], { target: { value: "abc12345" } });
    fireEvent.click(screen.getByRole("button", { name: /^create account/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/Account creation isn’t available yet/);
    expect(screen.getByRole("status")).toHaveTextContent(/not registered/);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "#/login");
  });
});
