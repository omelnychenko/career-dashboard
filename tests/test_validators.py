#!/usr/bin/env python3
"""Fixture runner for the Career vault validators.

Every broken fixture is the valid base plus one mutation, so "exactly one
defect" holds by construction rather than by inspection. Each case declares the
violation it expects; a case that fails for a different reason is a bug in the
validator, not a pass.

Each fixture lives in its own directory so the file stem stays constant — the
H1-equals-stem rule would otherwise turn every filename into a second defect.

    python3 tests/test_validators.py

Exit 0 when every case behaves; 1 names the ones that did not. This is the only
thing standing behind the validators — without it, a rule can be loosened by
accident and the vault sweep still reports OK.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# Fixtures are written to a temp directory rather than into the repo: they are
# an artefact of the run, and a stale one left on disk from an earlier version
# of a case would be read as evidence.
HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
FIXTURES = Path(tempfile.mkdtemp(prefix="vault-fixtures-"))
sys.path.insert(0, str(SRC))

import validate_application  # noqa: E402
import validate_company  # noqa: E402
import validate_person  # noqa: E402

# --- Valid bases -----------------------------------------------------------

COMPANY = """---
type: company
name: Acme
website: https://acme.example.com
location: Barcelona
industry: Fintech
---

# Acme

## About
- **Hiring process:**
  - Intro call with the recruiter.
  - Technical interview, 90 minutes, live coding.
  - Final call with the hiring manager.
- Re-application allowed after six months.
"""

PERSON = """---
type: person
name: Jane Doe
role: Engineering Manager
current_company: "[[Acme]]"
linkedin: https://www.linkedin.com/in/jane-doe/
email:
phone:
telegram:
---

# Jane Doe

## About
- Ran both rounds; asked for concrete examples rather than definitions.
- Communication style: direct, cuts follow-ups short when the answer lands.
"""

APP_FM_H1 = """---
type: application
company: "[[Acme]]"
role: Frontend Engineer
seniority: Middle
stack: [Angular, TypeScript, RxJS]
source: https://acme.example.com/jobs/frontend-engineer
applied_date: 2026-05-11
status: rejected
stages:
  - 2026-05-14 | Intro call | Screening | passed | [[Jane Doe]]
  - 2026-05-20 | Technical interview | Tech | failed | [[Jane Doe]]
salary_amount: 4000
salary_period: month
salary_currency: EUR
salary_note: Published range 3500-4500
location: Barcelona
closed_date: 2026-05-22
fit_score: 7.5
fit_note: Strong Angular overlap, thin on Node
---

# Acme — Frontend Engineer

"""

APP_LOG = """## Decision log
- 2026-05-11 — Applied through their careers page.
- 2026-05-22 — Rejected after the technical round.

"""

APP_STAGE1 = """## 2026-05-14 | Intro call | Screening | passed | [[Jane Doe]]

### What was asked
- How did you hear about us?
- Notice period and earliest start date.

### Their feedback
- Moved to the technical round the same week.

"""

APP_STAGE2 = """## 2026-05-20 | Technical interview | Tech | failed | [[Jane Doe]]

### What was asked

**Angular core**

| Question | Score |
| --- | --- |
| Dependency Injection — providers, scopes, injector hierarchy | 2 |
| Change detection — OnPush and the zone | 3 |

**RxJS**

| Question | Score |
| --- | --- |
| switchMap vs mergeMap | 4 |

