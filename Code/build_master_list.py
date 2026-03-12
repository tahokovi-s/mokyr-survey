#!/usr/bin/env python3
"""
build_master_list.py — Build a master contact list CSV with one row per person
in the Mokyr genealogy network.

Merges data from:
  - Network_Nodes (primary key: node_id)
  - Network_Edges (advisor relationships)
  - Advisors_and_Reported_Students (Q12a emails)
  - Wave contact lists (email_contact_list)
  - Cleaned survey responses (email_survey from Q3)

Usage:
    python3 Code/build_master_list.py [--date 030226]

Output:
    Data/Derived/Master_Contact_List_{date}.csv
"""

import argparse
import csv
import sys
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_csv(path):
    """Load a CSV file and return list of dicts."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def normalize(s):
    """Lowercase, strip whitespace."""
    return s.strip().lower() if s else ""


def split_emails(raw_email):
    """Split a possibly semicolon-delimited email string into individual emails."""
    parts = re.split(r'[;\s]+', raw_email or "")
    return [normalize(part) for part in parts if "@" in normalize(part)]


def split_name(full_name):
    """Split 'First Last' into (first, last). Handles multi-part first names."""
    parts = full_name.strip().rsplit(" ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return full_name.strip(), ""


def clean_contact_email(raw_email):
    """Clean contact list emails: strip semicolons, take first if multiple."""
    if not raw_email:
        return ""
    # Some wave CSVs have trailing semicolons and multiple emails separated by ;
    emails = [e.strip() for e in raw_email.split(";") if e.strip()]
    return emails[0] if emails else ""


def main():
    parser = argparse.ArgumentParser(description="Build master contact list CSV")
    parser.add_argument(
        "--date",
        default="030226",
        help="Date suffix for input/output files (MMDDYY, default: 030226)",
    )
    parser.add_argument(
        "--nodes",
        help="Path to Network_Nodes CSV (default: auto from --date)",
    )
    parser.add_argument(
        "--edges",
        help="Path to Network_Edges CSV (default: auto from --date)",
    )
    parser.add_argument(
        "--q12a",
        help="Path to Advisors_and_Reported_Students CSV (default: auto from --date)",
    )
    parser.add_argument(
        "--cleaned",
        help="Path to cleaned survey CSV (default: auto from --date)",
    )
    parser.add_argument(
        "--output",
        help="Output path (default: Data/Derived/Master_Contact_List_{date}.csv)",
    )
    args = parser.parse_args()

    date = args.date
    derived = PROJECT_ROOT / "Data" / "Derived"
    contact_dir = PROJECT_ROOT / "Data" / "Contact_Lists"
    cleaned_dir = PROJECT_ROOT / "Data" / "Cleaned"

    # Input files default to the 022226 dataset (the latest available).
    # Override with --nodes, --edges, --q12a, --cleaned for newer exports.
    input_date = "022226"
    nodes_path = Path(args.nodes) if args.nodes else derived / f"Network_Nodes_{input_date}.csv"
    edges_path = Path(args.edges) if args.edges else derived / f"Network_Edges_{input_date}.csv"
    q12a_path = Path(args.q12a) if args.q12a else derived / f"Advisors_and_Reported_Students_{input_date}.csv"
    cleaned_path = (
        Path(args.cleaned)
        if args.cleaned
        else cleaned_dir / f"Mokyr_Survey_Responses_{input_date}_Cleaned.csv"
    )
    output_path = (
        Path(args.output)
        if args.output
        else derived / f"Master_Contact_List_{date}.csv"
    )

    # --- Load all data sources ---
    print(f"Loading Network_Nodes from {nodes_path}")
    nodes = load_csv(nodes_path)
    print(f"  {len(nodes)} nodes loaded")

    print(f"Loading Network_Edges from {edges_path}")
    edges = load_csv(edges_path)
    print(f"  {len(edges)} edges loaded")

    print(f"Loading Q12a from {q12a_path}")
    q12a_rows = load_csv(q12a_path)
    print(f"  {len(q12a_rows)} Q12a rows loaded")

    print(f"Loading cleaned survey from {cleaned_path}")
    cleaned = load_csv(cleaned_path)
    print(f"  {len(cleaned)} survey responses loaded")

    # Load all wave contact lists
    wave_files = sorted(contact_dir.glob("Mokyr_Survey_Wave*.csv"))
    contact_rows = []
    for wf in wave_files:
        rows = load_csv(wf)
        contact_rows.extend(rows)
        print(f"  Loaded {len(rows)} contacts from {wf.name}")
    print(f"  {len(contact_rows)} total contact list entries")

    # --- Build lookup structures ---

    # 1. Node index by node_id
    node_by_id = {n["node_id"]: n for n in nodes}

    # 2. Advisor lookup: for each target_id, collect source node names.
    #    Prefer explicit "advisor" edges. If missing, fall back to q12a/manual
    #    parent links so non-respondent student nodes still get advisor names.
    advisor_map_primary = {}   # target_id -> list of advisors from "advisor" edges
    advisor_map_fallback = {}  # target_id -> list of advisors from "q12a"/"manual"

    def add_unique_name(mapping, target_id, advisor_name):
        names = mapping.setdefault(target_id, [])
        if advisor_name not in names:
            names.append(advisor_name)

    for e in edges:
        target = e["target_id"]
        source = e["source_id"]
        edge_type = e.get("edge_type", "").strip().lower()

        if source in node_by_id:
            src = node_by_id[source]
            advisor_name = f"{src['first_name']} {src['last_name']}".strip()
        else:
            advisor_name = source  # fallback to ID

        if edge_type == "advisor":
            add_unique_name(advisor_map_primary, target, advisor_name)
        elif edge_type in {"q12a", "manual"}:
            add_unique_name(advisor_map_fallback, target, advisor_name)

    # 3. Q12a email lookup: match students to node_ids by name and email
    #    Build node lookup helpers
    node_by_name = {}
    node_by_email = {}
    for n in nodes:
        key = (normalize(n["first_name"]), normalize(n["last_name"]))
        # If duplicate names, prefer the one that is a respondent
        if key not in node_by_name or n["is_respondent"] == "True":
            node_by_name[key] = n["node_id"]
        for email in split_emails(n["email"]):
            node_by_email[email] = n["node_id"]

    q12a_email_by_nid = {}  # node_id -> semicolon-joined student email(s) from Q12a
    q12a_unmatched = 0
    for row in q12a_rows:
        student_name = row["Student_Info_Cleaned"].strip()
        student_emails = split_emails(row.get("Student_Email", ""))
        first, last = split_name(student_name)
        name_key = (normalize(first), normalize(last))

        # Try name match first, then email match
        nid = node_by_name.get(name_key)
        if not nid and student_emails:
            for email in student_emails:
                nid = node_by_email.get(email)
                if nid:
                    break
        if nid and student_emails:
            existing = split_emails(q12a_email_by_nid.get(nid, ""))
            merged = []
            seen = set()
            for email in existing + student_emails:
                if email not in seen:
                    seen.add(email)
                    merged.append(email)
            q12a_email_by_nid[nid] = ";".join(merged)
        elif not nid:
            q12a_unmatched += 1

    print(f"  Q12a emails matched to nodes: {len(q12a_email_by_nid)}, unmatched: {q12a_unmatched}")

    # 4. Survey email lookup: ResponseId -> Q3 email
    #    node_id = "R-" + ResponseId
    survey_email_by_nid = {}
    for row in cleaned:
        rid = row["ResponseId"]
        nid = "R-" + rid
        q3_email = row.get("Q3", "").strip()
        if q3_email:
            survey_email_by_nid[nid] = q3_email

    print(f"  Survey emails (Q3) matched: {len(survey_email_by_nid)}")

    # 5. Contact list email lookup: match by name or email to node_id
    #    Contact lists have "First Name", "Last Name", "Email"
    contact_email_by_nid = {}
    contact_matched = 0
    contact_unmatched = 0
    for row in contact_rows:
        first = row.get("First Name", "").strip()
        last = row.get("Last Name", "").strip()
        raw_email = row.get("Email", "").strip()
        email = clean_contact_email(raw_email)
        if not email:
            continue

        name_key = (normalize(first), normalize(last))
        nid = node_by_name.get(name_key)
        if not nid and email:
            nid = node_by_email.get(normalize(email))

        if nid:
            # Keep first contact email found for each node
            if nid not in contact_email_by_nid:
                contact_email_by_nid[nid] = email
            contact_matched += 1
        else:
            contact_unmatched += 1

    print(
        f"  Contact list emails matched: {len(contact_email_by_nid)} unique nodes "
        f"({contact_matched} entries matched, {contact_unmatched} unmatched)"
    )

    # --- Build master rows ---
    output_rows = []
    for n in nodes:
        nid = n["node_id"]
        advisors = advisor_map_primary.get(nid, [])
        if not advisors:
            advisors = advisor_map_fallback.get(nid, [])
        advisor_str = "; ".join(advisors)

        is_resp = n.get("is_respondent", "False") == "True"
        gen = n.get("generation", "")

        row = {
            "node_id": nid,
            "first_name": n["first_name"],
            "last_name": n["last_name"],
            "advisor": advisor_str,
            "phd_institution": n.get("phd_institution_canon", ""),
            "current_employer": n.get("current_employer_canon", ""),
            "email_survey": survey_email_by_nid.get(nid, ""),
            "email_q12a": q12a_email_by_nid.get(nid, ""),
            "email_contact_list": contact_email_by_nid.get(nid, ""),
            "responded": 1 if is_resp else 0,
            "generation": gen,
        }
        output_rows.append(row)

    assert len(output_rows) == len(nodes), (
        f"Row count mismatch: {len(output_rows)} output rows vs {len(nodes)} nodes"
    )

    # --- Sort: generation ascending (blanks last), then last_name ---
    def sort_key(r):
        gen = r["generation"]
        if gen == "" or gen is None:
            gen_num = 999
        else:
            try:
                gen_num = int(gen)
            except ValueError:
                gen_num = 999
        return (gen_num, r["last_name"].lower(), r["first_name"].lower())

    output_rows.sort(key=sort_key)

    # --- Write output ---
    fieldnames = [
        "first_name",
        "last_name",
        "advisor",
        "phd_institution",
        "current_employer",
        "email_survey",
        "email_q12a",
        "email_contact_list",
        "responded",
        "generation",
        "node_id",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nOutput written to {output_path}")

    # --- Summary statistics ---
    total = len(output_rows)
    responded = sum(1 for r in output_rows if r["responded"] == 1)
    has_survey_email = sum(1 for r in output_rows if r["email_survey"])
    has_q12a_email = sum(1 for r in output_rows if r["email_q12a"])
    has_contact_email = sum(1 for r in output_rows if r["email_contact_list"])
    has_any_email = sum(
        1
        for r in output_rows
        if r["email_survey"] or r["email_q12a"] or r["email_contact_list"]
    )
    has_advisor = sum(1 for r in output_rows if r["advisor"])
    has_generation = sum(1 for r in output_rows if r["generation"] != "")

    # Generation distribution
    gen_counts = {}
    for r in output_rows:
        g = r["generation"] if r["generation"] != "" else "blank"
        gen_counts[g] = gen_counts.get(g, 0) + 1

    print(f"\n{'='*50}")
    print(f"MASTER CONTACT LIST SUMMARY")
    print(f"{'='*50}")
    print(f"Total rows:              {total}")
    print(f"Responded to survey:     {responded}")
    print(f"Non-respondents:         {total - responded}")
    print(f"")
    print(f"Email coverage:")
    print(f"  email_survey (Q3):     {has_survey_email} ({100*has_survey_email/total:.1f}%)")
    print(f"  email_q12a:            {has_q12a_email} ({100*has_q12a_email/total:.1f}%)")
    print(f"  email_contact_list:    {has_contact_email} ({100*has_contact_email/total:.1f}%)")
    print(f"  any email:             {has_any_email} ({100*has_any_email/total:.1f}%)")
    print(f"  no email at all:       {total - has_any_email}")
    print(f"")
    print(f"Has advisor listed:      {has_advisor}")
    print(f"Has generation:          {has_generation}")
    print(f"")
    print(f"Generation distribution:")
    for g in sorted(gen_counts.keys(), key=lambda x: (x == "blank", x)):
        print(f"  gen {g}: {gen_counts[g]}")


if __name__ == "__main__":
    main()
