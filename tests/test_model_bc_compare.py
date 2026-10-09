"""Paired Model B vs Model C comparison: integrity refusals, statistics mechanics, script behaviour, reliability SVG. SYNTHETIC forecasts only."""
import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glycotwin.models.model_bc_compare import ComparisonIntegrityError, paired_report, verify_matched
from glycotwin.models.reliability_svg import reliability_bins, reliability_svg

ROOT = Path(__file__).resolve().parents[1]


def make_pair(n_part=12, per=8, seed=0, c_better=False):
    rng = np.random.default_rng(seed)
    rows_b, rows_c = [], []
    for k in range(n_part):
        for j in range(per):
            rise = float(rng.normal(60, 30))
            base = 120.0
            y = int(base + rise >= 180)
            pb = float(np.clip(0.5 + 0.004 * (rise - 60) + rng.normal(0, 0.15), 0.02, 0.98))
            pc = float(np.clip(pb + (0.03 * (2 * y - 1) if c_better else rng.normal(0, 0.03)), 0.02, 0.98))
            common = {"event_id": f"e{k}_{j}", "participant_id": f"P{k}", "fold": k % 5, "y": y, "rise": rise, "n_personal_before": j,
                      "interval90_low": 0.0, "interval90_high": 120.0}
            mb, mc = rise + rng.normal(-9, 25), rise + rng.normal(-8, 25)
            rows_b.append({**common, "p": pb, "mean_rise": mb, "p_frozen_prior": 0.5, "mean_rise_frozen_prior": 60.0})
            rows_c.append({**common, "p": pc, "mean_rise": mc, "p_frozen_prior": 0.5, "mean_rise_frozen_prior": 60.0, "activity": float(rng.uniform(0, 1))})
    return pd.DataFrame(rows_b), pd.DataFrame(rows_c)


# ------------------------------------------------------------------ refusals

def test_matched_pair_is_accepted_and_counts_reported():
    b, c = make_pair()
    info = verify_matched(b, c, expected_events=96, expected_participants=12)
    assert info["n_events"] == 96 and info["n_participants"] == 12 and info["same_folds"] and info["same_labels"]


def mutate(which):
    b, c = make_pair()
    if which == "missing_event":
        c = c.iloc[1:]
    elif which == "different_event_id":
        c.loc[c.index[0], "event_id"] = "zzz"
    elif which == "participant_changed":
        c.loc[c.index[0], "participant_id"] = "P_other"
    elif which == "participant_missing":
        b, c = b[b["participant_id"] != "P0"], c[c["participant_id"] != "P0"]
        c = c.copy()
        b = pd.concat([b, make_pair()[0].query("participant_id == 'P0'").assign(event_id=lambda d: d["event_id"] + "x")])
    elif which == "fold_changed":
        c.loc[c.index[3], "fold"] = (c.loc[c.index[3], "fold"] + 1) % 5
    elif which == "participant_moved_fold":                                # a WHOLE participant sits in another fold in C
        c.loc[c["participant_id"] == "P1", "fold"] = (c.loc[c["participant_id"] == "P1", "fold"] + 1) % 5
    elif which == "label_changed":
        c.loc[c.index[2], "y"] = 1 - c.loc[c.index[2], "y"]
    elif which == "rise_changed":
        c.loc[c.index[5], "rise"] += 1.0
    elif which == "duplicate_id":
        c.loc[c.index[1], "event_id"] = c.loc[c.index[0], "event_id"]
    elif which == "nan_probability":
        c.loc[c.index[0], "p"] = np.nan
    elif which == "missing_column":
        c = c.drop(columns=["fold"])
    return b, c


@pytest.mark.parametrize("which, text", [
    ("missing_event", "event sets differ"), ("different_event_id", "event sets differ"), ("participant_changed", "different participants"),
    ("fold_changed", "more than one fold"), ("participant_moved_fold", "different folds"), ("label_changed", "different observed labels"), ("rise_changed", "observed rises differ"),
    ("duplicate_id", "duplicated"), ("nan_probability", "non-finite"), ("missing_column", "missing columns")])
def test_mismatches_are_refused(which, text):
    b, c = mutate(which)
    with pytest.raises(ComparisonIntegrityError, match=text):
        verify_matched(b, c)
    with pytest.raises(ComparisonIntegrityError):
        paired_report(b, c, n_boot=20)                                  # the report itself refuses, not just the helper


