#!/usr/bin/env python3
"""
build_network.py — Build academic genealogy network from Mokyr Survey data.

Outputs:
  Data/Derived/Network_Nodes_{date}.csv
  Data/Derived/Network_Edges_{date}.csv
  Data/Derived/Unresolved_Edges_{date}.csv
"""

import csv
import re
import sys
import difflib
import argparse
from pathlib import Path
from collections import defaultdict, Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATE = "022226"


def normalize_email(email: str) -> str:
    """Lowercase, strip whitespace and trailing semicolons."""
    return email.lower().strip().rstrip(';').strip()


def split_emails(raw_email: str) -> list[str]:
    """Split a possibly semicolon-delimited email string into individual emails."""
    parts = re.split(r'[;\s]+', raw_email or '')
    return [normalize_email(part) for part in parts if '@' in normalize_email(part)]

# ---------------------------------------------------------------------------
# Institution canonicalization
# ---------------------------------------------------------------------------
# Canonical form conventions:
#   - Abbreviations: use only when the acronym IS the institution's primary
#     English identity (MIT, LSE, UCL, CEMFI, NYU).
#   - Business schools / sub-units: roll up to parent university.
#   - Dual affiliations: use primary institution; raw value preserved in *_raw columns.
#   - Bare campus names (e.g. "University of Wisconsin"): assume flagship campus.
INSTITUTION_CANON = {
    # Stanford
    "stanford university": "Stanford University",
    "stanford": "Stanford University",
    "stanford graduate school of business": "Stanford University",
    "stanford university graduate school of business": "Stanford University",
    "hoover institution/stanford university": "Stanford University",
    # Northwestern
    "northwestern university": "Northwestern University",
    "northwestern": "Northwestern University",
    # UCLA
    "ucla": "University of California, Los Angeles",
    "uc los angeles": "University of California, Los Angeles",
    "university of california, los angeles": "University of California, Los Angeles",
    "university of california los angeles": "University of California, Los Angeles",
    "university of california, los angeles - anderson school of business": "University of California, Los Angeles",
    "university of california, los angeles (ucla)": "University of California, Los Angeles",
    # Harvard
    "harvard university": "Harvard University",
    "harvard": "Harvard University",
    # Yale
    "yale university": "Yale University",
    "yale": "Yale University",
    # Chicago
    "university of chicago": "University of Chicago",
    "chicago": "University of Chicago",
    "u chicago": "University of Chicago",
    # MIT
    "massachusetts institute of technology": "MIT",
    "mit": "MIT",
    "mit sloan school of management": "MIT",
    # Princeton
    "princeton university": "Princeton University",
    "princeton": "Princeton University",
    # Penn
    "university of pennsylvania": "University of Pennsylvania",
    "university of pennsylvania, the wharton school": "University of Pennsylvania",
    "wharton": "University of Pennsylvania",
    "upenn": "University of Pennsylvania",
    # Columbia
    "columbia university": "Columbia University",
    "columbia": "Columbia University",
    "columbia university (columbia business school)": "Columbia University",
    # Cornell
    "cornell university": "Cornell University",
    "cornell": "Cornell University",
    # Duke
    "duke university": "Duke University",
    "duke": "Duke University",
    # Michigan
    "university of michigan": "University of Michigan",
    "university of michigan, ross school of business": "University of Michigan",
    # Michigan State
    "michigan state university": "Michigan State University",
    # Notre Dame
    "university of notre dame": "University of Notre Dame",
    "notre dame": "University of Notre Dame",
    # George Mason
    "george mason university": "George Mason University",
    "george mason": "George Mason University",
    "gmu": "George Mason University",
    # LSE
    "london school of economics": "LSE",
    "london school of economics and political science": "LSE",
    "london school of economics & political science": "LSE",
    "lse": "LSE",
    # Oxford
    "university of oxford": "University of Oxford",
    "oxford": "University of Oxford",
    # Cambridge
    "university of cambridge": "University of Cambridge",
    "cambridge": "University of Cambridge",
    # Bocconi
    "bocconi university": "Bocconi University",
    # Toulouse
    "toulouse school of economics": "Toulouse School of Economics",
    "toulouse": "Toulouse School of Economics",
    # PSE
    "paris school of economics": "Paris School of Economics",
    "pse": "Paris School of Economics",
    # UPF
    "universitat pompeu fabra": "Universitat Pompeu Fabra",
    "upf": "Universitat Pompeu Fabra",
    # Hebrew University
    "hebrew university": "Hebrew University of Jerusalem",
    "hebrew university of jerusalem": "Hebrew University of Jerusalem",
    "the hebrew university": "Hebrew University of Jerusalem",
    "hebrew u": "Hebrew University of Jerusalem",
    # Tel Aviv
    "tel aviv university": "Tel Aviv University",
    "tel-aviv university": "Tel Aviv University",
    # NUS
    "national university of singapore": "National University of Singapore",
    "national university of singapore (ongoing)": "National University of Singapore",
    "nus": "National University of Singapore",
    # Tilburg
    "tilburg university": "Tilburg University",
    "tilburg university, nl": "Tilburg University",
    "tilburg": "Tilburg University",
    # KU Leuven
    "ku leuven": "KU Leuven",
    "kuleuven": "KU Leuven",
    # Auburn
    "auburn university": "Auburn University",
    # UC Davis
    "university of california, davis": "University of California, Davis",
    "university of california davis": "University of California, Davis",
    "uc davis": "University of California, Davis",
    # UC Berkeley
    "university of california, berkeley": "University of California, Berkeley",
    "uc berkeley": "University of California, Berkeley",
    "berkeley": "University of California, Berkeley",
    # CEMFI
    "cemfi": "CEMFI",
    # Vanderbilt
    "vanderbilt university": "Vanderbilt University",
    # Monash
    "monash university": "Monash University",
    # UBC
    "university of british columbia": "University of British Columbia",
    "ubc": "University of British Columbia",
    # Peking
    "peking university": "Peking University",
    # --- Additional institutions (Gen 1 coverage) ---
    # University of Tennessee
    "university of tennessee": "University of Tennessee",
    # Bank of Italy
    "bank of italy": "Bank of Italy",
    "banca d'italia": "Bank of Italy",
    # UCL
    "university college london": "UCL",
    "ucl": "UCL",
    # University of Missouri
    "university of missouri": "University of Missouri",
    # QuantCo
    "quantco": "QuantCo",
    # Analysis Group
    "analysis group": "Analysis Group",
    # Williams College
    "williams college": "Williams College",
    # Lake Forest College
    "lake forest college": "Lake Forest College",
    # Hebrew University (variant with leading "The")
    "the hebrew university of jerusalem": "Hebrew University of Jerusalem",
    # Harvard Business School → Harvard
    "harvard business school": "Harvard University",
    "hbs": "Harvard University",
    # Wabash College
    "wabash college": "Wabash College",
    # William & Mary
    "william & mary": "William & Mary",
    "college of william & mary": "William & Mary",
    "college of william and mary": "William & Mary",
    # Northwestern Kellogg → Northwestern
    "northwestern kellogg": "Northwestern University",
    "kellogg school of management": "Northwestern University",
    # Kiel Institute
    "kiel institute": "Kiel Institute for the World Economy",
    "kiel institute for the world economy": "Kiel Institute for the World Economy",
    # Wheaton College
    "wheaton college": "Wheaton College",
    # University of Alberta
    "university of alberta": "University of Alberta",
    # Rutgers
    "rutgers university": "Rutgers University",
    "rutgers university new brunswick": "Rutgers University",
    "rutgers": "Rutgers University",
    # Case Western Reserve
    "case western reserve university": "Case Western Reserve University",
    # Barnard / Columbia
    "barnard college, columbia university": "Barnard College, Columbia University",
    "barnard college": "Barnard College, Columbia University",
    # University of Tokyo
    "university of tokyo": "University of Tokyo",
    # CPP Investments
    "cpp investments": "CPP Investments",
    # Stonehill College
    "stonehill college": "Stonehill College",
    # CUNY
    "city university of new york": "City University of New York",
    "cuny": "City University of New York",
    # GRIPS
    "national graduate institute for policy studies": "GRIPS (National Graduate Institute for Policy Studies)",
    "grips": "GRIPS (National Graduate Institute for Policy Studies)",
    # University of Southern Denmark
    "university of southern denmark": "University of Southern Denmark",
    # Amazon
    "amazon": "Amazon",
    # E Source
    "e source": "E Source",
    # National Economic Council of Israel
    "national economic council of israel": "National Economic Council of Israel",
    # --- Additional institutions (Gen 2-3 coverage) ---
    # WashU
    "washington university in st. louis": "Washington University in St. Louis",
    "washington university (st. louis)": "Washington University in St. Louis",
    "washington university, st. louis": "Washington University in St. Louis",
    "washington university in st. louis, olin business school": "Washington University in St. Louis",
    # USC
    "university of southern california": "University of Southern California",
    "university of southern california, marshall business school": "University of Southern California",
    "usc": "University of Southern California",
    # Uber
    "uber": "Uber",
    "uber technologies, inc": "Uber",
    # Wisconsin (bare "University of Wisconsin" → Madison, the flagship campus)
    "university of wisconsin": "University of Wisconsin-Madison",
    "university of wisconsin madison": "University of Wisconsin-Madison",
    "university of wisconsin-madison": "University of Wisconsin-Madison",
    "university of wisconsin-la crosse": "University of Wisconsin-La Crosse",
    # Ben-Gurion
    "ben-gurion university": "Ben-Gurion University of the Negev",
    "ben-gurion university of the negev": "Ben-Gurion University of the Negev",
    # World Bank
    "the world bank": "World Bank",
    "world bank": "World Bank",
    # Brandeis
    "brandeis university": "Brandeis University",
    # LMU Munich
    "lmu munich": "LMU Munich",
    "ludwig maximilian university of munich": "LMU Munich",
    # Meta
    "meta": "Meta",
    # Renmin
    "renmin university of china": "Renmin University of China",
    # Rochester
    "university of rochester": "University of Rochester",
    # Strathclyde
    "university of strathclyde": "University of Strathclyde",
    # Bergamo
    "university of bergamo": "University of Bergamo",
    # Pisa
    "university of pisa": "University of Pisa",
    # Sant'Anna / Scuola Superiore
    "sant anna school of advanced studies - pisa, italy": "Scuola Superiore Sant'Anna",
    "scuola superiore sant'anna": "Scuola Superiore Sant'Anna",
    # Rutgers New Brunswick (variant without "University")
    "rutgers new brunswick": "Rutgers University",
    # --- Remaining employer misses ---
    # Adelaide
    "adelaide university": "University of Adelaide",
    "university of adelaide": "University of Adelaide",
    # Airbnb
    "airbnb": "Airbnb",
    # Aledade
    "aledade": "Aledade",
    # Arnold Ventures
    "arnold ventures": "Arnold Ventures",
    # BNP Paribas
    "bnp paribas asset management": "BNP Paribas Asset Management",
    # Babson
    "babson college": "Babson College",
    # Banco de Mexico
    "banco de méxico": "Banco de Mexico",
    "banco de mexico": "Banco de Mexico",
    # Bank of Israel
    "bank of israel": "Bank of Israel",
    # Bayes Business School (formerly Cass) → parent institution per rollup convention
    "bayes business school": "City, University of London",
    "bayes business school, city, university of london": "City, University of London",
    "cass business school": "City, University of London",
    "city, university of london": "City, University of London",
    # Bocconi & Bologna (dual affiliation → primary)
    "bocconi & bologna university": "Bocconi University",
    # Center for Global Development
    "center for global development": "Center for Global Development",
    # Chapman
    "chapman university": "Chapman University",
    # Charles River Associates
    "charles river associates": "Charles River Associates",
    # College of Charleston
    "college of charleston": "College of Charleston",
    # College of the Holy Cross
    "college of the holy cross": "College of the Holy Cross",
    # Cornerstone Research
    "cornerstone research": "Cornerstone Research",
    # Dartmouth
    "dartmouth college": "Dartmouth College",
    "dartmouth": "Dartmouth College",
    # ECON Analysis
    "econ|analysis": "ECON Analysis",
    "econ analysis": "ECON Analysis",
    # EIEF
    "eief - einaudi institute for economics & finance": "Einaudi Institute for Economics and Finance",
    "eief": "Einaudi Institute for Economics and Finance",
    "einaudi institute for economics and finance": "Einaudi Institute for Economics and Finance",
    # First Focus on Children
    "first focus on children": "First Focus on Children",
    # Forum on Economic and Fiscal Policy
    "forum on economic and fiscal policy": "Forum on Economic and Fiscal Policy",
    # Government of Alberta
    "government of alberta": "Government of Alberta",
    # University of Florida
    "hamilton school, university of florida": "University of Florida",
    "university of florida": "University of Florida",
    # IIM Lucknow
    "indian institute of management lucknow": "Indian Institute of Management Lucknow",
    # James Madison
    "james madison university": "James Madison University",
    # Joshu
    "joshu inc": "Joshu",
    # King's College London
    "king's college, london": "King's College London",
    "king's college london": "King's College London",
    # Longview Philanthropy
    "longview philanthropy": "Longview Philanthropy",
    # Lund
    "lund university": "Lund University",
    # Miami University (Ohio, not U of Miami)
    "miami university": "Miami University",
    # Ministry for Regulation, New Zealand
    "ministry for regulation, new zealand": "Ministry for Regulation, New Zealand",
    # NERA
    "nera": "NERA Economic Consulting",
    "nera economic consulting": "NERA Economic Consulting",
    # National Bank of Slovakia
    "national bank of slovakia": "National Bank of Slovakia",
    # NYU
    "new york university": "New York University",
    "nyu": "New York University",
    # NYU Abu Dhabi
    "new york university abu dhabi": "NYU Abu Dhabi",
    "nyu abu dhabi": "NYU Abu Dhabi",
    # NOVA SBE
    "nova sbe": "NOVA School of Business and Economics",
    "nova school of business and economics": "NOVA School of Business and Economics",
    # Radboud
    "radboud university nijmegen": "Radboud University",
    "radboud university": "Radboud University",
    # Roblox
    "roblox": "Roblox",
    # Saint Louis University
    "saint louis university": "Saint Louis University",
    # Shanghai University of Finance and Economics
    "shanghai university of finance and economics": "Shanghai University of Finance and Economics",
    # Simon Fraser
    "simon fraser university": "Simon Fraser University",
    "sfu": "Simon Fraser University",
    # Southwick Associates
    "southwick associates": "Southwick Associates",
    # Sun Yat-sen
    "sun yat-sen university": "Sun Yat-sen University",
    # Chinese University of Hong Kong, Shenzhen
    "the chinese university of hong kong, shenzhen": "Chinese University of Hong Kong, Shenzhen",
    "chinese university of hong kong, shenzhen": "Chinese University of Hong Kong, Shenzhen",
    # Tsinghua
    "tsinghua university": "Tsinghua University",
    # UNC Wilmington
    "unc wilmington": "University of North Carolina Wilmington",
    "university of north carolina wilmington": "University of North Carolina Wilmington",
    # Universidad de Chile
    "universidad de chile": "Universidad de Chile",
    # University of Bonn
    "university of bonn": "University of Bonn",
    # University of Bristol
    "university of bristol": "University of Bristol",
    # University of Calcutta
    "university of calcutta": "University of Calcutta",
    # UC Santa Cruz
    "university of california, santa cruz": "University of California, Santa Cruz",
    "uc santa cruz": "University of California, Santa Cruz",
    # University of Evansville
    "university of evansville": "University of Evansville",
    # University of Leicester
    "university of leicester": "University of Leicester",
    # University of Manchester
    "university of manchester": "University of Manchester",
    # UMBC
    "university of maryland baltimore county": "University of Maryland, Baltimore County",
    "umbc": "University of Maryland, Baltimore County",
    # University of Nottingham
    "university of nottingham": "University of Nottingham",
    # University of Puget Sound
    "university of puget sound": "University of Puget Sound",
    # University of Warwick
    "university of warwick": "University of Warwick",
    # Victoria University of Wellington
    "victoria university of wellington": "Victoria University of Wellington",
    # --- Remaining PhD institution misses ---
    # Tor Vergata (key with embedded quotes matches raw survey input verbatim)
    '"tor vergata" university of rome': "University of Rome Tor Vergata",
    "tor vergata university of rome": "University of Rome Tor Vergata",
    "university of rome tor vergata": "University of Rome Tor Vergata",
    # Boston University
    "boston university": "Boston University",
    # Colorado School of Mines
    "colorado school of mines": "Colorado School of Mines",
    # EIEF RED (doctoral program)
    "eief, rome economics doctorate (red)": "Einaudi Institute for Economics and Finance",
    # Eindhoven (with typo)
    "eindhoven univeristy of technology, the netherlands": "Eindhoven University of Technology",
    "eindhoven university of technology": "Eindhoven University of Technology",
    # IIM Bangalore
    "iim bangalore": "Indian Institute of Management Bangalore",
    "indian institute of management bangalore": "Indian Institute of Management Bangalore",
    # Sant'Anna (PhD variant)
    "sant'anna school of advanced studies": "Scuola Superiore Sant'Anna",
    # University of Bologna
    "university of bologna": "University of Bologna",
    # University of Iowa
    "university of iowa": "University of Iowa",
    # University of Melbourne
    "university of melbourne": "University of Melbourne",
    # University of Otago
    "university of otago": "University of Otago",
    # Wisconsin-Milwaukee
    "university of wisconsin-milwaukee": "University of Wisconsin-Milwaukee",
}


