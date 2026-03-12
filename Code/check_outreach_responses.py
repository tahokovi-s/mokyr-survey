#!/usr/bin/env python3
"""
Check new survey responses against outreach tracking files.

This script compares a cumulative raw Qualtrics export against an earlier raw
export, isolates only the new ResponseIds, and matches those responses back to
the March 3 non-respondent follow-up file and the March 8 Avner outreach file.

Outputs:
  - Data/Derived/Outreach_New_Responses_MMDDYY.csv
  - Data/Derived/Outreach_Status_MMDDYY.csv
  - Communications/Reports/Generated/Outreach_Response_Check_MMDDYY.md
"""

import argparse
import csv
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TRANSLIT_MAP = str.maketrans({
    "ø": "o",
    "Ø": "O",
    "ı": "i",
    "İ": "I",
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ð": "d",
    "Ð": "D",
    "þ": "th",
    "Þ": "Th",
    "ł": "l",
    "Ł": "L",
})

NICKNAME_EQUIVALENTS = {
    "tom": "thomas",
    "thomas": "tom",
    "bill": "william",
    "will": "william",
    "bob": "robert",
    "rob": "robert",
    "dave": "david",
    "jim": "james",
    "jimmy": "james",
    "joe": "joseph",
    "kate": "katherine",
    "katie": "katherine",
    "liz": "elizabeth",
    "beth": "elizabeth",
    "mike": "michael",
    "steve": "steven",
}


@dataclass
class Person:
    canonical_name: str
    name_variants: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    campaigns: set[str] = field(default_factory=set)
    non_respondent_action: str = ""
    avner_bucket: str = ""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Match new raw survey responses to outreach tracking files."
    )
    parser.add_argument(
        "--current-raw",
        required=True,
        help="Current cumulative raw Qualtrics export",
    )
    parser.add_argument(
        "--baseline-raw",
        required=True,
        help="Earlier cumulative raw Qualtrics export used as the baseline",
    )
    parser.add_argument(
        "--non-respondent",
        default="Data/Derived/Non_Respondent_Follow_Up_030326.csv",
        help="Non-respondent follow-up tracking CSV",
    )
    parser.add_argument(
        "--avner",
        default="Data/Derived/Avner_Student_Outreach_Buckets_030826.csv",
        help="Avner outreach tracking CSV",
    )
    parser.add_argument(
        "--output-responses",
        help="Optional override for matched new-response CSV output",
    )
    parser.add_argument(
        "--output-status",
        help="Optional override for outreach status CSV output",
    )
    parser.add_argument(
        "--output-summary",
        help="Optional override for markdown summary output",
    )
    return parser.parse_args()


