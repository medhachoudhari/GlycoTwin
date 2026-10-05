"""Read-only inventory of a local dataset directory (e.g. an extracted CGMacros copy).

Design rules this module follows, and must keep following when extended:

- Never write, rename, move, or delete anything under the scanned data root.
- Never print or persist participant-level rows, image contents, or raw values.
- Never assume what a column name, timestamp, or folder means. Only report
  observed, aggregate facts (counts, dtypes, missingness fractions) plus a
  name-based *candidate* flag (e.g. "looks like a timestamp column"), and let a
  human confirm the real semantics from the dataset's own documentation.
- Split output into two reports:
    * a "public" summary (safe to eventually consider for Git, after manual
      review) with participant-identifying folder names redacted, and
    * a "local" full inventory (never committed; lives under data/interim/,
      which is git-ignored) that keeps the real paths for local debugging.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# --- File classification -----------------------------------------------------

TABULAR_EXTENSIONS = {".csv", ".tsv", ".parquet"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".bmp", ".gif", ".tiff", ".tif"}
DOC_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".yaml", ".yml", ".rtf"}
DOC_NAME_HINTS = re.compile(
    r"(readme|license|licence|codebook|dictionary|metadata|documentation|methods|protocol|consent|changelog)",
    re.IGNORECASE,
)
TIMESTAMP_NAME_PATTERN = re.compile(r"(time|date|timestamp)", re.IGNORECASE)

# Folder-naming patterns commonly used for per-participant directories. This is a
# *heuristic* used only to decide what must be redacted/kept local-only — it is not
# an assumption about CGMacros's actual layout, which must still be confirmed by
# reading the dataset's own documentation.
SUBJECT_DIR_PATTERN = re.compile(
    r"^(cgmacros[-_]?\d+|subject[-_]?\d+|participant[-_]?\d+|p\d{2,4}|s\d{2,4}|\d{2,4})$",
    re.IGNORECASE,
)

SKIP_DIR_NAMES = {".git", "__pycache__", ".ipynb_checkpoints", ".DS_Store"}


# --- Data structures -----------------------------------------------------------


@dataclass
class FileRecord:
    relative_path: str
    extension: str
    size_bytes: int


@dataclass
class ColumnProfile:
    name: str
    dtype: str
    row_count: int
    null_count: int
    missing_fraction: float
    looks_like_timestamp_name: bool
    sample_datetime_parse_fraction: float | None  # based on a small sample only


@dataclass
class TabularFileProfile:
    relative_path: str
    format: str
    row_count: int | None
    columns: list[ColumnProfile]
    read_error: str | None = None
    truncated: bool = False  # True if the row scan was capped before EOF


@dataclass
class AuditResult:
    data_root: str
    generated_at_utc: str
    total_files: int
    total_size_bytes: int
    extension_counts: dict[str, int]
    extension_sizes_bytes: dict[str, int]
    image_summary: dict
    subject_like_dir_count: int
    doc_candidates_public: list[str]
    tabular_profiles_public: list[dict]
    observed_facts: list[str]
    open_questions: list[str]
    warnings: list[str] = field(default_factory=list)


# --- Scanning --------------------------------------------------------------------


def scan_directory(root: Path) -> list[FileRecord]:
    """Recursively list files under root. Read-only: only calls stat(), never open()."""
    records: list[FileRecord] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            try:
                size = fpath.stat().st_size
            except OSError:
                size = -1
            rel = fpath.relative_to(root)
            records.append(FileRecord(str(rel), fpath.suffix.lower(), size))
    return records


def find_subject_like_dirs(root: Path) -> list[str]:
    """Immediate child directory names that look like per-participant folders."""
    try:
        children = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return []
    return sorted(p.name for p in children if SUBJECT_DIR_PATTERN.match(p.name))


def _is_doc_candidate(rel_path: Path) -> bool:
    return rel_path.suffix.lower() in DOC_EXTENSIONS or bool(DOC_NAME_HINTS.search(rel_path.name))


def _is_inside_subject_dir(rel_path: Path, subject_dirs: set[str]) -> bool:
    return len(rel_path.parts) > 1 and rel_path.parts[0] in subject_dirs


def _redact_subject_ids(rel_path: str, subject_dirs: set[str]) -> str:
    parts = Path(rel_path).parts
    redacted = ["<participant_id>" if p in subject_dirs else p for p in parts]
    return str(Path(*redacted))


# --- Tabular schema / missingness profiling --------------------------------------


def profile_csv_file(
    path: Path,
    relative_path: str,
    sample_rows: int = 200,
    chunk_size: int = 20_000,
    max_rows_scanned: int | None = None,
) -> TabularFileProfile:
    """Report column names, dtypes, and missingness for a CSV/TSV file.

    Never returns row values: only aggregate counts/fractions computed in memory.
    """
    suffix = path.suffix.lower()
    sep = "\t" if suffix == ".tsv" else ","

    try:
        sample = pd.read_csv(path, sep=sep, nrows=sample_rows)
    except Exception as exc:  # noqa: BLE001 - surfaced as a reported, non-fatal error
        return TabularFileProfile(relative_path, suffix.lstrip("."), None, [], read_error=f"{type(exc).__name__}: could not read header/sample")

    timestamp_fraction: dict[str, float | None] = {}
    for col in sample.columns:
        if TIMESTAMP_NAME_PATTERN.search(str(col)):
            non_null = sample[col].dropna()
            timestamp_fraction[col] = (
                float(pd.to_datetime(non_null, errors="coerce").notna().mean()) if len(non_null) else None
            )
        else:
            timestamp_fraction[col] = None

    total_rows = 0
    null_counts = dict.fromkeys(sample.columns, 0)
    truncated = False
    try:
        for chunk in pd.read_csv(path, sep=sep, dtype=str, chunksize=chunk_size):
            total_rows += len(chunk)
            for col in sample.columns:
                if col in chunk.columns:
                    null_counts[col] += int(chunk[col].isna().sum() + (chunk[col] == "").sum())
            if max_rows_scanned is not None and total_rows >= max_rows_scanned:
                truncated = True
                break
    except Exception as exc:  # noqa: BLE001
        return TabularFileProfile(
            relative_path, suffix.lstrip("."), None, [],
            read_error=f"{type(exc).__name__}: header read ok, full scan failed",
        )

    columns = [
        ColumnProfile(
            name=str(col),
            dtype=str(sample[col].dtype),
            row_count=total_rows,
            null_count=null_counts[col],
            missing_fraction=(null_counts[col] / total_rows) if total_rows else 0.0,
            looks_like_timestamp_name=bool(TIMESTAMP_NAME_PATTERN.search(str(col))),
            sample_datetime_parse_fraction=timestamp_fraction[col],
        )
        for col in sample.columns
    ]
    return TabularFileProfile(relative_path, suffix.lstrip("."), total_rows, columns, truncated=truncated)


def profile_parquet_file(path: Path, relative_path: str) -> TabularFileProfile:
    try:
        df = pd.read_parquet(path)
    except ImportError as exc:
        return TabularFileProfile(relative_path, "parquet", None, [], read_error=f"optional dependency missing: {exc}")
    except Exception as exc:  # noqa: BLE001
        return TabularFileProfile(relative_path, "parquet", None, [], read_error=f"{type(exc).__name__}: could not read file")

    total_rows = len(df)
    columns = []
    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        name_match = bool(TIMESTAMP_NAME_PATTERN.search(str(col)))
        parse_fraction = None
        if name_match:
            non_null = series.dropna()
            if len(non_null):
                parse_fraction = float(pd.to_datetime(non_null, errors="coerce").notna().mean())
        columns.append(
            ColumnProfile(
                name=str(col),
                dtype=str(series.dtype),
                row_count=total_rows,
                null_count=null_count,
                missing_fraction=(null_count / total_rows) if total_rows else 0.0,
                looks_like_timestamp_name=name_match,
                sample_datetime_parse_fraction=parse_fraction,
            )
        )
    return TabularFileProfile(relative_path, "parquet", total_rows, columns)


def profile_tabular_file(path: Path, relative_path: str, **kwargs) -> TabularFileProfile:
    if path.suffix.lower() == ".parquet":
        return profile_parquet_file(path, relative_path)
    return profile_csv_file(path, relative_path, **kwargs)


# --- Report assembly ---------------------------------------------------------------


def _column_to_dict(c: ColumnProfile) -> dict:
    return asdict(c)


def _tabular_profile_to_public_dict(p: TabularFileProfile, subject_dirs: set[str]) -> dict:
    d = asdict(p)
    d["relative_path"] = _redact_subject_ids(p.relative_path, subject_dirs)
    return d


def _build_observed_facts(
    total_files: int,
    extension_counts: dict[str, int],
    image_summary: dict,
    subject_dirs: list[str],
    tabular_profiles: list[TabularFileProfile],
    redact_dirs: set[str],
) -> list[str]:
    facts = [
        f"{total_files} files found under the configured dataset root.",
        f"File extensions present: {dict(sorted(extension_counts.items()))}.",
        f"{len(subject_dirs)} top-level directories match a per-participant naming pattern "
        "(heuristic; not a confirmed participant count).",
        f"{image_summary['total_count']} image files found "
        f"({image_summary['by_extension']}); none were opened or read.",
    ]
    for p in tabular_profiles:
        display_path = _redact_subject_ids(p.relative_path, redact_dirs)
        if p.read_error:
            facts.append(f"Could not fully profile '{display_path}': {p.read_error}.")
            continue
        ts_cols = [c.name for c in p.columns if c.looks_like_timestamp_name]
        facts.append(
            f"'{display_path}' ({p.format}): {p.row_count} rows, {len(p.columns)} columns"
            + (f", candidate timestamp column(s): {ts_cols}" if ts_cols else "")
            + "."
        )
    return facts


def _default_open_questions() -> list[str]:
    return [
        "What each column actually means (units, timezone, meal-timing convention) is "
        "unconfirmed until the dataset's own documentation/data dictionary is read.",
        "The participant ID scheme and how files join across CGM, meal, and wearable "
        "records is unconfirmed.",
        "Whether different file types share a common, consistent time base is unconfirmed "
        "(note: CGMacros timestamps are privacy-shifted; do not attempt to recover real dates).",
        "Whether any 'timestamp-looking' column is actually a timestamp, and in what "
        "resolution/timezone, is unconfirmed without the data dictionary.",
        "Whether missingness is random or structured (e.g. device gaps, non-wear periods) "
        "is unconfirmed from counts alone.",
        "Any research target (e.g. a glucose-forecasting horizon or threshold) is undecided "
        "and must not be assumed before these questions are resolved.",
    ]


def run_audit(
    data_root: Path,
    output_dir: Path,
    local_output_dir: Path,
    max_tabular_files: int = 25,
    sample_rows: int = 200,
    chunk_size: int = 20_000,
    max_rows_scanned: int | None = None,
) -> AuditResult:
    """Run the full read-only inventory and write both reports. Returns the result."""
    data_root = Path(data_root)
    records = scan_directory(data_root)
    subject_dirs = set(find_subject_like_dirs(data_root))

    extension_counts = dict(Counter(r.extension or "<none>" for r in records))
    extension_sizes: dict[str, int] = defaultdict(int)
    for r in records:
        extension_sizes[r.extension or "<none>"] += max(r.size_bytes, 0)

    image_records = [r for r in records if r.extension in IMAGE_EXTENSIONS]
    image_summary = {
        "total_count": len(image_records),
        "total_size_bytes": sum(max(r.size_bytes, 0) for r in image_records),
        "by_extension": dict(Counter(r.extension for r in image_records)),
    }

    doc_public: list[str] = []
    for r in records:
        relp = Path(r.relative_path)
        if _is_doc_candidate(relp) and not _is_inside_subject_dir(relp, subject_dirs):
            doc_public.append(r.relative_path)

    tabular_records = [r for r in records if r.extension in TABULAR_EXTENSIONS]
    warnings: list[str] = []
    if len(tabular_records) > max_tabular_files:
        warnings.append(
            f"{len(tabular_records)} tabular files found; profiled only the first "
            f"{max_tabular_files} (by scan order) to bound runtime. Re-run with "
            "--max-tabular-files to change this."
        )

    tabular_profiles = [
        profile_tabular_file(
            data_root / r.relative_path,
            r.relative_path,
            sample_rows=sample_rows,
            chunk_size=chunk_size,
            max_rows_scanned=max_rows_scanned,
        )
        for r in tabular_records[:max_tabular_files]
    ]

    observed_facts = _build_observed_facts(
        len(records), extension_counts, image_summary, sorted(subject_dirs), tabular_profiles, subject_dirs
    )
    open_questions = _default_open_questions()

    generated_at = datetime.now(timezone.utc).isoformat()

    result = AuditResult(
        data_root=str(data_root),
        generated_at_utc=generated_at,
        total_files=len(records),
        total_size_bytes=sum(max(r.size_bytes, 0) for r in records),
        extension_counts=extension_counts,
        extension_sizes_bytes=dict(extension_sizes),
        image_summary=image_summary,
        subject_like_dir_count=len(subject_dirs),
        doc_candidates_public=sorted(doc_public),
        tabular_profiles_public=[_tabular_profile_to_public_dict(p, subject_dirs) for p in tabular_profiles],
        observed_facts=observed_facts,
        open_questions=open_questions,
        warnings=warnings,
    )

    _write_public_report(result, output_dir)
    _write_local_report(result, records, subject_dirs, doc_public, tabular_profiles, local_output_dir)
    return result


def _write_public_report(result: AuditResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = asdict(result)
    payload.pop("data_root", None)  # the real local path is not meaningful/safe to publish
    (output_dir / "dataset_inventory_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Dataset inventory summary (aggregate, no participant-level data)",
        "",
        f"Generated: {result.generated_at_utc}",
        "",
        "## Observed facts",
        *[f"- {f}" for f in result.observed_facts],
        "",
        "## Open questions",
        *[f"- {q}" for q in result.open_questions],
    ]
    if result.warnings:
        lines += ["", "## Warnings", *[f"- {w}" for w in result.warnings]]
    lines += [
        "",
        "> This file is a candidate for committing to Git, but review it yourself first — ",
        "> nothing here is guaranteed free of participant-identifying detail just because ",
        "> it was generated by this tool.",
        "",
    ]
    (output_dir / "dataset_inventory_summary.md").write_text("\n".join(lines), encoding="utf-8")


def _write_local_report(
    result: AuditResult,
    records: list[FileRecord],
    subject_dirs: set[str],
    doc_public: list[str],
    tabular_profiles: list[TabularFileProfile],
    local_output_dir: Path,
) -> None:
    """Full, unredacted inventory for local debugging only. Never committed."""
    local_output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "data_root": result.data_root,
        "generated_at_utc": result.generated_at_utc,
        "subject_like_dirs": sorted(subject_dirs),
        "all_files": [asdict(r) for r in records],
        "tabular_profiles": [asdict(p) for p in tabular_profiles],
    }
    (local_output_dir / "full_inventory.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
