#!/usr/bin/env python3
"""
describe_fourth_generation.py -- Descriptive statistics for Mokyr survey
fourth-generation PhD students.

Outputs:
  Data/Derived/Fourth_Generation_Headlines_{date}.csv
  Data/Derived/Fourth_Generation_Subtree_Sizes_{date}.csv
  Data/Derived/Fourth_Generation_Profile_{date}.csv
  Data/Derived/Fourth_Generation_Metadata_Coverage_{date}.csv
  Output/Fourth_Generation_Descriptives_{date}.md

Universes:
  - ALL gen-4: used for network/graph stats AND field distributions
    (excludes only nodes with blank values for each field)
  - RESPONDENT gen-4: used only for has_students (nonrespondent
    has_students=False is a mechanical default, not observed data)
  - Metadata coverage section spans all gen-4 to show backfill impact
"""

import argparse
import csv
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_NODES_DATE_RE = re.compile(r"^Network_Nodes_(\d{6})\.csv$")
_EDGES_DATE_RE = re.compile(r"^Network_Edges_(\d{6})\.csv$")
_COVERAGE_DATE_RE = re.compile(r"^Descriptive_Validation_Coverage_(\d{6})\.csv$")
_GENERATION_DATE_RE = re.compile(r"^Descriptive_Validation_Generation_(\d{6})\.csv$")
_CANON_DATE_RE = re.compile(r"^Descriptive_Validation_Canon_(\d{6})\.csv$")

PHD_YEAR_BINS = [
    ("pre-2026", 0, 2025),
    ("2026-2027", 2026, 2027),
    ("2028-2029", 2028, 2029),
    ("2030+", 2030, 9999),
]

COUNTRY_HARMONIZATION = {
    "United States of America": "United States",
    "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
}


def harmonize_country(raw: str) -> str:
    return COUNTRY_HARMONIZATION.get(raw, raw)


def _format_coverage_cell(count: int, total: int) -> str:
    if total <= 0:
        return f"{count}/{total} (n/a)"
    return f"{count}/{total} ({100 * count / total:.0f}%)"


