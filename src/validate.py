#!/usr/bin/env python3
"""Vault schema gate.

    python3 src/validate.py                 # the whole vault
    python3 src/validate.py <path> [...]    # the named files

Exit 0 when everything is clean, 1 when anything is not — the write pipeline
branches on that, so a violation must never come back as a success.

Whole-vault mode dispatches by where a file sits: the note named after its
folder is the company card, its siblings are applications, `People/*.md` are
people. Structure decides, not `type:` — dispatching on the field a file
declares would let a company card carrying `type: application` be checked
against the wrong schema and pass. Named-path mode has no such structure to go
on and dispatches on `type:`, where an unknown or missing value is itself the
violation.

`_templates/` is never swept: the templates carry placeholders and guidance
comments that are correct there and a violation anywhere else.

Stdlib only.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import validate_application
import validate_company
import validate_person
from vault_schema import (
    ENTITY_TYPES,
    application_files,
    company_card_files,
    person_files,
    read,
    split_frontmatter,
)

VALIDATORS = {
    "application": validate_application.validate,
    "company": validate_company.validate,
    "person": validate_person.validate,
}

# (type, singular, plural) in the order the summary line names them.
ENTITY_LABELS = (
    ("company", "company", "companies"),
    ("application", "application", "applications"),
    ("person", "person", "people"),
)


def is_template(path: Path) -> bool:
    return "_templates" in path.parts


def vault_jobs() -> list[tuple[str, Path]]:
    """Every note in the vault, paired with the schema its location implies."""
    jobs: list[tuple[str, Path]] = []
    for entity, files in (
        ("company", company_card_files()),
        ("application", application_files()),
        ("person", person_files()),
    ):
        jobs += [(entity, p) for p in files if not is_template(p)]
    return jobs


def dispatch(path: Path) -> tuple[str | None, list[str]]:
    """(entity type, violations) for one named path, keyed off `type:`."""
    if not path.exists():
        return None, [f"no such file: {path}"]
    if not path.is_file():
        return None, [f"not a file: {path}"]
    try:
        text = read(path)
    except OSError as exc:
        return None, [f"unreadable: {exc}"]
    fm, _ = split_frontmatter(text)
    entity = fm.get("type", None)
    if entity is None:
        return None, [
            f"frontmatter has no `type:` key — every note declares one of: "
            f"{', '.join(ENTITY_TYPES)}"
        ]
    if not isinstance(entity, str) or entity not in ENTITY_TYPES:
        return None, [
            f"frontmatter `type:` is {entity!r} — expected one of: "
            f"{', '.join(ENTITY_TYPES)}"
        ]
    return entity, VALIDATORS[entity](path)


def validate_path(path) -> list[str]:
    """Violations in one file, empty list when it is clean. The importable
    entry point: `from validate import validate_path`."""
    return dispatch(Path(path))[1]


def summary(passed: Counter) -> str:
    parts = [
        f"{passed[key]} {one if passed[key] == 1 else many}"
        for key, one, many in ENTITY_LABELS
    ]
    return ", ".join(parts)


def main(argv: list[str]) -> int:
    if argv:
        jobs: list[tuple[str | None, Path]] = [(None, Path(a)) for a in argv]
    else:
        jobs = list(vault_jobs())

    passed: Counter = Counter()
    failures: list[tuple[Path, list[str]]] = []

    for entity, path in jobs:
        if entity is None:
            entity, violations = dispatch(path)
        else:
            violations = VALIDATORS[entity](path)
        if violations:
            failures.append((path, violations))
        elif entity is not None:
            passed[entity] += 1

    if not failures:
        n = len(jobs)
        print(
            f"OK — {summary(passed)}; {n} file{'' if n == 1 else 's'}, "
            f"no violations."
        )
        return 0

    for path, violations in failures:
        print(path)
        for v in violations:
            print(f"  {v}")
    total = sum(len(v) for _, v in failures)
    print(
        f"FAILED — {len(failures)} of {len(jobs)} files carry {total} "
        f"violation{'' if total == 1 else 's'}. Passed: {summary(passed)}."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
