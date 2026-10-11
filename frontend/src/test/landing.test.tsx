import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Landing } from "../pages/Landing";
import { DISCLAIMER } from "../lib/config";

afterEach(() => vi.restoreAllMocks());

it("landing page shows the verbatim disclaimer, a menu control and states the B-vs-C result as inconclusive", () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
  const { container } = render(<Landing />);
  expect(container.textContent).toContain(DISCLAIMER);
  expect(screen.getByRole("button", { name: "Menu" })).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByText("inconclusive")).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/outperform|superior to/i);
});