def _norm_key(s: str) -> str:
    s = s.strip().lower().rstrip(".,")
    s = s.replace("\u2019", "'").replace("\u02bc", "'")
    return s


def canon_institution(raw: str) -> str:
    if not raw:
        return ""
    return INSTITUTION_CANON.get(_norm_key(raw), "")


# ---------------------------------------------------------------------------
# Q8 generation parsing
# ---------------------------------------------------------------------------
def parse_q8_generation(q8_val: str):
    """Return (generation: int|None, flag: bool).

    flag=True if non-adjacent multi-gen choices selected.
    """
    if not q8_val or not q8_val.strip():
        return None, False

    gen_candidates = set()
    for choice in q8_val.split(","):
        choice = choice.strip().lower()
        # Normalize apostrophes (straight vs. Unicode curly/modifier)
        choice = choice.replace("\u2019", "'").replace("\u02bc", "'")
        # Most-specific-first order
        if "advisor's advisor" in choice:                          # gen 3
            gen_candidates.add(3)
        elif "of my phd advisor" in choice:                        # gen 2
            gen_candidates.add(2)
        elif "advisor of my advisor" in choice:                    # gen 2
            gen_candidates.add(2)
        elif "multiple of my advisors" in choice:                  # gen 2 variant
            gen_candidates.add(2)
        elif "member of my dissertation committee" in choice:      # gen 1 by user convention
            gen_candidates.add(1)
        elif "my phd advisor" in choice or "is my advisor" in choice:  # gen 1
            gen_candidates.add(1)
        # committee-only, "other/i'm not sure", numeric codes → no gen contribution

    if not gen_candidates:
        return None, False

    gen = min(gen_candidates)
    flag = (max(gen_candidates) - min(gen_candidates)) > 1
    return gen, flag


