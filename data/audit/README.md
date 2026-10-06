# data/audit

Tracked in Git: small, **aggregate** audit summaries only (e.g. counts, column inventories,
missingness tables with no participant identifiers).

Never place participant-level rows, meal photos, or other sensitive records here.
Common data/image formats are git-ignored in this folder as a safety net.

## Files here

| File | Status |
|---|---|
| `dataset_aggregate_summary.{json,md}` | **Current.** Derived by `scripts/derive_aggregate_summary.py` from the committed inventory markdown. Aggregates only; no participant file names; regenerate rather than edit (a test checks they match). |
| `dataset_inventory_summary.md` | **Legacy / pending your decision.** A real-run inventory that lists every participant file name with its row and column counts. Kept so the aggregate summary stays reproducible. Contradicts the redaction policy above; the inventory tool no longer emits per-file participant entries. |
| `dataset_inventory_summary.json` | **Stale / pending your decision.** Generated from an earlier wrong-path run (it says 1 file, 0 participants) and disagrees with the `.md`. Do not cite it. |

Removing or replacing the two legacy files is a human decision (docs/PROJECT_STATUS.md, Human Action Queue);
both remain recoverable from Git history either way.
