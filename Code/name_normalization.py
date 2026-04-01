#!/usr/bin/env python3
"""
Shared person-name normalization helpers for the Mokyr survey pipeline.
"""

import re
import unicodedata

TRANSLIT_MAP = str.maketrans({
    "ø": "o",
    "Ø": "O",
    "ı": "i",
    "İ": "I",
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ð": "d",
    "Ð": "D",
    "þ": "th",
    "Þ": "Th",
    "ł": "l",
    "Ł": "L",
})

_HONORIFICS_RE = re.compile(r"\b(?:dr|prof|professor)\.?\s*", re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_person_text(
    value: str,
    *,
    strip_parentheticals: bool = True,
    strip_honorifics: bool = True,
) -> str:
    value = (value or "").translate(TRANSLIT_MAP)
    value = value.replace("\u2019", "'").replace("\u02bc", "'")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    if strip_parentheticals:
        value = _PARENTHETICAL_RE.sub(" ", value)
    if strip_honorifics:
        value = _HONORIFICS_RE.sub(" ", value)
    value = value.replace('"', " ").replace("'", " ")
    value = _NON_ALNUM_RE.sub(" ", value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def person_name_key(first_name: str, last_name: str) -> tuple[str, str]:
    return (
        normalize_person_text(first_name),
        normalize_person_text(last_name),
    )
