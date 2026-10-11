import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api/client";
import { checkForecast } from "../api/validate";
import { Disclaimer } from "../components/ui/Disclaimer";
import { parseNumber } from "../components/ui/Field";
import { ResponseChart } from "../dashboard/ResponseChart";
import { DISCLAIMER } from "../lib/config";
import { linear, niceTicks } from "../lib/chartMath";
import { parseHash } from "../lib/router";
import { isTwinId, upsert } from "../lib/twinRegistry";

afterEach(() => vi.restoreAllMocks());
const mockFetch = (status: number, body: unknown) => vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

describe("disclaimer", () => {
  it("is rendered verbatim", () => {
    render(<Disclaimer />);
    expect(screen.getByTestId("disclaimer")).toHaveTextContent(DISCLAIMER);
    expect(DISCLAIMER).toBe("GlycoTwin is an investigational metabolic Digital Twin research prototype. It is not a medical device or diagnostic instrument. Predictions and parameter estimates are experimental and must not be used for clinical decision-making, medical diagnosis, or insulin dosing.");
  });
});

describe("api client", () => {
  it("reads the health body (not enveloped)", async () => {
    mockFetch(200, { status: "ok", database: "sqlite", engine: {}, disclaimer: "x" });
    expect((await api.health()).status).toBe("ok");
  });
  it("maps statuses to error kinds", async () => {
    mockFetch(404, { detail: "no such twin", disclaimer: "x" });
    await expect(api.getTwin("a")).rejects.toMatchObject({ kind: "not_found" });
    mockFetch(409, { detail: "conflict", disclaimer: "x" });
    await expect(api.reconcile("a", "b")).rejects.toMatchObject({ kind: "conflict" });
    mockFetch(422, { detail: [{ loc: ["body", "carbs_g"], msg: "bad" }], disclaimer: "x" });
    await expect(api.forecast("a", { event_id: "e", meal_time: "t", carbs_g: -1, activity_level: 0, baseline_glucose: 100 })).rejects.toMatchObject({ kind: "validation" });
  });
  it("reports an unreachable backend", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const e = await api.health().catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e.kind).toBe("network");
  });
  it("rejects a malformed body instead of inventing values", async () => {
    mockFetch(200, { disclaimer: "x", data: { forecast_id: "f" } });
    await expect(api.forecast("a", { event_id: "e", meal_time: "t", carbs_g: 1, activity_level: 0, baseline_glucose: 100 })).rejects.toMatchObject({ kind: "shape" });
    expect(() => checkForecast({})).toThrow();
  });
});

describe("helpers", () => {
  it("parses routes", () => {
    expect(parseHash("#/app/forecast")).toEqual({ page: "app", view: "forecast" });
    expect(parseHash("#/app/bogus")).toEqual({ page: "app", view: "home" });
    expect(parseHash("")).toEqual({ page: "landing", section: undefined });
  });
  it("validates numbers", () => {
    expect(parseNumber("", "x", 0, 1).error).toMatch(/required/);
    expect(parseNumber("abc", "x", 0, 1).error).toMatch(/number/);
    expect(parseNumber("2", "x", 0, 1).error).toMatch(/between/);
    expect(parseNumber("0.5", "x", 0, 1).value).toBe(0.5);
  });
  it("registry", () => {
    expect(isTwinId("123e4567-e89b-12d3-a456-426614174000")).toBe(true);
    expect(isTwinId("nope")).toBe(false);
    expect(upsert([], { id: "a", label: "A" })).toHaveLength(1);
  });
  it("scales", () => {
    expect(linear([0, 10], [0, 100])(5)).toBe(50);
    expect(niceTicks(0, 100, 5).length).toBeGreaterThan(2);
  });
});

describe("response chart", () => {
  it("shows an empty state, no data, without a forecast", () => {
    render(<ResponseChart forecast={null} observedPeak={null} models="both" />);
    expect(screen.getByText(/No forecast to draw yet/)).toBeInTheDocument();
  });
});
