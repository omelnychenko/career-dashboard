#!/usr/bin/env python3
"""Career dashboard generator.

Single source of truth: YAML frontmatter in the Obsidian Career vault.
This script READS that frontmatter (plus each file's stage sections), and
writes payload.json — a timeless payload with no date-relative derivations.
The browser (index.html) derives all date-sensitive fields at render time.

Run:  python3 generate.py
Output: payload.json  (in the project root)
"""

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

# --- Paths -----------------------------------------------------------------

VAULT = Path(
    "/Users/omelnychenko/Library/Mobile Documents/iCloud~md~obsidian/Documents"
    "/Life/Career"
)
# Applications live under their company: Companies/Company/YYYY-MM-DD — Role/
COMPANIES = VAULT / "Companies"
# payload.json lands in the project root: it is neither published code (app/)
# nor source (src/), and it is gitignored. Named after the KV key it is pushed
# to and the route it is served on, so the same payload keeps one name end to
# end.
HERE = Path(__file__).resolve().parent.parent
PAYLOAD_JSON = HERE / "payload.json"

# Ghosted: active, no scheduled/future stage, last activity older than this.
GHOST_DAYS = 14

# Daily applied-per-day goal — drawn as a dashed target line on the histogram.
DAILY_TARGET = 5

# Canonical pipeline phases, in order. Stage `stage:` free-text is mapped here.
# Offer/Rejected are terminal and come from the application status, not a stage.
# All non-technical HR steps (short screen + deeper HR call) collapse into
# Screening — a dedicated Interview phase is reintroduced only if a real
# evaluative non-technical round ever appears.
PHASES = ["Applied", "Screening", "Tech", "Final", "Offer"]

# Values a stage may declare. Applied and Offer are terminal and come from the
# application `status`, so a stage never carries them.
STAGE_PHASES = ("Screening", "Tech", "Final")
STAGE_RESULTS = ("scheduled", "passed", "failed")

# Canonical application fields we care about. Drift firewall: anything not here
# is ignored; anything here but missing in a file becomes "".
APP_FIELDS = [
    "company", "role", "seniority", "stack", "source",
    "applied_date", "status", "stages",
    "salary_amount", "salary_period", "salary_currency", "salary_note",
    "location", "closed_date",
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

    # Without a rate the amount would be labelled € unconverted, turning e.g.
    # 5000 PLN into "€5K/mo" with the real currency nowhere in the payload.
    if currency and currency not in ("EUR", "USD", "GBP"):
        raise SystemExit(f"No conversion rate for {currency} — add one to generate.py.")

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

    cur_sym = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, "€")
    period_sfx = {"month": "/mo", "hour": "/h", "year": "/yr"}.get(period, "")
    if amt >= 1000:
        amt_str = f"{amt/1000:g}K"
    else:
        amt_str = f"{amt:g}"
    original = f"{cur_sym}{amt_str}{period_sfx}"

    if original == primary:
        original = ""

    return (primary, original)

# --- Minimal frontmatter parser (no external deps) -------------------------

def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Handles the small YAML subset we use:
    scalars, `[a, b]` inline lists, and quoted strings. Not a full YAML parser.
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
                block.append(_unquote(lines[j].lstrip()[2:].strip()))
                j += 1
            if block:
                fm[key] = block
                i = j
                continue
        fm[key] = _parse_value(val)
        i += 1
    return fm, body


def _parse_value(val: str):
    if val == "":
        return ""
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_unquote(x.strip()) for x in inner.split(",") if x.strip()]
    return _unquote(val)


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    # strip Obsidian wiki-link brackets for display: [[Name]] -> Name
    m = re.fullmatch(r"\[\[(.+?)\]\]", s.strip())
    if m:
        return m.group(1)
    return s


# --- Markdown (very small subset) -> HTML ----------------------------------

def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_table_divider(line: str) -> bool:
    """`|---|:--:|` — the row that separates a table header from its body."""
    s = line.strip()
    if not s.startswith("|"):
        return False
    return bool(re.fullmatch(r"\|(\s*:?-{1,}:?\s*\|)+", s))


def _split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


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
            and _is_table_divider(lines[i + 1])
        ):
            close_list()
            header = _split_row(raw)
            out.append("<table class='md'><thead><tr>")
            out.extend(f"<th>{_inline(c)}</th>" for c in header)
            out.append("</tr></thead><tbody>")
            i += 2
            while i < len(lines) and _is_table_row(lines[i]):
                cells = _split_row(lines[i])
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


# --- Stage extraction ------------------------------------------------------

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


def body_before_stages(body: str) -> str:
    """The application body up to `## Stages`.

    Stage sections are emitted as their own per-stage `body_html`, so leaving
    them in the application body would render every question table twice in the
    detail modal — once under Application, once under its stage tab.
    """
    for i, line in enumerate(body.splitlines()):
        m = re.match(r"^##\s+(.*)$", line)
        if m and m.group(1).strip().lower() == "stages":
            return "\n".join(body.splitlines()[:i]).rstrip()
    return body


