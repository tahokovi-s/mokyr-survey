#!/usr/bin/env python3
"""
Render the unresolved-case research report from the structured findings CSV.

Outputs:
  Data/Derived/Gen1_Unresolved_Research_Report_{date}.md
"""

import argparse
import csv
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FINDINGS_PATTERN = re.compile(r"^Gen1_Unresolved_Research_Findings_(\d{6})\.csv$")


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def latest_findings_path() -> Path:
    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    matches = []
    for path in derived_dir.iterdir():
        match = FINDINGS_PATTERN.match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        raise FileNotFoundError("No Gen1_Unresolved_Research_Findings_*.csv files found under Data/Derived")
    matches.sort()
    return matches[-1][1]


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def source_link(url: str, label: str) -> str:
    url = (url or "").strip()
    label = (label or "").strip().replace("_", " ")
    if not url:
        return ""
    display = label or url
    return f"[{display}]({url})"


def recommend_label(row: dict) -> str:
    rec = row.get("recommendation", "").strip()
    if rec == "add":
        return "ADD"
    if rec == "do_not_add_yet":
        return "HOLD"
    return "UNRESOLVED"


def join_sources(row: dict) -> str:
    parts = []
    for idx in ("1", "2"):
        url = row.get(f"source_{idx}_url", "").strip()
        if not url:
            continue
        source_type = row.get(f"source_{idx}_type", "").strip()
        parts.append(source_link(url, source_type))
    return ", ".join(parts) if parts else "None recorded"


def render_candidate_block(row: dict) -> list[str]:
    lines = [f"### {row['candidate_name']} ({row['advisor_name']})", ""]
    lines.append(f"- Recommendation: `{row['recommendation']}`")
    lines.append(f"- Add mechanism: `{row['add_mechanism']}`")
    lines.append(f"- Relationship type: `{row['relationship_type']}`")
    lines.append(f"- Evidence strength: `{row['evidence_strength']}`")
    lines.append(f"- Confidence: `{row['confidence']}`")
    lines.append(f"- Existing network match: `{row['existing_network_match']}`")
    lines.append(f"- Sources: {join_sources(row)}")
    lines.append(f"- Notes: {row['notes'].strip()}")
    lines.append("")
    return lines


def render_branch_block(row: dict) -> list[str]:
    lines = [f"### {row['advisor_name']}", ""]
    lines.append(f"- Recommendation: `{row['recommendation']}`")
    lines.append(f"- Branch conclusion: `{row['branch_conclusion']}`")
    lines.append(f"- Evidence strength: `{row['evidence_strength']}`")
    lines.append(f"- Confidence: `{row['confidence']}`")
    lines.append(f"- Sources: {join_sources(row)}")
    lines.append(f"- Notes: {row['notes'].strip()}")
    lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the unresolved-case research report from the findings CSV")
    parser.add_argument("--date", help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--findings", help="Path to findings CSV")
    parser.add_argument("--output", help="Path to output markdown report")
    args = parser.parse_args()

    if args.findings:
        findings_path = Path(args.findings)
        if not findings_path.is_absolute():
            findings_path = PROJECT_ROOT / findings_path
    elif args.date:
        findings_path = PROJECT_ROOT / "Data" / "Derived" / f"Gen1_Unresolved_Research_Findings_{args.date}.csv"
    else:
        findings_path = latest_findings_path()

    match = FINDINGS_PATTERN.match(findings_path.name)
    date_token = args.date or (match.group(1) if match else datetime.now().strftime("%m%d%y"))

    output_path = Path(args.output) if args.output else PROJECT_ROOT / "Data" / "Derived" / f"Gen1_Unresolved_Research_Report_{date_token}.md"
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    rows = load_csv(findings_path)
    additions = [row for row in rows if row.get("recommendation") == "add"]
    holdbacks = [row for row in rows if row.get("recommendation") == "do_not_add_yet"]
    unresolved = [row for row in rows if row.get("recommendation") == "unresolved"]
    branches = [row for row in rows if row.get("case_type") == "advisor_branch"]
    branch_conclusions = Counter(row.get("branch_conclusion", "").strip() for row in branches)
    duplicates = [row for row in rows if row.get("existing_network_match", "").strip() not in {"", "none", "n/a"}]

    lines = [
        "# Gen 1 Unresolved Cases — Research Report",
        "",
        f"**Date:** {datetime.strptime(date_token, '%m%d%y').strftime('%Y-%m-%d')}",
        f"**Snapshot:** {date_token}",
        f"**Scope:** {len(rows)} unresolved cases from `Gen1_Unresolved_Research_Findings_{date_token}.csv`",
        "",
        "## Executive Summary",
        "",
        f"- Recommend ADD now: {len(additions)}",
        f"- Holdbacks: {len(holdbacks)}",
        f"- Unresolved rows: {len(unresolved)}",
        f"- Advisor branches with `no_public_names_recovered`: {branch_conclusions.get('no_public_names_recovered', 0)}",
        f"- Advisor branches with `no_public_students_found`: {branch_conclusions.get('no_public_students_found', 0)}",
        "",
        "## Final Additions Recommended Now",
        "",
    ]

    if additions:
        for row in additions:
            lines.extend(render_candidate_block(row))
    else:
        lines.extend(["No additions are currently recommended.", ""])

    lines.extend(["## Cases Not Strong Enough to Add Now", ""])
    if holdbacks:
        for row in holdbacks:
            lines.extend(render_candidate_block(row))
    else:
        lines.extend(["No holdbacks recorded.", ""])

    lines.extend(["## Advisor Branch Outcomes", ""])
    if branches:
        for row in branches:
            lines.extend(render_branch_block(row))
    else:
        lines.extend(["No advisor-branch rows recorded.", ""])

    lines.extend(["## Duplicate-Risk / Existing-Node Findings", ""])
    if duplicates:
        for row in duplicates:
            candidate = row.get("candidate_name", "").strip() or row.get("advisor_name", "").strip()
            lines.append(f"- {candidate}: {row['existing_network_match']}")
    else:
        lines.append("No existing network or master-list matches were recorded in the findings CSV.")
    lines.append("")

    lines.extend(
        [
            "## Case-by-Case Appendix",
            "",
            "| Case | Type | Recommendation | Source 1 | Source 2 |",
            "|---|---|---|---|---|",
        ]
    )
    for row in rows:
        case_name = row.get("candidate_name", "").strip() or row.get("advisor_name", "").strip()
        lines.append(
            "| "
            + " | ".join(
                [
                    case_name,
                    row.get("case_type", "").strip(),
                    recommend_label(row),
                    source_link(row.get("source_1_url", ""), row.get("source_1_type", "")),
                    source_link(row.get("source_2_url", ""), row.get("source_2_type", "")),
                ]
            )
            + " |"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