# ---------------------------------------------------------------------------
# Q11 name tokenization + matching helpers
# ---------------------------------------------------------------------------
_HONORIFICS = re.compile(r'\b(dr\.?|prof\.?|professor)\s*', re.IGNORECASE)
_PARENTHETICAL = re.compile(r'\s*\([^)]*\)')
_TRAILING_PUNCT = re.compile(r'[\s.,;:?!]+$')


def clean_token(token: str) -> str:
    """Strip parentheticals, honorifics, trailing punctuation."""
    token = _PARENTHETICAL.sub('', token)
    token = _HONORIFICS.sub('', token)
    token = _TRAILING_PUNCT.sub('', token)
    return token.strip()


def norm_name(s: str) -> str:
    return s.strip().lower()


def is_mokyr_alias(token: str) -> bool:
    """True iff token contains both 'joel' and 'mokyr' (case-insensitive)."""
    tl = token.lower()
    return 'joel' in tl and 'mokyr' in tl


def tokenize_q11(q11_val: str) -> list:
    """Split Q11 value into individual name-candidate tokens.

    Splits on newlines, semicolons, case-insensitive ' and ', then commas.
    Returns a flat list of stripped non-empty strings.
    """
    if not q11_val or not q11_val.strip():
        return []

    # Step 1: newlines
    parts = q11_val.split('\n')
    tokens = []
    for part in parts:
        # Step 2: semicolons
        by_semi = re.split(r'\s*;\s*', part)
        for sub in by_semi:
            # Step 3: case-insensitive ' and '
            by_and = re.split(r'(?i)\s+and\s+', sub)
            tokens.extend(by_and)

    # Step 4: comma-split within each token; try Last,First recombination
    result = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if ',' not in tok:
            result.append(tok)
            continue
        parts_comma = [p.strip() for p in tok.split(',') if p.strip()]
        # Try adjacent single-word pair recombination (Last, First → First Last)
        i = 0
        while i < len(parts_comma):
            if (i + 1 < len(parts_comma)
                    and ' ' not in parts_comma[i]
                    and ' ' not in parts_comma[i + 1]):
                # Recombined candidate: token[i+1] token[i] = "First Last"
                result.append(f"{parts_comma[i + 1]} {parts_comma[i]}")
                i += 2
            else:
                result.append(parts_comma[i])
                i += 1

    return [t for t in result if t.strip()]