def test_expected_counts_are_enforced():
    b, c = make_pair()
    with pytest.raises(ComparisonIntegrityError, match="expected 963 events"):
        verify_matched(b, c, expected_events=963)
    with pytest.raises(ComparisonIntegrityError, match="expected 34 participants"):
        verify_matched(b, c, expected_participants=34)


def test_participant_set_difference_is_refused_even_when_events_match():
    b, c = make_pair()
    c = c.copy()
    c["participant_id"] = c["participant_id"].replace({"P1": "P0"})       # same events, but a different participant set and mapping
    with pytest.raises(ComparisonIntegrityError):
        verify_matched(b, c)


# ------------------------------------------------------------------ statistics

def test_report_structure_signs_and_reproducibility():
    b, c = make_pair()
    r1, r2 = paired_report(b, c, n_boot=200, seed=0), paired_report(b, c, n_boot=200, seed=0)
    assert r1 == r2                                                      # seeded
    assert set(r1["metrics"]) >= {"roc_auc", "pr_auc", "brier", "log_loss", "ece10", "ece5", "rise_mae_mg_dl", "mean_rise_error_mg_dl", "coverage_90pct_interval"}
    m = r1["metrics"]["brier"]
    sb = float(((b["p"] - b["y"]) ** 2).mean()); sc = float(((c["p"] - c["y"]) ** 2).mean())
    assert m["model_b"] == pytest.approx(sb) and m["model_c"] == pytest.approx(sc) and m["difference_c_minus_b"] == pytest.approx(sc - sb)
    lo, hi = m["ci95"]
    assert m["ci_excludes_zero"] == bool(lo > 0 or hi < 0)
    err = r1["metrics"]["mean_rise_error_mg_dl"]
    assert err["model_b"] == pytest.approx(float((b["mean_rise"] - b["rise"]).mean()))
    assert r1["metrics"]["rise_mae_mg_dl"]["model_c"] == pytest.approx(float((c["mean_rise"] - c["rise"]).abs().mean()))
    assert r1["n_intervals_reported"] == len(r1["metrics"]) and 0 <= r1["n_intervals_excluding_zero"] <= r1["n_intervals_reported"]
    assert "not clinically validated" in r1["_status"].lower() and "no claim of superiority" in r1["interpretation_limits"].lower()
    assert r1["not_computed"]


def test_a_model_that_is_clearly_better_gets_an_interval_excluding_zero_and_identical_models_do_not():
    b, c = make_pair(n_part=20, per=10, c_better=True)
    r = paired_report(b, c, n_boot=300, seed=1)
    assert r["metrics"]["brier"]["difference_c_minus_b"] < 0 and r["metrics"]["brier"]["ci_excludes_zero"]
    same = paired_report(b, b.assign(activity=0.5), n_boot=100, seed=1)
    assert same["activity_tertiles_exploratory"]["tertiles"]["middle"]["n_events"] == 0         # constant activity: empty tertile handled
    for k in ("brier", "log_loss", "roc_auc", "ece10", "rise_mae_mg_dl", "mean_rise_error_mg_dl"):
        assert same["metrics"][k]["difference_c_minus_b"] == pytest.approx(0.0, abs=1e-12)
        assert not same["metrics"][k]["ci_excludes_zero"]


def test_coverage_uses_the_stored_interval():
    b, c = make_pair()
    r = paired_report(b, c, n_boot=50)
    cov = float(((b["rise"] >= 0) & (b["rise"] <= 120)).mean())
    cv = r["metrics"]["coverage_90pct_interval"]
    assert cv["model_b"] == pytest.approx(cov) and cv["nominal"] == 0.90
    cov_c = float(((c["rise"] >= 0) & (c["rise"] <= 120)).mean())
    assert cv["model_c"] == pytest.approx(cov_c) and cv["difference_c_minus_b"] == pytest.approx(cov_c - cov)       # C minus B, not B minus C
    narrow = c.assign(interval90_high=20.0)
    assert paired_report(b, narrow, n_boot=50)["metrics"]["coverage_90pct_interval"]["difference_c_minus_b"] < 0


