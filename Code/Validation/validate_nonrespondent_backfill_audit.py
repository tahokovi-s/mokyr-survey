#!/usr/bin/env python3
"""
Validate audit-sensitive nonrespondent backfill artifacts.

Checks:
  - Findings first/last names exactly match the authoritative roster by node_id.
  - Approved rows exactly match their approved findings counterparts on exported fields.
  - Approved rows have blank clear_fields values.
  - No duplicate node_ids appear in approved files.
  - Any nonblank us_state implies a recognized U.S. country label in findings and approved files.
  - Any nonblank backfill_country uses canonical short-form labels for known aliases.
  - Any nonblank backfill_us_state uses a USPS two-letter abbreviation.
  - Findings/approved files do not use literal placeholder strings such as none/null/nan.
  - Backfill markdown outputs do not contain raw email addresses.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
EMPTY_LITERALS = {"none", "null", "nan"}
COUNTRY_ALIASES = {
    "United States of America": "United States",
    "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
}
US_COUNTRY_VALUES = {"United States"}
US_STATE_ABBREV_RE = re.compile(r"^[A-Z]{2}$")
APPROVED_FIELD_MAP = {
    "backfill_email": "backfill_email",
    "backfill_phd_institution_raw": "backfill_phd_institution_raw",
    "backfill_phd_institution_canon": "backfill_phd_institution_canon",
    "backfill_phd_year": "backfill_phd_year",
    "backfill_current_employer_raw": "backfill_current_employer_raw",
    "backfill_current_employer_canon": "backfill_current_employer_canon",
    "backfill_country": "backfill_country",
    "backfill_us_state": "backfill_us_state",
    "source_1_url": "source_1_url",
    "source_2_url": "source_2_url",
    "evidence_strength": "evidence_strength",
    "clear_fields": "clear_fields",
    "notes": "notes",
}
GENERATION_PHASES = {
    "gen3": [
        "phase1",
        "phase2",
        "phase3",
        "phase4",
        "phase5",
        "phase5_source_audit",
        "phase6",
        "phase7",
    ],
    "gen4": ["phase1", "phase2", "phase3", "phase4", "report"],
}


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def latest_matching_path(pattern: re.Pattern[str], base_dir: Path) -> Path | None:
    if not base_dir.exists():
        return None
    matches: list[tuple[datetime, Path]] = []
    for path in base_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        return None
    matches.sort()
    return matches[-1][1]


def latest_file(pattern: re.Pattern[str], base_dir: Path) -> Path:
    latest = latest_matching_path(pattern, base_dir)
    if latest is None:
        raise FileNotFoundError(f"No matching files found under {base_dir}")
    return latest


def generation_pattern(generation: str, kind: str) -> re.Pattern[str]:
    if kind in {"roster", "findings", "approved"}:
        stem = kind.capitalize()
        return re.compile(rf"^{generation.capitalize()}_Nonrespondent_Backfill_{stem}_(\d{{6}})\.csv$")
    if kind == "report":
        return re.compile(rf"^{generation.capitalize()}_Nonrespondent_Backfill_Report_(\d{{6}})\.md$")
    if kind == "phase5_source_audit":
        return re.compile(rf"^{generation.capitalize()}_Nonrespondent_Backfill_Phase5_Source_Audit_(\d{{6}})\.md$")
    phase_num = kind.removeprefix("phase")
    return re.compile(rf"^{generation.capitalize()}_Nonrespondent_Backfill_Phase{phase_num}_(\d{{6}})\.md$")


def resolve_path(raw: str | None, label: str, base_dir: Path) -> Path:
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return latest_file(generation_pattern(*label.split(":", 1)), base_dir)


def resolve_optional_path(raw: str | None, label: str, base_dir: Path) -> Path | None:
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else PROJECT_ROOT / path
    generation, kind = label.split(":", 1)
    return latest_matching_path(generation_pattern(generation, kind), base_dir)


def exact_generation_path(generation: str, kind: str, token: str, base_dir: Path) -> Path:
    suffix = "csv" if kind in {"roster", "findings", "approved"} else "md"
    if kind in {"roster", "findings", "approved"}:
        filename = f"{generation.capitalize()}_Nonrespondent_Backfill_{kind.capitalize()}_{token}.{suffix}"
    elif kind == "report":
        filename = f"{generation.capitalize()}_Nonrespondent_Backfill_Report_{token}.{suffix}"
    elif kind == "phase5_source_audit":
        filename = f"{generation.capitalize()}_Nonrespondent_Backfill_Phase5_Source_Audit_{token}.{suffix}"
    else:
        phase_num = kind.removeprefix("phase")
        filename = f"{generation.capitalize()}_Nonrespondent_Backfill_Phase{phase_num}_{token}.{suffix}"
    return base_dir / filename


def load_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def add_issue(
    issues: list[dict[str, str]],
    severity: str,
    issue_type: str,
    detail: str,
    path: Path | str = "",
    node_id: str = "",
) -> None:
    issues.append(
        {
            "severity": severity,
            "issue_type": issue_type,
            "detail": detail,
            "path": str(path),
            "node_id": node_id,
        }
    )


def normalize_country(raw_country: str) -> str:
    country = re.sub(r"\s+", " ", (raw_country or "").strip())
    if not country:
        return ""
    return COUNTRY_ALIASES.get(country, country)


def validate_name_keys(
    roster_rows: list[dict[str, str]],
    findings_rows: list[dict[str, str]],
    findings_path: Path,
    issues: list[dict[str, str]],
) -> None:
    roster_by_id = {row["node_id"]: row for row in roster_rows}
    for row in findings_rows:
        node_id = row.get("node_id", "")
        roster = roster_by_id.get(node_id)
        if not roster:
            continue
        for field in ("first_name", "last_name"):
            if row.get(field, "") != roster.get(field, ""):
                add_issue(
                    issues,
                    "high",
                    "name_key_mismatch",
                    f"{field} differs between findings and roster: {row.get(field, '')!r} != {roster.get(field, '')!r}",
                    findings_path,
                    node_id,
                )


def validate_approved_alignment(
    findings_rows: list[dict[str, str]],
    approved_rows: list[dict[str, str]],
    approved_path: Path,
    issues: list[dict[str, str]],
) -> None:
    approved_findings = {
        row["node_id"]: row
        for row in findings_rows
        if row.get("research_status", "") == "approved"
    }
    seen: set[str] = set()
    for row in approved_rows:
        node_id = row.get("node_id", "")
        if node_id in seen:
            add_issue(issues, "high", "duplicate_approved_node_id", "Duplicate node_id in approved file.", approved_path, node_id)
            continue
        seen.add(node_id)

        finding = approved_findings.get(node_id)
        if not finding:
            add_issue(issues, "high", "missing_approved_source_row", "Approved row has no approved findings counterpart.", approved_path, node_id)
            continue

        for approved_field, findings_field in APPROVED_FIELD_MAP.items():
            if row.get(approved_field, "") != finding.get(findings_field, ""):
                add_issue(
                    issues,
                    "high",
                    "approved_field_mismatch",
                    f"{approved_field} differs from findings export.",
                    approved_path,
                    node_id,
                )
                break

        if row.get("clear_fields", ""):
            add_issue(
                issues,
                "high",
                "unexpected_clear_fields_value",
                "clear_fields should be blank for this snapshot.",
                approved_path,
                node_id,
            )

    extra_approved = sorted(set(approved_findings) - seen)
    for node_id in extra_approved:
        add_issue(
            issues,
            "medium",
            "approved_row_missing",
            "Approved finding is missing from the approved export.",
            approved_path,
            node_id,
        )


def validate_country_state_consistency(
    rows: list[dict[str, str]],
    path: Path,
    issues: list[dict[str, str]],
) -> None:
    for row in rows:
        node_id = row.get("node_id", "")
        country = row.get("backfill_country", "") or row.get("country", "")
        us_state = row.get("backfill_us_state", "") or row.get("us_state", "")
        if us_state and normalize_country(country) not in US_COUNTRY_VALUES:
            add_issue(
                issues,
                "high",
                "us_state_without_us_country",
                f"us_state={us_state!r} but country={country!r}.",
                path,
                node_id,
            )


def validate_backfill_country_canonical(
    rows: list[dict[str, str]],
    path: Path,
    issues: list[dict[str, str]],
) -> None:
    for row in rows:
        node_id = row.get("node_id", "")
        backfill_country = row.get("backfill_country", "")
        if backfill_country and backfill_country != normalize_country(backfill_country):
            add_issue(
                issues,
                "high",
                "backfill_country_non_canonical",
                f"backfill_country={backfill_country!r} should use {normalize_country(backfill_country)!r}.",
                path,
                node_id,
            )


def validate_backfill_state_abbreviations(
    rows: list[dict[str, str]],
    path: Path,
    issues: list[dict[str, str]],
) -> None:
    for row in rows:
        node_id = row.get("node_id", "")
        backfill_state = row.get("backfill_us_state", "")
        if backfill_state and not US_STATE_ABBREV_RE.fullmatch(backfill_state):
            add_issue(
                issues,
                "high",
                "backfill_us_state_non_canonical",
                f"backfill_us_state={backfill_state!r} is not a USPS two-letter abbreviation.",
                path,
                node_id,
            )


def validate_placeholder_literals(
    rows: list[dict[str, str]],
    path: Path,
    issues: list[dict[str, str]],
) -> None:
    for row in rows:
        node_id = row.get("node_id", "")
        for field, value in row.items():
            if value.lower() in EMPTY_LITERALS:
                add_issue(
                    issues,
                    "medium",
                    "placeholder_literal_value",
                    f"{field} contains placeholder literal {value!r}.",
                    path,
                    node_id,
                )


def validate_markdown_emails(path: Path, issues: list[dict[str, str]]) -> None:
    text = path.read_text(encoding="utf-8")
    matches = EMAIL_RE.findall(text)
    if matches:
        preview = ", ".join(sorted(set(matches))[:3])
        add_issue(
            issues,
            "high",
            "markdown_contains_email",
            f"Found {len(matches)} raw email address match(es): {preview}",
            path,
        )


def resolve_generation_paths(
    generation: str,
    token: str | None,
    args: argparse.Namespace,
    derived_dir: Path,
    output_dir: Path,
    required: bool,
) -> dict[str, Path | None]:
    resolved: dict[str, Path | None] = {}
    for kind in ("roster", "findings", "approved"):
        arg_name = f"{generation}_{kind}"
        arg_value = getattr(args, arg_name, None)
        if token:
            path = exact_generation_path(generation, kind, token, derived_dir)
            if required or path.exists():
                resolved[arg_name] = path
        elif required:
            resolved[arg_name] = resolve_path(arg_value, f"{generation}:{kind}", derived_dir)
        else:
            resolved[arg_name] = resolve_optional_path(arg_value, f"{generation}:{kind}", derived_dir)

    for kind in GENERATION_PHASES[generation]:
        arg_name = f"{generation}_{kind}"
        arg_value = getattr(args, arg_name, None)
        if token:
            path = exact_generation_path(generation, kind, token, output_dir)
            if required or path.exists():
                resolved[arg_name] = path
        else:
            if required:
                resolved[arg_name] = resolve_path(arg_value, f"{generation}:{kind}", output_dir)
            else:
                resolved[arg_name] = resolve_optional_path(arg_value, f"{generation}:{kind}", output_dir)
    return resolved


def validate_generation(
    generation: str,
    paths: dict[str, Path | None],
    issues: list[dict[str, str]],
) -> None:
    roster_path = paths.get(f"{generation}_roster")
    findings_path = paths.get(f"{generation}_findings")
    approved_path = paths.get(f"{generation}_approved")
    if not (roster_path and findings_path and approved_path):
        return

    roster_rows = load_csv(roster_path)
    findings_rows = load_csv(findings_path)
    approved_rows = load_csv(approved_path)

    validate_name_keys(roster_rows, findings_rows, findings_path, issues)
    validate_approved_alignment(findings_rows, approved_rows, approved_path, issues)
    validate_country_state_consistency(findings_rows, findings_path, issues)
    validate_country_state_consistency(approved_rows, approved_path, issues)
    validate_backfill_country_canonical(findings_rows, findings_path, issues)
    validate_backfill_country_canonical(approved_rows, approved_path, issues)
    validate_backfill_state_abbreviations(findings_rows, findings_path, issues)
    validate_backfill_state_abbreviations(approved_rows, approved_path, issues)
    validate_placeholder_literals(findings_rows, findings_path, issues)
    validate_placeholder_literals(approved_rows, approved_path, issues)

    for kind in GENERATION_PHASES[generation]:
        md_path = paths.get(f"{generation}_{kind}")
        if md_path:
            validate_markdown_emails(md_path, issues)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Snapshot token in MMDDYY format. Defaults to latest available.")
    parser.add_argument("--gen2-report")
    for generation, phase_kinds in GENERATION_PHASES.items():
        parser.add_argument(f"--{generation}-roster")
        parser.add_argument(f"--{generation}-findings")
        parser.add_argument(f"--{generation}-approved")
        for kind in phase_kinds:
            parser.add_argument(f"--{generation}-{kind.replace('_', '-')}")
    args = parser.parse_args()

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    output_dir = PROJECT_ROOT / "Output"

    gen2_report: Path | None
    if args.date:
        token = args.date
        gen2_report = exact_generation_path("gen2", "report", token, output_dir)
    else:
        gen2_report = resolve_path(args.gen2_report, "gen2:report", output_dir)

    issues: list[dict[str, str]] = []

    generation_paths = {
        "gen3": resolve_generation_paths("gen3", args.date, args, derived_dir, output_dir, required=True),
        "gen4": resolve_generation_paths("gen4", args.date, args, derived_dir, output_dir, required=False),
    }
    validate_generation("gen3", generation_paths["gen3"], issues)
    validate_generation("gen4", generation_paths["gen4"], issues)

    if gen2_report and gen2_report.exists():
        validate_markdown_emails(gen2_report, issues)

    print("Nonrespondent backfill audit validation")
    print(f"- gen2_report: {gen2_report}")
    for generation, paths in generation_paths.items():
        for label, path in paths.items():
            if path is None:
                continue
            print(f"- {label}: {path}")
        if generation == "gen4" and not any(path is not None for path in paths.values()):
            print("- gen4: no artifacts found; skipped")

    if args.date:
        missing_required: list[str] = []
        if gen2_report and not gen2_report.exists():
            missing_required.append("gen2_report")
        for label, path in generation_paths["gen3"].items():
            if path is not None and not path.exists():
                missing_required.append(label)
        if missing_required:
            print("FAIL: required artifacts are missing.")
            for label in missing_required:
                if label == "gen2_report":
                    print(f"- {label}: {gen2_report}")
                else:
                    print(f"- {label}: {generation_paths['gen3'][label]}")
            return 1

    if not issues:
        print("PASS: no audit issues found.")
        return 0

    issues.sort(key=lambda row: (row["severity"] != "high", row["issue_type"], row["node_id"], row["path"]))
    print(f"FAIL: {len(issues)} issue(s) found.")
    for issue in issues:
        location = issue["path"]
        if issue["node_id"]:
            location = f"{location} [{issue['node_id']}]"
        print(f"[{issue['severity']}] {issue['issue_type']}: {issue['detail']} :: {location}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