# ---------------------------------------------------------------------------
# Data quality overrides (see plan: Data Quality Fixes + Santiago Perez)
# ---------------------------------------------------------------------------

# Survey Preview respondents with numeric Q8 — parse_q8_generation can't parse them.
Q8_GENERATION_OVERRIDES = {
    "R_7vrtdVnraeOr681": 2,  # Santiago Perez (Q11="Ran Abramitzky")
    "R_7rSYUx2xrPi8nia": 1,  # Netanel Ben-Porath (Q11="Joel himself!")
}

# Q12a student name misspellings.
STUDENT_NAME_CORRECTIONS = {
    "Pawel Charsz": "Pawel Charasz",
}

# Q12a student name aliases — map partial name to canonical respondent name.
STUDENT_NAME_ALIASES = {
    ("gian", "pinna"): ("gian marco", "pinna"),
    ("ben", "broman"): ("benjamin", "broman"),
}

# Explicit S-node merge rules for duplicate Q12a students.
SNODE_MERGE = {
    ("anne", "blas"): "merge",
}

# Respondent dedup — discard duplicate ResponseIds (keep the other entry).
RESPONDENT_DEDUP = {
    "R_1xg9ade2GWkIjO9": "R_12xBe57KfXWy6uB",  # Carolyn Tuttle: discard -> keep
}


