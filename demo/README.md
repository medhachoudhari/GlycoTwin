# GlycoTwin demonstration video (Digital Twin Challenge 2026 / Happiest Health Summit 2026)

> GlycoTwin is an investigational research prototype. It is not a medical device and gives no advice on diet, medication or insulin dosing.

## The video (15:34, 1920×1080, 30 fps, H.264 + AAC)
Opens directly on the real GlycoTwin landing page — no title card, no title slide, no generic animation first — with a short, first-person, conversational opening ("Hi everyone! This is GlycoTwin, my project for personalized post-meal glucose modelling..."). It then walks the landing page itself, creates an account and a twin, tours the app, covers the architecture and the CGMacros research briefly, runs the full forecast → observe → update loop live, explains uncertainty and Model B's Bayesian update, shows explainability/history/persistence, presents the research evidence honestly (including the inconclusive Model B vs Model C comparison), and closes with a summary of what's new and what remains unproven. English AI voiceover throughout, with **subtitles burned in** (and a separate SRT).

| File | Purpose |
|---|---|
| `video/GlycoTwin_demo_subtitled.mp4` | Master with burned-in subtitles, 68 MB |
| `video/GlycoTwin_demo_subtitled_compact.mp4` | Same content, 41 MB |
| `video/GlycoTwin_demo.srt` | Subtitles (144 cues, identical to the narration) |
| `narration_script.md` | Word-for-word narration with timestamps |
| `shot_list.md` | What is on screen at each timestamp |
| `evidence_map.md` | Source file for every number in the video |
| `demo_checklist.md` | Feature-verification table, pre-submission checklist, troubleshooting |
| `recording_guide_windows.md` | How to re-record or redo the video on Windows |
| `tools/` | The scripts and slides used to make it (Linux paths, not tested on Windows) |

## Chapters
00:00 Opening: the website and the application (live) · 01:34 continues live through account/twin creation and a page tour · 03:37 Architecture · 04:23 The CGMacros research behind it · 06:09 Forecast, observe, update (live) · 08:46 Uncertainty and personalization · 10:42 Explanation, history and persistence (live) · 12:33 Research evidence · 14:22 Closing. (Also embedded as chapter markers in the MP4.)

## Research, application demonstration and evidence are kept separate
* **Research on CGMacros** (chapter "The CGMacros research behind it", and "Research evidence"): the dataset, the meal-event definition, the leakage safeguards, and the Model B vs Model C comparison. All numbers come from repository documents recording the researcher's local runs and are **not recomputed** for the video; `evidence_map.md` lists the source file for each. No participant-level record, file name or image appears anywhere.
* **Application demonstration** (the live chapters): the real application on a temporary database, driven by real navigation and real clicks. The twin starts from the application's built-in demonstration prior (the interface labels it synthetic), because participant data cannot be shown publicly — the video says this explicitly, once, at the point the twin is created. The only hand-entered values are one meal (60 g, activity 0.3, glucose 110 mg/dL), a second forecast with the same inputs, and one outcome (185 mg/dL); the narration calls these out as values typed in for the demo, not a participant's observations. Every number spoken from the screen was checked by the recording script.
* **Evidence**: the retrospective B-vs-C comparison is inconclusive and personalization is not established; the planned shuffled-history / running-rate / population-XGBoost comparison has no real-data run in the repository, so no numbers are given for it. No clinical validation exists.

## How it was produced and what was checked
* Footage: the real frontend and backend (clean git checkout, temporary SQLite database) driven by a scripted Chromium at 1920×940, in a Linux cloud workspace, at real (unsped-up) interaction speed. The app area is 940 px high; the bottom 140 px is a black band reserved for subtitles, so they never cover application content.
* Voice: Kokoro-82M, voice `hf_alpha`, about 115 words per minute. **I could not listen to it.** Whether it sounds natural and whether it carries an Indian-English accent are both unverified; pronunciations were set with phonetic respellings (e.g. "Bayzian" for "Bayesian") and checked only against the phonemizer's output, not by ear.
* Checked programmatically: duration 15:34; audio −16.1 LUFS, true peak −1.5 dBFS; 144 subtitle cues, text identical word-for-word to the narration script, at most two lines of 60 characters each, no overlapping cues, reading speed at most 13 characters per second.
* **Four silence gaps over 4 seconds** (up to 14.0 s, 9.9 s, 4.9 s, 4.4 s) occur where real interaction — typing the registration form, clicking through the page tour — runs longer than the narration written for that beat. Sample frames at each gap were inspected and show the cursor and page actively moving, not a frozen or blank screen; this was a deliberate trade-off to keep the application interactions at a natural, unsped-up pace rather than padding the narration to fill dead time artificially.
* Checked by viewing sample frames only, at the live→landing transition, the registration flow, and the History page: subtitle placement, legibility and sync. The whole video has **not** been watched end to end by a person.
* Not done: Windows testing, other browsers, real devices, a human listening test, an external security review, any clinical validation.

## Where to host the video
The master is 68 MB (over GitHub's 50 MB warning size, under the 100 MB hard limit); the compact file is 41 MB. `demo/.gitignore` keeps `video/*.mp4` out of `git add` by default. Recommended: a **GitHub Release** asset or an unlisted YouTube/Vimeo link, referenced from the top-level README. Committing the compact file (`git add -f demo/video/GlycoTwin_demo_subtitled_compact.mp4`) is possible but permanent in repository history. Nothing has been committed.

## Repository inconsistency to resolve before submission
`README.md` and `docs/PROJECT_STATUS.md` still say no real experiment result exists, while `docs/model_card.md`, `docs/model_b_vs_c_report.md` and `docs/primary_channel_decision.md` record the researcher's local CGMacros runs (and the landing page cites them). The video follows the latter and labels the numbers as the researcher's own, not recomputed.

## Revision history
This is the third cut of the video, produced in response to successive feedback:
1. First cut: documentation-style narration, slide-heavy opening, heavy emphasis on synthetic-data caveats, 19:52.
2. Second cut: added real CGMacros dataset/methodology content, fixed a subtitle-scaling bug, 18:55.
3. **This cut**: opens directly on the real website instead of a title slide, uses first-person conversational narration throughout, trims repeated disclaimers and implementation detail, 15:34 (within the requested 15–16 minute range).
