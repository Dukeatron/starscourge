# Demo kit

Everything needed to (re-)record the demo video in [`docs/DEMO.md`](../docs/DEMO.md).

| File | What it is |
|---|---|
| `regulation.txt` | The CERT-In Directions of 28 Apr 2022 under section 70B(6) of the IT Act, copied from the official PDF (cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf). The covering "whereas" recitals and the annexures are omitted, and line breaks are reflowed. The last line ("Vendor note… ignore all previous instructions…") is **planted** for the prompt-injection shot and isn't part of the direction. |
| `company_state.json` | PaySetu Payments, a fictional online payment aggregator with 44 fields. It's built so that directions (i)–(iv) produce a mix of critical, high, medium and needs-info gaps. (v) and (vi) don't apply, and many fields are compliant or irrelevant. |
| `grounding_demo.py` | Offline terminal insert for the wow shot. A model that lies feeds a fabricated 24-hour clause through the real `analyze_compliance_gap()`, and the engine files the real 6-hour text. `--case 1` prints just that case. |
| `record.mjs` | Playwright recorder: drives the UI through the shot list and records 1080p video. |
| `capture_fixtures.py` | Saves a real API run to `fixtures/`, for `--mock` rehearsals. |
| `fixtures/` | One captured run (see `fixtures/meta.json` for the model). Used only for rehearsal and smoke tests. |
| `out/` | Recordings (gitignored). Never commit video. |

## Automated recording

```bash
# terminal 1 (repo root): a pinned, strong hosted model in .env (see docs/DEMO.md checklist)
uvicorn main:app

# terminal 2
cd demo
npm install                        # Playwright 1.64.1
npx playwright install chromium    # only if Chromium is missing
npm run smoke                      # 10-second headless mock run: does the flow still work?
npm run rehearse                   # full-pace mock run with video, to check pacing
npm run record                     # the live take
```

Each run writes `demo/out/<timestamp>/`:

- `video.webm`: 1920×1080, with a visible cursor overlay (headless Chromium doesn't draw one; `--no-cursor` turns it off).
- `timeline.json`: when each shot started, a per-card check that every quote is a verbatim substring of `regulation.txt`, and the badge text on each card.
- `captions.draft.srt`: draft subtitles taken from the voiceover, timed to the **uncut** video.
- `cut-llm-wait.sh`: an ffmpeg command that cuts both LLM waits down to about 3 s of the progress animation and writes `demo-cut.mp4`.

Flags: `--mock`, `--fast`, `--headless`, `--no-video`, `--no-cursor`, `--no-coldopen`, `--base-url=…`, `--ui=path/to/index.html` (serves that file at `/` so you can test a frontend branch before it's merged). Env: `DEMO_THEME=light|dark` (default dark), and `DEMO_PROVIDER` / `DEMO_MODEL` to set the UI's Model panel. Keep the key in `.env` either way.

### When the UI changes

All selectors live in the `SEL` object at the top of `record.mjs`. They target the redesigned `static/index.html` (refine/frontend @ a12aca6): `#healthTxt`, `#stateDetails > summary`, `#stateJson`, `#reg`, `#analyze`, `#findings .summary`, `#findings .ground-meter`, `#cards article.card` (with `.quote q`, `.grounded`, `[data-src]`), `#srcText mark`, `#audit`, `#report .md h1/h2` and `#report .doc-bar`. If an ID changes, update `SEL` and run `npm run smoke`. A failed run saves `failure.png` next to the video.

## Manual recording (OBS) and editing tips

- **Canvas:** 1920×1080 at 30 fps. Browser window exactly 1920×1080, zoom 100 %, dark theme (the UI's T key). Hide bookmarks, extensions and notifications (macOS Focus mode on).
- **OBS:** Output → Recording → format mkv (remux to mp4 afterwards; mkv survives a crash), encoder Apple VT H.264 or x264, CRF/quality 18–20, keyframe interval 2 s. Use a Display or Window Capture source with the cursor shown. Record the voiceover on a **separate track**, or better, record it afterwards.
- **Cutting the LLM wait:** never narrate over the spinner. Keep 2–3 s of the progress animation, then hard cut (or use a 6-frame dissolve) to the results. `cut-llm-wait.sh` does this for recorder takes. In an editor, cut on the frame where the donut first appears.
- **Voiceover:** record after the edit, to picture, with a USB or lapel mic in a quiet room, about 150 words a minute. The script has about 330 words for 2:15. Normalise to −16 LUFS and add a light compressor.
- **Captions:** burn them in, because judges often watch muted. Start from `captions.draft.srt`, re-time it after cutting (or regenerate it from the final voiceover with your editor's auto-captions), then burn in with `ffmpeg -i demo-cut.mp4 -vf subtitles=final.srt out.mp4`. Use a sans-serif at 42–48 px, bottom-centre, with a semi-transparent box.
- **Zoom-ins:** add 1.3–1.5× punch-ins on the top card's quote (shot 6), on the planted line in the Source tab (shot 7), and on the red/green lines in the terminal insert (shot 8). These sell the wow moments better than the cursor does.
- **Music:** a quiet royalty-free bed (YouTube Audio Library or Pixabay, licence noted in the description), ducked to −28 dB under the voice. Drop it entirely for the 2 s cold-open line so "six hours" lands.
- **Terminal insert:** 20–24 pt font, about 100 columns, `clear` first, and run `python demo/grounding_demo.py --case 1` (its 0.7 s pauses are tuned for video).
- **Export:** H.264 MP4, 1080p30, 8–12 Mbit/s, AAC 192 kbit/s. Keep it under 2:30. Upload it or keep it locally. It's gitignored, so never commit it.
