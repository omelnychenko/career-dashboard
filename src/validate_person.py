#!/usr/bin/env python3
"""Person note validator — `People/<Full Name>.md`.

Person is the same shape as Company: one H1 equal to the file stem, one
`## About` holding an unordered list, no heading deeper than H2. That shape
lives in `validate_common.validate_note()` — a second copy here would be the
drift the shared modules exist to prevent. What is genuinely person-only is the
key set and `current_company`, which is a link into the company graph and so has
a form the free-text fields do not.

Stdlib only.
"""

from __future__ import annotations

from pathlib import Path

from validate_common import check_wiki_link, first_lines, raw_values, validate_note
from vault_schema import PERSON_KEYS


def validate(path: Path) -> list[str]:
    """Violations in one person note, empty list when it is clean."""
    path = Path(path)
    out, entries = validate_note(path, "person", PERSON_KEYS, "person")

    # `current_company: "[[Acme]]"` is what puts this person in Acme's
    # backlinks. Bare text looks identical in the editor and links nothing.
    raw = raw_values(entries)
    if "current_company" in raw:
        out += check_wiki_link(
            "current_company",
            raw["current_company"],
            first_lines(entries).get("current_company"),
        )
    return out
