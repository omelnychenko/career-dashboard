#!/usr/bin/env python3
"""Career dashboard generator.

Single source of truth: YAML frontmatter in the Obsidian Career vault.
This script READS that frontmatter (plus stage notes and Match points), and
writes data.json — a timeless payload with no date-relative derivations.
The browser (index.html) derives all date-sensitive fields at render time.

Run:  python3 generate.py
Output: data.json  (next to this script)
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

# --- Paths -----------------------------------------------------------------

VAULT = Path(
    "/Users/omelnychenko/Library/Mobile Documents/iCloud~md~obsidian/Documents"
    "/Life/Growth/Areas/Career"
)
COMPANIES = VAULT / "Companies"
# data.json lands in the project root: it is neither published code (app/) nor
# source (src/), and it is gitignored.
HERE = Path(__file__).resolve().parent.parent
DATA_JSON = HERE / "data.json"

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

# Canonical application fields we care about. Drift firewall: anything not here
# is ignored; anything here but missing in a file becomes "".
APP_FIELDS = [
    "company", "role", "seniority", "stack", "source",
    "applied_date", "status",
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

def md_to_html(md: str) -> str:
    """Render the subset used in notes: headings, bold, bullet lists,
    checkboxes, paragraphs. Strips wiki-link brackets. Good enough for a
    read-only modal; not a CommonMark implementation."""
    lines = md.splitlines()
    out: list[str] = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in lines:
        raw = line.rstrip()
        if not raw.strip():
            close_list()
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", raw)
        if h:
            close_list()
            level = min(len(h.group(1)) + 2, 6)  # shift: # -> h3 inside modal
            out.append(f"<h{level}>{_inline(h.group(2))}</h{level}>")
            continue
        m = re.match(r"^\s*-\s+\[( |x|X)\]\s+(.*)$", raw)
        if m:
            if not in_list:
                out.append("<ul class='md'>")
                in_list = True
            box = "☑" if m.group(1).lower() == "x" else "☐"
            out.append(f"<li>{box} {_inline(m.group(2))}</li>")
            continue
        m = re.match(r"^\s*-\s+(.*)$", raw)
        if m:
            if not in_list:
                out.append("<ul class='md'>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        close_list()
        out.append(f"<p>{_inline(raw)}</p>")
    close_list()
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\[\[(.+?)\]\]", r"\1", s)  # wiki-links -> plain text
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


# --- Stage extraction ------------------------------------------------------

def extract_section(body: str, header: str) -> str:
    """Return the markdown under a heading, up to the next heading of the same
    or higher level (so nested `###` subsections are kept)."""
    head_pat = re.compile(
        rf"^(#{{1,6}})\s+{re.escape(header)}\s*$", re.MULTILINE
    )
    m = head_pat.search(body)
    if not m:
        return ""
    level = len(m.group(1))
    rest = body[m.end():]
    # stop at the next heading whose level is <= this section's level
    stop = re.compile(rf"^#{{1,{level}}}\s", re.MULTILINE)
    s = stop.search(rest)
    return (rest[: s.start()] if s else rest).strip()


def phase_of(stage_name: str) -> str:
    """Map a free-text stage name to a canonical pipeline phase.

    Order matters: most specific first. Tech = code/system/architecture/live
    coding; Final = final rounds; everything non-technical (intro / HR / any
    recruiter call / quiz / profiling) is Screening. Unknown stages default to
    Screening (earliest content phase) so they still count toward the funnel.
    """
    n = (stage_name or "").lower()
    if any(k in n for k in ("final", "onsite")):
        return "Final"
    if any(k in n for k in ("tech", "coding", "code", "system", "live")):
        return "Tech"
    return "Screening"


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


def load_stages(app_dir: Path) -> list[dict]:
    stages = []
    for f in sorted(app_dir.glob("*.md")):
        if f.name == "_application.md":
            continue
        fm, body = split_frontmatter(f.read_text(encoding="utf-8"))
        if fm.get("type") != "stage":
            continue
        feedback = extract_section(body, "Their feedback (if any)") \
            or extract_section(body, "Their feedback")
        name = fm.get("stage", "") or f.stem
        stages.append({
            "stage": name,
            "short": short_stage(name),
            "phase": phase_of(name),
            "date": str(fm.get("date", "")),
            "result": str(fm.get("result", "") or ""),
            "interviewer": fm.get("interviewer", ""),
            "feedback_html": md_to_html(feedback) if feedback else "",
            "body_html": md_to_html(body),
        })
    stages.sort(key=lambda s: s["date"])
    return stages


# --- Application loading ----------------------------------------------------

def derive_status(fm: dict, stages: list[dict]) -> str:
    """Status is authored, single source of truth = the `status:` field in
    _application.md. Stages do NOT influence status — the owner sets it by hand
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


def load_applications() -> tuple[list[dict], list[str]]:
    apps, skipped = [], []
    for app_md in sorted(COMPANIES.glob("*/*/_application.md")):
        fm, body = split_frontmatter(app_md.read_text(encoding="utf-8-sig"))
        if str(fm.get("type", "")).strip().lower() != "application":
            skipped.append(f"{app_md.parent.parent.name}/{app_md.parent.name}: type={fm.get('type')!r}")
            continue
        app_dir = app_md.parent
        stages = load_stages(app_dir)
        norm = {k: fm.get(k, "") for k in APP_FIELDS}
        salary_primary, salary_original = normalize_salary(
            norm.get("salary_amount"), norm.get("salary_period"), norm.get("salary_currency")
        )
        status = derive_status(fm, stages)
        applied_date = str(norm["applied_date"])
        apps.append({
            "company": norm["company"] or app_dir.parent.name,
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
            "body_html": md_to_html(body),
        })
    apps.sort(key=lambda a: a["applied_date"], reverse=True)
    return apps, skipped


# --- Main ------------------------------------------------------------------

def main() -> None:
    # A missing vault makes glob return nothing rather than raising, so without
    # these two guards a moved folder overwrites data.json with an empty payload
    # and the deploy ships it — the dashboard goes blank with exit code 0.
    if not COMPANIES.is_dir():
        raise SystemExit(f"Vault not found: {COMPANIES}")
    apps, skipped = load_applications()
    if not apps:
        raise SystemExit("Refusing to write an empty data.json — 0 applications found.")
    payload = {
        "schema": 1,
        "phases": PHASES,
        "ghost_days": GHOST_DAYS,
        "daily_target": DAILY_TARGET,
        "daily_window": DAILY_WINDOW,
        "apps": apps,
    }
    DATA_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {DATA_JSON} ({len(apps)} applications)")
    for s in skipped:
        print(f"  skipped: {s}")


if __name__ == "__main__":
    main()
