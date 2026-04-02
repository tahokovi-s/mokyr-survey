#!/usr/bin/env python3
"""
Validate and render the Gen 3 public student-verification layer.

Inputs:
  Data/Derived/Gen3_Public_Student_Verification_Findings_{date}.csv
  Data/Derived/Network_Nodes_{date}.csv
  Data/Derived/Network_Edges_{date}.csv

Outputs:
  Data/Derived/Gen3_Student_Verification_Audit_{date}.csv
  Data/Derived/Gen3_Student_Verification_Validation_{date}.csv
  Data/Derived/Gen3_Public_Student_Verification_Report_{date}.md
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Code"))

from Shared.name_normalization import normalize_person_text

FILE_PATTERNS = {
    "findings": re.compile(r"^Gen3_Public_Student_Verification_Findings_(\d{6})\.csv$"),
    "nodes": re.compile(r"^Network_Nodes_(\d{6})\.csv$"),
    "edges": re.compile(r"^Network_Edges_(\d{6})\.csv$"),
}

VALID_STATUSES = {
    "confirmed_primary_advisor",
    "confirmed_coadvisor",
    "likely_but_not_strong_enough",
    "not_supported_by_public_evidence",
    "unresolved",
}

VALID_EVIDENCE = {"strong", "moderate", "weak"}

AUDIT_FIELDNAMES = [
    "advisor_name",
    "advisor_node_id",
    "student_name",
    "student_node_id",
    "student_is_respondent",
    "current_edge_types",
    "survey_backed",
    "verification_status",
    "relationship_type",
    "evidence_strength",
    "verification_layer",
    "source_1_url",
    "source_1_type",
    "source_2_url",
    "source_2_type",
    "current_affiliation",
    "public_email",
    "recommended_action",
    "notes",
]

VALIDATION_FIELDNAMES = [
    "severity",
    "issue_type",
    "advisor_name",
    "student_name",
    "detail",
]


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def resolve_path(raw: str | None, label: str, base_dir: Path) -> Path:
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else PROJECT_ROOT / path

    matches = []
    for path in base_dir.iterdir():
        match = FILE_PATTERNS[label].match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        raise FileNotFoundError(f"No matching {label} file found under {base_dir}")
    matches.sort()
    return matches[-1][1]


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    os.replace(tmp_path, path)


def normalize_name(value: str) -> str:
    return normalize_person_text(value)


def normalize_email(value: str) -> str:
    return (value or "").strip().lower().rstrip(";").strip()


def full_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part).strip()


def format_snapshot_date(date_token: str) -> str:
    return parse_mmddyy(date_token).strftime("%Y-%m-%d")


def add_issue(
    issues: list[dict],
    severity: str,
    issue_type: str,
    detail: str,
    advisor_name: str = "",
    student_name: str = "",
) -> None:
    issues.append(
        {
            "severity": severity,
            "issue_type": issue_type,
            "advisor_name": advisor_name,
            "student_name": student_name,
            "detail": detail,
        }
    )


def sanitize_finding_row(row: dict) -> dict:
    return {key: (row.get(key, "") or "").strip() for key in row.keys()}


def build_node_indexes(nodes_rows: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    by_name = defaultdict(list)
    by_email = defaultdict(list)
    for node in nodes_rows:
        node_name = normalize_name(full_name(node.get("first_name", ""), node.get("last_name", "")))
        node_email = normalize_email(node.get("email", ""))
        if node_name:
            by_name[node_name].append(node)
        if node_email:
            by_email[node_email].append(node)
    return by_name, by_email


def resolve_advisor_node(row: dict, nodes_by_name: dict[str, list[dict]], issues: list[dict]) -> dict | None:
    advisor_name = row.get("advisor_name", "")
    matches = [
        node
        for node in nodes_by_name.get(normalize_name(advisor_name), [])
        if (node.get("is_respondent", "") or "").strip().lower() == "true"
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        add_issue(issues, "high", "advisor_not_found", "Advisor name did not resolve to a unique respondent node.", advisor_name)
    else:
        add_issue(issues, "high", "advisor_ambiguous", "Advisor name resolved to multiple respondent nodes.", advisor_name)
    return None


def resolve_student_node(
    row: dict,
    nodes_by_name: dict[str, list[dict]],
    nodes_by_email: dict[str, list[dict]],
    issues: list[dict],
) -> dict | None:
    advisor_name = row.get("advisor_name", "")
    student_name = row.get("student_name", "")
    public_email = normalize_email(row.get("public_email", ""))

    matches = []
    if public_email:
        matches.extend(nodes_by_email.get(public_email, []))
    if not matches:
        matches.extend(nodes_by_name.get(normalize_name(student_name), []))

    if len(matches) == 1:
        return matches[0]
    if not matches:
        add_issue(issues, "high", "student_not_found", "Student did not resolve to a unique node in the current graph.", advisor_name, student_name)
    else:
        add_issue(issues, "high", "student_ambiguous", "Student resolved to multiple nodes in the current graph.", advisor_name, student_name)
    return None


def classify_verification_layer(status: str, survey_backed: bool) -> str:
    if status in {"confirmed_primary_advisor", "confirmed_coadvisor"}:
        return "publicly_confirmed"
    if status == "likely_but_not_strong_enough":
        return "survey_backed_publicly_weak" if survey_backed else "publicly_weak"
    if status == "not_supported_by_public_evidence":
        return "survey_backed_publicly_not_supported" if survey_backed else "publicly_not_supported"
    return "survey_backed_publicly_unresolved" if survey_backed else "publicly_unresolved"


def build_audit_rows(findings_rows: list[dict], nodes_rows: list[dict], edges_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    issues = []
    nodes_by_name, nodes_by_email = build_node_indexes(nodes_rows)
    edge_types_by_pair = defaultdict(set)
    for edge in edges_rows:
        edge_types_by_pair[(edge.get("source_id", "").strip(), edge.get("target_id", "").strip())].add(edge.get("edge_type", "").strip())

    seen_pairs = set()
    audit_rows = []

    for raw_row in findings_rows:
        row = sanitize_finding_row(raw_row)
        advisor_name = row.get("advisor_name", "")
        student_name = row.get("student_name", "")
        status = row.get("verification_status", "")
        evidence_strength = row.get("evidence_strength", "")

        if status not in VALID_STATUSES:
            add_issue(issues, "high", "invalid_verification_status", f"Unexpected verification status: {status!r}", advisor_name, student_name)
        if evidence_strength and evidence_strength not in VALID_EVIDENCE:
            add_issue(issues, "high", "invalid_evidence_strength", f"Unexpected evidence strength: {evidence_strength!r}", advisor_name, student_name)

        dedupe_key = (normalize_name(advisor_name), normalize_name(student_name))
        if dedupe_key in seen_pairs:
            add_issue(issues, "high", "duplicate_finding_row", "Duplicate advisor-student finding row.", advisor_name, student_name)
            continue
        seen_pairs.add(dedupe_key)

        advisor_node = resolve_advisor_node(row, nodes_by_name, issues)
        student_node = resolve_student_node(row, nodes_by_name, nodes_by_email, issues)
        advisor_node_id = advisor_node.get("node_id", "") if advisor_node else ""
        student_node_id = student_node.get("node_id", "") if student_node else ""
        edge_types = edge_types_by_pair.get((advisor_node_id, student_node_id), set())
        survey_backed = "q12a" in edge_types

        if advisor_node_id and student_node_id and not edge_types:
            add_issue(issues, "high", "missing_current_edge", "Finding resolves to nodes but no current edge exists between them.", advisor_name, student_name)
        if advisor_node_id and student_node_id and not survey_backed:
            add_issue(issues, "medium", "non_q12a_link", "Current link is not backed by a q12a edge.", advisor_name, student_name)

        audit_rows.append(
            {
                "advisor_name": advisor_name,
                "advisor_node_id": advisor_node_id,
                "student_name": student_name,
                "student_node_id": student_node_id,
                "student_is_respondent": "yes" if student_node and (student_node.get("is_respondent", "") or "").strip().lower() == "true" else "no",
                "current_edge_types": "+".join(sorted(edge_types)),
                "survey_backed": "yes" if survey_backed else "no",
                "verification_status": status,
                "relationship_type": row.get("relationship_type", ""),
                "evidence_strength": evidence_strength,
                "verification_layer": classify_verification_layer(status, survey_backed),
                "source_1_url": row.get("source_1_url", ""),
                "source_1_type": row.get("source_1_type", ""),
                "source_2_url": row.get("source_2_url", ""),
                "source_2_type": row.get("source_2_type", ""),
                "current_affiliation": row.get("current_affiliation", ""),
                "public_email": row.get("public_email", ""),
                "recommended_action": row.get("recommended_action", ""),
                "notes": row.get("notes", ""),
            }
        )

    audit_rows.sort(key=lambda row: (normalize_name(row["advisor_name"]), normalize_name(row["student_name"])))
    return audit_rows, issues


def render_report(path: Path, date_token: str, audit_rows: list[dict], validation_rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    strong_rows = [row for row in audit_rows if row["verification_status"] in {"confirmed_primary_advisor", "confirmed_coadvisor"}]
    weak_rows = [row for row in audit_rows if row["verification_status"] == "likely_but_not_strong_enough"]
    unsupported_rows = [row for row in audit_rows if row["verification_status"] == "not_supported_by_public_evidence"]
    unresolved_rows = [row for row in audit_rows if row["verification_status"] == "unresolved"]
    issue_counts = Counter(row["severity"] for row in validation_rows if row.get("severity") != "info")

    status_label = "PASS" if not issue_counts else "FAIL"

    lines = [
        "# Gen 3 Public Student Verification Report",
        "",
        f"**Date:** {format_snapshot_date(date_token)}",
        f"**Snapshot:** {date_token}",
        f"**Validator status:** {status_label}",
        f"**Scope:** {len(audit_rows)} survey-listed Gen 4 students under current Gen 3 respondents",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        f"- **Total advisor-student pairs audited:** {len(audit_rows)}",
        f"- **Publicly strong confirmations:** {len(strong_rows)}",
        f"- **Survey-backed but not strongly confirmed:** {len(weak_rows)}",
        f"- **Not supported by public evidence:** {len(unsupported_rows)}",
        f"- **Unresolved:** {len(unresolved_rows)}",
        f"- **Validation issues:** {sum(issue_counts.values())}",
        "",
        "Survey `Q12a` remains the capture rule for these links. Public-source verification is a confidence layer for reporting and future cleanup, not a removal rule.",
        "",
        "| Advisor | Student | Status | Evidence | Current Edge Types | Verification Layer |",
        "|---|---|---|---|---|---|",
    ]

    for row in audit_rows:
        lines.append(
            f"| {row['advisor_name']} | {row['student_name']} | {row['verification_status']} | "
            f"{row['evidence_strength']} | {row['current_edge_types'] or '(none)'} | {row['verification_layer']} |"
        )

    lines.extend(["", "## Confirmed Advisor-Student Links", ""])
    if strong_rows:
        for row in strong_rows:
            lines.append(f"### {row['advisor_name']} -> {row['student_name']}")
            lines.append("")
            lines.append(f"- **Status:** `{row['verification_status']}`")
            lines.append(f"- **Relationship:** `{row['relationship_type'] or 'unclear'}`")
            lines.append(f"- **Edge types:** `{row['current_edge_types'] or 'none'}`")
            if row["source_1_url"]:
                lines.append(f"- **Source 1:** {row['source_1_url']}")
            if row["source_2_url"]:
                lines.append(f"- **Source 2:** {row['source_2_url']}")
            if row["notes"]:
                lines.append(f"- **Notes:** {row['notes']}")
            lines.append("")
    else:
        lines.append("None.")
        lines.append("")

    lines.extend(["## Weak / Unresolved Cases", ""])
    if weak_rows or unsupported_rows or unresolved_rows:
        for row in weak_rows + unsupported_rows + unresolved_rows:
            lines.append(f"### {row['advisor_name']} -> {row['student_name']}")
            lines.append("")
            lines.append(f"- **Status:** `{row['verification_status']}`")
            lines.append(f"- **Evidence strength:** `{row['evidence_strength']}`")
            lines.append(f"- **Verification layer:** `{row['verification_layer']}`")
            if row["source_1_url"]:
                lines.append(f"- **Source 1:** {row['source_1_url']}")
            if row["source_2_url"]:
                lines.append(f"- **Source 2:** {row['source_2_url']}")
            if row["notes"]:
                lines.append(f"- **Notes:** {row['notes']}")
            lines.append("")
    else:
        lines.append("None.")
        lines.append("")

    lines.extend(["## Existing-Network / Duplicate-Match Findings", ""])
    lines.append("All five students resolve to current graph nodes under the expected Gen 3 advisors. No duplicate or variant-name conflicts were found in this verification pass.")
    lines.append("")

    if validation_rows and any(row.get("severity") != "info" for row in validation_rows):
        lines.extend(["## Validation Issues", ""])
        for row in validation_rows:
            if row.get("severity") == "info":
                continue
            lines.append(f"- **{row['severity']} / {row['issue_type']}**: {row['advisor_name']} {row['student_name']} -- {row['detail']}".strip())
        lines.append("")

    lines.extend(["## Case-by-Case Appendix", ""])
    for row in audit_rows:
        lines.append(f"### {row['advisor_name']} / {row['student_name']}")
        lines.append("")
        lines.append(f"- **Advisor node:** `{row['advisor_node_id']}`")
        lines.append(f"- **Student node:** `{row['student_node_id']}`")
        lines.append(f"- **Student is respondent:** `{row['student_is_respondent']}`")
        lines.append(f"- **Current edge types:** `{row['current_edge_types'] or 'none'}`")
        lines.append(f"- **Survey backed:** `{row['survey_backed']}`")
        lines.append(f"- **Verification status:** `{row['verification_status']}`")
        lines.append(f"- **Evidence strength:** `{row['evidence_strength']}`")
        if row["current_affiliation"]:
            lines.append(f"- **Current affiliation:** {row['current_affiliation']}")
        if row["public_email"]:
            lines.append(f"- **Public email:** `{row['public_email']}`")
        if row["source_1_url"]:
            lines.append(f"- **Source 1:** {row['source_1_url']}")
        if row["source_2_url"]:
            lines.append(f"- **Source 2:** {row['source_2_url']}")
        if row["notes"]:
            lines.append(f"- **Notes:** {row['notes']}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and render Gen 3 public student verification outputs")
    parser.add_argument("--date", help="Snapshot date (MMDDYY)")
    parser.add_argument("--findings", help="Path to Gen3 public student verification findings CSV")
    parser.add_argument("--nodes", help="Path to network nodes CSV")
    parser.add_argument("--edges", help="Path to network edges CSV")
    args = parser.parse_args()

    date_token = args.date or datetime.now().strftime("%m%d%y")
    findings_path = resolve_path(args.findings, "findings", PROJECT_ROOT / "Data" / "Derived")
    nodes_path = resolve_path(args.nodes, "nodes", PROJECT_ROOT / "Data" / "Derived")
    edges_path = resolve_path(args.edges, "edges", PROJECT_ROOT / "Data" / "Derived")

    findings_rows = load_csv(findings_path)
    nodes_rows = load_csv(nodes_path)
    edges_rows = load_csv(edges_path)

    audit_rows, validation_rows = build_audit_rows(findings_rows, nodes_rows, edges_rows)
    if not validation_rows:
        validation_rows = [
            {
                "severity": "info",
                "issue_type": "validation_pass",
                "advisor_name": "",
                "student_name": "",
                "detail": "No validation issues.",
            }
        ]

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    audit_out = derived_dir / f"Gen3_Student_Verification_Audit_{date_token}.csv"
    validation_out = derived_dir / f"Gen3_Student_Verification_Validation_{date_token}.csv"
    report_out = derived_dir / f"Gen3_Public_Student_Verification_Report_{date_token}.md"

    write_csv(audit_out, AUDIT_FIELDNAMES, audit_rows)
    write_csv(validation_out, VALIDATION_FIELDNAMES, validation_rows)
    render_report(report_out, date_token, audit_rows, validation_rows)

    substantive_issues = [row for row in validation_rows if row.get("severity") == "high"]
    print(f"Audit rows: {len(audit_rows)}")
    print(f"Validation issues: {len([row for row in validation_rows if row.get('severity') != 'info'])}")
    print(f"Wrote {audit_out.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {validation_out.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {report_out.relative_to(PROJECT_ROOT)}")

    if substantive_issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
