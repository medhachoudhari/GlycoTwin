# GlycoTwin — submission deliverables (Digital Twin Challenge 2026)

| File | What it is |
|---|---|
| `GlycoTwin_Architecture.pdf` | 1-page architecture diagram (frontend, backend, 11-table SQLite database, shared Bayesian research engine, the forecast→observe→update loop, offline CGMacros pipeline). |
| `GlycoTwin_Architecture.pptx` | The same diagram, editable. |
| `GlycoTwin_Presentation.pdf` | **10-slide** project presentation (current version — see `_backup_v1/` for the original 12-slide dark deck and `_backup_v2/` for the first 10-slide revision this replaces): title, problem statement, proposed solution (with diagram), innovative features, CGMacros dataset and methodology, architecture and technical stack, ML models and personalization, research results (including the inconclusive Model B vs Model C comparison), a real application screenshot with the live demonstration numbers plus limitations/safety, and conclusion/future work. White background, navy accents, **Times New Roman throughout**. |
| `GlycoTwin_Presentation.pptx` | The same 10-slide deck, editable (built with `pptxgenjs`, a theme applied via `apply_theme.js`, structured with real shapes/text boxes — not an embedded image of each slide). |
| `_backup_v1/` | The original 12-slide, dark-themed version of the presentation, kept rather than deleted. |
| `_backup_v2/` | The first 10-slide revision (white/navy, same content) — superseded by the current deck, which reworks spacing and layout on every slide so the available area is used more effectively and nothing reads as too small. Kept rather than deleted. |

## What changed in this revision
The structure, all facts, figures, equations and the real screenshot are unchanged from `_backup_v2/` — only layout and typography were reworked, per explicit feedback that several slides had too much unused space and the content looked too small in the deck overview:
- Enlarged diagrams, cards, and tables throughout, with more generous padding and inter-element spacing so each slide's content fills the usable area instead of leaving the bottom third empty.
- Titles are set around 32–34pt and body text mostly in the 15–24pt range (component labels inside dense diagrams stay smaller by necessity).
- Slide 2 now visually separates "the problem" / "current limitation" into two cards with the central research question set off in its own bordered box. Slide 3's workflow diagram and slide 6's architecture are both noticeably larger and easier to read. Slide 7 now compares Models A/B/C in a single table instead of stacked cards. Slide 9's screenshot and before/after comparison are both bigger.
- No content was removed to make the deck look sparser, and no decorative filler was added — the extra space is filled by enlarging and better spacing the same real figures, equations, and statements that were already in the deck.

## How these were made
Both the diagram and the presentation were built two ways and cross-checked against each other:
1. **The `.pptx` files** — native PowerPoint via `pptxgenjs` (presentation) / `python-pptx` (architecture diagram), so they are genuinely editable.
2. **The `.pdf` files** — an HTML version with identical content and layout, rendered via headless Chromium `--print-to-pdf` and verified by converting every page to an image and visually inspecting it at presentation size (text overflow, overlaps, alignment, readability, spacing).

**LibreOffice (`soffice`) cannot run in this environment** — it fails to load even a trivial `.txt` file (exit code 81, confirmed again on the actual `.pptx` itself), which is an environment/sandbox limitation, not a problem with these files. Because of that, the exact visual rendering of the **`.pptx` file itself** could not be confirmed the way the PDF was. What *was* verified on the `.pptx`:
- `markitdown` text-content dump — every slide's text checked, no leftover placeholder junk beyond the intentional ones.
- The skill's `validate.py` schema/relationship/content-type checker — **all checks passed**.
It should open normally in real PowerPoint or LibreOffice Impress on your machine. If it looks different from the PDF when you open it, the PDF is the visually-confirmed reference.

## What is still a placeholder
Both documents mark, in amber italic text, the same items the main README marks pending: team/member names, institution, incubator, the YouTube demo-video link, and the final license choice. Fill those in (or tell me the values and I will) before submitting.

## Sources for every number used
Every figure in the presentation (dataset counts, model comparison table, live-demo numbers) is sourced in `../../demo/evidence_map.md`, which was built and checked during the demo-video work and reused here rather than re-derived. The screenshot on the "Demonstration, Limitations and Safety" slide is a genuine capture of the real application (`/tmp/vid/shots/final_5f.png` at build time — not fabricated), taken during the demo-video recording; its on-screen numbers match the table in `evidence_map.md`.
