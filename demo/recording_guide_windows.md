# Recording or re-doing the GlycoTwin demo on Windows

A finished, subtitled, 15:34 video already exists (`video/`), opening directly on the real landing page with a conversational, first-person narration. Use this guide only if you want to re-record the screen part on your own laptop (for example to show it running on Windows), or replace the voice with your own. Keep the same tone: talk through the project as your own, in first person ("Let me show you...", "Here I can create a twin..."), not as a read paper. **These steps were written on Linux and have not been run on Windows.**

## 1. Prepare a safe demonstration environment (two PowerShell windows)
Use a throw-away database so your real twins and research files are never touched.
```powershell
# Window 1, project root (the folder with pyproject.toml)
$env:GLYCOTWIN_DATABASE_URL = "sqlite:///" + ($env:TEMP -replace '\\','/') + "/glycotwin_demo.sqlite3"
python -m uvicorn glycotwin.backend.app:app --host 127.0.0.1 --port 8000

# Window 2, the frontend folder
cd frontend
npm install
npm run dev     # open http://127.0.0.1:5173/
```
Delete the temp database file between takes (`Remove-Item "$env:TEMP\glycotwin_demo.sqlite3"` while the backend is stopped) so the labels (`demo-twin-01`) are free and the numbers repeat. Do not delete anything else.

## 2. Browser
* Chrome or Edge, a **new profile or a private window**, no bookmarks bar, no extensions, no other tabs, zoom 100 %.
* Window 1920×1080 (or full-screen on a 1080p display). Windows display scaling 100 % gives the same layout as the recording.
* Turn on **Focus assist / Do not disturb** so notifications cannot appear. Hide the taskbar clock and any personal paths.
* Use `http://127.0.0.1:5173/` (not `localhost`) so cookies behave.

## 3. OBS Studio settings
| Setting | Value |
|---|---|
| Settings → Video → Base and Output resolution | 1920×1080 |
| Common FPS | 30 |
| Settings → Output (Advanced) → Recording | Type Standard, **Recording format MKV** (safer if it crashes; remux later), Encoder x264 (or NVENC if available), Rate control CRF, CRF 18–20, Preset veryfast |
| Settings → Audio | Sample rate 48 kHz, stereo |
| Source | Window Capture of the browser window (preferred) or Display Capture. Do **not** capture other windows. |
| Cursor | Capture cursor on; move it slowly |

Remux MKV → MP4: OBS → File → Remux Recordings.

## 4. Follow the script
Use `shot_list.md` (what is on screen at each moment) and `narration_script.md` (words). Values entered by hand, as in the video: label `demo-twin-01`; account emails at example.com; carbs 60 g, activity 0.3, glucose 110 mg/dL; meal times 2026-01-01 08:00 then 12:00; observed maximum 185 mg/dL. Label them on screen as manually entered demonstration values, never as a participant's observations. Read every number from the real screen; expected values for a fresh twin were: version 0 Model B β 0.747 ± 0.187; first forecast B expected max 155, 90 % 126–184, P = 7.7 %; after applying, β 0.950 ± 0.144; second forecast B 167, 140–194, P = 21.0 %. If your numbers differ, say what the screen shows.
Pace: about 110–120 words per minute, with 3–5 second pauses on every result. Do not speed anything up.

## 5. Voiceover options (Windows)
1. **Your own voice**: record in OBS or Audacity at 48 kHz mono, a quiet room, pop filter if available.
2. **The existing AI voice**: `video/GlycoTwin_demo_subtitled.mp4` already contains it. To reuse only the audio: `ffmpeg -i video\GlycoTwin_demo_subtitled.mp4 -vn -c:a pcm_s16le narration_full.wav` (install ffmpeg from ffmpeg.org first). This only lines up with the original footage.
3. **A Windows voice**: Windows 11 Narrator "natural" voices and Edge Read Aloud include English (India) voices on many systems (for example Microsoft Neerja); availability varies, so check Settings → Accessibility → Narrator → Add natural voices. Generate each paragraph of `narration_script.md` separately and align it by hand.

## 6. Combine and export
Any editor works (DaVinci Resolve, Clipchamp, Shotcut). Or with ffmpeg:
```powershell
ffmpeg -i screen.mp4 -i narration.wav -map 0:v -map 1:a -c:v libx264 -crf 20 -pix_fmt yuv420p -c:a aac -b:a 160k -ar 48000 -movflags +faststart GlycoTwin_demo.mp4
```
Export: MP4, H.264 + AAC, 1920×1080, 30 fps, 15–20 minutes. Subtitles: `video/GlycoTwin_demo.srt` only matches the original timing. To burn subtitles into your own cut (white text, black outline, bottom centre) use a 140-pixel black band under a 1920×940 recording: `ffmpeg -i screen.mp4 -vf "pad=1920:1080:0:0:black,subtitles=your.srt:original_size=1920x1080:force_style='FontSize=36,Bold=1,Outline=3,Alignment=2,MarginV=24'" -c:a copy out.mp4`.

## 7. Verify before you publish
Play it fully with headphones: voice audible and consistent from first to last second, no clipping, no silent gaps over 10 seconds, text readable, nothing private on screen, length 15–20 minutes. Then use `demo_checklist.md`.
Windows testing is only "done" once you have actually completed the checklist on your laptop. Do not state that it passed before then.
