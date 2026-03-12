#!/usr/bin/env python3
"""
Parse Q12a (PhD student listings) and generate Wave 4 contact list.

Part A: Parse Q12a free-text responses into structured advisor-student pairs.
        Reads from the RAW Qualtrics export to capture all Q12a data, including
        from Survey Preview respondents who provided legitimate student listings.
Part B: Generate Wave 4 contacts (previous non-respondents + new Q12a students).
        Uses the CLEANED CSV to determine who has responded.

Usage:
    # Full pipeline: parse Q12a + generate Wave 4
    python3 Code/parse_q12a.py \
      --raw Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv \
      --cleaned Data/Cleaned/Mokyr_Survey_Responses_020726_Cleaned.csv \
      --wave2 Data/Contact_Lists/Mokyr_Survey_Wave2.csv \
      --wave3 Data/Contact_Lists/Mokyr_Survey_Wave3.csv

    # Just parse Q12a (no wave generation)
    python3 Code/parse_q12a.py \
      --raw Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv \
      --cleaned Data/Cleaned/Mokyr_Survey_Responses_020726_Cleaned.csv \
      --parse-only
"""

import argparse
import csv
import io
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Q12a values that are test/gibberish and should be skipped entirely
GIBBERISH_Q12A = {'bla bla', 'test', 'testing', 'asdf', 'qwerty', 'n/a', 'na', 'none'}

# Known name aliases: respondents who used a different first name than their contact list entry.
# Maps (contact_first_lower, contact_last_lower) -> set of alternate (first_lower, last_lower).
NAME_ALIASES = {
    ('steve', 'mcbride'): {('stephan', 'mcbride')},
    ('hugh', 'wu'): {('hugh xiaolong', 'wu')},
    ('jenna', 'kowalski'): {('jennifer', 'kowalski')},
    ('martha w.', 'williams'): {('martha', '(weidner) williams')},
    ('gian', 'marco pinna'): {('gian marco', 'pinna')},
    ('aniket', 'pajwani'): {('aniket', 'panjwani')},
    ('manjunath', 'a.n'): {('manjunath agalagurki', 'nagaraj')},
    ('michael', 'porcellachia'): {('michael', 'porcellacchia')},
    ('marlous', 'van waigenburg'): {('marlous', 'van waijenburg')},
    ('harvey', 'mitchell'): {('mitchell', 'harvey')},
}

# Lines within Q12a that are notes/headers, not student entries
SKIP_LINE_PATTERNS = [
    r'^\s*$',                          # blank
    r'^\s*\*',                          # asterisk notes like "*Only including..."
    r'^\s*thus\b',                     # "Thus, I have served..."
    r'^\s*i\s+have\b',                # "I have only included..."
    r'^\s*only\s+including\b',         # "Only including students..."
    r'^\s*scott\s+was\b',             # Szostak's note "Scott was an Econ PhD..."
    r'^\s*member\s*,\s*dissertation',  # Wegge committee entries
    r'^\s*advised\s+as\b',            # header "Advised as dissertation committee member:"
    r'^\s*ran\s+asked\s+me\b',        # Avner note rather than a student entry
]

# Disqualifying phrases embedded within an otherwise parseable line.
# These should not produce student records because the respondent is explicitly
# saying the person does not count as their supervised PhD student.
DISQUALIFY_ENTRY_PATTERNS = [
    r"not sure this should count",
    r"outside committee member",
    r"not\s+(?:the\s+)?supervisor",
    r"not a professor of (?:him|her|them)",
]

# ---------------------------------------------------------------------------
# Q12a Parsing
# ---------------------------------------------------------------------------

def is_skip_line(line):
    """Check if a line is a header, note, or non-student content."""
    stripped = line.strip()
    if not stripped:
        return True
    lower = stripped.lower()
    for pat in SKIP_LINE_PATTERNS:
        if re.search(pat, lower):
            return True
    return False


def is_disqualified_entry(line):
    """Check if a line explicitly says the person should not count."""
    lower = line.lower()
    for pat in DISQUALIFY_ENTRY_PATTERNS:
        if re.search(pat, lower):
            return True
    return False


def normalize_email(email):
    """Normalize a single email token."""
    return email.lower().strip().rstrip(';').strip()


def split_emails(raw_email):
    """Split a possibly semicolon-delimited email string into individual emails."""
    parts = re.split(r'[;\s]+', raw_email or '')
    return [normalize_email(part) for part in parts if '@' in normalize_email(part)]


