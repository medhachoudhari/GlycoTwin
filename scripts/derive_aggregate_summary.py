"""Derive a redacted AGGREGATE dataset summary from the committed inventory markdown.

Why this exists: the committed `data/audit/dataset_inventory_summary.md` lists every participant
file with its row and column counts, and the committed `.json` next to it came from a different
(wrong-path) run. This script reads ONLY that committed markdown (never raw data) and writes
`data/audit/dataset_aggregate_summary.{json,md}`: totals, distributions and structural facts, with
no participant file names and no per-file entries. It is deterministic, so the output can be
regenerated and verified (tests/test_derive_aggregate_summary.py).

It does not decide anything: facts are copied or counted; causes are not asserted.

Usage:
    python scripts/derive_aggregate_summary.py [--source data/audit/dataset_inventory_summary.md]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

from glycotwin.config import REPO_ROOT
from glycotwin.data.inventory import summarize_participant_files

PARTICIPANT_LINE = re.compile(r"^- '<participant_id>[\\/][^']*' \((?:csv|tsv|parquet)\): (\d+) rows, (\d+) columns")
OTHER_TABLE_LINE = re.compile(r"^- '([^']+)' \((?:csv|tsv|parquet)\): (\d+) rows, (\d+) columns")
FILES_LINE = re.compile(r"^- (\d+) files found")
EXT_LINE = re.compile(r"^- File extensions present: (\{.*\})\.")
DIRS_LINE = re.compile(r"^- (\d+) top-level directories match")
IMAGES_LINE = re.compile(r"^- (\d+) image files found")


def parse_inventory_markdown(text: str) -> dict:
    out = {"participant_shapes": [], "other_tables": {}}
    for line in text.splitlines():
        if m := PARTICIPANT_LINE.match(line):
            out["participant_shapes"].append((int(m.group(1)), int(m.group(2))))
        elif m := OTHER_TABLE_LINE.match(line):
            if "<participant" not in m.group(1):
                out["other_tables"][m.group(1)] = {"rows": int(m.group(2)), "columns": int(m.group(3))}
        elif m := FILES_LINE.match(line):
            out["total_files"] = int(m.group(1))
        elif m := EXT_LINE.match(line):
            out["extension_counts"] = ast.literal_eval(m.group(1))
        elif m := DIRS_LINE.match(line):
            out["participant_like_dirs"] = int(m.group(1))
        elif m := IMAGES_LINE.match(line):
            out["image_files"] = int(m.group(1))
    return out


def build_aggregate_summary(parsed: dict, source_sha256: str, source_label: str) -> dict:
    return {
        "provenance": {
            "derived_from": source_label, "source_sha256": source_sha256,
            "method": "scripts/derive_aggregate_summary.py (reads the committed markdown only, never raw data)",
            "privacy": "no participant file names and no per-file entries",
        },
        "total_files": parsed.get("total_files"), "extension_counts": parsed.get("extension_counts"),
        "participant_like_directories": parsed.get("participant_like_dirs"), "image_files": parsed.get("image_files"),
        "participant_files": summarize_participant_files(parsed["participant_shapes"]),
        "other_tables": dict(sorted(parsed["other_tables"].items())),
        "unresolved": [
            "Which columns differ between participant files (only the column COUNTS are recorded here).",
            "Why every participant row count is divisible by 5 and nearly all by 15 (structural fact; cause not established).",
            "Meal-row meaning, native versus interpolated CGM readings: see docs/data_validity_rules.md.",
        ],
    }


def render_markdown(s: dict) -> str:
    p = s["participant_files"]
    lines = [
        "# Dataset aggregate summary (derived; no participant file names)", "",
        f"Derived from `{s['provenance']['derived_from']}` (sha256 `{s['provenance']['source_sha256'][:16]}...`) by "
        "`scripts/derive_aggregate_summary.py`. Not produced from raw data.", "",
        "## Observed facts",
        f"- {s['total_files']} files; extensions {s['extension_counts']}; {s['image_files']} image files (never opened).",
        f"- {p['n_files']} participant CSV files: total {p.get('total_rows')} rows; per-file rows min/median/max = "
        f"{p.get('rows_min')}/{p.get('rows_median')}/{p.get('rows_max')}.",
        f"- Column counts differ across participant files: {p.get('column_count_distribution')}.",
        f"- {p.get('files_with_fewer_than_14400_rows')} files have fewer than 14,400 rows (10 days at one row per minute).",
        f"- Row counts divisible by 5: {p.get('row_counts_divisible_by_5')}/{p['n_files']}; by 15: "
        f"{p.get('row_counts_divisible_by_15')}/{p['n_files']} (structural; cause not established).",
        "- Other tables (dimensions only): " + "; ".join(f"{k} {v['rows']}x{v['columns']}" for k, v in s["other_tables"].items()) + ".",
        "", "## Unresolved", *[f"- {u}" for u in s["unresolved"]], "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", default=str(REPO_ROOT / "data" / "audit" / "dataset_inventory_summary.md"))
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "data" / "audit"))
    args = ap.parse_args(argv)
    src = Path(args.source)
    raw = src.read_bytes()
    summary = build_aggregate_summary(parse_inventory_markdown(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest(),
                                      f"data/audit/{src.name}")
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dataset_aggregate_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "dataset_aggregate_summary.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"wrote {out / 'dataset_aggregate_summary.json'} and .md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
