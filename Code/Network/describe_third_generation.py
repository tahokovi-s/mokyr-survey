#!/usr/bin/env python3
"""
describe_third_generation.py -- Descriptive statistics for Mokyr survey
third-generation PhD students.

Outputs:
  Data/Derived/Third_Generation_Headlines_{date}.csv
  Data/Derived/Third_Generation_Subtree_Sizes_{date}.csv
  Data/Derived/Third_Generation_Profile_{date}.csv
  Data/Derived/Third_Generation_Metadata_Coverage_{date}.csv
  Output/Third_Generation_Descriptives_{date}.md

Universes:
  - ALL gen-3: used for network/graph stats AND field distributions
    (excludes only nodes with blank values for each field)
  - RESPONDENT gen-3: used only for has_students (nonrespondent
    has_students=False is a mechanical default, not observed data)
  - Metadata coverage section spans all gen-3 to show backfill impact
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
    ("pre-2020", 0, 2019),
    ("2020-2022", 2020, 2022),
    ("2023-2025", 2023, 2025),
    ("2026+", 2026, 9999),
]

# ------------------------------------------------------------------
# Country harmonization
# ------------------------------------------------------------------
# Current node builds should already use canonical short-form country
# labels. Keep a small alias map as a defensive fallback for older snapshots.

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


# ------------------------------------------------------------------
# File discovery
# ------------------------------------------------------------------

def _latest_common_date(base_dir: Path, patterns: list[re.Pattern]) -> str | None:
    date_sets = []
    for pattern in patterns:
        matches = set()
        if not base_dir.exists():
            return None
        for p in base_dir.iterdir():
            m = pattern.match(p.name)
            if m:
                matches.add(m.group(1))
        if not matches:
            return None
        date_sets.append(matches)
    common = set.intersection(*date_sets)
    if not common:
        return None
    return max(common, key=lambda t: datetime.strptime(t, "%m%d%y"))


def load_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------
# Subtree computation (reused from Gen 1 logic)
# ------------------------------------------------------------------

def build_adjacency(edges: list[dict]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        children[e["source_id"]].append(e["target_id"])
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
        nid = stack.pop()
        if nid in visited or nid in blocked:
            continue
        visited.add(nid)
        descendants.add(nid)
        stack.extend(adj.get(nid, []))

    return descendants


def build_descendant_summary(focal_nodes: list[dict], adj: dict[str, list[str]]) -> dict:
    focal_ids = {n["node_id"] for n in focal_nodes}
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


# ------------------------------------------------------------------
# Student data status (Gen 3-specific)
# ------------------------------------------------------------------

def _student_data_status(node: dict, adj: dict[str, list[str]], node_map: dict) -> str:
    """Classify student-data availability for a gen-3 node.

    Returns one of:
        non_respondent        - not a survey respondent
        q12_no                - respondent, has_students != True
        no_outgoing_edges     - has_students=True but no children in the network
        gen3_children_only    - has children, but all are generation 3 (co-advised peers)
        has_lower_gen_descendants - has at least one child in generation 4+
    """
    if node["is_respondent"] != "True":
        return "non_respondent"
    if node["has_students"] != "True":
        return "q12_no"
    targets = adj.get(node["node_id"], [])
    if not targets:
        return "no_outgoing_edges"
    for tid in targets:
        tnode = node_map.get(tid, {})
        gen = tnode.get("generation", "").strip()
        if gen and int(gen) > 3:
            return "has_lower_gen_descendants"
    return "gen3_children_only"


STUDENT_STATUS_LABELS = {
    "non_respondent": "Non-respondent",
    "q12_no": "Q12=No (no students)",
    "no_outgoing_edges": "Q12=Yes, no edges",
    "gen3_children_only": "Q12=Yes, gen-3 children only",
    "has_lower_gen_descendants": "Q12=Yes, gen-4+ descendants",
}

# ------------------------------------------------------------------
# Output writers
# ------------------------------------------------------------------

def write_headlines(gen3_all, gen3_resp, gen3_nonresp, descendant_summary,
                    adj, node_map, out_path: Path):
    has_stu = sum(1 for n in gen3_resp if n["has_students"] == "True")
    no_outgoing = sum(
        1 for n in gen3_resp
        if n["has_students"] == "True" and not adj.get(n["node_id"], [])
    )
    gen3_only = sum(
        1 for n in gen3_resp
        if _student_data_status(n, adj, node_map) == "gen3_children_only"
    )
    has_lower = sum(
        1 for n in gen3_resp
        if _student_data_status(n, adj, node_map) == "has_lower_gen_descendants"
    )

    rows = [
        {"statistic": "total_third_generation", "universe": "all_gen3",
         "count": len(gen3_all)},
        {"statistic": "respondent_third_generation", "universe": "respondent_gen3",
         "count": len(gen3_resp)},
        {"statistic": "non_respondent_third_generation", "universe": "all_gen3",
         "count": len(gen3_nonresp)},
        {"statistic": "gen3_with_descendants", "universe": "all_gen3",
         "count": sum(1 for n in gen3_all if n["descendant_count"] > 0)},
        {"statistic": "gen3_without_descendants", "universe": "all_gen3",
         "count": sum(1 for n in gen3_all if n["descendant_count"] == 0)},
        {"statistic": "unique_descendants_from_gen3", "universe": "all_gen3",
         "count": descendant_summary["unique_descendant_count"]},
        {"statistic": "summed_subtree_sizes", "universe": "all_gen3",
         "count": descendant_summary["summed_descendant_count"]},
        {"statistic": "subtree_overlap", "universe": "all_gen3",
         "count": descendant_summary["subtree_overlap_count"]},
        {"statistic": "respondent_has_students_yes", "universe": "respondent_gen3",
         "count": has_stu},
        {"statistic": "respondent_has_students_no", "universe": "respondent_gen3",
         "count": len(gen3_resp) - has_stu},
        {"statistic": "has_students_no_outgoing_edges", "universe": "respondent_gen3",
         "count": no_outgoing},
        {"statistic": "has_students_gen3_children_only", "universe": "respondent_gen3",
         "count": gen3_only},
        {"statistic": "has_students_lower_gen_descendants", "universe": "respondent_gen3",
         "count": has_lower},
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["statistic", "universe", "count"])
        writer.writeheader()
        writer.writerows(rows)


def write_subtree_sizes(gen3_all, adj, node_map, out_path: Path):
    ranked = sorted(gen3_all, key=lambda n: -n["descendant_count"])
    with open(out_path, "w", newline="") as f:
        fields = [
            "rank", "first_name", "last_name", "node_id", "is_respondent",
            "phd_year", "phd_institution_canon", "phd_institution_raw",
            "current_employer_canon", "current_employer_raw",
            "country", "us_state", "has_students", "student_data_status",
            "descendant_count",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for i, n in enumerate(ranked, 1):
            writer.writerow({
                "rank": i,
                "first_name": n["first_name"],
                "last_name": n["last_name"],
                "node_id": n["node_id"],
                "is_respondent": n["is_respondent"],
                "phd_year": n["phd_year"],
                "phd_institution_canon": n["phd_institution_canon"],
                "phd_institution_raw": n["phd_institution_raw"],
                "current_employer_canon": n["current_employer_canon"],
                "current_employer_raw": n["current_employer_raw"],
                "country": n["country"],
                "us_state": n["us_state"],
                "has_students": n["has_students"],
                "student_data_status": _student_data_status(n, adj, node_map),
                "descendant_count": n["descendant_count"],
            })


def write_profile(gen3_all, gen3_resp, out_path: Path):
    """Aggregated distributions for gen-3 nodes.

    Most distributions use all gen-3 nodes with nonblank values for the
    relevant field (includes backfilled nonrespondents).  has_students and
    has_students_by_cohort use respondent-only data because nonrespondent
    has_students=False is a mechanical default, not an observed answer.
    """
    rows: list[dict] = []

    def _add(section, label, value, count):
        rows.append({"section": section, "label": label, "value": value,
                      "count": count})

    n_all = len(gen3_all)
    n_resp = len(gen3_resp)

    # --- PhD year distribution (all gen-3 with data) ---
    years = [int(n["phd_year"]) for n in gen3_all if n["phd_year"].strip()]
    if years:
        _add("phd_year", "n_with_year", "", len(years))
        _add("phd_year", "n_total", "", n_all)
        _add("phd_year", "min", "", min(years))
        _add("phd_year", "max", "", max(years))
        _add("phd_year", "median", "", int(statistics.median(years)))
        _add("phd_year", "mean", "", round(statistics.mean(years), 1))
        decade_counts = Counter((y // 10) * 10 for y in years)
        for decade in sorted(decade_counts):
            _add("phd_year", "decade", f"{decade}s", decade_counts[decade])

    # --- PhD institution (canonical, all gen-3 with data) ---
    inst_counter = Counter(
        n["phd_institution_canon"] for n in gen3_all
        if n["phd_institution_canon"].strip()
    )
    _add("phd_institution", "n_with_institution", "", sum(inst_counter.values()))
    _add("phd_institution", "n_total", "", n_all)
    _add("phd_institution", "unique_institutions", "", len(inst_counter))
    for inst, cnt in inst_counter.most_common():
        _add("phd_institution", "institution", inst, cnt)

    # --- Current employer (canonical, all gen-3 with data) ---
    emp_counter = Counter(
        n["current_employer_canon"] for n in gen3_all
        if n["current_employer_canon"].strip()
    )
    emp_blank = sum(1 for n in gen3_all if not n["current_employer_canon"].strip())
    _add("current_employer", "n_with_employer", "", sum(emp_counter.values()))
    _add("current_employer", "n_blank_employer", "", emp_blank)
    _add("current_employer", "n_total", "", n_all)
    _add("current_employer", "unique_employers", "", len(emp_counter))
    for emp, cnt in emp_counter.most_common():
        _add("current_employer", "employer", emp, cnt)

    # --- Country distribution (harmonized, all gen-3 with data) ---
    country_counter = Counter(
        harmonize_country(n["country"]) for n in gen3_all if n["country"].strip()
    )
    _add("country", "n_with_country", "", sum(country_counter.values()))
    _add("country", "n_total", "", n_all)
    for c, cnt in country_counter.most_common():
        _add("country", "country", c, cnt)

    # --- US state distribution (all gen-3 in US with data) ---
    state_counter = Counter(
        n["us_state"] for n in gen3_all
        if n["us_state"].strip()
    )
    _add("us_state", "n_with_state", "", sum(state_counter.values()))
    for s, cnt in state_counter.most_common():
        _add("us_state", "state", s, cnt)

    # --- Has-students rate (respondent-only) ---
    has_stu = sum(1 for n in gen3_resp if n["has_students"] == "True")
    _add("has_students", "yes", "", has_stu)
    _add("has_students", "no", "", n_resp - has_stu)
    _add("has_students", "rate", "", round(has_stu / n_resp, 4) if n_resp else 0)
    _add("has_students", "n_respondent", "", n_resp)

    # --- Has-students by PhD-year bin (respondent-only) ---
    for label, lo, hi in PHD_YEAR_BINS:
        cohort = [n for n in gen3_resp
                  if n["phd_year"].strip() and lo <= int(n["phd_year"]) <= hi]
        yes = sum(1 for n in cohort if n["has_students"] == "True")
        _add("has_students_by_cohort", label, "total", len(cohort))
        _add("has_students_by_cohort", label, "has_students", yes)
        _add("has_students_by_cohort", label, "rate",
             round(yes / len(cohort), 4) if cohort else 0)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "label", "value", "count"])
        writer.writeheader()
        writer.writerows(rows)


def write_metadata_coverage(gen3_all, gen3_resp, gen3_nonresp, out_path: Path):
    """Field coverage for all gen-3 nodes, split by respondent status."""
    fields = [
        "phd_year", "phd_institution_canon", "phd_institution_raw",
        "current_employer_canon", "current_employer_raw",
        "country", "us_state", "email",
    ]
    rows = []
    for field in fields:
        all_ct = sum(1 for n in gen3_all if n.get(field, "").strip())
        resp_ct = sum(1 for n in gen3_resp if n.get(field, "").strip())
        nonresp_ct = sum(1 for n in gen3_nonresp if n.get(field, "").strip())
        rows.append({
            "field": field,
            "all_gen3": all_ct,
            "all_gen3_total": len(gen3_all),
            "respondent": resp_ct,
            "respondent_total": len(gen3_resp),
            "nonrespondent": nonresp_ct,
            "nonrespondent_total": len(gen3_nonresp),
        })
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "field", "all_gen3", "all_gen3_total",
                "respondent", "respondent_total",
                "nonrespondent", "nonrespondent_total",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------------
# Validation summary (reused from Gen 1)
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Markdown summary
# ------------------------------------------------------------------

def write_markdown(gen3_all, gen3_resp, gen3_nonresp, subtree_stats,
                   all_nodes, descendant_summary, validation_summary,
                   adj, node_map, date_token, out_path: Path):
    lines: list[str] = []

    def _h(level, text):
        lines.append(f"{'#' * level} {text}")

    def _p(text):
        lines.append(text)

    def _blank():
        lines.append("")

    n_all = len(gen3_all)
    n_resp = len(gen3_resp)
    n_nonresp = len(gen3_nonresp)
    has_stu = sum(1 for n in gen3_resp if n["has_students"] == "True")
    with_desc = sum(1 for n in gen3_all if n["descendant_count"] > 0)
    summed_desc = descendant_summary["summed_descendant_count"]
    unique_desc_count = descendant_summary["unique_descendant_count"]

    _h(1, "Third-Generation Descriptive Statistics")
    _blank()
    _p(f"Date: `{date_token}`")
    _blank()

    # --- Section 1: Network-wide facts (all gen-3) ---
    _h(2, "All Third-Generation Nodes (Network Universe)")
    _blank()
    _p(f"Universe: all {n_all} generation-3 nodes in `Network_Nodes_{date_token}.csv` "
       f"(excludes JM-ROOT).")
    _blank()
    _p("| Statistic | Count |")
    _p("|---|---|")
    _p(f"| Total third-generation students | {n_all} |")
    _p(f"| Respondents | {n_resp} |")
    _p(f"| Non-respondents | {n_nonresp} |")
    _p(f"| With descendants (subtree > 0) | {with_desc} |")
    _p(f"| Without descendants | {n_all - with_desc} |")
    _p(f"| Unique descendants reachable from gen-3 | {unique_desc_count} |")
    _p(f"| Sum of per-subtree sizes | {summed_desc} |")
    _p(f"| Subtree overlap (shared descendants) | {summed_desc - unique_desc_count} |")
    _blank()

    # Non-respondent roster with coverage
    _h(3, "Non-Respondent Third-Generation Students")
    _blank()
    coverage_fields = ["phd_year", "phd_institution_canon", "current_employer_canon",
                       "country", "email"]
    _p("| Name | Node ID | Fields Populated |")
    _p("|---|---|---|")
    for n in sorted(gen3_nonresp, key=lambda x: x["last_name"]):
        populated = [f for f in coverage_fields if n.get(f, "").strip()]
        field_str = ", ".join(populated) if populated else "(none)"
        _p(f"| {n['first_name']} {n['last_name']} | {n['node_id']} | {field_str} |")
    _blank()

    # Subtree ranking
    _h(3, "Subtree Sizes (All Gen-3, Ranked)")
    _blank()
    _p(
        "Descendant counts are **lower bounds** and exclude other generation-3 students "
        "even when cross-gen-3 advising edges exist. Respondents with missing Q12a "
        "student lists and unresolved branches will be understated."
    )
    _blank()
    _p(
        "**Note:** Only 3 gen-3 nodes have any descendants, and generation 4 contains "
        "only 5 nodes total. Subtree statistics for gen-3 should be interpreted with "
        "extreme caution given these small numbers."
    )
    _blank()
    ranked = sorted(gen3_all, key=lambda n: -n["descendant_count"])
    top = [n for n in ranked if n["descendant_count"] > 0]
    _p("| Rank | Name | Descendants | Student Data Status |")
    _p("|---|---|---|---|")
    for i, n in enumerate(top, 1):
        status = _student_data_status(n, adj, node_map)
        _p(f"| {i} | {n['first_name']} {n['last_name']} | "
           f"{n['descendant_count']} | {STUDENT_STATUS_LABELS.get(status, status)} |")
    _blank()

    _p(f"**Summary of subtree sizes (all {n_all} gen-3):** "
       f"mean={subtree_stats['mean']:.1f}, "
       f"median={subtree_stats['median']:.1f}, "
       f"min={subtree_stats['min']}, "
       f"max={subtree_stats['max']}, "
       f"std={subtree_stats['std']:.1f}")
    _blank()

    # Student data status breakdown
    _h(3, "Student Data Status (Gen-3 Respondents)")
    _blank()
    _p(
        "Gen-3 respondents who reported supervising PhD students (Q12=Yes) "
        "are classified by whether their students appear in the network."
    )
    _blank()
    status_counter = Counter(
        _student_data_status(n, adj, node_map) for n in gen3_resp
    )
    _p("| Status | Count | Description |")
    _p("|---|---|---|")
    for status_key in ["q12_no", "no_outgoing_edges", "gen3_children_only",
                       "has_lower_gen_descendants"]:
        _p(f"| {STUDENT_STATUS_LABELS[status_key]} | "
           f"{status_counter.get(status_key, 0)} | |")
    _blank()

    # List Q12a-censored (no outgoing edges)
    censored = [n for n in gen3_resp
                if _student_data_status(n, adj, node_map) == "no_outgoing_edges"]
    if censored:
        _p(f"**Q12a-censored gen-3 respondents ({len(censored)}):** "
           "these respondents reported supervising PhD students (Q12=Yes) "
           "but have no student edges in the network. Their subtree counts are "
           "mechanically zero.")
        for n in sorted(censored, key=lambda x: x["last_name"]):
            _p(f"- {n['first_name']} {n['last_name']}")
        _blank()

    # Gen-3-only children
    gen3_only = [n for n in gen3_resp
                 if _student_data_status(n, adj, node_map) == "gen3_children_only"]
    if gen3_only:
        _p(f"**Gen-3 children only ({len(gen3_only)}):** "
           "these respondents have outgoing student edges, but all targets are "
           "also generation-3 nodes (co-advised peers). Their subtrees are zero "
           "after blocking same-generation traversal.")
        for n in sorted(gen3_only, key=lambda x: x["last_name"]):
            targets = adj.get(n["node_id"], [])
            target_names = []
            for tid in targets:
                tn = node_map.get(tid, {})
                target_names.append(f"{tn.get('first_name', '?')} {tn.get('last_name', '?')}")
            # Deduplicate target names (duplicate edges possible)
            unique_targets = sorted(set(target_names))
            _p(f"- {n['first_name']} {n['last_name']} -> {', '.join(unique_targets)}")
        _blank()

    # Tree shape summary
    gen_counter = Counter(
        n["generation"] for n in all_nodes if n["node_id"] != "JM-ROOT"
    )
    max_gen = max(int(g) for g in gen_counter if g.strip())
    _h(3, "Tree Shape")
    _blank()
    _p("| Generation | Nodes |")
    _p("|---|---|")
    for g in sorted(gen_counter, key=lambda x: (x == "", int(x) if x else 999)):
        label = f"Gen {g}" if g.strip() else "Unassigned"
        _p(f"| {label} | {gen_counter[g]} |")
    _p(f"| **Total (excl. root)** | **{sum(gen_counter.values())}** |")
    _blank()
    _p(f"Maximum generation depth: {max_gen}")
    _blank()

    # --- Section 2: Metadata coverage (all gen-3) ---
    _h(2, "Metadata Coverage (All Gen-3)")
    _blank()
    _p(
        f"Field coverage across all {n_all} gen-3 nodes. Non-respondent fields "
        "come from the Gen 3 Nonrespondent Backfill; respondent fields come from "
        "the Qualtrics survey."
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
    _p("| Field | All Gen-3 | Respondent | Non-respondent |")
    _p("|---|---|---|---|")
    for field, label in coverage_fields_full:
        all_ct = sum(1 for n in gen3_all if n.get(field, "").strip())
        resp_ct = sum(1 for n in gen3_resp if n.get(field, "").strip())
        nonresp_ct = sum(1 for n in gen3_nonresp if n.get(field, "").strip())
        _p(f"| {label} | {_format_coverage_cell(all_ct, n_all)} "
           f"| {_format_coverage_cell(resp_ct, n_resp)} "
           f"| {_format_coverage_cell(nonresp_ct, n_nonresp)} |")
    _blank()

    # --- Section 3: Distributions (all gen-3 with data) ---
    _h(2, "Third-Generation Distributions")
    _blank()
    _p(
        f"Statistics use all {n_all} gen-3 nodes with nonblank values for each field "
        "(includes backfilled nonrespondents). Has-students uses respondent-only data "
        f"(N={n_resp}) because nonrespondent has_students values are mechanical defaults, "
        "not survey answers."
    )
    _blank()

    # PhD year
    years = [int(n["phd_year"]) for n in gen3_all if n["phd_year"].strip()]
    _h(3, "PhD Year Distribution")
    _blank()
    if years:
        _p(f"- N with year: {len(years)} / {n_all}")
        _p(f"- Range: {min(years)}--{max(years)} (includes expected graduation years)")
        _p(f"- Median: {int(statistics.median(years))}")
        _p(f"- Mean: {statistics.mean(years):.1f}")
        _blank()
        decade_counts = Counter((y // 10) * 10 for y in years)
        _p("| Decade | Count |")
        _p("|---|---|")
        for d in sorted(decade_counts):
            _p(f"| {d}s | {decade_counts[d]} |")
        _blank()
    else:
        _p("No PhD year data available.")
        _blank()

    # PhD institution
    inst_counter = Counter(
        n["phd_institution_canon"] for n in gen3_all
        if n["phd_institution_canon"].strip()
    )
    _h(3, "PhD Institution (Canonical)")
    _blank()
    _p(f"- N with institution: {sum(inst_counter.values())} / {n_all}")
    _p(f"- Unique institutions: {len(inst_counter)}")
    _blank()
    _p("| Institution | Count |")
    _p("|---|---|")
    for inst, cnt in inst_counter.most_common():
        _p(f"| {inst} | {cnt} |")
    _blank()

    # Current employer
    emp_counter = Counter(
        n["current_employer_canon"] for n in gen3_all
        if n["current_employer_canon"].strip()
    )
    emp_blank = sum(1 for n in gen3_all if not n["current_employer_canon"].strip())
    _h(3, "Current Employer (Canonical)")
    _blank()
    _p(f"- N with employer: {sum(emp_counter.values())} / {n_all}")
    _p(f"- Blank: {emp_blank}")
    _p(f"- Unique employers: {len(emp_counter)}")
    _blank()
    _p("| Employer | Count |")
    _p("|---|---|")
    for emp, cnt in emp_counter.most_common():
        _p(f"| {emp} | {cnt} |")
    _blank()

    # Country (harmonized)
    country_counter = Counter(
        harmonize_country(n["country"]) for n in gen3_all if n["country"].strip()
    )
    _h(3, "Country")
    _blank()
    _p(f"- N with country: {sum(country_counter.values())} / {n_all}")
    _p(
        "- Country counts are reported using canonical short-form labels "
        "(e.g., \"United States\")."
    )
    _blank()
    _p("| Country | Count |")
    _p("|---|---|")
    for c, cnt in country_counter.most_common():
        _p(f"| {c} | {cnt} |")
    _blank()

    # US state
    state_counter = Counter(
        n["us_state"] for n in gen3_all if n["us_state"].strip()
    )
    _h(3, "US State")
    _blank()
    us_count = sum(
        1 for n in gen3_all
        if harmonize_country(n["country"].strip()) == "United States"
    )
    _p(f"- US-based gen-3: {us_count}")
    _p(f"- N with state: {sum(state_counter.values())}")
    _blank()
    _p("| State | Count |")
    _p("|---|---|")
    for s, cnt in state_counter.most_common():
        _p(f"| {s} | {cnt} |")
    _blank()

    # Has-students (respondent-only)
    _h(3, "Has Supervised PhD Students (Respondent-Only)")
    _blank()
    _p(f"Universe: {n_resp} respondent gen-3 nodes only. Nonrespondent "
       "has_students=False is a mechanical default, not a survey answer.")
    _blank()
    if n_resp:
        _p(f"- Yes: {has_stu} / {n_resp} ({100*has_stu/n_resp:.1f}%)")
    else:
        _p(f"- Yes: {has_stu} / {n_resp}")
    _p(f"- No: {n_resp - has_stu} / {n_resp}")
    _blank()
    _p("**Has-students rate by PhD-year cohort** (respondent gen-3 only):")
    _blank()
    _p("| Cohort | N | Has Students | Rate |")
    _p("|---|---|---|---|")
    for label, lo, hi in PHD_YEAR_BINS:
        cohort = [n for n in gen3_resp
                  if n["phd_year"].strip() and lo <= int(n["phd_year"]) <= hi]
        yes = sum(1 for n in cohort if n["has_students"] == "True")
        rate = f"{100*yes/len(cohort):.0f}%" if cohort else "n/a"
        _p(f"| {label} | {len(cohort)} | {yes} | {rate} |")
    _blank()

    # --- Caveats ---
    _h(2, "Caveats")
    _blank()
    q12a_miss = sum(
        1 for n in gen3_all
        if _student_data_status(n, adj, node_map) == "no_outgoing_edges"
    )
    gen3_only_ct = sum(
        1 for n in gen3_all
        if _student_data_status(n, adj, node_map) == "gen3_children_only"
    )
    _p(f"1. **Subtree counts are lower bounds.** {q12a_miss} gen-3 respondents "
       "answered Q12=Yes but have no student edges in the network (their subtree sizes "
       "are mechanically zero). "
       f"{gen3_only_ct} additional respondents have outgoing edges only to other gen-3 "
       "nodes, so their subtrees are also zero after same-generation blocking. "
       f"Across all generations, "
       f"{validation_summary['all_generation_q12_yes_without_q12a']} respondents have "
       f"Q12=Yes without Q12a data. {validation_summary['unresolved_edges_total']} "
       "unresolved edges also reduce coverage.")
    _p("   - **Subtree interpretation is extremely limited.** Only 3 gen-3 nodes have "
       "any descendants, and generation 4 contains only 5 nodes total. Subtree "
       "statistics should be interpreted with extreme caution given these small numbers.")
    overlap = summed_desc - unique_desc_count
    if overlap > 0:
        _p(f"2. **Subtree overlap.** {overlap} descendants appear "
           f"in multiple gen-3 subtrees (shared advisory relationships). Per-subtree "
           f"sizes are correct; the sum of per-subtree sizes ({summed_desc}) exceeds "
           f"unique descendants ({unique_desc_count}).")
    else:
        _p(f"2. **No subtree overlap.** All {unique_desc_count} descendants reachable "
           "from gen-3 appear in exactly one subtree. No shared advisory relationships "
           "across gen-3 advisors at the gen-4+ level.")
    _p(f"3. **Distributions include backfilled nonrespondents.** The {n_nonresp} "
       "non-respondent gen-3 nodes have metadata from the Gen 3 Nonrespondent Backfill "
       "(web research). Distributions use all gen-3 nodes with nonblank values for "
       "each field, so backfilled data is reflected. Exception: has-students uses "
       f"respondent-only data (N={n_resp}) because nonrespondent has_students=False "
       "is a mechanical default from build_network.py, not a survey answer.")
    _p(f"4. **Country values should now be canonical in the node CSV.** This script "
       "retains a small alias map as a defensive fallback for older snapshots, but "
       "current rebuilds should already use short-form labels such as \"United States\" "
       "and \"United Kingdom\".")
    _p("5. **Canonical institution/employer mappings are incomplete.** "
       f"{validation_summary['unmapped_phd_count']} PhD institution values and "
       f"{validation_summary['unmapped_employer_count']} employer values lack canonical "
       "mappings. Affected nodes appear as blank in canonical counts but retain raw "
       "values in the subtree roster.")
    _p(f"6. **{validation_summary['blank_generation_count']} respondent nodes have no "
       "assigned generation** and are excluded from all generation-specific counts.")
    _p("7. **Generation assignments use topology-corrected values.** "
       f"{validation_summary['topology_overrode_q8_count']} respondents had Q8 "
       "overridden by edge topology; "
       f"{validation_summary['hardcoded_q8_override_count']} had hardcoded Q8 "
       "adjustments. The `generation` column reflects final assignments.")
    _blank()

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Descriptive statistics for Mokyr third-generation students."
    )
    parser.add_argument(
        "--date", default=None,
        help="Date token (MMDDYY). Default: latest aligned nodes/edges/validation date."
    )
    parser.add_argument("--nodes", default=None, help="Path to Network_Nodes CSV.")
    parser.add_argument("--edges", default=None, help="Path to Network_Edges CSV.")
    parser.add_argument("--coverage", default=None, help="Path to validation coverage CSV.")
    parser.add_argument("--generation", default=None, help="Path to validation generation CSV.")
    parser.add_argument("--canon", default=None, help="Path to validation canon CSV.")
    parser.add_argument(
        "--output-dir", default=None,
        help="Override output directory for CSVs (default: Data/Derived/)."
    )
    parser.add_argument(
        "--md-dir", default=None,
        help="Override output directory for markdown (default: Output/)."
    )
    args = parser.parse_args()

    # Resolve date
    date_token = args.date
    if not date_token:
        derived = PROJECT_ROOT / "Data" / "Derived"
        date_token = _latest_common_date(
            derived,
            [
                _NODES_DATE_RE,
                _EDGES_DATE_RE,
                _COVERAGE_DATE_RE,
                _GENERATION_DATE_RE,
                _CANON_DATE_RE,
            ],
        )
        if not date_token:
            sys.exit("ERROR: could not find a common dated snapshot across nodes, edges, and validation CSVs.")
    print(f"Date token: {date_token}")

    # Resolve file paths
    derived = PROJECT_ROOT / "Data" / "Derived"
    nodes_path = Path(args.nodes) if args.nodes else (
        derived / f"Network_Nodes_{date_token}.csv"
    )
    edges_path = Path(args.edges) if args.edges else (
        derived / f"Network_Edges_{date_token}.csv"
    )
    coverage_path = Path(args.coverage) if args.coverage else (
        derived / f"Descriptive_Validation_Coverage_{date_token}.csv"
    )
    generation_path = Path(args.generation) if args.generation else (
        derived / f"Descriptive_Validation_Generation_{date_token}.csv"
    )
    canon_path = Path(args.canon) if args.canon else (
        derived / f"Descriptive_Validation_Canon_{date_token}.csv"
    )
    for p, label in [
        (nodes_path, "nodes"),
        (edges_path, "edges"),
        (coverage_path, "coverage"),
        (generation_path, "generation"),
        (canon_path, "canon"),
    ]:
        if not p.exists():
            sys.exit(f"ERROR: {label} file not found: {p}")

    out_dir = Path(args.output_dir) if args.output_dir else derived
    md_dir = Path(args.md_dir) if args.md_dir else (PROJECT_ROOT / "Output")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    nodes = load_csv(nodes_path)
    edges = load_csv(edges_path)
    coverage_rows = load_csv(coverage_path)
    generation_rows = load_csv(generation_path)
    canon_rows = load_csv(canon_path)
    print(f"Loaded {len(nodes)} nodes, {len(edges)} edges.")

    # Build lookup structures
    node_map = {n["node_id"]: n for n in nodes}
    adj = build_adjacency(edges)

    # Filter gen-3
    gen3_all = [
        n for n in nodes
        if n["generation"] == "3" and n["node_id"] != "JM-ROOT"
    ]
    gen3_resp = [n for n in gen3_all if n["is_respondent"] == "True"]
    gen3_nonresp = [n for n in gen3_all if n["is_respondent"] != "True"]
    print(f"Gen-3: {len(gen3_all)} total, {len(gen3_resp)} respondent, "
          f"{len(gen3_nonresp)} non-respondent.")

    # Compute subtrees (block same-generation traversal)
    descendant_summary = build_descendant_summary(gen3_all, adj)
    for n in gen3_all:
        n["descendant_count"] = len(descendant_summary["sets"][n["node_id"]])

    desc_counts = [n["descendant_count"] for n in gen3_all]
    subtree_stats = {
        "mean": statistics.mean(desc_counts),
        "median": statistics.median(desc_counts),
        "min": min(desc_counts),
        "max": max(desc_counts),
        "std": statistics.stdev(desc_counts) if len(desc_counts) > 1 else 0,
    }
    print(f"Subtree stats: mean={subtree_stats['mean']:.1f}, "
          f"median={subtree_stats['median']:.1f}, "
          f"min={subtree_stats['min']}, max={subtree_stats['max']}")
    validation_summary = build_validation_summary(coverage_rows, generation_rows, canon_rows)

    # Write outputs
    headlines_path = out_dir / f"Third_Generation_Headlines_{date_token}.csv"
    subtree_path = out_dir / f"Third_Generation_Subtree_Sizes_{date_token}.csv"
    profile_path = out_dir / f"Third_Generation_Profile_{date_token}.csv"
    coverage_out_path = out_dir / f"Third_Generation_Metadata_Coverage_{date_token}.csv"
    md_path = md_dir / f"Third_Generation_Descriptives_{date_token}.md"

    write_headlines(gen3_all, gen3_resp, gen3_nonresp, descendant_summary,
                    adj, node_map, headlines_path)
    print(f"Wrote {headlines_path.name}")

    write_subtree_sizes(gen3_all, adj, node_map, subtree_path)
    print(f"Wrote {subtree_path.name}")

    write_profile(gen3_all, gen3_resp, profile_path)
    print(f"Wrote {profile_path.name}")

    write_metadata_coverage(gen3_all, gen3_resp, gen3_nonresp, coverage_out_path)
    print(f"Wrote {coverage_out_path.name}")

    write_markdown(
        gen3_all,
        gen3_resp,
        gen3_nonresp,
        subtree_stats,
        nodes,
        descendant_summary,
        validation_summary,
        adj,
        node_map,
        date_token,
        md_path,
    )
    print(f"Wrote {md_path.name}")

    print("Done.")


if __name__ == "__main__":
    main()
