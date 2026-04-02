#!/usr/bin/env python3
"""
Normalize and render the Gen 2 empty-Q12a public-recovery artifacts.

Outputs:
  Data/Derived/Gen2_EmptyQ12a_Public_Recovery_Findings_{date}.csv
  Data/Derived/Gen2_EmptyQ12a_Public_Recovery_Report_{date}.md
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
    "findings": re.compile(r"^Gen2_EmptyQ12a_Public_Recovery_Findings_(\d{6})\.csv$"),
    "nodes": re.compile(r"^Network_Nodes_(\d{6})\.csv$"),
}

FIELDNAMES = [
    "advisor_name",
    "advisor_status",
    "student_name",
    "relationship_type",
    "student_already_in_network",
    "existing_network_match",
    "recommended_action",
    "recommended_mechanism",
    "source_1_url",
    "source_1_type",
    "source_2_url",
    "source_2_type",
    "evidence_strength",
    "current_affiliation",
    "public_email",
    "notes",
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


def normalize_email(value: str) -> str:
    return (value or "").strip().lower().rstrip(";").strip()


def normalize_name(value: str) -> str:
    return normalize_person_text(value)


def full_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part).strip()


def format_snapshot_date(date_token: str) -> str:
    return parse_mmddyy(date_token).strftime("%Y-%m-%d")


def sanitize_row(row: dict) -> dict:
    sanitized = {field: (row.get(field, "") or "").strip() for field in FIELDNAMES}
    if (
        sanitized["advisor_status"] in {"no_public_evidence_found", "unresolved"}
        and not sanitized["student_name"]
        and not sanitized["notes"]
        and sanitized["public_email"]
    ):
        sanitized["notes"] = sanitized["public_email"]
        sanitized["public_email"] = ""
    return sanitized


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


def enrich_rows(findings_rows: list[dict], nodes_rows: list[dict]) -> list[dict]:
    nodes_by_name, nodes_by_email = build_node_indexes(nodes_rows)
    enriched = []

    for row in findings_rows:
        enriched_row = dict(row)
        if row["student_name"]:
            matches = []
            email = normalize_email(row["public_email"])
            if email:
                matches.extend(nodes_by_email.get(email, []))
            if not matches:
                matches.extend(nodes_by_name.get(normalize_name(row["student_name"]), []))

            if len(matches) == 1:
                node_id = matches[0]["node_id"]
                enriched_row["student_already_in_network"] = "yes"
                enriched_row["existing_network_match"] = node_id
                enriched_row["recommended_action"] = "none"
                enriched_row["recommended_mechanism"] = "none"
                note = enriched_row["notes"]
                suffix = f"Captured in current network as {node_id}."
                if suffix not in note:
                    enriched_row["notes"] = f"{note} {suffix}".strip()
            else:
                enriched_row["student_already_in_network"] = "no"
                enriched_row["existing_network_match"] = ""
        else:
            enriched_row["student_already_in_network"] = ""
            enriched_row["existing_network_match"] = ""
            if enriched_row["advisor_status"] == "no_public_evidence_found":
                enriched_row["recommended_action"] = "none"
                enriched_row["recommended_mechanism"] = "none"
            elif enriched_row["advisor_status"] == "unresolved":
                enriched_row["recommended_action"] = "investigate_public_sources"
                enriched_row["recommended_mechanism"] = "none"

        enriched.append(enriched_row)

    enriched.sort(
        key=lambda row: (
            normalize_name(row["advisor_name"]),
            normalize_name(row["student_name"]),
            row["advisor_status"],
        )
    )
    return enriched


def render_report(path: Path, date_token: str, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["advisor_name"]].append(row)

    advisor_status = {}
    for advisor_name, advisor_rows in grouped.items():
        advisor_status[advisor_name] = advisor_rows[0]["advisor_status"]

    status_counts = Counter(advisor_status.values())
    confirmed_rows = [row for row in rows if row["advisor_status"] == "confirmed_students_found" and row["student_name"]]
    no_evidence_rows = [row for row in rows if row["advisor_status"] == "no_public_evidence_found" and not row["student_name"]]
    unresolved_rows = [row for row in rows if row["advisor_status"] == "unresolved" and not row["student_name"]]
    pending_add_rows = [row for row in confirmed_rows if row["recommended_action"] == "add_to_network"]
    captured_rows = [row for row in confirmed_rows if row["student_already_in_network"] == "yes"]

    lines = [
        "# Gen 2 Empty-Q12a Public Recovery Report",
        "",
        f"**Date:** {format_snapshot_date(date_token)}",
        f"**Snapshot:** {date_token}",
        f"**Scope:** {len(advisor_status)} Gen 2 advisors with blank raw/derived Q12a plus current network reconciliation",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        f"Of the {len(advisor_status)} advisors in this recovery universe, **{status_counts.get('confirmed_students_found', 0)} have strong public evidence of PhD students** ({len(confirmed_rows)} students total), **{status_counts.get('no_public_evidence_found', 0)} have no public evidence**, **{status_counts.get('unresolved', 0)} remain unresolved**, and **{status_counts.get('already_supplemented', 0)} were already supplemented before this pass.**",
        "",
        "| Status | Count |",
        "|--------|------:|",
    ]

    for status in ("confirmed_students_found", "no_public_evidence_found", "unresolved", "already_supplemented"):
        if status_counts.get(status, 0):
            lines.append(f"| {status} | {status_counts[status]} |")

    lines.extend(
        [
            "",
            f"**Confirmed students now captured in network:** {len(captured_rows)}",
            f"**Recommended additions still pending:** {len(pending_add_rows)}",
            "",
            "## Advisors with Confirmed PhD Students Found",
            "",
        ]
    )

    if confirmed_rows:
        for advisor_name in sorted({row["advisor_name"] for row in confirmed_rows}, key=normalize_name):
            advisor_rows = [row for row in confirmed_rows if row["advisor_name"] == advisor_name]
            lines.append(f"### {advisor_name} -- {len(advisor_rows)} students")
            lines.append("")
            lines.append("| Student | Role | Current Affiliation | Network Status | Evidence |")
            lines.append("|---------|------|---------------------|----------------|----------|")
            for row in advisor_rows:
                network_status = row["existing_network_match"] or "not yet captured"
                evidence = row["source_1_url"] or row["source_2_url"]
                lines.append(
                    f"| {row['student_name']} | {row['relationship_type'] or 'advisor'} | "
                    f"{row['current_affiliation'] or ''} | {network_status} | {evidence} |"
                )
            lines.append("")
    else:
        lines.append("None.")
        lines.append("")

    lines.extend(["## Advisors with No Public Evidence Found", ""])
    if no_evidence_rows:
        for row in no_evidence_rows:
            lines.append(f"- **{row['advisor_name']}** -- {row['notes']}")
    else:
        lines.append("None.")

    lines.extend(["", "## Advisors Still Unresolved", ""])
    if unresolved_rows:
        for row in unresolved_rows:
            lines.append(f"- **{row['advisor_name']}** -- {row['notes']}")
    else:
        lines.append("None.")

    lines.extend(["", "## Recommended Network Additions Now", ""])
    if pending_add_rows:
        for row in pending_add_rows:
            lines.append(f"- {row['advisor_name']}: {row['student_name']} (`{row['recommended_mechanism']}`)")
    else:
        lines.append("None. All currently confirmed students are already captured in the network.")

    lines.extend(["", "## Duplicate-Risk / Existing-Node Findings", ""])
    if captured_rows:
        lines.append(
            f"All {len(captured_rows)} confirmed students currently match unique network nodes. No duplicate-risk conflicts remain in the refreshed findings table."
        )
    else:
        lines.append("No existing-node matches are currently recorded.")

    lines.extend(["", "## Case-by-Case Appendix", ""])
    for row in rows:
        label = row["student_name"] or row["advisor_name"]
        lines.append(f"### {label}")
        lines.append(f"- Advisor: {row['advisor_name']}")
        lines.append(f"- Status: {row['advisor_status']}")
        if row["student_name"]:
            lines.append(f"- Relationship: {row['relationship_type']}")
            lines.append(f"- In network: {row['student_already_in_network'] or 'no'}")
            if row["existing_network_match"]:
                lines.append(f"- Network match: {row['existing_network_match']}")
        if row["source_1_url"]:
            lines.append(f"- Source 1: {row['source_1_url']}")
        if row["source_2_url"]:
            lines.append(f"- Source 2: {row['source_2_url']}")
        if row["notes"]:
            lines.append(f"- Notes: {row['notes']}")
        lines.append("")

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Gen 2 empty-Q12a public-recovery outputs")
    parser.add_argument("--date", required=True, help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--findings", help="Path to recovery findings CSV")
    parser.add_argument("--nodes", help="Path to network nodes CSV")
    args = parser.parse_args()

    date_token = args.date
    findings_path = resolve_path(args.findings, "findings", PROJECT_ROOT / "Data" / "Derived")
    nodes_path = resolve_path(args.nodes, "nodes", PROJECT_ROOT / "Data" / "Derived")

    findings_rows = [sanitize_row(row) for row in load_csv(findings_path)]
    nodes_rows = load_csv(nodes_path)
    enriched_rows = enrich_rows(findings_rows, nodes_rows)

    report_path = findings_path.with_name(f"Gen2_EmptyQ12a_Public_Recovery_Report_{date_token}.md")
    write_csv(findings_path, FIELDNAMES, enriched_rows)
    render_report(report_path, date_token, enriched_rows)

    print(f"Wrote {findings_path.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {report_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
