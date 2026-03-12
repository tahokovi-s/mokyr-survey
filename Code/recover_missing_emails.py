"""
recover_missing_emails.py

Cross-references Q12a derived file with Wave 2/3/4 contact lists to recover
emails for students with no email on file.

Output: Data/Derived/Advisors_and_Reported_Students_{date}_Enriched.csv

Usage:
    python3 Code/recover_missing_emails.py [--date 022226]
"""

import argparse
import csv
import difflib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

WAVE_FILES = [
    ("Data/Contact_Lists/Mokyr_Survey_Wave2.csv", "Wave2"),
    ("Data/Contact_Lists/Mokyr_Survey_Wave3.csv", "Wave3"),
    ("Data/Contact_Lists/Mokyr_Survey_Wave4.csv", "Wave4"),
]

FUZZY_CUTOFF = 0.85


def normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def build_lookup(wave_files: list[tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """
    Returns dict: normalized_full_name -> (email, source_label)
    Rows with empty email are skipped.
    Later waves overwrite earlier ones for the same name.
    """
    lookup: dict[str, tuple[str, str]] = {}
    for rel_path, label in wave_files:
        path = PROJECT_ROOT / rel_path
        if not path.exists():
            print(f"  [warn] {path} not found — skipping")
            continue
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                first = row.get("First Name", "").strip()
                last = row.get("Last Name", "").strip()
                email = row.get("Email", "").strip().rstrip(";")
                if not email or not first or not last:
                    continue
                key = normalize(f"{first} {last}")
                lookup[key] = (email, label)
    return lookup


def match_email(
    full_name: str,
    lookup: dict[str, tuple[str, str]],
    fuzzy_cutoff: float = FUZZY_CUTOFF,
) -> tuple[str, str, str]:
    """
    Returns (email, source, match_type) or ("", "", "").
    match_type is "exact" or "fuzzy".
    """
    key = normalize(full_name)
    if key in lookup:
        email, source = lookup[key]
        return email, source, "exact"
    # Fuzzy fallback
    candidates = difflib.get_close_matches(key, lookup.keys(), n=1, cutoff=fuzzy_cutoff)
    if candidates:
        email, source = lookup[candidates[0]]
        return email, source, f"fuzzy({candidates[0]})"
    return "", "", ""


def main():
    parser = argparse.ArgumentParser(description="Recover missing emails from contact lists")
    parser.add_argument("--date", default="022226", help="Date suffix for Q12a file (MMDDYY)")
    args = parser.parse_args()

    q12a_path = PROJECT_ROOT / f"Data/Derived/Advisors_and_Reported_Students_{args.date}.csv"
    if not q12a_path.exists():
        raise FileNotFoundError(f"Q12a file not found: {q12a_path}")

    out_path = PROJECT_ROOT / f"Data/Derived/Advisors_and_Reported_Students_{args.date}_Enriched.csv"

    print(f"Loading contact lists...")
    lookup = build_lookup(WAVE_FILES)
    print(f"  {len(lookup)} name→email entries loaded")

    rows = []
    with q12a_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            rows.append(dict(row))

    total = len(rows)
    originally_missing = sum(1 for r in rows if not r.get("Student_Email", "").strip())
    recovered = 0
    still_missing_names = []

    for row in rows:
        row["Email_Recovered"] = ""
        row["Email_Source"] = ""
        row["Match_Type"] = ""

        if row.get("Student_Email", "").strip():
            # Already has email — nothing to do
            continue

        name = row.get("Student_Info_Cleaned", "").strip()
        if not name:
            continue

        email, source, match_type = match_email(name, lookup)
        if email:
            row["Email_Recovered"] = email
            row["Email_Source"] = source
            row["Match_Type"] = match_type
            recovered += 1
        else:
            advisor = f"{row.get('Advisor_FirstName', '')} {row.get('Advisor_LastName', '')}".strip()
            still_missing_names.append(f"{name} (advisor: {advisor})")

    out_fieldnames = fieldnames + ["Email_Recovered", "Email_Source", "Match_Type"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nResults:")
    print(f"  Total Q12a students:    {total}")
    print(f"  Originally missing email: {originally_missing}")
    print(f"  Recovered via lookup:   {recovered}")
    print(f"  Still missing:          {originally_missing - recovered}")
    print(f"\nStill missing ({len(still_missing_names)}):")
    for name in still_missing_names:
        print(f"  - {name}")
    print(f"\nOutput: {out_path}")


if __name__ == "__main__":
    main()