def split_stage_sections(body: str) -> dict:
    """Map `### <heading>` under `## Stages` to that section's markdown.

    Keyed by the heading text, so a stage's prose is matched to its frontmatter
    entry by `<date> — <name>`. Headings deeper than `###` stay inside their
    section rather than starting a new one.
    """
    sections: dict = {}
    current = None
    buf: list[str] = []
    in_stages = False
    for line in body.splitlines():
        h2 = re.match(r"^##\s+(.*)$", line)
        h3 = re.match(r"^###\s+(.*)$", line)
        if h3 and in_stages:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = h3.group(1).strip()
            buf = []
            continue
        if h2 and not line.startswith("###"):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
                current = None
                buf = []
            in_stages = h2.group(1).strip().lower() == "stages"
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def parse_stage_entry(entry: str) -> dict | None:
    """`date | name | phase | result[ | interviewer]` -> dict, or None.

    Phase and result are authored enums rather than keyword-guessed from free
    text, so a value outside the enum is a typo and must be reported, never
    silently bucketed into a default phase.
    """
    parts = [p.strip() for p in str(entry).split("|")]
    if len(parts) < 4:
        return None
    date, name, phase, result = parts[0], parts[1], parts[2], parts[3].lower()
    interviewer = parts[4] if len(parts) > 4 else ""
    if phase not in STAGE_PHASES or result not in STAGE_RESULTS:
        return None
    return {
        "stage": name,
        "short": short_stage(name),
        "phase": phase,
        "date": date,
        "result": result,
        "interviewer": _unquote(interviewer),
    }


def load_stages(fm: dict, body: str) -> tuple[list[dict], list[str]]:
    """Return (stages, errors). Stage order comes from the authored dates."""
    raw = fm.get("stages") or []
    if isinstance(raw, str):
        raw = [raw] if raw else []
    sections = split_stage_sections(body)
    stages, errors = [], []
    for entry in raw:
        parsed = parse_stage_entry(entry)
        if parsed is None:
            errors.append(
                f"unparseable stage entry {entry!r} "
                f"(expected `date | name | {'|'.join(STAGE_PHASES)} | "
                f"{'|'.join(STAGE_RESULTS)}[ | interviewer]`)"
            )
            continue
        heading = f"{parsed['date']} — {parsed['stage']}"
        parsed["body_html"] = md_to_html(sections.pop(heading, ""))
        stages.append(parsed)
    # A section left over matched no entry, so its write-up would silently
    # vanish from the dashboard while the file still looks complete in Obsidian.
    for heading in sections:
        errors.append(
            f"stage section '### {heading}' matches no `stages:` entry "
            f"(heading must read `<date> — <name>`)"
        )
    stages.sort(key=lambda s: s["date"])
    return stages, errors


# --- Application loading ----------------------------------------------------

def derive_status(fm: dict) -> str:
    """Status is authored, single source of truth = the `status:` field in the
    application file. Stages do NOT influence status — the owner sets it by hand
    (applied -> active once contact happens, then a terminal when the process
    ends). Canonical values: applied | active | rejected | offer | withdrawn.
    Empty/unknown -> applied (the default starting point).

    upcoming/ghosted/needs_update remain derived sub-flags (computed from stage
    dates elsewhere) — they are display overlays, not statuses.
    """
    raw = (fm.get("status") or "").lower()
    if raw in ("applied", "active", "rejected", "offer", "withdrawn"):
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


def application_files() -> list[Path]:
    """Every `Companies/<Company>/<date — Role>.md`.

    The company card is `Companies/<Company>/<Company>.md` — named after its
    folder so `[[Company]]` resolves — so it is excluded by that rule rather
    than by its `type:`. Letting it fall through to the `type` check would put
    a legitimate file in `skipped`, which aborts the whole run.
    """
    return sorted(
        f
        for f in COMPANIES.glob("*/*.md")
        if f.stem != f.parent.name
    )


def load_applications() -> tuple[list[dict], list[str]]:
    apps, skipped = [], []
    for app_md in application_files():
        fm, body = split_frontmatter(app_md.read_text(encoding="utf-8-sig"))
        if str(fm.get("type", "")).strip().lower() != "application":
            skipped.append(
                f"{app_md.parent.name}/{app_md.name}: type={fm.get('type')!r}"
            )
            continue
        stages, stage_errors = load_stages(fm, body)
        if stage_errors:
            skipped.extend(
                f"{app_md.parent.name}/{app_md.name}: {e}" for e in stage_errors
            )
            continue
        norm = {k: fm.get(k, "") for k in APP_FIELDS}
        salary_primary, salary_original = normalize_salary(
            norm.get("salary_amount"), norm.get("salary_period"), norm.get("salary_currency")
        )
        status = derive_status(fm)
        applied_date = str(norm["applied_date"])
        apps.append({
            # The company folder is authoritative when frontmatter omits it.
            "company": norm["company"] or app_md.parent.name,
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
            "stages": stages,
            "body_html": md_to_html(body_before_stages(body)),
        })
    apps.sort(key=lambda a: a["applied_date"], reverse=True)
    return apps, skipped


# --- Main ------------------------------------------------------------------

def main() -> None:
    # A missing vault makes glob return nothing rather than raising, so without
    # these two guards a moved folder overwrites the payload with an empty one
    # and the deploy ships it — the dashboard goes blank with exit code 0.
    if not COMPANIES.is_dir():
        raise SystemExit(f"Vault not found: {COMPANIES}")
    apps, skipped = load_applications()
    if not apps:
        raise SystemExit("Refusing to write an empty payload.json — 0 applications found.")
    # A card the vault holds but this run could not read is indistinguishable from
    # one that was never written: the payload is simply shorter, and every later
    # step reports success. A typo in one `type:` would quietly drop it from the
    # dashboard, so stop and name the files instead.
    if skipped:
        raise SystemExit(
            f"Refusing to write a partial payload.json — {len(skipped)} of "
            f"{len(apps) + len(skipped)} applications could not be read:\n  "
            + "\n  ".join(skipped)
        )
    payload = {
        "phases": PHASES,
        "ghost_days": GHOST_DAYS,
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
