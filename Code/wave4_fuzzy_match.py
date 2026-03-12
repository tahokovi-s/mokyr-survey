#!/usr/bin/env python3
"""
Fuzzy matching of Wave 4 contacts against existing survey respondents.
Checks 10 matching criteria and reports potential duplicates.
No external dependencies -- uses only csv and standard library.
"""

import csv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Levenshtein distance (pure DP) ──────────────────────────────────
def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            ins = prev[j + 1] + 1
            dele = curr[j] + 1
            sub = prev[j] + (0 if c1 == c2 else 1)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]


# ── Load data ───────────────────────────────────────────────────────
def load_respondents(path):
    """Return list of dicts with first, last, email from cleaned CSV."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        # Q1=17, Q2=18, Q3=19 per CLAUDE.md
        for row in reader:
            if len(row) < 20:
                continue
            first = row[17].strip()
            last = row[18].strip()
            email = row[19].strip().rstrip(";").lower()
            rows.append({"first": first, "last": last, "email": email})
    return rows


def load_wave4(path):
    """Return list of dicts with first, last, email, source."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) < 3 or not row[0].strip():
                continue
            rows.append({
                "first": row[0].strip(),
                "last": row[1].strip(),
                "email": row[2].strip().rstrip(";").lower(),
                "source": row[3].strip() if len(row) > 3 else "",
            })
    return rows


# ── Matching functions ──────────────────────────────────────────────
def normalize(s):
    return s.strip().lower()


def email_local(email):
    """Return part before @, lowered."""
    if "@" in email:
        return email.split("@")[0].lower()
    return email.lower()


def email_domain(email):
    if "@" in email:
        return email.split("@")[1].lower()
    return ""


def run_matching(wave4, respondents):
    """
    For every Wave 4 entry, compare against every respondent using 10 criteria.
    Returns a dict keyed by (w4_idx, resp_idx) -> set of match criteria.
    """
    matches = {}  # (w4_idx, resp_idx) -> set of criteria strings

    for wi, w in enumerate(wave4):
        w_first = normalize(w["first"])
        w_last = normalize(w["last"])
        w_email = w["email"].lower().rstrip(";")
        w_full = f"{w_first} {w_last}"
        w_local = email_local(w_email)
        w_domain = email_domain(w_email)

        for ri, r in enumerate(respondents):
            r_first = normalize(r["first"])
            r_last = normalize(r["last"])
            r_email = r["email"].lower().rstrip(";")
            r_full = f"{r_first} {r_last}"
            r_local = email_local(r_email)
            r_domain = email_domain(r_email)

            key = (wi, ri)
            criteria = set()

            # 1. Exact email match
            if w_email and r_email and w_email == r_email:
                criteria.add("1-exact-email")

            # 2. Exact name match (first+last)
            if w_first and w_last and w_first == r_first and w_last == r_last:
                criteria.add("2-exact-name")

            # 3. Email local-part match (different domain)
            if (w_local and r_local and w_local == r_local
                    and w_domain and r_domain and w_domain != r_domain):
                criteria.add("3-email-local-match")

            # 4. Last name + first initial
            if (w_last and r_last and w_last == r_last
                    and w_first and r_first
                    and w_first[0] == r_first[0]
                    and w_first != r_first):
                criteria.add("4-lastname+initial")

            # 5. Last name only (different first)
            if (w_last and r_last and w_last == r_last
                    and w_first != r_first):
                criteria.add("5-lastname-only")

            # 6. Levenshtein on full name <= 3
            if w_full and r_full:
                dist = levenshtein(w_full, r_full)
                if dist <= 3 and dist > 0:
                    criteria.add(f"6-levenshtein-fullname(d={dist})")

            # 7. Same first name + similar last name (lev <= 2)
            if w_first and r_first and w_first == r_first:
                ld = levenshtein(w_last, r_last)
                if 0 < ld <= 2:
                    criteria.add(f"7-samefirst+similarlast(d={ld})")

            # 8. Reversed name parts
            if (w_first and w_last and r_first and r_last
                    and w_first == r_last and w_last == r_first):
                criteria.add("8-reversed-names")

            # 9. Substring/contains on last name in full name
            if w_last and r_full and len(w_last) >= 3 and w_last in r_full:
                if w_last != r_last and w_last != r_first:
                    criteria.add("9-substring-w4last-in-resp-full")
            if r_last and w_full and len(r_last) >= 3 and r_last in w_full:
                if r_last != w_last and r_last != w_first:
                    criteria.add("9-substring-resplast-in-w4full")

            # 10. Same email domain + same last name
            if (w_domain and r_domain and w_domain == r_domain
                    and w_last and r_last and w_last == r_last
                    and w_email != r_email):
                criteria.add("10-same-domain+lastname")

            if criteria:
                matches[key] = criteria

    return matches


