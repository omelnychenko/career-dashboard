#!/usr/bin/env python3
"""Checks the three vault validators share.

`vault_schema.py` describes the shape and is read by the generator too; this
module is validation-only — it turns a shape mismatch into a sentence an author
can act on. A violation names what was expected and what was found, with the
file line number wherever one exists: the message has to be enough to fix the
file without opening a validator.

Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

from vault_schema import (
    Heading,
    body_offset,
    fm_entries,
    has_frontmatter,
    is_bullet,
    non_empty,
    parse_headings,
    read,
    split_frontmatter,
)


def fmt(values) -> str:
    return ", ".join(str(v) for v in values)


def first_lines(entries) -> dict[str, int]:
    """key -> line number of its first occurrence."""
    out: dict[str, int] = {}
    for key, line, _ in entries:
        out.setdefault(key, line)
    return out


def raw_values(entries) -> dict[str, str]:
    """key -> its value exactly as authored, quotes and brackets intact."""
    out: dict[str, str] = {}
    for key, _, val in entries:
        out.setdefault(key, val)
    return out


def missing_frontmatter(text: str) -> str:
    if text.startswith("---"):
        return "frontmatter opens with `---` but never closes — add the closing `---` line"
    return "no YAML frontmatter — the file must open with a `---` block"


def check_frontmatter_keys(entries, expected) -> list[str]:
    """Missing, unexpected and misordered keys, reported as three separate
    fixes — deleting a key, adding one and moving one are not the same edit."""
    out: list[str] = []
    seen = [k for k, _, _ in entries]
    line_of = first_lines(entries)
    unique = list(dict.fromkeys(seen))

    for key in unique:
        if seen.count(key) > 1:
            out.append(
                f"line {line_of[key]}: frontmatter key '{key}' appears "
                f"{seen.count(key)} times — each key appears exactly once"
            )
    for key in expected:
        if key not in seen:
            out.append(
                f"frontmatter: missing key '{key}' — the schema is exactly "
                f"these {len(expected)} keys in this order: {fmt(expected)}"
            )
    for key in unique:
        if key not in expected:
            out.append(
                f"line {line_of[key]}: frontmatter: unexpected key '{key}' — "
                f"the schema is exactly these {len(expected)} keys: {fmt(expected)}"
            )

    # Order is checked over the keys that are both present and expected, so a
    # missing or extra key does not also read as a reordering.
    present = [k for k in unique if k in expected]
    wanted = [k for k in expected if k in seen]
    if present != wanted:
        for i, (got, want) in enumerate(zip(present, wanted)):
            if got != want:
                out.append(
                    f"line {line_of[got]}: frontmatter key order — position "
                    f"{i + 1} is '{got}', expected '{want}'; required order: "
                    f"{fmt(expected)}"
                )
                break
    return out


def check_enum(key, value, allowed, line, *, allow_empty) -> list[str]:
    where = f"line {line}: " if line else "frontmatter: "
    expect = f"'{allowed[0]}'" if len(allowed) == 1 else f"one of: {fmt(allowed)}"
    if isinstance(value, list):
        return [f"{where}{key}: is a list; expected a single value, {expect}"]
    if value == "":
        if allow_empty:
            return []
        return [f"{where}{key}: is empty — required, {expect}"]
    if value not in allowed:
        return [f"{where}{key}: '{value}' is not {expect}"]
    return []


def check_no_html_comments(body: str, off: int) -> list[str]:
    """One stray comment currently renders as visible junk in the dashboard,
    so this is a hard failure rather than a warning."""
    out = []
    for n, line in enumerate(body.splitlines(), start=1):
        if "<!--" in line:
            out.append(
                f"line {n + off}: HTML comment `<!--` in the body — comments "
                f"render as visible text in the dashboard; delete the block"
            )
    return out


def check_preamble(preamble: list[str], off: int, expected_h1: str) -> list[str]:
    for i, line in enumerate(preamble, start=1):
        if line.strip():
            return [
                f"line {i + off}: content before the H1 ({line.strip()!r}) — "
                f"the body opens with `{expected_h1}`"
            ]
    return []


def check_single_h1(headings: list[Heading], expected: str, off: int) -> list[str]:
    h1s = [h for h in headings if h.level == 1]
    if not h1s:
        return [f"no H1 — the body must open with `# {expected}`"]
    out = []
    for extra in h1s[1:]:
        out.append(
            f"line {extra.line_no + off}: a second H1 '# {extra.text}' — "
            f"exactly one H1 per file"
        )
    if h1s[0].text != expected:
        out.append(
            f"line {h1s[0].line_no + off}: H1 is '{h1s[0].text}', expected "
            f"'{expected}'"
        )
    return out


def check_h1_content(headings: list[Heading], off: int, next_section: str) -> list[str]:
    h1s = [h for h in headings if h.level == 1]
    if not h1s:
        return []
    for i, line in enumerate(h1s[0].lines, start=1):
        if line.strip():
            return [
                f"line {h1s[0].line_no + i + off}: content sits directly under "
                f"the H1 ({line.strip()!r}) — the first section is `{next_section}`"
            ]
    return []


def check_heading_depth(headings: list[Heading], deepest: int, off: int) -> list[str]:
    allowed = ", ".join(f"H{n}" for n in range(1, deepest + 1))
    return [
        f"line {h.line_no + off}: H{h.level} '{h.text}' — this schema allows "
        f"{allowed} only"
        for h in headings
        if h.level > deepest
    ]


def check_bullet_list(h: Heading, off: int, ctx: str, *, allow_empty=False) -> list[str]:
    """Everything under `h` is an unordered-list line. Blank lines are fine;
    prose, numbered lists and tables are not."""
    out: list[str] = []
    if not non_empty(h.lines):
        if not allow_empty:
            out.append(
                f"line {h.line_no + off}: `{ctx}` is empty — expected an "
                f"unordered list"
            )
        return out
    for i, line in enumerate(h.lines, start=1):
        if not line.strip():
            continue
        if not is_bullet(line):
            out.append(
                f"line {h.line_no + i + off}: `{ctx}`: expected an "
                f"unordered-list line starting with '- ', found: "
                f"{line.strip()!r}"
            )
    return out


WIKI_LINK_RE = re.compile(r'^"\[\[.+\]\]"$')


def check_wiki_link(key: str, raw: str, line) -> list[str]:
    """A set link field is a quoted wiki-link: `key: "[[Target]]"`. Empty is
    allowed; anything else breaks Obsidian's backlink graph."""
    if raw == "":
        return []
    if WIKI_LINK_RE.match(raw):
        return []
    where = f"line {line}: " if line else "frontmatter: "
    return [
        f'{where}{key}: {raw} — a set {key} is a quoted wiki-link, e.g. '
        f'{key}: "[[Target Name]]"'
    ]