def test_participant_level_mae_counts_partition_the_participants_and_use_the_tolerance():
    b, c = make_pair()
    r = paired_report(b, c, n_boot=50, mae_tolerance_mg_dl=1.0)
    pl = r["participant_level_rise_mae"]
    assert pl["c_improved_by_more_than_tolerance"] + pl["c_worsened_by_more_than_tolerance"] + pl["within_tolerance"] == pl["n_participants"] == 12
    wide = paired_report(b, c, n_boot=50, mae_tolerance_mg_dl=1e6)["participant_level_rise_mae"]
    assert wide["within_tolerance"] == 12


def test_exploratory_tables_present_labelled_and_consistent():
    b, c = make_pair()
    r = paired_report(b, c, n_boot=50)
    t = r["activity_tertiles_exploratory"]
    assert "exploratory" in t["definition"] and sum(x["n_events"] for x in t["tertiles"].values()) == len(b)
    assert set(t["tertiles"]) == {"low", "middle", "high"}
    st = r["personal_observation_stage_exploratory"]
    assert sum(v["n_events"] for k, v in st.items() if not k.startswith("_")) == len(b)
    noact = paired_report(b, c.drop(columns=["activity"]), n_boot=50)
    assert noact["activity_tertiles_exploratory"] is None


def test_frozen_prior_section_present_for_both_models():
    b, c = make_pair()
    f = paired_report(b, c, n_boot=50)["frozen_prior_comparisons"]
    for m in ("model_b", "model_c"):
        assert set(f[m]) == {"brier", "log_loss", "mae_rise"} and "ci_low" in f[m]["brier"]


# ------------------------------------------------------------------ reliability bins and SVG

def test_reliability_bins_are_aggregate_and_correct():
    y = np.array([0, 0, 1, 1, 1, 0]); p = np.array([0.05, 0.15, 0.55, 0.95, 0.85, 0.65])
    bins = reliability_bins(y, p, 10)
    assert len(bins) == 10 and sum(b["n"] for b in bins) == 6
    nz = [b for b in bins if b["n"]]
    assert all(set(b) == {"lower", "upper", "n", "mean_predicted", "mean_observed"} for b in bins)
    assert nz[0]["mean_observed"] == 0.0 and nz[0]["mean_predicted"] == pytest.approx(0.05)


def test_reliability_svg_is_valid_deterministic_accessible_and_distinguishes_series():
    b, c = make_pair()
    series = {"Model B": reliability_bins(b["y"], b["p"]), "Model C": reliability_bins(c["y"], c["p"])}
    svg = reliability_svg(series, title="T", subtitle="sub")
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    assert svg == reliability_svg(series, title="T", subtitle="sub")
    assert "Model B" in svg and "Model C" in svg and "T" in svg
    assert "<circle" in svg and "<rect" in svg                             # different marker shapes, not colour alone
    assert 'stroke="#c4511f"' in svg and 'stroke-dasharray="6 3"' in svg          # the second series is a dashed line, not only another colour
    assert svg.count("stroke-dasharray") >= 2
    assert "P0" not in svg and "e0_0" not in svg                           # no participant or event identifiers


def test_reliability_svg_escapes_markup_in_labels():
    svg = reliability_svg({"A<b>&": reliability_bins([0, 1], [0.2, 0.8])}, title="x<y")
    ET.fromstring(svg)                                                     # still well-formed
    assert "<b>" not in svg


# ------------------------------------------------------------------ script

