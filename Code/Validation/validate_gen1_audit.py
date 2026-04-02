#!/usr/bin/env python3
"""
Validate the Gen 1 browser-verification audit and regenerate its summary.

Outputs:
  Data/Derived/Gen1_Student_Verification_Validation_{date}.csv
  Data/Derived/Gen1_Student_Verification_Summary_{date}.txt
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Code"))

from Network.build_network import MANUAL_RESPONDENT_DEDUP

FILE_PATTERNS = {
    "first_generation": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^First_Generation_Subtree_Sizes_(\d{6})\.csv$"),
    ),
    "nodes": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Network_Nodes_(\d{6})\.csv$"),
    ),
    "edges": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Network_Edges_(\d{6})\.csv$"),
    ),
    "audit": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Gen1_Student_Verification_Audit_(\d{6})\.csv$"),
    ),
    "manual_nodes": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Manual_Nodes_(\d{6})\.csv$"),
    ),
    "manual_provenance": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Manual_Node_Provenance_(\d{6})\.csv$"),
    ),
    "manual_edges": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Manual_Edges_(\d{6})\.csv$"),
    ),
}

WEAK_SOURCE_TYPES = {
    "",
    "math_genealogy",
    "repec_genealogy",
    "web_search",
    "repec",
    "web_profile",
}

ALLOWED_STATUSES = {"captured_in_network", "missing_from_network", "needs_manual_review"}
ALLOWED_LINEAGE_BASIS = {"survey_reported", "public_only", "manual_curated", ""}
ALLOWED_PUBLIC_STATUSES = {"confirmed", "not_checked", "not_found", "insufficient", "n/a", ""}
ALLOWED_PATCH_FLAGS = {"yes", "no", "n/a", ""}

NICKNAME_GROUPS = [
    {"jon", "jonathan"},
    {"mike", "michael"},
    {"tom", "thomas"},
    {"chris", "christopher"},
    {"matt", "matthew"},
    {"josh", "joshua"},
    {"nick", "nicholas", "nicolas"},
    {"ben", "benjamin"},
    {"liz", "elizabeth"},
    {"bill", "william"},
]


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes"}


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("\u2019", "'").replace("\u02bc", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def latest_file(label: str) -> Path:
    base_dir, pattern = FILE_PATTERNS[label]
    matches = []
    for path in base_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        raise FileNotFoundError(f"No files found for {label!r} under {base_dir}")
    matches.sort()
    return matches[-1][1]


def resolve_path(arg_value: str | None, label: str) -> Path:
    if arg_value:
        path = Path(arg_value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return latest_file(label)


def normalize_name_key(first_name: str, last_name: str) -> tuple[str, str]:
    return normalize_text(first_name), normalize_text(last_name)


def first_name_alias_match(left: str, right: str) -> bool:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if left_norm == right_norm:
        return True
    for group in NICKNAME_GROUPS:
        if left_norm in group and right_norm in group:
            return True
    return False


def is_patch_eligible(row: dict) -> bool:
    return (row.get("eligible_for_manual_patch", "") or "").strip().lower() == "yes"


def is_strong_source(row: dict) -> bool:
    source_type = (row.get("source_type", "") or "").strip().lower()
    source_url = (row.get("source_url", "") or "").strip()
    return bool(source_url) and source_type not in WEAK_SOURCE_TYPES


def add_issue(issues: list[dict], severity: str, issue_type: str, detail: str, row: dict | None = None, **extra) -> None:
    record = {
        "severity": severity,
        "issue_type": issue_type,
        "advisor_node_id": "",
        "advisor_name": "",
        "node_id": "",
        "student_name": "",
        "detail": detail,
    }
    if row:
        record["advisor_node_id"] = row.get("advisor_node_id", "")
        record["advisor_name"] = row.get("advisor_name", "")
        record["node_id"] = row.get("current_network_node_id", "")
        student_name = f"{row.get('student_first_name', '').strip()} {row.get('student_last_name', '').strip()}".strip()
        record["student_name"] = student_name
    record.update(extra)
    issues.append(record)


def build_summary(
    path: Path,
    date_token: str,
    target_advisors: list[dict],
    captured_children: dict[str, dict[str, set[str]]],
    audit_rows: list[dict],
    issues: list[dict],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    issue_counts = Counter(issue["severity"] for issue in issues)
    status_counts = Counter(row.get("verification_status", "") for row in audit_rows)
    public_counts = Counter(row.get("public_verification_status", "") for row in audit_rows)
    coverage_gap_rows = [issue for issue in issues if issue["issue_type"] == "coverage_missing"]
    advisors_by_id = {row["node_id"]: row for row in target_advisors}
    audit_by_advisor = defaultdict(list)
    for row in audit_rows:
        audit_by_advisor[row["advisor_node_id"]].append(row)

    overall = "PASS"
    if issue_counts["high"]:
        overall = "FAIL"
    elif issue_counts["medium"]:
        overall = "WARN"

    with open(path, "w", encoding="utf-8") as f:
        f.write("Gen 1 Student Verification Audit — Derived Summary\n")
        f.write("=================================================\n")
        f.write(f"Date: {datetime.strptime(date_token, '%m%d%y').strftime('%Y-%m-%d')}\n")
        f.write(f"Snapshot: {date_token}\n")
        f.write(f"Validator status: {overall}\n\n")

        f.write("STATUS COUNTS\n")
        f.write("-------------\n")
        for status in ["captured_in_network", "missing_from_network", "needs_manual_review"]:
            f.write(f"{status}: {status_counts.get(status, 0)}\n")
        f.write("\nPublic verification:\n")
        for status in ["confirmed", "not_checked", "not_found", "insufficient", "n/a"]:
            f.write(f"- {status}: {public_counts.get(status, 0)}\n")
        f.write("\n")

        f.write("VALIDATION RESULTS\n")
        f.write("------------------\n")
        f.write(f"- High-severity issues: {issue_counts.get('high', 0)}\n")
        f.write(f"- Medium-severity issues: {issue_counts.get('medium', 0)}\n")
        f.write(f"- Low-severity issues: {issue_counts.get('low', 0)}\n")
        f.write(f"- Coverage gaps: {len(coverage_gap_rows)}\n\n")

        f.write("ADVISOR COVERAGE\n")
        f.write("---------------\n")
        for advisor in sorted(target_advisors, key=lambda row: row["last_name"]):
            advisor_id = advisor["node_id"]
            advisor_name = f"{advisor['first_name']} {advisor['last_name']}".strip()
            audit_group = audit_by_advisor.get(advisor_id, [])
            captured_count = len(captured_children.get(advisor_id, {}))
            captured_rows = sum(1 for row in audit_group if row.get("current_network_node_id", "").strip())
            missing_count = sum(1 for row in audit_group if row.get("verification_status") == "missing_from_network")
            review_count = sum(1 for row in audit_group if row.get("verification_status") == "needs_manual_review")
            public_confirmed = sum(1 for row in audit_group if row.get("public_verification_status") == "confirmed")
            f.write(
                f"- {advisor_name}: captured children {captured_rows}/{captured_count}, "
                f"publicly confirmed {public_confirmed}, missing_from_network {missing_count}, "
                f"needs_manual_review {review_count}\n"
            )
        f.write("\n")

        if issues:
            f.write("TOP ISSUES\n")
            f.write("----------\n")
            for issue in issues[:20]:
                prefix = issue["severity"].upper()
                who = issue["student_name"] or issue["advisor_name"] or issue["node_id"]
                if who:
                    f.write(f"- [{prefix}] {issue['issue_type']}: {who} — {issue['detail']}\n")
                else:
                    f.write(f"- [{prefix}] {issue['issue_type']}: {issue['detail']}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the Gen 1 browser-verification audit")
    parser.add_argument("--date", help="Date suffix for output files (defaults to audit date)")
    parser.add_argument("--first-generation", help="Path to First_Generation_Subtree_Sizes CSV")
    parser.add_argument("--nodes", help="Path to Network_Nodes CSV")
    parser.add_argument("--edges", help="Path to Network_Edges CSV")
    parser.add_argument("--audit", help="Path to Gen1_Student_Verification_Audit CSV")
    parser.add_argument("--manual-nodes", help="Path to Manual_Nodes CSV")
    parser.add_argument("--manual-provenance", help="Path to Manual_Node_Provenance CSV")
    parser.add_argument("--manual-edges", help="Path to Manual_Edges CSV")
    args = parser.parse_args()

    first_generation_path = resolve_path(args.first_generation, "first_generation")
    nodes_path = resolve_path(args.nodes, "nodes")
    edges_path = resolve_path(args.edges, "edges")
    audit_path = resolve_path(args.audit, "audit")
    manual_nodes_path = resolve_path(args.manual_nodes, "manual_nodes")
    manual_provenance_path = resolve_path(args.manual_provenance, "manual_provenance")
    manual_edges_path = resolve_path(args.manual_edges, "manual_edges")

    date_match = FILE_PATTERNS["audit"][1].match(audit_path.name)
    date_token = args.date or (date_match.group(1) if date_match else datetime.now().strftime("%m%d%y"))

    first_generation_rows = load_csv(first_generation_path)
    nodes_rows = load_csv(nodes_path)
    edges_rows = load_csv(edges_path)
    audit_rows = load_csv(audit_path)
    manual_nodes_rows = load_csv(manual_nodes_path)
    manual_provenance_rows = load_csv(manual_provenance_path)
    manual_edges_rows = load_csv(manual_edges_path)

    nodes_by_id = {row["node_id"]: row for row in nodes_rows}
    target_advisors = [
        row for row in first_generation_rows
        if parse_bool(row.get("is_respondent", "")) and parse_bool(row.get("has_students", ""))
    ]
    target_advisor_ids = {row["node_id"] for row in target_advisors}

    captured_children = defaultdict(lambda: defaultdict(set))
    for edge in edges_rows:
        src = edge.get("source_id", "").strip()
        tgt = edge.get("target_id", "").strip()
        if src in target_advisor_ids and tgt:
            captured_children[src][tgt].add(edge.get("edge_type", "").strip())

    audit_by_pair = defaultdict(list)
    audit_missing_rows = []
    issues = []

    for row in audit_rows:
        status = row.get("verification_status", "")
        lineage_basis = row.get("lineage_basis", "")
        public_status = row.get("public_verification_status", "")
        patch_flag = row.get("eligible_for_manual_patch", "")

        if status not in ALLOWED_STATUSES:
            add_issue(issues, "high", "invalid_status", f"Unexpected verification_status={status!r}", row=row)
        if lineage_basis not in ALLOWED_LINEAGE_BASIS:
            add_issue(issues, "high", "invalid_lineage_basis", f"Unexpected lineage_basis={lineage_basis!r}", row=row)
        if public_status not in ALLOWED_PUBLIC_STATUSES:
            add_issue(issues, "high", "invalid_public_status", f"Unexpected public_verification_status={public_status!r}", row=row)
        if patch_flag not in ALLOWED_PATCH_FLAGS:
            add_issue(issues, "high", "invalid_patch_flag", f"Unexpected eligible_for_manual_patch={patch_flag!r}", row=row)

        current_id = row.get("current_network_node_id", "").strip()
        if current_id:
            audit_by_pair[(row["advisor_node_id"], current_id)].append(row)
            if row.get("verification_status") != "captured_in_network":
                add_issue(
                    issues,
                    "high",
                    "captured_row_bad_status",
                    "Row references an in-network child but is not marked captured_in_network",
                    row=row,
                )
            if row.get("eligible_for_manual_patch") == "yes":
                add_issue(
                    issues,
                    "high",
                    "captured_row_bad_patch_flag",
                    "Captured network child cannot be patch-eligible",
                    row=row,
                )
        else:
            audit_missing_rows.append(row)

        if row.get("public_verification_status") == "confirmed" and not row.get("source_url", "").strip():
            add_issue(
                issues,
                "high",
                "confirmed_without_source",
                "Publicly confirmed row is missing source_url",
                row=row,
            )

        if status == "missing_from_network":
            if is_patch_eligible(row) and not is_strong_source(row):
                add_issue(
                    issues,
                    "high",
                    "weak_patch_evidence",
                    "Patch-eligible missing row does not meet the strong-source requirement",
                    row=row,
                )
            if is_patch_eligible(row) and not row.get("source_url", "").strip():
                add_issue(
                    issues,
                    "high",
                    "patch_missing_source",
                    "Patch-eligible missing row is missing source_url",
                    row=row,
                )

    for advisor in target_advisors:
        advisor_id = advisor["node_id"]
        advisor_name = f"{advisor['first_name']} {advisor['last_name']}".strip()
        for child_id, edge_types in sorted(captured_children.get(advisor_id, {}).items()):
            matched_rows = audit_by_pair.get((advisor_id, child_id), [])
            if not matched_rows:
                node = nodes_by_id[child_id]
                add_issue(
                    issues,
                    "high",
                    "coverage_missing",
                    f"Captured child missing from audit; edge types={'+'.join(sorted(edge_types))}",
                    advisor_node_id=advisor_id,
                    advisor_name=advisor_name,
                    node_id=child_id,
                    student_name=f"{node.get('first_name', '').strip()} {node.get('last_name', '').strip()}".strip(),
                )
            elif len(matched_rows) > 1:
                node = nodes_by_id[child_id]
                add_issue(
                    issues,
                    "high",
                    "duplicate_audit_rows",
                    f"Captured child has {len(matched_rows)} audit rows",
                    advisor_node_id=advisor_id,
                    advisor_name=advisor_name,
                    node_id=child_id,
                    student_name=f"{node.get('first_name', '').strip()} {node.get('last_name', '').strip()}".strip(),
                )

    audit_missing_by_name = defaultdict(list)
    for row in audit_missing_rows:
        key = (
            row.get("advisor_node_id", "").strip(),
            normalize_name_key(row.get("student_first_name", ""), row.get("student_last_name", "")),
        )
        audit_missing_by_name[key].append(row)

    manual_nodes_by_key = defaultdict(list)
    for row in manual_nodes_rows:
        key = (row.get("advisor_source", "").strip(), normalize_name_key(row.get("first_name", ""), row.get("last_name", "")))
        manual_nodes_by_key[key].append(row)

    manual_provenance_by_key = defaultdict(list)
    for row in manual_provenance_rows:
        key = (row.get("advisor_node_id", "").strip(), normalize_name_key(row.get("first_name", ""), row.get("last_name", "")))
        manual_provenance_by_key[key].append(row)

    manual_edge_by_pair = defaultdict(list)
    for row in manual_edges_rows:
        manual_edge_by_pair[(row.get("source_id", "").strip(), row.get("target_id", "").strip())].append(row)
        if not row.get("source_url", "").strip():
            add_issue(
                issues,
                "medium",
                "manual_edge_missing_source",
                "Manual edge is missing source_url",
                advisor_node_id=row.get("source_id", "").strip(),
                node_id=row.get("target_id", "").strip(),
                student_name="",
                advisor_name="",
            )

    for row in audit_missing_rows:
        if not is_patch_eligible(row):
            continue
        advisor_id = row.get("advisor_node_id", "").strip()
        name_key = normalize_name_key(row.get("student_first_name", ""), row.get("student_last_name", ""))
        node_matches = manual_nodes_by_key.get((advisor_id, name_key), [])
        prov_matches = manual_provenance_by_key.get((advisor_id, name_key), [])
        if not node_matches:
            add_issue(
                issues,
                "high",
                "missing_manual_node",
                "Patch-eligible missing row is not present in Manual_Nodes",
                row=row,
            )
        if not prov_matches:
            add_issue(
                issues,
                "high",
                "missing_provenance",
                "Patch-eligible missing row is missing Manual_Node_Provenance",
                row=row,
            )

    respondent_rows = [row for row in nodes_rows if parse_bool(row.get("is_respondent", ""))]
    respondent_name_map = defaultdict(list)
    respondent_email_map = defaultdict(list)
    for row in respondent_rows:
        respondent_name_map[normalize_name_key(row.get("first_name", ""), row.get("last_name", ""))].append(row)
        email = (row.get("email", "") or "").strip().lower()
        if email:
            respondent_email_map[email].append(row)

    for row in manual_nodes_rows:
        manual_key = normalize_name_key(row.get("first_name", ""), row.get("last_name", ""))
        exact_matches = respondent_name_map.get(manual_key, [])
        manual_email = (row.get("email", "") or "").strip().lower()
        email_matches = respondent_email_map.get(manual_email, []) if manual_email else []
        curated_rid = MANUAL_RESPONDENT_DEDUP.get(manual_key)
        curated_match_id = f"R-{curated_rid}" if curated_rid else ""
        resolved_duplicate = bool(exact_matches or email_matches or curated_match_id)

        manual_last = normalize_text(row.get("last_name", ""))
        manual_first = normalize_text(row.get("first_name", ""))
        for respondent in respondent_rows:
            if normalize_text(respondent.get("last_name", "")) != manual_last:
                continue
            if not first_name_alias_match(manual_first, respondent.get("first_name", "")):
                continue
            if normalize_name_key(row.get("first_name", ""), row.get("last_name", "")) == normalize_name_key(
                respondent.get("first_name", ""), respondent.get("last_name", "")
            ):
                continue
            if resolved_duplicate:
                continue
            add_issue(
                issues,
                "high",
                "duplicate_manual_node_alias",
                "Manual node is a likely nickname/alias duplicate of an existing respondent",
                advisor_node_id=row.get("advisor_source", "").strip(),
                student_name=f"{row.get('first_name', '').strip()} {row.get('last_name', '').strip()}".strip(),
                node_id=respondent.get("node_id", ""),
                advisor_name="",
            )

    for row in manual_edges_rows:
        src = row.get("source_id", "").strip()
        tgt = row.get("target_id", "").strip()
        if src not in nodes_by_id or tgt not in nodes_by_id:
            add_issue(
                issues,
                "high",
                "manual_edge_missing_node",
                "Manual edge references a node that is not present in the current network snapshot",
                advisor_node_id=src,
                node_id=tgt,
                student_name="",
                advisor_name="",
            )
            continue
        if tgt not in captured_children.get(src, {}):
            add_issue(
                issues,
                "medium",
                "manual_edge_not_in_network",
                "Manual edge input is not reflected in the current network edges output",
                advisor_node_id=src,
                advisor_name=f"{nodes_by_id[src].get('first_name', '').strip()} {nodes_by_id[src].get('last_name', '').strip()}".strip(),
                node_id=tgt,
                student_name=f"{nodes_by_id[tgt].get('first_name', '').strip()} {nodes_by_id[tgt].get('last_name', '').strip()}".strip(),
            )

    issues.sort(key=lambda row: ({"high": 0, "medium": 1, "low": 2}[row["severity"]], row["issue_type"], row["advisor_name"], row["student_name"]))

    validation_out = PROJECT_ROOT / "Data" / "Derived" / f"Gen1_Student_Verification_Validation_{date_token}.csv"
    summary_out = PROJECT_ROOT / "Data" / "Derived" / f"Gen1_Student_Verification_Summary_{date_token}.txt"

    write_csv(
        validation_out,
        ["severity", "issue_type", "advisor_node_id", "advisor_name", "node_id", "student_name", "detail"],
        issues,
    )
    build_summary(summary_out, date_token, target_advisors, captured_children, audit_rows, issues)

    print(f"Wrote validation report: {validation_out}")
    print(f"Wrote summary: {summary_out}")
    if issues:
        print(f"Validation issues: {len(issues)}")
    else:
        print("Validation issues: 0")


if __name__ == "__main__":
    main()
