"""Excerpt grounding and clause coverage: pure functions over the submitted regulation text.

Every finding's `regulation_excerpt` is matched back to the regulation and replaced with
the exact source text, and the match is reported honestly:

    exact     the model's quote was found verbatim (ignoring case, whitespace, quote style)
    fragment  one "..."-separated part of the quote was found verbatim
    nearest   not found; the clause sharing the most words with it is cited instead
              (an unverified citation the UI should flag)
    none      nothing in the regulation resembles it; the closest clause text is kept so
              the excerpt is still a real quote, but it has no span and must not be trusted

Offsets are Python string indices into the regulation exactly as submitted, end exclusive,
so regulation[start:end] == excerpt. No network calls, no I/O, stdlib only.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "MAX_EXCERPT_CHARS",
    "NEAREST_MIN_SCORE",
    "Clause",
    "Grounding",
    "RegulationIndex",
    "build_coverage",
    "normalized_with_map",
    "truncate_verbatim",
]

MAX_EXCERPT_CHARS = 200
# A "nearest" citation must share at least this fraction of the excerpt's words with the
# clause; below it the citation is reported as "none".
NEAREST_MIN_SCORE = 0.3

MatchType = Literal["exact", "fragment", "nearest", "none"]

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9(\"'])|\n+")
WORD_RE = re.compile(r"[a-z0-9]{3,}")
_ELLIPSIS_RE = re.compile(r"\.{3}|…")
_MIN_FRAGMENT_CHARS = 20
MIN_SENTENCE_CHARS = 15

# Text addressed to an AI rather than stating an obligation (prompt-injection attempts).
_INSTRUCTION_RE = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|prompts?|rules?)\b"
    r"|\b(automated systems?|language models?|system prompt|ai (assistants?|models?|systems?))\b"
    r"|\byou are (an?|the) \w+",
    re.IGNORECASE,
)
_OBLIGATION_RE = re.compile(
    r"\b(shall|must|required?|requires|should|will|may not|prohibited|ensure|obliged|need to)\b",
    re.IGNORECASE,
)
_HEADING_START_RE = re.compile(r"^(section|article|part|chapter|schedule|annex|§|\(?\d+(\.\d+)*[.)]?\s)", re.IGNORECASE)
_MAX_HEADING_WORDS = 8


def _normalize_char(ch: str) -> str:
    """Casefold one character and unify quotes and dashes (ASCII skips the Unicode tables)."""
    if ch.isascii():
        return ch.lower()  # NFKC and _QUOTE_MAP leave ASCII unchanged, and casefold == lower
    return unicodedata.normalize("NFKC", ch).translate(_QUOTE_MAP).casefold()


def normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Casefold, unify quotes/dashes, collapse whitespace; map each char back to the source."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        for c in _normalize_char(ch):
            if c.isspace():
                if prev_space:
                    continue
                c, prev_space = " ", True
            else:
                prev_space = False
            out.append(c)
            index.append(i)
    return "".join(out), index


def truncate_verbatim(text: str, limit: int) -> str:
    """Shorten a quote by cutting it, never adding characters, so it stays verbatim."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:")


def is_instruction_like(sentence: str) -> bool:
    """Text that talks to an AI instead of stating an obligation (e.g. "ignore all previous instructions")."""
    return bool(_INSTRUCTION_RE.search(sentence))


def is_bare_heading(sentence: str) -> bool:
    """A short title such as "Section 4.1 Data Retention." that states no obligation."""
    words = sentence.split()
    if len(words) > _MAX_HEADING_WORDS or _OBLIGATION_RE.search(sentence):
        return False
    if _HEADING_START_RE.match(sentence):
        return True
    alpha = [w for w in words if w[:1].isalpha()]
    capitalized = sum(1 for w in alpha if w[0].isupper())
    return bool(alpha) and capitalized / len(alpha) >= 0.6


@dataclass(frozen=True)
class Clause:
    """One sentence of the regulation, with its span in the source text."""

    text: str
    start: int
    end: int
    norm: str
    words: frozenset[str]


@dataclass(frozen=True)
class Grounding:
    """A verbatim excerpt and how it was matched; `span` is None only for match "none"."""

    text: str
    match: MatchType
    score: float
    span: tuple[int, int] | None


