#!/usr/bin/env python3
"""
Validate the Mokyr survey inputs before computing descriptive statistics.

Outputs:
  Data/Derived/Descriptive_Validation_Coverage_{date}.csv
  Data/Derived/Descriptive_Validation_Generation_{date}.csv
  Data/Derived/Descriptive_Validation_Canon_{date}.csv
  Output/Descriptive_Input_Validation_{date}.md
"""

import argparse
import csv
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from build_network import MANUAL_RESPONDENT_DEDUP

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FILE_PATTERNS = {
    "cleaned": (
        PROJECT_ROOT / "Data" / "Cleaned",
        re.compile(r"^Mokyr_Survey_Responses_(\d{6})_Cleaned\.csv$"),
    ),
    "q12a": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Advisors_and_Reported_Students_(\d{6})\.csv$"),
    ),
    "nodes": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Network_Nodes_(\d{6})\.csv$"),
    ),
    "edges": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Network_Edges_(\d{6})\.csv$"),
    ),
    "unresolved": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Unresolved_Edges_(\d{6})\.csv$"),
    ),
    "manual_nodes": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Manual_Nodes_(\d{6})\.csv$"),
    ),
    "email_recovery": (
        PROJECT_ROOT / "Data" / "Derived",
        re.compile(r"^Email_Recovery_(\d{6})\.csv$"),
    ),
}

PRIMARY_INPUT_LABELS = ["cleaned", "q12a", "nodes", "edges", "unresolved"]
AUXILIARY_INPUT_LABELS = ["manual_nodes", "email_recovery"]
INPUT_LABELS = PRIMARY_INPUT_LABELS + AUXILIARY_INPUT_LABELS
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    return value.replace("\u2019", "'").replace("\u02bc", "'")


def normalize_email(value: str) -> str:
    return normalize_text(value).rstrip(";").strip()