def fix_malformed_email(text):
    """Fix common email typos like 'mhaupert uwlax.edu' -> 'mhaupert@uwlax.edu'.

    Only applies when there's NO valid email already in the text.
    Looks for patterns like 'word domain.tld' where there's a missing @.
    """
    # If there's already a valid email, don't try to fix anything
    if re.search(r'[\w.+-]+@[\w.-]+\.\w+', text):
        return text

    # Pattern: word then a space then something that looks like a domain
    # Must be a simple username (not a number) followed by a domain
    m = re.search(r'\b(\w+)\s+([\w.-]+\.\w{2,})\b', text)
    if m:
        candidate_user = m.group(1)
        candidate_domain = m.group(2)
        # Don't treat years or numbers as email usernames
        if candidate_user.isdigit():
            return text
        if '.' in candidate_domain:
            fixed_email = f"{candidate_user}@{candidate_domain}"
            fixed_text = text[:m.start()] + fixed_email + text[m.end():]
            return fixed_text
    return text


def extract_emails(text):
    """Extract all email addresses from text, return (semicolon_joined, text_without_emails)."""
    emails = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', text)
    if emails:
        remainder = re.sub(r'[\w.+-]+@[\w.-]+\.\w+', '', text)
        remainder = remainder.replace(';', ' ')
        deduped = []
        seen = set()
        for email in emails:
            norm = normalize_email(email)
            if norm and norm not in seen:
                seen.add(norm)
                deduped.append(norm)
        return ';'.join(deduped), remainder
    return '', text


def extract_year(text):
    """Extract a 4-digit year (1950-2035) from text, return (year, text_without_year)."""
    m = re.search(r'\b(19[5-9]\d|20[0-3]\d)\b', text)
    if m:
        year = m.group(0)
        remainder = text[:m.start()] + text[m.end():]
        return year, remainder
    return '', text


