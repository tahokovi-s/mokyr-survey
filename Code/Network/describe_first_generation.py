#!/usr/bin/env python3
"""
describe_first_generation.py -- Descriptive statistics for Joel Mokyr's
first-generation PhD students.

Outputs:
  Data/Derived/First_Generation_Headlines_{date}.csv
  Data/Derived/First_Generation_Subtree_Sizes_{date}.csv
  Data/Derived/First_Generation_Profile_{date}.csv
  Data/Derived/First_Generation_Metadata_Coverage_{date}.csv
  Data/Derived/First_Generation_Excluded_{date}.csv
  Output/First_Generation_Descriptives_{date}.md

Universes:
  - ALL gen-1: used for network/graph stats AND most field distributions
    (excludes only nodes with blank values for each field)
  - RESPONDENT gen-1: used only for has_students (nonrespondent
    has_students=False is a mechanical default, not observed data)
  - Metadata coverage section spans all gen-1 to show
    respondent/nonrespondent coverage

Notes:
  - First_Generation_Profile_{date}.csv is the canonical aggregated profile
    output for Gen 1 descriptives.
  - Historical First_Generation_Respondent_Profile_{date}.csv files predate
    the current mixed-universe denominator convention and are not written by
    this script.
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
_DISCREPANCY_DATE_RE = re.compile(r"^Network_Discrepancies_(\d{6})\.csv$")

PHD_YEAR_BINS = [
    ("pre-2000", 0, 1999),
    ("2000-2009", 2000, 2009),
    ("2010-2019", 2010, 2019),
    ("2020+", 2020, 9999),
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


DISCREPANCY_CATEGORY_LABELS = {
    "committee_only_unassigned": "Committee-only unassigned",
    "manual_review_q8_committee_indirect": "Manual review: committee + indirect",
    "direct_q8_missing_gen1": "Direct Q8 missing Gen 1",
    "gen1_without_direct_q8": "Gen 1 without direct Q8",
}


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
# Subtree computation
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


def build_descendant_summary(gen1_all: list[dict], adj: dict[str, list[str]]) -> dict:
    gen1_ids = {n["node_id"] for n in gen1_all}
    descendant_sets = {
        node_id: descendant_set(node_id, adj, blocked_ids=gen1_ids)
        for node_id in gen1_ids
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
# Output writers
# ------------------------------------------------------------------

def write_headlines(gen1_all, gen1_resp, gen1_nonresp, descendant_summary, exclusion_summary, out_path: Path):
    rows = [
        {"statistic": "total_first_generation", "universe": "all_gen1",
         "count": len(gen1_all)},
        {"statistic": "respondent_first_generation", "universe": "respondent_gen1",
         "count": len(gen1_resp)},
        {"statistic": "non_respondent_first_generation", "universe": "all_gen1",
         "count": len(gen1_nonresp)},
        {"statistic": "gen1_with_descendants", "universe": "all_gen1",
         "count": sum(1 for n in gen1_all if n["descendant_count"] > 0)},
        {"statistic": "gen1_without_descendants", "universe": "all_gen1",
         "count": sum(1 for n in gen1_all if n["descendant_count"] == 0)},
        {"statistic": "unique_descendants_from_gen1", "universe": "all_gen1",
         "count": descendant_summary["unique_descendant_count"]},
        {"statistic": "summed_subtree_sizes", "universe": "all_gen1",
         "count": descendant_summary["summed_descendant_count"]},
        {"statistic": "subtree_overlap", "universe": "all_gen1",
         "count": descendant_summary["subtree_overlap_count"]},
        {"statistic": "respondent_has_students_yes", "universe": "respondent_gen1",
         "count": sum(1 for n in gen1_resp if n["has_students"] == "True")},
        {"statistic": "respondent_has_students_no", "universe": "respondent_gen1",
         "count": sum(1 for n in gen1_resp if n["has_students"] != "True")},
        {"statistic": "excluded_gen1_adjacent_total", "universe": "excluded_from_gen1",
         "count": exclusion_summary["total"]},
        {"statistic": "excluded_committee_only_unassigned", "universe": "excluded_from_gen1",
         "count": exclusion_summary["by_category"].get("committee_only_unassigned", 0)},
        {"statistic": "excluded_manual_review_q8_committee_indirect", "universe": "excluded_from_gen1",
         "count": exclusion_summary["by_category"].get("manual_review_q8_committee_indirect", 0)},
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["statistic", "universe", "count"])
        writer.writeheader()
        writer.writerows(rows)


def _q12a_status(node: dict) -> str:
    """Classify Q12a data availability for a gen-1 node."""
    if node["is_respondent"] != "True":
        return "non_respondent"
    if node["has_students"] != "True":
        return "q12_no"
    if node["descendant_count"] > 0:
        return "q12a_present"
    return "q12a_missing"


def _category_label(category: str) -> str:
    return DISCREPANCY_CATEGORY_LABELS.get(category, category.replace("_", " "))


def build_exclusion_rows(discrepancy_rows: list[dict], gen1_ids: set[str]) -> list[dict]:
    rows = []
    for row in discrepancy_rows:
        if row.get("node_id", "") in gen1_ids:
            continue
        rows.append({
            "category": row.get("category", ""),
            "category_label": _category_label(row.get("category", "")),
            "response_id": row.get("response_id", ""),
            "node_id": row.get("node_id", ""),
            "first_name": row.get("first_name", ""),
            "last_name": row.get("last_name", ""),
            "final_generation": row.get("final_generation", ""),
            "raw_q8": row.get("raw_q8", ""),
            "raw_q11": row.get("raw_q11", ""),
            "raw_q12": row.get("raw_q12", ""),
            "note": row.get("note", ""),
        })
    return sorted(rows, key=lambda row: (row["category_label"], row["last_name"], row["first_name"]))


def build_exclusion_summary(exclusion_rows: list[dict]) -> dict:
    by_category = Counter(row["category"] for row in exclusion_rows)
    return {
        "total": len(exclusion_rows),
        "by_category": by_category,
    }


def write_excluded_roster(exclusion_rows: list[dict], out_path: Path):
    fields = [
        "category",
        "category_label",
        "response_id",
        "node_id",
        "first_name",
        "last_name",
        "final_generation",
        "raw_q8",
        "raw_q11",
        "raw_q12",
        "note",
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(exclusion_rows)


def write_subtree_sizes(gen1_all, out_path: Path):
    ranked = sorted(gen1_all, key=lambda n: -n["descendant_count"])
    with open(out_path, "w", newline="") as f:
        fields = [
            "rank", "first_name", "last_name", "node_id", "is_respondent",
            "phd_year", "phd_institution_canon", "phd_institution_raw",
            "current_employer_canon", "current_employer_raw",
            "country", "us_state", "has_students", "q12a_status",
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
                "q12a_status": _q12a_status(n),
                "descendant_count": n["descendant_count"],
            })


def write_profile(gen1_all, gen1_resp, out_path: Path):
    """Aggregated distributions for gen-1 nodes.

    Most distributions use all gen-1 nodes with nonblank values for the
    relevant field. has_students and has_students_by_cohort use
    respondent-only data because nonrespondent data for this field
    is sparse or non-existent in build_network.
    """
    rows: list[dict] = []

    def _add(section, label, value, count):
        rows.append({"section": section, "label": label, "value": value,
                      "count": count})

    n_all = len(gen1_all)
    n_resp = len(gen1_resp)

    # --- PhD year distribution (all gen-1 with data) ---
    years = [int(n["phd_year"]) for n in gen1_all if n["phd_year"].strip()]
    if years:
        _add("phd_year", "n_with_year", "", len(years))
        _add("phd_year", "n_total", "", n_all)
        _add("phd_year", "min", "", min(years))
        _add("phd_year", "max", "", max(years))
        _add("phd_year", "median", "", int(statistics.median(years)))
        _add("phd_year", "mean", "", round(statistics.mean(years), 1))
        # Decade bins
        decade_counts = Counter((y // 10) * 10 for y in years)
        for decade in sorted(decade_counts):
            _add("phd_year", "decade", f"{decade}s", decade_counts[decade])

    # --- PhD institution (canonical, all gen-1 with data) ---
    inst_counter = Counter(
        n["phd_institution_canon"] for n in gen1_all
        if n["phd_institution_canon"].strip()
    )
    _add("phd_institution", "n_with_institution", "", sum(inst_counter.values()))
    _add("phd_institution", "n_total", "", n_all)
    _add("phd_institution", "unique_institutions", "", len(inst_counter))
    for inst, cnt in inst_counter.most_common():
        _add("phd_institution", "institution", inst, cnt)

    # --- Current employer (canonical, all gen-1 with data) ---
    emp_counter = Counter(
        n["current_employer_canon"] for n in gen1_all
        if n["current_employer_canon"].strip()
    )
    emp_blank = sum(1 for n in gen1_all if not n["current_employer_canon"].strip())
    _add("current_employer", "n_with_employer", "", sum(emp_counter.values()))
    _add("current_employer", "n_blank_employer", "", emp_blank)
    _add("current_employer", "n_total", "", n_all)
    _add("current_employer", "unique_employers", "", len(emp_counter))
    for emp, cnt in emp_counter.most_common():
        _add("current_employer", "employer", emp, cnt)

    # --- Country distribution (harmonized, all gen-1 with data) ---
    country_counter = Counter(
        harmonize_country(n["country"]) for n in gen1_all if n["country"].strip()
    )
    _add("country", "n_with_country", "", sum(country_counter.values()))
    _add("country", "n_total", "", n_all)
    for c, cnt in country_counter.most_common():
        _add("country", "country", c, cnt)

    # --- US state distribution (all gen-1 in US with data) ---
    state_counter = Counter(
        n["us_state"] for n in gen1_all
        if n["us_state"].strip()
    )
    _add("us_state", "n_with_state", "", sum(state_counter.values()))
    for s, cnt in state_counter.most_common():
        _add("us_state", "state", s, cnt)

    # --- Has-students rate (respondent-only) ---
    has_stu = sum(1 for n in gen1_resp if n["has_students"] == "True")
    _add("has_students", "yes", "", has_stu)
    _add("has_students", "no", "", n_resp - has_stu)
    _add("has_students", "rate", "", round(has_stu / n_resp, 4) if n_resp else 0)
    _add("has_students", "n_respondent", "", n_resp)

    # --- Has-students by PhD-year bin (respondent-only) ---
    for label, lo, hi in PHD_YEAR_BINS:
        cohort = [n for n in gen1_resp
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


def write_metadata_coverage(gen1_all, gen1_resp, gen1_nonresp, out_path: Path):
    """Field coverage for all gen-1 nodes, split by respondent status."""
    fields = [
        "phd_year", "phd_institution_canon", "phd_institution_raw",
        "current_employer_canon", "current_employer_raw",
        "country", "us_state", "email",
    ]
    rows = []
    for field in fields:
        all_ct = sum(1 for n in gen1_all if n.get(field, "").strip())
        resp_ct = sum(1 for n in gen1_resp if n.get(field, "").strip())
        nonresp_ct = sum(1 for n in gen1_nonresp if n.get(field, "").strip())
        rows.append({
            "field": field,
            "all_gen1": all_ct,
            "all_gen1_total": len(gen1_all),
            "respondent": resp_ct,
            "respondent_total": len(gen1_resp),
            "nonrespondent": nonresp_ct,
            "nonrespondent_total": len(gen1_nonresp),
        })
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "field", "all_gen1", "all_gen1_total",
                "respondent", "respondent_total",
                "nonrespondent", "nonrespondent_total",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------------
# Markdown summary
# ------------------------------------------------------------------

def build_validation_summary(coverage_rows: list[dict], generation_rows: list[dict], canon_rows: list[dict]) -> dict:
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


def write_markdown(gen1_all, gen1_resp, gen1_nonresp, subtree_stats,
                   all_nodes, descendant_summary, validation_summary,
                   exclusion_rows, exclusion_summary, discrepancy_available,
                   date_token, out_path: Path):
    lines: list[str] = []

    def _h(level, text):
        lines.append(f"{'#' * level} {text}")

    def _p(text):
        lines.append(text)

    def _blank():
        lines.append("")

    n_all = len(gen1_all)
    n_resp = len(gen1_resp)
    n_nonresp = len(gen1_nonresp)
    has_stu = sum(1 for n in gen1_resp if n["has_students"] == "True")
    with_desc = sum(1 for n in gen1_all if n["descendant_count"] > 0)
    summed_desc = descendant_summary["summed_descendant_count"]
    unique_desc_count = descendant_summary["unique_descendant_count"]

    _h(1, "First-Generation Descriptive Statistics")
    _blank()
    _p(f"Date: `{date_token}`")
    _blank()

    # --- Section 1: Network-wide facts (all gen-1) ---
    _h(2, "All First-Generation Nodes (Network Universe)")
    _blank()
    _p(f"Universe: all {n_all} generation-1 nodes in `Network_Nodes_{date_token}.csv` "
       f"(excludes JM-ROOT).")
    _blank()
    _p(f"| Statistic | Count |")
    _p(f"|---|---|")
    _p(f"| Total first-generation students | {n_all} |")
    _p(f"| Respondents | {n_resp} |")
    _p(f"| Non-respondents | {n_nonresp} |")
    _p(f"| With descendants (subtree > 0) | {with_desc} |")
    _p(f"| Without descendants | {n_all - with_desc} |")
    _p(f"| Unique descendants reachable from gen-1 | {unique_desc_count} |")
    _p(f"| Sum of per-subtree sizes | {summed_desc} |")
    _p(f"| Subtree overlap (shared descendants) | {summed_desc - unique_desc_count} |")
    _blank()

    # Non-respondent roster
    _h(3, "Non-Respondent First-Generation Students")
    _blank()
    _p("| Name | Node ID |")
    _p("|---|---|")
    for n in sorted(gen1_nonresp, key=lambda x: x["last_name"]):
        _p(f"| {n['first_name']} {n['last_name']} | {n['node_id']} |")
    _blank()

    # Subtree ranking
    _h(3, "Subtree Sizes (All Gen-1, Ranked)")
    _blank()
    _p(
        "Descendant counts are **lower bounds** and exclude other generation-1 students "
        "even when cross-gen-1 advising edges exist. Respondents with missing Q12a "
        "student lists and unresolved branches will be understated."
    )
    _blank()
    ranked = sorted(gen1_all, key=lambda n: -n["descendant_count"])
    top = [n for n in ranked if n["descendant_count"] > 0]
    _p("| Rank | Name | Descendants | Q12a Status |")
    _p("|---|---|---|---|")
    for i, n in enumerate(top, 1):
        _p(f"| {i} | {n['first_name']} {n['last_name']} | "
           f"{n['descendant_count']} | {_q12a_status(n)} |")
    _blank()

    _p(f"**Summary of subtree sizes (all {n_all} gen-1):** "
       f"mean={subtree_stats['mean']:.1f}, "
       f"median={subtree_stats['median']:.1f}, "
       f"min={subtree_stats['min']}, "
       f"max={subtree_stats['max']}, "
       f"std={subtree_stats['std']:.1f}")
    _blank()

    # Q12a censoring note
    q12a_missing = [n for n in gen1_all
                    if _q12a_status(n) == "q12a_missing"]
    if q12a_missing:
        _p(f"**Q12a-censored gen-1 nodes ({len(q12a_missing)}):** "
           "these respondents reported supervising PhD students (Q12=Yes) "
           "but provided no student list. Their subtree counts are "
           "mechanically zero.")
        for n in sorted(q12a_missing, key=lambda x: x["last_name"]):
            _p(f"- {n['first_name']} {n['last_name']}")
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

    # Excluded/disputed appendix
    _h(3, "Excluded or Disputed Gen-1-Adjacent Respondents")
    _blank()
    if discrepancy_available:
        _p(
            "Primary Gen-1 headline counts use the strict final network universe only. "
            f"{exclusion_summary['total']} respondent cases are listed here for audit and "
            "excluded from headline Gen-1 counts. This appendix overlaps with, but is "
            "not identical to, the blank-generation count reported in Caveats."
        )
        _blank()
        if exclusion_rows:
            _p("| Reason | Count |")
            _p("|---|---|")
            for category, count in sorted(
                exclusion_summary["by_category"].items(),
                key=lambda item: (_category_label(item[0]), item[0]),
            ):
                _p(f"| {_category_label(category)} | {count} |")
            _blank()
            _p("| Name | Reason | Final Generation | Q12 |")
            _p("|---|---|---|---|")
            for row in exclusion_rows:
                final_gen = row["final_generation"] or "Unassigned"
                name = " ".join(part for part in (row["first_name"], row["last_name"]) if part)
                _p(f"| {name} | {row['category_label']} | {final_gen} | {row['raw_q12']} |")
        else:
            _p("No excluded or disputed respondent cases for this snapshot.")
        _blank()
    else:
        _p("No `Network_Discrepancies` file was available for this snapshot, so the exclusion/dispute appendix could not be generated.")
        _blank()

    # --- Section 2: Metadata coverage (all gen-1) ---
    _h(2, "Metadata Coverage (All Gen-1)")
    _blank()
    _p(
        f"Field coverage across all {n_all} gen-1 nodes. Non-respondent fields "
        "come from backfilled research; respondent fields come from "
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
    _p("| Field | All Gen-1 | Respondent | Non-respondent |")
    _p("|---|---|---|---|")
    for field, label in coverage_fields_full:
        all_ct = sum(1 for n in gen1_all if n.get(field, "").strip())
        resp_ct = sum(1 for n in gen1_resp if n.get(field, "").strip())
        nonresp_ct = sum(1 for n in gen1_nonresp if n.get(field, "").strip())
        _p(f"| {label} | {_format_coverage_cell(all_ct, n_all)} "
           f"| {_format_coverage_cell(resp_ct, n_resp)} "
           f"| {_format_coverage_cell(nonresp_ct, n_nonresp)} |")
    _blank()

    # --- Section 3: Distributions (all gen-1 with data) ---
    _h(2, "First-Generation Distributions")
    _blank()
    _p(
        f"Statistics use all {n_all} gen-1 nodes with nonblank values for each field "
        "(includes backfilled data). Has-students uses respondent-only data "
        f"(N={n_resp}) because nonrespondent has_students values are mechanical defaults, "
        "not survey answers."
    )
    _blank()

    # PhD year
    years = [int(n["phd_year"]) for n in gen1_all if n["phd_year"].strip()]
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
        n["phd_institution_canon"] for n in gen1_all
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
        n["current_employer_canon"] for n in gen1_all
        if n["current_employer_canon"].strip()
    )
    emp_blank = sum(1 for n in gen1_all if not n["current_employer_canon"].strip())
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
        harmonize_country(n["country"]) for n in gen1_all if n["country"].strip()
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
        n["us_state"] for n in gen1_all if n["us_state"].strip()
    )
    _h(3, "US State")
    _blank()
    us_count = sum(
        1 for n in gen1_all
        if harmonize_country(n["country"].strip()) == "United States"
    )
    _p(f"- US-based gen-1: {us_count}")
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
    _p(f"Universe: {n_resp} respondent gen-1 nodes only. Nonrespondent "
       "has_students=False is a mechanical default, not a survey answer.")
    _blank()
    _p(f"- Yes: {has_stu} / {n_resp} ({100*has_stu/n_resp:.1f}%)")
    _p(f"- No: {n_resp - has_stu} / {n_resp}")
    _blank()
    _p("**Has-students rate by PhD-year cohort** (respondent gen-1 only):")
    _blank()
    _p("| Cohort | N | Has Students | Rate |")
    _p("|---|---|---|---|")
    for label, lo, hi in PHD_YEAR_BINS:
        cohort = [n for n in gen1_resp
                  if n["phd_year"].strip() and lo <= int(n["phd_year"]) <= hi]
        yes = sum(1 for n in cohort if n["has_students"] == "True")
        rate = f"{100*yes/len(cohort):.0f}%" if cohort else "n/a"
        _p(f"| {label} | {len(cohort)} | {yes} | {rate} |")
    _blank()

    # --- Caveats ---
    _h(2, "Caveats")
    _blank()
    q12a_miss_gen1 = sum(1 for n in gen1_all
                         if _q12a_status(n) == "q12a_missing")
    _p(f"1. **Subtree counts are lower bounds.** {q12a_miss_gen1} gen-1 respondents "
       "answered Q12=Yes but provided no Q12a student list (their subtree sizes are "
       "mechanically zero). Across all generations, "
       f"{validation_summary['all_generation_q12_yes_without_q12a']} respondents have "
       f"this gap. {validation_summary['unresolved_edges_total']} unresolved edges also "
       "reduce coverage.")
    _p(f"2. **Subtree overlap.** {summed_desc - unique_desc_count} descendants appear "
       f"in multiple gen-1 subtrees (shared advisory relationships). Per-subtree sizes "
       f"are correct; the sum of per-subtree sizes ({summed_desc}) exceeds unique "
       f"descendants ({unique_desc_count}).")
    _p(f"3. **Distributions include backfilled nonrespondents.** The {n_nonresp} "
       "non-respondent gen-1 nodes have metadata from backfilled research. "
       "Distributions use all gen-1 nodes with nonblank values for "
       "each field, so backfilled data is reflected. Exception: has-students uses "
       f"respondent-only data (N={n_resp}) because nonrespondent has_students=False "
       "is a mechanical default, not a survey answer.")
    _p(f"4. **Country values should now be canonical in the node CSV.** This script "
       "retains a small alias map as a defensive fallback for older snapshots, but "
       "current rebuilds should already use short-form labels such as \"United States\" "
       "and \"United Kingdom\".")
    _p("5. **Canonical institution/employer mappings are incomplete.** "
       f"{validation_summary['unmapped_phd_count']} PhD institution values and "
       f"{validation_summary['unmapped_employer_count']} employer values lack canonical "
       "mappings. "
       "Affected respondents appear as blank in canonical counts but retain raw values "
       "in the subtree roster.")
    if discrepancy_available:
        _p(
            f"6. **{validation_summary['blank_generation_count']} respondent nodes have no assigned generation** overall. "
            f"Separately, {exclusion_summary['total']} respondent cases appear in the "
            "Gen-1 exclusion appendix and are excluded from headline Gen-1 counts; "
            "these counts overlap but are not identical."
        )
    else:
        _p(f"6. **{validation_summary['blank_generation_count']} respondent nodes have no "
           "assigned generation** and are excluded "
           "from generation-1 counts. See validation report for details.")
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
        description="Descriptive statistics for Mokyr first-generation students."
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
    parser.add_argument("--discrepancies", default=None, help="Path to network discrepancy CSV.")
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
    nodes_path = Path(args.nodes) if args.nodes else (
        PROJECT_ROOT / "Data" / "Derived" / f"Network_Nodes_{date_token}.csv"
    )
    edges_path = Path(args.edges) if args.edges else (
        PROJECT_ROOT / "Data" / "Derived" / f"Network_Edges_{date_token}.csv"
    )
    coverage_path = Path(args.coverage) if args.coverage else (
        PROJECT_ROOT / "Data" / "Derived" / f"Descriptive_Validation_Coverage_{date_token}.csv"
    )
    generation_path = Path(args.generation) if args.generation else (
        PROJECT_ROOT / "Data" / "Derived" / f"Descriptive_Validation_Generation_{date_token}.csv"
    )
    canon_path = Path(args.canon) if args.canon else (
        PROJECT_ROOT / "Data" / "Derived" / f"Descriptive_Validation_Canon_{date_token}.csv"
    )
    discrepancies_path = Path(args.discrepancies) if args.discrepancies else (
        PROJECT_ROOT / "Data" / "Derived" / f"Network_Discrepancies_{date_token}.csv"
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
    if args.discrepancies and not discrepancies_path.exists():
        sys.exit(f"ERROR: discrepancies file not found: {discrepancies_path}")

    out_dir = Path(args.output_dir) if args.output_dir else (
        PROJECT_ROOT / "Data" / "Derived"
    )
    md_dir = Path(args.md_dir) if args.md_dir else (PROJECT_ROOT / "Output")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    nodes = load_csv(nodes_path)
    edges = load_csv(edges_path)
    coverage_rows = load_csv(coverage_path)
    generation_rows = load_csv(generation_path)
    canon_rows = load_csv(canon_path)
    discrepancy_available = discrepancies_path.exists()
    discrepancy_rows = load_csv(discrepancies_path) if discrepancy_available else []
    print(f"Loaded {len(nodes)} nodes, {len(edges)} edges.")

    # Filter gen-1
    gen1_all = [
        n for n in nodes
        if n["generation"] == "1" and n["node_id"] != "JM-ROOT"
    ]
    gen1_resp = [n for n in gen1_all if n["is_respondent"] == "True"]
    gen1_nonresp = [n for n in gen1_all if n["is_respondent"] != "True"]
    print(f"Gen-1: {len(gen1_all)} total, {len(gen1_resp)} respondent, "
          f"{len(gen1_nonresp)} non-respondent.")
    gen1_ids = {n["node_id"] for n in gen1_all}
    exclusion_rows = build_exclusion_rows(discrepancy_rows, gen1_ids)
    exclusion_summary = build_exclusion_summary(exclusion_rows)

    # Compute subtrees
    adj = build_adjacency(edges)
    descendant_summary = build_descendant_summary(gen1_all, adj)
    for n in gen1_all:
        n["descendant_count"] = len(descendant_summary["sets"][n["node_id"]])

    desc_counts = [n["descendant_count"] for n in gen1_all]
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
    headlines_path = out_dir / f"First_Generation_Headlines_{date_token}.csv"
    subtree_path = out_dir / f"First_Generation_Subtree_Sizes_{date_token}.csv"
    profile_path = out_dir / f"First_Generation_Profile_{date_token}.csv"
    coverage_out_path = out_dir / f"First_Generation_Metadata_Coverage_{date_token}.csv"
    excluded_path = out_dir / f"First_Generation_Excluded_{date_token}.csv"
    md_path = md_dir / f"First_Generation_Descriptives_{date_token}.md"

    write_headlines(gen1_all, gen1_resp, gen1_nonresp, descendant_summary, exclusion_summary, headlines_path)
    print(f"Wrote {headlines_path.name}")

    write_subtree_sizes(gen1_all, subtree_path)
    print(f"Wrote {subtree_path.name}")

    write_profile(gen1_all, gen1_resp, profile_path)
    print(f"Wrote {profile_path.name}")

    write_metadata_coverage(gen1_all, gen1_resp, gen1_nonresp, coverage_out_path)
    print(f"Wrote {coverage_out_path.name}")

    write_excluded_roster(exclusion_rows, excluded_path)
    print(f"Wrote {excluded_path.name}")

    write_markdown(
        gen1_all,
        gen1_resp,
        gen1_nonresp,
        subtree_stats,
        nodes,
        descendant_summary,
        validation_summary,
        exclusion_rows,
        exclusion_summary,
        discrepancy_available,
        date_token,
        md_path,
    )
    print(f"Wrote {md_path.name}")

    print("Done.")


if __name__ == "__main__":
    main()
