"""Demo: the engine will not let a model put an invented quote into an audit file.

Run from the repo root (offline, no key, no network):

    python demo/grounding_demo.py

A "lying model" stands in for the LLM and returns three findings whose
`regulation_excerpt` fields are (1) a fabricated clause that would make the
company look compliant, (2) a sloppy paraphrase, and (3) a correct quote with
odd casing and whitespace. Each finding goes through the real public
`analyze_compliance_gap()` pipeline, and the script prints what the model
claimed next to what the engine actually returned, then checks that every
returned excerpt is an exact substring of the regulation.

This only swaps the network call (the same seam the offline test suite uses).
The grounding code under test is the production code in ai_engine.py.
"""

from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ai_engine  # noqa: E402

REGULATION = (ROOT / "demo" / "regulation.txt").read_text(encoding="utf-8")
STATE = json.loads((ROOT / "demo" / "company_state.json").read_text(encoding="utf-8"))

PAUSE = 0.0 if "--fast" in sys.argv else 0.6
USE_COLOR = sys.stdout.isatty() and "--no-color" not in sys.argv


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


RED, GREEN, YELLOW, DIM, BOLD = "31", "32", "33", "2", "1"

LIES = [
    {
        "label": "Fabricated clause (would hide a critical gap)",
        "title": "Incident reporting SLA",
        "excerpt": "Regulated entities shall report cyber security incidents within twenty-four (24) hours.",
    },
    {
        "label": "Paraphrase, not a quote",
        "title": "Backups kept outside India",
        "excerpt": "Payment data and its backups have to stay inside India",
    },
    {
        "label": "Real quote, sloppy formatting",
        "title": "TLS below 1.2",
        "excerpt": "“DATA IN TRANSIT shall be protected   using TLS version 1.2 or higher”",
    },
]


def lying_model(*_args, **_kwargs) -> dict:
    """Stands in for ai_engine._provider_complete and returns fabricated excerpts."""
    return {
        "anomalies": [
            {
                "title": lie["title"],
                "category": "security",
                "severity": "high",
                "gap_type": "non_compliant",
                "regulation_requirement": "See excerpt.",
                "regulation_excerpt": lie["excerpt"],
                "current_state": "See company state.",
                "gap_description": f"Demo finding {i}.",
                "recommended_remediation": "Demo remediation.",
            }
            for i, lie in enumerate(LIES)
        ]
    }


def wrap(text: str, indent: str) -> str:
    return textwrap.fill(text, width=92, initial_indent=indent, subsequent_indent=indent)


def main() -> int:
    ai_engine._provider_complete = lying_model  # swap only the network call
    result = ai_engine.analyze_compliance_gap(REGULATION, STATE)
    by_title = {a["title"]: a for a in result}

    print(c(BOLD, "\nGrounding check: can the model slip an invented quote into the audit log?\n"))
    all_ok = True
    for i, lie in enumerate(LIES, start=1):
        grounded = by_title[lie["title"]]["regulation_excerpt"]
        verbatim = grounded in REGULATION
        all_ok &= verbatim
        changed = grounded != lie["excerpt"]
        print(c(BOLD, f"[{i}] {lie['label']}"))
        time.sleep(PAUSE)
        print(c(RED, "  model said:"))
        print(c(RED, wrap(lie["excerpt"], "    ")))
        time.sleep(PAUSE)
        print(c(GREEN, "  engine filed:"))
        print(c(GREEN, wrap(grounded, "    ")))
        status = "exact substring of the regulation" if verbatim else "NOT FOUND IN REGULATION"
        note = "replaced" if changed else "kept"
        print(c(DIM if verbatim else RED, f"    -> {note}; {status}\n"))
        time.sleep(PAUSE)

    if all_ok:
        print(c(GREEN + ";" + BOLD, f"All {len(LIES)} excerpts are verbatim regulation text. Nothing invented reaches the file."))
    else:
        print(c(RED + ";" + BOLD, "A non-verbatim excerpt got through."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