### Their feedback
- Weak on DI internals; they wanted the injector hierarchy in detail.
- Retro: rehearse the OnPush explanation with a concrete example.
"""

APPLICATION = APP_FM_H1 + APP_LOG + APP_STAGE1 + APP_STAGE2

BASES = {
    "company": ("Acme.md", COMPANY, validate_company.validate),
    "person": ("Jane Doe.md", PERSON, validate_person.validate),
    "application": (
        "2026-05-11 — Frontend Engineer.md",
        APPLICATION,
        validate_application.validate,
    ),
}

# --- Cases -----------------------------------------------------------------
# edits: (old, new) pairs applied once each to the base.
# build: replaces the base wholesale, for cases that move whole sections.
# count: total violations expected — an extra one means a rule misfired.

CASES = [
    # -- Company ------------------------------------------------------------
    dict(name="company_bad_enum", base="company",
         edits=[("type: company", "type: org")],
         expect="type: 'org' is not 'company'", count=1),
    dict(name="company_missing_key", base="company",
         edits=[("website: https://acme.example.com\n", "")],
         expect="missing key 'website'", count=1),
    dict(name="company_extra_key", base="company",
         edits=[("industry: Fintech\n", "industry: Fintech\nfounded: 2011\n")],
         expect="unexpected key 'founded'", count=1),
    dict(name="company_misordered_keys", base="company",
         edits=[("location: Barcelona\nindustry: Fintech",
                 "industry: Fintech\nlocation: Barcelona")],
         expect="position 4 is 'industry', expected 'location'", count=1),
    dict(name="company_two_h1", base="company",
         edits=[("\n## About", "\n# Acme again\n\n## About")],
         expect="a second H1 '# Acme again'", count=1),
    dict(name="company_h1_mismatch", base="company",
         edits=[("# Acme\n", "# ACME\n")],
         expect="H1 is 'ACME', expected 'Acme'", count=1),
    dict(name="company_extra_h2", base="company",
         edits=[("- Re-application allowed after six months.\n",
                 "- Re-application allowed after six months.\n\n"
                 "## Hiring process\n- Three rounds.\n")],
         expect="extra H2 'Hiring process'", count=1),
    dict(name="company_h4", base="company",
         edits=[("- Re-application allowed after six months.\n",
                 "- Re-application allowed after six months.\n\n"
                 "#### Notes\n- Something.\n")],
         expect="H4 'Notes' — this schema allows H1, H2 only", count=1),
    dict(name="company_prose_in_about", base="company",
         edits=[("- Re-application allowed after six months.\n",
                 "Acme is a fintech company.\n")],
         expect="expected an unordered-list line starting with '- ', found: "
                "'Acme is a fintech company.'", count=1),
    dict(name="company_html_comment", base="company",
         edits=[("- Re-application allowed after six months.\n",
                 "- Re-application allowed after six months.\n"
                 "<!-- ask them again in December -->\n")],
         expect="HTML comment `<!--` in the body", count=2,
         note="a comment inside a bullet-only section is also a non-bullet "
              "line; both messages name the same fix"),

    # -- Person -------------------------------------------------------------
    dict(name="person_bad_enum", base="person",
         edits=[("type: person", "type: contact")],
         expect="type: 'contact' is not 'person'", count=1),
    dict(name="person_bare_wiki_link", base="person",
         edits=[('current_company: "[[Acme]]"', "current_company: Acme")],
         expect="a set current_company is a quoted wiki-link", count=1),
    dict(name="person_misordered_keys", base="person",
         edits=[('role: Engineering Manager\ncurrent_company: "[[Acme]]"',
                 'current_company: "[[Acme]]"\nrole: Engineering Manager')],
         expect="position 3 is 'current_company', expected 'role'", count=1),

    # -- Application: frontmatter -------------------------------------------
    dict(name="app_bad_enum_seniority", base="application",
         edits=[("seniority: Middle", "seniority: Mid–Senior")],
         expect="seniority: 'Mid–Senior' is not one of: "
                "Junior, Middle, Senior, Lead", count=1),
    dict(name="app_bad_enum_status", base="application",
         edits=[("status: rejected", "status: ghosted")],
         expect="status: 'ghosted' is not one of: "
                "applied, active, rejected, offer, withdrawn", count=1),
    dict(name="app_bad_enum_currency", base="application",
         edits=[("salary_currency: EUR", "salary_currency: PLN")],
         expect="salary_currency: 'PLN' is not one of: EUR, USD, GBP",
         count=1),
    dict(name="app_missing_key", base="application",
         edits=[("fit_note: Strong Angular overlap, thin on Node\n", "")],
         expect="missing key 'fit_note'", count=1),
    dict(name="app_extra_key", base="application",
         edits=[("location: Barcelona\n", "location: Barcelona\n"
                                          "recruiter: Jane Doe\n")],
         expect="unexpected key 'recruiter'", count=1),
    dict(name="app_misordered_keys", base="application",
         edits=[("role: Frontend Engineer\nseniority: Middle",
                 "seniority: Middle\nrole: Frontend Engineer")],
         expect="position 3 is 'seniority', expected 'role'", count=1),
    dict(name="app_terminal_without_closed_date", base="application",
         edits=[("closed_date: 2026-05-22", "closed_date: ")],
         expect="closed_date: is empty but status is 'rejected'", count=1),
    dict(name="app_closed_date_on_live_status", base="application",
         edits=[("status: rejected", "status: active")],
         expect="closed_date: '2026-05-22' is set but status is 'active'",
         count=1),
    dict(name="app_applied_date_not_iso", base="application",
         edits=[("applied_date: 2026-05-11", "applied_date: 11-05-2026")],
         expect="applied_date: '11-05-2026' is not an ISO date YYYY-MM-DD",
         count=1),
    dict(name="app_fit_score_out_of_range", base="application",
         edits=[("fit_score: 7.5", "fit_score: 12")],
         expect="fit_score: 12 is outside 1–10", count=1),
    dict(name="app_fit_score_two_decimals", base="application",
         edits=[("fit_score: 7.5", "fit_score: 7.55")],
         expect="fit_score: '7.55' has 2 decimal places", count=1),
    dict(name="app_stack_not_a_list", base="application",
         edits=[("stack: [Angular, TypeScript, RxJS]", "stack: ")],
         expect="stack: is not a list", count=1),
    dict(name="app_source_with_label", base="application",
         edits=[("source: https://acme.example.com/jobs/frontend-engineer",
                 "source: https://acme.example.com/jobs/frontend-engineer "
                 "(LinkedIn)")],
         expect="a URL must stand alone on the line", count=1),
    # A source that is not a URL is the only provenance a posting without a
    # link has, and there is nothing for a label to break — free text passes.
    dict(name="app_source_channel_name", base="application",
         edits=[("source: https://acme.example.com/jobs/frontend-engineer",
                 "source: Proxify JD (PDF)")],
         expect=None, count=0),
    # The result enum is case-sensitive, like the phase enum beside it.
    # Entry and heading both, so the pairing stays intact and the only defect
    # left is the enum itself.
    dict(name="app_stage_result_wrong_case", base="application",
         edits=[("  - 2026-05-14 | Intro call | Screening | passed",
                 "  - 2026-05-14 | Intro call | Screening | Passed"),
                ("## 2026-05-14 | Intro call | Screening | passed",
                 "## 2026-05-14 | Intro call | Screening | Passed")],
         expect="result 'Passed' is not one of: scheduled, passed, failed",
         count=1),
    dict(name="app_company_bare_text", base="application",
         edits=[('company: "[[Acme]]"', "company: Acme")],
         expect="a set company is a quoted wiki-link", count=1),

    # -- Application: stages <-> sections ------------------------------------
    dict(name="app_h2_matches_no_entry", base="application",
         edits=[(APP_STAGE2, APP_STAGE2 + "\n"
                 "## 2026-06-01 | Final call | Final | passed | [[Jane Doe]]\n"
                 "\n### What was asked\n- Team fit questions.\n"
                 "\n### Their feedback\n- Positive.\n")],
         expect="H2 '2026-06-01 | Final call | Final | passed | [[Jane Doe]]' "
                "matches no stages: entry", count=1),
    dict(name="app_entry_without_h2", base="application",
         edits=[("  - 2026-05-20 | Technical interview | Tech | failed | "
                 "[[Jane Doe]]\n",
                 "  - 2026-05-20 | Technical interview | Tech | failed | "
                 "[[Jane Doe]]\n"
                 "  - 2026-06-01 | Final call | Final | passed | "
                 "[[Jane Doe]]\n")],
         expect="stages: entry '2026-06-01 | Final call | Final | passed | "
                "[[Jane Doe]]' has no section", count=1),
    dict(name="app_stage_entries_out_of_order", base="application",
         edits=[("  - 2026-05-14 | Intro call", "  - 2026-05-28 | Intro call"),
                ("## 2026-05-14 | Intro call", "## 2026-05-28 | Intro call")],
         expect="stages: entry #2 is dated 2026-05-20 but entry #1 is dated "
                "2026-05-28 — entries run oldest first", count=1),
    dict(name="app_sections_out_of_order", base="application",
         build=lambda: APP_FM_H1 + APP_LOG + APP_STAGE2 + "\n" + APP_STAGE1,
         expect="stage section #1 is '2026-05-20 | Technical interview | Tech "
                "| failed | [[Jane Doe]]' but stages: entry #1 is "
                "'2026-05-14 | Intro call | Screening | passed | "
                "[[Jane Doe]]'", count=1),
    dict(name="app_decision_log_not_first", base="application",
         build=lambda: APP_FM_H1 + APP_STAGE1 + APP_STAGE2 + "\n" + APP_LOG,
         expect="first H2 is '2026-05-14 | Intro call | Screening | passed | "
                "[[Jane Doe]]' — `## Decision log` is always the first H2",
         count=1),
    dict(name="app_bad_stage_result", base="application",
         edits=[("| Tech | failed | [[Jane Doe]]\n"
                 "salary_amount", "| Tech | rejected | [[Jane Doe]]\n"
                 "salary_amount"),
                ("## 2026-05-20 | Technical interview | Tech | failed",
                 "## 2026-05-20 | Technical interview | Tech | rejected")],
         expect="result 'rejected' is not one of: scheduled, passed, failed",
         count=1),

    # -- Application: body shapes -------------------------------------------
    dict(name="app_two_h1", base="application",
         edits=[("\n## Decision log", "\n# Acme — Other Role\n\n"
                                      "## Decision log")],
         expect="a second H1 '# Acme — Other Role'", count=1),
    dict(name="app_h1_wrong_dash", base="application",
         edits=[("# Acme — Frontend Engineer\n",
                 "# Acme - Frontend Engineer\n")],
         expect="H1 is 'Acme - Frontend Engineer', expected "
                "'Acme — Frontend Engineer'", count=1),
    dict(name="app_three_column_table", base="application",
         edits=[("| Question | Score |\n| --- | --- |\n"
                 "| switchMap vs mergeMap | 4 |",
                 "| Question | Topic | Score |\n| --- | --- | --- |\n"
                 "| switchMap vs mergeMap | RxJS | 4 |")],
         expect="3-column table ['Question', 'Topic', 'Score'] — the "
                "schema is the 2-column `| Question | Score |`", count=1),
    dict(name="app_score_six", base="application",
         edits=[("| switchMap vs mergeMap | 4 |",
                 "| switchMap vs mergeMap | 6 |")],
         expect="Score 6 is outside 1–5", count=1),
    dict(name="app_table_and_list_mixed", base="application",
         edits=[("| switchMap vs mergeMap | 4 |\n",
                 "| switchMap vs mergeMap | 4 |\n"
                 "- Also chatted about their release process.\n")],
         expect="mixes a table and an unordered list", count=1),
    dict(name="app_prose_instead_of_bullets", base="application",
         edits=[("- Moved to the technical round the same week.",
                 "Moved to the technical round the same week.")],
         expect="`### Their feedback`: expected an unordered-list line "
                "starting with '- ', found: 'Moved to the technical round "
                "the same week.'", count=1),
    dict(name="app_h4", base="application",
         edits=[("- Retro: rehearse the OnPush explanation with a concrete "
                 "example.\n",
                 "- Retro: rehearse the OnPush explanation with a concrete "
                 "example.\n\n#### Notes\n- Something.\n")],
         expect="H4 'Notes' — this schema allows H1, H2, H3 only",
         count=1),
    dict(name="app_h3_outside_stage", base="application",
         edits=[("- 2026-05-22 — Rejected after the technical round.\n",
                 "- 2026-05-22 — Rejected after the technical round.\n\n"
                 "### Notes\n- Something.\n")],
         expect="H3 'Notes' sits under `## Decision log`", count=1),
    dict(name="app_stage_missing_an_h3", base="application",
         edits=[("### Their feedback\n- Moved to the technical round the "
                 "same week.\n\n", "")],
         expect="stage section '2026-05-14 | Intro call | Screening | passed "
                "| [[Jane Doe]]' has H3s ['What was asked'] — expected "
                "exactly 'What was asked', 'Their feedback', in that order",
         count=1),
    dict(name="app_html_comment", base="application",
         edits=[("- Moved to the technical round the same week.\n",
                 "- Moved to the technical round the same week.\n"
                 "<!-- Result: passed -->\n")],
         expect="HTML comment `<!--` in the body", count=2,
         note="a comment inside a bullet-only section is also a non-bullet "
              "line; both messages name the same fix"),
    dict(name="app_no_frontmatter", base="application",
         build=lambda: APPLICATION.split("---\n", 2)[2].lstrip("\n"),
         expect="no YAML frontmatter — the file must open with a `---` "
                "block", count=None,
         note="cascades: with no frontmatter there is no company or role to "
              "build the expected H1 from"),
]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    failures = 0
    checked = 0

    print("=" * 78)
    print("VALID FIXTURES  (expect zero violations)")
    print("=" * 78)
    valid_paths = []
    for entity, (fname, text, validator) in BASES.items():
        path = FIXTURES / "valid" / fname
        write(path, text)
        valid_paths.append(path)
        violations = validator(path)
        checked += 1
        if violations:
            failures += 1
            print(f"FAIL  {entity:<12} {fname}")
            for v in violations:
                print(f"        {v}")
        else:
            print(f"ok    {entity:<12} {fname}")

    print()
    print("=" * 78)
    print("BROKEN FIXTURES  (expect the named violation, and only it)")
    print("=" * 78)
    for case in CASES:
        name = case["name"]
        fname, base, validator = BASES[case["base"]]
        if "build" in case:
            text = case["build"]()
        else:
            text = base
            for old, new in case["edits"]:
                if old not in text:
                    print(f"FAIL  {name}: fixture edit does not apply: {old!r}")
                    failures += 1
                    text = None
                    break
                text = text.replace(old, new, 1)
            if text is None:
                continue
        path = FIXTURES / name / fname
        write(path, text)

        violations = validator(path)
        checked += 1
        problems = []
        # expect=None marks a mutation that must still validate — a rule that
        # fires on it is over-strict, which no "expect this message" case can
        # catch.
        if case["expect"] is None:
            if violations:
                problems.append("expected no violations")
        else:
            matched = [v for v in violations if case["expect"] in v]
            if not violations:
                problems.append("no violations at all")
            elif not matched:
                problems.append(f"expected {case['expect']!r}, got none matching")
        if case["count"] is not None and len(violations) != case["count"]:
            problems.append(
                f"expected {case['count']} violation(s), got {len(violations)}"
            )
        if problems:
            failures += 1
            print(f"FAIL  {name}")
            for p in problems:
                print(f"        ! {p}")
            for v in violations:
                print(f"        - {v}")
        else:
            extra = f"  [{case['note']}]" if "note" in case else ""
            print(f"ok    {name}{extra}")
            for v in violations:
                print(f"        - {v}")

    print()
    print("=" * 78)
    print("CLI")
    print("=" * 78)
    cli = SRC / "validate.py"

    clean = subprocess.run(
        [sys.executable, str(cli), *[str(p) for p in valid_paths]],
        capture_output=True, text=True,
    )
    print(f"$ validate.py <3 valid fixtures>   -> exit {clean.returncode}")
    print("  " + clean.stdout.strip().replace("\n", "\n  "))
    checked += 1
    if clean.returncode != 0:
        failures += 1
        print("  FAIL: a clean run must exit 0")

    broken = FIXTURES / "app_score_six" / BASES["application"][0]
    dirty = subprocess.run(
        [sys.executable, str(cli), str(valid_paths[0]), str(broken)],
        capture_output=True, text=True,
    )
    print(f"\n$ validate.py <1 valid> <1 broken>  -> exit {dirty.returncode}")
    print("  " + dirty.stdout.strip().replace("\n", "\n  "))
    checked += 1
    if dirty.returncode != 1:
        failures += 1
        print("  FAIL: a failing run must exit 1")

    untyped = FIXTURES / "untyped" / "Mystery.md"
    write(untyped, "---\nfoo: bar\n---\n\n# Mystery\n")
    typeless = subprocess.run(
        [sys.executable, str(cli), str(untyped)],
        capture_output=True, text=True,
    )
    print(f"\n$ validate.py <no type: key>        -> exit {typeless.returncode}")
    print("  " + typeless.stdout.strip().replace("\n", "\n  "))
    checked += 1
    if typeless.returncode != 1 or "no `type:` key" not in typeless.stdout:
        failures += 1
        print("  FAIL: a missing type: must be a violation, exit 1")

    importable = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(SRC)!r});"
         f"from validate import validate_path;"
         f"print('import ok, violations:', validate_path({str(broken)!r}))"],
        capture_output=True, text=True,
    )
    print(f"\n$ from validate import validate_path -> exit "
          f"{importable.returncode}")
    print("  " + (importable.stdout or importable.stderr).strip())
    checked += 1
    if importable.returncode != 0:
        failures += 1
        print("  FAIL: validate.py must import without running")

    print()
    print("=" * 78)
    if failures:
        print(f"{failures} of {checked} checks FAILED")
    else:
        print(f"all {checked} checks passed")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