def project_path(raw_path):
    path = Path(raw_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def extract_date_tag(path):
    match = re.search(r"_(\d{6})_", Path(path).name)
    if not match:
        raise ValueError(f"Could not infer MMDDYY tag from {path}")
    return match.group(1)


def normalize_text(text):
    text = (text or "").translate(TRANSLIT_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace('"', " ").replace("'", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_tokens(text):
    return normalize_text(text).split()


def same_person(name_a, name_b):
    tokens_a = normalize_tokens(name_a)
    tokens_b = normalize_tokens(name_b)
    if not tokens_a or not tokens_b:
        return None
    if tokens_a == tokens_b:
        return "name_exact"

    first_a, last_a = tokens_a[0], tokens_a[-1]
    first_b, last_b = tokens_b[0], tokens_b[-1]

    if last_a == last_b:
        if first_a == first_b:
            return "name_first_last"
        if NICKNAME_EQUIVALENTS.get(first_a) == first_b or NICKNAME_EQUIVALENTS.get(first_b) == first_a:
            return "name_nickname"
        if (len(first_a) == 1 and first_a == first_b[:1]) or (len(first_b) == 1 and first_b == first_a[:1]):
            return "name_initial"
        if first_a[:1] == first_b[:1]:
            if (first_a.startswith(first_b) or first_b.startswith(first_a)) and min(len(first_a), len(first_b)) >= 4:
                return "name_prefix"

    if SequenceMatcher(None, last_a, last_b).ratio() >= 0.90:
        if first_a == first_b:
            return "name_fuzzy_last"
        if SequenceMatcher(None, first_a, first_b).ratio() >= 0.85:
            return "name_fuzzy_full"
        if (len(first_a) == 1 and first_a == first_b[:1]) or (len(first_b) == 1 and first_b == first_a[:1]):
            return "name_initial_fuzzy_last"

    return None


def emails_from_cell(cell):
    emails = set()
    for part in (cell or "").replace(",", ";").split(";"):
        part = part.strip().lower()
        if "@" in part:
            emails.add(part)
    return emails


def read_raw_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    header = rows[0]
    data_rows = rows[3:]
    col_idx = {name: idx for idx, name in enumerate(header)}

    def get(row, column):
        idx = col_idx.get(column)
        if idx is None or idx >= len(row) or row[idx] is None:
            return ""
        return row[idx].strip()

    return [
        {
            "response_id": get(row, "ResponseId"),
            "recorded_date": get(row, "RecordedDate"),
            "status": get(row, "Status"),
            "finished": get(row, "Finished"),
            "progress": get(row, "Progress"),
            "respondent_name": f"{get(row, 'Q1')} {get(row, 'Q2')}".strip(),
            "survey_email": get(row, "Q3"),
            "recipient_email": get(row, "RecipientEmail"),
        }
        for row in data_rows
    ]


def add_or_merge_person(people, name, emails, campaign, non_respondent_action="", avner_bucket=""):
    matched_person = None
    for person in people:
        shared_email = emails and person.emails and emails & person.emails
        shared_name = any(same_person(name, variant) for variant in person.name_variants)
        if shared_email or shared_name:
            matched_person = person
            break

    if matched_person is None:
        matched_person = Person(canonical_name=name.strip() or "(blank)")
        people.append(matched_person)

    matched_person.name_variants.add(name.strip())
    matched_person.emails.update(emails)
    matched_person.campaigns.add(campaign)
    if non_respondent_action:
        matched_person.non_respondent_action = non_respondent_action
    if avner_bucket:
        matched_person.avner_bucket = avner_bucket


def load_people(non_respondent_path, avner_path):
    people = []

    with open(non_respondent_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = f"{row['first_name']} {row['last_name']}"
            emails = emails_from_cell(row.get("email_on_file", "")) | emails_from_cell(row.get("recommended_email", ""))
            add_or_merge_person(
                people,
                name=name,
                emails=emails,
                campaign="non_respondent_follow_up",
                non_respondent_action=row.get("recommended_action", ""),
            )

    with open(avner_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            add_or_merge_person(
                people,
                name=row["reviewed_identity"],
                emails=emails_from_cell(row.get("best_email", "")),
                campaign="avner_student_outreach",
                avner_bucket=row.get("bucket", ""),
            )

    return people


def score_match(response, person):
    reasons = []
    score = 0
    response_emails = {
        email.lower()
        for email in (response["survey_email"], response["recipient_email"])
        if email and "@" in email
    }

    email_overlap = sorted(response_emails & person.emails)
    if email_overlap:
        score += 100
        reasons.append("email")

    best_name_reason = None
    best_name_score = 0
    for variant in person.name_variants:
        reason = same_person(response["respondent_name"], variant)
        if reason is None:
            continue
        reason_score = {
            "name_exact": 95,
            "name_first_last": 90,
            "name_nickname": 80,
            "name_initial": 78,
            "name_prefix": 76,
            "name_fuzzy_last": 72,
            "name_fuzzy_full": 70,
            "name_initial_fuzzy_last": 68,
        }[reason]
        if reason_score > best_name_score:
            best_name_score = reason_score
            best_name_reason = reason

    if best_name_reason:
        score += best_name_score
        reasons.append(best_name_reason)

    return score, reasons, email_overlap


def match_responses(new_responses, people):
    matched = []
    unmatched = []
    for response in new_responses:
        best_person = None
        best_score = 0
        best_reasons = []
        best_email_overlap = []

        for person in people:
            score, reasons, email_overlap = score_match(response, person)
            if score > best_score:
                best_person = person
                best_score = score
                best_reasons = reasons
                best_email_overlap = email_overlap

        if best_person is None or best_score == 0:
            unmatched.append(response)
            continue

        record = dict(response)
        record["matched_person"] = best_person
        record["match_basis"] = "+".join(best_reasons)
        record["matched_email_overlap"] = ";".join(best_email_overlap)
        matched.append(record)

    return matched, unmatched


def write_responses_csv(path, matched, unmatched):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "matched",
        "response_id",
        "recorded_date",
        "finished",
        "progress",
        "respondent_name",
        "survey_email",
        "recipient_email",
        "matched_person_name",
        "campaign_membership",
        "non_respondent_action",
        "avner_bucket",
        "match_basis",
        "matched_email_overlap",
    ]

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for row in matched:
            person = row["matched_person"]
            writer.writerow(
                {
                    "matched": "yes",
                    "response_id": row["response_id"],
                    "recorded_date": row["recorded_date"],
                    "finished": row["finished"],
                    "progress": row["progress"],
                    "respondent_name": row["respondent_name"],
                    "survey_email": row["survey_email"],
                    "recipient_email": row["recipient_email"],
                    "matched_person_name": person.canonical_name,
                    "campaign_membership": campaign_membership(person),
                    "non_respondent_action": person.non_respondent_action,
                    "avner_bucket": person.avner_bucket,
                    "match_basis": row["match_basis"],
                    "matched_email_overlap": row["matched_email_overlap"],
                }
            )

        for row in unmatched:
            writer.writerow(
                {
                    "matched": "no",
                    "response_id": row["response_id"],
                    "recorded_date": row["recorded_date"],
                    "finished": row["finished"],
                    "progress": row["progress"],
                    "respondent_name": row["respondent_name"],
                    "survey_email": row["survey_email"],
                    "recipient_email": row["recipient_email"],
                }
            )


def campaign_membership(person):
    campaigns = sorted(person.campaigns)
    if campaigns == ["avner_student_outreach", "non_respondent_follow_up"]:
        return "both"
    if campaigns == ["avner_student_outreach"]:
        return "avner_only"
    if campaigns == ["non_respondent_follow_up"]:
        return "non_respondent_only"
    return "+".join(campaigns)


def best_response_for_person(person, matched):
    rows = [row for row in matched if row["matched_person"] is person]
    if not rows:
        return None
    return max(rows, key=lambda row: (row["finished"] == "True", row["recorded_date"], row["response_id"]))


def write_status_csv(path, people, matched):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "person_name",
        "campaign_membership",
        "non_respondent_action",
        "avner_bucket",
        "known_emails",
        "responded_since_baseline",
        "response_id",
        "recorded_date",
        "finished",
        "progress",
        "respondent_name",
        "survey_email",
        "recipient_email",
        "match_basis",
    ]

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for person in sorted(people, key=lambda item: normalize_text(item.canonical_name)):
            response = best_response_for_person(person, matched)
            writer.writerow(
                {
                    "person_name": person.canonical_name,
                    "campaign_membership": campaign_membership(person),
                    "non_respondent_action": person.non_respondent_action,
                    "avner_bucket": person.avner_bucket,
                    "known_emails": ";".join(sorted(person.emails)),
                    "responded_since_baseline": "yes" if response else "no",
                    "response_id": response["response_id"] if response else "",
                    "recorded_date": response["recorded_date"] if response else "",
                    "finished": response["finished"] if response else "",
                    "progress": response["progress"] if response else "",
                    "respondent_name": response["respondent_name"] if response else "",
                    "survey_email": response["survey_email"] if response else "",
                    "recipient_email": response["recipient_email"] if response else "",
                    "match_basis": response["match_basis"] if response else "",
                }
            )


def build_summary(current_raw, baseline_raw, people, matched, unmatched, non_respondent_path, avner_path):
    completed_matched = [row for row in matched if row["finished"] == "True"]
    incomplete_matched = [row for row in matched if row["finished"] != "True"]
    completed_unmatched = [row for row in unmatched if row["finished"] == "True"]
    incomplete_unmatched = [row for row in unmatched if row["finished"] != "True"]

    membership_counts = Counter(campaign_membership(row["matched_person"]) for row in completed_matched)

    with open(non_respondent_path, newline="", encoding="utf-8") as handle:
        non_respondent_rows = list(csv.DictReader(handle))
    with open(avner_path, newline="", encoding="utf-8") as handle:
        avner_rows = list(csv.DictReader(handle))

    avner_send_now_total = sum(row.get("bucket") == "send_now" for row in avner_rows)
    avner_send_now_responded = sum(
        1
        for person in people
        if person.avner_bucket == "send_now"
        and best_response_for_person(person, matched)
        and best_response_for_person(person, matched)["finished"] == "True"
    )

    list_overlap = sum(1 for person in people if person.campaigns == {"non_respondent_follow_up", "avner_student_outreach"})

    non_response_action_counts = Counter(
        row["matched_person"].non_respondent_action
        for row in completed_matched
        if "non_respondent_follow_up" in row["matched_person"].campaigns
    )

    fuzzy_or_alias = [
        row for row in completed_matched
        if row["match_basis"] not in {"email", "email+name_exact", "name_exact", "email+name_first_last", "name_first_last"}
    ]

    lines = [
        f"# Outreach Response Check — {extract_date_tag(current_raw)}",
        "",
        f"- Current raw export: `{Path(current_raw).name}`",
        f"- Baseline raw export: `{Path(baseline_raw).name}`",
        "- Matching method: ResponseId delta between raw exports, then match by known email plus normalized/fuzzy name variants.",
        "- Important caveat: this is list membership tracking, not a verified sent-email log.",
        "",
        "## New Activity Since Baseline",
        "",
        f"- New raw response records: {len(matched) + len(unmatched)}",
        f"- New completed responses: {len(completed_matched) + len(completed_unmatched)}",
        f"- New incomplete starts: {len(incomplete_matched) + len(incomplete_unmatched)}",
        f"- Completed responses matched to outreach union: {len(completed_matched)}",
        f"- Completed responses unmatched: {len(completed_unmatched)}",
        f"- Incomplete starts matched to outreach union: {len(incomplete_matched)}",
        "",
        "## Outreach Universe",
        "",
        f"- Non-respondent file rows: {len(non_respondent_rows)}",
        f"- Avner file rows: {len(avner_rows)}",
        f"- Overlap between the two files: {list_overlap}",
        f"- Unique people across both files: {len(people)}",
        "",
        "## Completed Respondents By Membership",
        "",
        f"- Non-respondent only: {membership_counts.get('non_respondent_only', 0)}",
        f"- In both files: {membership_counts.get('both', 0)}",
        f"- Avner only: {membership_counts.get('avner_only', 0)}",
        "",
        "## Avner `send_now` Bucket",
        "",
        f"- Responded since baseline: {avner_send_now_responded}",
        f"- Total `send_now` rows: {avner_send_now_total}",
    ]

    if avner_send_now_total:
        lines.append(f"- Share of `send_now` rows with a completed response in this snapshot: {avner_send_now_responded / avner_send_now_total:.1%}")

    lines.extend(
        [
            "",
            "## Non-Respondent Actions Represented Among Completed Responders",
            "",
        ]
    )

    for action, count in sorted(non_response_action_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{action}`: {count}")

    lines.extend(
        [
            "",
            "## Alias / Fuzzy Matches Worth Noting",
            "",
        ]
    )

    if fuzzy_or_alias:
        for row in sorted(fuzzy_or_alias, key=lambda item: item["recorded_date"]):
            lines.append(
                f"- `{row['respondent_name']}` -> `{row['matched_person'].canonical_name}` ({row['match_basis']})"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Unmatched New Activity",
            "",
        ]
    )

    if unmatched:
        for row in unmatched:
            label = row["respondent_name"] or "(blank name)"
            email = row["survey_email"] or row["recipient_email"] or "(blank email)"
            lines.append(
                f"- `{row['recorded_date']}` | finished=`{row['finished']}` progress=`{row['progress']}` | {label} | {email}"
            )
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def main():
    args = parse_args()

    current_raw = project_path(args.current_raw)
    baseline_raw = project_path(args.baseline_raw)
    non_respondent_path = project_path(args.non_respondent)
    avner_path = project_path(args.avner)

    tag = extract_date_tag(current_raw)
    output_responses = project_path(
        args.output_responses or f"Data/Derived/Outreach_New_Responses_{tag}.csv"
    )
    output_status = project_path(
        args.output_status or f"Data/Derived/Outreach_Status_{tag}.csv"
    )
    output_summary = project_path(
        args.output_summary or f"Communications/Reports/Generated/Outreach_Response_Check_{tag}.md"
    )

    baseline_rows = read_raw_rows(baseline_raw)
    current_rows = read_raw_rows(current_raw)
    baseline_ids = {row["response_id"] for row in baseline_rows}
    new_responses = [row for row in current_rows if row["response_id"] not in baseline_ids]

    people = load_people(non_respondent_path, avner_path)
    matched, unmatched = match_responses(new_responses, people)

    write_responses_csv(output_responses, matched, unmatched)
    write_status_csv(output_status, people, matched)

    summary = build_summary(
        current_raw=current_raw,
        baseline_raw=baseline_raw,
        people=people,
        matched=matched,
        unmatched=unmatched,
        non_respondent_path=non_respondent_path,
        avner_path=avner_path,
    )
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_summary.write_text(summary, encoding="utf-8")

    print(f"New raw response records: {len(new_responses)}")
    print(f"Matched records: {len(matched)}")
    print(f"Unmatched records: {len(unmatched)}")
    print(f"Wrote matched response CSV: {output_responses}")
    print(f"Wrote outreach status CSV: {output_status}")
    print(f"Wrote summary markdown: {output_summary}")


if __name__ == "__main__":
    main()