def _latest_common_date(base_dir: Path, patterns: list[re.Pattern]) -> str | None:
    date_sets = []
    for pattern in patterns:
        matches = set()
        if not base_dir.exists():
            return None
        for path in base_dir.iterdir():
            match = pattern.match(path.name)
            if match:
                matches.add(match.group(1))
        if not matches:
            return None
        date_sets.append(matches)
    common = set.intersection(*date_sets)
    if not common:
        return None
    return max(common, key=lambda token: datetime.strptime(token, "%m%d%y"))


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def build_adjacency(edges: list[dict]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        children[edge["source_id"]].append(edge["target_id"])
    return dict(children)


def descendant_set(
    node_id: str,
    adj: dict[str, list[str]],
    blocked_ids: set[str] | None = None,
) -> set[str]:
    blocked = set(blocked_ids or set()) - {node_id}
    visited: set[str] = set()
    descendants: set[str] = set()
    stack = list(adj.get(node_id, []))

    while stack:
        current = stack.pop()
        if current in visited or current in blocked:
            continue
        visited.add(current)
        descendants.add(current)
        stack.extend(adj.get(current, []))

    return descendants


def build_descendant_summary(focal_nodes: list[dict], adj: dict[str, list[str]]) -> dict:
    focal_ids = {node["node_id"] for node in focal_nodes}
    descendant_sets = {
        node_id: descendant_set(node_id, adj, blocked_ids=focal_ids)
        for node_id in focal_ids
    }
    unique_descendants = set().union(*descendant_sets.values()) if descendant_sets else set()
    summed_descendants = sum(len(descendants) for descendants in descendant_sets.values())
    return {
        "sets": descendant_sets,
        "unique_descendant_count": len(unique_descendants),
        "summed_descendant_count": summed_descendants,
        "subtree_overlap_count": summed_descendants - len(unique_descendants),
    }


def _student_data_status(node: dict, adj: dict[str, list[str]], node_map: dict) -> str:
    """Classify student-data availability for a gen-4 node."""
    if node["is_respondent"] != "True":
        return "non_respondent"
    if node["has_students"] != "True":
        return "q12_no"
    targets = adj.get(node["node_id"], [])
    if not targets:
        return "no_outgoing_edges"
    for target_id in targets:
        target_node = node_map.get(target_id, {})
        generation = target_node.get("generation", "").strip()
        if generation and int(generation) > 4:
            return "has_lower_gen_descendants"
    return "gen4_children_only"


STUDENT_STATUS_LABELS = {
    "non_respondent": "Non-respondent",
    "q12_no": "Q12=No (no students)",
    "no_outgoing_edges": "Q12=Yes, no edges",
    "gen4_children_only": "Q12=Yes, gen-4 children only",
    "has_lower_gen_descendants": "Q12=Yes, gen-5+ descendants",
}


def write_headlines(gen4_all, gen4_resp, gen4_nonresp, descendant_summary, adj, node_map, out_path: Path):
    has_students_yes = sum(1 for node in gen4_resp if node["has_students"] == "True")
    no_outgoing = sum(
        1
        for node in gen4_resp
        if node["has_students"] == "True" and not adj.get(node["node_id"], [])
    )
    gen4_only = sum(
        1
        for node in gen4_resp
        if _student_data_status(node, adj, node_map) == "gen4_children_only"
    )
    has_lower = sum(
        1
        for node in gen4_resp
        if _student_data_status(node, adj, node_map) == "has_lower_gen_descendants"
    )

    rows = [
        {"statistic": "total_fourth_generation", "universe": "all_gen4", "count": len(gen4_all)},
        {"statistic": "respondent_fourth_generation", "universe": "respondent_gen4", "count": len(gen4_resp)},
        {"statistic": "non_respondent_fourth_generation", "universe": "all_gen4", "count": len(gen4_nonresp)},
        {
            "statistic": "gen4_with_descendants",
            "universe": "all_gen4",
            "count": sum(1 for node in gen4_all if node["descendant_count"] > 0),
        },
        {
            "statistic": "gen4_without_descendants",
            "universe": "all_gen4",
            "count": sum(1 for node in gen4_all if node["descendant_count"] == 0),
        },
        {
            "statistic": "unique_descendants_from_gen4",
            "universe": "all_gen4",
            "count": descendant_summary["unique_descendant_count"],
        },
        {
            "statistic": "summed_subtree_sizes",
            "universe": "all_gen4",
            "count": descendant_summary["summed_descendant_count"],
        },
        {
            "statistic": "subtree_overlap",
            "universe": "all_gen4",
            "count": descendant_summary["subtree_overlap_count"],
        },
        {
            "statistic": "respondent_has_students_yes",
            "universe": "respondent_gen4",
            "count": has_students_yes,
        },
        {
            "statistic": "respondent_has_students_no",
            "universe": "respondent_gen4",
            "count": len(gen4_resp) - has_students_yes,
        },
        {
            "statistic": "has_students_no_outgoing_edges",
            "universe": "respondent_gen4",
            "count": no_outgoing,
        },
        {
            "statistic": "has_students_gen4_children_only",
            "universe": "respondent_gen4",
            "count": gen4_only,
        },
        {
            "statistic": "has_students_lower_gen_descendants",
            "universe": "respondent_gen4",
            "count": has_lower,
        },
    ]
    with open(out_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["statistic", "universe", "count"])
        writer.writeheader()
        writer.writerows(rows)


def write_subtree_sizes(gen4_all, adj, node_map, out_path: Path):
    ranked = sorted(gen4_all, key=lambda node: (-node["descendant_count"], node["last_name"], node["first_name"]))
    with open(out_path, "w", newline="") as handle:
        fields = [
            "rank",
            "first_name",
            "last_name",
            "node_id",
            "is_respondent",
            "phd_year",
            "phd_institution_canon",
            "phd_institution_raw",
            "current_employer_canon",
            "current_employer_raw",
            "country",
            "us_state",
            "has_students",
            "student_data_status",
            "descendant_count",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for rank, node in enumerate(ranked, 1):
            writer.writerow(
                {
                    "rank": rank,
                    "first_name": node["first_name"],
                    "last_name": node["last_name"],
                    "node_id": node["node_id"],
                    "is_respondent": node["is_respondent"],
                    "phd_year": node["phd_year"],
                    "phd_institution_canon": node["phd_institution_canon"],
                    "phd_institution_raw": node["phd_institution_raw"],
                    "current_employer_canon": node["current_employer_canon"],
                    "current_employer_raw": node["current_employer_raw"],
                    "country": node["country"],
                    "us_state": node["us_state"],
                    "has_students": node["has_students"],
                    "student_data_status": _student_data_status(node, adj, node_map),
                    "descendant_count": node["descendant_count"],
                }
            )


def write_profile(gen4_all, gen4_resp, out_path: Path):
    rows: list[dict] = []

    def _add(section, label, value, count):
        rows.append({"section": section, "label": label, "value": value, "count": count})

    n_all = len(gen4_all)
    n_resp = len(gen4_resp)

    years = [int(node["phd_year"]) for node in gen4_all if node["phd_year"].strip()]
    if years:
        _add("phd_year", "n_with_year", "", len(years))
        _add("phd_year", "n_total", "", n_all)
        _add("phd_year", "min", "", min(years))
        _add("phd_year", "max", "", max(years))
        _add("phd_year", "median", "", int(statistics.median(years)))
        _add("phd_year", "mean", "", round(statistics.mean(years), 1))
        decade_counts = Counter((year // 10) * 10 for year in years)
        for decade in sorted(decade_counts):
            _add("phd_year", "decade", f"{decade}s", decade_counts[decade])

    institution_counter = Counter(
        node["phd_institution_canon"]
        for node in gen4_all
        if node["phd_institution_canon"].strip()
    )
    _add("phd_institution", "n_with_institution", "", sum(institution_counter.values()))
    _add("phd_institution", "n_total", "", n_all)
    _add("phd_institution", "unique_institutions", "", len(institution_counter))
    for institution, count in institution_counter.most_common():
        _add("phd_institution", "institution", institution, count)

    employer_counter = Counter(
        node["current_employer_canon"]
        for node in gen4_all
        if node["current_employer_canon"].strip()
    )
    employer_blank = sum(1 for node in gen4_all if not node["current_employer_canon"].strip())
    _add("current_employer", "n_with_employer", "", sum(employer_counter.values()))
    _add("current_employer", "n_blank_employer", "", employer_blank)
    _add("current_employer", "n_total", "", n_all)
    _add("current_employer", "unique_employers", "", len(employer_counter))
    for employer, count in employer_counter.most_common():
        _add("current_employer", "employer", employer, count)

    country_counter = Counter(
        harmonize_country(node["country"])
        for node in gen4_all
        if node["country"].strip()
    )
    _add("country", "n_with_country", "", sum(country_counter.values()))
    _add("country", "n_total", "", n_all)
    for country, count in country_counter.most_common():
        _add("country", "country", country, count)

    state_counter = Counter(node["us_state"] for node in gen4_all if node["us_state"].strip())
    _add("us_state", "n_with_state", "", sum(state_counter.values()))
    for state, count in state_counter.most_common():
        _add("us_state", "state", state, count)

    has_students_yes = sum(1 for node in gen4_resp if node["has_students"] == "True")
    _add("has_students", "yes", "", has_students_yes)
    _add("has_students", "no", "", n_resp - has_students_yes)
    _add("has_students", "rate", "", round(has_students_yes / n_resp, 4) if n_resp else 0)
    _add("has_students", "n_respondent", "", n_resp)

    for label, low, high in PHD_YEAR_BINS:
        cohort = [
            node
            for node in gen4_resp
            if node["phd_year"].strip() and low <= int(node["phd_year"]) <= high
        ]
        yes = sum(1 for node in cohort if node["has_students"] == "True")
        _add("has_students_by_cohort", label, "total", len(cohort))
        _add("has_students_by_cohort", label, "has_students", yes)
        _add("has_students_by_cohort", label, "rate", round(yes / len(cohort), 4) if cohort else "n/a")

    with open(out_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["section", "label", "value", "count"])
        writer.writeheader()
        writer.writerows(rows)


def write_metadata_coverage(gen4_all, gen4_resp, gen4_nonresp, out_path: Path):
    fields = [
        "phd_year",
        "phd_institution_canon",
        "phd_institution_raw",
        "current_employer_canon",
        "current_employer_raw",
        "country",
        "us_state",
        "email",
    ]
    rows = []
    for field in fields:
        all_count = sum(1 for node in gen4_all if node.get(field, "").strip())
        respondent_count = sum(1 for node in gen4_resp if node.get(field, "").strip())
        nonrespondent_count = sum(1 for node in gen4_nonresp if node.get(field, "").strip())
        rows.append(
            {
                "field": field,
                "all_gen4": all_count,
                "all_gen4_total": len(gen4_all),
                "respondent": respondent_count,
                "respondent_total": len(gen4_resp),
                "nonrespondent": nonrespondent_count,
                "nonrespondent_total": len(gen4_nonresp),
            }
        )

    with open(out_path, "w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "field",
                "all_gen4",
                "all_gen4_total",
                "respondent",
                "respondent_total",
                "nonrespondent",
                "nonrespondent_total",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def build_validation_summary(coverage_rows, generation_rows, canon_rows):
    return {
        "all_generation_q12_yes_without_q12a": sum(
            1
            for row in coverage_rows
            if row.get("record_type", "") == "cleaned_respondent"
            and row.get("q12", "").strip() == "Yes"
            and str(row.get("advisor_entries_in_q12a", "")).strip() == "0"
        ),
        "unresolved_edges_total": sum(
            1 for row in generation_rows if row.get("issue_type", "") == "unresolved_edge"
        ),
        "blank_generation_count": sum(
            1 for row in generation_rows if row.get("issue_type", "") == "blank_generation"
        ),
        "topology_overrode_q8_count": sum(
            1
            for row in generation_rows
            if row.get("issue_type", "") == "generation_override"
            and row.get("issue_subtype", "") == "topology_overrode_q8"
        ),
        "hardcoded_q8_override_count": sum(
            1 for row in generation_rows if row.get("issue_type", "") == "hardcoded_q8_override"
        ),
        "unmapped_phd_count": sum(
            1
            for row in canon_rows
            if row.get("field_group", "") == "phd_institution"
            and row.get("row_type", "") == "unmapped_raw"
        ),
        "unmapped_employer_count": sum(
            1
            for row in canon_rows
            if row.get("field_group", "") == "current_employer"
            and row.get("row_type", "") == "unmapped_raw"
        ),
    }


def write_markdown(
    gen4_all,
    gen4_resp,
    gen4_nonresp,
    subtree_stats,
    all_nodes,
    descendant_summary,
    validation_summary,
    adj,
    node_map,
    date_token,
    out_path: Path,
):
    lines: list[str] = []

    def _h(level, text):
        lines.append(f"{'#' * level} {text}")

    def _p(text):
        lines.append(text)

    def _blank():
        lines.append("")

    n_all = len(gen4_all)
    n_resp = len(gen4_resp)
    n_nonresp = len(gen4_nonresp)
    has_students_yes = sum(1 for node in gen4_resp if node["has_students"] == "True")
    with_descendants = sum(1 for node in gen4_all if node["descendant_count"] > 0)
    summed_descendants = descendant_summary["summed_descendant_count"]
    unique_descendants = descendant_summary["unique_descendant_count"]

    _h(1, "Fourth-Generation Descriptive Statistics")
    _blank()
    _p(f"Date: `{date_token}`")
    _blank()

    _h(2, "All Fourth-Generation Nodes (Network Universe)")
    _blank()
    _p(f"Universe: all {n_all} generation-4 nodes in `Network_Nodes_{date_token}.csv` (excludes JM-ROOT).")
    _blank()
    _p("| Statistic | Count |")
    _p("|---|---|")
    _p(f"| Total fourth-generation students | {n_all} |")
    _p(f"| Respondents | {n_resp} |")
    _p(f"| Non-respondents | {n_nonresp} |")
    _p(f"| With descendants (subtree > 0) | {with_descendants} |")
    _p(f"| Without descendants | {n_all - with_descendants} |")
    _p(f"| Unique descendants reachable from gen-4 | {unique_descendants} |")
    _p(f"| Sum of per-subtree sizes | {summed_descendants} |")
    _p(f"| Subtree overlap (shared descendants) | {summed_descendants - unique_descendants} |")
    _blank()

    _h(3, "Non-Respondent Fourth-Generation Students")
    _blank()
    coverage_fields = ["phd_year", "phd_institution_canon", "current_employer_canon", "country", "email"]
    _p("| Name | Node ID | Fields Populated |")
    _p("|---|---|---|")
    for node in sorted(gen4_nonresp, key=lambda row: (row["last_name"], row["first_name"])):
        populated = [field for field in coverage_fields if node.get(field, "").strip()]
        field_text = ", ".join(populated) if populated else "(none)"
        _p(f"| {node['first_name']} {node['last_name']} | {node['node_id']} | {field_text} |")
    _blank()

    _h(3, "Subtree Sizes (All Gen-4, Ranked)")
    _blank()
    _p(
        "Descendant counts are **lower bounds** and exclude other generation-4 students "
        "even when cross-gen-4 advising edges exist. Respondents with missing Q12a student "
        "lists and unresolved branches will be understated."
    )
    _blank()
    _p(
        f"**Current snapshot note:** generation 5 is absent at `{date_token}`, so all current "
        "gen-4 nodes are leaf nodes and every subtree size is zero."
    )
    _blank()
    ranked = sorted(gen4_all, key=lambda node: (-node["descendant_count"], node["last_name"], node["first_name"]))
    top = [node for node in ranked if node["descendant_count"] > 0]
    if top:
        _p("| Rank | Name | Descendants | Student Data Status |")
        _p("|---|---|---|---|")
        for rank, node in enumerate(top, 1):
            status = _student_data_status(node, adj, node_map)
            _p(
                f"| {rank} | {node['first_name']} {node['last_name']} | "
                f"{node['descendant_count']} | {STUDENT_STATUS_LABELS.get(status, status)} |"
            )
    else:
        _p("No fourth-generation nodes currently have descendants.")
    _blank()
    _p(
        f"**Summary of subtree sizes (all {n_all} gen-4):** mean={subtree_stats['mean']:.1f}, "
        f"median={subtree_stats['median']:.1f}, min={subtree_stats['min']}, "
        f"max={subtree_stats['max']}, std={subtree_stats['std']:.1f}"
    )
    _blank()

    _h(3, "Student Data Status (Gen-4 Respondents)")
    _blank()
    _p(
        "Gen-4 respondents who reported supervising PhD students (Q12=Yes) are classified "
        "by whether their students appear in the network."
    )
    _blank()
    status_counter = Counter(_student_data_status(node, adj, node_map) for node in gen4_resp)
    _p("| Status | Count | Description |")
    _p("|---|---|---|")
    for status_key in ["q12_no", "no_outgoing_edges", "gen4_children_only", "has_lower_gen_descendants"]:
        _p(f"| {STUDENT_STATUS_LABELS[status_key]} | {status_counter.get(status_key, 0)} | |")
    _blank()

    censored = [
        node
        for node in gen4_resp
        if _student_data_status(node, adj, node_map) == "no_outgoing_edges"
    ]
    if censored:
        _p(
            f"**Q12a-censored gen-4 respondents ({len(censored)}):** these respondents reported "
            "supervising PhD students (Q12=Yes) but have no student edges in the network. "
            "Their subtree counts are mechanically zero."
        )
        for node in sorted(censored, key=lambda row: (row["last_name"], row["first_name"])):
            _p(f"- {node['first_name']} {node['last_name']}")
        _blank()

    gen4_only = [
        node
        for node in gen4_resp
        if _student_data_status(node, adj, node_map) == "gen4_children_only"
    ]
    if gen4_only:
        _p(
            f"**Gen-4 children only ({len(gen4_only)}):** these respondents have outgoing "
            "student edges, but all targets are also generation-4 nodes (co-advised peers). "
            "Their subtrees are zero after blocking same-generation traversal."
        )
        for node in sorted(gen4_only, key=lambda row: (row["last_name"], row["first_name"])):
            targets = adj.get(node["node_id"], [])
            target_names = sorted(
                {
                    f"{node_map.get(target_id, {}).get('first_name', '?')} "
                    f"{node_map.get(target_id, {}).get('last_name', '?')}"
                    for target_id in targets
                }
            )
            _p(f"- {node['first_name']} {node['last_name']} -> {', '.join(target_names)}")
        _blank()

    gen_counter = Counter(node["generation"] for node in all_nodes if node["node_id"] != "JM-ROOT")
    max_generation = max((int(gen) for gen in gen_counter if gen.strip()), default=0)
    _h(3, "Tree Shape")
    _blank()
    _p("| Generation | Nodes |")
    _p("|---|---|")
    for generation in sorted(gen_counter, key=lambda value: (value == "", int(value) if value else 999)):
        label = f"Gen {generation}" if generation.strip() else "Unassigned"
        _p(f"| {label} | {gen_counter[generation]} |")
    _p(f"| **Total (excl. root)** | **{sum(gen_counter.values())}** |")
    _blank()
    _p(f"Maximum generation depth: {max_generation}")
    _blank()

    _h(2, "Metadata Coverage (All Gen-4)")
    _blank()
    _p(
        f"Field coverage across all {n_all} gen-4 nodes. Respondent fields come from the "
        "Qualtrics survey. Non-respondent fields reflect approved Gen 4 backfill when "
        "available; otherwise they remain blank in the node CSV."
    )
    _blank()
    coverage_fields_full = [
        ("phd_year", "PhD year"),
        ("phd_institution_canon", "PhD institution (canon)"),
        ("current_employer_canon", "Current employer (canon)"),
        ("country", "Country"),
        ("us_state", "US state"),
        ("email", "Email"),
    ]
    _p("| Field | All Gen-4 | Respondent | Non-respondent |")
    _p("|---|---|---|---|")
    for field, label in coverage_fields_full:
        all_count = sum(1 for node in gen4_all if node.get(field, "").strip())
        respondent_count = sum(1 for node in gen4_resp if node.get(field, "").strip())
        nonrespondent_count = sum(1 for node in gen4_nonresp if node.get(field, "").strip())
        _p(
            f"| {label} | {_format_coverage_cell(all_count, n_all)} "
            f"| {_format_coverage_cell(respondent_count, n_resp)} "
            f"| {_format_coverage_cell(nonrespondent_count, n_nonresp)} |"
        )
    _blank()

    _h(2, "Fourth-Generation Distributions")
    _blank()
    _p(
        f"Statistics use all {n_all} gen-4 nodes with nonblank values for each field "
        "(includes backfilled nonrespondents when present). Has-students uses respondent-only "
        f"data (N={n_resp}) because nonrespondent has_students values are mechanical defaults, "
        "not survey answers."
    )
    _blank()

    years = [int(node["phd_year"]) for node in gen4_all if node["phd_year"].strip()]
    _h(3, "PhD Year Distribution")
    _blank()
    if years:
        _p(f"- N with year: {len(years)} / {n_all}")
        _p(f"- Range: {min(years)}--{max(years)} (includes expected graduation years)")
        _p(f"- Median: {int(statistics.median(years))}")
        _p(f"- Mean: {statistics.mean(years):.1f}")
        _blank()
        decade_counts = Counter((year // 10) * 10 for year in years)
        _p("| Decade | Count |")
        _p("|---|---|")
        for decade in sorted(decade_counts):
            _p(f"| {decade}s | {decade_counts[decade]} |")
        _blank()
    else:
        _p("No PhD year data available.")
        _blank()

    institution_counter = Counter(
        node["phd_institution_canon"]
        for node in gen4_all
        if node["phd_institution_canon"].strip()
    )
    _h(3, "PhD Institution (Canonical)")
    _blank()
    _p(f"- N with institution: {sum(institution_counter.values())} / {n_all}")
    _p(f"- Unique institutions: {len(institution_counter)}")
    _blank()
    if institution_counter:
        _p("| Institution | Count |")
        _p("|---|---|")
        for institution, count in institution_counter.most_common():
            _p(f"| {institution} | {count} |")
    else:
        _p("No canonical PhD institution data available.")
    _blank()

    employer_counter = Counter(
        node["current_employer_canon"]
        for node in gen4_all
        if node["current_employer_canon"].strip()
    )
    employer_blank = sum(1 for node in gen4_all if not node["current_employer_canon"].strip())
    _h(3, "Current Employer (Canonical)")
    _blank()
    _p(f"- N with employer: {sum(employer_counter.values())} / {n_all}")
    _p(f"- Blank: {employer_blank}")
    _p(f"- Unique employers: {len(employer_counter)}")
    _blank()
    if employer_counter:
        _p("| Employer | Count |")
        _p("|---|---|")
        for employer, count in employer_counter.most_common():
            _p(f"| {employer} | {count} |")
    else:
        _p("No canonical employer data available.")
    _blank()

    country_counter = Counter(
        harmonize_country(node["country"])
        for node in gen4_all
        if node["country"].strip()
    )
    _h(3, "Country")
    _blank()
    _p(f"- N with country: {sum(country_counter.values())} / {n_all}")
    _p("- Country counts are reported using canonical short-form labels (for example, `United States`).")
    _blank()
    if country_counter:
        _p("| Country | Count |")
        _p("|---|---|")
        for country, count in country_counter.most_common():
            _p(f"| {country} | {count} |")
    else:
        _p("No country data available.")
    _blank()

    state_counter = Counter(node["us_state"] for node in gen4_all if node["us_state"].strip())
    _h(3, "US State")
    _blank()
    us_count = sum(
        1 for node in gen4_all if harmonize_country(node["country"].strip()) == "United States"
    )
    _p(f"- US-based gen-4: {us_count}")
    _p(f"- N with state: {sum(state_counter.values())}")
    _blank()
    if state_counter:
        _p("| State | Count |")
        _p("|---|---|")
        for state, count in state_counter.most_common():
            _p(f"| {state} | {count} |")
    else:
        _p("No US state data available.")
    _blank()

    _h(3, "Has Supervised PhD Students (Respondent-Only)")
    _blank()
    _p(
        f"Universe: {n_resp} respondent gen-4 nodes only. Nonrespondent has_students=False is "
        "a mechanical default, not a survey answer."
    )
    _blank()
    if n_resp:
        _p(f"- Yes: {has_students_yes} / {n_resp} ({100 * has_students_yes / n_resp:.1f}%)")
    else:
        _p(f"- Yes: {has_students_yes} / {n_resp}")
    _p(f"- No: {n_resp - has_students_yes} / {n_resp}")
    _blank()
    _p("**Has-students rate by PhD-year cohort** (respondent gen-4 only):")
    _blank()
    _p("| Cohort | N | Has Students | Rate |")
    _p("|---|---|---|---|")
    for label, low, high in PHD_YEAR_BINS:
        cohort = [
            node
            for node in gen4_resp
            if node["phd_year"].strip() and low <= int(node["phd_year"]) <= high
        ]
        yes = sum(1 for node in cohort if node["has_students"] == "True")
        rate = f"{100 * yes / len(cohort):.0f}%" if cohort else "n/a"
        _p(f"| {label} | {len(cohort)} | {yes} | {rate} |")
    _blank()

    _h(2, "Caveats")
    _blank()
    q12a_missing = sum(
        1
        for node in gen4_all
        if _student_data_status(node, adj, node_map) == "no_outgoing_edges"
    )
    gen4_only_count = sum(
        1
        for node in gen4_all
        if _student_data_status(node, adj, node_map) == "gen4_children_only"
    )
    _p(
        f"1. **Subtree counts are lower bounds.** {q12a_missing} gen-4 respondents answered "
        "Q12=Yes but have no student edges in the network (their subtree sizes are mechanically zero). "
        f"{gen4_only_count} additional respondents have outgoing edges only to other gen-4 nodes, "
        "so their subtrees are also zero after same-generation blocking. "
        f"Across all generations, {validation_summary['all_generation_q12_yes_without_q12a']} respondents "
        f"have Q12=Yes without Q12a data. {validation_summary['unresolved_edges_total']} unresolved edges "
        "also reduce coverage."
    )
    overlap = summed_descendants - unique_descendants
    if overlap > 0:
        _p(
            f"2. **Subtree overlap.** {overlap} descendants appear in multiple gen-4 subtrees "
            "(shared advisory relationships). Per-subtree sizes are correct; the sum of per-subtree "
            f"sizes ({summed_descendants}) exceeds unique descendants ({unique_descendants})."
        )
    else:
        _p(
            f"2. **No subtree overlap.** All {unique_descendants} descendants reachable from gen-4 "
            "appear in exactly one subtree. No shared advisory relationships across gen-4 advisors "
            "at the gen-5+ level."
        )
    _p(
        f"3. **This generation is extremely sparse at `{date_token}`.** All {n_all} current gen-4 nodes "
        "are leaves, and generation 5 is absent. Subtree statistics should be interpreted as current-snapshot "
        "placeholders rather than stable lineage measures."
    )
    _p(
        f"4. **Distributions include backfilled nonrespondents when available.** The {n_nonresp} non-respondent "
        "gen-4 nodes may receive metadata from the Gen 4 Nonrespondent Backfill, but until approved backfill "
        "rows exist most nonrespondent fields will remain blank. Has-students remains respondent-only "
        f"(N={n_resp}) because nonrespondent has_students=False is a mechanical default."
    )
    _p(
        "5. **Country values should now be canonical in the node CSV.** This script retains a small alias map "
        "as a defensive fallback for older snapshots, but current rebuilds should already use short-form labels "
        "such as `United States` and `United Kingdom`."
    )
    _p(
        f"6. **Canonical institution/employer mappings are incomplete.** {validation_summary['unmapped_phd_count']} "
        f"PhD institution values and {validation_summary['unmapped_employer_count']} employer values lack canonical "
        "mappings. Affected nodes appear as blank in canonical counts but retain raw values in the subtree roster."
    )
    _p(
        f"7. **{validation_summary['blank_generation_count']} respondent nodes have no assigned generation** and are "
        "excluded from all generation-specific counts."
    )
    _p(
        "8. **Generation assignments use topology-corrected values.** "
        f"{validation_summary['topology_overrode_q8_count']} respondents had Q8 overridden by edge topology; "
        f"{validation_summary['hardcoded_q8_override_count']} had hardcoded Q8 adjustments. The `generation` "
        "column reflects final assignments."
    )
    _blank()

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Descriptive statistics for Mokyr fourth-generation students."
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date token (MMDDYY). Default: latest aligned nodes/edges/validation date.",
    )
    parser.add_argument("--nodes", default=None, help="Path to Network_Nodes CSV.")
    parser.add_argument("--edges", default=None, help="Path to Network_Edges CSV.")
    parser.add_argument("--coverage", default=None, help="Path to validation coverage CSV.")
    parser.add_argument("--generation", default=None, help="Path to validation generation CSV.")
    parser.add_argument("--canon", default=None, help="Path to validation canon CSV.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory for CSVs (default: Data/Derived/).",
    )
    parser.add_argument(
        "--md-dir",
        default=None,
        help="Override output directory for markdown (default: Output/).",
    )
    args = parser.parse_args()

    date_token = args.date
    if not date_token:
        derived = PROJECT_ROOT / "Data" / "Derived"
        date_token = _latest_common_date(
            derived,
            [_NODES_DATE_RE, _EDGES_DATE_RE, _COVERAGE_DATE_RE, _GENERATION_DATE_RE, _CANON_DATE_RE],
        )
        if not date_token:
            sys.exit("ERROR: could not find a common dated snapshot across nodes, edges, and validation CSVs.")
    print(f"Date token: {date_token}")

    derived = PROJECT_ROOT / "Data" / "Derived"
    nodes_path = Path(args.nodes) if args.nodes else (derived / f"Network_Nodes_{date_token}.csv")
    edges_path = Path(args.edges) if args.edges else (derived / f"Network_Edges_{date_token}.csv")
    coverage_path = Path(args.coverage) if args.coverage else (derived / f"Descriptive_Validation_Coverage_{date_token}.csv")
    generation_path = Path(args.generation) if args.generation else (derived / f"Descriptive_Validation_Generation_{date_token}.csv")
    canon_path = Path(args.canon) if args.canon else (derived / f"Descriptive_Validation_Canon_{date_token}.csv")

    for path, label in [
        (nodes_path, "nodes"),
        (edges_path, "edges"),
        (coverage_path, "coverage"),
        (generation_path, "generation"),
        (canon_path, "canon"),
    ]:
        if not path.exists():
            sys.exit(f"ERROR: {label} file not found: {path}")

    out_dir = Path(args.output_dir) if args.output_dir else derived
    md_dir = Path(args.md_dir) if args.md_dir else (PROJECT_ROOT / "Output")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    nodes = load_csv(nodes_path)
    edges = load_csv(edges_path)
    coverage_rows = load_csv(coverage_path)
    generation_rows = load_csv(generation_path)
    canon_rows = load_csv(canon_path)
    print(f"Loaded {len(nodes)} nodes, {len(edges)} edges.")

    node_map = {node["node_id"]: node for node in nodes}
    adjacency = build_adjacency(edges)

    gen4_all = [node for node in nodes if node["generation"] == "4" and node["node_id"] != "JM-ROOT"]
    gen4_resp = [node for node in gen4_all if node["is_respondent"] == "True"]
    gen4_nonresp = [node for node in gen4_all if node["is_respondent"] != "True"]
    print(
        f"Gen-4: {len(gen4_all)} total, {len(gen4_resp)} respondent, "
        f"{len(gen4_nonresp)} non-respondent."
    )

    descendant_summary = build_descendant_summary(gen4_all, adjacency)
    for node in gen4_all:
        node["descendant_count"] = len(descendant_summary["sets"][node["node_id"]])

    descendant_counts = [node["descendant_count"] for node in gen4_all]
    if descendant_counts:
        subtree_stats = {
            "mean": statistics.mean(descendant_counts),
            "median": statistics.median(descendant_counts),
            "min": min(descendant_counts),
            "max": max(descendant_counts),
            "std": statistics.stdev(descendant_counts) if len(descendant_counts) > 1 else 0,
        }
    else:
        subtree_stats = {"mean": 0, "median": 0, "min": 0, "max": 0, "std": 0}
    print(
        f"Subtree stats: mean={subtree_stats['mean']:.1f}, "
        f"median={subtree_stats['median']:.1f}, "
        f"min={subtree_stats['min']}, max={subtree_stats['max']}"
    )

    validation_summary = build_validation_summary(coverage_rows, generation_rows, canon_rows)

    headlines_path = out_dir / f"Fourth_Generation_Headlines_{date_token}.csv"
    subtree_path = out_dir / f"Fourth_Generation_Subtree_Sizes_{date_token}.csv"
    profile_path = out_dir / f"Fourth_Generation_Profile_{date_token}.csv"
    coverage_out_path = out_dir / f"Fourth_Generation_Metadata_Coverage_{date_token}.csv"
    md_path = md_dir / f"Fourth_Generation_Descriptives_{date_token}.md"

    write_headlines(gen4_all, gen4_resp, gen4_nonresp, descendant_summary, adjacency, node_map, headlines_path)
    print(f"Wrote {headlines_path.name}")

    write_subtree_sizes(gen4_all, adjacency, node_map, subtree_path)
    print(f"Wrote {subtree_path.name}")

    write_profile(gen4_all, gen4_resp, profile_path)
    print(f"Wrote {profile_path.name}")

    write_metadata_coverage(gen4_all, gen4_resp, gen4_nonresp, coverage_out_path)
    print(f"Wrote {coverage_out_path.name}")

    write_markdown(
        gen4_all,
        gen4_resp,
        gen4_nonresp,
        subtree_stats,
        nodes,
        descendant_summary,
        validation_summary,
        adjacency,
        node_map,
        date_token,
        md_path,
    )
    print(f"Wrote {md_path.name}")

    print("Done.")


if __name__ == "__main__":
    main()
