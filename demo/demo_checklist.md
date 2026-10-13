# Demo checklist

## A. Feature verification (done before scripting)
Categories: **1** implemented and verified live in this environment (Linux, temporary database) · **2** implemented per code/tests/prior reports but not verified live here · **3** partially implemented · **4** planned or unavailable.

| Feature | Cat. | Evidence / note | In the video |
|---|---|---|---|
| Registration, session cookie, sign-out, sign-in again | 1 | Driven live; `tests/test_auth.py` | Yes (opening and "Explanation, history and persistence") |
| Twin creation, ownership, persistence across sign-out/in | 1 | Driven live (version 1 still present after sign-in) | Yes |
| Twin state, version history, provenance | 1 | My Twin page | Yes |
| Forecast (Models B and C), 90 % interval, P(max ≥ 180) | 1 | Driven live; numbers asserted by the recorder | Yes |
| Observation recording; apply → new version | 1 | Driven live (0 → 1) | Yes |
| Second forecast from the updated state | 1 | Driven live (7.7 % → 21.0 %) | Yes |
| Explanation, history, insights, sensitivity | 1 | Driven live | Yes |
| Loading an aggregate prior exported from the CGMacros pipeline (`prior_file`) | 2 | Backend code and tests; no CGMacros prior file exists in the public environment | Stated as a capability, not shown |
| Guest mode ("Continue as demo") | 2 | Tests | Not shown |
| What-if scenario comparison | 2 | Backend tests, earlier test report | Not shown |
| Another account cannot read a twin (404 for foreign ids) | 2 | `tests/test_ownership.py` (815-test suite) | Described |
| Excluded meals never update the twin | 2 | `docs/model_b.md`, tests | Described |
| Replay of a participant | 3 | Library code, no UI | Not shown |
| Model A (population XGBoost) | 2 | Implemented; no real-data run in the repository | Described |
| Dataset audit, event table, leakage checks on CGMacros | 2 | Aggregate audit committed; researcher's local runs reported in docs; raw data not in this environment | Described from documents, no data shown |
| Real-data B vs C comparison | 2 | `docs/model_b_vs_c_report.md` (researcher's numbers, not recomputed) | Quoted and labelled |
| Key experiment vs shuffled history / running rate / XGBoost on real data | 4 | Harness exists; no real-data run available | Stated as not available |
| Password recovery, email verification, account deletion | 4 | Not built | Not mentioned in the video (see `docs/BACKEND.md`) |
| Windows verification | 4 | Never run | Not claimed |
| Clinical validation | 4 | None | Stated as not done |

## B. Before you submit (play the whole video once)
- [ ] The voice is acceptable to you. It was **not** listened to by the author of this package. It is an AI voice (Kokoro `hf_alpha`); whether it sounds Indian-English is unverified.
- [ ] Pronunciation of "GlycoTwin", "Bayesian", "scrypt", "CGMacros", "XGBoost", "METs" acceptable. If not, edit the `PRON` table in `tools/script.py` and regenerate.
- [ ] Subtitles are readable and never cover application content. (They sit in a dedicated 140-pixel band below the 940-pixel application area.)
- [ ] Every research number matches `evidence_map.md` and the cited documents.
- [ ] You agree with the wording of the research claims given that `README.md` and `docs/PROJECT_STATUS.md` still say no real experiment result exists, while `docs/model_card.md`, `docs/model_b_vs_c_report.md` and `docs/primary_channel_decision.md` record the researcher's local runs. Reconcile the documents before submission.
- [ ] Nothing private is visible: only example.com throw-away emails and masked passwords appear; no participant-level data, file names, tokens, cookies or local paths.
- [ ] Total length is between 15 and 16 minutes (15:34).
- [ ] The opening is the real landing page (no title slide first) and the tone sounds like a first-person walkthrough, not a read paper.
- [ ] Four silence gaps over 4 seconds exist (up to 14 s), each during real, visible interaction (typing a form, navigating pages) rather than a blank screen — see `README.md`.
- [ ] Decide where the MP4 is hosted before committing anything (see `README.md`).
- [ ] Run the website on your own Windows laptop before saying it works there.

## C. Troubleshooting a local re-recording
| Symptom | Likely cause | What to do |
|---|---|---|
| "Cannot reach the backend" / empty page | Backend not running or wrong port | Start both windows; open `http://127.0.0.1:8000/health` |
| Forecast refused (409/422) | Meal time earlier than the twin's last event, or activity outside 0–1 on the demonstration prior | Use a later meal time (08:00 then 12:00); keep activity 0–1 |
| Redirected to sign-in / 401 | Session cookie missing or expired, or the database was replaced | Sign in again; use `127.0.0.1`, not `localhost` |
| "Twin not found" / empty twin list | Signed in as a different account, or a different database file | Check Settings → My twins; check `GLYCOTWIN_DATABASE_URL` |
| 409 "label already exists" | Labels are unique across the database | Use a new label or a fresh temporary database |
| "Too many attempts" (429) | 5 wrong sign-ins for one email | Wait, or restart the test backend |
| Different numbers on screen than in the narration | Different prior or inputs | Use the exact inputs in `shot_list.md`; a new twin is deterministic |
| Settings shows "(uncommitted changes)" next to the engine version | Your working tree has uncommitted files | Harmless; run the backend from a clean checkout if you want it hidden |
