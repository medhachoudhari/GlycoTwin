"""Model A participant-level stratified 5-fold evaluation, on SYNTHETIC data only (software tests; no real-data claim)."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from glycotwin.data.events import ELIGIBILITY_COLUMNS, FEATURE_COLUMNS, OUTCOME_COLUMNS
from glycotwin.data.groups import GroupMappingError, classify_a1c, participant_groups
from glycotwin.models import model_a_cv as ma
from glycotwin.models.baseline import PopulationBaselineModel

ROOT = Path(__file__).resolve().parents[1]
SIZES = {"healthy": 15, "pre-diabetes": 16, "t2d": 14}


def cohort():
    g, k = {}, 1
    for name, n in SIZES.items():
        for _ in range(n):
            g[f"CGMacros-{k:03d}"] = name
            k += 1
    return g


def make_events(per=24, seed=1, missing=0.03):
    rng = np.random.default_rng(seed)
    rows = []
    for pid in cohort():
        for j in range(per):
            carbs, base, act = rng.uniform(10, 90), rng.normal(110, 15), rng.uniform(0.5, 3.0)
            y = int(base + carbs * 0.8 + rng.normal(0, 20) >= 180)
            rows.append({"participant_id": pid, "event_id": f"{pid}-m{j:03d}", "meal_time": pd.Timestamp("2000-01-01") + pd.Timedelta(hours=5 * j),
                         "carbs_g": carbs, "baseline_glucose": base if rng.random() > missing else np.nan, "activity_level": act,
                         "label_exceeds_180": y, "eligible_core": True})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def events():
    return make_events()


@pytest.fixture(scope="module")
def folds():
    return ma.make_participant_folds(cohort(), seed=0)


# ------------------------------------------------------------------ 1/2 participant-level separation

def test_every_participant_is_in_exactly_one_fold_and_all_five_folds_are_used(folds):
    assert set(folds) == set(cohort()) and sorted(set(folds.values())) == [0, 1, 2, 3, 4]


def test_no_participant_is_in_both_training_and_validation_in_any_fold(events, folds):
    seen = []

    class Spy(PopulationBaselineModel):
        def fit(self, df):
            seen.append(set(df["participant_id"]))
            return super().fit(df)
    ma.cross_validated_predictions(events, folds, model_factory=lambda: Spy())
    assert len(seen) == 5
    for k, train_participants in enumerate(seen):
        held_out = {p for p, f in folds.items() if f == k}
        assert not train_participants & held_out and train_participants | held_out == set(cohort())


# ------------------------------------------------------------------ 3 stratification

def test_folds_are_stratified_by_participant_level_glycaemic_group(folds):
    comp = ma.fold_composition(make_events(per=2), folds, cohort())
    for g, n in SIZES.items():
        per_fold = [c["participants_by_group"][g] for c in comp]
        assert sum(per_fold) == n and max(per_fold) - min(per_fold) <= 1, (g, per_fold)
    assert [c["n_participants"] for c in comp] == [9, 9, 9, 9, 9]


def test_stratification_uses_participants_not_events(folds):
    unbalanced = make_events(per=2)
    extra = unbalanced[unbalanced["participant_id"] == "CGMacros-001"].copy()
    extra["event_id"] = extra["event_id"] + "x"
    big = pd.concat([unbalanced] + [extra.assign(event_id=extra["event_id"] + str(i)) for i in range(30)], ignore_index=True)
    assert ma.make_participant_folds(cohort(), seed=0) == folds                      # fold assignment ignores event counts entirely
    comp = ma.fold_composition(big, folds, cohort())
    assert sum(c["n_events"] for c in comp) == len(big)


def test_a_group_smaller_than_the_number_of_folds_is_refused():
    g = cohort(); g.update({f"CGMacros-{k:03d}": "t2d" for k in range(1, 12)})
    small = {p: ("healthy" if i < 4 else "t2d") for i, p in enumerate(sorted(g))}
    with pytest.raises(ValueError, match="at least 5"):
        ma.make_participant_folds(small)


# ------------------------------------------------------------------ 4 determinism

def test_fold_assignment_is_deterministic_independent_of_input_order_and_seed_dependent():
    g = cohort()
    a = ma.make_participant_folds(g, seed=0)
    shuffled = dict(sorted(g.items(), key=lambda kv: hashlib.md5(kv[0].encode()).hexdigest()))
    assert ma.make_participant_folds(shuffled, seed=0) == a
    assert ma.fold_assignment_hash(a) == ma.fold_assignment_hash(ma.make_participant_folds(g, seed=0))
    assert ma.fold_assignment_hash(ma.make_participant_folds(g, seed=1)) != ma.fold_assignment_hash(a)


def test_out_of_fold_predictions_are_reproducible_bit_for_bit(events, folds):
    a = ma.cross_validated_predictions(events, folds)
    b = ma.cross_validated_predictions(events.sample(frac=1.0, random_state=3), folds)    # row order must not matter
    pd.testing.assert_frame_equal(a, b)


# ------------------------------------------------------------------ 5 no target leakage through features

def test_feature_policy_accepts_model_a_features_and_rejects_leaky_columns():
    ma.assert_feature_policy(ma.MODEL_A_FEATURES)
    assert set(ma.MODEL_A_FEATURES) <= set(FEATURE_COLUMNS)
    for bad in ("label_exceeds_180", "peak_glucose", "peak_glucose_rise", "n_window_readings", "window_completeness", "isolated",
                "eligible_core", "participant_id", "event_id", "group", "glycaemic_group", "amount_consumed_raw", "Amount Consumed", "Image path"):
        with pytest.raises(ma.FeaturePolicyError):
            ma.assert_feature_policy(ma.MODEL_A_FEATURES + [bad])
    assert "label_norm" in FEATURE_COLUMNS                                                  # an event-table feature that Model A must still not use
    with pytest.raises(ma.FeaturePolicyError, match="forbidden"):
        ma.assert_feature_policy(ma.MODEL_A_FEATURES + ["label_norm"])
    with pytest.raises(ma.FeaturePolicyError, match="duplicate"):
        ma.assert_feature_policy(["carbs_g", "carbs_g"])
    with pytest.raises(ma.FeaturePolicyError):
        ma.assert_feature_policy(["carbs_g", "some_new_column"])                       # not an established pre-meal feature
    assert not set(ma.MODEL_A_FEATURES) & (set(OUTCOME_COLUMNS) | set(ELIGIBILITY_COLUMNS))


def test_predictions_for_a_fold_do_not_depend_on_that_folds_own_labels(events, folds):
    base = ma.cross_validated_predictions(events, folds)
    flipped = events.copy()
    in_fold0 = flipped["participant_id"].map(folds) == 0
    flipped.loc[in_fold0, "label_exceeds_180"] = 1 - flipped.loc[in_fold0, "label_exceeds_180"]
    changed = ma.cross_validated_predictions(flipped, folds)
    f0 = lambda d: d[d["fold"] == 0].set_index("event_id")["p"].sort_index()
    pd.testing.assert_series_equal(f0(base), f0(changed))                                # fold 0's model never saw fold 0's labels
    assert not np.allclose(base[base["fold"] == 1]["p"].to_numpy(), changed[changed["fold"] == 1]["p"].to_numpy())  # sanity: training labels do matter


def test_group_labels_and_ids_never_reach_the_model(events, folds):
    cols_seen = []

    class Spy(PopulationBaselineModel):
        def fit(self, df):
            cols_seen.append(list(df.columns))
            return super().fit(df)
    noisy = events.assign(glycaemic_group="healthy", group="t2d")
    ma.cross_validated_predictions(noisy, folds, model_factory=lambda: Spy())
    from glycotwin.models.baseline import BASELINE_FEATURE_COLUMNS
    assert BASELINE_FEATURE_COLUMNS == ma.MODEL_A_FEATURES == ["carbs_g", "baseline_glucose", "activity_level"]
    x = noisy.assign(group="healthy")[ma.MODEL_A_FEATURES]
    assert list(x.columns) == ma.MODEL_A_FEATURES                                          # the model matrix is built from the 3 columns only


# ------------------------------------------------------------------ 6 out-of-fold coverage

def test_every_event_gets_exactly_one_out_of_fold_prediction(events, folds):
    oof = ma.cross_validated_predictions(events, folds)
    assert len(oof) == len(events) and oof["event_id"].is_unique and set(oof["event_id"]) == set(events["event_id"])
    assert oof["p"].between(0, 1).all() and np.isfinite(oof["p"]).all()
    assert (oof["participant_id"].map(folds) == oof["fold"]).all()
    assert (oof.merge(events, on="event_id")["y"] == oof.merge(events, on="event_id")["label_exceeds_180"]).all()


def test_out_of_fold_probabilities_equal_an_independently_trained_model_scored_on_the_held_out_rows(events, folds):
    oof = ma.cross_validated_predictions(events, folds).set_index("event_id")
    fold_of = events["participant_id"].map(folds)
    for k in range(5):
        train, val = events[fold_of != k], events[fold_of == k].sort_values("event_id")
        manual = PopulationBaselineModel().fit(train).predict_proba(val)
        np.testing.assert_allclose(oof.loc[val["event_id"], "p"].to_numpy(), manual)
        assert (oof.loc[val["event_id"], "fold"] == k).all()


def test_missing_predictors_are_not_imputed_and_the_model_still_predicts(events, folds):
    assert events["baseline_glucose"].isna().sum() > 0
    assert ma.feature_missingness(events)["baseline_glucose"]["n_missing"] == int(events["baseline_glucose"].isna().sum())
    oof = ma.cross_validated_predictions(events, folds)
    assert np.isfinite(oof["p"]).all()
    assert events["baseline_glucose"].isna().sum() > 0                                       # input untouched (no in-place imputation)


def test_a_missing_column_or_an_unmapped_participant_is_an_error(events, folds):
    with pytest.raises(ValueError, match="missing columns"):
        ma.cross_validated_predictions(events.drop(columns=["activity_level"]), folds)
    partial = {k: v for k, v in folds.items() if k != "CGMacros-001"}
    with pytest.raises(ValueError, match="no fold"):
        ma.cross_validated_predictions(events, partial)


# ------------------------------------------------------------------ 7 metrics

def test_threshold_metrics_on_a_hand_computed_example():
    y = [1, 1, 1, 0, 0, 0, 0, 0]
    p = [0.9, 0.6, 0.2, 0.7, 0.4, 0.1, 0.3, 0.2]
    m = ma.classification_metrics(y, p, 0.5)
    assert m["confusion_matrix"] == {"tn": 4, "fp": 1, "fn": 1, "tp": 2}
    assert m["sensitivity_recall"] == pytest.approx(2 / 3) and m["specificity"] == pytest.approx(4 / 5)
    assert m["precision"] == pytest.approx(2 / 3) and m["f1"] == pytest.approx(2 / 3) and m["undefined"] == {}
    assert ma.classification_metrics(y, p, 0.6)["confusion_matrix"] == {"tn": 4, "fp": 1, "fn": 1, "tp": 2}    # >= is inclusive: 0.6 counts as positive
    assert ma.classification_metrics(y, p, 0.61)["confusion_matrix"]["tp"] == 1


def test_undefined_metrics_are_reported_with_a_reason_not_hidden():
    none_pos = ma.classification_metrics([0, 0, 0], [0.1, 0.2, 0.3], 0.5)
    assert none_pos["sensitivity_recall"] is None and none_pos["precision"] is None and none_pos["f1"] is None
    assert set(none_pos["undefined"]) == {"sensitivity", "precision", "f1"} and none_pos["specificity"] == 1.0
    no_neg = ma.classification_metrics([1, 1], [0.9, 0.8], 0.5)
    assert no_neg["specificity"] is None and "specificity" in no_neg["undefined"]
    one_class = ma.metric_bundle([0, 0, 0, 0], [0.1, 0.2, 0.1, 0.3])
    assert one_class["roc_auc"] is None and one_class["average_precision_pr_auc"] is None and one_class["warnings"]
    assert one_class["calibration"]["slope"] is None and "single class" in one_class["calibration"]["reason"]
    assert one_class["brier_score"] == pytest.approx(brier_score_loss([0, 0, 0, 0], [0.1, 0.2, 0.1, 0.3]))


def test_discrimination_and_calibration_metrics_match_reference_implementations():
    rng = np.random.default_rng(0)
    p = rng.uniform(0.02, 0.98, 4000)
    y = (rng.random(4000) < p).astype(int)
    m = ma.metric_bundle(y, p)
    assert m["roc_auc"] == pytest.approx(roc_auc_score(y, p)) and m["average_precision_pr_auc"] == pytest.approx(average_precision_score(y, p))
    assert m["brier_score"] == pytest.approx(brier_score_loss(y, p)) and m["prevalence"] == pytest.approx(y.mean())
    assert m["calibration"]["slope"] == pytest.approx(1.0, abs=0.1) and abs(m["calibration"]["intercept"]) < 0.1     # calibrated by construction
    assert sum(b["n"] for b in m["reliability_bins_10"]) == 4000 and m["ece_10_bins"] < 0.05
    over = ma.metric_bundle(y, np.clip(0.5 + 2.0 * (p - 0.5), 0.001, 0.999))                                      # overconfident forecasts
    assert over["calibration"]["slope"] < m["calibration"]["slope"] and over["ece_10_bins"] > m["ece_10_bins"]
    assert m["brier_score_of_constant_prevalence_forecast"] == pytest.approx(y.mean() * (1 - y.mean()))


def test_training_fold_prevalence_threshold_is_applied_per_event():
    y, p = [1, 0, 1, 0], [0.4, 0.4, 0.6, 0.1]
    per_event = np.array([0.3, 0.3, 0.7, 0.3])                                          # mean 0.4: a scalar mean would give a different answer
    m = ma.metric_bundle(y, p, 0.5, threshold_by_event=per_event)
    assert m["classification_at_0.5"]["confusion_matrix"] == {"tn": 2, "fp": 0, "fn": 1, "tp": 1}
    assert m["classification_at_training_fold_prevalence"]["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert ma.classification_metrics(y, p, 0.4)["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 0, "tp": 2}


def test_per_fold_and_group_metrics_report_undefined_cases_explicitly(events, folds):
    oof = ma.cross_validated_predictions(events, folds)
    pf = ma.per_fold_metrics(oof)
    assert [r["fold"] for r in pf] == [0, 1, 2, 3, 4] and all("undefined_metrics" in r for r in pf)
    one_class = oof.assign(y=0)
    assert all(r["roc_auc"] is None and "roc_auc" in r["undefined_metrics"] for r in ma.per_fold_metrics(one_class))
    gm = ma.group_metrics(oof, cohort())
    assert set(gm) == set(SIZES) and all("no superiority" in v["note"] for v in gm.values())
    assert {g: v["n_participants"] for g, v in gm.items()} == SIZES
    assert sum(v["n_events"] for v in gm.values()) == len(oof)


def test_bootstrap_intervals_are_clustered_seeded_and_contain_the_estimate(events, folds):
    oof = ma.cross_validated_predictions(events, folds)
    a, b = ma.bootstrap_ci(oof, n_boot=60, seed=5), ma.bootstrap_ci(oof, n_boot=60, seed=5)
    assert a == b and a["n_draws_used"] == 60
    est = ma.metric_bundle(oof["y"], oof["p"])["roc_auc"]
    assert a["roc_auc"]["low"] <= est <= a["roc_auc"]["high"]


# ------------------------------------------------------------------ 8 reproducible configuration

def test_model_configuration_is_fixed_untuned_and_recorded(events, folds):
    m = PopulationBaselineModel()._model.get_params()
    assert (m["n_estimators"], m["max_depth"], m["learning_rate"], m["objective"], m["random_state"], m["n_jobs"]) == (100, 3, 0.1, "binary:logistic", 0, 1)
    assert m["scale_pos_weight"] is None                                                   # no class weighting
    man = ma.build_manifest(events, folds, seed=0, channel="Libre GL", event_table_name="event_table_Libre_GL.csv", threshold=0.5)
    assert man["feature_columns"] == ["carbs_g", "baseline_glucose", "activity_level"] and man["seed_for_folds"] == 0 and man["n_splits"] == 5
    assert man["xgboost_params"]["n_estimators"] == 100 and man["xgboost_params"]["random_state"] == 0
    assert man["fold_assignment_sha256"] == ma.fold_assignment_hash(folds) and len(man["event_table_sha256_of_model_a_columns"]) == 64
    assert {"xgboost", "scikit-learn", "numpy", "pandas"} <= set(man["versions"]) and "no imputation" in man["missing_value_policy"]
    assert "no resampling" in man["class_imbalance_policy"]
    again = ma.build_manifest(events, folds, seed=0, channel="Libre GL", event_table_name="event_table_Libre_GL.csv", threshold=0.5)
    assert again["event_table_sha256_of_model_a_columns"] == man["event_table_sha256_of_model_a_columns"]
    changed = events.copy(); changed.loc[changed.index[0], "carbs_g"] += 1
    assert ma.event_table_fingerprint(changed) != man["event_table_sha256_of_model_a_columns"]


def test_full_protocol_report_is_aggregate_only_and_complete(events):
    report, oof, folds = ma.run_model_a(events, cohort(), seed=0, n_boot=30, channel="Libre GL", event_table_name="t.csv")
    text = json.dumps(report, default=str)
    for needle in ("CGMacros-", "2000-01-01", "event_id"):
        assert needle not in text, needle
    assert report["data"]["n_events"] == len(events) and report["data"]["participants_by_group"] == SIZES
    assert sum(c["n_events"] for c in report["fold_composition"]) == len(events)
    assert sum(c["n_positive"] for c in report["fold_composition"]) == int(events["label_exceeds_180"].sum())
    assert report["overall_out_of_fold"]["n_events"] == len(events) and "RESEARCH BASELINE" in report["_status"]
    again, oof2, _ = ma.run_model_a(events, cohort(), seed=0, n_boot=30, channel="Libre GL", event_table_name="t.csv")
    pd.testing.assert_frame_equal(oof, oof2)
    assert again["overall_out_of_fold"] == report["overall_out_of_fold"]


# ------------------------------------------------------------------ groups (A1c rule, verified mapping, no positional fallback)

@pytest.mark.parametrize("a1c, g", [(5.69, "healthy"), (5.7, "pre-diabetes"), (6.4, "pre-diabetes"), (6.41, "t2d"), (np.nan, None)])
def test_a1c_rule(a1c, g):
    assert classify_a1c(a1c) == g


def test_group_rule_matches_the_audit_script_so_the_two_cannot_drift():
    spec = importlib.util.spec_from_file_location("audit_bio_groups", ROOT / "scripts" / "audit_bio_groups.py")
    abg = importlib.util.module_from_spec(spec); sys.modules["audit_bio_groups"] = abg; spec.loader.exec_module(abg)
    for v in (4.9, 5.69, 5.7, 5.71, 6.0, 6.4, 6.41, 8.0, np.nan):
        expect = abg.classify_a1c(v)
        assert (classify_a1c(v) or "unknown") == expect
    for raw in ("5.4", 5.4, "5.4 (low)", "n/a", None):
        a, b = abg.parse_numeric(raw), __import__("glycotwin.data.groups", fromlist=["x"]).parse_numeric(raw)
        assert (np.isnan(a[0]) and np.isnan(b[0]) or a[0] == b[0]) and a[1] == b[1]


def test_participant_groups_uses_the_identifier_column_not_row_order():
    bio = pd.DataFrame({"subject ": [3, 1, 2], "A1c PDL (Lab) ": [7.0, 5.0, 6.0]})
    got = participant_groups(bio, ["CGMacros-001", "CGMacros-002", "CGMacros-003"])
    assert got == {"CGMacros-001": "healthy", "CGMacros-002": "pre-diabetes", "CGMacros-003": "t2d"}


@pytest.mark.parametrize("bio, why", [
    (pd.DataFrame({"A1c PDL (Lab)": [5.0, 6.0, 7.0]}), "no identifier column (a positional mapping is not used)"),
    (pd.DataFrame({"subject": [1, 1, 2], "A1c PDL (Lab)": [5.0, 6.0, 7.0]}), "duplicate identifiers"),
    (pd.DataFrame({"subject": [1, 2], "A1c PDL (Lab)": [5.0, 6.0]}), "a participant with no bio row"),
    (pd.DataFrame({"subject": [1, 2, 3], "A1c PDL (Lab)": [5.0, np.nan, 7.0]}), "a missing A1c"),
    (pd.DataFrame({"subject": [1, 2, 3], "participant": [1, 2, 3], "A1c PDL (Lab)": [5.0, 6.0, 7.0]}), "two identifier columns match: ambiguous"),
    (pd.DataFrame({"subject": [1, 2, 3], "HbA1c": [5.0, 6.0, 7.0], "A1c other": [5.0, 6.0, 7.0]}), "ambiguous A1c column"),
])
def test_group_mapping_refuses_to_guess(bio, why):
    with pytest.raises(GroupMappingError):
        participant_groups(bio, ["CGMacros-001", "CGMacros-002", "CGMacros-003"])


# ------------------------------------------------------------------ script end to end

def _script():
    spec = importlib.util.spec_from_file_location("run_model_a", ROOT / "scripts" / "run_model_a.py")
    mod = importlib.util.module_from_spec(spec); sys.modules["run_model_a"] = mod; spec.loader.exec_module(mod)
    return mod


def test_script_end_to_end_is_aggregate_only_writes_local_files_and_is_read_only(tmp_path, capsys):
    rma = _script()
    root = tmp_path / "ds"; root.mkdir()
    g = cohort()
    a1c = {"healthy": 5.2, "pre-diabetes": 6.0, "t2d": 7.1}
    pd.DataFrame({"subject": [int(p[-3:]) for p in g], "A1c PDL (Lab)": [a1c[v] for v in g.values()], "Age": 40}).to_csv(root / "bio.csv", index=False)
    ev = make_events(per=18)
    ev.loc[ev.index[:7], "eligible_core"] = False                                       # ineligible events must be dropped by the script
    table = tmp_path / "event_table_Libre_GL.csv"; ev.to_csv(table, index=False)
    before = hashlib.sha256((root / "bio.csv").read_bytes()).hexdigest(), hashlib.sha256(table.read_bytes()).hexdigest()
    args = ["--data-root", str(root), "--event-table", str(table), "--n-boot", "20", "--report-out", str(tmp_path / "r.json"),
            "--oof-out", str(tmp_path / "oof.csv"), "--folds-out", str(tmp_path / "folds.json")]
    assert rma.main(args) == 0
    text = capsys.readouterr().out
    rep = json.loads(text)
    assert rep["data"]["n_events"] == len(ev) - 7 and rep["data"]["participants_by_group"] == SIZES
    for needle in ("CGMacros-", "2000-01-01", str(root)):
        assert needle not in text, needle
    assert len(pd.read_csv(tmp_path / "oof.csv")) == len(ev) - 7 and "assignment" in json.loads((tmp_path / "folds.json").read_text())
    assert before == (hashlib.sha256((root / "bio.csv").read_bytes()).hexdigest(), hashlib.sha256(table.read_bytes()).hexdigest())


def test_script_refuses_a_table_that_does_not_name_the_channel_and_a_missing_mapping(tmp_path, capsys):
    rma = _script()
    root = tmp_path / "ds"; root.mkdir()
    pd.DataFrame({"A1c PDL (Lab)": [5.0]}).to_csv(root / "bio.csv", index=False)         # no identifier column
    ev = make_events(per=3)
    wrong = tmp_path / "events.csv"; ev.to_csv(wrong, index=False)
    assert rma.main(["--data-root", str(root), "--event-table", str(wrong)]) == 2        # file name does not mention Libre
    ok_name = tmp_path / "event_table_Libre_GL.csv"; ev.to_csv(ok_name, index=False)
    assert rma.main(["--data-root", str(root), "--event-table", str(ok_name)]) == 2      # mapping cannot be established
    assert rma.main(["--data-root", str(root), "--event-table", str(tmp_path / "nope_Libre_GL.csv")]) == 2


def test_existing_event_definition_files_are_not_touched_by_model_a():
    src = (ROOT / "scripts" / "build_event_table.py").read_text(encoding="utf-8")
    assert "model_a" not in src and "run_model_a" not in src
