#!/usr/bin/env python3
"""
Clean Mokyr Survey Responses
- Removes Qualtrics metadata rows
- Removes Survey Preview/test responses
- Removes incomplete responses
- Trims whitespace
- Handles duplicates (keeps more complete entry)
- Preserves anyone from baseline survey responses (if they have valid data)

Usage:
    python clean_survey.py --input Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv
    python clean_survey.py --input Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv --baseline Data/Raw/Mokyr_Survey_Responses_013026_Raw.csv
"""

import argparse
import csv
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Known legitimate short names (first or last) that should NOT be flagged
LEGITIMATE_SHORT_NAMES = {
    'or', 'hu', 'ma', 'he', 'li', 'wu', 'yi', 'mi', 'jo', 'bo', 'al', 'an',
    'yu', 'xu', 'ye', 'lu', 'su', 'ho', 'lo', 'le', 'ji', 'qi'
}

# Survey Preview entries to keep (legitimate respondents who used preview mode)
WHITELISTED_PREVIEW_NAMES = {
    ('santiago', 'perez'),
    ('netanel', 'ben-porath'),
}

# Test/gibberish patterns - these are NEVER real names
GIBBERISH_PATTERNS = {
    'a', 'aa', 'aaa', 's', 'ss', 'd', 'dd', 'r', 'rr', 't', 'tt', 'm', 'mm',
    'asdf', 'asd', 'sdf', 'qwer', 'qwe', 'test', 'testing', 'awd', 'adsf',
    'sdaf', 'sdf', 'fds', 'dfs', 'abc', 'xyz', 'xxx', 'yyy', 'zzz',
    'qwerty', 'zxcv', 'wasd'
}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def discover_columns(header):
    """Build column index map from header row."""
    col_indices = {name: i for i, name in enumerate(header)}
    return {
        'first_name': col_indices.get('Q1', 17),
        'last_name':  col_indices.get('Q2', 18),
        'email':      col_indices.get('Q3', 19),
        'response_id': col_indices.get('ResponseId', 8),
        'status':     col_indices.get('Status', 2),
        'finished':   col_indices.get('Finished', 6),
        'progress':   col_indices.get('Progress', 4),
    }


def safe_get(row, idx):
    """Get a cell value safely, returning '' if out of bounds or None."""
    if idx < len(row) and row[idx]:
        return row[idx].strip()
    return ''


def is_gibberish_name(name):
    """Check if a name is gibberish/test data."""
    name_lower = name.lower().strip()
    if name_lower in GIBBERISH_PATTERNS:
        return True
    if len(name_lower) == 1 and name_lower not in LEGITIMATE_SHORT_NAMES:
        return True
    return False


def is_test_entry(row, cols):
    """Check if this is a test/gibberish entry."""
    first = safe_get(row, cols['first_name'])
    last  = safe_get(row, cols['last_name'])
    email = safe_get(row, cols['email'])

    if is_gibberish_name(first) and is_gibberish_name(last):
        return True
    if (is_gibberish_name(first) or is_gibberish_name(last)) and (not email or '@' not in email):
        return True
    if email and '@' not in email and email.lower() in GIBBERISH_PATTERNS:
        return True
    return False


def is_protected(row, cols, protected_names, protected_emails, protected_response_ids):
    """Check if this respondent was in baseline data with valid info."""
    try:
        first   = safe_get(row, cols['first_name']).lower()
        last    = safe_get(row, cols['last_name']).lower()
        email   = safe_get(row, cols['email']).lower()
        resp_id = safe_get(row, cols['response_id'])

        if resp_id and resp_id in protected_response_ids:
            return True
        if first and last and (first, last) in protected_names:
            return True
        if email and email in protected_emails:
            return True
        return False
    except Exception:
        return False


