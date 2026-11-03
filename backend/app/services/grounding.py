"""Evidence verification.

A claim is only stored if its quote is a real substring of the cited transcript
segment. Matching collapses whitespace and ignores case, but returns offsets
into the original text so the UI can highlight the exact span.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUOTE_WRAPPERS = "".join(chr(code) for code in (0x22, 0x27, 0x201C, 0x201D, 0x2018, 0x2019))
_TRAILING = ".,;:"


@dataclass(frozen=True)
class VerifiedQuote:
    start: int
    end: int
    text: str


def _normalize_ws(text: str) -> tuple[str, list[int]]:
    """Collapse runs of whitespace, keeping a 1:1 map back to original indices."""
    chars: list[str] = []
    mapping: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if chars and not previous_space:
                chars.append(" ")
                mapping.append(index)
                previous_space = True
            continue
        chars.append(char)
        mapping.append(index)
        previous_space = False
    while chars and chars[-1] == " ":
        chars.pop()
        mapping.pop()
    return "".join(chars), mapping


def verify_quote(segment_text: str, quote: str) -> VerifiedQuote | None:
    """Return the verified span, or None when the quote is not supported."""
    candidate = quote.strip().strip(_QUOTE_WRAPPERS).strip().rstrip(_TRAILING).strip()
    if len(candidate) < 3:
        return None

    norm_segment, mapping = _normalize_ws(segment_text)
    norm_quote, _ = _normalize_ws(candidate)
    if not norm_segment or not norm_quote:
        return None

    match = re.search(re.escape(norm_quote), norm_segment, flags=re.IGNORECASE)
    if match is None:
        return None

    start = mapping[match.start()]
    end = mapping[match.end() - 1] + 1
    return VerifiedQuote(start=start, end=end, text=segment_text[start:end])


def quote_supported(segment_text: str, phrase: str | None) -> bool:
    if not phrase:
        return False
    return verify_quote(segment_text, phrase) is not None
