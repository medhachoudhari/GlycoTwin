"""Read-only inventory of a local CGMacros-style dataset directory.

What this does:
    - Recursively lists files, extensions, and sizes.
    - Profiles CSV/TSV/Parquet files: column names, dtypes, missingness,
      and candidate (name-based) timestamp columns.
    - Counts image files by extension without ever opening them.
    - Flags likely documentation/metadata files.
    - Writes two reports (never prints row-level data to the terminal):
        * data/audit/dataset_inventory_summary.{json,md}  - aggregate, participant
          folder names redacted. A candidate for eventual Git commit, after you
          review it yourself.
        * data/interim/audit_local/full_inventory.json     - full detail, including
          real file paths. Git-ignored; local debugging only.

What this does NOT do:
    - It never writes, renames, moves, or deletes anything under the dataset root.
    - It never prints participant rows, meal records, or image contents.
    - It never assumes column/timestamp semantics beyond a name-based heuristic.
    - It never uploads anything anywhere.

Usage:
    python scripts/audit_dataset.py [--data-root PATH] [options]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from glycotwin.config import AUDIT_DIR, REPO_ROOT, DatasetNotFoundError, get_dataset_root
from glycotwin.data.inventory import run_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-root", default=None, help="Overrides $GLYCOTWIN_DATA_ROOT.")
    parser.add_argument(
        "--output-dir", default=None,
        help="Where to write the public-safe summary report (default: data/audit).",
    )
    parser.add_argument(
        "--local-output-dir", default=None,
        help="Where to write the full local-only inventory, never committed "
        "(default: data/interim/audit_local).",
    )
    parser.add_argument(
        "--max-tabular-files", type=int, default=25,
        help="Cap on the number of tabular files profiled in depth (default: 25).",
    )
    parser.add_argument(
        "--max-rows-scanned", type=int, default=None,
        help="Optional cap on rows scanned per tabular file, for very large files.",
    )
    args = parser.parse_args(argv)

    try:
        root = get_dataset_root(args.data_root)
    except DatasetNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir) if args.output_dir else AUDIT_DIR
    local_output_dir = (
        Path(args.local_output_dir) if args.local_output_dir else REPO_ROOT / "data" / "interim" / "audit_local"
    )

    print(f"Dataset root: {root}")
    print("Scanning read-only (no files will be modified, moved, or deleted)...")

    result = run_audit(
        root,
        output_dir=output_dir,
        local_output_dir=local_output_dir,
        max_tabular_files=args.max_tabular_files,
        max_rows_scanned=args.max_rows_scanned,
    )

    print(f"Files found: {result.total_files}")
    print(f"Extensions: {result.extension_counts}")
    print(f"Images found (not opened): {result.image_summary['total_count']}")
    print(f"Public summary written to: {output_dir}")
    print(f"Full local inventory (do not commit) written to: {local_output_dir}")
    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"  - {w}")
    print("\nSee the written reports for observed facts vs. open questions. "
          "No row-level data was printed here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
