/** Single place where the API base URL is configured (Vite env var, default: the dev/preview proxy at /api). */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, "") || "/api";

export const DISCLAIMER =
  "GlycoTwin is an investigational metabolic Digital Twin research prototype. It is not a medical device or diagnostic instrument. " +
  "Predictions and parameter estimates are experimental and must not be used for clinical decision-making, medical diagnosis, or insulin dosing.";

export const OUTCOME_THRESHOLD_MG_DL = 180;
export const OUTCOME_WINDOW_MIN = 120;
