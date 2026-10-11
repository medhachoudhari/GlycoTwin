/** Types mirror the responses of the FastAPI backend (src/glycotwin/backend/services.py). Every success body is { disclaimer, data }. */

export interface Envelope<T> { disclaimer: string; data: T }

export interface Health {
  status: "ok" | "degraded"; database: string; tables: string[]; disclaimer: string;
  engine: { package_version: string | null; git_commit: string | null; working_tree_dirty: boolean | null; engine: string };
}

export interface PriorProvenance {
  source: string; SYNTHETIC?: boolean; population?: string; prior_scheme: string; gamma_relative_sd: number | null;
  activity_scale?: string; supported_activity_range?: [number, number]; activity_range?: [number, number];
  activity_range_enforcement?: string; contains_participant_level_data: boolean; [k: string]: unknown;
}

export interface Moment { mean: number; variance: number }

export interface DataQuality {
  low_data_quality: boolean; insufficient_history: boolean; reasons: string[]; n_personal_observations: number;
  warnings: string[]; warning: string | null; interval_adjusted: boolean; note: string;
}

export interface TwinStateView {
  kind: string; as_of: string | null;
  current_glucose_state: { last_value_mg_dl: number | null; as_of: string | null; basis: string };
  recent_activity_state: { rolling_mets_4h: number | null; activity_label: string; as_of: string | null; step_count_today: number | null };
  meal_state: { open_meal_windows: unknown[]; forecasts_awaiting_reconciliation: string[]; carbs_in_open_outcome_windows_g: number };
  personalized_parameters: {
    carb_sensitivity_model_b: Moment;
    carb_sensitivity_model_c_at_reference_activity: (Moment & { reference_activity: number }) | null;
    beta_model_c: Moment & { note: string }; activity_interaction_coefficient: Moment; n_meals_observed: number;
  };
  uncertainty: { posterior_band_width_90: { model_b: number; model_c_at_reference_activity: number | null; unit: string };
    calibration_score_rolling: { window: number; n_reconciled_in_window: number; model_b: number | null; model_c: number | null; unavailable_because?: string } };
  prediction_state: { last_forecast_id: string | null; reconciled?: boolean; twin_version_at_forecast?: number };
  historical_response_state: { version_number: number; parent_version_id: number | null; created_at: string; reconciliation_log_ref: string[] };
  unavailable: string[];
}

export interface Twin {
  twin_id: string; label: string; created_at: string; prior_source: string; prior_scheme: string; gamma_relative_sd: number | null;
  prior_provenance: PriorProvenance; profile: Record<string, unknown>; config: { reference_activity: number; outcome_window_minutes: number; threshold_mg_dl: number };
  is_synthetic: boolean; state: TwinStateView; insight: Record<string, unknown>;
}

export interface ModelForecast {
  p_peak_at_least_180: number; mean_rise_mg_dl: number; sd_mg_dl: number; interval90_rise_mg_dl: [number, number]; description: string;
}

export type ForecastStatus = "pending" | "observed" | "reconciled" | "excluded";

export interface Forecast {
  forecast_id: string; event_id: string; meal_time: string; created_at: string; twin_version_at_forecast: number; model_version: string;
  inputs: { carbs_g: number; activity_level: number; baseline_glucose: number; activity_coverage?: number | null; baseline_age_minutes?: number | null;
    trend_slope_30min?: number | null; time_since_last_meal_min?: number | null; meal_time: string; event_id: string };
  model_b: ModelForecast; model_c: ModelForecast; horizon_minutes: number; data_quality: DataQuality;
  engine_provenance: { package_version: string | null; git_commit: string | null; working_tree_dirty: boolean | null; engine: string };
  status: ForecastStatus; observation_id?: string; reconciliation_id?: string; created?: boolean;
}

export interface ForecastList { twin_id: string; total: number; limit: number; offset: number; forecasts: Forecast[] }

export interface Observation {
  observation_id: string; forecast_id: string; observed_through: string; peak_glucose_mg_dl: number | null; peak_glucose_rise_mg_dl: number | null;
  label_peak_at_least_180: boolean | null; window_completeness: number | null; excluded_reason: string | null; kind: string; created?: boolean;
}

export interface ParamChange {
  beta_mean_before: number; beta_mean_after: number; beta_sd_before: number; beta_sd_after: number; beta_sd_ratio: number | null;
  gamma_mean_before?: number; gamma_mean_after?: number; gamma_sd_before?: number; gamma_sd_after?: number; gamma_sd_ratio?: number | null;
}

export interface Reconciliation {
  reconciliation_id: string; forecast_id: string; observation_id: string; outcome: "updated" | "excluded";
  twin_version_before: number; twin_version_after: number; reconciled_at: string;
  metrics: Partial<Record<"model_b" | "model_c", { hit_at_50pct: boolean; brier_component: number; observed_inside_interval90: boolean; standardised_error: number }>> & { reason?: string };
  parameter_change?: { model_b: ParamChange; model_c: ParamChange }; created?: boolean;
}

