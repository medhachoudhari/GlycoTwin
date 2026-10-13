# GlycoTwin demo: word-for-word narration

1637 words, 14.2 minutes of speech (about 115 words per minute); video length 15.5 minutes. Timestamps are the start of each paragraph in `video/GlycoTwin_demo_subtitled.mp4`.
The voice is AI-generated (Kokoro, voice `hf_alpha`). The subtitles are exactly this text, split into cues. Spoken-form spellings used by the speech engine (for example "Glyco Twin", "Bayzian") are not shown.
Sources for every number: `evidence_map.md`.


## Chapter 1: Opening: the website and the application (live)

**[00:00]** Hi everyone! This is GlycoTwin, my project for personalized post-meal glucose modelling. Let me show you how it works, what makes it different, and the research behind it.

**[00:16]** The big idea is that a forecast shouldn't be a one-off. After the same meal, two people can respond very differently, so each twin here holds a personal estimate of how strongly that person's glucose rises per gram of carbohydrate. Every forecast carries its own uncertainty, and every update creates a new, auditable version.

**[00:44]** This section is the whole story in five steps. Real data from the CGMacros research dataset. A simple model: the rise in glucose is a personal sensitivity, plus an activity effect, times the grams of carbohydrate. A forecast of the two-hour glucose maximum. An observation, once that window has closed. And a Bayesian update that writes a new version of the twin. Forecast, observe, update is the loop this project is built around.

**[01:23]** The research summary is honest too. The first comparison of two model variants was inconclusive, and I'll show you exactly what that means later. But first, let me open the application.

**[01:40]** I'll create an account first. Each twin belongs to the person who created it, passwords are hashed, and the browser only keeps a session cookie, so I won't dwell on that. I'm using a throw-away email on a temporary database, so nothing here touches real data.

**[02:15]** Now I can create a Digital Twin. For this walkthrough it starts from the built-in demonstration prior, which the interface labels synthetic, because participant-level CGMacros data can't be shown publicly. The application can also load an aggregate prior exported from the research pipeline.

**[02:41]** This is the twin's state at version zero. For Model B, the personal carbohydrate sensitivity, beta, starts at 0.747 with an uncertainty of 0.187. Model C adds an activity term. Every update will appear here as a new version.

**[03:07]** The other pages follow the loop. Forecast takes a meal and gives a forecast. Observations is where an outcome is recorded and applied. History lists every forecast and every version, and Insights compares forecast with outcome. We'll use all of them.


## Chapter 2: Architecture

**[03:37]** Before the demo, a quick look at how it fits together. The browser talks to a FastAPI back end, which stores accounts, twins and every twin version in SQLite. Behind it is the research engine, with Models B and C, and the live twin uses the same update and forecast functions as the research experiments.

**[04:05]** The CGMacros pipeline that processes the real data runs offline, on the researcher's own machine. Only aggregate priors and reports ever cross over to the website.


## Chapter 3: The CGMacros research behind it

**[04:23]** So what's the research behind it? We use the CGMacros dataset: forty-five participants, about ten days each, with minute-level glucose from two sensors, plus activity, heart rate and logged meals. It's released under a Creative Commons non-commercial licence.

**[04:47]** Each meal is anchored at its logged meal row, and the target is whether the maximum glucose in the next two hours reaches one hundred and eighty. That's exactly what the app forecasts. One caveat: the dataset has no meal-end time, so we always say after the logged meal, never after the end of the meal.

**[05:13]** A meal is only used if its window has enough readings, missing glucose is never filled in, and the main set keeps isolated meals. On the Libre sensor that left one thousand, two hundred and sixty-two eligible meals, three hundred and one of them positive. The Dexcom sensor is a sensitivity analysis, because the two disagree on the label about twenty-three percent of the time.

**[05:44]** To avoid leakage, features only use information from before the meal, the folds are split by participant, and evaluation is sequential, so a forecast only sees outcomes that were already known. The leakage check passed for all forty-five participants, on both sensors.


## Chapter 4: Forecast, observe, update (live)

**[06:09]** Now the main demonstration. I'll enter one meal by hand: sixty grams of carbohydrate, an activity of 0.3 on the twin's zero-to-one scale, and a pre-meal glucose of one hundred and ten, for the first of January at eight in the morning.

**[06:32]** And here's the forecast, made from version zero, before the twin has learned anything about this person. Model B expects the two-hour maximum to be about one hundred and fifty-five, with a ninety percent interval from one hundred and twenty-six to one hundred and eighty-four, and a seven point seven percent chance of reaching one hundred and eighty.

**[07:01]** Two hours later the window has closed, so I can record what happened. I'll enter a maximum of one hundred and eighty-five. That's a demonstration value I typed in, not a participant's observation. The app only accepts it after the full two hours.

