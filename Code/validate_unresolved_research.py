#!/usr/bin/env python3
"""
Validate unresolved-case research findings and report artifacts.

Outputs:
  Data/Derived/Gen1_Unresolved_Research_Validation_{date}.csv
"""

import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FILE_PATTERNS = {
    "findings": re.compile(r"^Gen1_Unresolved_Research_Findings_(\d{6})\.csv$"),
    "report": re.compile(r"^Gen1_Unresolved_Research_Report_(\d{6})\.md$"),
    "nodes": re.compile(r"^Network_Nodes_(\d{6})\.csv$"),
    "master": re.compile(r"^Master_Contact_List_(\d{6})\.csv$"),
}

ALLOWED_RECOMMENDATIONS = {"add", "do_not_add_yet", "unresolved"}
ALLOWED_ADD_MECHANISMS = {"manual_node", "manual_edge", "none"}
ALLOWED_RELATIONSHIP_TYPES = {"advisor", "chair", "co-chair", "unclear", "n/a", ""}
ALLOWED_STABILITY = {"record", "search_result", "supporting_only", "unknown", ""}
WEAK_SOURCE_TYPES = {"math_genealogy", "repec_genealogy", "news_article_naming_haber", ""}

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


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def latest_path(pattern: re.Pattern[str]) -> Path:
    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    matches = []
    for path in derived_dir.iterdir():
        match = pattern.match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        raise FileNotFoundError(f"No files found for pattern {pattern.pattern}")
    matches.sort()
    return matches[-1][1]


def resolve_path(value: str | None, pattern: re.Pattern[str], default_name: str | None = None) -> Path:
    if value:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path
    if default_name:
        path = PROJECT_ROOT / "Data" / "Derived" / default_name
        if path.exists():
            return path
    return latest_path(pattern)


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("\u2019", "'").replace("\u02bc", "'")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def first_name_alias_match(left: str, right: str) -> bool:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if left_norm == right_norm:
        return True
    for group in NICKNAME_GROUPS:
        if left_norm in group and right_norm in group:
            return True
    return False


def split_name_parts(full_name: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"\s+", (full_name or "").strip()) if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def is_search_url(url: str) -> bool:
    return "search_field=" in url or "/catalog?" in url


def has_strong_record_source(row: dict) -> bool:
    for idx in ("1", "2"):
        url = (row.get(f"source_{idx}_url", "") or "").strip()
        source_type = (row.get(f"source_{idx}_type", "") or "").strip().lower()
        stability = (row.get(f"source_{idx}_stability", "") or "").strip().lower()
        if url and stability == "record" and source_type not in WEAK_SOURCE_TYPES:
            return True
    return False


def add_issue(issues: list[dict], severity: str, issue_type: str, detail: str, row: dict | None = None) -> None:
    issue = {
        "severity": severity,
        "issue_type": issue_type,
        "advisor_name": "",
        "candidate_name": "",
        "detail": detail,
    }
    if row:
        issue["advisor_name"] = row.get("advisor_name", "")
        issue["candidate_name"] = row.get("candidate_name", "")
    issues.append(issue)


