"""Demo: a model cannot put an invented quote into the findings.

Run from the repo root (offline, no key, no network):

    python demo/grounding_demo.py             # all cases
    python demo/grounding_demo.py --case 1    # just the fabricated-clause case (the video shot)

A "lying model" stands in for the LLM and returns findings whose
`regulation_excerpt` is (1) a fabricated clause that would make the company look
compliant, (2) a correct quote with odd casing and whitespace, and (3) a loose
paraphrase. Each goes through the real public `analyze_compliance_gap()` pipeline.
The script prints what the model claimed next to what the engine returned, and
checks that every returned excerpt is an exact substring of the regulation.

What this proves, and what it does not:
- Proven: whatever the model writes, the excerpt that reaches the findings and the
  audit log is real text from the submitted regulation.
- Not proven: that it is the right clause. When the model's quote is not found, the
  engine substitutes the most similar sentence (case 3 can land on the wrong clause),
  and the API does not currently say which path was taken. A human still reviews.

Only the network call is swapped (the same seam the offline test suite uses). The
grounding code under test is the production code in ai_engine.py.
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

ARGS = sys.argv[1:]
PAUSE = 0.0 if "--fast" in ARGS else 0.7
USE_COLOR = sys.stdout.isatty() and "--no-color" not in ARGS
ONLY = int(ARGS[ARGS.index("--case") + 1]) if "--case" in ARGS else None


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


RED, GREEN, YELLOW, DIM, BOLD = "31", "32", "33", "2", "1"

CASES = [
    {
        "label": "Fabricated clause: 24 hours, which would make PaySetu look compliant",
        "title": "Incident reporting SLA",
        "excerpt": "Body corporates shall report cyber incidents to CERT-In within 24 hours of completing internal triage.",
        "note": "The invented 24-hour clause never reaches the file. The real 6-hour text does.",
    },
    {
        "label": "Real quote, sloppy formatting",
        "title": "Point of Contact not registered",
        "excerpt": "“SHALL DESIGNATE a Point of Contact   to interface with CERT-In”",
        "note": "Snapped to the exact characters in the source.",
    },
    {
        "label": "Loose paraphrase (limitation)",
        "title": "Logs stored outside India",
        "excerpt": "ICT logs have to be kept for six months on servers in India",
        "note": "Real text, but check the clause: closest-sentence matching can pick the wrong one. "
        "This is why findings are reviewed by a human.",
    },
]


def lying_model(*_args, **_kwargs) -> dict:
    """Stands in for ai_engine._provider_complete and returns the cases above."""
    return {
        "anomalies": [
            {
                "title": case["title"],
                "category": "reporting",
                "severity": "high",
                "gap_type": "non_compliant",
                "regulation_requirement": "See excerpt.",
                "regulation_excerpt": case["excerpt"],
                "current_state": "See company state.",
                "gap_description": f"Demo finding {i}.",
                "recommended_remediation": "Demo remediation.",
            }
            for i, case in enumerate(CASES)
        ]
    }


def wrap(text: str, indent: str) -> str:
    return textwrap.fill(text, width=92, initial_indent=indent, subsequent_indent=indent)


def main() -> int:
    ai_engine._provider_complete = lying_model  # swap only the network call
    result = ai_engine.analyze_compliance_gap(REGULATION, STATE)
    by_title = {a["title"]: a for a in result}

    print(c(BOLD, "\nCan a model slip an invented quote into the findings?\n"))
    all_ok = True
    for i, case in enumerate(CASES, start=1):
        if ONLY and i != ONLY:
            continue
        filed = by_title[case["title"]]["regulation_excerpt"]
        verbatim = filed in REGULATION
        all_ok &= verbatim
        print(c(BOLD, f"[{i}] {case['label']}"))
        time.sleep(PAUSE)
        print(c(RED, "  model wrote:"))
        print(c(RED, wrap(case["excerpt"], "    ")))
        time.sleep(PAUSE)
        print(c(GREEN, "  engine filed:"))
        print(c(GREEN, wrap(filed, "    ")))
        status = "exact substring of the regulation" if verbatim else "NOT FOUND IN REGULATION"
        print(c(DIM if verbatim else RED, f"    -> {status}. {case['note']}\n"))
        time.sleep(PAUSE)

    if all_ok:
        print(c(GREEN + ";" + BOLD, "Every filed excerpt is verbatim regulation text."))
    else:
        print(c(RED + ";" + BOLD, "A non-verbatim excerpt got through."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
