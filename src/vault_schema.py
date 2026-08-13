#!/usr/bin/env python3
"""Shared vault schema: enums, frontmatter parsing, heading walking.

Imported by both the generator (which trusts the vault) and the validators
(which prove it). One definition of every enum lives here — a second copy
elsewhere drifts, and a drifted enum silently accepts a value the other half
rejects.

Stdlib only. This repo has no dependencies and keeps it that way.
"""

from __future__ import annotations

import re
from pathlib import Path

# --- Paths -----------------------------------------------------------------

VAULT = Path(
    "/Users/omelnychenko/Library/Mobile Documents/iCloud~md~obsidian/Documents"
    "/Life/Career"
)
COMPANIES = VAULT / "Companies"
PEOPLE = VAULT / "People"
TEMPLATES = VAULT / "_templates"


# --- Enums -----------------------------------------------------------------

ENTITY_TYPES = ("application", "company", "person")

# Fork postings collapse to the lower level: the label inflates, the
# requirements do not.
SENIORITY = ("Junior", "Middle", "Senior", "Lead")

# Lifecycle of one application. Authored by hand — stages never derive it.
STATUS = ("applied", "active", "rejected", "offer", "withdrawn")
TERMINAL_STATUS = ("rejected", "offer", "withdrawn")

# How far it got. Applied and Offer are terminal and come from `status`, so a
# stage never carries them.
STAGE_PHASES = ("Screening", "Tech", "Final")
STAGE_RESULTS = ("scheduled", "passed", "failed")

SALARY_PERIODS = ("month", "hour", "year")
# These currencies have a stable dashboard conversion to EUR/month. Every
# application still preserves its authored three-letter currency code.
SALARY_CONVERTIBLE_CURRENCIES = ("EUR", "USD", "GBP")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# Question scores in a stage table, on the `Knowledge base/_Skills.md` scale.
SCORE_MIN, SCORE_MAX = 1, 5

FIT_MIN, FIT_MAX = 1, 10

# Frontmatter keys, in the order the templates declare them. Order is part of
# the schema: a file that reads differently top to bottom is harder to scan
# against its siblings, and the diff of a reordered file hides the real change.
COMPANY_KEYS = ("type", "name", "website", "location", "industry")
PERSON_KEYS = (
    "type", "name", "role", "current_company",
    "linkedin", "email", "phone", "telegram",
)
APPLICATION_KEYS = (
    "type", "company", "role", "seniority", "stack", "source",
    "applied_date", "status", "stages",
    "salary_amount", "salary_period", "salary_currency", "salary_note",
    "location", "closed_date", "fit_score", "fit_note",
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Frontmatter -----------------------------------------------------------

def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body).

    Handles the small YAML subset the vault uses: scalars, `[a, b]` inline
    lists, and `key:` followed by `  - item` block lists. Not a full YAML
    parser. Key insertion order is preserved, so callers can check it.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fm: dict = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # Block-list form: `key:` with empty value followed by `  - item` lines.
        if val == "":
            block: list = []
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("- "):
                block.append(unquote(lines[j].lstrip()[2:].strip()))
                j += 1
            if block:
                fm[key] = block
                i = j
                continue
        fm[key] = parse_value(val)
        i += 1
    return fm, body


def parse_value(val: str):
    if val == "":
        return ""
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [unquote(x.strip()) for x in inner.split(",") if x.strip()]
    return unquote(val)