# ── Confidence assignment ───────────────────────────────────────────
def assign_confidence(criteria_set):
    """
    HIGH  = very likely same person (exact email, exact name, reversed names, or combo of strong signals)
    MEDIUM = plausible (email local match, last+initial, close Levenshtein, etc.)
    LOW   = probably coincidence (last name only, substring only, domain+lastname only)
    """
    high_signals = {"1-exact-email", "2-exact-name", "8-reversed-names"}
    if criteria_set & high_signals:
        return "HIGH"

    # If multiple medium-strength signals fire, upgrade to HIGH
    medium_signals = set()
    for c in criteria_set:
        if c.startswith("3-") or c.startswith("4-") or c.startswith("6-") or c.startswith("7-"):
            medium_signals.add(c)
    if len(medium_signals) >= 2:
        return "HIGH"
    if medium_signals:
        return "MEDIUM"

    # Everything else is LOW
    return "LOW"


# ── Main ────────────────────────────────────────────────────────────
def main():
    resp_path = PROJECT_ROOT / "Data" / "Cleaned" / "Mokyr_Survey_Responses_020726_Cleaned.csv"
    w4_path = PROJECT_ROOT / "Data" / "Contact_Lists" / "Mokyr_Survey_Wave4.csv"

    respondents = load_respondents(resp_path)
    wave4 = load_wave4(w4_path)

    print(f"Loaded {len(respondents)} respondents, {len(wave4)} Wave 4 contacts.\n")

    matches = run_matching(wave4, respondents)

    # Group by (w4_idx, resp_idx) – already done
    # Build display records
    records = []
    for (wi, ri), criteria in matches.items():
        w = wave4[wi]
        r = respondents[ri]
        conf = assign_confidence(criteria)
        records.append({
            "w4_name": f"{w['first']} {w['last']}",
            "w4_email": w["email"],
            "w4_source": w["source"],
            "resp_name": f"{r['first']} {r['last']}",
            "resp_email": r["email"],
            "criteria": sorted(criteria),
            "confidence": conf,
        })

    # Sort: HIGH first, then MEDIUM, then LOW; within each, alphabetical by w4_name
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    records.sort(key=lambda x: (order[x["confidence"]], x["w4_name"], x["resp_name"]))

    # Print
    conf_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    sep = "-" * 100

    for rec in records:
        conf_counts[rec["confidence"]] += 1
        print(sep)
        print(f"  Confidence : {rec['confidence']}")
        print(f"  Wave 4     : {rec['w4_name']}  <{rec['w4_email']}>  (Source: {rec['w4_source']})")
        print(f"  Respondent : {rec['resp_name']}  <{rec['resp_email']}>")
        print(f"  Match type : {', '.join(rec['criteria'])}")

    print(sep)
    print(f"\n=== SUMMARY ===")
    print(f"  Total Wave 4 contacts: {len(wave4)}")
    print(f"  Total respondents:     {len(respondents)}")
    print(f"  Flagged pairs:         {len(records)}")
    print(f"    HIGH confidence:     {conf_counts['HIGH']}")
    print(f"    MEDIUM confidence:   {conf_counts['MEDIUM']}")
    print(f"    LOW confidence:      {conf_counts['LOW']}")

    # Also list Wave 4 entries with NO match at all
    flagged_w4 = set(wi for (wi, _) in matches)
    unflagged = [i for i in range(len(wave4)) if i not in flagged_w4]
    print(f"\n  Wave 4 contacts with NO match: {len(unflagged)} of {len(wave4)}")


if __name__ == "__main__":
    main()