# --- The About-note shape, shared by Company and Person ---------------------


def validate_note(
    path: Path, entity: str, keys, label: str
) -> tuple[list[str], list[tuple[str, int, str]]]:
    """Company and Person are one schema with two key sets: one H1 equal to the
    file stem, one `## About` holding an unordered list, nothing deeper.

    Returns the violations and the parsed frontmatter entries, so a caller can
    add its own field rules without walking the frontmatter a third time.
    """
    text = read(path)
    fm, body = split_frontmatter(text)
    off = body_offset(text, body)
    out: list[str] = []

    if not has_frontmatter(text):
        out.append(missing_frontmatter(text))
        entries: list[tuple[str, int, str]] = []
    else:
        entries = fm_entries(text)
        out += check_frontmatter_keys(entries, keys)
        out += check_enum(
            "type", fm.get("type", ""), (entity,),
            first_lines(entries).get("type"), allow_empty=False,
        )

    out += check_no_html_comments(body, off)

    headings, preamble = parse_headings(body)
    out += check_preamble(preamble, off, f"# {path.stem}")
    out += check_heading_depth(headings, 2, off)
    out += check_single_h1(headings, path.stem, off)
    out += check_h1_content(headings, off, "## About")

    h2s = [h for h in headings if h.level == 2]
    if not h2s:
        out.append(
            f"no `## About` section — a {label} note carries exactly one H2, "
            f"named About"
        )
    else:
        for extra in h2s[1:]:
            out.append(
                f"line {extra.line_no + off}: extra H2 '{extra.text}' — a "
                f"{label} note carries exactly one H2, named About; fold this "
                f"section's content into `## About` as bullets"
            )
        about = h2s[0]
        if about.text != "About":
            out.append(
                f"line {about.line_no + off}: H2 is '{about.text}', expected "
                f"'About'"
            )
        out += check_bullet_list(about, off, f"## {about.text}")

    return out, entries
