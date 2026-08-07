#!/usr/bin/env python3
"""Application validator — `Companies/<Company>/<YYYY-MM-DD — Role>.md`.

The load-bearing rule is the one-to-one pairing between `stages:` entries and
stage H2s: the dashboard matches a write-up to its entry by exact string, so a
single character of drift loses the section. That pairing is checked in both
directions and reported as two different failures, because an entry with no
section and a section with no entry are two different edits.

Frontmatter and heading primitives come from `validate_company` — see the note
at the top of that module for why they live there.

Stdlib only.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from vault_schema import (
    APPLICATION_KEYS,
    DATE_RE,
    FIT_MAX,
    FIT_MIN,
    Heading,
    SALARY_CURRENCIES,
    SALARY_PERIODS,
    SCORE_MAX,
    SCORE_MIN,
    SENIORITY,
    STAGE_PHASES,
    STAGE_RESULTS,
    STATUS,
    TERMINAL_STATUS,
    body_offset,
    children_of,
    fm_entries,
    has_frontmatter,
    is_bullet,
    parse_headings,
    parse_stage_entry,
    parse_table,
    read,
    split_row,
    split_frontmatter,
)
from validate_common import (
    check_bullet_list,
    check_enum,
    check_frontmatter_keys,
    check_h1_content,
    check_heading_depth,
    check_no_html_comments,
    check_preamble,
    check_single_h1,
    check_wiki_link,
    first_lines,
    fmt,
    missing_frontmatter,
    raw_values,
)

DECISION_LOG = "Decision log"
STAGE_H3S = ("What was asked", "Their feedback")

NUMBER_RE = re.compile(r"\d+(\.\d+)?")
INT_RE = re.compile(r"\d+")
BOLD_LABEL_RE = re.compile(r"\*\*.+\*\*")
MD_LINK_RE = re.compile(r"\[.*\]\(.*\)")
URL_RE = re.compile(r"https?://")


# --- Frontmatter -----------------------------------------------------------


def check_date(key: str, value, line, *, required: bool) -> list[str]:
    where = f"line {line}: " if line else "frontmatter: "
    if isinstance(value, list):
        return [f"{where}{key}: is a list; expected an ISO date YYYY-MM-DD"]
    if value == "":
        if required:
            return [f"{where}{key}: is empty — required, ISO date YYYY-MM-DD"]
        return []
    if not DATE_RE.match(value):
        return [f"{where}{key}: '{value}' is not an ISO date YYYY-MM-DD"]
    return []


def check_number(key: str, value, line, *, low=None, high=None, max_decimals=None):
    """A bare number, optionally bounded and capped in decimal places. Empty is
    allowed — these fields are all optional; the caller enforces presence."""
    where = f"line {line}: " if line else "frontmatter: "
    if value == "":
        return []
    if isinstance(value, list):
        return [f"{where}{key}: is a list; expected a bare number"]
    if not NUMBER_RE.fullmatch(value):
        return [
            f"{where}{key}: '{value}' is not a bare number — digits and at "
            f"most one decimal point, no currency symbol, no separators"
        ]
    if max_decimals is not None and "." in value:
        places = len(value.split(".", 1)[1])
        if places > max_decimals:
            return [
                f"{where}{key}: '{value}' has {places} decimal places; at most "
                f"{max_decimals} is allowed"
            ]
    if low is not None and not (low <= float(value) <= high):
        return [f"{where}{key}: {value} is outside {low}–{high}"]
    return []


def check_inline_list(key: str, value, raw: str, line) -> list[str]:
    """`stack` and `stages` are lists. A bare `key:` parses as an empty string,
    which is a different thing from an empty list and reads as an unfilled
    field — `[]` is how "none" is written."""
    where = f"line {line}: " if line else "frontmatter: "
    if isinstance(value, list):
        return []
    return [
        f"{where}{key}: is not a list (found {raw!r}) — write `{key}: []` when "
        f"there are none"
    ]


def check_source(raw: str, line) -> list[str]:
    """A URL must stand alone; anything that is not a URL is free text.

    Obsidian renders a bare URL in frontmatter as a clickable link and stops
    doing so the moment a label shares the line — that is the whole reason for
    the rule. Where the posting had no link at all, the channel it came through
    ("LinkedIn", "SKELAR careers", "Proxify JD (PDF)") is the only provenance
    there is, and it has nothing to break.
    """
    where = f"line {line}: " if line else "frontmatter: "
    if raw == "":
        return []
    if MD_LINK_RE.search(raw):
        return [
            f"{where}source: {raw} — write the URL bare; markdown link syntax "
            f"does not render as a link in frontmatter"
        ]
    if URL_RE.search(raw) and re.search(r"\s", raw.strip()):
        return [
            f"{where}source: {raw} — a URL must stand alone on the line, with "
            f"no label text around it, or Obsidian stops linking it"
        ]
    return []


def check_closed_date(status, closed, line_closed, line_status) -> list[str]:
    """`closed_date` is set exactly when `status` is terminal. A terminal
    status without it loses the funnel's timing; a date on a live application
    says it is closed when it is not."""
    terminal = status in TERMINAL_STATUS
    if terminal and closed == "":
        return [
            f"line {line_closed or line_status}: closed_date: is empty but "
            f"status is '{status}' — a terminal status ({fmt(TERMINAL_STATUS)}) "
            f"requires closed_date"
        ]
    if not terminal and closed != "":
        return [
            f"line {line_closed}: closed_date: '{closed}' is set but status is "
            f"'{status}' — closed_date belongs only to a terminal status "
            f"({fmt(TERMINAL_STATUS)})"
        ]
    return []


# --- Stage entries ---------------------------------------------------------


def diagnose_stage_entry(entry: str) -> str:
    """Why `parse_stage_entry()` rejected this entry.

    The parser answers yes/no — it is the single authority on what is valid —
    but a bare "does not parse" would send the author hunting. This only
    explains a decision already made.
    """
    parts = [p.strip() for p in str(entry).split("|")]
    if len(parts) < 4:
        return (
            f"has {len(parts)} field(s) — the format is "
            f"`date | name | phase | result[ | interviewer]`"
        )
    if len(parts) > 5:
        return (
            f"has {len(parts)} fields — the format is "
            f"`date | name | phase | result[ | interviewer]`, at most 5"
        )
    if not DATE_RE.match(parts[0]):
        return f"field 1 '{parts[0]}' is not an ISO date YYYY-MM-DD"
    if not parts[1]:
        return "field 2 (stage name) is empty"
    if parts[2] not in STAGE_PHASES:
        return f"phase '{parts[2]}' is not one of: {fmt(STAGE_PHASES)}"
    if parts[3] not in STAGE_RESULTS:
        return f"result '{parts[3]}' is not one of: {fmt(STAGE_RESULTS)}"
    return "does not parse as `date | name | phase | result[ | interviewer]`"


def check_stage_entries(entries: list, stages_line, block: bool) -> list[str]:
    """Each entry parses, and entries run oldest first."""
    out: list[str] = []

    def line_of(i):
        # A block list puts item i on its own line under `stages:`; an inline
        # list puts every item on the `stages:` line itself.
        return (stages_line + 1 + i) if (block and stages_line) else stages_line

    dates: list[tuple[int, str]] = []
    for i, entry in enumerate(entries):
        where = f"line {line_of(i)}: " if line_of(i) else "frontmatter: "
        if not isinstance(entry, str):
            out.append(f"{where}stages: entry #{i + 1} is not a string")
            continue
        parsed = parse_stage_entry(entry)
        if parsed is None:
            out.append(
                f"{where}stages: entry #{i + 1} '{entry}' — "
                f"{diagnose_stage_entry(entry)}"
            )
            continue
        dates.append((i, parsed["date"]))

    for (pi, prev), (ci, cur) in zip(dates, dates[1:]):
        if cur < prev:
            where = f"line {line_of(ci)}: " if line_of(ci) else "frontmatter: "
            out.append(
                f"{where}stages: entry #{ci + 1} is dated {cur} but entry "
                f"#{pi + 1} is dated {prev} — entries run oldest first"
            )
    return out


# --- `### What was asked` --------------------------------------------------


def check_questions(h: Heading, off: int, *, allow_empty: bool) -> list[str]:
    """Either a 2-column `| Question | Score |` table or an unordered list.
    Never both: the table feeds `_Skills.md` row by row, and a half-list beside
    it means half the round never reaches the matrix.
    """
    out: list[str] = []
    ctx = f"### {h.text}"
    rows = [
        (h.line_no + i, line)
        for i, line in enumerate(h.lines, start=1)
        if line.strip()
    ]
    if not rows:
        if not allow_empty:
            out.append(
                f"line {h.line_no + off}: `{ctx}` is empty — expected a "
                f"`| Question | Score |` table or an unordered list"
            )
        return out

    bullets = [(n, ln) for n, ln in rows if is_bullet(ln)]
    table_lines = [(n, ln) for n, ln in rows if ln.strip().startswith("|")]
    labels = [(n, ln) for n, ln in rows if BOLD_LABEL_RE.fullmatch(ln.strip())]
    known = {n for n, _ in bullets} | {n for n, _ in table_lines}
    if table_lines:
        # Bold labels separate multiple tables in one round; with a bullet list
        # there is nothing to separate, so they are stray prose there.
        known |= {n for n, _ in labels}

    for n, ln in rows:
        if n not in known:
            out.append(
                f"line {n + off}: `{ctx}`: expected a `| Question | Score |` "
                f"table row or an unordered-list line, found: {ln.strip()!r}"
            )

    if bullets and table_lines:
        out.append(
            f"line {h.line_no + off}: `{ctx}` mixes a table and an unordered "
            f"list — it is one or the other, never both"
        )

    out += check_question_tables(table_lines, off, ctx)
    return out


def check_question_tables(table_lines, off: int, ctx: str) -> list[str]:
    """Every table under the heading is the 2-column `| Question | Score |`
    shape with integer scores."""
    out: list[str] = []
    blocks: list[list[tuple[int, str]]] = []
    block: list[tuple[int, str]] = []
    prev_n = None
    for n, line in table_lines:
        if prev_n is not None and n != prev_n + 1:
            blocks.append(block)
            block = []
        block.append((n, line))
        prev_n = n
    if block:
        blocks.append(block)

    for blk in blocks:
        parsed = parse_table([ln for _, ln in blk])
        if parsed is None:
            out.append(
                f"line {blk[0][0] + off}: `{ctx}`: this block is not a table — "
                f"a header row, then a `| --- | --- |` divider, then the rows"
            )
            continue
        header, _ = parsed
        if len(header) != 2:
            out.append(
                f"line {blk[0][0] + off}: `{ctx}`: {len(header)}-column table "
                f"{header} — the schema is the 2-column `| Question | Score |`"
            )
            continue
        if header != ["Question", "Score"]:
            out.append(
                f"line {blk[0][0] + off}: `{ctx}`: table header is {header} — "
                f"expected `| Question | Score |`"
            )
            continue
        for n, line in blk[2:]:
            cells = split_row(line)
            if len(cells) != 2:
                out.append(
                    f"line {n + off}: `{ctx}`: row has {len(cells)} cells "
                    f"{cells} — the table is 2-column `| Question | Score |`"
                )
                continue
            question, score = cells
            if not question:
                out.append(
                    f"line {n + off}: `{ctx}`: Question cell is empty — every "
                    f"row is one asked question"
                )
            if not INT_RE.fullmatch(score):
                out.append(
                    f"line {n + off}: `{ctx}`: Score '{score}' is not an "
                    f"integer {SCORE_MIN}–{SCORE_MAX} (the `_Skills.md` scale)"
                )
            elif not SCORE_MIN <= int(score) <= SCORE_MAX:
                out.append(
                    f"line {n + off}: `{ctx}`: Score {score} is outside "
                    f"{SCORE_MIN}–{SCORE_MAX} (the `_Skills.md` scale)"
                )
    return out


# --- Body ------------------------------------------------------------------


def check_stage_sections(headings, stage_h2s, entries, off: int) -> list[str]:
    """Pair `stages:` entries with their H2 sections by exact string, in order.

    Reported as three separate failures: an entry with no section (write the
    section), a section with no entry (fix the heading or add the entry), and a
    right set in the wrong order (move a section).
    """
    out: list[str] = []
    texts = [h.text for h in stage_h2s]
    wanted = Counter(e for e in entries if isinstance(e, str))

    seen: Counter = Counter()
    for h in stage_h2s:
        seen[h.text] += 1
        if seen[h.text] > wanted[h.text]:
            out.append(
                f"line {h.line_no + off}: H2 '{h.text}' matches no stages: "
                f"entry — a stage section's heading must repeat its entry "
                f"verbatim, and any other H2 belongs in `## {DECISION_LOG}`"
            )

    unmatched = wanted - Counter(texts)
    for entry in entries:
        if isinstance(entry, str) and unmatched[entry]:
            unmatched[entry] -= 1
            out.append(
                f"stages: entry '{entry}' has no section — every entry needs "
                f"its write-up under an H2 repeating the entry verbatim: "
                f"`## {entry}`"
            )

    if Counter(texts) == wanted:
        ordered = [e for e in entries if isinstance(e, str)]
        for i, (got, want) in enumerate(zip(texts, ordered)):
            if got != want:
                out.append(
                    f"line {stage_h2s[i].line_no + off}: stage section #{i + 1} "
                    f"is '{got}' but stages: entry #{i + 1} is '{want}' — "
                    f"sections follow the stages: order"
                )
                break
    return out


def check_stage_body(h2: Heading, headings, off: int) -> list[str]:
    """Exactly `### What was asked` then `### Their feedback`, in that order."""
    out: list[str] = []
    kids = children_of(headings, h2)
    h3s = [k for k in kids if k.level == 3]
    texts = [k.text for k in h3s]
    if texts != list(STAGE_H3S):
        out.append(
            f"line {h2.line_no + off}: stage section '{h2.text}' has H3s "
            f"{texts if texts else 'none'} — expected exactly "
            f"{fmt(repr(t) for t in STAGE_H3S)}, in that order"
        )

    for i, line in enumerate(h2.lines, start=1):
        if line.strip():
            out.append(
                f"line {h2.line_no + i + off}: content sits directly under the "
                f"stage heading ({line.strip()!r}) — everything belongs under "
                f"`### {STAGE_H3S[0]}` or `### {STAGE_H3S[1]}`; the "
                f"interviewer lives in the heading and nowhere else"
            )
            break

    # A scheduled interview has not happened yet, so it has nothing to record.
    parsed = parse_stage_entry(h2.text)
    pending = parsed is not None and parsed["result"] == "scheduled"

    for k in h3s:
        if k.text == STAGE_H3S[0]:
            out += check_questions(k, off, allow_empty=pending)
        elif k.text == STAGE_H3S[1]:
            out += check_bullet_list(
                k, off, f"### {k.text}", allow_empty=pending
            )
    return out


# --- Entry point -----------------------------------------------------------


def validate(path: Path) -> list[str]:
    """Violations in one application file, empty list when it is clean."""
    path = Path(path)
    text = read(path)
    fm, body = split_frontmatter(text)
    off = body_offset(text, body)
    out: list[str] = []

    has_fm = has_frontmatter(text)
    if not has_fm:
        # Without a frontmatter block every field check would fire at once and
        # bury the one fix that matters.
        out.append(missing_frontmatter(text))
        entries: list[tuple[str, int, str]] = []
    else:
        entries = fm_entries(text)
        out += check_frontmatter_keys(entries, APPLICATION_KEYS)

    line = first_lines(entries)
    raw = raw_values(entries)
    status = fm.get("status", "")
    stage_entries: list = []

    if has_fm:
        out += check_enum("type", fm.get("type", ""), ("application",),
                          line.get("type"), allow_empty=False)
        out += check_enum("seniority", fm.get("seniority", ""), SENIORITY,
                          line.get("seniority"), allow_empty=False)
        out += check_enum("status", status, STATUS, line.get("status"),
                          allow_empty=False)
        out += check_enum("salary_period", fm.get("salary_period", ""),
                          SALARY_PERIODS, line.get("salary_period"),
                          allow_empty=True)
        out += check_enum("salary_currency", fm.get("salary_currency", ""),
                          SALARY_CURRENCIES, line.get("salary_currency"),
                          allow_empty=True)

        if "company" in raw:
            out += check_wiki_link("company", raw["company"],
                                   line.get("company"))
        if "source" in raw:
            out += check_source(raw["source"], line.get("source"))

        out += check_date("applied_date", fm.get("applied_date", ""),
                          line.get("applied_date"), required=True)
        out += check_date("closed_date", fm.get("closed_date", ""),
                          line.get("closed_date"), required=False)
        if status in STATUS and "closed_date" in raw:
            out += check_closed_date(status, fm.get("closed_date", ""),
                                     line.get("closed_date"),
                                     line.get("status"))

        out += check_number("salary_amount", fm.get("salary_amount", ""),
                            line.get("salary_amount"))
        out += check_number("fit_score", fm.get("fit_score", ""),
                            line.get("fit_score"), low=FIT_MIN, high=FIT_MAX,
                            max_decimals=1)

        if "stack" in raw:
            out += check_inline_list("stack", fm.get("stack"), raw["stack"],
                                     line.get("stack"))
        if "stages" in raw:
            problems = check_inline_list("stages", fm.get("stages"),
                                         raw["stages"], line.get("stages"))
            out += problems
            if not problems:
                stage_entries = fm.get("stages") or []
                out += check_stage_entries(
                    stage_entries, line.get("stages"),
                    block=raw["stages"] == "",
                )

    out += check_no_html_comments(body, off)

    company = fm.get("company", "") or path.parent.name
    expected_h1 = f"{company} — {fm.get('role', '')}"

    headings, preamble = parse_headings(body)
    out += check_preamble(preamble, off, f"# {expected_h1}")
    out += check_heading_depth(headings, 3, off)
    out += check_single_h1(headings, expected_h1, off)
    out += check_h1_content(headings, off, f"## {DECISION_LOG}")

    h2s = [h for h in headings if h.level == 2]
    logs = [h for h in h2s if h.text == DECISION_LOG]
    if not logs:
        out.append(
            f"no `## {DECISION_LOG}` section — it is required and is always "
            f"the first H2"
        )
    else:
        if h2s[0] is not logs[0]:
            out.append(
                f"line {h2s[0].line_no + off}: first H2 is '{h2s[0].text}' — "
                f"`## {DECISION_LOG}` is always the first H2"
            )
        for extra in logs[1:]:
            out.append(
                f"line {extra.line_no + off}: a second `## {DECISION_LOG}` — "
                f"there is exactly one, holding every dated event"
            )
        out += check_bullet_list(logs[0], off, f"## {DECISION_LOG}")

    stage_h2s = [h for h in h2s if h.text != DECISION_LOG]
    out += check_stage_sections(headings, stage_h2s, stage_entries, off)
    for h2 in stage_h2s:
        out += check_stage_body(h2, headings, off)

    # An H3 outside a stage section has no place to be rendered.
    inside = {id(k) for h2 in stage_h2s for k in children_of(headings, h2)}
    parent: dict[int, Heading | None] = {}
    current: Heading | None = None
    for h in headings:
        if h.level == 2:
            current = h
        elif h.level >= 3:
            parent[id(h)] = current
    for h in headings:
        if h.level == 3 and id(h) not in inside:
            owner = parent.get(id(h))
            where = f"`## {owner.text}`" if owner is not None else "the H1"
            out.append(
                f"line {h.line_no + off}: H3 '{h.text}' sits under {where} — "
                f"H3 headings appear only inside a stage's `## <entry>` section"
            )

    return out
