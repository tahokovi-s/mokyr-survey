#!/usr/bin/env python3
"""
Generate Wave 5 contact list.

Wave 5 = Wave 4 non-respondents + newly reachable Q12a students (reported by
advisors who responded after Wave 4 was sent, or whose emails were recently
recovered in the enriched Q12a file).

Usage:
    python3 Code/generate_wave5.py \
      --enriched Data/Derived/Advisors_and_Reported_Students_022226_Enriched.csv \
      --cleaned  Data/Cleaned/Mokyr_Survey_Responses_022226_Cleaned.csv \
      --wave2    Data/Contact_Lists/Mokyr_Survey_Wave2.csv \
      --wave3    Data/Contact_Lists/Mokyr_Survey_Wave3.csv \
      --wave4    Data/Contact_Lists/Mokyr_Survey_Wave4.csv
"""

import argparse
import csv
import io
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Helpers (duplicated from parse_q12a.py to keep this script self-contained)
# ---------------------------------------------------------------------------

def normalize_email(email):
    """Lowercase, strip whitespace and trailing semicolons."""
    return email.lower().strip().rstrip(';').strip()


def load_wave_contacts(wave_path):
    """Return list of dicts with keys: first, last, email, source."""
    contacts = []
    with open(wave_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            contacts.append({
                'first': row.get('First Name', '').strip(),
                'last':  row.get('Last Name',  '').strip(),
                'email': normalize_email(row.get('Email', '')),
                'source': row.get('Source', '').strip(),
            })
    return contacts


def split_emails(raw_email):
    """Split a possibly semicolon-delimited email string into individual emails."""
    parts = re.split(r'[;\s]+', raw_email)
    return [normalize_email(p) for p in parts if '@' in normalize_email(p)]


def valid_email(e):
    return bool(e and '@' in e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Generate Wave 5 contact list')
    parser.add_argument('--enriched', default='Data/Derived/Advisors_and_Reported_Students_022226_Enriched.csv')
    parser.add_argument('--cleaned',  default='Data/Cleaned/Mokyr_Survey_Responses_022226_Cleaned.csv')
    parser.add_argument('--wave2',    default='Data/Contact_Lists/Mokyr_Survey_Wave2.csv')
    parser.add_argument('--wave3',    default='Data/Contact_Lists/Mokyr_Survey_Wave3.csv')
    parser.add_argument('--wave4',    default='Data/Contact_Lists/Mokyr_Survey_Wave4.csv')
    args = parser.parse_args()

    enriched_path = PROJECT_ROOT / args.enriched
    cleaned_path  = PROJECT_ROOT / args.cleaned
    wave2_path    = PROJECT_ROOT / args.wave2
    wave3_path    = PROJECT_ROOT / args.wave3
    wave4_path    = PROJECT_ROOT / args.wave4

    # -----------------------------------------------------------------------
    # Step 1: Load respondents from cleaned CSV
    # -----------------------------------------------------------------------
    with open(cleaned_path, 'r', encoding='utf-8') as f:
        raw = f.read()
    reader = csv.reader(io.StringIO(raw))
    all_rows = list(reader)
    header = all_rows[0]
    data_rows = all_rows[1:]

    col_map = {name: i for i, name in enumerate(header)}
    q1_idx = col_map.get('Q1', 17)
    q2_idx = col_map.get('Q2', 18)
    q3_idx = col_map.get('Q3', 19)

    respondent_emails = set()
    respondent_names  = set()
    for row in data_rows:
        first = row[q1_idx].strip().lower() if q1_idx < len(row) else ''
        last  = row[q2_idx].strip().lower() if q2_idx < len(row) else ''
        email = normalize_email(row[q3_idx]) if q3_idx < len(row) else ''
        if email and valid_email(email):
            respondent_emails.add(email)
        if first and last:
            respondent_names.add((first, last))

    # -----------------------------------------------------------------------
    # Step 2: Load all prior wave contacts
    # -----------------------------------------------------------------------
    wave2_contacts = load_wave_contacts(wave2_path)
    wave3_contacts = load_wave_contacts(wave3_path)
    wave4_contacts = load_wave_contacts(wave4_path)
    all_prior_contacts = wave2_contacts + wave3_contacts + wave4_contacts

    all_contacted_emails = set()
    all_contacted_names  = set()
    for c in all_prior_contacts:
        for e in split_emails(c['email']):
            all_contacted_emails.add(e)
        if c['first'] and c['last']:
            all_contacted_names.add((c['first'].lower(), c['last'].lower()))

    # -----------------------------------------------------------------------
    # Step 3: Pool A — Wave 4 non-respondents
    # -----------------------------------------------------------------------
    pool_a = []          # included rows: dicts with First Name, Last Name, Email, Source, Flag
    vetting_rows = []    # all candidates (included + excluded) for the report

    seen_emails_a = set()   # dedup within pool A
    seen_names_a  = set()

    excl_responded   = 0
    excl_no_email    = 0

    for c in wave4_contacts:
        raw_email = c['email']
        emails = split_emails(raw_email) if raw_email else []

        first = c['first']
        last  = c['last']
        name_key = (first.lower(), last.lower())

        if not emails:
            excl_no_email += 1
            vetting_rows.append({
                'First Name': first, 'Last Name': last, 'Email': raw_email,
                'Source': c['source'], 'Pool': 'A',
                'Flag': '', 'Exclusion_Reason': 'no_valid_email',
            })
            continue

        primary_email = emails[0]

        # Skip if already responded (check all emails in the field)
        if any(e in respondent_emails for e in emails):
            excl_responded += 1
            vetting_rows.append({
                'First Name': first, 'Last Name': last, 'Email': primary_email,
                'Source': c['source'], 'Pool': 'A',
                'Flag': '', 'Exclusion_Reason': 'already_responded',
            })
            continue

        # Skip if name matches a respondent
        if name_key in respondent_names:
            excl_responded += 1
            vetting_rows.append({
                'First Name': first, 'Last Name': last, 'Email': primary_email,
                'Source': c['source'], 'Pool': 'A',
                'Flag': 'NAME_MATCH', 'Exclusion_Reason': 'name_matches_respondent',
            })
            continue

        # Dedup within pool A by email
        if primary_email in seen_emails_a:
            continue
        # Dedup by name
        if name_key in seen_names_a:
            continue

        seen_emails_a.add(primary_email)
        seen_names_a.add(name_key)

        # Flag if name is close to a respondent (shouldn't happen after skip above,
        # but kept here for safety — no flagging needed since we already skip on NAME_MATCH)
        flag = ''

        row = {
            'First Name': first, 'Last Name': last, 'Email': primary_email,
            'Source': c['source'], 'Pool': 'A', 'Flag': flag, 'Exclusion_Reason': '',
        }
        pool_a.append(row)
        vetting_rows.append(row)

    # -----------------------------------------------------------------------
    # Step 4: Pool B — Newly reachable Q12a students
    # -----------------------------------------------------------------------
    pool_b = []
    seen_emails_b = set()
    seen_names_b  = set()

    excl_prior_contact = 0
    excl_b_responded   = 0
    excl_b_no_email    = 0
    flag_name_match    = 0
    flag_fuzzy_email   = 0

    with open(enriched_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        enriched_rows = list(reader)

    for row in enriched_rows:
        advisor_last = row.get('Advisor_LastName', '').strip()

        # Determine effective email
        student_emails = split_emails(row.get('Student_Email', '') or '')
        recovered_emails = split_emails(row.get('Email_Recovered', '') or '')
        email_source  = (row.get('Email_Source', '') or '').strip()

        if student_emails:
            effective_email = student_emails[0]
            is_recovered    = False
        elif recovered_emails:
            effective_email = recovered_emails[0]
            is_recovered    = True
        else:
            excl_b_no_email += 1
            student_name = (row.get('Student_Info_Cleaned', '') or '').strip()
            vetting_rows.append({
                'First Name': student_name, 'Last Name': '', 'Email': '',
                'Source': f'Q12a-{advisor_last}', 'Pool': 'B',
                'Flag': '', 'Exclusion_Reason': 'no_valid_email',
            })
            continue

        # Parse name into first/last
        student_name = (row.get('Student_Info_Cleaned', '') or '').strip()
        if ' ' in student_name:
            idx = student_name.rfind(' ')
            s_first = student_name[:idx].strip()
            s_last  = student_name[idx+1:].strip()
        else:
            s_first = student_name
            s_last  = ''

        name_key = (s_first.lower(), s_last.lower()) if s_last else None

        candidate_emails = student_emails if student_emails else recovered_emails

        # Skip if already in a prior wave (by email)
        if any(email in all_contacted_emails for email in candidate_emails):
            excl_prior_contact += 1
            vetting_rows.append({
                'First Name': s_first, 'Last Name': s_last, 'Email': effective_email,
                'Source': f'Q12a-{advisor_last}', 'Pool': 'B',
                'Flag': '', 'Exclusion_Reason': 'already_contacted',
            })
            continue

        # Skip if already in Pool A (by email)
        if any(email in seen_emails_a for email in candidate_emails):
            excl_prior_contact += 1
            vetting_rows.append({
                'First Name': s_first, 'Last Name': s_last, 'Email': effective_email,
                'Source': f'Q12a-{advisor_last}', 'Pool': 'B',
                'Flag': '', 'Exclusion_Reason': 'already_in_pool_a',
            })
            continue

        # Skip if already responded (by email)
        if any(email in respondent_emails for email in candidate_emails):
            excl_b_responded += 1
            vetting_rows.append({
                'First Name': s_first, 'Last Name': s_last, 'Email': effective_email,
                'Source': f'Q12a-{advisor_last}', 'Pool': 'B',
                'Flag': '', 'Exclusion_Reason': 'already_responded',
            })
            continue

        # Skip if name matches a respondent
        if name_key and name_key in respondent_names:
            excl_b_responded += 1
            flag_name_match += 1
            vetting_rows.append({
                'First Name': s_first, 'Last Name': s_last, 'Email': effective_email,
                'Source': f'Q12a-{advisor_last}', 'Pool': 'B',
                'Flag': 'NAME_MATCH', 'Exclusion_Reason': 'name_matches_respondent',
            })
            continue

        # Dedup within pool B
        if any(email in seen_emails_b for email in candidate_emails):
            continue
        if name_key and name_key in seen_names_b:
            continue

        for email in candidate_emails:
            seen_emails_b.add(email)
        if name_key:
            seen_names_b.add(name_key)

        # Determine flags
        flag = ''
        if name_key and name_key in respondent_names:
            flag = 'NAME_MATCH'
            flag_name_match += 1
        elif is_recovered:
            flag = 'FUZZY_EMAIL'
            flag_fuzzy_email += 1

        b_row = {
            'First Name': s_first, 'Last Name': s_last, 'Email': effective_email,
            'Source': f'Q12a-{advisor_last}', 'Pool': 'B',
            'Flag': flag, 'Exclusion_Reason': '',
        }
        pool_b.append(b_row)
        vetting_rows.append(b_row)

    # -----------------------------------------------------------------------
    # Step 5: Write outputs
    # -----------------------------------------------------------------------
    out_dir  = PROJECT_ROOT / 'Data' / 'Contact_Lists'
    logs_dir = PROJECT_ROOT / 'Logs'
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    wave5_path   = out_dir  / 'Mokyr_Survey_Wave5.csv'
    vetting_path = logs_dir / 'Wave5_Vetting_Report.csv'

    # Sort pool A by last name, then pool B by last name
    pool_a_sorted = sorted(pool_a, key=lambda r: r['Last Name'].lower())
    pool_b_sorted = sorted(pool_b, key=lambda r: r['Last Name'].lower())
    wave5_rows = pool_a_sorted + pool_b_sorted

    with open(wave5_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['First Name', 'Last Name', 'Email', 'Source'])
        writer.writeheader()
        for r in wave5_rows:
            writer.writerow({
                'First Name': r['First Name'],
                'Last Name':  r['Last Name'],
                'Email':      r['Email'],
                'Source':     r['Source'],
            })

    with open(vetting_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(
            f, fieldnames=['First Name', 'Last Name', 'Email', 'Source', 'Pool', 'Flag', 'Exclusion_Reason']
        )
        writer.writeheader()
        for r in vetting_rows:
            writer.writerow(r)

    # -----------------------------------------------------------------------
    # Step 6: Summary
    # -----------------------------------------------------------------------
    total_a = len(pool_a)
    total_b = len(pool_b)
    total   = total_a + total_b

    # Count flags in included rows
    a_name_match   = sum(1 for r in pool_a if r['Flag'] == 'NAME_MATCH')
    b_name_match   = sum(1 for r in pool_b if r['Flag'] == 'NAME_MATCH')
    b_fuzzy_email  = sum(1 for r in pool_b if r['Flag'] == 'FUZZY_EMAIL')
    total_name_match  = a_name_match + b_name_match
    total_fuzzy_email = b_fuzzy_email

    excl_no_email_total = excl_no_email + excl_b_no_email

    print()
    print('Wave 5 Summary')
    print('--------------')
    print(f'Pool A (Wave 4 non-respondents):   {total_a}')
    print(f'Pool B (Newly reachable Q12a):     {total_b}')
    print(f'  of which NAME_MATCH flagged:     {total_name_match}')
    print(f'  of which FUZZY_EMAIL flagged:    {total_fuzzy_email}')
    print(f'Total contacts:                    {total}')
    print(f'Excluded (already responded):      {excl_responded + excl_b_responded}')
    print(f'Excluded (already contacted):      {excl_prior_contact}')
    print(f'Excluded (no valid email):         {excl_no_email_total}')
    print(f'Wave 5 CSV:     {wave5_path}')
    print(f'Vetting report: {vetting_path}')
    print()


if __name__ == '__main__':
    main()