def _lookup_email_recovery(student_name, node_id, email_recovery):
    """Look up recovered email by (name, node_id) then by name alone."""
    name_lower = student_name.strip().lower()
    # Try compound key first
    result = email_recovery.get((name_lower, node_id))
    if result:
        return result
    # Fall back to name-only key (None = ambiguous, skip)
    result = email_recovery.get(name_lower)
    if result is None and name_lower in email_recovery:
        print(f"  WARN: ambiguous email recovery for {student_name!r}, skipping")
        return None
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Build Mokyr genealogy network node/edge CSVs"
    )
    parser.add_argument('--date', default=DEFAULT_DATE,
                        help="Date suffix for output filenames (MMDDYY)")
    parser.add_argument('--cleaned',
                        default=None,
                        help="Path to cleaned CSV (default: Data/Cleaned/Mokyr_Survey_Responses_{date}_Cleaned.csv)")
    parser.add_argument('--q12a',
                        default=None,
                        help="Path to Q12a derived CSV (default: Data/Derived/Advisors_and_Reported_Students_{date}.csv)")
    parser.add_argument('--email-recovery',
                        default=None,
                        help="Path to email recovery CSV (optional)")
    parser.add_argument('--manual-nodes',
                        default=None,
                        help="Path to manual nodes CSV (optional)")
    args = parser.parse_args()

    date = args.date
    cleaned_path = PROJECT_ROOT / (args.cleaned or f"Data/Cleaned/Mokyr_Survey_Responses_{date}_Cleaned.csv")
    q12a_path    = PROJECT_ROOT / (args.q12a    or f"Data/Derived/Advisors_and_Reported_Students_{date}.csv")
    email_recovery_path = PROJECT_ROOT / args.email_recovery if args.email_recovery else None
    manual_nodes_path   = PROJECT_ROOT / args.manual_nodes   if args.manual_nodes   else None
    nodes_out      = PROJECT_ROOT / f"Data/Derived/Network_Nodes_{date}.csv"
    edges_out      = PROJECT_ROOT / f"Data/Derived/Network_Edges_{date}.csv"
    unresolved_out = PROJECT_ROOT / f"Data/Derived/Unresolved_Edges_{date}.csv"

    # Load email recovery data (optional)
    email_recovery = {}  # (name_lower,) -> email  OR  (name_lower, node_id) -> email
    if email_recovery_path and email_recovery_path.exists():
        print(f"Loading email recovery: {email_recovery_path}")
        with open(email_recovery_path, newline='', encoding='utf-8') as f:
            for erow in csv.DictReader(f):
                recovered = erow.get('recovered_email', '').strip()
                if not recovered:
                    continue
                name = erow.get('name', '').strip().lower()
                nid  = erow.get('node_id', '').strip()
                if nid:
                    email_recovery[(name, nid)] = recovered
                if name:
                    if name in email_recovery:
                        # Multiple entries for same name — mark ambiguous
                        email_recovery[name] = None
                    else:
                        email_recovery[name] = recovered
        n_recovered = sum(1 for v in email_recovery.values() if v is not None)
        print(f"  Loaded {n_recovered} usable recovered emails\n")
    else:
        if email_recovery_path:
            print(f"  WARN: email recovery file not found: {email_recovery_path}\n")

    # -------------------------------------------------------------------------
    # Step A: Load CSV + discover column indices
    # -------------------------------------------------------------------------
    print(f"Loading cleaned CSV: {cleaned_path}")
    with open(cleaned_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)       # row 0: column names
        respondent_rows = list(reader)

    col = {name: idx for idx, name in enumerate(header)}

    required_cols = ['ResponseId', 'Q1', 'Q2', 'Q3', 'Q5_1_TEXT',
                     'Q6', 'Q6a', 'Q8', 'Q9', 'Q10', 'Q11', 'Q12']
    for rc in required_cols:
        if rc not in col:
            sys.exit(f"ERROR: Required column '{rc}' not found in {cleaned_path}")

    # Build respondents dict and lookup indices
    _SENTINEL = object()
    respondents = {}    # ResponseId -> dict
    email_to_rid = {}   # email.lower() -> ResponseId
    name_to_rid = {}    # (first_lower, last_lower) -> ResponseId | None (None=ambiguous)

    for row in respondent_rows:
        rid = row[col['ResponseId']].strip()
        if not rid or not rid.startswith("R_"):
            continue
        if rid in RESPONDENT_DEDUP:
            print(f"  INFO respondent dedup: skipping {rid} (kept {RESPONDENT_DEDUP[rid]})")
            continue
        first = row[col['Q1']].strip()
        last  = row[col['Q2']].strip()
        email = row[col['Q3']].strip()
        respondents[rid] = {
            'first':   first,
            'last':    last,
            'email':   email,
            'q5_text': row[col['Q5_1_TEXT']].strip(),
            'q6':      row[col['Q6']].strip(),
            'q6a':     row[col['Q6a']].strip(),
            'q8':      row[col['Q8']].strip(),
            'q9':      row[col['Q9']].strip(),
            'q10':     row[col['Q10']].strip(),
            'q11':     row[col['Q11']].strip(),
            'q12':     row[col['Q12']].strip(),
        }
        if email:
            email_to_rid[email.lower()] = rid
        name_key = (first.lower(), last.lower())
        if name_key in name_to_rid:
            name_to_rid[name_key] = None  # ambiguous
        else:
            name_to_rid[name_key] = rid

    print(f"Loaded {len(respondents)} respondents\n")

    # Print Q8 distribution (detects numeric encoding early)
    q8_dist = Counter(r['q8'] for r in respondents.values())
    print("=== Q8 distribution ===")
    for val, cnt in q8_dist.most_common():
        print(f"  {cnt:3d}  {val!r}")
    print()

    # Full-name lookup (only unambiguous entries)
    name_lookup = {}  # norm("first last") -> ResponseId
    for (fl, ll), rid in name_to_rid.items():
        if rid is not None:
            name_lookup[f"{fl} {ll}"] = rid

    # -------------------------------------------------------------------------
    # Step B: Parse Q8 → generation
    # -------------------------------------------------------------------------
    gen_by_rid = {}
    for rid, r in respondents.items():
        if rid in Q8_GENERATION_OVERRIDES:
            gen = Q8_GENERATION_OVERRIDES[rid]
            print(f"  INFO Q8 override: {r['first']} {r['last']} ({rid}) -> Gen {gen}")
            gen_by_rid[rid] = gen
            continue
        gen, flag = parse_q8_generation(r['q8'])
        gen_by_rid[rid] = gen
        if flag:
            print(f"  WARN non-adjacent multi-gen Q8: {r['first']} {r['last']} ({rid}): {r['q8']!r}")

    # -------------------------------------------------------------------------
    # Step C: Institution canonicalization
    # -------------------------------------------------------------------------
    canon_misses_phd = set()
    canon_misses_emp = set()
    for r in respondents.values():
        r['phd_canon'] = canon_institution(r['q9'])
        r['emp_canon'] = canon_institution(r['q5_text'])
        if r['q9'] and not r['phd_canon']:
            canon_misses_phd.add(r['q9'])
        if r['q5_text'] and not r['emp_canon']:
            canon_misses_emp.add(r['q5_text'])

    # -------------------------------------------------------------------------
    # Step D: Q11 advisor name matching
    # -------------------------------------------------------------------------
    advisor_by_rid  = {}    # ResponseId -> list of (source_id, confidence, note)
    unresolved_edges = []   # list of dicts

    def _match_token(token, rid, r, gen):
        """Try to resolve one name token.  Returns source_id or None (logs unresolved)."""
        cleaned = clean_token(token)
        if not cleaned:
            return None
        cn = norm_name(cleaned)

        # Mokyr alias: must contain both 'joel' and 'mokyr'
        if is_mokyr_alias(cn):
            return 'JM-ROOT'

        # Exact match
        if cn in name_lookup:
            return f"R-{name_lookup[cn]}"

        # Fuzzy (cutoff 0.75)
        matches = difflib.get_close_matches(cn, name_lookup.keys(), n=2, cutoff=0.75)
        if len(matches) == 1:
            return f"R-{name_lookup[matches[0]]}"
        if len(matches) >= 2:
            s1 = difflib.SequenceMatcher(None, cn, matches[0]).ratio()
            s2 = difflib.SequenceMatcher(None, cn, matches[1]).ratio()
            if s1 - s2 < 0.05:
                unresolved_edges.append({
                    'source_id': None, 'target_id': f"R-{rid}",
                    'reason': 'ambiguous_q11', 'raw_q11': token,
                    'respondent': f"{r['first']} {r['last']}", 'gen': gen,
                    'note': f"{matches[0]!r}({s1:.3f}) vs {matches[1]!r}({s2:.3f})",
                })
                return None
            return f"R-{name_lookup[matches[0]]}"

        unresolved_edges.append({
            'source_id': None, 'target_id': f"R-{rid}",
            'reason': 'unresolved_q11', 'raw_q11': token,
            'respondent': f"{r['first']} {r['last']}", 'gen': gen,
            'note': '',
        })
        return None

    for rid, r in respondents.items():
        gen = gen_by_rid[rid]
        if gen is None:
            continue

        if gen == 1:
            # Direct Mokyr student — no Q11 resolution needed
            advisor_by_rid[rid] = [('JM-ROOT', 'high', 'q8_gen1')]
            continue

        # gen >= 2: must resolve Q11
        q11 = r['q11']
        if not q11:
            unresolved_edges.append({
                'source_id': None, 'target_id': f"R-{rid}",
                'reason': 'missing_q11', 'raw_q11': '',
                'respondent': f"{r['first']} {r['last']}", 'gen': gen,
                'note': '',
            })
            continue

        # Full-string exact match first (no fuzzy on full string)
        full_norm = norm_name(q11)
        if is_mokyr_alias(full_norm):
            advisor_by_rid[rid] = [('JM-ROOT', 'high', 'mokyr_alias_full')]
            continue
        if full_norm in name_lookup:
            advisor_by_rid[rid] = [(f"R-{name_lookup[full_norm]}", 'high', 'exact_full')]
            continue

        # Split into tokens
        tokens = tokenize_q11(q11)
        for tok in tokens:
            src = _match_token(tok, rid, r, gen)
            if src is not None:
                conf = 'medium' if 'fuzzy' in tok else 'high'
                # Re-derive confidence by checking if full cn was exact
                cleaned = clean_token(tok)
                cn = norm_name(cleaned) if cleaned else ''
                if cn in name_lookup or is_mokyr_alias(cn):
                    conf = 'high'
                else:
                    conf = 'medium'
                advisor_by_rid.setdefault(rid, []).append((src, conf, f'token:{tok!r}'))

    # -------------------------------------------------------------------------
    # Step E: Build node table
    # -------------------------------------------------------------------------
    nodes = {}  # node_id -> dict

    # Root node
    nodes['JM-ROOT'] = {
        'node_id': 'JM-ROOT',
        'first_name': 'Joel',
        'last_name': 'Mokyr',
        'email': '',
        'phd_institution_raw': '',
        'phd_institution_canon': '',
        'current_employer_raw': 'Northwestern University',
        'current_employer_canon': 'Northwestern University',
        'phd_year': '',
        'country': 'United States',
        'us_state': 'Illinois',
        'generation': 0,
        'generation_q8': 0,
        'has_students': True,
        'is_respondent': False,
    }

    # Respondent nodes
    for rid, r in respondents.items():
        node_id = f"R-{rid}"
        nodes[node_id] = {
            'node_id': node_id,
            'first_name': r['first'],
            'last_name': r['last'],
            'email': r['email'],
            'phd_institution_raw': r['q9'],
            'phd_institution_canon': r['phd_canon'],
            'current_employer_raw': r['q5_text'],
            'current_employer_canon': r['emp_canon'],
            'phd_year': r['q10'],
            'country': r['q6'],
            'us_state': r['q6a'],
            'generation': gen_by_rid[rid],
            'generation_q8': gen_by_rid[rid],
            'has_students': r['q12'].strip().lower() in ('yes', '1', 'true'),
            'is_respondent': True,
        }

    # Q12a-only nodes
    print(f"Loading Q12a derived file: {q12a_path}")
    with open(q12a_path, newline='', encoding='utf-8') as f:
        q12a_rows = list(csv.DictReader(f))
    print(f"Loaded {len(q12a_rows)} Q12a advisor-student pairs\n")

    # Group Q12a rows by advisor name
    advisor_groups = defaultdict(list)
    for row in q12a_rows:
        key = (row['Advisor_FirstName'].strip().lower(),
               row['Advisor_LastName'].strip().lower())
        advisor_groups[key].append(row)

    q12a_edge_triples = []  # (source_id, target_id, confidence)
    s_counter = defaultdict(int)  # source_id -> count for unique S- IDs

    for (adv_fl, adv_ll), student_rows in advisor_groups.items():
        # Resolve advisor → source_id
        adv_rid = name_to_rid.get((adv_fl, adv_ll), _SENTINEL)
        if adv_rid is _SENTINEL:
            # Key not in dict — try fuzzy
            adv_full = f"{adv_fl} {adv_ll}"
            matches = difflib.get_close_matches(adv_full, name_lookup.keys(), n=1, cutoff=0.8)
            if matches:
                adv_rid = name_lookup[matches[0]]
            elif 'mokyr' in adv_ll:
                source_id = 'JM-ROOT'
                adv_rid = None  # handled below via source_id
            else:
                unresolved_edges.append({
                    'source_id': None, 'target_id': f"Q12a-{adv_fl}-{adv_ll}",
                    'reason': 'unresolved_q12a_advisor',
                    'raw_q11': f"{adv_fl} {adv_ll}",
                    'respondent': f"{adv_fl} {adv_ll}", 'gen': None, 'note': '',
                })
                continue

        if adv_rid is None and 'mokyr' not in adv_ll:
            # Ambiguous advisor name
            unresolved_edges.append({
                'source_id': None, 'target_id': f"Q12a-{adv_fl}-{adv_ll}",
                'reason': 'ambiguous_q12a_advisor',
                'raw_q11': f"{adv_fl} {adv_ll}",
                'respondent': f"{adv_fl} {adv_ll}", 'gen': None, 'note': '',
            })
            continue

        source_id = 'JM-ROOT' if (adv_rid is None and 'mokyr' in adv_ll) else f"R-{adv_rid}"

        for row in student_rows:
            student_name  = row['Student_Info_Cleaned'].strip()
            student_email = row['Student_Email'].strip()
            student_emails = split_emails(student_email)
            primary_student_email = student_emails[0] if student_emails else ''

            # Apply name corrections (misspellings)
            if student_name in STUDENT_NAME_CORRECTIONS:
                corrected = STUDENT_NAME_CORRECTIONS[student_name]
                print(f"  INFO name correction: {student_name!r} -> {corrected!r}")
                student_name = corrected

            # Check if student is already a respondent
            student_rid = None
            if student_emails:
                for email in student_emails:
                    student_rid = email_to_rid.get(email)
                    if student_rid is not None:
                        break
            if student_rid is None and student_name:
                parts = student_name.split()
                if len(parts) >= 2:
                    skey = (parts[0].lower(), parts[-1].lower())
                    # Apply name aliases before matching
                    skey = STUDENT_NAME_ALIASES.get(skey, skey)
                    val = name_to_rid.get(skey, _SENTINEL)
                    if val is not _SENTINEL and val is not None:
                        student_rid = val
                    # If ambiguous (val is None) or not found: create new node

            if student_rid is not None:
                target_id = f"R-{student_rid}"
            else:
                # Check SNODE_MERGE: reuse existing S-node if rule exists
                sparts = student_name.split() if student_name else []
                s_first = sparts[0].lower() if sparts else ''
                s_last  = ' '.join(sparts[1:]).lower() if len(sparts) > 1 else ''
                merge_key = (s_first, s_last)

                merged = False
                if merge_key in SNODE_MERGE:
                    # Find existing S-node with this name
                    for nid, n in nodes.items():
                        if (nid.startswith('S-')
                                and n['first_name'].lower() == s_first
                                and n['last_name'].lower() == s_last):
                            target_id = nid
                            # Backfill empty fields
                            backfilled = []
                            if not n['email'] and primary_student_email:
                                n['email'] = primary_student_email
                                backfilled.append('email')
                            print(f"  INFO: Merged duplicate S-node for {student_name}"
                                  + (f" (backfilled: {', '.join(backfilled)})" if backfilled else ""))
                            merged = True
                            break

                if not merged:
                    # Create Q12a-only node
                    s_counter[source_id] += 1
                    idx = s_counter[source_id]
                    safe_src = source_id.replace('R-', '').replace('JM-ROOT', 'JMR')
                    target_id = f"S-{safe_src}-{idx:04d}"

                    # Determine generation from parent
                    if source_id == 'JM-ROOT':
                        student_gen = 1
                    elif source_id in nodes:
                        pg = nodes[source_id].get('generation')
                        student_gen = (pg + 1) if pg is not None else None
                        if student_gen is None:
                            print(f"  INFO: Q12a student {student_name!r} has parent {source_id} with generation=None")
                    else:
                        student_gen = None

                    # Apply recovered email if Q12a email is empty
                    if not primary_student_email and email_recovery:
                        recovered = _lookup_email_recovery(
                            student_name, target_id, email_recovery)
                        if recovered:
                            primary_student_email = recovered

                    nodes[target_id] = {
                        'node_id': target_id,
                        'first_name': sparts[0] if sparts else '',
                        'last_name': ' '.join(sparts[1:]) if len(sparts) > 1 else '',
                        'email': primary_student_email,
                        'phd_institution_raw': '',
                        'phd_institution_canon': '',
                        'current_employer_raw': '',
                        'current_employer_canon': '',
                        'phd_year': '',
                        'country': '',
                        'us_state': '',
                        'generation': student_gen,
                        'generation_q8': None,
                        'has_students': False,
                        'is_respondent': False,
                    }

            q12a_edge_triples.append((source_id, target_id, 'high'))

    # -------------------------------------------------------------------------
    # Step E2: Load manual nodes (optional)
    # -------------------------------------------------------------------------
    manual_edge_triples = []
    if manual_nodes_path and manual_nodes_path.exists():
        print(f"Loading manual nodes: {manual_nodes_path}")
        with open(manual_nodes_path, newline='', encoding='utf-8') as f:
            manual_rows = list(csv.DictReader(f))
        print(f"  {len(manual_rows)} manual node entries")

        # Build lookup for existing nodes by (first_lower, last_lower)
        existing_name_nodes = {}
        for nid, n in nodes.items():
            nkey = (n['first_name'].lower(), n['last_name'].lower())
            existing_name_nodes.setdefault(nkey, []).append(nid)

        for mrow in manual_rows:
            mfirst = mrow['first_name'].strip()
            mlast  = mrow['last_name'].strip()
            memail = mrow['email'].strip()
            madv   = mrow['advisor_source'].strip()
            mgen   = mrow['generation'].strip()
            mgen   = int(mgen) if mgen else None

            # Check if node already exists (by name + email)
            mkey = (mfirst.lower(), mlast.lower())
            found_nid = None
            if mkey in existing_name_nodes:
                for candidate_nid in existing_name_nodes[mkey]:
                    cn = nodes[candidate_nid]
                    if memail and cn['email'] and cn['email'].lower() == memail.lower():
                        found_nid = candidate_nid
                        break
                    if not cn['email'] or not memail:
                        found_nid = candidate_nid
                        break
            # Also check email_to_rid
            if found_nid is None and memail:
                erid = email_to_rid.get(memail.lower())
                if erid:
                    found_nid = f"R-{erid}"

            if found_nid:
                print(f"  SKIP manual node {mfirst} {mlast}: already exists as {found_nid}")
                continue

            # Validate advisor_source
            if madv != 'JM-ROOT' and madv not in nodes:
                print(f"  WARN: manual node {mfirst} {mlast} has unresolved advisor_source {madv!r}, skipping")
                unresolved_edges.append({
                    'source_id': madv, 'target_id': f"M-{mfirst.lower()}-{mlast.lower()}",
                    'reason': 'unresolved_manual_advisor',
                    'raw_q11': madv,
                    'respondent': f"{mfirst} {mlast}", 'gen': mgen, 'note': '',
                })
                continue

            # Generate M- ID
            slug_first = mfirst.lower().replace(' ', '-')
            slug_last  = mlast.lower().replace(' ', '-')
            m_id = f"M-{slug_first}-{slug_last}"
            # Handle collision
            if m_id in nodes:
                suffix = 2
                while f"{m_id}-{suffix}" in nodes:
                    suffix += 1
                m_id = f"{m_id}-{suffix}"

            nodes[m_id] = {
                'node_id': m_id,
                'first_name': mfirst,
                'last_name': mlast,
                'email': memail,
                'phd_institution_raw': '',
                'phd_institution_canon': '',
                'current_employer_raw': '',
                'current_employer_canon': '',
                'phd_year': '',
                'country': '',
                'us_state': '',
                'generation': mgen,
                'generation_q8': None,
                'has_students': False,
                'is_respondent': False,
            }
            manual_edge_triples.append((madv, m_id, 'high'))
            print(f"  Added manual node: {m_id} ({mfirst} {mlast}, Gen {mgen})")

        print(f"  Created {len(manual_edge_triples)} manual nodes\n")
    elif manual_nodes_path:
        print(f"  WARN: manual nodes file not found: {manual_nodes_path}\n")

    # -------------------------------------------------------------------------
    # Step F: Build edge list + cycle detection + generation consistency
    # -------------------------------------------------------------------------
    raw_edges = []  # (source_id, target_id, edge_type, confidence)

    # Q8/Q11-derived edges
    for rid in respondents:
        node_id = f"R-{rid}"
        for (src, conf, _note) in advisor_by_rid.get(rid, []):
            raw_edges.append((src, node_id, 'advisor', conf))

    # Q12a-derived edges
    for (src, tgt, conf) in q12a_edge_triples:
        raw_edges.append((src, tgt, 'q12a', conf))

    # Manual-node edges
    for (src, tgt, conf) in manual_edge_triples:
        raw_edges.append((src, tgt, 'manual', conf))

    # Deduplicate edges
    seen_edges = set()
    deduped = []
    for e in raw_edges:
        key = (e[0], e[1], e[2])
        if key not in seen_edges:
            seen_edges.add(key)
            deduped.append(e)
    raw_edges = deduped

    # Cycle detection via DFS
    graph = defaultdict(set)
    for s, t, _, _ in raw_edges:
        graph[s].add(t)

    visited   = set()
    rec_stack = set()
    cycle_pairs = set()

    def dfs(node):
        visited.add(node)
        rec_stack.add(node)
        for nb in list(graph.get(node, [])):
            if nb not in visited:
                dfs(nb)
            elif nb in rec_stack:
                cycle_pairs.add((node, nb))
        rec_stack.discard(node)

    all_nodes_in_edges = {s for s, _, _, _ in raw_edges} | {t for _, t, _, _ in raw_edges}
    for n in all_nodes_in_edges:
        if n not in visited:
            dfs(n)

    if cycle_pairs:
        print(f"  WARN: {len(cycle_pairs)} cycle edge(s) detected")

    clean_edges = []
    for e in raw_edges:
        s, t, etype, conf = e
        if (s, t) in cycle_pairs:
            unresolved_edges.append({
                'source_id': s, 'target_id': t,
                'reason': 'cycle_detected', 'raw_q11': '',
                'respondent': '', 'gen': None, 'note': '',
            })
        else:
            clean_edges.append(e)

    # Generation consistency — propagate rooted generations through the graph
    child_parents = defaultdict(list)
    for s, t, _, _ in clean_edges:
        child_parents[t].append(s)

    changed = True
    while changed:
        changed = False
        parent_gens = {nid: n['generation'] for nid, n in nodes.items()}

        for nid, node in nodes.items():
            parent_gen_values = [
                parent_gens[src] for src in child_parents.get(nid, [])
                if parent_gens.get(src) not in (None, '')
            ]
            if not parent_gen_values:
                continue
            gen_from_topo = min(parent_gen_values) + 1
            old_gen = node['generation']
            q8_gen = node['generation_q8']

            if old_gen in (None, ''):
                node['generation'] = gen_from_topo
                changed = True
            elif gen_from_topo != old_gen:
                print(f"  GEN OVERRIDE: {nid} {node['first_name']} {node['last_name']}: "
                      f"reported={q8_gen} → topo={gen_from_topo}")
                node['generation'] = gen_from_topo
                changed = True

    # -------------------------------------------------------------------------
    # Step G: Write outputs + report
    # -------------------------------------------------------------------------
    NODE_COLS = [
        'node_id', 'first_name', 'last_name', 'email',
        'phd_institution_raw', 'phd_institution_canon',
        'current_employer_raw', 'current_employer_canon',
        'phd_year', 'country', 'us_state',
        'generation', 'generation_q8', 'has_students', 'is_respondent',
    ]
    EDGE_COLS = ['source_id', 'target_id', 'edge_type', 'confidence']
    UNRESOLVED_COLS = ['source_id', 'target_id', 'reason', 'raw_q11', 'respondent', 'gen', 'note']

    with open(nodes_out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=NODE_COLS)
        w.writeheader()
        for n in nodes.values():
            w.writerow({k: n.get(k, '') for k in NODE_COLS})

    with open(edges_out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=EDGE_COLS)
        w.writeheader()
        for s, t, etype, conf in clean_edges:
            w.writerow({'source_id': s, 'target_id': t, 'edge_type': etype, 'confidence': conf})

    with open(unresolved_out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=UNRESOLVED_COLS)
        w.writeheader()
        for u in unresolved_edges:
            w.writerow({k: u.get(k, '') for k in UNRESOLVED_COLS})

    # Summary
    n_respondent = sum(1 for n in nodes.values() if n['is_respondent'])
    n_q12a_only  = sum(1 for n in nodes.values() if not n['is_respondent'] and n['node_id'] != 'JM-ROOT')
    conf_counts  = Counter(e[3] for e in clean_edges)

    print(f"\n=== Summary ===")
    print(f"  Nodes : {len(nodes)} total  ({n_respondent} respondents, {n_q12a_only} Q12a-only, 1 root)")
    print(f"  Edges : {len(clean_edges)} total  ({dict(conf_counts)})")
    print(f"  Unresolved : {len(unresolved_edges)}")

    print(f"\n  Canon misses (PhD institution): {len(canon_misses_phd)}")
    for m in sorted(canon_misses_phd):
        print(f"    {m!r}")
    print(f"\n  Canon misses (employer): {len(canon_misses_emp)}")
    for m in sorted(canon_misses_emp):
        print(f"    {m!r}")

    print(f"\nOutputs written:")
    print(f"  {nodes_out}")
    print(f"  {edges_out}")
    print(f"  {unresolved_out}")


if __name__ == '__main__':
    main()