def parse_report_counts(report_text: str) -> dict[str, int]:
    counts = {}
    patterns = {
        "add": r"^- Recommend ADD now: (\d+)$",
        "hold": r"^- Holdbacks: (\d+)$",
        "unresolved": r"^- Unresolved rows: (\d+)$",
        "branch_no_names": r"^- Advisor branches with `no_public_names_recovered`: (\d+)$",
        "branch_no_students": r"^- Advisor branches with `no_public_students_found`: (\d+)$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, report_text, flags=re.MULTILINE)
        if match:
            counts[key] = int(match.group(1))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate unresolved-case research findings and report artifacts")
    parser.add_argument("--date", help="Date suffix for default input/output paths (MMDDYY)")
    parser.add_argument("--findings", help="Path to findings CSV")
    parser.add_argument("--report", help="Path to markdown report")
    parser.add_argument("--nodes", help="Path to Network_Nodes CSV")
    parser.add_argument("--master", help="Path to Master_Contact_List CSV")
    parser.add_argument("--output", help="Path to validation CSV")
    args = parser.parse_args()

    date_token = args.date
    findings_path = resolve_path(
        args.findings,
        FILE_PATTERNS["findings"],
        f"Gen1_Unresolved_Research_Findings_{date_token}.csv" if date_token else None,
    )
    if not date_token:
        match = FILE_PATTERNS["findings"].match(findings_path.name)
        date_token = match.group(1) if match else datetime.now().strftime("%m%d%y")
    report_path = resolve_path(
        args.report,
        FILE_PATTERNS["report"],
        f"Gen1_Unresolved_Research_Report_{date_token}.md",
    )
    nodes_path = resolve_path(
        args.nodes,
        FILE_PATTERNS["nodes"],
        f"Network_Nodes_{date_token}.csv",
    )
    master_path = resolve_path(
        args.master,
        FILE_PATTERNS["master"],
        f"Master_Contact_List_{date_token}.csv",
    )

    output_path = Path(args.output) if args.output else PROJECT_ROOT / "Data" / "Derived" / f"Gen1_Unresolved_Research_Validation_{date_token}.csv"
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    findings_rows = load_csv(findings_path)
    node_rows = load_csv(nodes_path)
    master_rows = load_csv(master_path)
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""

    issues = []
    record_url_owners = defaultdict(list)

    known_people = []
    for row in node_rows:
        known_people.append(
            {
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "display_name": row.get("display_name", ""),
                "source": "network",
            }
        )
    for row in master_rows:
        known_people.append(
            {
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "display_name": row.get("display_name", ""),
                "source": "master",
            }
        )

    for row in findings_rows:
        recommendation = (row.get("recommendation", "") or "").strip()
        add_mechanism = (row.get("add_mechanism", "") or "").strip()
        relationship_type = (row.get("relationship_type", "") or "").strip()
        case_type = (row.get("case_type", "") or "").strip()
        candidate_name = (row.get("candidate_name", "") or "").strip()
        branch_conclusion = (row.get("branch_conclusion", "") or "").strip()

        if recommendation not in ALLOWED_RECOMMENDATIONS:
            add_issue(issues, "high", "invalid_recommendation", f"Unexpected recommendation={recommendation!r}", row=row)
        if add_mechanism not in ALLOWED_ADD_MECHANISMS:
            add_issue(issues, "high", "invalid_add_mechanism", f"Unexpected add_mechanism={add_mechanism!r}", row=row)
        if relationship_type not in ALLOWED_RELATIONSHIP_TYPES:
            add_issue(issues, "high", "invalid_relationship_type", f"Unexpected relationship_type={relationship_type!r}", row=row)

        if case_type == "advisor_branch" and candidate_name:
            add_issue(issues, "high", "branch_has_candidate", "Advisor-branch rows must have blank candidate_name", row=row)
        if case_type != "advisor_branch" and not candidate_name:
            add_issue(issues, "high", "candidate_missing", "Candidate row is missing candidate_name", row=row)

        for idx in ("1", "2"):
            url = (row.get(f"source_{idx}_url", "") or "").strip()
            stability = (row.get(f"source_{idx}_stability", "") or "").strip().lower()
            if stability not in ALLOWED_STABILITY:
                add_issue(issues, "high", "invalid_source_stability", f"Unexpected source_{idx}_stability={stability!r}", row=row)
            if stability == "record" and url:
                record_url_owners[url].append(row)
            if recommendation == "add" and stability == "search_result":
                add_issue(issues, "high", "search_url_on_add", f"source_{idx} uses search_result stability on an add row", row=row)
            if recommendation == "add" and url and is_search_url(url):
                add_issue(issues, "high", "search_url_on_add", f"source_{idx} URL is a search query, not a stable record URL", row=row)

        if recommendation == "add":
            if add_mechanism not in {"manual_node", "manual_edge"}:
                add_issue(issues, "high", "add_without_mechanism", "Add row must specify manual_node or manual_edge", row=row)
            if not has_strong_record_source(row):
                add_issue(issues, "high", "add_without_record_source", "Add row is missing a strong record-level source", row=row)

        if recommendation != "add" and add_mechanism != "none":
            add_issue(issues, "high", "non_add_with_mechanism", "Non-add rows must use add_mechanism=none", row=row)

        if case_type == "advisor_branch" and recommendation != "unresolved":
            add_issue(issues, "high", "branch_bad_recommendation", "Advisor-branch rows must use recommendation=unresolved", row=row)

        if case_type != "advisor_branch" and branch_conclusion:
            add_issue(issues, "medium", "candidate_has_branch_conclusion", "Candidate rows should not populate branch_conclusion", row=row)

        if recommendation == "add" and candidate_name:
            first_name, last_name = split_name_parts(candidate_name)
            exact_match = False
            alias_match = False
            for person in known_people:
                if normalize_text(last_name) != normalize_text(person["last_name"]):
                    continue
                if normalize_text(first_name) == normalize_text(person["first_name"]):
                    exact_match = True
                    break
                if first_name_alias_match(first_name, person["first_name"]):
                    alias_match = True
            if exact_match:
                add_issue(issues, "high", "duplicate_exact_match", "Add row already exists in the network/master lists", row=row)
            elif alias_match:
                add_issue(issues, "medium", "duplicate_alias_risk", "Add row looks like a nickname/alias of an existing person", row=row)

    for url, owners in record_url_owners.items():
        owner_keys = {
            (row.get("advisor_name", "").strip(), row.get("candidate_name", "").strip(), row.get("case_type", "").strip())
            for row in owners
        }
        if len(owner_keys) > 1:
            for row in owners:
                add_issue(issues, "high", "record_url_reused", f"Stable record URL reused across multiple rows: {url}", row=row)

    if report_text:
        report_counts = parse_report_counts(report_text)
        expected_counts = {
            "add": sum(1 for row in findings_rows if row.get("recommendation") == "add"),
            "hold": sum(1 for row in findings_rows if row.get("recommendation") == "do_not_add_yet"),
            "unresolved": sum(1 for row in findings_rows if row.get("recommendation") == "unresolved"),
            "branch_no_names": sum(1 for row in findings_rows if row.get("branch_conclusion") == "no_public_names_recovered"),
            "branch_no_students": sum(1 for row in findings_rows if row.get("branch_conclusion") == "no_public_students_found"),
        }
        for key, expected in expected_counts.items():
            actual = report_counts.get(key)
            if actual != expected:
                add_issue(issues, "high", "report_count_mismatch", f"Report count for {key} is {actual}; expected {expected}")
    else:
        add_issue(issues, "medium", "missing_report", "Markdown report was not found for validation")

    issue_counts = Counter(issue["severity"] for issue in issues)
    if issue_counts["high"]:
        status = "FAIL"
    elif issue_counts["medium"]:
        status = "WARN"
    else:
        status = "PASS"

    write_csv(
        output_path,
        ["severity", "issue_type", "advisor_name", "candidate_name", "detail"],
        issues,
    )
    print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")
    print(f"Validator status: {status}")
    print(f"Issues: high={issue_counts.get('high', 0)} medium={issue_counts.get('medium', 0)} low={issue_counts.get('low', 0)}")


if __name__ == "__main__":
    main()
