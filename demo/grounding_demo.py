"""Demo: an invented quote is never presented as a verified citation.

Run from the repo root (offline, no key, no network):

    python demo/grounding_demo.py             # all cases
    python demo/grounding_demo.py --case 1    # just the fabricated-clause case (the video shot)

A "lying model" stands in for the LLM and returns findings whose `regulation_excerpt`
is (1) a fabricated 24-hour clause that would make the company look compliant,
(2) a real quote with odd casing and whitespace, (3) a loose paraphrase, and (4) a
quote about something the regulation never mentions. Each one goes through the real
public `analyze_compliance_gap()` pipeline. The script prints what the model wrote,
how the server classified it (`excerpt_match`), the badge the UI shows for that
class, and the text the finding now cites.

What this shows (checked against the real output, not assumed):
- Only a quote found in the source is marked "exact" (UI: "Verified · verbatim").
- An invented or paraphrased quote is marked "nearest" (UI: amber "Unverified citation
  · closest clause") or "none" (UI: red "No matching source"). The finding then cites
  the closest real clause, which can be the WRONG clause (case 3). That is why it is
  flagged for a human, not presented as verified.

Only the network call is swapped (the same seam the offline test suite uses). The
grounding code under test is the production code in grounding.py and ai_engine.py.
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

# What static/index.html shows for each server-side match class, and its colour here.
BADGE = {
    "exact": ("Verified · verbatim", GREEN),
    "fragment": ("Partial quote", YELLOW),
    "nearest": ("Unverified citation · closest clause", YELLOW),
    "none": ("No matching source", RED),
}

CASES = [
    {
        "label": "Invented clause: 24 hours, which would make PaySetu look compliant",
        "title": "Incident reporting SLA",
        "excerpt": "Body corporates shall report cyber incidents to CERT-In within 24 hours of completing internal triage.",
    },
    {
        "label": "Real quote, sloppy formatting",
        "title": "Point of Contact not registered",
        "excerpt": "“SHALL DESIGNATE a Point of Contact   to interface with CERT-In”",
    },
    {
        "label": "Loose paraphrase",
        "title": "Logs stored outside India",
        "excerpt": "ICT logs have to be kept for six months on servers in India",
    },
    {
        "label": "Quote about something the direction never mentions",
        "title": "Quantum-safe cryptography",
        "excerpt": "Entities must migrate to post-quantum cryptography by 2027.",
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

    print(c(BOLD, "\nThe model invents a quote. Does it get presented as verified?\n"))
    ok = True
    for i, case in enumerate(CASES, start=1):
        if ONLY and i != ONLY:
            continue
        a = by_title.get(case["title"])
        if a is None:  # the engine may drop a finding outright
            print(c(BOLD, f"[{i}] {case['label']}"), c(DIM, "-> finding dropped by the engine\n"))
            continue
        match, score = a.get("excerpt_match"), a.get("excerpt_score")
        badge, color = BADGE.get(match, (f"unknown match '{match}'", RED))
        invented = i != 2
        # The property we demo: invented or paraphrased quotes are never "exact".
        ok &= not (invented and match == "exact")
        ok &= a["regulation_excerpt"] in REGULATION

        print(c(BOLD, f"[{i}] {case['label']}"))
        time.sleep(PAUSE)
        print(c(RED if invented else DIM, "  model wrote:"))
        print(c(RED if invented else DIM, wrap(case["excerpt"], "    ")))
        time.sleep(PAUSE)
        score_txt = f" (score {score:.2f})" if isinstance(score, (int, float)) else ""
        print(c(color + ";" + BOLD, f"  server: excerpt_match = {match}{score_txt}  ->  UI badge \"{badge}\""))
        time.sleep(PAUSE)
        label = "  finding now cites (real text, for a human to check):" if match != "exact" else "  finding cites:"
        print(c(DIM, label))
        print(wrap(a["regulation_excerpt"], "    "))
        print()
        time.sleep(PAUSE)

    if ok:
        print(c(GREEN + ";" + BOLD, "No invented quote was marked verified. Only the real quote got the green badge."))
    else:
        print(c(RED + ";" + BOLD, "An invented quote was marked verified, or a cited excerpt is not regulation text."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