def unquote(s: str) -> str:
    """Strip surrounding quotes and Obsidian wiki-link brackets."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    m = re.fullmatch(r"\[\[(.+?)\]\]", s.strip())
    if m:
        return m.group(1)
    return s


def has_frontmatter(text: str) -> bool:
    return text.startswith("---") and text.find("\n---", 3) != -1


def fm_entries(text: str) -> list[tuple[str, int, str]]:
    """Ordered `(key, file line number, raw value)` over the frontmatter block.

    `split_frontmatter()` parses values into a dict and discards both the line
    number and the value as authored. A caller that has to name a line, or that
    cares about the raw form rather than the parsed one — "a set `company` is a
    quoted wiki-link" is about the text, not the value — needs this instead.
    Keys come back in document order, duplicates included.
    """
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    pre = text[3:end]
    # The opening `---` is file line 1; `pre` starts at its end-of-line.
    first = 1 + (len(pre) - len(pre.lstrip("\n")))
    lines = pre.strip("\n").splitlines()
    out: list[tuple[str, int, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            i += 1
            continue
        key, _, val = line.partition(":")
        out.append((key.strip(), first + i, val.strip()))
        if val.strip() == "":
            # Block-list form: swallow the `  - item` lines so an item that
            # happens to contain a colon is not read as a key.
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("- "):
                j += 1
            if j > i + 1:
                i = j
                continue
        i += 1
    return out


def body_offset(text: str, body: str) -> int:
    """Add to a body-relative line number to get the file line number.

    `parse_headings()` numbers lines from the start of the body; an author
    reads line numbers from the start of the file. `body` is a suffix of
    `text`, so the difference is the newline count of everything before it.
    """
    return text[: len(text) - len(body)].count("\n")


# --- Headings --------------------------------------------------------------

class Heading:
    """One `#`-heading plus the lines under it, up to the next heading."""

    __slots__ = ("level", "text", "line_no", "lines")

    def __init__(self, level: int, text: str, line_no: int):
        self.level = level
        self.text = text
        self.line_no = line_no
        self.lines: list[str] = []

    def content(self) -> str:
        return "\n".join(self.lines).strip()

    def __repr__(self) -> str:
        return f"<h{self.level} {self.text!r} @{self.line_no}>"


def parse_headings(body: str) -> tuple[list[Heading], list[str]]:
    """Return (headings in document order, lines before the first heading).

    Fenced code blocks are skipped so a `# comment` inside one is not read as
    a heading.
    """
    headings: list[Heading] = []
    preamble: list[str] = []
    current: Heading | None = None
    in_fence = False
    for n, line in enumerate(body.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            current = Heading(len(m.group(1)), m.group(2).strip(), n)
            headings.append(current)
            continue
        (current.lines if current is not None else preamble).append(line)
    return headings, preamble


def children_of(headings: list[Heading], parent: Heading) -> list[Heading]:
    """Headings nested under `parent`, at any depth, until its next sibling."""
    start = headings.index(parent)
    out = []
    for h in headings[start + 1:]:
        if h.level <= parent.level:
            break
        out.append(h)
    return out


# --- Body shapes -----------------------------------------------------------

def is_bullet(line: str) -> bool:
    return bool(re.match(r"^\s*-\s+\S", line))


def non_empty(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip()]


def is_table_divider(line: str) -> bool:
    """`|---|:--:|` — the row separating a table header from its body."""
    s = line.strip()
    return s.startswith("|") and bool(
        re.fullmatch(r"\|(\s*:?-{1,}:?\s*\|)+", s)
    )


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse_table(lines: list[str]) -> tuple[list[str], list[list[str]]] | None:
    """Return (header cells, body rows) for a block that is one whole table.

    None when the lines are not exactly a table: without a divider row the
    pipes are literal text, and guessing a table out of them would let a
    malformed block validate.
    """
    rows = non_empty(lines)
    if len(rows) < 2:
        return None
    if not all(r.strip().startswith("|") for r in rows):
        return None
    if not is_table_divider(rows[1]):
        return None
    header = split_row(rows[0])
    body = [split_row(r) for r in rows[2:]]
    return header, body


# --- Stage entries ---------------------------------------------------------

def parse_stage_entry(entry: str) -> dict | None:
    """`date | name | phase | result[ | interviewer]` -> dict, or None.

    Phase and result are authored enums rather than keyword-guessed from free
    text, so a value outside the enum is a typo to report, never a default to
    fall back on.
    """
    parts = [p.strip() for p in str(entry).split("|")]
    if len(parts) < 4 or len(parts) > 5:
        return None
    # Case-sensitive on both enums. Lowercasing `result` would quietly accept a
    # `Passed` that `Tech`/`tech` next to it does not, and the point of writing
    # these as enums is that the vault reads the same way in every file.
    date, name, phase, result = parts[0], parts[1], parts[2], parts[3]
    interviewer = parts[4] if len(parts) > 4 else ""
    if not DATE_RE.match(date) or not name:
        return None
    if phase not in STAGE_PHASES or result not in STAGE_RESULTS:
        return None
    return {
        "stage": name,
        "phase": phase,
        "date": date,
        "result": result,
        "interviewer": unquote(interviewer),
    }


# --- File discovery --------------------------------------------------------

def company_card_files() -> list[Path]:
    """`Companies/<Company>/<Company>.md` — named after its folder so
    `[[Company]]` resolves."""
    return sorted(f for f in COMPANIES.glob("*/*.md") if f.stem == f.parent.name)


def application_files() -> list[Path]:
    """Every `Companies/<Company>/<date — Role>.md` — the company card
    excluded by the folder-name rule rather than by its `type:`."""
    return sorted(f for f in COMPANIES.glob("*/*.md") if f.stem != f.parent.name)


def person_files() -> list[Path]:
    return sorted(PEOPLE.glob("*.md"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")
