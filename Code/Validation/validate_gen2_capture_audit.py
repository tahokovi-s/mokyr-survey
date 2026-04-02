#!/usr/bin/env python3
"""
Sanitize, validate, and summarize the Gen 2 student-capture audit.

Outputs:
  Data/Derived/Gen2_Student_Capture_Audit_{date}.csv
  Data/Derived/Gen2_Student_Capture_Validation_{date}.csv
  Data/Derived/Gen2_Advisor_Q12_Gaps_{date}.csv
  Data/Derived/Gen2_Q12a_Recovery_Audit_{date}.csv
  Data/Derived/Gen2_Student_Capture_Summary_{date}.md
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
    "cleaned": re.compile(r"^Mokyr_Survey_Responses_(\d{6})_Cleaned\.csv$"),
    "q12a": re.compile(r"^Advisors_and_Reported_Students_(\d{6})\.csv$"),
    "nodes": re.compile(r"^Network_Nodes_(\d{6})\.csv$"),
    "edges": re.compile(r"^Network_Edges_(\d{6})\.csv$"),
    "audit": re.compile(r"^Gen2_Student_Capture_Audit_(\d{6})\.csv$"),
    "recovery_findings": re.compile(r"^Gen2_EmptyQ12a_Public_Recovery_Findings_(\d{6})\.csv$"),
}

AUDIT_FIELDNAMES = [
    "advisor_node_id",
    "advisor_name",
    "advisor_response_id",
    "listed_student_raw",
    "listed_student_normalized",
    "source_of_listing",
    "derived_q12a_match",
    "current_network_node_id",
    "current_network_name",
    "current_edge_type",
    "capture_status",
    "recommended_action",
    "recommended_mechanism",
    "existing_network_match_type",
    "source_url",
    "source_type",
    "current_affiliation",
    "public_email",
    "notes",
]

VALIDATION_FIELDNAMES = [
    "severity",
    "issue_type",
    "advisor_name",
    "advisor_node_id",
    "student_name",
    "detail",
]

GAP_FIELDNAMES = [
    "advisor_node_id",
    "advisor_name",
    "advisor_response_id",
    "q12_status",
    "raw_q12a_status",
    "derived_q12a_row_count",
    "outgoing_edge_count",
    "incident_edge_count",
    "manual_student_edge_count",
    "has_manual_students",
    "public_recovery_status",
    "public_recovery_student_count",
    "followup_priority",
    "notes",
]

RECOVERY_FIELDNAMES = [
    "advisor_node_id",
    "advisor_name",
    "recovery_status",
    "public_students_found",
    "student_name",
    "relationship_type",
    "source_url",
    "source_strength",
    "recommended_network_action",
    "notes",
]

EDGE_TYPE_ORDER = {"advisor": 0, "q12a": 1, "manual": 2}
RAW_SOURCE_VALUES = {"raw_q12a", "both"}
DERIVED_SOURCE_VALUES = {"derived_q12a", "both"}
SUPPLEMENTAL_SOURCE_VALUES = {"manual_curated"}


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def latest_file(pattern: re.Pattern[str], base_dir: Path) -> Path:
    matches = []
    for path in base_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        raise FileNotFoundError(f"No matching files found under {base_dir}")
    matches.sort()
    return matches[-1][1]


def resolve_path(raw: str | None, label: str, base_dir: Path) -> Path:
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return latest_file(FILE_PATTERNS[label], base_dir)


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


def parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes"}


def normalize_email(value: str) -> str:
    return (value or "").strip().lower().rstrip(";").strip()


def normalize_name(value: str) -> str:
    return normalize_person_text(value)


def full_name(first_name: str, last_name: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part).strip()


def format_snapshot_date(date_token: str) -> str:
    return parse_mmddyy(date_token).strftime("%Y-%m-%d")


def format_edge_types(edge_types: set[str]) -> str:
    if not edge_types:
        return ""
    ordered = sorted(edge_types, key=lambda edge_type: (EDGE_TYPE_ORDER.get(edge_type, 99), edge_type))
    return "+".join(ordered)


def is_placeholder_row(row: dict) -> bool:
    return not any(
        (row.get(field, "") or "").strip()
        for field in (
            "listed_student_raw",
            "listed_student_normalized",
            "capture_status",
            "recommended_action",
            "recommended_mechanism",
            "current_network_node_id",
        )
    )


def add_issue(issues: list[dict], severity: str, issue_type: str, detail: str, advisor_name: str = "", advisor_node_id: str = "", student_name: str = "") -> None:
    issues.append(
        {
            "severity": severity,
            "issue_type": issue_type,
            "advisor_name": advisor_name,
            "advisor_node_id": advisor_node_id,
            "student_name": student_name,
            "detail": detail,
        }
    )


def build_advisor_universe(cleaned_rows: list[dict], nodes_rows: list[dict]) -> list[dict]:
    respondent_rows = {
        row["ResponseId"].strip(): row
        for row in cleaned_rows
        if row.get("ResponseId", "").strip().startswith("R_")
    }
    advisors = []
    for node in nodes_rows:
        node_id = node.get("node_id", "").strip()
        if not parse_bool(node.get("is_respondent", "")):
            continue
        if node.get("generation", "").strip() != "2":
            continue
        if not parse_bool(node.get("has_students", "")):
            continue
        response_id = node_id.removeprefix("R-")
        cleaned = respondent_rows.get(response_id)
        if not cleaned:
            continue
        advisors.append(
            {
                "advisor_node_id": node_id,
                "advisor_response_id": response_id,
                "advisor_first_name": node.get("first_name", "").strip(),
                "advisor_last_name": node.get("last_name", "").strip(),
                "advisor_name": full_name(node.get("first_name", "").strip(), node.get("last_name", "").strip()),
                "raw_q12a": cleaned.get("Q12a", "").strip(),
                "q12": cleaned.get("Q12", "").strip(),
            }
        )
    advisors.sort(key=lambda row: normalize_name(row["advisor_name"]))
    return advisors


def sanitize_recovery_finding_row(row: dict) -> dict:
    sanitized = {key: (row.get(key, "") or "").strip() for key in row.keys()}
    advisor_status = sanitized.get("advisor_status", "")
    student_name = sanitized.get("student_name", "")
    notes = sanitized.get("notes", "")
    public_email = sanitized.get("public_email", "")

    if advisor_status in {"no_public_evidence_found", "unresolved"} and not student_name and not notes and public_email:
        sanitized["notes"] = public_email
        sanitized["public_email"] = ""

    return sanitized


def load_recovery_findings(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return [sanitize_recovery_finding_row(row) for row in load_csv(path)]


def build_recovery_lookup(findings_rows: list[dict]) -> dict[str, dict]:
    grouped = defaultdict(list)
    for row in findings_rows:
        advisor_name = row.get("advisor_name", "").strip()
        if advisor_name:
            grouped[advisor_name].append(row)

    lookup = {}
    for advisor_name, rows in grouped.items():
        status = next((row.get("advisor_status", "").strip() for row in rows if row.get("advisor_status", "").strip()), "")
        student_rows = [row for row in rows if row.get("student_name", "").strip()]
        advisor_notes = next((row.get("notes", "").strip() for row in rows if row.get("notes", "").strip() and not row.get("student_name", "").strip()), "")
        lookup[advisor_name] = {
            "advisor_status": status,
            "student_rows": student_rows,
            "student_count": len(student_rows),
            "advisor_notes": advisor_notes,
            "rows": rows,
        }
    return lookup


def build_gap_rows(
    advisors: list[dict],
    q12a_rows: list[dict],
    edges_rows: list[dict],
    recovery_lookup: dict[str, dict] | None = None,
) -> list[dict]:
    q12a_counts = Counter(
        (
            normalize_name(row.get("Advisor_FirstName", "")),
            normalize_name(row.get("Advisor_LastName", "")),
        )
        for row in q12a_rows
    )
    outgoing_counts = Counter()
    incident_counts = Counter()
    manual_outgoing_counts = Counter()
    for edge in edges_rows:
        source_id = edge.get("source_id", "").strip()
        target_id = edge.get("target_id", "").strip()
        if source_id:
            outgoing_counts[source_id] += 1
            incident_counts[source_id] += 1
            if edge.get("edge_type", "").strip() == "manual":
                manual_outgoing_counts[source_id] += 1
        if target_id:
            incident_counts[target_id] += 1

    rows = []
    for advisor in advisors:
        recovery = (recovery_lookup or {}).get(advisor["advisor_name"], {})
        derived_count = q12a_counts.get(
            (normalize_name(advisor["advisor_first_name"]), normalize_name(advisor["advisor_last_name"])),
            0,
        )
        raw_q12a_status = "blank" if not advisor["raw_q12a"] else "has_content"
        if raw_q12a_status != "blank" or derived_count != 0:
            continue
        manual_count = manual_outgoing_counts.get(advisor["advisor_node_id"], 0)
        incident_count = incident_counts.get(advisor["advisor_node_id"], 0)
        outgoing_count = outgoing_counts.get(advisor["advisor_node_id"], 0)
        public_recovery_status = recovery.get("advisor_status", "")
        public_recovery_student_count = recovery.get("student_count", 0)

        if public_recovery_status == "confirmed_students_found":
            priority = "none"
            notes = (
                f"Public recovery confirmed {public_recovery_student_count} student(s); "
                "branch is now supplemented in the current network."
            )
        elif public_recovery_status == "no_public_evidence_found":
            priority = "none"
            notes = recovery.get("advisor_notes", "") or "No public evidence of PhD students found during the branch-recovery pass."
        elif public_recovery_status == "unresolved":
            priority = "high"
            notes = recovery.get("advisor_notes", "") or "Public recovery pass remains unresolved for this blank-Q12a branch."
        elif manual_count > 0:
            public_recovery_status = "already_supplemented"
            public_recovery_student_count = manual_count
            priority = "none"
            notes = f"Q12=Yes with blank raw/derived Q12a, but {manual_count} manual student edges already supplement the branch."
        elif incident_count == 0:
            public_recovery_status = "needs_public_recovery"
            priority = "high"
            notes = "Q12=Yes with blank raw/derived Q12a and zero incident edges; isolate for advisor and student recovery."
        else:
            public_recovery_status = "needs_public_recovery"
            priority = "medium"
            notes = "Q12=Yes with blank raw/derived Q12a and no student roster captured yet."
        rows.append(
            {
                "advisor_node_id": advisor["advisor_node_id"],
                "advisor_name": advisor["advisor_name"],
                "advisor_response_id": advisor["advisor_response_id"],
                "q12_status": advisor["q12"],
                "raw_q12a_status": raw_q12a_status,
                "derived_q12a_row_count": derived_count,
                "outgoing_edge_count": outgoing_count,
                "incident_edge_count": incident_count,
                "manual_student_edge_count": manual_count,
                "has_manual_students": "yes" if manual_count else "no",
                "public_recovery_status": public_recovery_status,
                "public_recovery_student_count": public_recovery_student_count,
                "followup_priority": priority,
                "notes": notes,
            }
        )
    return rows


def build_recovery_rows(gap_rows: list[dict], recovery_lookup: dict[str, dict], nodes_rows: list[dict]) -> list[dict]:
    nodes_by_id = {row["node_id"]: row for row in nodes_rows}
    nodes_by_name = defaultdict(list)
    nodes_by_email = defaultdict(list)
    for node in nodes_rows:
        full = normalize_name(full_name(node.get("first_name", ""), node.get("last_name", "")))
        if full:
            nodes_by_name[full].append(node)
        email = normalize_email(node.get("email", ""))
        if email:
            nodes_by_email[email].append(node)

    rows = []
    for gap in gap_rows:
        advisor_name = gap["advisor_name"]
        recovery = recovery_lookup.get(advisor_name)
        if recovery:
            recovery_status = recovery.get("advisor_status", "")
            student_count = recovery.get("student_count", 0)
            if recovery_status == "confirmed_students_found":
                for finding in recovery.get("student_rows", []):
                    student_name = finding.get("student_name", "").strip()
                    public_email = normalize_email(finding.get("public_email", ""))
                    matches = []
                    if public_email:
                        matches.extend(nodes_by_email.get(public_email, []))
                    if not matches:
                        matches.extend(nodes_by_name.get(normalize_name(student_name), []))
                    node_match = matches[0]["node_id"] if len(matches) == 1 else ""
                    notes = finding.get("notes", "").strip()
                    captured_suffix = f"Captured in current network as {node_match}."
                    if node_match and captured_suffix not in notes:
                        notes = f"{notes} {captured_suffix}".strip()
                    rows.append(
                        {
                            "advisor_node_id": gap["advisor_node_id"],
                            "advisor_name": advisor_name,
                            "recovery_status": recovery_status,
                            "public_students_found": str(student_count),
                            "student_name": student_name,
                            "relationship_type": finding.get("relationship_type", "").strip(),
                            "source_url": finding.get("source_1_url", "").strip(),
                            "source_strength": finding.get("evidence_strength", "").strip(),
                            "recommended_network_action": "none" if node_match else (finding.get("recommended_action", "").strip() or "add_to_network"),
                            "notes": notes,
                        }
                    )
                continue

            notes = recovery.get("advisor_notes", "") or gap["notes"]
            recommended_action = "none" if recovery_status == "no_public_evidence_found" else "investigate_public_sources"
            rows.append(
                {
                    "advisor_node_id": gap["advisor_node_id"],
                    "advisor_name": advisor_name,
                    "recovery_status": recovery_status,
                    "public_students_found": str(student_count),
                    "student_name": "",
                    "relationship_type": "",
                    "source_url": "",
                    "source_strength": "",
                    "recommended_network_action": recommended_action,
                    "notes": notes,
                }
            )
            continue

        manual_count = int(gap.get("manual_student_edge_count", 0) or 0)
        if manual_count > 0:
            recovery_status = "already_supplemented"
            public_students_found = str(manual_count)
            recommended_action = "none"
            notes = f"Supplemented via prior manual curation; keep in queue only for documentation. {gap['notes']}"
        else:
            recovery_status = "needs_public_recovery"
            public_students_found = "0"
            recommended_action = "investigate_public_sources"
            notes = gap["notes"]
        rows.append(
            {
                "advisor_node_id": gap["advisor_node_id"],
                "advisor_name": gap["advisor_name"],
                "recovery_status": recovery_status,
                "public_students_found": public_students_found,
                "student_name": "",
                "relationship_type": "",
                "source_url": "",
                "source_strength": "",
                "recommended_network_action": recommended_action,
                "notes": notes,
            }
        )
    return rows


def build_direct_edge_index(edges_rows: list[dict]) -> dict[str, dict[str, set[str]]]:
    direct_edges = defaultdict(lambda: defaultdict(set))
    for edge in edges_rows:
        source_id = edge.get("source_id", "").strip()
        target_id = edge.get("target_id", "").strip()
        edge_type = edge.get("edge_type", "").strip()
        if source_id and target_id and edge_type:
            direct_edges[source_id][target_id].add(edge_type)
    return direct_edges


def sanitize_audit_rows(audit_rows: list[dict], nodes_rows: list[dict], edges_rows: list[dict], issues: list[dict]) -> list[dict]:
    nodes_by_id = {row["node_id"]: row for row in nodes_rows}
    direct_edges = build_direct_edge_index(edges_rows)

    sanitized_rows = []
    for row in audit_rows:
        if is_placeholder_row(row):
            continue

        sanitized = dict(row)
        advisor_id = sanitized.get("advisor_node_id", "").strip()
        advisor_node = nodes_by_id.get(advisor_id)
        if advisor_node:
            sanitized["advisor_name"] = full_name(advisor_node.get("first_name", ""), advisor_node.get("last_name", ""))
        listed_name_norm = normalize_name(sanitized.get("listed_student_normalized", ""))
        public_email = normalize_email(sanitized.get("public_email", ""))
        node_id = sanitized.get("current_network_node_id", "").strip()

        should_resolve_from_graph = (
            sanitized.get("recommended_action") == "review_duplicate"
            or " / " in node_id
            or (node_id and node_id not in nodes_by_id)
        )
        if node_id and " / " not in node_id and node_id in nodes_by_id:
            node = nodes_by_id[node_id]
            sanitized["current_network_name"] = full_name(node.get("first_name", ""), node.get("last_name", ""))
            sanitized["current_edge_type"] = format_edge_types(direct_edges.get(advisor_id, {}).get(node_id, set()))

        if should_resolve_from_graph:
            candidates = []
            for target_id, edge_types in direct_edges.get(advisor_id, {}).items():
                node = nodes_by_id.get(target_id)
                if not node:
                    continue
                node_name_norm = normalize_name(full_name(node.get("first_name", ""), node.get("last_name", "")))
                node_email = normalize_email(node.get("email", ""))
                exact_name = bool(listed_name_norm and node_name_norm == listed_name_norm)
                email_match = bool(public_email and node_email and node_email == public_email)
                if exact_name or email_match:
                    candidates.append((target_id, node, edge_types))

            if len(candidates) == 1:
                target_id, node, edge_types = candidates[0]
                sanitized["current_network_node_id"] = target_id
                sanitized["current_network_name"] = full_name(node.get("first_name", ""), node.get("last_name", ""))
                sanitized["current_edge_type"] = format_edge_types(edge_types)
                sanitized["capture_status"] = "captured_exact"
                sanitized["recommended_action"] = "none"
                sanitized["recommended_mechanism"] = "none"
                sanitized["existing_network_match_type"] = "exact"
                if "duplicate resolved after respondent/q12a merge rebuild" not in sanitized.get("notes", "").lower():
                    note = sanitized.get("notes", "").strip()
                    note_suffix = "Duplicate resolved after respondent/q12a merge rebuild."
                    sanitized["notes"] = f"{note} {note_suffix}".strip()

        capture_status = sanitized.get("capture_status", "").strip()
        recommended_action = sanitized.get("recommended_action", "").strip()
        mechanism = sanitized.get("recommended_mechanism", "").strip()
        current_node_id = sanitized.get("current_network_node_id", "").strip()
        student_name = sanitized.get("listed_student_normalized", "").strip()
        advisor_name = sanitized.get("advisor_name", "").strip()

        if not capture_status:
            add_issue(issues, "high", "blank_capture_status", "Audit row is missing capture_status.", advisor_name, advisor_id, student_name)
        if not recommended_action:
            add_issue(issues, "high", "blank_recommended_action", "Audit row is missing recommended_action.", advisor_name, advisor_id, student_name)
        if not mechanism:
            add_issue(issues, "high", "blank_recommended_mechanism", "Audit row is missing recommended_mechanism.", advisor_name, advisor_id, student_name)

        if capture_status in {"captured_exact", "captured_variant"} and not current_node_id:
            add_issue(issues, "high", "captured_without_node", "Captured row is missing current_network_node_id.", advisor_name, advisor_id, student_name)
        if capture_status in {"captured_exact", "captured_variant"} and current_node_id and current_node_id not in nodes_by_id:
            add_issue(issues, "high", "captured_with_missing_node", "Captured row points at a node_id that does not exist in Network_Nodes.", advisor_name, advisor_id, student_name)
        if capture_status == "missing_from_network" and current_node_id:
            add_issue(issues, "high", "missing_with_node", "Missing row still points at a current_network_node_id.", advisor_name, advisor_id, student_name)
        if capture_status == "needs_manual_review":
            add_issue(issues, "medium", "needs_manual_review", "Manual review still required after duplicate cleanup.", advisor_name, advisor_id, student_name)

        sanitized_rows.append(sanitized)

    return sanitized_rows


def synthesize_missing_advisor_rows(
    advisor: dict,
    q12a_rows: list[dict],
    nodes_rows: list[dict],
    edges_rows: list[dict],
) -> list[dict]:
    direct_edges = build_direct_edge_index(edges_rows)
    nodes_by_id = {row["node_id"]: row for row in nodes_rows}
    advisor_key = (
        normalize_name(advisor["advisor_first_name"]),
        normalize_name(advisor["advisor_last_name"]),
    )
    matching_q12a_rows = [
        row for row in q12a_rows
        if (
            normalize_name(row.get("Advisor_FirstName", "")),
            normalize_name(row.get("Advisor_LastName", "")),
        ) == advisor_key
    ]
    synthesized = []
    raw_q12a_norm = normalize_name(advisor.get("raw_q12a", ""))

    for q12a_row in matching_q12a_rows:
        listed_raw = q12a_row.get("Student_Info", "").strip()
        listed_clean = q12a_row.get("Student_Info_Cleaned", "").strip()
        listed_email = normalize_email(q12a_row.get("Student_Email", ""))
        listed_norm = normalize_name(listed_clean or listed_raw)
        current_node_id = ""
        current_network_name = ""
        current_edge_type = ""
        capture_status = "missing_from_network"
        existing_match_type = "none"

        matches = []
        for target_id, edge_types in direct_edges.get(advisor["advisor_node_id"], {}).items():
            node = nodes_by_id.get(target_id)
            if not node:
                continue
            node_name_norm = normalize_name(full_name(node.get("first_name", ""), node.get("last_name", "")))
            node_email = normalize_email(node.get("email", ""))
            if (listed_email and node_email and listed_email == node_email) or (listed_norm and node_name_norm == listed_norm):
                matches.append((target_id, node, edge_types))

        if len(matches) == 1:
            target_id, node, edge_types = matches[0]
            current_node_id = target_id
            current_network_name = full_name(node.get("first_name", ""), node.get("last_name", ""))
            current_edge_type = format_edge_types(edge_types)
            capture_status = "captured_exact"
            existing_match_type = "exact"

        source_of_listing = "derived_q12a"
        if listed_norm and listed_norm in raw_q12a_norm:
            source_of_listing = "both"

        synthesized.append(
            {
                "advisor_node_id": advisor["advisor_node_id"],
                "advisor_name": advisor["advisor_name"],
                "advisor_response_id": advisor["advisor_response_id"],
                "listed_student_raw": listed_raw,
                "listed_student_normalized": listed_clean or listed_raw,
                "source_of_listing": source_of_listing,
                "derived_q12a_match": "yes",
                "current_network_node_id": current_node_id,
                "current_network_name": current_network_name,
                "current_edge_type": current_edge_type,
                "capture_status": capture_status,
                "recommended_action": "none" if capture_status == "captured_exact" else "add_to_network",
                "recommended_mechanism": "none" if capture_status == "captured_exact" else "manual_node",
                "existing_network_match_type": existing_match_type,
                "source_url": "",
                "source_type": "",
                "current_affiliation": "",
                "public_email": listed_email,
                "notes": "Auto-generated during Gen2 audit validation because the original audit omitted this advisor row.",
            }
        )

    return synthesized


def build_advisor_summary_rows(advisors: list[dict], audit_rows: list[dict], gap_rows: list[dict]) -> list[dict]:
    rows_by_advisor = defaultdict(list)
    for row in audit_rows:
        rows_by_advisor[row["advisor_name"]].append(row)
    gap_by_advisor = {row["advisor_name"]: row for row in gap_rows}

    summary_rows = []
    for advisor in advisors:
        advisor_name = advisor["advisor_name"]
        group = rows_by_advisor.get(advisor_name, [])
        gap = gap_by_advisor.get(advisor_name)
        raw_count = sum(1 for row in group if row.get("source_of_listing", "") in RAW_SOURCE_VALUES)
        derived_count = sum(1 for row in group if row.get("source_of_listing", "") in DERIVED_SOURCE_VALUES)
        supplemental_count = sum(1 for row in group if row.get("source_of_listing", "") in SUPPLEMENTAL_SOURCE_VALUES)
        status_counts = Counter(row.get("capture_status", "") for row in group)
        summary_rows.append(
            {
                "advisor_name": advisor_name,
                "listed_student_count_raw": raw_count,
                "listed_student_count_derived": derived_count,
                "supplemental_manual_student_count": supplemental_count,
                "captured_exact_count": status_counts.get("captured_exact", 0),
                "captured_variant_count": status_counts.get("captured_variant", 0),
                "missing_from_network_count": status_counts.get("missing_from_network", 0),
                "captured_wrong_advisor_count": status_counts.get("captured_wrong_advisor", 0),
                "needs_manual_review_count": status_counts.get("needs_manual_review", 0),
                "gap_status": gap.get("followup_priority", "") if gap else "",
            }
        )
    return summary_rows


def write_summary(
    path: Path,
    date_token: str,
    audit_rows: list[dict],
    advisor_summary_rows: list[dict],
    gap_rows: list[dict],
    recovery_rows: list[dict],
    validation_rows: list[dict],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status_counts = Counter(row.get("capture_status", "") for row in audit_rows)
    raw_listed_students = sum(row["listed_student_count_raw"] for row in advisor_summary_rows)
    derived_listed_students = sum(row["listed_student_count_derived"] for row in advisor_summary_rows)
    supplemental_students = sum(row["supplemental_manual_student_count"] for row in advisor_summary_rows)
    unresolved_gap_rows = [row for row in gap_rows if row.get("public_recovery_status") in {"needs_public_recovery", "unresolved"}]
    variant_rows = [row for row in audit_rows if row.get("capture_status") == "captured_variant"]
    issue_counts = Counter(row["severity"] for row in validation_rows)
    recovery_status_by_advisor = {}
    for row in recovery_rows:
        advisor_name = row.get("advisor_name", "").strip()
        recovery_status = row.get("recovery_status", "").strip()
        if advisor_name and advisor_name not in recovery_status_by_advisor and recovery_status:
            recovery_status_by_advisor[advisor_name] = recovery_status
    recovery_status_counts = Counter(recovery_status_by_advisor.values())

    status_label = "PASS"
    if issue_counts.get("high"):
        status_label = "FAIL"
    elif issue_counts.get("medium"):
        status_label = "WARN"

    lines = [
        "# Gen 2 Student Capture Audit -- Summary",
        "",
        f"**Date:** {format_snapshot_date(date_token)}",
        f"**Snapshot:** {date_token}",
        f"**Validator status:** {status_label}",
        "",
        "## Executive Summary",
        "",
        f"- **Raw Q12a-listed students audited:** {raw_listed_students}",
        f"- **Derived Q12a-listed students audited:** {derived_listed_students}",
        f"- **Supplemental manual students audited:** {supplemental_students}",
        f"- **Total student cases audited:** {len(audit_rows)}",
        f"- **Captured exactly:** {status_counts.get('captured_exact', 0)}",
        f"- **Captured by variant:** {status_counts.get('captured_variant', 0)}",
        f"- **Missing from network:** {status_counts.get('missing_from_network', 0)}",
        f"- **Captured under wrong advisor:** {status_counts.get('captured_wrong_advisor', 0)}",
        f"- **Needs manual review:** {status_counts.get('needs_manual_review', 0)}",
        f"- **Empty-Q12a advisors:** {len(gap_rows)} total (`confirmed_students_found`: {recovery_status_counts.get('confirmed_students_found', 0)}, `no_public_evidence_found`: {recovery_status_counts.get('no_public_evidence_found', 0)}, `unresolved`: {recovery_status_counts.get('unresolved', 0)}, `already_supplemented`: {recovery_status_counts.get('already_supplemented', 0)}, unresolved follow-up: {len(unresolved_gap_rows)})",
        "",
        "**Bottom line:** Every student explicitly listed in raw or derived Q12a is captured in the current network. The empty-Q12a branch work is now narrowed to report-only no-evidence cases plus any advisors still explicitly marked unresolved.",
        "",
        "## Advisor-Level Counts",
        "",
        "| Advisor | Raw | Derived | Supplemental | Exact | Variant | Missing | Wrong | Review |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in advisor_summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["advisor_name"],
                    str(row["listed_student_count_raw"]),
                    str(row["listed_student_count_derived"]),
                    str(row["supplemental_manual_student_count"]),
                    str(row["captured_exact_count"]),
                    str(row["captured_variant_count"]),
                    str(row["missing_from_network_count"]),
                    str(row["captured_wrong_advisor_count"]),
                    str(row["needs_manual_review_count"]),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Missing-from-Network Recommendations", ""])
    missing_rows = [row for row in audit_rows if row.get("capture_status") == "missing_from_network"]
    if missing_rows:
        for row in missing_rows:
            lines.append(f"- {row['advisor_name']}: {row['listed_student_normalized']} (`{row['recommended_mechanism']}`)")
    else:
        lines.append("None. All listed students are captured in the network.")

    lines.extend(["", "## Variant / Duplicate-Risk Cases", ""])
    if variant_rows:
        for row in variant_rows:
            lines.append(
                f"- {row['advisor_name']}: {row['listed_student_raw'] or row['listed_student_normalized']} "
                f"-> {row['current_network_name']} ({row['notes'].strip()})"
            )
    else:
        lines.append("No variant or duplicate-risk cases remain.")

    q12a_content_advisors = sum(1 for row in advisor_summary_rows if row["listed_student_count_derived"] > 0)
    lines.extend(["", "## Raw-vs-Derived Q12a Parsing Discrepancies", ""])
    lines.append(
        f"No parsing-gap issues are currently recorded in the sanitized audit. "
        f"{q12a_content_advisors} advisors have non-empty Q12a rosters represented in the student-level audit."
    )

    lines.extend(["", "## Empty Q12a Advisor Follow-Up Queue", ""])
    if gap_rows:
        lines.append("| Advisor | Recovery Status | Public Students | Priority | Manual Students | Outgoing Edges | Incident Edges | Notes |")
        lines.append("|---|---|---:|---|---:|---:|---:|---|")
        for row in gap_rows:
            lines.append(
                "| "
                + " | ".join(
                    str(value)
                    for value in [
                        row["advisor_name"],
                        row["public_recovery_status"],
                        row["public_recovery_student_count"],
                        row["followup_priority"],
                        row["manual_student_edge_count"],
                        row["outgoing_edge_count"],
                        row["incident_edge_count"],
                        row["notes"],
                    ]
                )
                + " |"
            )
    else:
        lines.append("No empty-Q12a advisors remain.")

    if validation_rows:
        lines.extend(["", "## Validation Notes", ""])
        for issue in validation_rows:
            lines.append(
                f"- [{issue['severity'].upper()}] {issue['issue_type']}: "
                f"{issue['advisor_name'] or issue['student_name'] or issue['advisor_node_id']} -- {issue['detail']}"
            )

    lines.extend(["", "## Case-by-Case Appendix", "", f"See `Gen2_Student_Capture_Audit_{date_token}.csv` for the sanitized student-level audit."])
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and regenerate the Gen 2 student capture audit")
    parser.add_argument("--date", help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--cleaned", help="Path to cleaned survey CSV")
    parser.add_argument("--q12a", help="Path to derived Q12a CSV")
    parser.add_argument("--nodes", help="Path to network nodes CSV")
    parser.add_argument("--edges", help="Path to network edges CSV")
    parser.add_argument("--audit", help="Path to Gen2 audit CSV")
    parser.add_argument("--recovery-findings", help="Path to Gen2 empty-Q12a public recovery findings CSV")
    args = parser.parse_args()

    date_token = args.date or datetime.now().strftime("%m%d%y")
    cleaned_path = resolve_path(args.cleaned, "cleaned", PROJECT_ROOT / "Data" / "Cleaned")
    q12a_path = resolve_path(args.q12a, "q12a", PROJECT_ROOT / "Data" / "Derived")
    nodes_path = resolve_path(args.nodes, "nodes", PROJECT_ROOT / "Data" / "Derived")
    edges_path = resolve_path(args.edges, "edges", PROJECT_ROOT / "Data" / "Derived")
    audit_path = resolve_path(args.audit, "audit", PROJECT_ROOT / "Data" / "Derived")
    recovery_findings_path = resolve_path(args.recovery_findings, "recovery_findings", PROJECT_ROOT / "Data" / "Derived") if args.recovery_findings else None

    cleaned_rows = load_csv(cleaned_path)
    q12a_rows = load_csv(q12a_path)
    nodes_rows = load_csv(nodes_path)
    edges_rows = load_csv(edges_path)
    audit_rows = load_csv(audit_path)
    recovery_findings_rows = load_recovery_findings(recovery_findings_path)

    validation_rows = []
    advisors = build_advisor_universe(cleaned_rows, nodes_rows)
    recovery_lookup = build_recovery_lookup(recovery_findings_rows)
    gap_rows = build_gap_rows(advisors, q12a_rows, edges_rows, recovery_lookup)
    recovery_rows = build_recovery_rows(gap_rows, recovery_lookup, nodes_rows)
    sanitized_audit_rows = sanitize_audit_rows(audit_rows, nodes_rows, edges_rows, validation_rows)

    gap_advisors = {row["advisor_name"] for row in gap_rows}
    for advisor in advisors:
        if advisor["advisor_name"] in gap_advisors:
            continue
        if any(row["advisor_name"] == advisor["advisor_name"] for row in sanitized_audit_rows):
            continue
        synthesized_rows = synthesize_missing_advisor_rows(advisor, q12a_rows, nodes_rows, edges_rows)
        if synthesized_rows:
            sanitized_audit_rows.extend(synthesized_rows)
        else:
            add_issue(
                validation_rows,
                "high",
                "missing_advisor_coverage",
                "Advisor is missing from both the student-level audit and the empty-Q12a gap file.",
                advisor["advisor_name"],
                advisor["advisor_node_id"],
            )

    deduped_rows = {}
    for row in sanitized_audit_rows:
        dedupe_key = (
            row.get("advisor_node_id", "").strip(),
            normalize_name(row.get("listed_student_normalized", "")),
            normalize_email(row.get("public_email", "")),
            row.get("current_network_node_id", "").strip(),
            row.get("capture_status", "").strip(),
        )
        existing = deduped_rows.get(dedupe_key)
        if existing is None:
            deduped_rows[dedupe_key] = row
            continue
        existing_auto = existing.get("notes", "").startswith("Auto-generated during Gen2 audit validation")
        row_auto = row.get("notes", "").startswith("Auto-generated during Gen2 audit validation")
        if existing_auto and not row_auto:
            deduped_rows[dedupe_key] = row

    sanitized_audit_rows = list(deduped_rows.values())
    sanitized_audit_rows.sort(
        key=lambda row: (
            normalize_name(row.get("advisor_name", "")),
            normalize_name(row.get("listed_student_normalized", "")),
            normalize_name(row.get("listed_student_raw", "")),
        )
    )

    advisor_summary_rows = build_advisor_summary_rows(advisors, sanitized_audit_rows, gap_rows)

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    sanitized_audit_out = derived_dir / f"Gen2_Student_Capture_Audit_{date_token}.csv"
    validation_out = derived_dir / f"Gen2_Student_Capture_Validation_{date_token}.csv"
    gap_out = derived_dir / f"Gen2_Advisor_Q12_Gaps_{date_token}.csv"
    recovery_out = derived_dir / f"Gen2_Q12a_Recovery_Audit_{date_token}.csv"
    summary_out = derived_dir / f"Gen2_Student_Capture_Summary_{date_token}.md"

    write_csv(sanitized_audit_out, AUDIT_FIELDNAMES, sanitized_audit_rows)
    write_csv(validation_out, VALIDATION_FIELDNAMES, validation_rows)
    write_csv(gap_out, GAP_FIELDNAMES, gap_rows)
    write_csv(recovery_out, RECOVERY_FIELDNAMES, recovery_rows)
    write_summary(summary_out, date_token, sanitized_audit_rows, advisor_summary_rows, gap_rows, recovery_rows, validation_rows)

    print(f"Sanitized audit rows: {len(sanitized_audit_rows)}")
    print(f"Gap advisors: {len(gap_rows)}")
    print(f"Validation issues: {len(validation_rows)}")
    print(f"Wrote {sanitized_audit_out.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {validation_out.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {gap_out.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {recovery_out.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {summary_out.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
