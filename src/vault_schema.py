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
APPLICATIONS = VAULT / "Applications"
COMPANIES = VAULT / "Companies"
TEMPLATES = VAULT / "_templates"


# --- Enums -----------------------------------------------------------------

ENTITY_TYPES = ("application", "company")

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

# Fit score on an application card: one decimal place at most. The bounds are
# floats so the range a violation prints is written the way the score is.
FIT_MIN, FIT_MAX = 1.0, 5.0

# Frontmatter keys, in the order the templates declare them. Order is part of
# the schema: a file that reads differently top to bottom is harder to scan
# against its siblings, and the diff of a reordered file hides the real change.
COMPANY_KEYS = ("type", "name", "website", "location", "industry")
APPLICATION_KEYS = (
    "type", "company", "role", "seniority", "stack", "source",
    "applied_date", "status", "stages",
    "salary_amount", "salary_period", "salary_currency", "salary_note",
    "location", "closed_date", "fit_score", "fit_note",
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Names -----------------------------------------------------------------

# An application filename is `<company> • <role> • <date>.md`. The separator is
# a bullet with a space on each side: it reads as punctuation, it is legal in a
# filename everywhere the vault syncs, and it is rare enough in a company or a
# role that sanitizing it away costs nothing.
NAME_SEP = " • "
# Stem length cap, chosen well under the 255-byte limit of the filesystems the
# vault crosses — the same name has to survive iCloud, git and a zip.
NAME_MAX = 180
# Contract artifacts live in `Companies/_docs/<Company>/`. The leading
# underscore sorts them away from the cards and marks the folder as machinery,
# the way `_templates` does.
DOCS_DIRNAME = "_docs"

# Obsidian-hostile characters plus the separator itself.
_NAME_BAD = set('/\\:|#^[]•?*"<>')


def sanitize_name_part(s: str) -> str:
    """One field of an application filename, made safe to write and to read back.

    Two rules in one pass. The first is about the outside world: `/`, `\\`, `:`
    and the link-syntax characters either cannot appear in a filename or break
    the `[[...]]` parser that reads one. The second is about this schema — the
    separator is in the replaced set, so no field can carry one, and a name
    built out of sanitized parts therefore splits back into exactly three
    fields and no other number. That round trip is what lets the filename be a
    record of company, role and date rather than only a label for one.

    Control characters become a space rather than a dash because they stand
    where a space was meant; whitespace runs then collapse. Leading and
    trailing `-`, `.` and whitespace go last: a name starting with a dot is
    hidden, and one ending in a dot or a space is silently stored under a
    different name by some filesystems than the one that was asked for.
    """
    out = []
    for ch in str(s):
        if ch in _NAME_BAD:
            out.append("-")
        elif ord(ch) < 32:
            out.append(" ")
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip(" -.")


def application_filename(company: str, role: str, applied_date: str) -> str:
    """`<Company> • <Role> • <YYYY-MM-DD>.md` — the whole identity of a card.

    Nothing stores this name. The validator recomputes it from the frontmatter
    and compares, so a card whose fields are edited without a rename reports
    itself instead of quietly disagreeing with its own contents. That only
    holds while the function is deterministic: the same three fields in, the
    same name out — no clock, no counter, no disambiguating suffix. Two
    applications to one company on one day with one role title are the same
    application, and collapsing onto the same name is the right answer.

    `applied_date` goes in verbatim; it is ISO by the time it arrives, and
    sanitizing it could only hide a malformed date the validator wants to see.
    Over `NAME_MAX` the role is what gives — it is the field that can run long,
    and cutting the company or the date would break both the name sort and the
    split back into fields. That is a cap on the role, not a guarantee about the
    stem: a company long enough to blow the budget on its own leaves the role
    empty and the name still over, because the alternative is a card no longer
    filed under its own company. A company name that long is a frontmatter
    problem, and it is visible as one.
    """
    c = sanitize_name_part(company)
    r = sanitize_name_part(role)
    stem = f"{c}{NAME_SEP}{r}{NAME_SEP}{applied_date}"
    if len(stem) > NAME_MAX:
        keep = len(r) - (len(stem) - NAME_MAX)
        # A cut lands mid-word as often as not, and the leftover space or
        # hyphen would then read as a typo rather than as a truncation.
        r = r[: max(keep, 0)].rstrip(" -")
        stem = f"{c}{NAME_SEP}{r}{NAME_SEP}{applied_date}"
    return f"{stem}.md"


def split_application_stem(stem: str) -> tuple[str, str, str] | None:
    """`(company, role, date)` out of a name, or None when it is not one.

    Exactly three parts and the third a date, or nothing. The strictness is the
    point: this is how a reader recovers the fields when the frontmatter is
    missing or empty, and half-reading a name that was never built by
    `application_filename()` would invent a company out of whatever sat before
    the first bullet. Sanitization keeps the separator out of every field, so a
    well-formed name splits into three parts and a name that splits into some
    other number is by construction not one of ours.
    """
    parts = stem.split(NAME_SEP)
    if len(parts) != 3 or not DATE_RE.match(parts[2]):
        return None
    return parts[0], parts[1], parts[2]


def company_dir_for(app_path: Path) -> Path:
    """The `Companies/` folder that governs `app_path`.

    Resolved from the file rather than from the module-level `VAULT`, because a
    validator judges whatever file it is handed: a fixture written into a temp
    directory has its own sibling `Companies/`, and answering out of the vault
    constant would judge that fixture against the real vault — passing or
    failing it on cards it does not own.

    `resolve()` first, so the answer comes from where the file sits and not from
    how it was typed. A path given relative to the shell — a bare filename, or
    one starting `./` — otherwise walks two levels up from nothing and looks for
    `Companies/` beside the caller's working directory, which is how the same
    file validates differently depending on which folder the command ran in.
    """
    return app_path.resolve().parent.parent / "Companies"


def company_card_exists(app_path: Path, company: str) -> bool:
    """Whether this company has earned a card in the vault `app_path` lives in.

    Decides which of the two legal forms of `company:` the field must take, so
    it asks the filesystem rather than the frontmatter. The name goes through
    `sanitize_name_part()` because the card is filed under the sanitized name
    too — the raw value would miss the card of any company whose name carries a
    `:` or a `/`.
    """
    return (
        company_dir_for(app_path) / f"{sanitize_name_part(company)}.md"
    ).is_file()


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
    """`Companies/<Company>.md` — flat, named so `[[Company]]` resolves.

    The glob does not recurse, which is what keeps `Companies/_docs/` out of
    the sweep: the contract artifacts filed under it are not notes, have no
    frontmatter, and would fail every validator they were handed to.
    """
    return sorted(COMPANIES.glob("*.md"))


def application_files() -> list[Path]:
    """Every `Applications/<Company> • <Role> • <YYYY-MM-DD>.md`.

    One flat folder, so the sweep is the glob itself — there is no company card
    sitting among these files to exclude, and nothing to recurse into.
    """
    return sorted(APPLICATIONS.glob("*.md"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")