def clean_name(text):
    """Clean a name string by removing status labels, years, institutions, etc."""
    # Remove parenthetical content like (UC Davis), (Ph.D., graduated 2022), (ongoing)
    text = re.sub(r'\([^)]*\)', '', text)
    # Remove status/role labels
    for label in ['in progress', 'current', 'ongoing', 'deceased', 'on hold',
                  'expected', 'AP at']:
        text = re.sub(re.escape(label), '', text, flags=re.IGNORECASE)
    # Remove extra whitespace, commas, periods at edges
    text = re.sub(r'[,.\s]+$', '', text)
    text = re.sub(r'^[,.\s]+', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def looks_like_name(text):
    """Check if text looks like a person's name (at least two words, mostly alpha)."""
    words = text.split()
    if len(words) < 2:
        return False
    alpha_chars = sum(1 for c in text if c.isalpha())
    return alpha_chars >= 3


def name_from_email_local(email):
    """Try to infer a name from the local part of an email (best effort).

    E.g. hong.zhao@neoma-bs.fr -> Hong Zhao
    """
    if not email or '@' not in email:
        return ''
    local = email.split('@')[0]
    # Split on dots, hyphens, underscores
    parts = re.split(r'[._-]+', local)
    # Filter out numeric parts and very short fragments
    name_parts = [p.capitalize() for p in parts if p.isalpha() and len(p) >= 2]
    if len(name_parts) >= 2:
        return ' '.join(name_parts)
    return ''


def parse_entry(line, advisor_first, advisor_last):
    """Parse a single Q12a line into (student_name_cleaned, student_email).

    Handles these formats:
    - Name, Year, Email          (e.g. "Ran Abramitzky, 2005, ranabr@stanford.edu")
    - Name Email                 (e.g. "Philip Keefer pkeefer@idb.org")
    - Name (Institution)         (e.g. "Zhixian Lin (UC Davis)")
    - Name, Status, Email        (e.g. "Yanran Li, in progress, liyanran@stu.pku.edu.cn")
    - Year, Name, Institution    (e.g. "2029, Hyoungchul Kim, Wharton")
    - Name only                  (e.g. "Pawel Charsz")
    - Name (email), Role, Year   (e.g. "Wilbur Townsend (wilbur.townsend@gmail.com), ...")
    - Email only                 (e.g. "hong.zhao@neoma-bs.fr")
    - Malformed email            (e.g. "Mike Haupert mhaupert uwlax.edu")
    - Dissertation committee     (e.g. "Member, Dissertation Committee, Name (Field), ...")
    """
    line = line.strip()
    if not line:
        return None
    if is_disqualified_entry(line):
        return None

    # Try to fix malformed emails (missing @) before extraction
    fixed_line = fix_malformed_email(line)

    # Extract email(s) first (always reliable)
    email, remainder = extract_emails(fixed_line)

    # Extract year
    _, remainder = extract_year(remainder)

    # Clean up the remainder to get the name
    name = clean_name(remainder)

    # Handle "Year, Name, Institution" format (van Benthem style)
    # After removing year, we might have "Name, Institution"
    # Split on comma and take the part that looks most like a name
    if ',' in name:
        parts = [p.strip() for p in name.split(',') if p.strip()]
        # Filter to parts that look like names (not institutions)
        name_parts = [p for p in parts if looks_like_name(p)]
        if name_parts:
            name = name_parts[0]
        else:
            # Maybe the comma is inside a name like "Yiqing, Li"
            # Check if joining all parts makes a valid name
            joined = ' '.join(parts)
            if looks_like_name(joined) and len(parts) <= 3:
                name = joined
            elif parts:
                name = parts[0]

    # Handle dissertation committee format (Simone Wegge)
    if 'dissertation committee' in line.lower():
        m = re.search(r'committee[,\s]+(\w[\w\s.]+?)(?:\s*\(|\s*,)', line, re.IGNORECASE)
        if m:
            name = m.group(1).strip()

    # If we only got an email and no name, try to infer from the email
    if not name and email:
        primary_email = split_emails(email)[0] if split_emails(email) else ''
        name = name_from_email_local(primary_email)
        if not name:
            return None

    if not name:
        return None

    # Final cleanup: make sure name doesn't contain email fragments
    name = re.sub(r'[\w.+-]+@[\w.-]+', '', name).strip()
    name = re.sub(r'[,.\s]+$', '', name).strip()

    if not name or len(name) < 2:
        return None

    return name, email


def parse_q12a(raw_path, cleaned_path, output_path=None):
    """Parse all Q12a responses from the raw CSV.

    Reads from the raw file to capture Q12a data from all respondents,
    including Survey Preview entries that may contain legitimate student lists.
    Skips only rows that are clearly test/gibberish based on Q12a content.

    Returns list of dicts with keys:
    Advisor_FirstName, Advisor_LastName, Student_Info, Student_Info_Cleaned, Student_Email
    """
    raw_path = Path(raw_path)
    cleaned_path = Path(cleaned_path)

    # Read the raw file
    with open(raw_path, 'r', encoding='utf-8') as f:
        raw_content = f.read()

    reader = csv.reader(io.StringIO(raw_content))
    all_rows = list(reader)
    header = all_rows[0]
    data_rows = all_rows[3:]  # skip header + 2 Qualtrics metadata rows

    # Discover column indices
    col_map = {name: i for i, name in enumerate(header)}
    q1_idx = col_map.get('Q1', 17)
    q2_idx = col_map.get('Q2', 18)
    q12_idx = col_map.get('Q12', None)
    q12a_idx = col_map.get('Q12a', len(header) - 1)
    finished_idx = col_map.get('Finished', 6)

    records = []
    skipped_gibberish = 0
    skipped_entries = 0

    for row in data_rows:
        if q12a_idx >= len(row):
            continue

        # Must have finished the survey
        finished = row[finished_idx].strip() if finished_idx < len(row) else ''
        if finished != 'True':
            continue

        q12a = row[q12a_idx].strip()
        if not q12a:
            continue

        # Skip gibberish Q12a values
        if q12a.lower() in GIBBERISH_Q12A:
            skipped_gibberish += 1
            continue

        advisor_first = row[q1_idx].strip() if q1_idx < len(row) else ''
        advisor_last = row[q2_idx].strip() if q2_idx < len(row) else ''

        # Skip if the advisor name itself is gibberish
        if not advisor_first or not advisor_last:
            continue

        # Split Q12a on newlines
        lines = q12a.split('\n')

        for line in lines:
            line = line.strip()
            if is_skip_line(line):
                skipped_entries += 1
                continue

            result = parse_entry(line, advisor_first, advisor_last)
            if result is None:
                skipped_entries += 1
                continue

            student_name, student_email = result
            # Clean trailing semicolons from email
            student_email = ';'.join(split_emails(student_email))

            records.append({
                'Advisor_FirstName': advisor_first,
                'Advisor_LastName': advisor_last,
                'Student_Info': line,
                'Student_Info_Cleaned': student_name,
                'Student_Email': student_email,
            })

    # Write output
    if output_path is None:
        date_match = re.search(r'(\d{6})', cleaned_path.name)
        date_str = date_match.group(1) if date_match else 'unknown'
        output_path = PROJECT_ROOT / 'Data' / 'Derived' / f'Advisors_and_Reported_Students_{date_str}.csv'
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Advisor_FirstName', 'Advisor_LastName',
            'Student_Info', 'Student_Info_Cleaned', 'Student_Email',
        ])
        writer.writeheader()
        writer.writerows(records)

    print(f"\n=== Q12a Parsing Results ===")
    print(f"Advisors with Q12a data: {len(set((r['Advisor_FirstName'], r['Advisor_LastName']) for r in records))}")
    print(f"Total student records parsed: {len(records)}")
    with_email = sum(1 for r in records if r['Student_Email'])
    print(f"  With email: {with_email}")
    print(f"  Without email: {len(records) - with_email}")
    print(f"Skipped gibberish Q12a values: {skipped_gibberish}")
    print(f"Skipped non-student lines: {skipped_entries}")
    print(f"Output written to: {output_path}")

    return records, output_path


