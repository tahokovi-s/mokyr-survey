#!/usr/bin/env python3
"""
Wave 4 sanity check: verify that NONE of the 112 Wave 4 contacts
have already responded to the survey (checked against both cleaned
and raw response files).

Checks performed:
  1. Exact email match (case-insensitive, strip trailing semicolons)
  2. Exact full name match (first.lower(), last.lower())
  3. Alias match (Wave 4 name matches known alias target)
  4. Email local-part match (same local part, different domain)
  5. Last name + first initial match
  6. Levenshtein distance on full name <= 2
  7. Reversed names (Wave 4 first,last == respondent last,first)
  8. First name match + last name Levenshtein <= 1

Uses only csv module. Levenshtein implemented inline.
"""

import csv
import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT = "/Users/tahokovi/Library/CloudStorage/Dropbox/Stanford/Abramitzky/Mokyr Survey"
WAVE4_PATH = os.path.join(PROJECT, "Data/Contact_Lists/Mokyr_Survey_Wave4.csv")
CLEANED_PATH = os.path.join(PROJECT, "Data/Cleaned/Mokyr_Survey_Responses_020726_Cleaned.csv")
RAW_PATH = os.path.join(PROJECT, "Data/Raw/Mokyr_Survey_Responses_020726_Raw.csv")

# ---------------------------------------------------------------------------
# Known name aliases: contact-list name -> respondent name
# ---------------------------------------------------------------------------
ALIASES = {
    ("steve", "mcbride"): ("stephan", "mcbride"),
    ("hugh", "wu"): ("hugh xiaolong", "wu"),
    ("jenna", "kowalski"): ("jennifer", "kowalski"),
    ("martha w.", "williams"): ("martha", "(weidner) williams"),
    ("gian", "marco pinna"): ("gian marco", "pinna"),
    ("aniket", "pajwani"): ("aniket", "panjwani"),
    ("manjunath", "a.n"): ("manjunath agalagurki", "nagaraj"),
    ("michael", "porcellachia"): ("michael", "porcellacchia"),
    ("marlous", "van waigenburg"): ("marlous", "van waijenburg"),
    ("harvey", "mitchell"): ("mitchell", "harvey"),
}

# Build reverse lookup: respondent-side name -> alias contact-list name
ALIAS_TARGETS = {}
for contact_name, resp_name in ALIASES.items():
    ALIAS_TARGETS[resp_name] = contact_name

# ---------------------------------------------------------------------------
# Levenshtein distance (no external packages)
# ---------------------------------------------------------------------------
def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_str(s):
    """Strip and lowercase."""
    if s is None:
        return ""
    return s.strip().lower()

def strip_semicolons(s):
    """Strip trailing semicolons (and whitespace)."""
    return s.rstrip("; ").strip()

def email_local(email):
    """Return local part of email (before @)."""
    if "@" in email:
        return email.split("@")[0]
    return email

