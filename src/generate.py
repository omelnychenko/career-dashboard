#!/usr/bin/env python3
"""Career dashboard generator.

Single source of truth: the Obsidian Career vault. This script READS each
application's frontmatter and body (its sections and per-stage write-ups), and
writes payload.json — a timeless payload with no date-relative derivations.
The browser (index.html) derives all date-sensitive fields at render time.

The schema itself — enums, frontmatter parsing, heading walking — comes from
vault_schema, shared with the validators. A second copy here would drift, and a
drifted enum accepts what the validators reject.

Run:  python3 generate.py
Output: payload.json  (in the project root)
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

from vault_schema import (
    APPLICATIONS, SALARY_CONVERTIBLE_CURRENCIES, STAGE_PHASES, STAGE_RESULTS,
    STATUS, Heading, application_files, children_of, is_table_divider,
    parse_headings, parse_stage_entry, read, split_application_stem,
    split_frontmatter, split_row,
)

# --- Paths -----------------------------------------------------------------

# payload.json lands in the project root: it is neither published code (app/)
# nor source (src/), and it is gitignored. Named after the KV key it is pushed
# to and the route it is served on, so the same payload keeps one name end to
# end.
HERE = Path(__file__).resolve().parent.parent
PAYLOAD_JSON = HERE / "payload.json"

# Daily applied-per-day goal — drawn as a dashed target line on the histogram.
DAILY_TARGET = 5

# Canonical pipeline, in order: the authored stage phases bracketed by the two
# states that come from the application status rather than from a stage.
# All non-technical HR steps (short screen + deeper HR call) collapse into
# Screening — a dedicated Interview phase is reintroduced only if a real
# evaluative non-technical round ever appears.
PHASES = ["Applied", *STAGE_PHASES, "Offer"]

# Canonical application fields we care about. Drift firewall: anything not here
# is ignored; anything here but missing in a file becomes "".
APP_FIELDS = [
    "company", "role", "seniority", "stack", "source",
    "applied_date", "status", "stages",
    "salary_amount", "salary_period", "salary_currency", "salary_note",
    "location", "closed_date", "fit_score", "fit_note",
]


USD_TO_EUR = 0.92
GBP_TO_EUR = 1.17
HOURS_PER_MONTH = 160

DAILY_WINDOW = 29  # days shown in the "applied per day" histogram


def normalize_salary(amount, period, currency) -> tuple:
    """Return (primary, original) salary strings.

    primary — EUR/month normalised, e.g. "€4.8K/mo".
    original — source value as written, e.g. "$35/h". Empty when same as primary.
    Both empty when amount is missing.
    """
    if not amount and amount != 0:
        return ("", "")
    try:
        amt = float(str(amount).strip())
    except (ValueError, TypeError):
        print(f"  warn: unparseable salary_amount {amount!r} — salary dropped")
        return ("", "")

    period = (period or "").strip().lower()
    currency = (currency or "").strip().upper()

    cur_prefix = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, f"{currency} " if currency else "")
    period_sfx = {"month": "/mo", "hour": "/h", "year": "/yr"}.get(period, "")
    if amt >= 1000:
        amt_str = f"{amt/1000:g}K"
    else:
        amt_str = f"{amt:g}"
    original = f"{cur_prefix}{amt_str}{period_sfx}"

    # Preserve unsupported currencies exactly as submitted. The UI displays
    # `salary_original` when there is no trustworthy EUR/month conversion.
    if currency and currency not in SALARY_CONVERTIBLE_CURRENCIES:
        return ("", original)

    eur_month = amt
    if currency == "USD":
        eur_month *= USD_TO_EUR
    elif currency == "GBP":
        eur_month *= GBP_TO_EUR
    if period == "hour":
        eur_month *= HOURS_PER_MONTH
    elif period == "year":
        eur_month /= 12

    if eur_month >= 1000:
        k = eur_month / 1000
        # Drop trailing .0: 5.0 -> "5", 4.8 -> "4.8"
        k_str = f"{k:.1f}".rstrip("0").rstrip(".")
        primary = f"€{k_str}K/mo"
    else:
        primary = f"€{eur_month:g}/mo"

    if original == primary:
        original = ""

    return (primary, original)


def normalize_fit(score) -> object:
    """The 1.0–5.0 fit score as a number, "" when unset.

    Kept numeric so the dashboard can compare and format it; an integral score
    stays an int so the modal reads "4" and not "4.0".
    """
    if score == "" or score is None:
        return ""
    try:
        val = float(str(score).strip())
    except (ValueError, TypeError):
        print(f"  warn: unparseable fit_score {score!r} — fit score dropped")
        return ""
    return int(val) if val == int(val) else val


# --- Markdown (very small subset) -> HTML ----------------------------------

def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def md_to_html(md: str) -> str:
    """Render the subset used in notes: headings, bold, bullet lists,
    checkboxes, tables, paragraphs. Strips wiki-link brackets. Good enough for
    a read-only modal; not a CommonMark implementation."""
    lines = md.splitlines()
    out: list[str] = []
    in_list = False
    i = 0

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        raw = lines[i].rstrip()
        if not raw.strip():
            close_list()
            i += 1
            continue
        # A table is a header row, a divider, then body rows. Without the
        # divider the pipes are literal text, so the whole block stays a
        # paragraph rather than being guessed into a table.
        if (
            _is_table_row(raw)
            and i + 1 < len(lines)
            and is_table_divider(lines[i + 1])
        ):
            close_list()
            header = split_row(raw)
            out.append("<table class='md'><thead><tr>")
            out.extend(f"<th>{_inline(c)}</th>" for c in header)
            out.append("</tr></thead><tbody>")
            i += 2
            while i < len(lines) and _is_table_row(lines[i]):
                cells = split_row(lines[i])
                # Pad or trim to the header width so a malformed row cannot
                # shift every later cell into the wrong column.
                cells = (cells + [""] * len(header))[: len(header)]
                out.append("<tr>")
                out.extend(f"<td>{_inline(c)}</td>" for c in cells)
                out.append("</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if h:
            close_list()
            level = min(len(h.group(1)) + 2, 6)  # shift: # -> h3 inside modal
            out.append(f"<h{level}>{_inline(h.group(2))}</h{level}>")
            i += 1
            continue
        m = re.match(r"^\s*-\s+\[( |x|X)\]\s+(.*)$", raw)
        if m:
            if not in_list:
                out.append("<ul class='md'>")
                in_list = True
            box = "☑" if m.group(1).lower() == "x" else "☐"
            out.append(f"<li>{box} {_inline(m.group(2))}</li>")
            i += 1
            continue
        m = re.match(r"^\s*-\s+(.*)$", raw)
        if m:
            if not in_list:
                out.append("<ul class='md'>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue
        close_list()
        out.append(f"<p>{_inline(raw)}</p>")
        i += 1
    close_list()
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\[\[(.+?)\]\]", r"\1", s)  # wiki-links -> plain text
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


# --- Body: sections and stages ---------------------------------------------

def short_stage(name: str) -> str:
    """Short label for the pipeline pill in the table."""
    n = (name or "").lower()
    if "intro" in n:
        return "Intro"
    if "hr" in n or "recruiter" in n:
        return "HR"
    if "quiz" in n or "profiling" in n:
        return "Quiz"
    if "system" in n:
        return "SysDesign"
    if "tech" in n or "coding" in n or "code" in n or "live" in n:
        return "Tech"
    if "final" in n or "onsite" in n:
        return "Final"
    if "interview" in n:
        return "Interview"
    name = name or ""
    return name if len(name) <= 14 else name[:13] + "…"


def section_markdown(headings: list[Heading], heading: Heading) -> str:
    """The markdown under `heading`, its nested headings included.

    A heading's own lines stop at the next heading of any level, so a stage
    section rebuilt from them alone would lose both of its H3s and everything
    they hold — the question table and the feedback.
    """
    parts = list(heading.lines)
    for child in children_of(headings, heading):
        parts.append("#" * child.level + " " + child.text)
        parts.extend(child.lines)
    return "\n".join(parts).strip()


def load_body(fm: dict, body: str) -> tuple[list[dict], list[dict], list[str]]:
    """Return (stages, sections, errors).

    Every H2 is either the opening `Decision log` — a `sections` entry, its own
    tab in the modal — or one interview, paired to its `stages:` entry by exact
    string. Anything else is reported: a heading one character off its entry
    would drop a whole write-up from the dashboard while the file still looks
    complete in Obsidian, and an entry with no section would render an empty tab.
    """
    raw = fm.get("stages") or []
    if isinstance(raw, str):
        raw = [raw] if raw else []
    entries = [str(e).strip() for e in raw]

    headings, _ = parse_headings(body)
    sections: list[dict] = []
    errors: list[str] = []
    claimed: dict[int, str] = {}
    for pos, h in enumerate([h for h in headings if h.level == 2]):
        if h.text == "Decision log":
            if pos != 0:
                errors.append(
                    "section '## Decision log' must be the first H2 in the "
                    "body, before any stage section"
                )
                continue
            sections.append({
                "label": h.text,
                "html": md_to_html(section_markdown(headings, h)),
            })
            continue
        # Claimed once: a repeated heading finds no free entry and is reported,
        # instead of overwriting the write-up the first one carried.
        idx = next(
            (i for i, e in enumerate(entries) if e == h.text and i not in claimed),
            None,
        )
        if idx is None:
            errors.append(
                f"section '## {h.text}' matches no `stages:` entry — a body "
                "holds `## Decision log` and one H2 per stage, nothing else"
            )
            continue
        claimed[idx] = section_markdown(headings, h)

    stages = []
    for i, entry in enumerate(entries):
        parsed = parse_stage_entry(entry)
        if parsed is None:
            errors.append(
                f"unparseable stage entry {entry!r} "
                f"(expected `YYYY-MM-DD | name | {'|'.join(STAGE_PHASES)} | "
                f"{'|'.join(STAGE_RESULTS)}[ | interviewer]`)"
            )
            continue
        if i not in claimed:
            errors.append(
                f"`stages:` entry {entry!r} has no section — expected an H2 "
                f"reading `## {entry}`"
            )
            continue
        stages.append({
            "stage": parsed["stage"],
            "short": short_stage(parsed["stage"]),
            "phase": parsed["phase"],
            "date": parsed["date"],
            "result": parsed["result"],
            "interviewer": parsed["interviewer"],
            "body_html": md_to_html(claimed[i]),
        })
    stages.sort(key=lambda s: s["date"])
    return stages, sections, errors


# --- Application loading ----------------------------------------------------

def derive_status(fm: dict) -> str:
    """Status is authored, single source of truth = the `status:` field in the
    application file. Stages do NOT influence status — the owner sets it by hand
    (applied -> active once contact happens, then a terminal when the process
    ends). Anything outside the `STATUS` enum -> applied (the starting point).

    Status and the stage `result` enum are the only two axes the dashboard
    filters on. Nothing is inferred from a date: an application is where its
    owner says it is.
    """
    raw = (fm.get("status") or "").lower()
    if raw in STATUS:
        return raw
    return "applied"


def first_stack(stack) -> str:
    if isinstance(stack, list):
        return stack[0] if stack else ""
    return str(stack or "")


def reached_phase_index(stages: list[dict]) -> int:
    """Highest canonical phase index reached via stages (0 = Applied only)."""
    best = 0  # Applied
    for s in stages:
        try:
            best = max(best, PHASES.index(s["phase"]))
        except ValueError:
            continue
    return best


def load_applications() -> tuple[list[dict], list[str]]:
    apps, skipped = [], []
    for app_md in application_files():
        fm, body = split_frontmatter(read(app_md))
        if str(fm.get("type", "")).strip().lower() != "application":
            skipped.append(f"{app_md.name}: type={fm.get('type')!r}")
            continue
        stages, sections, body_errors = load_body(fm, body)
        # One entry per unreadable file, not per problem, so the count in the
        # abort message is a count of files and every problem still names the
        # string it choked on.
        if body_errors:
            skipped.append(f"{app_md.name}: " + "; ".join(body_errors))
            continue
        norm = {k: fm.get(k, "") for k in APP_FIELDS}
        salary_primary, salary_original = normalize_salary(
            norm.get("salary_amount"), norm.get("salary_period"), norm.get("salary_currency")
        )
        status = derive_status(fm)
        applied_date = str(norm["applied_date"])
        # The filename was built out of the same company the frontmatter
        # carries, so it is where an empty `company:` is recovered from — and
        # only when the name splits back into its three fields, since a name
        # that does not is not one this vault wrote and guessing a company out
        # of whatever sits before its first bullet would invent one.
        from_name = split_application_stem(app_md.stem)
        apps.append({
            "company": norm["company"] or (from_name[0] if from_name else ""),
            "role": norm["role"],
            "stack_main": first_stack(norm["stack"]),
            "stack_all": norm["stack"] if isinstance(norm["stack"], list) else [norm["stack"]] if norm["stack"] else [],
            "seniority": norm["seniority"],
            "salary_primary": salary_primary,
            "salary_original": salary_original,
            "salary_note": str(norm.get("salary_note") or ""),
            "status": status,
            # "applied" = authored status is applied (no contact yet). Mirrors
            # the badge; status is the single source of truth.
            "applied": status == "applied",
            "reached": reached_phase_index(stages),
            "applied_date": applied_date,
            "source": norm["source"],
            "location": norm["location"],
            "closed_date": str(norm["closed_date"]),
            "fit_score": normalize_fit(norm["fit_score"]),
            "fit_note": str(norm.get("fit_note") or ""),
            "stages": stages,
            "sections": sections,
        })
    apps.sort(key=lambda a: a["applied_date"], reverse=True)
    return apps, skipped


# --- Main ------------------------------------------------------------------

def main() -> None:
    # A missing vault makes glob return nothing rather than raising, so without
    # this guard and the empty-payload one below, a moved folder overwrites the
    # payload with an empty one and the deploy ships it — the dashboard goes
    # blank with exit code 0.
    if not APPLICATIONS.is_dir():
        raise SystemExit(f"Vault not found: {APPLICATIONS}")
    apps, skipped = load_applications()
    # A card the vault holds but this run could not read is indistinguishable from
    # one that was never written: the payload is simply shorter, and every later
    # step reports success. A typo in one `type:` would quietly drop it from the
    # dashboard, so stop and name the files instead. Checked before the count
    # below, which would otherwise swallow the reasons on a run where every
    # single file failed.
    if skipped:
        raise SystemExit(
            f"Refusing to write a partial payload.json — {len(skipped)} of "
            f"{len(apps) + len(skipped)} applications could not be read:\n  "
            + "\n  ".join(skipped)
        )
    if not apps:
        raise SystemExit("Refusing to write an empty payload.json — 0 applications found.")
    payload = {
        "phases": PHASES,
        "daily_target": DAILY_TARGET,
        "daily_window": DAILY_WINDOW,
        "apps": apps,
    }
    # Written via a temp file: a truncated payload from an interrupted write
    # still looks complete to deploy-data.sh, which would push the fragment to KV.
    tmp = PAYLOAD_JSON.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, PAYLOAD_JSON)
    print(f"Wrote {PAYLOAD_JSON} ({len(apps)} applications)")


if __name__ == "__main__":
    main()