def get_completeness_score(row, cols):
    """Score how complete a response is (for duplicate resolution)."""
    score = 0
    first = safe_get(row, cols['first_name'])
    last  = safe_get(row, cols['last_name'])
    email = safe_get(row, cols['email'])

    if first: score += 1
    if last:  score += 1
    if email and '@' in email: score += 3

    for cell in row:
        if cell and cell.strip():
            score += 0.1
    return score


def trim_row(row):
    return [cell.strip() if isinstance(cell, str) else cell for cell in row]


# ---------------------------------------------------------------------------
# Baseline (protection) loader
# ---------------------------------------------------------------------------

def load_baseline(baseline_path, cols):
    """Load a previous raw export and extract protected respondents."""
    protected_names = set()
    protected_emails = set()
    protected_response_ids = set()

    if baseline_path is None:
        return protected_names, protected_emails, protected_response_ids

    with open(baseline_path, 'r', encoding='utf-8') as f:
        raw_content = f.read()

    reader = csv.reader(io.StringIO(raw_content))
    all_rows = list(reader)
    data_rows = all_rows[3:]  # skip header + 2 Qualtrics metadata rows

    for row in data_rows:
        if len(row) <= max(cols['first_name'], cols['last_name'], cols['email'], cols['response_id']):
            continue

        status   = safe_get(row, cols['status'])
        finished = safe_get(row, cols['finished'])
        first    = safe_get(row, cols['first_name']).lower()
        last     = safe_get(row, cols['last_name']).lower()
        email    = safe_get(row, cols['email']).lower()
        resp_id  = safe_get(row, cols['response_id'])

        if status == 'Survey Preview' or finished != 'True':
            continue
        if first in GIBBERISH_PATTERNS or last in GIBBERISH_PATTERNS:
            continue
        if first and last and email and '@' in email:
            protected_names.add((first, last))
            protected_emails.add(email)
        if resp_id and email and '@' in email:
            protected_response_ids.add(resp_id)

    return protected_names, protected_emails, protected_response_ids


# ---------------------------------------------------------------------------
# Main cleaning pipeline
# ---------------------------------------------------------------------------

