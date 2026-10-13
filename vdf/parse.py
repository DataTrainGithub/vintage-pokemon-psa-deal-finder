"""Turn free-text titles (eBay titles, Cardmarket comments) into a CardKey.

Being strict here is what keeps false "bargains" out of the report: anything ambiguous,
qualified, reprinted or not actually graded is rejected.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .catalog import ALIASES, SETS, TOTAL_TO_SETS, normalise_variant
from .models import CardKey

# Titles containing any of these are never a real vintage graded card (or are not the card itself).
EXCLUDE = re.compile(
    r"\b(reprint|proxy|custom|fake|replica|orica|celebrations?|evolutions|25th|classic collection|"
    r"anniversary|digital|lot|bundle|choose|pick|you pick|ready|candidate|potential|raw|ungraded|"
    r"not graded|empty|label only|case only|slab only|no card|read description|art card|"
    r"metal|gold plated|sticker|jumbo|oversize|psa/dna|auto(graph)?|signed|mystery|repack|"
    r"break|cracked|damaged slab|japanese|japan|korean|chinese|german|french|italian|spanish)\b",
    re.I,
)
# PSA qualifiers (OC, ST, PD, OF, MK, MC) cut value hard; never compare them to clean slabs.
# Case-sensitive and anchored to the grade or brackets so words like "of" don't trigger it.
QUALIFIER = re.compile(r"\((OC|ST|PD|OF|MK|MC)\)|\bPSA\s*\d{1,2}\s*(OC|ST|PD|OF|MK|MC)\b|\bqualifier\b")
OTHER_GRADERS = re.compile(r"\b(BGS|beckett|CGC|SGC|ACE|TAG|GMA|MNT|AGS|PCA|HGA)\b", re.I)
GRADE = re.compile(
    r"\bPSA\s*[-:#]?\s*(?:gem\s*(?:mint|mt)|mint|nm[\s-]*mt|near\s*mint[\s-]*mint)?\s*(10|[1-9])(?![\d./])"
    r"|\b(?:gem\s*(?:mint|mt)|mint)\s*(10|9)\s*PSA\b",
    re.I,
)
NUM_SLASH = re.compile(r"\b(\d{1,3})\s*/\s*(\d{2,3})\b")
NUM_HASH = re.compile(r"#\s*([A-Z]{0,2}\d{1,3})\b", re.I)
FIRST_ED = re.compile(r"\b(1st|first)[\s.-]*(ed(ition|\.)?|ed)\b|\b1st\b", re.I)
SHADOWLESS = re.compile(r"\bshadow\s*less\b", re.I)
UNLIMITED = re.compile(r"\bunlimited\b", re.I)


@dataclass
class ParseResult:
    key: Optional[CardKey]
    reason: str = ""  # why parsing failed, for debugging/rejection stats


def parse_grade(text: str) -> Optional[int]:
    m = GRADE.search(text)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def parse_set(text: str) -> Optional[str]:
    low = text.lower()
    for alias, code in ALIASES:
        # (?!\s*/) stops "Base Set 2/102" (Blastoise #2) being read as "Base Set 2".
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z0-9])(?!\s*/)", low):
            return code
    return None


def parse_number(text: str, set_code: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (number, set_code inferred from the /total, if any). Grade text must be stripped first."""
    m = NUM_SLASH.search(text)
    if m:
        num, total = m.group(1).lstrip("0") or "0", int(m.group(2))
        candidates = TOTAL_TO_SETS.get(total, [])
        inferred = set_code if set_code in candidates else (candidates[0] if len(candidates) == 1 else None)
        return num, inferred
    m = NUM_HASH.search(text)
    if m:
        return m.group(1).upper().lstrip("0") or "0", None
    return None, None


def parse_variant(text: str, set_code: str) -> str:
    if SHADOWLESS.search(text):
        v = "shadowless"
    elif FIRST_ED.search(text):
        v = "1st"
    else:
        v = "unlimited"
    return normalise_variant(set_code, v)


def parse_title(text: str, grader: str = "PSA", allowed_grades=(9, 10), hint: Optional[CardKey] = None) -> ParseResult:
    """Parse a listing title. `hint` (the target we searched for) fills in what the title omits,
    but never overrides what the title explicitly says."""
    if EXCLUDE.search(text):
        return ParseResult(None, "excluded keyword")
    if OTHER_GRADERS.search(text) and not re.search(r"\bPSA\b", text, re.I):
        return ParseResult(None, "other grader")
    grade = parse_grade(text)
    if grade is None:
        return ParseResult(None, "no PSA grade")
    if grade not in allowed_grades:
        return ParseResult(None, f"grade {grade} not wanted")
    if QUALIFIER.search(text):
        return ParseResult(None, "PSA qualifier")

    stripped = GRADE.sub(" ", text)
    set_code = parse_set(stripped)
    number, inferred = parse_number(stripped, set_code)
    set_code = set_code or inferred
    if hint is not None:
        if set_code and set_code != hint.set_code:
            return ParseResult(None, "different set than target")
        if number and number != hint.number:
            return ParseResult(None, "different number than target")
        set_code = set_code or hint.set_code
        number = number or hint.number
    if not set_code:
        return ParseResult(None, "unknown set")
    if not number:
        return ParseResult(None, "no card number")

    variant = parse_variant(stripped, set_code)
    if hint is not None and variant != hint.variant:
        # "1st Edition" missing from a title we found by searching "1st edition" is common on
        # eBay, but guessing would compare an unlimited card to 1st-ed comps: reject instead.
        return ParseResult(None, f"variant {variant} != {hint.variant}")
    if variant == "unlimited" and UNLIMITED.search(stripped) is None and SETS[set_code].has_first_ed and hint is None:
        # Discovery mode: an unlabelled WotC card could be either print run; be conservative.
        return ParseResult(None, "edition not stated")
    return ParseResult(CardKey(set_code, number, variant, grade, grader))
