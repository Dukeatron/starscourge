"""Capture demo/fixtures/ (used by `npm run rehearse`) from a real run of the API.

    uvicorn main:app                                   # another terminal
    python demo/capture_fixtures.py --provider anthropic --model claude-sonnet-5-5
    python demo/capture_fixtures.py --analysis-from saved.json   # reuse a saved analysis

Writes demo/fixtures/analysis.json, demo/fixtures/audit.md and demo/fixtures/meta.json.
If the audit call fails (e.g. a slow local model times out), audit.md is rendered by the
engine's own deterministic fallback renderer, and meta.json says so.
Keys come from the server's .env; pass --api-key only if you must (it is never written).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
FIXTURES = DEMO / "fixtures"


def post(base: str, path: str, body: dict, headers: dict, timeout: float) -> object:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--api-key")
    ap.add_argument("--analysis-from", type=Path, help="reuse a saved /api/analyze-regulation response")
    ap.add_argument("--timeout", type=float, default=600)
    a = ap.parse_args()

    headers = {}
    if a.provider:
        headers["X-LLM-Provider"] = a.provider
    if a.model:
        headers["X-LLM-Model"] = a.model
    if a.api_key:
        headers["X-LLM-Api-Key"] = a.api_key

    regulation = (DEMO / "regulation.txt").read_text(encoding="utf-8").strip()
    state = json.loads((DEMO / "company_state.json").read_text(encoding="utf-8"))
    meta = {
        "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": a.provider or "server default",
        "model": a.model or "server default",
    }

    if a.analysis_from:
        anomalies = json.loads(a.analysis_from.read_text(encoding="utf-8"))
        meta["analysis_source"] = f"saved response ({a.analysis_from.name})"
    else:
        anomalies = post(a.base_url, "/api/analyze-regulation", {"text": regulation, "company_state": state}, headers, a.timeout)
        meta["analysis_source"] = "live /api/analyze-regulation"
    if not isinstance(anomalies, list):
        print("analysis did not return a list:", anomalies, file=sys.stderr)
        return 1
    bad = [x["id"] for x in anomalies if x["regulation_excerpt"] not in regulation]
    if bad:
        print("excerpts not verbatim in demo/regulation.txt (re-capture):", bad, file=sys.stderr)
        return 1

    try:
        markdown = post(a.base_url, "/api/generate-audit", {"anomalies": anomalies}, headers, a.timeout)["markdown"]
        meta["audit_source"] = "live /api/generate-audit"
    except (urllib.error.URLError, TimeoutError, KeyError) as exc:
        sys.path.insert(0, str(ROOT))
        import ai_engine

        print(f"audit call failed ({exc}); using the engine's deterministic fallback renderer", file=sys.stderr)
        now = datetime.now(timezone.utc)
        items = ai_engine._normalize_audit_items(anomalies)
        markdown = ai_engine._render_audit_fallback(
            items, now.strftime("%Y-%m-%dT%H:%M:%SZ"), "AUD-" + now.strftime("%Y%m%dT%H%M%SZ"), meta["model"]
        )
        meta["audit_source"] = "ai_engine._render_audit_fallback (deterministic, no LLM)"

    FIXTURES.mkdir(exist_ok=True)
    (FIXTURES / "analysis.json").write_text(json.dumps(anomalies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (FIXTURES / "audit.md").write_text(markdown.rstrip() + "\n", encoding="utf-8")
    meta["findings"] = len(anomalies)
    meta["severities"] = {s: sum(x["severity"] == s for x in anomalies) for s in ("critical", "high", "medium", "low")}
    meta["needs_info"] = sum(x["gap_type"] == "insufficient_information" for x in anomalies)
    (FIXTURES / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