# ---------------------------------------------------------------------------
# Wave 4 Generation
# ---------------------------------------------------------------------------

def load_wave_contacts(wave_path):
    """Load a wave CSV and return list of dicts with First Name, Last Name, Email, Source."""
    contacts = []
    with open(wave_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            contacts.append({
                'first': row.get('First Name', '').strip(),
                'last': row.get('Last Name', '').strip(),
                'email': normalize_email(row.get('Email', '')),
                'source': row.get('Source', '').strip(),
            })
    return contacts


def generate_wave4(cleaned_path, wave2_path, wave3_path, q12a_records, output_path=None):
    """Generate Wave 4 contact list.

    Wave 4 = non-respondents from Wave 2/3 + new Q12a students not yet contacted.
    """
    cleaned_path = Path(cleaned_path)
    wave2_path = Path(wave2_path)
    wave3_path = Path(wave3_path)

    # 1. Load respondents from cleaned data
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
    respondent_names = set()
    for row in data_rows:
        first = row[q1_idx].strip().lower() if q1_idx < len(row) else ''
        last = row[q2_idx].strip().lower() if q2_idx < len(row) else ''
        email = normalize_email(row[q3_idx]) if q3_idx < len(row) else ''
        if email:
            respondent_emails.add(email)
        if first and last:
            respondent_names.add((first, last))

    # 2. Load previous wave contacts
    wave2_contacts = load_wave_contacts(wave2_path)
    wave3_contacts = load_wave_contacts(wave3_path)
    all_prev_contacts = wave2_contacts + wave3_contacts

    # Build set of all previously contacted emails
    prev_contacted_emails = set()
    for c in all_prev_contacts:
        if c['email']:
            for e in re.split(r'[;\s]+', c['email']):
                e = normalize_email(e)
                if e and '@' in e:
                    prev_contacted_emails.add(e)

    # Build set of previously contacted names (for fallback matching)
    prev_contacted_names = set()
    for c in all_prev_contacts:
        if c['first'] and c['last']:
            prev_contacted_names.add((c['first'].lower(), c['last'].lower()))

    # 3. Identify non-respondents from Wave 2/3
    wave4_rows = []
    seen_emails = set()
    seen_names = set()

    for c in all_prev_contacts:
        # Check if they responded (by email or name)
        responded = False
        if c['email']:
            for e in re.split(r'[;\s]+', c['email']):
                e = normalize_email(e)
                if e and e in respondent_emails:
                    responded = True
                    break
        if not responded and c['first'] and c['last']:
            contact_key = (c['first'].lower(), c['last'].lower())
            if contact_key in respondent_names:
                responded = True
            # Check known name aliases
            elif contact_key in NAME_ALIASES:
                for alias in NAME_ALIASES[contact_key]:
                    if alias in respondent_names:
                        responded = True
                        break

        if responded:
            continue

        # Skip if no email
        primary_email = c['email'].split(';')[0].strip() if c['email'] else ''
        if not primary_email or '@' not in primary_email:
            continue

        # Deduplicate
        email_key = normalize_email(primary_email)
        name_key = (c['first'].lower(), c['last'].lower()) if c['first'] and c['last'] else None
        if email_key in seen_emails:
            continue
        if name_key and name_key in seen_names:
            continue

        seen_emails.add(email_key)
        if name_key:
            seen_names.add(name_key)

        wave4_rows.append({
            'First Name': c['first'],
            'Last Name': c['last'],
            'Email': primary_email,
            'Source': c['source'],
        })

    non_respondent_count = len(wave4_rows)

    # 4. Identify new Q12a students to add
    new_q12a_count = 0
    for r in q12a_records:
        emails = split_emails(r['Student_Email'])
        if not emails:
            continue

        # Parse student name into first/last
        name_parts = r['Student_Info_Cleaned'].strip().split()
        if len(name_parts) >= 2:
            first = name_parts[0]
            last = ' '.join(name_parts[1:])
        elif name_parts:
            first = name_parts[0]
            last = ''
        else:
            continue

        name_key = (first.lower(), last.lower()) if first and last else None

        # Check name-based matching (including aliases)
        if name_key and (name_key in respondent_names or name_key in prev_contacted_names or name_key in seen_names):
            continue
        if name_key and name_key in NAME_ALIASES:
            if any(alias in respondent_names for alias in NAME_ALIASES[name_key]):
                continue

        # Skip if any listed email is already known; otherwise use the first viable one.
        if any(email in prev_contacted_emails for email in emails):
            continue
        if any(email in respondent_emails for email in emails):
            continue

        primary_email = next((email for email in emails if email not in seen_emails), '')
        if not primary_email:
            continue

        for email in emails:
            seen_emails.add(email)
        if name_key:
            seen_names.add(name_key)

        wave4_rows.append({
            'First Name': first,
            'Last Name': last,
            'Email': primary_email,
            'Source': f"Q12a-{r['Advisor_LastName']}",
        })
        new_q12a_count += 1

    # Write output
    if output_path is None:
        output_path = PROJECT_ROOT / 'Data' / 'Contact_Lists' / 'Mokyr_Survey_Wave4.csv'
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['First Name', 'Last Name', 'Email', 'Source'])
        writer.writeheader()
        writer.writerows(wave4_rows)

    print(f"\n=== Wave 4 Generation Results ===")
    print(f"Respondents in cleaned data: {len(respondent_emails)}")
    print(f"Previously contacted (Wave 2+3): {len(all_prev_contacts)}")
    print(f"Non-respondents carried forward: {non_respondent_count}")
    print(f"New Q12a students added: {new_q12a_count}")
    print(f"Total Wave 4 contacts: {len(wave4_rows)}")
    print(f"Output written to: {output_path}")

    return wave4_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Parse Q12a responses and generate Wave 4 contact list.'
    )
    parser.add_argument(
        '--raw', required=True,
        help='Path to raw CSV for Q12a extraction (e.g. Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv)'
    )
    parser.add_argument(
        '--cleaned', required=True,
        help='Path to cleaned CSV for respondent identification'
    )
    parser.add_argument(
        '--wave2', default=None,
        help='Path to Wave 2 contact list CSV'
    )
    parser.add_argument(
        '--wave3', default=None,
        help='Path to Wave 3 contact list CSV'
    )
    parser.add_argument(
        '--parse-only', action='store_true',
        help='Only parse Q12a, skip Wave 4 generation'
    )

    args = parser.parse_args()

    # Resolve paths
    raw_path = Path(args.raw)
    if not raw_path.is_absolute():
        raw_path = PROJECT_ROOT / raw_path

    cleaned_path = Path(args.cleaned)
    if not cleaned_path.is_absolute():
        cleaned_path = PROJECT_ROOT / cleaned_path

    # Part A: Parse Q12a from raw file
    records, derived_path = parse_q12a(raw_path, cleaned_path)

    # Part B: Generate Wave 4
    if not args.parse_only:
        if not args.wave2 or not args.wave3:
            print("\nError: --wave2 and --wave3 required for Wave 4 generation (use --parse-only to skip)")
            sys.exit(1)

        wave2_path = Path(args.wave2)
        if not wave2_path.is_absolute():
            wave2_path = PROJECT_ROOT / wave2_path

        wave3_path = Path(args.wave3)
        if not wave3_path.is_absolute():
            wave3_path = PROJECT_ROOT / wave3_path

        generate_wave4(cleaned_path, wave2_path, wave3_path, records)


if __name__ == '__main__':
    main()