def clean(input_path, baseline_path=None, output_path=None, log_dir=None):
    """Run the full cleaning pipeline on a raw Qualtrics export."""
    input_path = Path(input_path)

    # Auto-derive output path: replace _Raw with _Cleaned, put in Data/Cleaned/
    if output_path is None:
        out_name = input_path.name.replace('_Raw', '_Cleaned')
        output_path = PROJECT_ROOT / 'Data' / 'Cleaned' / out_name
    else:
        output_path = Path(output_path)

    if log_dir is None:
        log_dir = PROJECT_ROOT / 'Logs'
    else:
        log_dir = Path(log_dir)

    # Read raw data
    with open(input_path, 'r', encoding='utf-8') as f:
        raw_content = f.read()

    reader = csv.reader(io.StringIO(raw_content))
    all_rows = list(reader)
    header = all_rows[0]
    data_rows = all_rows[3:]

    cols = discover_columns(header)

    print(f"Total rows in raw file: {len(all_rows)}")
    print(f"Data rows (after removing metadata): {len(data_rows)}")

    # Load baseline for protection
    protected_names, protected_emails, protected_response_ids = load_baseline(baseline_path, cols)
    if baseline_path:
        print(f"Loaded {len(protected_names)} valid names, {len(protected_emails)} emails from baseline")

    # --- First pass: filter and group by name ---
    stats = {
        'total_raw': len(data_rows),
        'survey_preview': 0,
        'incomplete': 0,
        'test_entries': 0,
        'duplicates': 0,
        'kept': 0
    }

    entries_by_name = {}

    for row in data_rows:
        if len(row) < max(cols['status'], cols['finished'], cols['first_name'], cols['last_name']) + 1:
            continue

        status   = safe_get(row, cols['status'])
        finished = safe_get(row, cols['finished'])
        first    = safe_get(row, cols['first_name'])
        last     = safe_get(row, cols['last_name'])

        if status == 'Survey Preview':
            preview_key = (first.lower(), last.lower()) if first and last else None
            if preview_key not in WHITELISTED_PREVIEW_NAMES:
                stats['survey_preview'] += 1
                continue
        if finished != 'True':
            stats['incomplete'] += 1
            continue
        if is_test_entry(row, cols):
            stats['test_entries'] += 1
            continue
        if not first and not last:
            stats['incomplete'] += 1
            continue

        key = (first.lower(), last.lower())
        entries_by_name.setdefault(key, []).append(row)

    # --- Second pass: resolve duplicates ---
    cleaned_rows = []
    duplicate_rows = []

    for key, rows in entries_by_name.items():
        if len(rows) == 1:
            cleaned_rows.append(trim_row(rows[0]))
        else:
            rows_with_scores = [(get_completeness_score(r, cols), r) for r in rows]
            rows_with_scores.sort(key=lambda x: x[0], reverse=True)
            cleaned_rows.append(trim_row(rows_with_scores[0][1]))
            for score, row in rows_with_scores[1:]:
                duplicate_rows.append((key, row))
                stats['duplicates'] += 1

    stats['kept'] = len(cleaned_rows)

    print(f"\n=== Cleaning Statistics ===")
    print(f"Total raw data rows: {stats['total_raw']}")
    print(f"Removed - Survey Preview: {stats['survey_preview']}")
    print(f"Removed - Incomplete: {stats['incomplete']}")
    print(f"Removed - Test entries: {stats['test_entries']}")
    print(f"Removed - Duplicates: {stats['duplicates']}")
    print(f"Final cleaned rows: {stats['kept']}")

    # --- Write outputs ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(cleaned_rows)
    print(f"\nCleaned data written to: {output_path}")

    log_dir.mkdir(parents=True, exist_ok=True)
    dup_file = log_dir / 'Mokyr_Survey_Duplicates.csv'
    with open(dup_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['First Name', 'Last Name', 'Email', 'Response ID', 'Start Date', 'Reason'])
        for key, row in duplicate_rows:
            first   = row[cols['first_name']] if len(row) > cols['first_name'] else ''
            last    = row[cols['last_name']]  if len(row) > cols['last_name']  else ''
            email   = row[cols['email']]      if len(row) > cols['email']      else ''
            resp_id = row[cols['response_id']] if len(row) > cols['response_id'] else ''
            start   = row[0] if row else ''
            writer.writerow([first, last, email, resp_id, start, 'Less complete duplicate'])
    print(f"Duplicates log written to: {dup_file}")

    # --- Verification ---
    print(f"\n=== Verification: Checking for remaining issues ===")
    issues_found = 0
    for row in cleaned_rows:
        first = safe_get(row, cols['first_name'])
        last  = safe_get(row, cols['last_name'])
        email = safe_get(row, cols['email'])
        if is_gibberish_name(first) or is_gibberish_name(last):
            print(f"  WARNING: Potential issue - {first} {last} ({email})")
            issues_found += 1

    if issues_found == 0:
        print("  No issues found - all entries appear legitimate!")
    else:
        print(f"  Found {issues_found} potential issues to review")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Clean a raw Qualtrics export for the Mokyr Survey.'
    )
    parser.add_argument(
        '--input', required=True,
        help='Path to raw CSV (e.g. Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv)'
    )
    parser.add_argument(
        '--baseline', default=None,
        help='Path to previous raw CSV for respondent protection (optional)'
    )
    parser.add_argument(
        '--output', default=None,
        help='Path for cleaned output CSV (auto-derived from input if omitted)'
    )

    args = parser.parse_args()

    # Resolve relative paths against PROJECT_ROOT
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path

    baseline_path = None
    if args.baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.is_absolute():
            baseline_path = PROJECT_ROOT / baseline_path

    output_path = None
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path

    clean(input_path, baseline_path, output_path)


if __name__ == '__main__':
    main()
