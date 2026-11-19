# Rehearsal fixtures

`record.mjs --mock` (`npm run rehearse` / `npm run smoke`) answers the two LLM endpoints with these files, so you can check pacing and selectors without waiting on a model. `/api/coverage` isn't mocked. It's deterministic, so the real server computes it from the fixture's `excerpt_span` values.

- `analysis.json` is a real `/api/analyze-regulation` response (merged backend, including `excerpt_match`, `excerpt_score`, `excerpt_span` and `state_fields`) for `demo/regulation.txt` + `demo/company_state.json`.
- `audit.md` is the real `/api/generate-audit` Markdown for those findings.
- `meta.json` records the model, the time, the renderer (`llm` or `deterministic`) and the match mix. The mock returns these as the audit's `renderer` and `model`.

The current capture used a **local `qwen2.5-coder:14b`**, a deliberately modest model. It produced 9 findings (1 high, 8 medium, 1 needs-info): 8 quotes verified and 1 unverified citation. The audit was drafted by the LLM. It rated the 6-hour reporting gap only "medium", so **don't narrate from these fixtures, and don't publish a mock take as the demo.** Re-capture on the pinned recording model with:

```bash
python demo/capture_fixtures.py --provider anthropic --model claude-sonnet-5-5
```
