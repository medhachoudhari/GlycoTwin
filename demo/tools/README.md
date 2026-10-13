# Tools used to produce the demo video

Reference implementation. **Linux paths (`/tmp/vid`) are hard-coded and nothing here was tested on Windows.** Needs: Python with `playwright`, `kokoro-onnx`, `soundfile`, `numpy`; Chromium; ffmpeg with libass; the Kokoro model files `kokoro-v1.0.onnx` and `voices-v1.0.bin` (from the kokoro-onnx GitHub release); the backend and `npm run dev` running on a temporary database.

| File | Role |
|---|---|
| `script.py` | The narration beats (source of `../narration_script.md`) and the pronunciation table. Chapter 1 is the live opening (landing page through the page tour); later chapters alternate live application footage and slides. |
| `tts.py` | Generates one WAV per beat (voice `hf_alpha`, speed 0.75 ≈ 115 wpm) |
| `slides.html` | The presentation slides (1920×940), used only for the architecture, dataset-methodology, Bayesian-math and research-evidence chapters; `show('arch',3)` reveals a step |
| `record.py`, `lib.py` | Drives the real application and the slides with Playwright at 1920×940, records video per chapter, asserts that the quoted numbers appear on screen (`CHECKS` list), and overlays a moving cursor, highlight boxes and short callouts |
| `reset_backend.sh` | Restarts the backend on a fresh temporary database, from a clean clone so the Settings page shows no "uncommitted changes" |
| `assemble.py` | Trims each chapter's recording to its narrated span, mixes narration audio at the measured timestamps, builds the SRT, converts it to an explicit-canvas `.ass` (avoids a libass auto-scaling bug seen with the plain `subtitles=` filter + `force_style`), burns subtitles, adds chapter markers, and writes the two final MP4s in one pass |
| `subtitle_style_reference.ass` | A sample of the `.ass` style block assemble.py generates (38 px, white, black outline, bottom-centre, explicit 1920×1080 canvas) |
| `gen_docs.py` | Regenerates `../narration_script.md` and `../shot_list.md` from the beats and the measured timeline (`build/timeline.json`) |

Layout: every frame is 1920×1080. The application or slide occupies the top 940 pixels; the bottom 140 pixels are a black band reserved for subtitles, so subtitles can never cover charts, numbers or controls.
Typical run order: `tts.py` → `record.py` (per chapter, `CHAPTERS=1,2,...` env var) → `assemble.py` → `gen_docs.py`.
The scripts contain throw-away demonstration credentials for the temporary database (example.com addresses). Do not reuse them anywhere real.