def load_script():
    spec = importlib.util.spec_from_file_location("compare_models_b_c", ROOT / "scripts" / "compare_models_b_c.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_pair(tmp_path, b, c, bname="model_b_sequential_forecasts_Libre_GL_activity_eligible.csv", cname="model_c_sequential_forecasts_Libre_GL.csv"):
    pb, pc = tmp_path / bname, tmp_path / cname
    b.to_csv(pb, index=False); c.to_csv(pc, index=False)
    return pb, pc


def test_script_runs_aggregate_only_and_never_modifies_inputs(tmp_path, capsys):
    b, c = make_pair()
    pb, pc = write_pair(tmp_path, b, c)
    before = (pb.read_bytes(), pc.read_bytes())
    rep, svg = tmp_path / "rep.json", tmp_path / "rel.svg"
    rc = load_script().main(["--model-b", str(pb), "--model-c", str(pc), "--report-out", str(rep), "--svg-out", str(svg),
                             "--n-boot", "50", "--expect-events", "96", "--expect-participants", "12"])
    shown = capsys.readouterr().out
    assert rc == 0 and json.loads(shown)["integrity"]["n_events"] == 96
    assert (pb.read_bytes(), pc.read_bytes()) == before
    assert json.loads(rep.read_text())["channel"] == "Libre GL" and ET.fromstring(svg.read_text())
    assert "P0" not in shown and "e0_0" not in shown                       # no participant or event identifiers


def test_script_exit_codes(tmp_path, capsys):
    mod = load_script()
    b, c = make_pair()
    pb, pc = write_pair(tmp_path, b, c)
    assert mod.main(["--model-b", str(tmp_path / "none.csv"), "--model-c", str(pc)]) == 2
    nb, nc = write_pair(tmp_path, b, c, bname="model_b_plain.csv", cname="c2.csv")
    assert mod.main(["--model-b", str(nb), "--model-c", str(nc)]) == 2               # B file not marked activity_eligible
    assert mod.main(["--model-b", str(pb), "--model-c", str(pc), "--report-out", str(pc)]) == 2     # would overwrite a model output
    assert mod.main(["--model-b", str(pb), "--model-c", str(pc), "--report-out", str(pb)]) == 2
    bb, cc = mutate("label_changed")
    pb2, pc2 = write_pair(tmp_path, bb, cc, bname="x_activity_eligible.csv", cname="y.csv")
    rep = tmp_path / "never.json"
    assert mod.main(["--model-b", str(pb2), "--model-c", str(pc2), "--report-out", str(rep), "--n-boot", "20"]) == 3
    assert not rep.exists()
    assert "REFUSED" in capsys.readouterr().err
    assert mod.main(["--model-b", str(pb), "--model-c", str(pc), "--expect-events", "963", "--report-out", str(rep), "--n-boot", "20"]) == 3
    assert not rep.exists()


# ------------------------------------------------------------------ the written report keeps its numbers and caveats

REPORT = (ROOT / "docs" / "model_b_vs_c_report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("token", ["0.7943", "0.8059", "[-0.0084, +0.0479]", "0.5792", "0.5890", "0.1391", "0.1379", "0.4510", "0.4500",
                                   "29.3962", "29.5103", "[-0.5234, +0.6760]", "963", "34 participants", "+0.0055", "**5**", "**11**", "**18**"])
def test_report_contains_the_supplied_numbers(token):
    assert token in REPORT


def test_report_conclusion_and_unavailable_items_are_explicit():
    assert "**Inconclusive.**" in REPORT
    assert REPORT.count("NOT AVAILABLE") >= 5
    low = REPORT.lower()
    assert "inconclusive-to-negative" not in low and "not clinically validated" in low
    assert "does not demonstrate" in low or "not demonstrate" in low


# ------------------------------------------------------------------ stronger fold / label / range validation