# ---------------------------------------------------------------------------
# Load Wave 4 contacts
# ---------------------------------------------------------------------------
def load_wave4():
    contacts = []
    with open(WAVE4_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if not row or not any(row):
                continue
            first = clean_str(row[0])
            last = clean_str(row[1])
            email = clean_str(strip_semicolons(row[2]))
            source = row[3].strip() if len(row) > 3 else ""
            if first or last or email:
                contacts.append({
                    "first": first,
                    "last": last,
                    "email": email,
                    "source": source,
                    "first_raw": row[0].strip(),
                    "last_raw": row[1].strip(),
                })
    return contacts

# ---------------------------------------------------------------------------
# Load respondents from cleaned file (1 header row, data starts at row 2)
# ---------------------------------------------------------------------------
def load_cleaned():
    respondents = []
    with open(CLEANED_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            if len(row) <= 19:
                continue
            first = clean_str(row[17])
            last = clean_str(row[18])
            email = clean_str(strip_semicolons(row[19]))
            resp_id = row[8].strip() if len(row) > 8 else ""
            respondents.append({
                "first": first,
                "last": last,
                "email": email,
                "resp_id": resp_id,
                "status": row[2].strip() if len(row) > 2 else "",
                "finished": row[6].strip() if len(row) > 6 else "",
                "source": "cleaned",
            })
    return respondents

# ---------------------------------------------------------------------------
# Load respondents from raw file (3 header rows, data starts at row index 3)
# ---------------------------------------------------------------------------
def load_raw():
    respondents = []
    with open(RAW_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        # Skip 3 header rows
        # Row 0 = column names, Row 1-2 = question text / import IDs
        # But the raw file has multi-line fields in the header, so we
        # need to count actual CSV rows (the csv module handles quoted newlines).
        header = next(reader)  # row 0: column names
        next(reader)           # row 1: question text (may span multiple lines in file)
        next(reader)           # row 2: import IDs
        for row in reader:
            if len(row) <= 19:
                continue
            first = clean_str(row[17])
            last = clean_str(row[18])
            email = clean_str(strip_semicolons(row[19]))
            resp_id = row[8].strip() if len(row) > 8 else ""
            status = row[2].strip() if len(row) > 2 else ""
            finished = row[6].strip() if len(row) > 6 else ""
            respondents.append({
                "first": first,
                "last": last,
                "email": email,
                "resp_id": resp_id,
                "status": status,
                "finished": finished,
                "source": "raw",
            })
    return respondents

# ---------------------------------------------------------------------------
# Run all 8 checks for one Wave 4 contact against a list of respondents
# ---------------------------------------------------------------------------
def check_contact(contact, respondents, source_label):
    """
    Returns list of (check_name, details_dict) for any matches found.
    """
    matches = []
    c_first = contact["first"]
    c_last = contact["last"]
    c_email = contact["email"]
    c_fullname = f"{c_first} {c_last}"
    c_local = email_local(c_email)

    for r in respondents:
        r_first = r["first"]
        r_last = r["last"]
        r_email = r["email"]
        r_fullname = f"{r_first} {r_last}"
        r_local = email_local(r_email)

        hit_checks = []

        # 1. Exact email match
        if c_email and r_email and c_email == r_email:
            hit_checks.append("1-exact-email")

        # 2. Exact full name match
        if c_first and c_last and c_first == r_first and c_last == r_last:
            hit_checks.append("2-exact-name")

        # 3. Alias match — check if Wave 4 name matches any alias target
        #    i.e., the Wave 4 contact's (first, last) matches the *respondent side*
        #    of any known alias. But also: check if the respondent's name is the
        #    alias-target of the Wave 4 contact's name.
        for contact_alias, resp_alias in ALIASES.items():
            # Wave 4 name is the contact-list side, respondent is the resp side
            if (c_first, c_last) == contact_alias and (r_first, r_last) == resp_alias:
                hit_checks.append(f"3-alias({contact_alias}->{resp_alias})")
            # Or Wave 4 name matches respondent-side alias
            if (c_first, c_last) == resp_alias and (r_first, r_last) == contact_alias:
                hit_checks.append(f"3-alias-reverse({resp_alias}->{contact_alias})")
            # Or if Wave 4 contact matches one side and respondent matches the other
            if (c_first, c_last) == contact_alias and r_first == resp_alias[0] and r_last == resp_alias[1]:
                pass  # already covered above
            if (c_first, c_last) == resp_alias and r_first == contact_alias[0] and r_last == contact_alias[1]:
                pass  # already covered above

        # 4. Email local-part match (same local, different domain)
        if c_local and r_local and c_local == r_local and c_email != r_email:
            hit_checks.append(f"4-email-local({c_email} vs {r_email})")

        # 5. Last name + first initial match
        if (c_last and r_last and c_first and r_first
                and c_last == r_last
                and c_first[0] == r_first[0]
                and not (c_first == r_first)):  # exclude exact name match (already #2)
            hit_checks.append(f"5-last+initial({r_first} {r_last})")

        # 6. Levenshtein on full name <= 2
        if c_fullname.strip() and r_fullname.strip():
            dist = levenshtein(c_fullname, r_fullname)
            if dist <= 2 and dist > 0:  # dist==0 is exact match, already covered
                hit_checks.append(f"6-levenshtein-fullname(d={dist}, '{r_fullname}')")

        # 7. Reversed names
        if (c_first and c_last and r_first and r_last
                and c_first == r_last and c_last == r_first
                and c_first != c_last):  # avoid palindrome names
            hit_checks.append(f"7-reversed({r_first} {r_last})")

        # 8. First name match + last name Levenshtein <= 1
        if (c_first and r_first and c_last and r_last
                and c_first == r_first and c_last != r_last):
            ld = levenshtein(c_last, r_last)
            if ld <= 1:
                hit_checks.append(f"8-first+similar-last(d={ld}, '{r_first} {r_last}')")

        if hit_checks:
            matches.append({
                "checks": hit_checks,
                "respondent": r,
                "source": source_label,
            })

    return matches

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 80)
    print("WAVE 4 SANITY CHECK")
    print("=" * 80)

    wave4 = load_wave4()
    print(f"\nLoaded {len(wave4)} Wave 4 contacts")

    cleaned = load_cleaned()
    print(f"Loaded {len(cleaned)} cleaned respondents")

    raw = load_raw()
    print(f"Loaded {len(raw)} raw respondents (all rows including preview/incomplete)")

    print("\n" + "-" * 80)
    print("CHECKING EACH WAVE 4 CONTACT")
    print("-" * 80)

    all_fails = []
    all_passes = 0
    raw_incomplete_flags = []

    for i, contact in enumerate(wave4):
        label = f"{contact['first_raw']} {contact['last_raw']} <{contact['email']}>"

        # Check against cleaned
        cleaned_matches = check_contact(contact, cleaned, "CLEANED")
        # Check against raw
        raw_matches = check_contact(contact, raw, "RAW")

        all_matches = cleaned_matches + raw_matches

        if all_matches:
            print(f"\n[FAIL] #{i+1}: {label}")
            for m in all_matches:
                r = m["respondent"]
                checks_str = ", ".join(m["checks"])
                r_label = f"{r['first']} {r['last']} <{r['email']}>"
                extra = ""
                if m["source"] == "RAW":
                    extra = f" [Status={r['status']}, Finished={r['finished']}]"
                print(f"       {m['source']}: matched {r_label} via {checks_str}{extra}")
            all_fails.append((contact, all_matches))

            # Check if any raw match is incomplete/preview
            for m in raw_matches:
                r = m["respondent"]
                if r["finished"].lower() != "true" or "preview" in r["status"].lower():
                    raw_incomplete_flags.append((contact, m))
        else:
            print(f"[PASS] #{i+1}: {label}")
            all_passes += 1

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"\nTotal Wave 4 contacts checked: {len(wave4)}")
    print(f"PASS (no match found): {all_passes}")
    print(f"FAIL (match found):    {len(all_fails)}")

    if all_fails:
        print(f"\n{'='*80}")
        print("DETAILED FAIL LIST")
        print("=" * 80)
        for contact, matches in all_fails:
            label = f"{contact['first_raw']} {contact['last_raw']} <{contact['email']}>"
            print(f"\n  {label}  (source: {contact['source']})")
            for m in matches:
                r = m["respondent"]
                checks_str = ", ".join(m["checks"])
                r_label = f"{r['first']} {r['last']} <{r['email']}>"
                extra = ""
                if m["source"] == "RAW":
                    extra = f" [Status={r['status']}, Finished={r['finished']}]"
                print(f"    -> {m['source']}: {r_label}")
                print(f"       Checks: {checks_str}{extra}")

    if raw_incomplete_flags:
        print(f"\n{'='*80}")
        print("WAVE 4 CONTACTS WITH INCOMPLETE/PREVIEW RESPONSES IN RAW FILE")
        print("=" * 80)
        for contact, m in raw_incomplete_flags:
            r = m["respondent"]
            label = f"{contact['first_raw']} {contact['last_raw']} <{contact['email']}>"
            r_label = f"{r['first']} {r['last']} <{r['email']}>"
            checks_str = ", ".join(m["checks"])
            print(f"\n  {label}")
            print(f"    -> Matched: {r_label}")
            print(f"       Status={r['status']}, Finished={r['finished']}, ResponseId={r['resp_id']}")
            print(f"       Checks: {checks_str}")
    else:
        print("\nNo Wave 4 contacts found with incomplete/preview responses in raw file.")

    print("\n" + "=" * 80)
    print("SANITY CHECK COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
