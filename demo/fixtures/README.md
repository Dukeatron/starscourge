# Rehearsal fixtures

`record.mjs --mock` (`npm run rehearse` / `npm run smoke`) answers the two LLM endpoints with these files, so you can check pacing and selectors without waiting on a model.

- `analysis.json` is a real `/api/analyze-regulation` response for `demo/regulation.txt` + `demo/company_state.json`.
- `audit.md` is the audit log for those findings.
- `meta.json` records the model, the time, and where each file came from.

The current capture used a **local `qwen2.5-coder:14b`**, a deliberately modest model. Its audit call timed out, so `audit.md` comes from the engine's own deterministic fallback renderer (`ai_engine._render_audit_fallback`). The severities are milder than a strong hosted model should give: it rated the 6-hour reporting gap "medium". So **don't narrate from these fixtures, and don't publish a mock take as the demo.** Re-capture on the pinned recording model with:

```bash
python demo/capture_fixtures.py --provider anthropic --model claude-sonnet-5-5
```