def _split_participant(df, pid="P0"):
    """Put one participant into two folds (events inside the file stay consistent between B and C)."""
    df = df.copy()
    idx = df.index[df["participant_id"] == pid]
    df.loc[idx[: len(idx) // 2], "fold"] = (df.loc[idx[0], "fold"] + 1) % 5
    return df


@pytest.mark.parametrize("which", ["both", "only_b", "only_c"])
def test_a_participant_in_more_than_one_fold_is_refused_even_when_b_and_c_agree(which):
    b, c = make_pair()
    if which in ("both", "only_b"):
        b = _split_participant(b)
    if which in ("both", "only_c"):
        c = _split_participant(c)
    with pytest.raises(ComparisonIntegrityError, match="more than one fold|different folds"):
        verify_matched(b, c)
    with pytest.raises(ComparisonIntegrityError):
        paired_report(b, c, n_boot=20)


def test_b_and_c_agreeing_on_a_split_participant_is_still_refused_with_the_specific_reason():
    b, c = make_pair()
    with pytest.raises(ComparisonIntegrityError, match="participants appear in more than one fold"):
        verify_matched(_split_participant(b), _split_participant(c))


@pytest.mark.parametrize("bad", [-1, 1.5, np.nan])
def test_invalid_fold_values_are_refused(bad):
    b, c = make_pair()
    c = c.copy()
    c["fold"] = c["fold"].astype(float)
    c.loc[c.index[0], "fold"] = bad
    with pytest.raises(ComparisonIntegrityError):
        verify_matched(b, c)


@pytest.mark.parametrize("col, value, text", [("y", 2, "not 0 or 1"), ("p", 1.2, "outside"), ("p_frozen_prior", -0.1, "outside"),
                                              ("interval90_low", 500.0, "low > high")])
def test_out_of_range_labels_probabilities_and_intervals_are_refused(col, value, text):
    b, c = make_pair()
    c = c.copy()
    c.loc[c.index[0], col] = value
    with pytest.raises(ComparisonIntegrityError, match=text):
        verify_matched(b, c)


def test_empty_and_missing_value_inputs_are_refused():
    b, c = make_pair()
    with pytest.raises(ComparisonIntegrityError, match="empty"):
        verify_matched(b.iloc[0:0], c.iloc[0:0])
    c2 = c.copy()
    c2.loc[c2.index[0], "participant_id"] = None
    with pytest.raises(ComparisonIntegrityError, match="missing"):
        verify_matched(b, c2)


def test_participant_ids_of_different_types_in_the_two_files_still_match():
    b, c = make_pair()
    b = b.assign(participant_id=b["participant_id"].str[1:].astype(int))
    c = c.assign(participant_id=c["participant_id"].str[1:])
    assert verify_matched(b, c)["n_participants"] == 12


def test_integrity_block_documents_the_fold_comparison_limitation_and_fold_counts():
    b, c = make_pair()
    info = paired_report(b, c, n_boot=20)["integrity"]
    assert info["each_participant_in_exactly_one_fold"] and sum(info["participants_per_fold"].values()) == 12 and info["n_folds"] == 5
    assert "NOT checked" in info["fold_comparison_limitation"] and "Model A" in info["fold_comparison_limitation"]
    assert "P0" not in json.dumps(info)                                            # counts only, no identifiers


# ------------------------------------------------------------------ blueprint section 21-22: cold-start / experienced and per-participant active / sedentary

from glycotwin.models.activity_strata import ACTIVE, EXCLUDED, SEDENTARY, within_participant_strata  # noqa: E402


def test_cold_start_and_experienced_groups_follow_the_blueprint_definition_exactly():
    b, c = make_pair(n_part=10, per=14, seed=3)                  # n_personal_before runs 0..13 for every participant
    r = paired_report(b, c, n_boot=100, seed=0)["cold_start_vs_experienced"]
    assert r["n_personal_before_agrees_between_b_and_c"]
    assert r["cold_start"]["n_events"] == 10 * 3                     # meals 1, 2, 3 -> n_personal_before 0, 1, 2
    assert r["experienced"]["n_events"] == 10 * 4                    # n_personal_before 10, 11, 12, 13
    assert r["n_events_in_neither_group"] == 10 * 7                  # 3..9
    for grp, mask in (("cold_start", b["n_personal_before"] < 3), ("experienced", b["n_personal_before"] >= 10)):
        bb, cc = b[mask], c[mask]
        assert r[grp]["model_b"]["brier"] == pytest.approx(((bb["p"] - bb["y"]) ** 2).mean())
        assert r[grp]["model_c"]["rise_mae_mg_dl"] == pytest.approx((cc["mean_rise"] - cc["rise"]).abs().mean())
        d = r[grp]["difference_c_minus_b_brier"]
        assert d["estimate"] == pytest.approx(((cc["p"] - cc["y"]) ** 2).mean() - ((bb["p"] - bb["y"]) ** 2).mean())
        assert d["ci95"][0] <= d["estimate"] <= d["ci95"][1]


def test_boundaries_of_cold_start_and_experienced_are_exact():
    b, c = make_pair(n_part=6, per=14, seed=1)
    for df in (b, c):
        df["n_personal_before"] = df["n_personal_before"].replace({2: 3, 9: 10})        # nobody has exactly 2 or 9 earlier meals now
    r = paired_report(b, c, n_boot=50)["cold_start_vs_experienced"]
    assert r["cold_start"]["n_events"] == 6 * 2 and r["experienced"]["n_events"] == 6 * 5       # 0,1  |  10 (was 9), 10..13
    assert r["n_events_in_neither_group"] == len(b) - 6 * 7


def test_disagreeing_personal_counts_between_b_and_c_are_flagged_not_hidden():
    b, c = make_pair(n_part=6, per=14)
    c = c.copy()
    c.loc[c.index[0], "n_personal_before"] += 1
    assert paired_report(b, c, n_boot=30)["cold_start_vs_experienced"]["n_personal_before_agrees_between_b_and_c"] is False


def test_matching_personal_counts_are_reported_as_agreeing():
    b, c = make_pair(n_part=6, per=14)
    assert paired_report(b, c, n_boot=30)["cold_start_vs_experienced"]["n_personal_before_agrees_between_b_and_c"] is True


def test_empty_experienced_group_is_reported_as_empty():
    b, c = make_pair(per=8)
    assert paired_report(b, c, n_boot=30)["cold_start_vs_experienced"]["experienced"] == {"n_events": 0, "n_participants": 0, "note": "empty stratum"}


def test_active_vs_sedentary_uses_each_participants_own_median_and_reports_the_blueprint_conditions():
    b, c = make_pair(n_part=12, per=10, seed=5)
    rep = paired_report(b, c, n_boot=100, seed=0)["active_vs_sedentary_per_participant"]
    labels = within_participant_strata(c["participant_id"], c["activity"]).to_numpy()
    assert rep["active"]["n_events"] == int((labels == ACTIVE).sum()) and rep["sedentary"]["n_events"] == int((labels == SEDENTARY).sum())
    assert rep["n_events_excluded"] == int((labels == EXCLUDED).sum())
    bb, cc = b[labels == ACTIVE], c[labels == ACTIVE]
    assert rep["active"]["difference_c_minus_b_brier"]["estimate"] == pytest.approx(((cc["p"] - cc["y"]) ** 2).mean() - ((bb["p"] - bb["y"]) ** 2).mean())
    for pid, g in c.assign(lab=labels).groupby("participant_id"):                           # every participant is split at their OWN median
        if (g["lab"] != EXCLUDED).all():
            med = g["activity"].median()
            assert (g.loc[g["lab"] == ACTIVE, "activity"] > med).all() and (g.loc[g["lab"] == SEDENTARY, "activity"] <= med).all()
    cond = rep["blueprint_conditions_on_brier"]
    assert set(cond) >= {"c_better_on_active_meals_interval_excludes_zero", "c_at_least_as_good_on_sedentary_meals_point_estimate"}
    assert "NOT the full decision rules" in cond["note"] and "No non-inferiority margin" in cond["note"]


def test_active_vs_sedentary_conditions_respond_to_the_data():
    b, c = make_pair(n_part=20, per=10, seed=2, c_better=True)
    cond = paired_report(b, c, n_boot=200, seed=0)["active_vs_sedentary_per_participant"]["blueprint_conditions_on_brier"]
    assert cond["c_better_on_active_meals_interval_excludes_zero"] and cond["c_at_least_as_good_on_sedentary_meals_point_estimate"]
    same = paired_report(b, b.assign(activity=c["activity"]), n_boot=100)["active_vs_sedentary_per_participant"]["blueprint_conditions_on_brier"]
    assert not same["c_better_on_active_meals_interval_excludes_zero"]


def test_an_interval_straddling_zero_does_not_satisfy_the_active_condition():
    b, c = make_pair(n_part=12, per=10, seed=5)                          # C is noise around B: no real difference
    rep = paired_report(b, c, n_boot=200, seed=0)["active_vs_sedentary_per_participant"]
    lo, hi = rep["active"]["difference_c_minus_b_brier"]["ci95"]
    assert lo < 0 < hi and rep["blueprint_conditions_on_brier"]["c_better_on_active_meals_interval_excludes_zero"] is False


def test_active_vs_sedentary_is_none_without_an_activity_column_and_excludes_constant_participants():
    b, c = make_pair()
    assert paired_report(b, c.drop(columns=["activity"]), n_boot=30)["active_vs_sedentary_per_participant"] is None
    c2 = c.copy()
    c2.loc[c2["participant_id"] == "P0", "activity"] = 0.5                                   # one person with constant activity
    rep = paired_report(b, c2, n_boot=30)["active_vs_sedentary_per_participant"]
    assert rep["n_participants_excluded"] == 1 and rep["n_events_excluded"] == 8
    assert rep["active"]["n_events"] + rep["sedentary"]["n_events"] + rep["n_events_excluded"] == len(b)


# ------------------------------------------------------------------ Model A key experiment, glycaemic groups, per-participant metrics, seed check

def make_a(b, extra_events=6, seed=11):
    """Model A out-of-fold file: all B/C events (same participant, fold, label) plus a few events only A has."""
    rng = np.random.default_rng(seed)
    a = b[["event_id", "participant_id", "fold", "y"]].copy()
    a["p"] = np.clip(0.4 + 0.2 * (2 * a["y"] - 1) * rng.uniform(0, 1, len(a)) + rng.normal(0, 0.1, len(a)), 0.02, 0.98)
    extra = a.head(extra_events).copy()
    extra["event_id"] = ["a_only_" + str(i) for i in range(len(extra))]
    return pd.concat([a, extra], ignore_index=True)


def test_model_a_key_experiment_uses_exactly_the_shared_events_and_reports_all_pairs():
    b, c = make_pair(n_part=12, per=8, seed=4)
    a = make_a(b)
    r = paired_report(b, c, n_boot=100, seed=0, oof_a=a)["key_experiment_model_a_b_c"]
    assert r["integrity"]["n_model_a_only_events"] == 6 and r["integrity"]["n_shared_events"] == 96 and r["n_events"] == 96
    shared = a[a["event_id"].isin(b["event_id"])].sort_values("event_id")
    assert r["models"]["model_a"]["brier"] == pytest.approx(((shared["p"] - shared["y"]) ** 2).mean())            # A's extra events are not used
    assert set(r["differences"]) == {"model_b_minus_model_a", "model_c_minus_model_a", "model_c_minus_model_b"}
    d = r["differences"]["model_c_minus_model_a"]["brier"]
    assert d["estimate"] == pytest.approx(r["models"]["model_c"]["brier"] - r["models"]["model_a"]["brier"]) and d["ci95"][0] <= d["estimate"] <= d["ci95"][1]
    cb = r["differences"]["model_c_minus_model_b"]["brier"]["estimate"]
    assert cb == pytest.approx(paired_report(b, c, n_boot=50)["metrics"]["brier"]["difference_c_minus_b"])      # consistent with the two-model report
    assert len(r["reliability_bins_10"]["model_a"]) == 10 and "no multiplicity" in r["note"]


@pytest.mark.parametrize("what, text", [("fold", "different folds"), ("label", "different labels"), ("participant", "different participants"),
                                        ("missing_event", "absent from the Model A"), ("split_participant", "more than one fold"),
                                        ("duplicate", "duplicated"), ("range", "out-of-range")])
def test_model_a_mismatches_are_refused(what, text):
    b, c = make_pair(n_part=12, per=8, seed=4)
    a = make_a(b)
    i = a.index[a["event_id"] == b["event_id"].iloc[3]][0]
    if what == "fold":
        a.loc[a["participant_id"] == "P2", "fold"] = (a.loc[a["participant_id"] == "P2", "fold"] + 1) % 5          # whole person in another fold
    elif what == "label":
        a.loc[i, "y"] = 1 - a.loc[i, "y"]
    elif what == "participant":
        a.loc[i, "participant_id"] = "Pzz"
    elif what == "missing_event":
        a = a[a["event_id"] != b["event_id"].iloc[3]]
    elif what == "split_participant":
        a.loc[i, "fold"] = (a.loc[i, "fold"] + 1) % 5
    elif what == "duplicate":
        a.loc[a.index[1], "event_id"] = a.loc[a.index[0], "event_id"]
    elif what == "range":
        a.loc[i, "p"] = 1.5
    with pytest.raises(ComparisonIntegrityError, match=text):
        paired_report(b, c, n_boot=30, oof_a=a)


def test_glycaemic_group_breakdown_partitions_the_events_and_flags_small_groups():
    b, c = make_pair(n_part=12, per=8, seed=6)
    groups = {f"P{k}": ("healthy" if k < 5 else "prediabetes" if k < 10 else "t2d") for k in range(12)}
    r = paired_report(b, c, n_boot=60, seed=0, group_of=groups)["glycaemic_group_breakdown"]
    assert {g: v["n_events"] for g, v in r["groups"].items()} == {"healthy": 40, "prediabetes": 40, "t2d": 16}
    assert {g: v["n_participants"] for g, v in r["groups"].items()} == {"healthy": 5, "prediabetes": 5, "t2d": 2}
    assert r["groups"]["t2d"]["too_few_participants_for_a_group_claim"] and not r["groups"]["healthy"]["too_few_participants_for_a_group_claim"]
    h = b[b["participant_id"].isin([f"P{k}" for k in range(5)])]
    assert r["groups"]["healthy"]["model_b"]["brier"] == pytest.approx(((h["p"] - h["y"]) ** 2).mean())
    ints = {int(k[1:]): v for k, v in groups.items()}                                                              # integer ids in the groups file
    b2, c2 = b.assign(participant_id=b["participant_id"].str[1:].astype(int)), c.assign(participant_id=c["participant_id"].str[1:].astype(int))
    assert paired_report(b2, c2, n_boot=30, group_of=ints)["glycaemic_group_breakdown"]["groups"]["t2d"]["n_events"] == 16


def test_glycaemic_group_breakdown_refuses_participants_without_a_group():
    b, c = make_pair()
    with pytest.raises(ComparisonIntegrityError, match="no glycaemic group"):
        paired_report(b, c, n_boot=30, group_of={"P0": "healthy"})


def test_per_participant_distribution_counts_only_participants_with_enough_events():
    b, c = make_pair(n_part=12, per=8, seed=1)
    r = paired_report(b, c, n_boot=30)["per_participant_metric_distribution"]
    assert r["brier_c_minus_b"]["n_participants"] == 12
    assert r["brier_c_minus_b"]["n_c_better"] + r["brier_c_minus_b"]["n_c_worse"] + r["brier_c_minus_b"]["n_equal"] == 12
    sparse = paired_report(b, c, n_boot=30)  # default min 8 events: all 12 have exactly 8
    assert sparse["per_participant_metric_distribution"]["min_events_per_participant"] == 8
    from glycotwin.models.model_bc_compare import per_participant_metric_distribution
    assert per_participant_metric_distribution(b, c, min_events=9)["brier_c_minus_b"] == {"n_participants": 0}
    assert "P0" not in json.dumps(r)                                                                                  # no identifiers


def test_script_model_a_groups_and_seed_check(tmp_path, capsys):
    mod = load_script()
    b, c = make_pair(n_part=12, per=8, seed=4)
    pb, pc = write_pair(tmp_path, b, c)
    a_path = tmp_path / "model_a_oof.csv"; make_a(b).to_csv(a_path, index=False)
    gpath = tmp_path / "groups.csv"
    pd.DataFrame({"participant_id": [f"P{k}" for k in range(12)], "group": ["healthy"] * 6 + ["t2d"] * 6}).to_csv(gpath, index=False)
    rep = tmp_path / "r.json"
    rc = mod.main(["--model-b", str(pb), "--model-c", str(pc), "--model-a", str(a_path), "--groups-file", str(gpath), "--seed-check", "1,2",
                   "--n-boot", "40", "--report-out", str(rep)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["key_experiment_model_a_b_c"]["n_events"] == 96 and set(out["glycaemic_group_breakdown"]["groups"]) == {"healthy", "t2d"}
    sens = out["bootstrap_seed_sensitivity"]
    assert sens["seeds"] == [0, 1, 2] and "brier" in sens["metrics"] and sens["metrics"]["brier"]["lower_endpoint_range"][0] <= sens["metrics"]["brier"]["lower_endpoint_range"][1]
    assert "P0" not in json.dumps(out)
    assert mod.main(["--model-b", str(pb), "--model-c", str(pc), "--model-a", str(tmp_path / "missing.csv"), "--report-out", str(rep)]) == 2
    assert mod.main(["--model-b", str(pb), "--model-c", str(pc), "--groups-file", str(tmp_path / "missing.csv"), "--report-out", str(rep)]) == 2
    bad = tmp_path / "bad.csv"; pd.DataFrame({"x": [1]}).to_csv(bad, index=False)
    assert mod.main(["--model-b", str(pb), "--model-c", str(pc), "--groups-file", str(bad), "--report-out", str(rep)]) == 2
    a_bad = make_a(b); a_bad.loc[a_bad.index[0], "y"] = 1 - a_bad.loc[a_bad.index[0], "y"]
    a_bad.to_csv(a_path, index=False)
    assert mod.main(["--model-b", str(pb), "--model-c", str(pc), "--model-a", str(a_path), "--report-out", str(tmp_path / "never.json"), "--n-boot", "20"]) == 3
    assert not (tmp_path / "never.json").exists()
    capsys.readouterr()