def _split_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Sentences (stripped) with their [start, end) offsets, split like SENTENCE_SPLIT_RE."""
    pieces: list[tuple[str, int, int]] = []
    pos = 0
    bounds = [(m.start(), m.end()) for m in SENTENCE_SPLIT_RE.finditer(text)] + [(len(text), len(text))]
    for sep_start, sep_end in bounds:
        raw = text[pos:sep_start]
        start = pos + (len(raw) - len(raw.lstrip()))
        end = sep_start - (len(raw) - len(raw.rstrip()))
        if end > start:
            pieces.append((text[start:end], start, end))
        pos = sep_end
    return pieces


class RegulationIndex:
    """A regulation prepared once, so many excerpts can be grounded against it cheaply.

    The normalized text and its map back to source offsets are built up front. The clause
    list (for the closest-clause fallback and for coverage) is built on first use and then
    shared.
    """

    def __init__(self, regulation: str) -> None:
        self.text = regulation
        self.norm, self.index = normalized_with_map(regulation)
        self._clauses: list[Clause] | None = None

    def locate(self, norm_fragment: str) -> tuple[int, str] | None:
        """(source start offset, exact source text) of a normalized fragment, or None."""
        pos = self.norm.find(norm_fragment)
        if pos == -1:
            return None
        start = self.index[pos]
        end = self.index[min(pos + len(norm_fragment), len(self.index)) - 1] + 1
        raw = self.text[start:end]
        return start + (len(raw) - len(raw.lstrip())), raw.strip()

    def clauses(self) -> list[Clause]:
        """Obligation candidates: sentences of 15+ characters, minus bare headings and
        instruction-like text (injection attempts). If that filter would leave nothing,
        every sentence of 15+ characters is kept."""
        if self._clauses is None:
            sentences = [s for s in _split_with_spans(self.text) if len(s[0]) >= MIN_SENTENCE_CHARS]
            kept = [s for s in sentences if not is_bare_heading(s[0]) and not is_instruction_like(s[0])]
            self._clauses = []
            for sentence, start, end in kept or sentences:
                norm = normalized_with_map(sentence)[0]
                self._clauses.append(Clause(sentence, start, end, norm, frozenset(WORD_RE.findall(norm))))
        return self._clauses

    def closest_clause(self, norm_excerpt: str) -> tuple[Clause | None, float]:
        """The clause sharing the most words with the excerpt (difflib similarity breaks ties)
        and that word-overlap fraction.

        Same result as ranking every clause by (word overlap, difflib ratio) and taking the
        first best, but the quadratic difflib ratio is only computed for the clauses tied on
        the best overlap.
        """
        clauses = self.clauses()
        if not clauses:
            return None, 0.0
        target = set(WORD_RE.findall(norm_excerpt))
        overlaps = [len(target & c.words) / len(target) if target else 0.0 for c in clauses]
        top = max(overlaps)
        best, best_ratio = clauses[0], -1.0
        for clause, overlap in zip(clauses, overlaps):
            if overlap != top:
                continue
            ratio = difflib.SequenceMatcher(None, norm_excerpt, clause.norm, autojunk=False).ratio()
            if ratio > best_ratio:
                best, best_ratio = clause, ratio
        return best, top

    def _verbatim(self, start: int, text: str, match: MatchType, score: float) -> Grounding:
        quote = truncate_verbatim(text, MAX_EXCERPT_CHARS)
        return Grounding(quote, match, round(score, 3), (start, start + len(quote)))

    def ground(self, excerpt: str) -> Grounding:
        """Locate the model's excerpt in the regulation and return the exact source text.

        The excerpt is always a real quote from the regulation; `match`, `score` and `span`
        say how far it can be trusted (see the module docstring).
        """
        norm_ex = normalized_with_map(excerpt)[0].strip().strip("\"'…. ")
        if norm_ex:
            found = self.locate(norm_ex)
            if found is not None:
                return self._verbatim(*found, "exact", 1.0)
            # The model sometimes joins two fragments with "..."; ground the longest fragment.
            fragments = sorted((f.strip() for f in _ELLIPSIS_RE.split(norm_ex)), key=len, reverse=True)
            for fragment in fragments:
                if len(fragment) >= _MIN_FRAGMENT_CHARS:
                    found = self.locate(fragment)
                    if found is not None:
                        return self._verbatim(*found, "fragment", len(fragment) / len(norm_ex))
        # Not quoted verbatim: cite the clause that shares the most words with it.
        clause, overlap = self.closest_clause(norm_ex)
        if clause is None:
            return Grounding(truncate_verbatim(self.text.strip(), MAX_EXCERPT_CHARS), "none", 0.0, None)
        if overlap < NEAREST_MIN_SCORE:
            return Grounding(truncate_verbatim(clause.text, MAX_EXCERPT_CHARS), "none", round(overlap, 3), None)
        return self._verbatim(clause.start, clause.text, "nearest", overlap)


def _span(value: Any) -> tuple[int, int] | None:
    if (
        isinstance(value, (list, tuple)) and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value) and value[0] < value[1]
    ):
        return value[0], value[1]
    return None


def build_coverage(regulation_text: str, anomalies: list[dict]) -> list[dict]:
    """Deterministic clause-by-clause coverage of the regulation by the findings.

    Each clause (see RegulationIndex.clauses) gets the ids of the findings whose grounded
    `excerpt_span` overlaps it, and a status: "gap" if any of them is non_compliant,
    "needs_info" if they are all insufficient_information, else "not_flagged". Findings
    without a span (match "none", or from an older client) map to no clause.
    """
    clauses = RegulationIndex(regulation_text).clauses()
    spans = [(a, _span(a.get("excerpt_span"))) for a in anomalies if isinstance(a, dict)]
    coverage: list[dict] = []
    for number, clause in enumerate(clauses, start=1):
        hits = [a for a, span in spans if span and span[0] < clause.end and clause.start < span[1]]
        gap_types = {a.get("gap_type") for a in hits}
        if "non_compliant" in gap_types:
            status = "gap"
        elif hits:
            status = "needs_info"
        else:
            status = "not_flagged"
        coverage.append({
            "id": f"CL-{number:03d}",
            "text": clause.text,
            "span": [clause.start, clause.end],
            "status": status,
            "finding_ids": [str(a.get("id", "")) for a in hits],
        })
    return coverage
