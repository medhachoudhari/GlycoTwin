import json,sys,shutil
sys.path.insert(0,'/tmp/vid')
from script import B,CH
tl=json.load(open('build/timeline.json')); bt={b:(x,y) for b,x,y in tl['beats']}; DUR=json.load(open('build/durations.json'))
def mmss(t): return f"{int(t//60):02d}:{int(t%60):02d}"
words=sum(len(b[3].split()) for b in B); narr=sum(DUR.values())
ACT={'1a':'Live: the real GlycoTwin landing page; small overlay with the project name; backend/database status.','1b':'Live: landing page, "A twin that keeps its history" (three product points).','1c':'Live: landing page "How it works" five-step flow and the model equation.','1d':'Live: landing page research summary (inconclusive first comparison, limitations); cursor to Launch App.',
'2a':'Live: Launch App → sign-in → Create one → type demonstration name, example.com email, masked password, tick acknowledgement, Create account.','2b':'Live: Settings → label demo-twin-01 → Create twin; callout "BUILT-IN DEMONSTRATION PRIOR".','2c':'Live: My Twin at version 0 (Model B β 0.747 ± 0.187).','2d':'Live: sidebar tour: Forecast, Observations, History, Insights, Home.',
'3a':'Slide: browser → proxy → FastAPI → SQLite (11 tables); research engine.','3b':'Slide: offline CGMacros pipeline; only aggregates cross to the website.',
'4a':'Slide: CGMacros facts (45 participants, 687,580 rows, signals, licence).','4b':'Slide: meal-event timeline, t0, 120-minute window, ≥ 180 label, no meal-end field.','4c':'Slide: eligibility rule and verified Libre vs Dexcom counts.','4d':'Slide: leakage controls (features, folds, sequential evaluation; 45/45).',
'5a':'Live: Forecast page; type 60 g, activity 0.3, glucose 110, meal time 2026-01-01 08:00. Badge "MANUALLY ENTERED DEMONSTRATION VALUES".','5b':'Live: Request forecast; numbers table highlighted (B: 155, 126–184, 7.7 %).','5c':'Live: Observations; enter outcome 185. Callout "MANUALLY ENTERED OUTCOME · NOT A PARTICIPANT RECORD".','5d':'Live: Record outcome; "twin has not been updated yet".','5e':'Live: Apply; "Twin updated: version 0 → 1".','5f':'Live: My Twin v1; β 0.747 → 0.950, SD 0.187 → 0.144; version history.','5g':'Live: second forecast, same inputs, noon; B 167 (140–194), P 21.0 %.',
'6a':'Live: chart highlighted; no glucose curve is drawn.','6b':'Live: predictive distribution, numbers table, data-quality notice highlighted in turn.','7a':'Slide: Model B equations and the closed-form update.','7b':'Slide: forecast from the posterior; eligibility rules; parameter update, not retraining.',
'8a':'Live: "Why this forecast?" explanation.','8b':'Live: Model B / Model C toggle.','8c':'Live: History; parameter chart v0 → v1.','8d':'Live: Insights; forecast-versus-outcome table (185 outside 126–184), then sensitivity chart.','9a':'Live: Settings → Log out.','9b':'Live: sign in again; My Twin still at version 1 with both versions listed.',
'10a':'Slide: B vs C design (963 events, 34 participants) and provenance of the numbers.','10b':'Slide: B vs C table; 8 of 9 intervals contain zero.','10c':'Slide: each model vs frozen prior; planned controls without real-data numbers.',
'11a':'Slide: what is new and what the evidence shows.','11b':'Slide: limits, next steps, repository.'}
o=open('/home/user/GlycoTwin/demo/narration_script.md','w',encoding='utf-8')
o.write(f"""# GlycoTwin demo: word-for-word narration

{words} words, {narr/60:.1f} minutes of speech (about {words/(narr/60):.0f} words per minute); video length {tl['total_s']/60:.1f} minutes. Timestamps are the start of each paragraph in `video/GlycoTwin_demo_subtitled.mp4`.
The voice is AI-generated (Kokoro, voice `hf_alpha`). The subtitles are exactly this text, split into cues. Spoken-form spellings used by the speech engine (for example "Glyco Twin", "Bayzian") are not shown.
Sources for every number: `evidence_map.md`.

""")
cur=0
for bid,ch,vis,text in B:
    if ch!=cur: cur=ch; o.write(f"\n## Chapter {ch}: {CH[ch]}\n\n")
    o.write(f"**[{mmss(bt[bid][0])}]** {text}\n\n")
o.close()
s=open('/home/user/GlycoTwin/demo/shot_list.md','w',encoding='utf-8')
s.write("# GlycoTwin demo: timestamped shot list\n\n'Live' = the real application (frontend on port 5173, backend on 127.0.0.1:8000, temporary database). 'Slide' = `tools/slides.html`. The app area is 1920×940; the bottom 140 pixels are a subtitle band, so subtitles never cover the application.\nValues entered by hand in the live part: label demo-twin-01 · carbs 60 g · activity 0.3 (twin's 0–1 scale) · pre-meal glucose 110 mg/dL · meals 2026-01-01 08:00 and 12:00 UTC · outcome 185 mg/dL. Account names use example.com addresses and are throw-away.\n\n| Start | Beat | Type | What is on screen | Narration (first words) |\n|---|---|---|---|---|\n")
for bid,ch,vis,text in B:
    s.write(f"| {mmss(bt[bid][0])} | {bid} | {'Slide' if vis[0]=='slide' else 'Live'} | {ACT[bid]} | {' '.join(text.split()[:9])}… |\n")
s.write("\n## Chapters\n\n| Start | Chapter |\n|---|---|\n")
for a,b,t in tl['chapters']: s.write(f"| {mmss(a)} | {t} |\n")
s.close()
print(words,round(narr/60,2),len(B),[ (mmss(a),t) for a,b,t in tl['chapters']])