def normalize_name_part(value: str) -> str:
    value = (value or "").strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("\u2019", "'").replace("\u02bc", "'")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = value.replace('"', " ").replace("'", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def person_name_key(first_name: str, last_name: str) -> tuple[str, str]:
    return (normalize_name_part(first_name), normalize_name_part(last_name))


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def extract_date_token(path: Path | None, label: str) -> str:
    if path is None:
        return ""
    _, pattern = FILE_PATTERNS[label]
    match = pattern.match(path.name)
    return match.group(1) if match else ""


def latest_file(label: str) -> Path:
    base_dir, pattern = FILE_PATTERNS[label]
    matches = []
    for path in base_dir.iterdir():
        match = pattern.match(path.name)
        if not match:
            continue
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


def resolve_optional_path(arg_value: str | None) -> Path | None:
    if not arg_value:
        return None
    path = Path(arg_value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def parse_bool(value: str) -> bool:
    return normalize_text(value) in {"true", "1", "yes"}


def tokenize_q11(raw_q11: str) -> list[str]:
    if not raw_q11 or not raw_q11.strip():
        return []
    tokens = re.split(r"\n|;|(?i)\band\b|,", raw_q11)
    return [token.strip() for token in tokens if token.strip()]


def classify_missing_coverage(row: dict, same_name_matches: list[str]) -> str:
    if len(same_name_matches) == 1:
        return "deduped_same_name"
    if len(same_name_matches) > 1:
        return "deduped_ambiguous_same_name"

    q8 = normalize_text(row.get("Q8", ""))
    q11 = row.get("Q11", "").strip()
    q11_tokens = tokenize_q11(q11)

    if not q8 and not q11:
        return "missing_q8_and_q11"
    if "other/i'm not sure" in q8 or "other/ i'm not sure" in q8 or q8.startswith("other/"):
        return "q8_other_or_unsure"
    if "my phd advisor" in q8 and not q11:
        return "direct_advisor_blank_q11"
    if "member of my dissertation committee" in q8 and not q11:
        return "committee_only_blank_q11"
    if len(q11_tokens) >= 2:
        return "multi_advisor_q11"
    if q11:
        return "unmatched_q11_link"
    if "phd advisor of my phd advisor" in q8 or "phd advisor of my advisor's advisor" in q8:
        return "indirect_link_without_q11"
    return "other_missing"


def build_duplicate_candidate_rows(nodes_rows: list[dict], edges_rows: list[dict]) -> tuple[list[dict], dict]:
    respondent_nodes = {
        row["node_id"]: row
        for row in nodes_rows
        if parse_bool(row.get("is_respondent", ""))
    }
    manual_nodes = [
        row for row in nodes_rows
        if row.get("node_id", "").startswith("M-")
    ]

    respondent_name_to_ids = defaultdict(list)
    respondent_email_to_ids = defaultdict(list)
    for node_id, row in respondent_nodes.items():
        respondent_name_to_ids[person_name_key(row.get("first_name", ""), row.get("last_name", ""))].append(node_id)
        email = normalize_email(row.get("email", ""))
        if email:
            respondent_email_to_ids[email].append(node_id)

    incident_edge_counts = Counter()
    root_edge_counts = Counter()
    for edge in edges_rows:
        source_id = edge.get("source_id", "").strip()
        target_id = edge.get("target_id", "").strip()
        if source_id:
            incident_edge_counts[source_id] += 1
        if target_id:
            incident_edge_counts[target_id] += 1
        if source_id == "JM-ROOT" and target_id:
            root_edge_counts[target_id] += 1

    rows = []
    duplicate_manual_nodes = set()
    for manual in manual_nodes:
        reasons_by_respondent = defaultdict(set)
        manual_id = manual["node_id"]
        manual_name_key = person_name_key(manual.get("first_name", ""), manual.get("last_name", ""))
        manual_email = normalize_email(manual.get("email", ""))

        curated_rid = MANUAL_RESPONDENT_DEDUP.get(manual_name_key)
        if curated_rid:
            curated_node_id = f"R-{curated_rid}"
            if curated_node_id in respondent_nodes:
                reasons_by_respondent[curated_node_id].add("curated_match")

        if manual_email:
            for respondent_id in respondent_email_to_ids.get(manual_email, []):
                reasons_by_respondent[respondent_id].add("exact_email")

        for respondent_id in respondent_name_to_ids.get(manual_name_key, []):
            reasons_by_respondent[respondent_id].add("exact_name")

        for respondent_id, reasons in sorted(reasons_by_respondent.items()):
            duplicate_manual_nodes.add(manual_id)
            respondent = respondent_nodes[respondent_id]
            rows.append(
                {
                    "record_type": "duplicate_person_candidate",
                    "response_id": respondent_id.removeprefix("R-"),
                    "node_id": manual_id,
                    "matched_node_id": respondent_id,
                    "first_name": manual.get("first_name", "").strip(),
                    "last_name": manual.get("last_name", "").strip(),
                    "coverage_status": "duplicate_person_candidate",
                    "coverage_reason": "; ".join(sorted(reasons)),
                    "matched_same_name_node_ids": respondent_id,
                    "matched_same_name_count": 1,
                    "advisor_entries_in_q12a": "",
                    "q12": "",
                    "q8": "",
                    "q11": "",
                    "edge_rows_for_node": incident_edge_counts.get(manual_id, 0),
                    "matched_edge_rows": incident_edge_counts.get(respondent_id, 0),
                    "root_edge_rows_for_node": root_edge_counts.get(manual_id, 0),
                    "detail": f"respondent={respondent.get('first_name', '').strip()} {respondent.get('last_name', '').strip()}".strip(),
                    "note": (
                        f"manual_email={manual.get('email', '').strip()}; "
                        f"respondent_email={respondent.get('email', '').strip()}"
                    ),
                }
            )

    summary = {
        "duplicate_person_candidate_count": len(rows),
        "duplicate_manual_node_count": len(duplicate_manual_nodes),
        "duplicate_manual_edge_count": sum(incident_edge_counts.get(node_id, 0) for node_id in duplicate_manual_nodes),
        "duplicate_manual_root_edge_count": sum(root_edge_counts.get(node_id, 0) for node_id in duplicate_manual_nodes),
    }
    return rows, summary


def build_coverage_rows(
    cleaned_rows: list[dict],
    q12a_rows: list[dict],
    nodes_rows: list[dict],
    edges_rows: list[dict],
) -> tuple[list[dict], dict]:
    respondent_nodes = {
        row["node_id"]: row
        for row in nodes_rows
        if parse_bool(row.get("is_respondent", ""))
    }
    respondent_name_to_ids = defaultdict(list)
    for node_id, node in respondent_nodes.items():
        respondent_name_to_ids[person_name_key(node["first_name"], node["last_name"])].append(node_id)

    q12a_advisor_counts = Counter(
        (
            normalize_name_part(row.get("Advisor_FirstName", "")),
            normalize_name_part(row.get("Advisor_LastName", "")),
        )
        for row in q12a_rows
    )

    rows = []
    cleaned_present = 0
    cleaned_missing = 0
    explained_missing = 0
    q12_yes_total = 0
    q12_yes_without_q12a = 0

    for row in cleaned_rows:
        response_id = row.get("ResponseId", "").strip()
        node_id = f"R-{response_id}"
        key = person_name_key(row.get("Q1", ""), row.get("Q2", ""))
        same_name_matches = respondent_name_to_ids.get(key, [])
        in_network = node_id in respondent_nodes
        coverage_reason = "matched_response_id" if in_network else classify_missing_coverage(row, same_name_matches)
        if in_network:
            cleaned_present += 1
        else:
            cleaned_missing += 1
            if coverage_reason.startswith("deduped_"):
                explained_missing += 1

        advisor_entries_in_q12a = q12a_advisor_counts.get(key, 0)
        q12_yes = normalize_text(row.get("Q12", "")) == "yes"
        if q12_yes:
            q12_yes_total += 1
            if advisor_entries_in_q12a == 0:
                q12_yes_without_q12a += 1

        rows.append(
            {
                "record_type": "cleaned_respondent",
                "response_id": response_id,
                "node_id": node_id if in_network else "",
                "matched_node_id": "",
                "first_name": row.get("Q1", "").strip(),
                "last_name": row.get("Q2", "").strip(),
                "coverage_status": "present_in_network" if in_network else "missing_from_network",
                "coverage_reason": coverage_reason,
                "matched_same_name_node_ids": "; ".join(same_name_matches),
                "matched_same_name_count": len(same_name_matches),
                "advisor_entries_in_q12a": advisor_entries_in_q12a,
                "q12": row.get("Q12", "").strip(),
                "q8": row.get("Q8", "").strip(),
                "q11": row.get("Q11", "").strip(),
                "edge_rows_for_node": "",
                "matched_edge_rows": "",
                "root_edge_rows_for_node": "",
                "detail": "",
                "note": "",
            }
        )

    q12a_orphan_count = 0
    for (first_name, last_name), advisor_rows in sorted(q12a_advisor_counts.items()):
        if not first_name and not last_name:
            continue
        node_ids = respondent_name_to_ids.get((first_name, last_name), [])
        matched = bool(node_ids)
        if not matched:
            q12a_orphan_count += 1
        rows.append(
            {
                "record_type": "q12a_advisor",
                "response_id": "",
                "node_id": "; ".join(node_ids),
                "matched_node_id": "",
                "first_name": first_name,
                "last_name": last_name,
                "coverage_status": "matched_respondent" if matched else "orphan_q12a_advisor",
                "coverage_reason": "matched_by_name" if matched else "advisor_not_in_respondent_nodes",
                "matched_same_name_node_ids": "; ".join(node_ids),
                "matched_same_name_count": len(node_ids),
                "advisor_entries_in_q12a": advisor_rows,
                "q12": "",
                "q8": "",
                "q11": "",
                "edge_rows_for_node": "",
                "matched_edge_rows": "",
                "root_edge_rows_for_node": "",
                "detail": "",
                "note": "",
            }
        )

    duplicate_rows, duplicate_summary = build_duplicate_candidate_rows(nodes_rows, edges_rows)
    rows.extend(duplicate_rows)

    summary = {
        "cleaned_rows": len(cleaned_rows),
        "network_nodes_total": len(nodes_rows),
        "network_edges_total": len(edges_rows),
        "network_respondent_nodes": len(respondent_nodes),
        "cleaned_present": cleaned_present,
        "cleaned_missing": cleaned_missing,
        "explained_missing": explained_missing,
        "unexplained_missing": cleaned_missing - explained_missing,
        "q12_yes_total": q12_yes_total,
        "q12_yes_without_q12a": q12_yes_without_q12a,
        "q12a_unique_advisors": len(q12a_advisor_counts),
        "q12a_orphan_advisors": q12a_orphan_count,
        **duplicate_summary,
    }
    rows.sort(
        key=lambda row: (
            {
                "duplicate_person_candidate": 0,
                "cleaned_respondent": 1,
                "q12a_advisor": 2,
            }.get(row["record_type"], 9),
            row["coverage_status"] not in {"missing_from_network", "duplicate_person_candidate", "orphan_q12a_advisor"},
            row["last_name"],
            row["first_name"],
        )
    )
    return rows, summary


def build_generation_rows(
    cleaned_rows: list[dict],
    nodes_rows: list[dict],
    unresolved_rows: list[dict],
) -> tuple[list[dict], dict]:
    cleaned_by_node_id = {
        f"R-{row['ResponseId'].strip()}": row
        for row in cleaned_rows
        if row.get("ResponseId", "").strip()
    }
    node_by_id = {row["node_id"]: row for row in nodes_rows}
    respondent_nodes = [row for row in nodes_rows if parse_bool(row.get("is_respondent", ""))]

    rows = []
    blank_generation_count = 0
    filled_from_topology_count = 0
    topology_overrode_q8_count = 0
    hardcoded_q8_override_count = 0

    for node in respondent_nodes:
        node_id = node["node_id"]
        generation = node.get("generation", "").strip()
        generation_q8 = node.get("generation_q8", "").strip()
        generation_q8_raw = node.get("generation_q8_raw", "").strip()
        cleaned = cleaned_by_node_id.get(node_id, {})

        if generation_q8 != generation_q8_raw:
            hardcoded_q8_override_count += 1
            rows.append(
                {
                    "issue_type": "hardcoded_q8_override",
                    "issue_subtype": "adjusted_from_raw_q8",
                    "priority": "low",
                    "node_id": node_id,
                    "target_id": node_id,
                    "source_id": "",
                    "first_name": node["first_name"],
                    "last_name": node["last_name"],
                    "generation": generation,
                    "generation_q8": generation_q8,
                    "generation_q8_raw": generation_q8_raw,
                    "q8": cleaned.get("Q8", "").strip(),
                    "q11": cleaned.get("Q11", "").strip(),
                    "reason": "",
                    "note": f"raw_q8={generation_q8_raw or 'None'} -> adjusted_q8={generation_q8 or 'None'}",
                }
            )

        if not generation:
            blank_generation_count += 1
            rows.append(
                {
                    "issue_type": "blank_generation",
                    "issue_subtype": "no_final_generation",
                    "priority": "high",
                    "node_id": node_id,
                    "target_id": node_id,
                    "source_id": "",
                    "first_name": node["first_name"],
                    "last_name": node["last_name"],
                    "generation": generation,
                    "generation_q8": generation_q8,
                    "generation_q8_raw": generation_q8_raw,
                    "q8": cleaned.get("Q8", "").strip(),
                    "q11": cleaned.get("Q11", "").strip(),
                    "reason": "",
                    "note": "",
                }
            )
        elif generation != generation_q8:
            if generation_q8:
                issue_subtype = "topology_overrode_q8"
                priority = "medium"
                topology_overrode_q8_count += 1
            else:
                issue_subtype = "filled_from_topology"
                priority = "low"
                filled_from_topology_count += 1

            rows.append(
                {
                    "issue_type": "generation_override",
                    "issue_subtype": issue_subtype,
                    "priority": priority,
                    "node_id": node_id,
                    "target_id": node_id,
                    "source_id": "",
                    "first_name": node["first_name"],
                    "last_name": node["last_name"],
                    "generation": generation,
                    "generation_q8": generation_q8,
                    "generation_q8_raw": generation_q8_raw,
                    "q8": cleaned.get("Q8", "").strip(),
                    "q11": cleaned.get("Q11", "").strip(),
                    "reason": "",
                    "note": "",
                }
            )

    unresolved_reason_counts = Counter()
    unresolved_respondent_linked = 0
    for unresolved in unresolved_rows:
        source_id = unresolved.get("source_id", "").strip()
        target_id = unresolved.get("target_id", "").strip()
        reason = unresolved.get("reason", "").strip()
        unresolved_reason_counts[reason] += 1

        target_node = node_by_id.get(target_id, {})
        source_node = node_by_id.get(source_id, {})
        target_is_respondent = parse_bool(target_node.get("is_respondent", ""))
        source_is_respondent = parse_bool(source_node.get("is_respondent", ""))
        if target_is_respondent or source_is_respondent:
            unresolved_respondent_linked += 1

        rows.append(
            {
                "issue_type": "unresolved_edge",
                "issue_subtype": reason,
                "priority": "high" if target_is_respondent or source_is_respondent else "medium",
                "node_id": target_id or source_id,
                "target_id": target_id,
                "source_id": source_id,
                "first_name": target_node.get("first_name", "") or source_node.get("first_name", ""),
                "last_name": target_node.get("last_name", "") or source_node.get("last_name", ""),
                "generation": target_node.get("generation", ""),
                "generation_q8": target_node.get("generation_q8", ""),
                "generation_q8_raw": target_node.get("generation_q8_raw", ""),
                "q8": cleaned_by_node_id.get(target_id, {}).get("Q8", "").strip(),
                "q11": unresolved.get("raw_q11", "").strip() or cleaned_by_node_id.get(target_id, {}).get("Q11", "").strip(),
                "reason": reason,
                "note": unresolved.get("note", "").strip(),
            }
        )

    rows.sort(
        key=lambda row: (
            PRIORITY_ORDER.get(row["priority"], 9),
            row["issue_type"],
            row["issue_subtype"],
            row["last_name"],
            row["first_name"],
        )
    )
    summary = {
        "blank_generation_count": blank_generation_count,
        "filled_from_topology_count": filled_from_topology_count,
        "topology_overrode_q8_count": topology_overrode_q8_count,
        "hardcoded_q8_override_count": hardcoded_q8_override_count,
        "respondent_nodes": len(respondent_nodes),
        "unresolved_edges_total": len(unresolved_rows),
        "unresolved_edges_respondent_linked": unresolved_respondent_linked,
        "unresolved_reason_counts": unresolved_reason_counts,
    }
    return rows, summary


def build_canon_rows(nodes_rows: list[dict]) -> tuple[list[dict], dict]:
    respondent_nodes = [row for row in nodes_rows if parse_bool(row.get("is_respondent", ""))]
    rows = []
    summary = {}
    field_specs = [
        ("phd_institution", "phd_institution_raw", "phd_institution_canon"),
        ("current_employer", "current_employer_raw", "current_employer_canon"),
    ]

    for field_group, raw_key, canon_key in field_specs:
        nonblank_raw = [row[raw_key].strip() for row in respondent_nodes if row.get(raw_key, "").strip()]
        nonblank_canon = [row[canon_key].strip() for row in respondent_nodes if row.get(canon_key, "").strip()]
        raw_counts = Counter(nonblank_raw)
        canon_counts = Counter(nonblank_canon)
        blank_raw_count = sum(1 for row in respondent_nodes if not row.get(raw_key, "").strip())
        blank_canon_count = sum(1 for row in respondent_nodes if not row.get(canon_key, "").strip())
        unmapped_rows = [
            row for row in respondent_nodes
            if row.get(raw_key, "").strip() and not row.get(canon_key, "").strip()
        ]
        unmapped_counts = Counter(row[raw_key].strip() for row in unmapped_rows)

        summary[field_group] = {
            "unique_raw": len(raw_counts),
            "unique_canon": len(canon_counts),
            "blank_raw_count": blank_raw_count,
            "blank_canon_count": blank_canon_count,
            "unmapped_unique_count": len(unmapped_counts),
            "unmapped_row_count": len(unmapped_rows),
        }

        rows.append(
            {
                "field_group": field_group,
                "row_type": "summary",
                "rank": "",
                "count": len(respondent_nodes),
                "canon_value": "",
                "raw_value": "",
                "node_id": "",
                "person_name": "",
                "status": "respondent_nodes",
                "note": (
                    f"unique_raw={len(raw_counts)}; unique_canon={len(canon_counts)}; "
                    f"blank_raw={blank_raw_count}; blank_canon={blank_canon_count}; "
                    f"unmapped_unique={len(unmapped_counts)}; unmapped_rows={len(unmapped_rows)}"
                ),
            }
        )

        for rank, (canon_value, count) in enumerate(canon_counts.most_common(20), start=1):
            contributor_counts = Counter(
                row[raw_key].strip()
                for row in respondent_nodes
                if row.get(canon_key, "").strip() == canon_value and row.get(raw_key, "").strip()
            )
            top_variants = contributor_counts.most_common(5)
            rows.append(
                {
                    "field_group": field_group,
                    "row_type": "top_canon",
                    "rank": rank,
                    "count": count,
                    "canon_value": canon_value,
                    "raw_value": "",
                    "node_id": "",
                    "person_name": "",
                    "status": "",
                    "note": " | ".join(f"{raw} ({raw_count})" for raw, raw_count in top_variants),
                }
            )
            for raw_value, raw_count in top_variants:
                rows.append(
                    {
                        "field_group": field_group,
                        "row_type": "raw_variant",
                        "rank": rank,
                        "count": raw_count,
                        "canon_value": canon_value,
                        "raw_value": raw_value,
                        "node_id": "",
                        "person_name": "",
                        "status": "",
                        "note": "",
                    }
                )

        for raw_value, count in unmapped_counts.most_common():
            rows.append(
                {
                    "field_group": field_group,
                    "row_type": "unmapped_raw",
                    "rank": "",
                    "count": count,
                    "canon_value": "",
                    "raw_value": raw_value,
                    "node_id": "",
                    "person_name": "",
                    "status": "missing_mapping",
                    "note": "",
                }
            )

        for row in respondent_nodes:
            raw_value = row.get(raw_key, "").strip()
            canon_value = row.get(canon_key, "").strip()
            if canon_value:
                continue
            status = "blank_raw_source" if not raw_value else "missing_mapping"
            rows.append(
                {
                    "field_group": field_group,
                    "row_type": "blank_canon_respondent",
                    "rank": "",
                    "count": "",
                    "canon_value": canon_value,
                    "raw_value": raw_value,
                    "node_id": row["node_id"],
                    "person_name": f"{row['first_name']} {row['last_name']}".strip(),
                    "status": status,
                    "note": "",
                }
            )

    rows.sort(
        key=lambda row: (
            row["field_group"],
            {"summary": 0, "top_canon": 1, "raw_variant": 2, "unmapped_raw": 3, "blank_canon_respondent": 4}.get(row["row_type"], 5),
            int(row["rank"]) if str(row["rank"]).isdigit() else 999,
            -int(row["count"]) if str(row["count"]).isdigit() else 0,
            row["canon_value"],
            row["raw_value"],
            row["person_name"],
        )
    )
    return rows, summary


def summarize_input_dates(input_dates: dict[str, str]) -> dict:
    primary_dates = {input_dates[label] for label in PRIMARY_INPUT_LABELS if input_dates.get(label)}
    baseline = input_dates.get("cleaned", "")
    stale_auxiliary_labels = [
        label for label in AUXILIARY_INPUT_LABELS
        if baseline and input_dates.get(label) and input_dates[label] != baseline
    ]
    return {
        "baseline_date": baseline,
        "primary_dates_aligned": len(primary_dates) <= 1,
        "stale_auxiliary_labels": stale_auxiliary_labels,
    }


def readiness_status(coverage_summary: dict, generation_summary: dict, canon_summary: dict, input_dates: dict) -> dict:
    date_summary = summarize_input_dates(input_dates)

    coverage_status = "PASS"
    if (
        not date_summary["primary_dates_aligned"]
        or coverage_summary["unexplained_missing"] > 0
        or coverage_summary["q12a_orphan_advisors"] > 0
        or coverage_summary["q12_yes_without_q12a"] > 0
        or coverage_summary["duplicate_person_candidate_count"] > 0
        or bool(date_summary["stale_auxiliary_labels"])
    ):
        coverage_status = "WARN"

    generation_status = "PASS"
    if (
        generation_summary["blank_generation_count"] > 0
        or generation_summary["topology_overrode_q8_count"] > 0
        or generation_summary["unresolved_edges_respondent_linked"] > 0
    ):
        generation_status = "WARN"

    canon_status = "PASS"
    canon_issues = any(
        canon_summary[field]["unmapped_row_count"] > 0
        for field in canon_summary
    )
    if canon_issues:
        canon_status = "WARN"

    return {
        "coverage": coverage_status,
        "generation": generation_status,
        "canon": canon_status,
        "overall": "PASS" if {coverage_status, generation_status, canon_status} == {"PASS"} else "WARN",
        "primary_dates_aligned": date_summary["primary_dates_aligned"],
        "stale_auxiliary_labels": date_summary["stale_auxiliary_labels"],
        "baseline_date": date_summary["baseline_date"],
    }


def top_issue_lines(rows: list[dict], limit: int = 5) -> list[str]:
    lines = []
    for row in rows[:limit]:
        person = row.get("person_name", "").strip()
        if not person:
            person = f"{row.get('first_name', '').strip()} {row.get('last_name', '').strip()}".strip()
        detail = (
            row.get("issue_subtype")
            or row.get("status")
            or row.get("reason")
            or row.get("coverage_reason")
            or row.get("detail")
        )
        identifier = row.get("node_id") or row.get("matched_node_id") or row.get("response_id") or row.get("target_id")
        if detail:
            lines.append(f"- {person or identifier}: {detail}")
        else:
            lines.append(f"- {person or identifier}")
    return lines


def write_summary(
    path: Path,
    input_paths: dict[str, Path | None],
    input_dates: dict[str, str],
    coverage_rows: list[dict],
    coverage_summary: dict,
    generation_rows: list[dict],
    generation_summary: dict,
    canon_rows: list[dict],
    canon_summary: dict,
    statuses: dict,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    missing_coverage = [
        row for row in coverage_rows
        if row["record_type"] == "cleaned_respondent" and row["coverage_status"] == "missing_from_network"
    ]
    q12_gap_rows = [
        row for row in coverage_rows
        if row["record_type"] == "cleaned_respondent"
        and normalize_text(row.get("q12", "")) == "yes"
        and str(row.get("advisor_entries_in_q12a", "")) == "0"
    ]
    duplicate_rows = [
        row for row in coverage_rows
        if row["record_type"] == "duplicate_person_candidate"
    ]
    unmapped_phd = [
        row for row in canon_rows
        if row["field_group"] == "phd_institution" and row["row_type"] == "unmapped_raw"
    ]
    unmapped_emp = [
        row for row in canon_rows
        if row["field_group"] == "current_employer" and row["row_type"] == "unmapped_raw"
    ]
    blank_generation_rows = [row for row in generation_rows if row["issue_type"] == "blank_generation"]
    topology_override_rows = [
        row for row in generation_rows
        if row["issue_type"] == "generation_override" and row["issue_subtype"] == "topology_overrode_q8"
    ]
    hardcoded_override_rows = [
        row for row in generation_rows
        if row["issue_type"] == "hardcoded_q8_override"
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("# Descriptive Input Validation\n\n")
        f.write(f"Overall status: **{statuses['overall']}**\n\n")

        f.write("## Inputs\n")
        for label in INPUT_LABELS:
            path_value = input_paths.get(label)
            if path_value is None:
                f.write(f"- {label}: not provided\n")
                continue
            f.write(f"- {label}: `{path_value}`")
            if input_dates.get(label):
                f.write(f" (date `{input_dates[label]}`)")
            f.write("\n")
        f.write("\n")

        f.write(f"## Coverage & Completeness: {statuses['coverage']}\n")
        f.write(
            f"- Cleaned respondents in scope: {coverage_summary['cleaned_rows']}\n"
            f"- Network nodes total: {coverage_summary['network_nodes_total']}\n"
            f"- Network edges total: {coverage_summary['network_edges_total']}\n"
            f"- Network respondent nodes: {coverage_summary['network_respondent_nodes']}\n"
            f"- Missing cleaned respondents from network: {coverage_summary['cleaned_missing']}\n"
            f"- Explained missing respondents: {coverage_summary['explained_missing']}\n"
            f"- Unexplained missing respondents: {coverage_summary['unexplained_missing']}\n"
            f"- Q12=Yes respondents: {coverage_summary['q12_yes_total']}\n"
            f"- Q12=Yes respondents with no Q12a advisor rows: {coverage_summary['q12_yes_without_q12a']}\n"
            f"- Unique Q12a advisors: {coverage_summary['q12a_unique_advisors']}\n"
            f"- Orphan Q12a advisors (no respondent-node name match): {coverage_summary['q12a_orphan_advisors']}\n"
            f"- Duplicate-person candidate pairs: {coverage_summary['duplicate_person_candidate_count']}\n"
            f"- Duplicate manual nodes implicated: {coverage_summary['duplicate_manual_node_count']}\n"
            f"- Edge rows attached to duplicate manual nodes: {coverage_summary['duplicate_manual_edge_count']}\n"
            f"- Root edges attached to duplicate manual nodes: {coverage_summary['duplicate_manual_root_edge_count']}\n"
        )
        if not statuses["primary_dates_aligned"]:
            f.write("- Primary inputs are date-misaligned.\n")
        if statuses["stale_auxiliary_labels"]:
            stale_aux = ", ".join(sorted(statuses["stale_auxiliary_labels"]))
            f.write(f"- Auxiliary inputs older/different than cleaned baseline `{statuses['baseline_date']}`: {stale_aux}\n")
        f.write("\n")
        if duplicate_rows:
            f.write("Duplicate-person candidates to inspect first:\n")
            for line in top_issue_lines(duplicate_rows, limit=8):
                f.write(f"{line}\n")
            f.write("\n")
        if q12_gap_rows:
            f.write("Q12 completeness gaps to inspect first:\n")
            for line in top_issue_lines(q12_gap_rows, limit=8):
                f.write(f"{line}\n")
            f.write("\n")
        if missing_coverage:
            f.write("Coverage issues to inspect first:\n")
            for line in top_issue_lines(missing_coverage, limit=5):
                f.write(f"{line}\n")
            f.write("\n")

        f.write(f"## Generation: {statuses['generation']}\n")
        f.write(
            f"- Respondent nodes audited: {generation_summary['respondent_nodes']}\n"
            f"- Blank respondent generations: {generation_summary['blank_generation_count']}\n"
            f"- Filled from topology: {generation_summary['filled_from_topology_count']}\n"
            f"- Topology overrode Q8: {generation_summary['topology_overrode_q8_count']}\n"
            f"- Hardcoded Q8 adjustments from raw parse: {generation_summary['hardcoded_q8_override_count']}\n"
            f"- Unresolved edges total: {generation_summary['unresolved_edges_total']}\n"
            f"- Unresolved edges linked to respondent nodes: {generation_summary['unresolved_edges_respondent_linked']}\n"
        )
        if generation_summary["hardcoded_q8_override_count"] > 0:
            f.write("- Hardcoded Q8 adjustments are disclosed, but do not by themselves block readiness.\n")
        unresolved_counts = generation_summary["unresolved_reason_counts"]
        if unresolved_counts:
            f.write(f"- Unresolved edge reasons: {dict(unresolved_counts)}\n")
        f.write("\n")
        gen_priority_rows = blank_generation_rows + topology_override_rows
        if gen_priority_rows:
            f.write("Generation issues to inspect first:\n")
            for line in top_issue_lines(gen_priority_rows, limit=10):
                f.write(f"{line}\n")
            f.write("\n")
        if hardcoded_override_rows:
            f.write("Hardcoded Q8 adjustments disclosed:\n")
            for line in top_issue_lines(hardcoded_override_rows, limit=10):
                f.write(f"{line}\n")
            f.write("\n")

        f.write(f"## Canon: {statuses['canon']}\n")
        for field_group in ["phd_institution", "current_employer"]:
            field_summary = canon_summary[field_group]
            f.write(
                f"- {field_group}: unique raw {field_summary['unique_raw']}, "
                f"unique canon {field_summary['unique_canon']}, "
                f"blank raw {field_summary['blank_raw_count']}, "
                f"blank canon {field_summary['blank_canon_count']}, "
                f"unmapped raw values {field_summary['unmapped_unique_count']} "
                f"across {field_summary['unmapped_row_count']} respondent rows\n"
            )
        f.write("\n")
        if unmapped_phd:
            f.write("Unmapped PhD institution values:\n")
            for row in unmapped_phd[:10]:
                f.write(f"- {row['raw_value']} ({row['count']})\n")
            f.write("\n")
        if unmapped_emp:
            f.write("Unmapped employer values:\n")
            for row in unmapped_emp[:10]:
                f.write(f"- {row['raw_value']} ({row['count']})\n")
            f.write("\n")

        f.write("## Recommendation\n")
        if coverage_summary["duplicate_person_candidate_count"] > 0:
            f.write("- Inputs are not ready for whole-tree descriptives until duplicate person-nodes are resolved.\n")
            f.write("- Avoid reporting total nodes, total edges, or subtree sizes from the current network snapshot.\n")
        elif statuses["overall"] == "PASS":
            f.write("- Inputs are aligned enough to begin descriptives.\n")
        else:
            f.write("- Inputs are usable, but coverage, generation, and canon caveats should be disclosed alongside descriptive tables.\n")
            f.write("- Use final `generation` for descriptives, `generation_q8` for pre-topology Q8 lineage, and `generation_q8_raw` for raw-parse audit trail.\n")
            f.write("- Use canonical institution/employer fields for grouped counts and treat unmapped raw values as a recode queue.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Mokyr descriptive-stat inputs")
    parser.add_argument("--cleaned", help="Path to cleaned survey CSV (defaults to latest available)")
    parser.add_argument("--q12a", help="Path to Q12a derived CSV (defaults to latest available)")
    parser.add_argument("--nodes", help="Path to Network_Nodes CSV (defaults to latest available)")
    parser.add_argument("--edges", help="Path to Network_Edges CSV (defaults to latest available)")
    parser.add_argument("--unresolved", help="Path to Unresolved_Edges CSV (defaults to latest available)")
    parser.add_argument("--manual-nodes", help="Path to Manual_Nodes CSV used in the build")
    parser.add_argument("--email-recovery", help="Path to Email_Recovery CSV used in the build")
    parser.add_argument(
        "--output-date",
        help="Date suffix for generated audit files (defaults to cleaned-file date, else today's date)",
    )
    args = parser.parse_args()

    input_paths = {
        "cleaned": resolve_path(args.cleaned, "cleaned"),
        "q12a": resolve_path(args.q12a, "q12a"),
        "nodes": resolve_path(args.nodes, "nodes"),
        "edges": resolve_path(args.edges, "edges"),
        "unresolved": resolve_path(args.unresolved, "unresolved"),
        "manual_nodes": resolve_optional_path(args.manual_nodes),
        "email_recovery": resolve_optional_path(args.email_recovery),
    }
    for label, path in input_paths.items():
        if path is None:
            continue
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    input_dates = {label: extract_date_token(path, label) for label, path in input_paths.items()}
    output_date = args.output_date or input_dates["cleaned"] or datetime.now().strftime("%m%d%y")

    cleaned_rows = load_csv(input_paths["cleaned"])
    q12a_rows = load_csv(input_paths["q12a"])
    nodes_rows = load_csv(input_paths["nodes"])
    edges_rows = load_csv(input_paths["edges"])
    unresolved_rows = load_csv(input_paths["unresolved"])

    coverage_rows, coverage_summary = build_coverage_rows(cleaned_rows, q12a_rows, nodes_rows, edges_rows)
    generation_rows, generation_summary = build_generation_rows(cleaned_rows, nodes_rows, unresolved_rows)
    canon_rows, canon_summary = build_canon_rows(nodes_rows)
    statuses = readiness_status(coverage_summary, generation_summary, canon_summary, input_dates)

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    output_dir = PROJECT_ROOT / "Output"
    coverage_out = derived_dir / f"Descriptive_Validation_Coverage_{output_date}.csv"
    generation_out = derived_dir / f"Descriptive_Validation_Generation_{output_date}.csv"
    canon_out = derived_dir / f"Descriptive_Validation_Canon_{output_date}.csv"
    summary_out = output_dir / f"Descriptive_Input_Validation_{output_date}.md"

    write_csv(
        coverage_out,
        [
            "record_type",
            "response_id",
            "node_id",
            "matched_node_id",
            "first_name",
            "last_name",
            "coverage_status",
            "coverage_reason",
            "matched_same_name_node_ids",
            "matched_same_name_count",
            "advisor_entries_in_q12a",
            "q12",
            "q8",
            "q11",
            "edge_rows_for_node",
            "matched_edge_rows",
            "root_edge_rows_for_node",
            "detail",
            "note",
        ],
        coverage_rows,
    )
    write_csv(
        generation_out,
        [
            "issue_type",
            "issue_subtype",
            "priority",
            "node_id",
            "target_id",
            "source_id",
            "first_name",
            "last_name",
            "generation",
            "generation_q8",
            "generation_q8_raw",
            "q8",
            "q11",
            "reason",
            "note",
        ],
        generation_rows,
    )
    write_csv(
        canon_out,
        [
            "field_group",
            "row_type",
            "rank",
            "count",
            "canon_value",
            "raw_value",
            "node_id",
            "person_name",
            "status",
            "note",
        ],
        canon_rows,
    )
    write_summary(
        summary_out,
        input_paths,
        input_dates,
        coverage_rows,
        coverage_summary,
        generation_rows,
        generation_summary,
        canon_rows,
        canon_summary,
        statuses,
    )

    print(f"Wrote coverage audit: {coverage_out}")
    print(f"Wrote generation audit: {generation_out}")
    print(f"Wrote canon audit: {canon_out}")
    print(f"Wrote summary: {summary_out}")


if __name__ == "__main__":
    main()
