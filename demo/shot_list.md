# GlycoTwin demo: timestamped shot list

'Live' = the real application (frontend on port 5173, backend on 127.0.0.1:8000, temporary database). 'Slide' = `tools/slides.html`. The app area is 1920×940; the bottom 140 pixels are a subtitle band, so subtitles never cover the application.
Values entered by hand in the live part: label demo-twin-01 · carbs 60 g · activity 0.3 (twin's 0–1 scale) · pre-meal glucose 110 mg/dL · meals 2026-01-01 08:00 and 12:00 UTC · outcome 185 mg/dL. Account names use example.com addresses and are throw-away.

| Start | Beat | Type | What is on screen | Narration (first words) |
|---|---|---|---|---|
| 00:00 | 1a | Live | Live: the real GlycoTwin landing page; small overlay with the project name; backend/database status. | Hi everyone! This is GlycoTwin, my project for personalized… |
| 00:16 | 1b | Live | Live: landing page, "A twin that keeps its history" (three product points). | The big idea is that a forecast shouldn't be… |
| 00:44 | 1c | Live | Live: landing page "How it works" five-step flow and the model equation. | This section is the whole story in five steps.… |
| 01:23 | 1d | Live | Live: landing page research summary (inconclusive first comparison, limitations); cursor to Launch App. | The research summary is honest too. The first comparison… |
| 01:40 | 2a | Live | Live: Launch App → sign-in → Create one → type demonstration name, example.com email, masked password, tick acknowledgement, Create account. | I'll create an account first. Each twin belongs to… |
| 02:15 | 2b | Live | Live: Settings → label demo-twin-01 → Create twin; callout "BUILT-IN DEMONSTRATION PRIOR". | Now I can create a Digital Twin. For this… |
| 02:41 | 2c | Live | Live: My Twin at version 0 (Model B β 0.747 ± 0.187). | This is the twin's state at version zero. For… |
| 03:07 | 2d | Live | Live: sidebar tour: Forecast, Observations, History, Insights, Home. | The other pages follow the loop. Forecast takes a… |
| 03:37 | 3a | Slide | Slide: browser → proxy → FastAPI → SQLite (11 tables); research engine. | Before the demo, a quick look at how it… |
| 04:05 | 3b | Slide | Slide: offline CGMacros pipeline; only aggregates cross to the website. | The CGMacros pipeline that processes the real data runs… |
| 04:23 | 4a | Slide | Slide: CGMacros facts (45 participants, 687,580 rows, signals, licence). | So what's the research behind it? We use the… |
| 04:47 | 4b | Slide | Slide: meal-event timeline, t0, 120-minute window, ≥ 180 label, no meal-end field. | Each meal is anchored at its logged meal row,… |
| 05:13 | 4c | Slide | Slide: eligibility rule and verified Libre vs Dexcom counts. | A meal is only used if its window has… |
| 05:44 | 4d | Slide | Slide: leakage controls (features, folds, sequential evaluation; 45/45). | To avoid leakage, features only use information from before… |
| 06:09 | 5a | Live | Live: Forecast page; type 60 g, activity 0.3, glucose 110, meal time 2026-01-01 08:00. Badge "MANUALLY ENTERED DEMONSTRATION VALUES". | Now the main demonstration. I'll enter one meal by… |
| 06:32 | 5b | Live | Live: Request forecast; numbers table highlighted (B: 155, 126–184, 7.7 %). | And here's the forecast, made from version zero, before… |
| 07:01 | 5c | Live | Live: Observations; enter outcome 185. Callout "MANUALLY ENTERED OUTCOME · NOT A PARTICIPANT RECORD". | Two hours later the window has closed, so I… |
| 07:23 | 5d | Live | Live: Record outcome; "twin has not been updated yet". | Recording it doesn't change the twin yet. It waits… |
| 07:36 | 5e | Live | Live: Apply; "Twin updated: version 0 → 1". | Now I apply it. That creates version one.… |
| 07:42 | 5f | Live | Live: My Twin v1; β 0.747 → 0.950, SD 0.187 → 0.144; version history. | On My Twin, beta has moved from 0.747 to… |
| 08:09 | 5g | Live | Live: second forecast, same inputs, noon; B 167 (140–194), P 21.0 %. | Now the interesting part. Same meal, same activity, same… |
| 08:46 | 6a | Live | Live: chart highlighted; no glucose curve is drawn. | Let's look at what the forecast really says. The… |
| 09:04 | 6b | Live | Live: predictive distribution, numbers table, data-quality notice highlighted in turn. | The curve on the right is the predictive distribution,… |
| 09:35 | 7a | Slide | Slide: Model B equations and the closed-form update. | So how does Model B personalize? The rise in… |
| 10:05 | 7b | Slide | Slide: forecast from the posterior; eligibility rules; parameter update, not retraining. | The forecast then comes straight from that current beta.… |
| 10:42 | 8a | Live | Live: "Why this forecast?" explanation. | Every forecast comes with an explanation. Here the carbohydrate… |
| 11:06 | 8b | Live | Live: Model B / Model C toggle. | This toggle shows Model B and Model C for… |
| 11:23 | 8c | Live | Live: History; parameter chart v0 → v1. | History lists every forecast with its status, and the… |
| 11:38 | 8d | Live | Live: Insights; forecast-versus-outcome table (185 outside 126–184), then sensitivity chart. | Insights compares forecast with outcome. My demonstration outcome of… |
| 12:00 | 9a | Live | Live: Settings → Log out. | Finally, persistence. I'll log out and sign back in.… |
| 12:09 | 9b | Live | Live: sign in again; My Twin still at version 1 with both versions listed. | The twin is still at version one, with its… |
| 12:33 | 10a | Slide | Slide: B vs C design (963 events, 34 participants) and provenance of the numbers. | Now back to the research, because the website demo… |
| 13:08 | 10b | Slide | Slide: B vs C table; 8 of 9 intervals contain zero. | Model C's area under the curve, which measures how… |
| 13:52 | 10c | Slide | Slide: each model vs frozen prior; planned controls without real-data numbers. | Compared with their own never-updated priors, both models point… |
| 14:22 | 11a | Slide | Slide: what is new and what the evidence shows. | To wrap up. What's new here is the integration:… |
| 14:55 | 11b | Slide | Slide: limits, next steps, repository. | The limits: this is an investigational research prototype, not… |

## Chapters

| Start | Chapter |
|---|---|
| 00:00 | Opening: the website and the application (live) |
| 03:37 | Architecture |
| 04:23 | The CGMacros research behind it |
| 06:09 | Forecast, observe, update (live) |
| 08:46 | Uncertainty and personalization |
| 10:42 | Explanation, history and persistence (live) |
| 12:33 | Research evidence |
| 14:22 | Closing |
