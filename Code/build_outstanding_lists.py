#!/usr/bin/env python3
"""
Build validated outstanding outreach lists from the master contact list.

Outputs:
  Data/Derived/Outstanding_People_{date}_Validated.csv
  Data/Derived/Outstanding_Advisor_Summary_{date}_Validated.csv
"""

import argparse
import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER_PATTERN = re.compile(r"^Master_Contact_List_(\d{6})\.csv$")

EMAIL_FIELDS = [
    "email_network",
    "email_survey",
    "email_q12a",
    "email_contact_list",
]


def parse_mmddyy(token: str) -> datetime:
    return datetime.strptime(token, "%m%d%y")


def latest_master_path() -> Path:
    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    matches = []
    for path in derived_dir.iterdir():
        match = MASTER_PATTERN.match(path.name)
        if match:
            matches.append((parse_mmddyy(match.group(1)), path))
    if not matches:
        raise FileNotFoundError("No Master_Contact_List_*.csv files found under Data/Derived")
    matches.sort()
    return matches[-1][1]


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
    return (value or "").strip().lower()


def parse_bool(value: str) -> bool:
    return normalize_text(value) in {"1", "true", "yes"}


def sort_generation(value: str) -> tuple[int, str]:
    raw = (value or "").strip()
    if not raw:
        return (999, "")
    try:
        return (int(raw), raw)
    except ValueError:
        return (999, raw)


def has_any_email(row: dict) -> bool:
    return any((row.get(field, "") or "").strip() for field in EMAIL_FIELDS)


def build_outstanding_people(master_rows: list[dict]) -> list[dict]:
    rows = []
    for row in master_rows:
        if parse_bool(row.get("responded", "")):
            continue
        if not has_any_email(row):
            continue
        rows.append(
            {
                "first_name": row.get("first_name", "").strip(),
                "last_name": row.get("last_name", "").strip(),
                "advisor": row.get("advisor", "").strip(),
                "generation": row.get("generation", "").strip(),
                "email_network": row.get("email_network", "").strip(),
                "email_survey": row.get("email_survey", "").strip(),
                "email_q12a": row.get("email_q12a", "").strip(),
                "email_contact_list": row.get("email_contact_list", "").strip(),
                "node_id": row.get("node_id", "").strip(),
            }
        )

    rows.sort(
        key=lambda row: (
            row["advisor"] == "",
            normalize_text(row["advisor"]),
            sort_generation(row["generation"]),
            normalize_text(row["last_name"]),
            normalize_text(row["first_name"]),
            normalize_text(row["node_id"]),
        )
    )
    return rows


def build_advisor_summary(outstanding_rows: list[dict]) -> list[dict]:
    advisor_people: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in outstanding_rows:
        advisor = row.get("advisor", "").strip()
        full_name = " ".join(
            part for part in (row.get("first_name", "").strip(), row.get("last_name", "").strip()) if part
        )
        advisor_people[advisor].append((normalize_text(full_name), full_name))

    summary_rows = []
    for advisor, people in advisor_people.items():
        sorted_people = [display for _, display in sorted(people)]
        summary_rows.append(
            {
                "advisor": advisor,
                "outstanding_count": len(sorted_people),
                "outstanding_people": "; ".join(sorted_people),
            }
        )

    summary_rows.sort(
        key=lambda row: (
            -int(row["outstanding_count"]),
            row["advisor"] == "",
            normalize_text(row["advisor"]),
        )
    )
    return summary_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build validated outstanding outreach lists from the master contact list"
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Date suffix for default input/output paths (MMDDYY, defaults to latest master list date)",
    )
    parser.add_argument(
        "--master",
        default=None,
        help="Path to Master_Contact_List CSV (default: Data/Derived/Master_Contact_List_{date}.csv)",
    )
    parser.add_argument(
        "--output-people",
        default=None,
        help="Output CSV for validated outstanding people",
    )
    parser.add_argument(
        "--output-advisors",
        default=None,
        help="Output CSV for advisor-level outstanding summary",
    )
    args = parser.parse_args()

    if args.master:
        master_path = Path(args.master)
        if not master_path.is_absolute():
            master_path = PROJECT_ROOT / master_path
        date_token_match = re.search(r"(\d{6})", master_path.name)
        date_token = args.date or (date_token_match.group(1) if date_token_match else None)
    else:
        if args.date:
            date_token = args.date
            master_path = PROJECT_ROOT / "Data" / "Derived" / f"Master_Contact_List_{date_token}.csv"
        else:
            master_path = latest_master_path()
            match = MASTER_PATTERN.match(master_path.name)
            date_token = match.group(1) if match else None

    if not date_token:
        raise ValueError("Could not infer output date. Pass --date explicitly.")

    people_out = (
        Path(args.output_people)
        if args.output_people
        else PROJECT_ROOT / "Data" / "Derived" / f"Outstanding_People_{date_token}_Validated.csv"
    )
    advisor_out = (
        Path(args.output_advisors)
        if args.output_advisors
        else PROJECT_ROOT / "Data" / "Derived" / f"Outstanding_Advisor_Summary_{date_token}_Validated.csv"
    )
    if not people_out.is_absolute():
        people_out = PROJECT_ROOT / people_out
    if not advisor_out.is_absolute():
        advisor_out = PROJECT_ROOT / advisor_out

    master_rows = load_csv(master_path)
    outstanding_rows = build_outstanding_people(master_rows)
    advisor_summary_rows = build_advisor_summary(outstanding_rows)

    people_fields = [
        "first_name",
        "last_name",
        "advisor",
        "generation",
        "email_network",
        "email_survey",
        "email_q12a",
        "email_contact_list",
        "node_id",
    ]
    advisor_fields = [
        "advisor",
        "outstanding_count",
        "outstanding_people",
    ]

    write_csv(people_out, people_fields, outstanding_rows)
    write_csv(advisor_out, advisor_fields, advisor_summary_rows)

    total_outstanding = len(outstanding_rows)
    advisor_count = len(advisor_summary_rows)
    network_only = sum(
        1
        for row in outstanding_rows
        if row["email_network"] and not any(row[field] for field in EMAIL_FIELDS[1:])
    )

    print(f"Loaded master list: {master_path}")
    print(f"Outstanding people: {total_outstanding}")
    print(f"Advisors represented: {advisor_count}")
    print(f"Network-only email rows retained: {network_only}")
    print(f"Wrote people CSV: {people_out}")
    print(f"Wrote advisor summary CSV: {advisor_out}")


if __name__ == "__main__":
    main()
