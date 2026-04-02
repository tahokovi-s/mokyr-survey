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
    python3 Code/Network/build_master_list.py [--date 030226]

Defaults:
    - Network_Nodes / Network_Edges use the requested --date exactly
    - Q12a / cleaned survey prefer the requested --date, else fall back to the
      latest compatible snapshot not newer than --date

Output:
    Data/Derived/Master_Contact_List_{date}.csv
"""

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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


def parse_date_token(token):
    """Parse MMDDYY tokens used in dated CSV filenames."""
    return datetime.strptime(token, "%m%d%y")


def resolve_versioned_default(base_dir, prefix, suffix, requested_date):
    """Resolve a dated CSV, falling back to the latest compatible snapshot."""
    exact = base_dir / f"{prefix}{requested_date}{suffix}"
    if exact.exists():
        return exact, requested_date, "exact"

    requested_dt = parse_date_token(requested_date)
    candidates = []
    for path in base_dir.glob(f"{prefix}*{suffix}"):
        name = path.name
        if not (name.startswith(prefix) and name.endswith(suffix)):
            continue
        token = name[len(prefix):-len(suffix)]
        if len(token) != 6 or not token.isdigit():
            continue
        try:
            token_dt = parse_date_token(token)
        except ValueError:
            continue
        if token_dt <= requested_dt:
            candidates.append((token_dt, token, path))

    if not candidates:
        raise FileNotFoundError(
            f"No compatible input found for {prefix}*{suffix} at or before {requested_date}"
        )

    _, token, path = max(candidates)
    return path, token, "fallback"


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
        help="Path to Advisors_and_Reported_Students CSV (default: exact --date, else latest <= --date)",
    )
    parser.add_argument(
        "--cleaned",
        help="Path to cleaned survey CSV (default: exact --date, else latest <= --date)",
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

    # Network snapshots are date-pinned; primary survey inputs may lag behind a
    # newer auxiliary/network snapshot, so they fall back to the latest
    # compatible dated file when an exact match is unavailable.
    nodes_path = Path(args.nodes) if args.nodes else derived / f"Network_Nodes_{date}.csv"
    edges_path = Path(args.edges) if args.edges else derived / f"Network_Edges_{date}.csv"
    if args.q12a:
        q12a_path = Path(args.q12a)
        q12a_mode = "explicit"
        q12a_date = None
    else:
        q12a_path, q12a_date, q12a_mode = resolve_versioned_default(
            derived,
            "Advisors_and_Reported_Students_",
            ".csv",
            date,
        )
    if args.cleaned:
        cleaned_path = Path(args.cleaned)
        cleaned_mode = "explicit"
        cleaned_date = None
    else:
        cleaned_path, cleaned_date, cleaned_mode = resolve_versioned_default(
            cleaned_dir,
            "Mokyr_Survey_Responses_",
            "_Cleaned.csv",
            date,
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
    if q12a_mode == "fallback":
        print(f"  Requested date {date} has no Q12a file; using {q12a_date} instead")
    q12a_rows = load_csv(q12a_path)
    print(f"  {len(q12a_rows)} Q12a rows loaded")

    print(f"Loading cleaned survey from {cleaned_path}")
    if cleaned_mode == "fallback":
        print(f"  Requested date {date} has no cleaned survey file; using {cleaned_date} instead")
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
            "email_network": n.get("email", ""),
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
        "email_network",
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
    has_network_email = sum(1 for r in output_rows if r["email_network"])
    has_survey_email = sum(1 for r in output_rows if r["email_survey"])
    has_q12a_email = sum(1 for r in output_rows if r["email_q12a"])
    has_contact_email = sum(1 for r in output_rows if r["email_contact_list"])
    has_any_email = sum(
        1
        for r in output_rows
        if r["email_network"] or r["email_survey"] or r["email_q12a"] or r["email_contact_list"]
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
    print(f"  email_network:         {has_network_email} ({100*has_network_email/total:.1f}%)")
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
