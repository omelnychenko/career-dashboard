#!/usr/bin/env python3
"""Company card validator — `Companies/<Company>.md`.

The shape it checks is the About-note shape, so the work lives in
`validate_common.validate_note()`; a company card is that shape plus its own
key set. Stdlib only.
"""

from __future__ import annotations

from pathlib import Path

from validate_common import validate_note
from vault_schema import COMPANY_KEYS


def validate(path: Path) -> list[str]:
    """Violations in one company card, empty list when it is clean."""
    out, _entries = validate_note(Path(path), "company", COMPANY_KEYS, "company")
    return out