**[07:23]** Recording it doesn't change the twin yet. It waits until I apply it, and a meal with an unusable window would be excluded instead of used.

**[07:36]** Now I apply it. That creates version one.

**[07:42]** On My Twin, beta has moved from 0.747 to 0.950, and its uncertainty has shrunk from 0.187 to 0.144. The twin is more certain, which isn't the same as more accurate. Both versions are in the history, and nothing was overwritten.

**[08:09]** Now the interesting part. Same meal, same activity, same glucose, but a forecast at noon, made from version one. The expected maximum is now one hundred and sixty-seven, the interval runs from one hundred and forty to one hundred and ninety-four, and the chance of reaching one hundred and eighty has gone from seven point seven to twenty-one percent. The inputs are the same, but the twin's state has changed, so its next forecast changes too.


## Chapter 5: Uncertainty and personalization

**[08:46]** Let's look at what the forecast really says. The target is the maximum glucose in the two hours after the meal, not a full glucose curve, so I'm not drawing one. The band is an interval for that maximum.

**[09:04]** The curve on the right is the predictive distribution, and the shaded part above one eighty is the threshold probability. The table gives each model's mean rise, spread and ninety percent interval. That interval isn't a guarantee, and a note warns that the twin has little personal history yet. GlycoTwin shows its uncertainty instead of hiding it.

**[09:35]** So how does Model B personalize? The rise in glucose is a personal sensitivity, beta, times the grams of carbohydrate, plus noise. Beta starts from a prior fitted on other participants, and after each eligible observation a closed-form Bayesian update moves its mean toward what that meal suggests and narrows its uncertainty.

**[10:05]** The forecast then comes straight from that current beta. Only eligible outcomes can update the twin: the window must be closed, unusable windows are excluded, and back-dated forecasts are refused. So it's a parameter update, not retraining a neural network after every meal. People differ, so a personal estimate that learns from each person's own meals is a natural research direction, but we haven't shown yet that it beats a population model.


## Chapter 6: Explanation, history and persistence (live)

**[10:42]** Every forecast comes with an explanation. Here the carbohydrate term contributes about sixty-three milligrams per decilitre, the activity term about minus four, and thirty percent of the uncertainty is about this person's parameters, which shrinks as observations accumulate.

**[11:06]** This toggle shows Model B and Model C for the same meal. The research comparison between them was inconclusive, so the app shows both side by side and doesn't pick a winner.

**[11:23]** History lists every forecast with its status, and the chart shows beta moving from version zero to version one while its band narrows, so you can audit what changed and when.

**[11:38]** Insights compares forecast with outcome. My demonstration outcome of one hundred and eighty-five landed just outside the first forecast's ninety percent interval, and the page says so plainly.

**[12:00]** Finally, persistence. I'll log out and sign back in.

**[12:09]** The twin is still at version one, with its full history. That's what makes it a twin rather than a one-off prediction: it keeps a personal state. Ownership is checked on every request, and the project's eight hundred and fifteen Python tests and thirty-seven frontend tests cover it.


## Chapter 7: Research evidence

**[12:33]** Now back to the research, because the website demo and the CGMacros evaluation are different kinds of evidence. The key comparison put Model B against Model C on the same nine hundred and sixty-three meals from thirty-four participants, out of fold and sequential, with participant-clustered intervals. These numbers come from our recorded runs in the repository report; they weren't recomputed for this video.

**[13:08]** Model C's area under the curve, which measures how well the model ranks risky meals above safe ones, was 0.8059 against 0.7943 for Model B. The difference, 0.0116, has an interval from minus 0.0084 to plus 0.0479. Eight of the nine paired intervals contain zero. So it's inconclusive: adding activity hasn't been shown to help, and a small effect isn't ruled out.

**[13:52]** Compared with their own never-updated priors, both models point toward personal updating, but no interval excludes zero, so that benefit isn't established either. The shuffled-history, running-rate and population XGBoost comparisons are built, but there's no real-data run in the repository, so I'm not quoting numbers for them.


## Chapter 8: Closing

**[14:22]** To wrap up. What's new here is the integration: a persistent, versioned twin that forecasts with uncertainty, learns from eligible outcomes with a Bayesian update, and explains itself, all tied to a leakage-safe evaluation on CGMacros. What the evidence shows is that the Model B versus Model C comparison is inconclusive, and that personalization isn't established yet.

**[14:55]** The limits: this is an investigational research prototype, not a medical device and not advice on diet, medication or insulin. There are only thirty-four participants, the label is a lower bound, and there's no clinical validation. Next, we want to run the full key experiment on the real data, and test whether an activity effect differs by activity level. Thanks for watching. The code is on GitHub at medhachoudhari slash GlycoTwin.