export interface ParameterRow {
  beta_mean: number; beta_var: number; gamma_mean: number | null; gamma_var: number | null; beta_gamma_cov: number | null;
  noise_variance: number; n_observations_used: number; prior_source: string;
}
export interface HistoryVersion {
  version: number; parent_version: number | null; created_at: string; n_observations: number; reconciliation_id: string | null;
  parameters: { B: ParameterRow; C: ParameterRow };
}
export interface History {
  twin_id: string; reference_activity: number; versions: HistoryVersion[];
  parameter_history: { versions: Array<{ version: number; b_sensitivity_mean: number; b_sensitivity_sd: number; c_beta_mean: number; c_beta_sd: number;
    c_gamma_mean: number; c_gamma_sd: number; c_sensitivity_at_reference_mean: number; c_sensitivity_at_reference_sd: number }> };
  posterior_convergence: { n_observations: number[]; sd: Record<string, number[]>; monotone_non_increasing: Record<string, boolean>; current_over_prior: Record<string, number> };
  hit_rate_trend: { n_reconciled: number; model_b: { overall_hit_rate: number | null }; model_c: { overall_hit_rate: number | null }; note: string };
  exclusions: Array<{ forecast_id: string; reason: string }>;
}

export interface SensitivityPoint { activity_level: number; mean: number; sd: number; interval90: [number, number] }
export interface Sensitivity {
  twin_version: number; model_b: { mean: number; sd: number; interval90: [number, number] }; model_c_curve: SensitivityPoint[];
  gamma_activity_interaction: { mean: number; sd: number; interval90: [number, number] }; n_meals_observed: number; activity_scale: string | null;
  prior_support_warnings: string[];
}

export interface Explanation {
  kind: string; model: string; twin_version_used: number; terms: Record<string, { coefficient_mean: number; contribution_mg_dl: number; contribution_sd_mg_dl: number }>;
  predicted_rise_mg_dl: number; predictive_sd_mg_dl: number; p_peak_at_least_180: number; plain_language: string[];
  variance: { share_parameter_uncertainty: number }; contributing_factors: Array<{ factor: string; text: string }>;
}

export interface WhatIfRow {
  label: string; carbs_g: number; activity_level: number; is_reference: boolean;
  model_b: { p_peak_at_least_180: number; mean_rise_mg_dl: number; delta_p_vs_reference?: number; delta_rise_mg_dl_vs_reference?: number };
  model_c: { p_peak_at_least_180: number; mean_rise_mg_dl: number; delta_p_vs_reference?: number; delta_rise_mg_dl_vs_reference?: number };
}
export interface WhatIf { what_if_id: string; screen_label: string; comparison: { reference: string; twin_version_used: number; rows: WhatIfRow[]; note: string }; prior_support_warnings: string[] }

export interface ReconciliationView {
  reconciled: Array<{ forecast_id: string; meal_time: string; twin_version_after_update: number; observed: { peak_rise_mg_dl: number; peak_at_least_180: boolean };
    model_b: { forecast_p_peak_at_least_180: number; observed_inside_interval90: boolean }; model_c: { forecast_p_peak_at_least_180: number; observed_inside_interval90: boolean } }>;
  pending: Array<{ forecast_id: string; meal_time: string }>; summary: { n_reconciled: number; n_pending: number };
}

export interface CreateTwinBody { label: string; prior?: { source: "synthetic_demo" | "prior_file"; name?: string; prior_scheme?: "empirical_bayes" | "blueprint"; gamma_relative_sd?: number };
  glycaemic_group?: "healthy" | "pre-diabetes" | "t2d"; reference_activity?: number }
export interface ForecastBody { event_id: string; meal_time: string; carbs_g: number; activity_level: number; baseline_glucose: number;
  activity_coverage?: number; baseline_age_minutes?: number; trend_slope_30min?: number; time_since_last_meal_min?: number }
export interface ObserveBody { forecast_id: string; observed_through: string; peak_glucose_mg_dl?: number; window_completeness?: number; excluded_reason?: string }
export interface WhatIfBody { baseline_glucose: number; scenarios: Array<{ label?: string; carbs_g: number; activity_level: number }> }

/** Accounts and the caller's own twins (backend: /auth/*, GET /twins). The session itself lives in an HttpOnly cookie that page scripts cannot read. */
export interface AuthUser { id: string; name: string; email: string | null; is_guest: boolean; created_at: string }
export interface TwinSummary { twin_id: string; label: string; created_at: string; prior_source: string; prior_scheme: string; is_synthetic: boolean; current_version: number }
export interface RegisterBody { name: string; email: string; password: string }
export interface LoginBody { email: string; password: string }
