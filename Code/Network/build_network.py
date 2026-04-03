#!/usr/bin/env python3
"""
build_network.py — Build academic genealogy network from Mokyr Survey data.

Outputs:
  Data/Derived/Network_Nodes_{date}.csv
  Data/Derived/Network_Edges_{date}.csv
  Data/Derived/Unresolved_Edges_{date}.csv
  Data/Derived/Network_Discrepancies_{date}.csv

Optional curated inputs:
  Data/Derived/Manual_Nodes_{date}.csv
  Data/Derived/Manual_Edges_{date}.csv
  Data/Derived/Gen2_Nonrespondent_Backfill_Approved_{date}.csv

The approved backfill CSV enriches existing nodes (matched by node_id) with
web-researched metadata.  It does not create nodes; all node_ids must already
exist after respondent + Q12a + manual node creation.  Semantics:
  nonblank backfill_*  → set/overwrite that field
  blank backfill_*     → no change
  clear_fields column  → comma-separated canonical field names to set to ''

Manual_Nodes supports the legacy minimal schema:
  first_name,last_name,email,advisor_source,generation

It also accepts optional enrichment columns used to backfill node metadata:
  phd_institution_raw,phd_institution_canon,current_employer_raw,
  current_employer_canon,phd_year,country,us_state
"""

import csv
import re
import sys
import difflib
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict, Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "Code"))

from Shared.name_normalization import normalize_person_text, person_name_key

_CLEANED_DATE_RE = re.compile(r"^Mokyr_Survey_Responses_(\d{6})_Cleaned\.csv$")
_Q12A_DATE_RE = re.compile(r"^Advisors_and_Reported_Students_(\d{6})\.csv$")


def normalize_email(email: str) -> str:
    """Lowercase, strip whitespace and trailing semicolons."""
    return email.lower().strip().rstrip(';').strip()


def split_emails(raw_email: str) -> list[str]:
    """Split a possibly semicolon-delimited email string into individual emails."""
    parts = re.split(r'[;\s]+', raw_email or '')
    return [normalize_email(part) for part in parts if '@' in normalize_email(part)]


def _latest_matching_date(base_dir: Path, pattern: re.Pattern[str]) -> str | None:
    if not base_dir.exists():
        sys.exit(f"ERROR: Expected directory not found while inferring latest date: {base_dir}")
    matches = []
    for path in base_dir.iterdir():
        match = pattern.match(path.name)
        if not match:
            continue
        matches.append(match.group(1))
    if not matches:
        return None
    return max(matches, key=lambda token: datetime.strptime(token, "%m%d%y"))


def _extract_date_token(path_str: str | None) -> str | None:
    if not path_str:
        return None
    match = re.search(r"(\d{6})", Path(path_str).name)
    return match.group(1) if match else None


def _resolve_build_date(date_arg: str | None, cleaned_arg: str | None, q12a_arg: str | None) -> str:
    if date_arg:
        return date_arg

    explicit_dates = {
        token for token in (
            _extract_date_token(cleaned_arg),
            _extract_date_token(q12a_arg),
        )
        if token
    }
    if len(explicit_dates) > 1:
        sys.exit(
            "ERROR: --cleaned and --q12a imply different dates. "
            "Pass --date explicitly or provide aligned inputs."
        )
    if explicit_dates:
        return explicit_dates.pop()

    latest_cleaned = _latest_matching_date(PROJECT_ROOT / "Data" / "Cleaned", _CLEANED_DATE_RE)
    latest_q12a = _latest_matching_date(PROJECT_ROOT / "Data" / "Derived", _Q12A_DATE_RE)
    if not latest_cleaned or not latest_q12a:
        sys.exit(
            "ERROR: Could not infer a default date from cleaned/Q12a inputs. "
            "Pass --date explicitly."
        )
    if latest_cleaned != latest_q12a:
        sys.exit(
            "ERROR: Latest cleaned and Q12a files have different dates "
            f"({latest_cleaned} vs {latest_q12a}). Pass --date or explicit paths."
        )
    print(f"INFO: Using latest common cleaned/Q12a date: {latest_cleaned}")
    return latest_cleaned

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
    "school of social sciences, tsinghua university": "Tsinghua University, School of Social Sciences",
    "institute of economics, school of social sciences, tsinghua university": "Tsinghua University, School of Social Sciences",
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
    # --- Backfill-sourced institutions (Gen 2 nonrespondent enrichment) ---
    # Kent State University
    "kent state university": "Kent State University",
    "kent state": "Kent State University",
    # Ahmedabad University
    "ahmedabad university": "Ahmedabad University",
    # Alberta Health Services
    "alberta health services": "Alberta Health Services",
    # Align Technology
    "align technology": "Align Technology",
    # Bank of England
    "bank of england": "Bank of England",
    # Butler University
    "butler university": "Butler University",
    # CEIBS (China Europe International Business School)
    "ceibs": "CEIBS",
    "china europe international business school": "CEIBS",
    # California ISO
    "california iso": "California ISO",
    "caiso": "California ISO",
    # Centre for Development Studies (Trivandrum)
    "centre for development studies": "Centre for Development Studies",
    # Citadel LLC
    "citadel llc": "Citadel LLC",
    "citadel": "Citadel LLC",
    # City St George's, University of London (2024 rename of City, University of London)
    "city st george's, university of london": "City St George's, University of London",
    # Compass Lexecon
    "compass lexecon": "Compass Lexecon",
    # Deakin University
    "deakin university": "Deakin University",
    # Georgia Southern University
    "georgia southern university": "Georgia Southern University",
    # IIM Ahmedabad
    "indian institute of management ahmedabad": "Indian Institute of Management Ahmedabad",
    "iim ahmedabad": "Indian Institute of Management Ahmedabad",
    # Nanyang Technological University
    "nanyang technological university": "Nanyang Technological University",
    "ntu singapore": "Nanyang Technological University",
    # OECD
    "oecd": "OECD",
    "organisation for economic co-operation and development": "OECD",
    # Perlman Eilat and Co.
    "perlman eilat and co.": "Perlman Eilat and Co.",
    "perlman eilat and co": "Perlman Eilat and Co.",
    # Productivity Commission (Australia)
    "productivity commission": "Productivity Commission",
    # Red River College Polytechnic
    "red river college polytechnic": "Red River College Polytechnic",
    "red river college": "Red River College Polytechnic",
    # Susquehanna University
    "susquehanna university": "Susquehanna University",
    # University of Pittsburgh
    "university of pittsburgh": "University of Pittsburgh",
    # University of Salamanca
    "university of salamanca": "University of Salamanca",
    # University of Washington
    "university of washington": "University of Washington",
    "uw": "University of Washington",
    # Xi'an Jiaotong-Liverpool University
    "xi'an jiaotong-liverpool university": "Xi'an Jiaotong-Liverpool University",
    "xjtlu": "Xi'an Jiaotong-Liverpool University",
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
def parse_q8_generation(q8_val: str) -> dict:
    """Classify Q8 into generation evidence and review flags.

    Committee membership alone is not treated as direct-advisee evidence.
    Mixed committee + indirect cases are left for manual review rather than
    auto-assigned from Q8.
    """
    result = {
        'generation': None,
        'raw_generation': None,
        'flag': False,
        'has_direct': False,
        'has_committee': False,
        'has_indirect': False,
        'requires_manual_review': False,
    }
    if not q8_val or not q8_val.strip():
        return result

    raw_candidates = set()
    effective_candidates = set()

    for choice in q8_val.split(","):
        choice = choice.strip().lower()
        # Normalize apostrophes (straight vs. Unicode curly/modifier)
        choice = choice.replace("\u2019", "'").replace("\u02bc", "'")
        # Most-specific-first order
        if "advisor's advisor" in choice:                          # gen 3
            raw_candidates.add(3)
            effective_candidates.add(3)
            result['has_indirect'] = True
        elif "of my phd advisor" in choice:                        # gen 2
            raw_candidates.add(2)
            effective_candidates.add(2)
            result['has_indirect'] = True
        elif "advisor of my advisor" in choice:                    # gen 2
            raw_candidates.add(2)
            effective_candidates.add(2)
            result['has_indirect'] = True
        elif "multiple of my advisors" in choice:                  # gen 2 variant
            raw_candidates.add(2)
            effective_candidates.add(2)
            result['has_indirect'] = True
        elif "member of my dissertation committee" in choice:
            raw_candidates.add(1)
            result['has_committee'] = True
        elif "my phd advisor" in choice or "is my advisor" in choice:  # gen 1
            raw_candidates.add(1)
            effective_candidates.add(1)
            result['has_direct'] = True
        # committee-only, "other/i'm not sure", numeric codes → no effective gen contribution

    if raw_candidates:
        result['raw_generation'] = min(raw_candidates)
        result['flag'] = (max(raw_candidates) - min(raw_candidates)) > 1

    result['requires_manual_review'] = (
        result['has_committee'] and result['has_indirect'] and not result['has_direct']
    )
    if not result['requires_manual_review'] and effective_candidates:
        result['generation'] = min(effective_candidates)

    return result


def norm_name(s: str) -> str:
    return normalize_person_text(s)


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

# Curated respondent metadata overrides from strong post-survey verification.
RESPONDENT_METADATA_OVERRIDES = {
    "R_9i4H75l7IKGKK6n": {
        "q5_text": "Institute of Economics, School of Social Sciences, Tsinghua University",
    },
}

# Q12a student name misspellings.
_STUDENT_NAME_CORRECTIONS_RAW = {
    "Pawel Charsz": "Pawel Charasz",
}

STUDENT_NAME_CORRECTIONS = {
    normalize_person_text(source_name): target_name
    for source_name, target_name in _STUDENT_NAME_CORRECTIONS_RAW.items()
}

# Q12a student name aliases — map partial name to canonical respondent name.
_STUDENT_NAME_ALIASES_RAW = {
    ("Gian", "Pinna"): ("Gian Marco", "Pinna"),
    ("Ben", "Broman"): ("Benjamin", "Broman"),
    ("Juan", "Gonzalez Blanco"): ("Juan", "González"),
    ("Burkett", "Evans"): ("Burke", "Evans"),
    ("Geoff", "Clark"): ("Geoff", "Clarke"),
}

STUDENT_NAME_ALIASES = {
    person_name_key(source_first, source_last): person_name_key(target_first, target_last)
    for (source_first, source_last), (target_first, target_last) in _STUDENT_NAME_ALIASES_RAW.items()
}

# Explicit S-node merge rules for duplicate Q12a students.
_SNODE_MERGE_RAW = {
    ("Anne", "Blas"): "merge",
}

SNODE_MERGE = {
    person_name_key(first_name, last_name): action
    for (first_name, last_name), action in _SNODE_MERGE_RAW.items()
}

# Respondent dedup — discard duplicate ResponseIds (keep the other entry).
RESPONDENT_DEDUP = {
    "R_1xg9ade2GWkIjO9": "R_12xBe57KfXWy6uB",  # Carolyn Tuttle: discard -> keep
}

# Curated manual/respondent duplicate matches for verified identity merges.
_MANUAL_RESPONDENT_DEDUP_RAW = {
    ("Carl", "Hallmann"): "R_2eK0hmgM4y2gCXr",
    ("Jon", "Hartley"): "R_11MnENdbOxOicDt",
    ("Peter", "Meyer"): "R_1IE5Y4BmXmFwwbe",
    ("Thomas", "Geraghty"): "R_1KE1sbrmfVgvF1B",
}

MANUAL_RESPONDENT_DEDUP = {
    person_name_key(first_name, last_name): rid
    for (first_name, last_name), rid in _MANUAL_RESPONDENT_DEDUP_RAW.items()
}


def _lookup_email_recovery(student_name, node_id, email_recovery):
    """Look up recovered email by (name, node_id) then by name alone."""
    name_key = normalize_person_text(student_name)
    # Try compound key first
    result = email_recovery.get((name_key, node_id))
    if result:
        return result
    # Fall back to name-only key (None = ambiguous, skip)
    result = email_recovery.get(name_key)
    if result is None and name_key in email_recovery:
        print(f"  WARN: ambiguous email recovery for {student_name!r}, skipping")
        return None
    return result


def _person_name_key(first_name: str, last_name: str) -> tuple[str, str]:
    return person_name_key(first_name, last_name)


def _full_name_key(first_name: str, last_name: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part).strip()


def _student_name_candidate_keys(student_name: str) -> list[tuple[str, str]]:
    parts = [part for part in student_name.split() if part]
    if len(parts) < 2:
        return []

    candidate_keys = []
    seen = set()
    split_points = []
    for index in (1, 2, len(parts) - 1):
        if 0 < index < len(parts) and index not in split_points:
            split_points.append(index)

    for index in split_points:
        first_name = " ".join(parts[:index])
        last_name = " ".join(parts[index:])
        if not first_name or not last_name:
            continue
        name_key = _person_name_key(first_name, last_name)
        aliased_key = STUDENT_NAME_ALIASES.get(name_key, name_key)
        if aliased_key in seen:
            continue
        seen.add(aliased_key)
        candidate_keys.append(aliased_key)

    return candidate_keys


def is_committee_only_q11(text: str) -> bool:
    normalized = norm_name(text)
    if "committee" not in normalized:
        return False
    if "not the chair" in normalized or "not chair" in normalized or "not my advisor" in normalized:
        return True
    return (
        "on my dissertation committee" in normalized
        or "on my committee" in normalized
        or "member of my dissertation committee" in normalized
    )


def is_other_unsure_q8(text: str) -> bool:
    raw = (text or "").strip().lower().replace("\u2019", "'").replace("\u02bc", "'")
    normalized = norm_name(text)
    return (
        ("other/" in raw and "not sure" in raw)
        or ("other" in normalized and "not sure" in normalized)
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Build Mokyr genealogy network node/edge CSVs"
    )
    parser.add_argument('--date', default=None,
                        help="Date suffix for output filenames (MMDDYY, defaults to latest common cleaned/Q12a date)")
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
    parser.add_argument('--manual-edges',
                        default=None,
                        help="Path to manual edges CSV (optional)")
    parser.add_argument('--backfill',
                        default=None,
                        help="Path to approved backfill CSV (optional, enriches existing nodes)")
    args = parser.parse_args()

    date = _resolve_build_date(args.date, args.cleaned, args.q12a)
    cleaned_path = PROJECT_ROOT / (args.cleaned or f"Data/Cleaned/Mokyr_Survey_Responses_{date}_Cleaned.csv")
    q12a_path    = PROJECT_ROOT / (args.q12a    or f"Data/Derived/Advisors_and_Reported_Students_{date}.csv")
    email_recovery_path = PROJECT_ROOT / args.email_recovery if args.email_recovery else None
    manual_nodes_path   = PROJECT_ROOT / args.manual_nodes   if args.manual_nodes   else None
    manual_edges_path   = PROJECT_ROOT / args.manual_edges   if args.manual_edges   else None
    backfill_path       = PROJECT_ROOT / args.backfill       if args.backfill       else None
    nodes_out      = PROJECT_ROOT / f"Data/Derived/Network_Nodes_{date}.csv"
    edges_out      = PROJECT_ROOT / f"Data/Derived/Network_Edges_{date}.csv"
    unresolved_out = PROJECT_ROOT / f"Data/Derived/Unresolved_Edges_{date}.csv"
    discrepancy_out = PROJECT_ROOT / f"Data/Derived/Network_Discrepancies_{date}.csv"

    # Load email recovery data (optional)
    email_recovery = {}  # normalized full name -> email  OR  (normalized full name, node_id) -> email
    if email_recovery_path and email_recovery_path.exists():
        print(f"Loading email recovery: {email_recovery_path}")
        with open(email_recovery_path, newline='', encoding='utf-8') as f:
            for erow in csv.DictReader(f):
                recovered = erow.get('recovered_email', '').strip()
                if not recovered:
                    continue
                name = normalize_person_text(erow.get('name', ''))
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
    name_to_rid = {}    # normalized (first_name, last_name) -> ResponseId | None (None=ambiguous)

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
        if not email and email_recovery:
            recovered_email = _lookup_email_recovery(f"{first} {last}", f"R-{rid}", email_recovery)
            if recovered_email:
                email = recovered_email
                print(f"  INFO respondent email recovery: {first} {last} ({rid}) -> {email}")
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
        if rid in RESPONDENT_METADATA_OVERRIDES:
            respondents[rid].update(RESPONDENT_METADATA_OVERRIDES[rid])
            print(f"  INFO respondent metadata override: {first} {last} ({rid})")
        if email:
            email_to_rid[normalize_email(email)] = rid
        name_key = _person_name_key(first, last)
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
    for (first_key, last_key), rid in name_to_rid.items():
        if rid is not None:
            full_key = _full_name_key(first_key, last_key)
            if full_key:
                name_lookup[full_key] = rid

    # -------------------------------------------------------------------------
    # Step B: Parse Q8 → generation
    # -------------------------------------------------------------------------
    raw_gen_by_rid = {}
    pretopo_gen_by_rid = {}
    q8_analysis_by_rid = {}
    unresolved_edges = []   # list of dicts
    for rid, r in respondents.items():
        q8_analysis = parse_q8_generation(r['q8'])
        q8_analysis_by_rid[rid] = q8_analysis
        raw_gen = q8_analysis['raw_generation']
        raw_gen_by_rid[rid] = raw_gen
        if q8_analysis['requires_manual_review']:
            print(f"  INFO Q8 manual review: {r['first']} {r['last']} ({rid}) -> mixed committee + indirect")
            pretopo_gen_by_rid[rid] = None
            unresolved_edges.append({
                'source_id': None, 'target_id': f"R-{rid}",
                'reason': 'manual_review_q8_committee_indirect',
                'raw_q11': r['q11'],
                'respondent': f"{r['first']} {r['last']}",
                'gen': raw_gen,
                'note': r['q8'],
            })
            if q8_analysis['flag']:
                print(f"  WARN non-adjacent multi-gen Q8: {r['first']} {r['last']} ({rid}): {r['q8']!r}")
            continue
        if rid in Q8_GENERATION_OVERRIDES:
            gen = Q8_GENERATION_OVERRIDES[rid]
            print(f"  INFO Q8 override: {r['first']} {r['last']} ({rid}) -> Gen {gen}")
            pretopo_gen_by_rid[rid] = gen
        else:
            pretopo_gen_by_rid[rid] = q8_analysis['generation']
        if q8_analysis['flag']:
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

    def _match_token(token, rid, r, gen):
        """Try to resolve one name token.  Returns source_id or None (logs unresolved)."""
        cn = norm_name(token)
        if not cn:
            return None

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
        q8_analysis = q8_analysis_by_rid[rid]
        gen = pretopo_gen_by_rid[rid]
        q8_other_unsure = is_other_unsure_q8(r['q8'])
        if gen is None and not q8_other_unsure:
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
            note = 'exact_full'
            if q8_other_unsure:
                note = 'q11_resolved_from_other_unsure'
            advisor_by_rid[rid] = [(f"R-{name_lookup[full_norm]}", 'high', note)]
            continue
        if is_committee_only_q11(q11):
            unresolved_edges.append({
                'source_id': None, 'target_id': f"R-{rid}",
                'reason': 'unresolved_q11_committee_only', 'raw_q11': q11,
                'respondent': f"{r['first']} {r['last']}", 'gen': gen,
                'note': '',
            })
            continue

        # Split into tokens
        tokens = tokenize_q11(q11)
        for tok in tokens:
            src = _match_token(tok, rid, r, gen)
            if src is not None:
                # Re-derive confidence by checking if the normalized token was exact.
                cn = norm_name(tok)
                if cn in name_lookup or is_mokyr_alias(cn):
                    conf = 'high'
                else:
                    conf = 'medium'
                note = f'token:{tok!r}'
                if q8_other_unsure:
                    note = f'q11_resolved_from_other_unsure:{tok!r}'
                advisor_by_rid.setdefault(rid, []).append((src, conf, note))

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
        'generation_q8_raw': 0,
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
            'generation': pretopo_gen_by_rid[rid],
            'generation_q8': pretopo_gen_by_rid[rid],
            'generation_q8_raw': raw_gen_by_rid[rid],
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
        key = _person_name_key(row['Advisor_FirstName'], row['Advisor_LastName'])
        advisor_groups[key].append(row)

    q12a_edge_triples = []  # (source_id, target_id, confidence)
    s_counter = defaultdict(int)  # source_id -> count for unique S- IDs

    for (adv_fl, adv_ll), student_rows in advisor_groups.items():
        advisor_label = " ".join(
            part for part in (
                student_rows[0].get('Advisor_FirstName', '').strip(),
                student_rows[0].get('Advisor_LastName', '').strip(),
            )
            if part
        )
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
                    'raw_q11': advisor_label,
                    'respondent': advisor_label, 'gen': None, 'note': '',
                })
                continue

        if adv_rid is None and 'mokyr' not in adv_ll:
            # Ambiguous advisor name
            unresolved_edges.append({
                'source_id': None, 'target_id': f"Q12a-{adv_fl}-{adv_ll}",
                'reason': 'ambiguous_q12a_advisor',
                'raw_q11': advisor_label,
                'respondent': advisor_label, 'gen': None, 'note': '',
            })
            continue

        source_id = 'JM-ROOT' if (adv_rid is None and 'mokyr' in adv_ll) else f"R-{adv_rid}"

        for row in student_rows:
            student_name  = row['Student_Info_Cleaned'].strip()
            student_email = row['Student_Email'].strip()
            student_emails = split_emails(student_email)
            primary_student_email = student_emails[0] if student_emails else ''

            # Apply name corrections (misspellings)
            correction_key = normalize_person_text(student_name)
            if correction_key in STUDENT_NAME_CORRECTIONS:
                corrected = STUDENT_NAME_CORRECTIONS[correction_key]
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
                student_full_norm = norm_name(student_name)
                if student_full_norm in name_lookup:
                    student_rid = name_lookup[student_full_norm]
                else:
                    for skey in _student_name_candidate_keys(student_name):
                        val = name_to_rid.get(skey, _SENTINEL)
                        if val is _SENTINEL:
                            continue
                        if val is None:
                            break
                        student_rid = val
                        break
                    # If ambiguous (val is None) or not found: create new node

            if student_rid is not None:
                target_id = f"R-{student_rid}"
                existing = nodes.get(target_id)
                if existing and not existing.get('email') and primary_student_email:
                    existing['email'] = primary_student_email
            else:
                # Check SNODE_MERGE: reuse existing S-node if rule exists
                sparts = student_name.split() if student_name else []
                s_first = sparts[0] if sparts else ''
                s_last  = ' '.join(sparts[1:]) if len(sparts) > 1 else ''
                merge_key = _person_name_key(s_first, s_last)

                merged = False
                if merge_key in SNODE_MERGE:
                    # Find existing S-node with this name
                    for nid, n in nodes.items():
                        if nid.startswith('S-') and _person_name_key(n['first_name'], n['last_name']) == merge_key:
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
                        'generation_q8_raw': None,
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

        # Build lookup for existing respondent nodes by normalized exact name.
        existing_name_nodes = {}
        for nid, n in nodes.items():
            if not n.get('is_respondent'):
                continue
            existing_name_nodes.setdefault(
                _person_name_key(n['first_name'], n['last_name']), []).append(nid)

        for mrow in manual_rows:
            mfirst = mrow['first_name'].strip()
            mlast  = mrow['last_name'].strip()
            memail = mrow.get('email', '').strip()
            madv   = mrow['advisor_source'].strip()
            mgen   = mrow['generation'].strip()
            mgen   = int(mgen) if mgen else None
            mphd_raw = mrow.get('phd_institution_raw', '').strip()
            mphd_canon = mrow.get('phd_institution_canon', '').strip()
            memp_raw = mrow.get('current_employer_raw', '').strip()
            memp_canon = mrow.get('current_employer_canon', '').strip()
            mphd_year = mrow.get('phd_year', '').strip()
            mcountry = mrow.get('country', '').strip()
            mstate = mrow.get('us_state', '').strip()

            if mphd_raw and not mphd_canon:
                mphd_canon = canon_institution(mphd_raw) or mphd_raw
            if memp_raw and not memp_canon:
                memp_canon = canon_institution(memp_raw) or memp_raw

            # Check if node already exists (curated duplicate, exact email, or exact normalized name).
            mkey = _person_name_key(mfirst, mlast)
            found_nid = None
            match_reason = None
            curated_rid = MANUAL_RESPONDENT_DEDUP.get(mkey)
            if curated_rid and f"R-{curated_rid}" in nodes:
                found_nid = f"R-{curated_rid}"
                match_reason = 'curated_match'

            if found_nid is None and memail:
                normalized_manual_email = normalize_email(memail)
                for nid, n in nodes.items():
                    if not n.get('is_respondent') or not n.get('email'):
                        continue
                    if normalize_email(n['email']) == normalized_manual_email:
                        found_nid = nid
                        match_reason = 'exact_email'
                        break
            if found_nid is None and memail:
                erid = email_to_rid.get(normalize_email(memail))
                if erid:
                    found_nid = f"R-{erid}"
                    match_reason = 'respondent_email_lookup'
            if found_nid is None:
                candidate_ids = existing_name_nodes.get(mkey, [])
                if candidate_ids:
                    found_nid = candidate_ids[0]
                    match_reason = 'exact_name'

            if found_nid:
                print(f"  SKIP manual node {mfirst} {mlast}: already exists as {found_nid} ({match_reason})")
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
                'phd_institution_raw': mphd_raw,
                'phd_institution_canon': mphd_canon,
                'current_employer_raw': memp_raw,
                'current_employer_canon': memp_canon,
                'phd_year': mphd_year,
                'country': mcountry,
                'us_state': mstate,
                'generation': mgen,
                'generation_q8': None,
                'generation_q8_raw': None,
                'has_students': False,
                'is_respondent': False,
            }
            manual_edge_triples.append((madv, m_id, 'high'))
            print(f"  Added manual node: {m_id} ({mfirst} {mlast}, Gen {mgen})")

        print(f"  Created {len(manual_edge_triples)} manual nodes\n")
    elif manual_nodes_path:
        print(f"  WARN: manual nodes file not found: {manual_nodes_path}\n")

    # -------------------------------------------------------------------------
    # Step E3: Load curated manual edges (optional)
    # -------------------------------------------------------------------------
    if manual_edges_path and manual_edges_path.exists():
        print(f"Loading manual edges: {manual_edges_path}")
        with open(manual_edges_path, newline='', encoding='utf-8') as f:
            manual_edge_rows = list(csv.DictReader(f))
        print(f"  {len(manual_edge_rows)} manual edge entries")
        existing_manual_edge_count = len(manual_edge_triples)

        for row in manual_edge_rows:
            src = row.get('source_id', '').strip()
            tgt = row.get('target_id', '').strip()
            etype = row.get('edge_type', '').strip() or 'manual'
            conf = row.get('confidence', '').strip() or 'high'
            reason = row.get('reason', '').strip()

            if not src or not tgt:
                print(f"  WARN: skipping manual edge with blank endpoint: {row}")
                continue
            if src not in nodes or tgt not in nodes:
                print(f"  WARN: manual edge {src} -> {tgt} references missing node(s), skipping")
                unresolved_edges.append({
                    'source_id': src,
                    'target_id': tgt,
                    'reason': 'unresolved_manual_edge',
                    'raw_q11': '',
                    'respondent': '',
                    'gen': None,
                    'note': reason,
                })
                continue

            manual_edge_triples.append((src, tgt, conf, etype))

        loaded_manual_edges = len(manual_edge_triples) - existing_manual_edge_count
        print(f"  Loaded {loaded_manual_edges} curated manual edges\n")
    elif manual_edges_path:
        print(f"  WARN: manual edges file not found: {manual_edges_path}\n")

    # -------------------------------------------------------------------------
    # Step E4: Apply approved backfill enrichments (optional)
    # -------------------------------------------------------------------------
    # The approved backfill CSV enriches existing nodes with web-researched
    # metadata (PhD institution, employer, country, email, etc.).  It does NOT
    # create new nodes — every node_id must already exist in the built node set.
    #
    # Behaviour per backfill_* field:
    #   blank in approved CSV  → no change (skip)
    #   nonblank in approved   → write to node (backfill empty OR overwrite)
    #
    # Explicit clear via clear_fields column:
    #   Comma-separated list of canonical node field names to set to ''.
    #   A field cannot appear in both clear_fields and as a nonblank backfill_*.
    BACKFILL_FIELD_MAP = {
        'backfill_email':                   'email',
        'backfill_phd_institution_raw':     'phd_institution_raw',
        'backfill_phd_institution_canon':   'phd_institution_canon',
        'backfill_phd_year':                'phd_year',
        'backfill_current_employer_raw':    'current_employer_raw',
        'backfill_current_employer_canon':  'current_employer_canon',
        'backfill_country':                 'country',
        'backfill_us_state':                'us_state',
    }

    CLEARABLE_FIELDS = set(BACKFILL_FIELD_MAP.values())

    if backfill_path and backfill_path.exists():
        print(f"Loading approved backfill: {backfill_path}")
        with open(backfill_path, newline='', encoding='utf-8') as f:
            backfill_rows = list(csv.DictReader(f))
        print(f"  {len(backfill_rows)} backfill entries")

        # --- Validation ---
        bf_nids = [r['node_id'].strip() for r in backfill_rows]
        bf_nid_counts = Counter(bf_nids)
        bf_dupes = {nid for nid, cnt in bf_nid_counts.items() if cnt > 1}
        if bf_dupes:
            sys.exit(f"ERROR: Duplicate node_id(s) in approved backfill: {sorted(bf_dupes)}")

        bf_missing = [nid for nid in bf_nids if nid not in nodes]
        if bf_missing:
            sys.exit(
                f"ERROR: Approved backfill references {len(bf_missing)} node_id(s) "
                f"not in built node set: {bf_missing[:5]}{'...' if len(bf_missing) > 5 else ''}"
            )

        bf_updated = 0
        bf_fields_updated = Counter()
        bf_fields_cleared = Counter()
        for brow in backfill_rows:
            nid = brow['node_id'].strip()
            node = nodes[nid]

            # Parse clear_fields
            clear_raw = brow.get('clear_fields', '').strip()
            clear_set = {f.strip() for f in clear_raw.split(',') if f.strip()} if clear_raw else set()

            # Validate: reject unknown field names in clear_fields
            unknown_clear = clear_set - CLEARABLE_FIELDS
            if unknown_clear:
                sys.exit(
                    f"ERROR: Approved backfill for {nid} has unknown clear_fields: "
                    f"{sorted(unknown_clear)}"
                )

            # Validate: reject rows that both set and clear the same field
            bf_set_fields = set()
            for bf_col, node_col in BACKFILL_FIELD_MAP.items():
                if brow.get(bf_col, '').strip():
                    bf_set_fields.add(node_col)
            set_and_clear = bf_set_fields & clear_set
            if set_and_clear:
                sys.exit(
                    f"ERROR: Approved backfill for {nid} both sets and clears: "
                    f"{sorted(set_and_clear)}"
                )

            # Validate: email requires at least one source URL
            bf_email = brow.get('backfill_email', '').strip()
            bf_src1 = brow.get('source_1_url', '').strip()
            bf_src2 = brow.get('source_2_url', '').strip()
            if bf_email and not bf_src1 and not bf_src2:
                sys.exit(
                    f"ERROR: Approved backfill for {nid} has email without source URL"
                )

            # Validate: us_state requires country = United States
            bf_state = brow.get('backfill_us_state', '').strip()
            bf_country = brow.get('backfill_country', '').strip()
            if bf_state and bf_country and bf_country != 'United States':
                sys.exit(
                    f"ERROR: Approved backfill for {nid} has us_state={bf_state!r} "
                    f"but country={bf_country!r} (expected 'United States')"
                )

            # Apply enrichments (nonblank backfill_* → set/overwrite)
            updated_fields = []
            for bf_col, node_col in BACKFILL_FIELD_MAP.items():
                val = brow.get(bf_col, '').strip()
                if not val:
                    continue
                old_val = str(node.get(node_col, '') or '').strip()
                if val != old_val:
                    action = 'backfill' if not old_val else 'overwrite'
                    node[node_col] = val
                    updated_fields.append(f"{node_col}({action})")
                    bf_fields_updated[node_col] += 1

            # Apply clears (clear_fields → set to '')
            for field in sorted(clear_set):
                old_val = str(node.get(field, '') or '').strip()
                if old_val:
                    node[field] = ''
                    updated_fields.append(f"{field}(clear)")
                    bf_fields_cleared[field] += 1

            if updated_fields:
                bf_updated += 1
                print(f"  ENRICH {nid} ({node['first_name']} {node['last_name']}): "
                      f"{', '.join(updated_fields)}")

        total_updates = sum(bf_fields_updated.values()) + sum(bf_fields_cleared.values())
        print(f"  Enriched {bf_updated} nodes ({total_updates} field changes)")
        if bf_fields_updated:
            print(f"  Set/overwrite:")
            for field, cnt in sorted(bf_fields_updated.items()):
                print(f"    {field}: {cnt}")
        if bf_fields_cleared:
            print(f"  Cleared:")
            for field, cnt in sorted(bf_fields_cleared.items()):
                print(f"    {field}: {cnt}")
        print()
    elif backfill_path:
        print(f"  WARN: approved backfill file not found: {backfill_path}\n")

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
    for edge in manual_edge_triples:
        if len(edge) == 3:
            src, tgt, conf = edge
            etype = 'manual'
        else:
            src, tgt, conf, etype = edge
        raw_edges.append((src, tgt, etype, conf))

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
    # Step G: Build discrepancy report
    # -------------------------------------------------------------------------
    discrepancy_rows = []
    for rid, r in respondents.items():
        node_id = f"R-{rid}"
        node = nodes[node_id]
        q8_analysis = q8_analysis_by_rid[rid]
        final_generation = node['generation']
        override_generation = Q8_GENERATION_OVERRIDES.get(rid)
        is_direct = q8_analysis['has_direct'] or override_generation == 1

        if q8_analysis['requires_manual_review']:
            discrepancy_rows.append({
                'response_id': rid,
                'node_id': node_id,
                'category': 'manual_review_q8_committee_indirect',
                'first_name': r['first'],
                'last_name': r['last'],
                'raw_q8': r['q8'],
                'raw_q11': r['q11'],
                'raw_q12': r['q12'],
                'generation_q8': node.get('generation_q8', ''),
                'generation_q8_raw': node.get('generation_q8_raw', ''),
                'final_generation': final_generation,
                'note': 'Review mixed committee + indirect raw relationship before curating a direct link.',
            })

        if is_other_unsure_q8(r['q8']) and final_generation in (None, ''):
            discrepancy_rows.append({
                'response_id': rid,
                'node_id': node_id,
                'category': 'other_unsure_unassigned',
                'first_name': r['first'],
                'last_name': r['last'],
                'raw_q8': r['q8'],
                'raw_q11': r['q11'],
                'raw_q12': r['q12'],
                'generation_q8': node.get('generation_q8', ''),
                'generation_q8_raw': node.get('generation_q8_raw', ''),
                'final_generation': final_generation,
                'note': 'Q8 was Other/unsure and topology could not assign a final generation from available edges.',
            })

        if is_direct and final_generation != 1:
            discrepancy_rows.append({
                'response_id': rid,
                'node_id': node_id,
                'category': 'direct_q8_missing_gen1',
                'first_name': r['first'],
                'last_name': r['last'],
                'raw_q8': r['q8'],
                'raw_q11': r['q11'],
                'raw_q12': r['q12'],
                'generation_q8': node.get('generation_q8', ''),
                'generation_q8_raw': node.get('generation_q8_raw', ''),
                'final_generation': final_generation,
                'note': 'Respondent reported a direct Mokyr relationship but did not finish in generation 1.',
            })
        elif not is_direct and final_generation == 1:
            discrepancy_rows.append({
                'response_id': rid,
                'node_id': node_id,
                'category': 'gen1_without_direct_q8',
                'first_name': r['first'],
                'last_name': r['last'],
                'raw_q8': r['q8'],
                'raw_q11': r['q11'],
                'raw_q12': r['q12'],
                'generation_q8': node.get('generation_q8', ''),
                'generation_q8_raw': node.get('generation_q8_raw', ''),
                'final_generation': final_generation,
                'note': 'Respondent remains generation 1 without direct raw Q8 evidence.',
            })
        elif (
            not q8_analysis['requires_manual_review']
            and q8_analysis['has_committee']
            and not q8_analysis['has_direct']
            and not q8_analysis['has_indirect']
            and final_generation in (None, '')
        ):
            discrepancy_rows.append({
                'response_id': rid,
                'node_id': node_id,
                'category': 'committee_only_unassigned',
                'first_name': r['first'],
                'last_name': r['last'],
                'raw_q8': r['q8'],
                'raw_q11': r['q11'],
                'raw_q12': r['q12'],
                'generation_q8': node.get('generation_q8', ''),
                'generation_q8_raw': node.get('generation_q8_raw', ''),
                'final_generation': final_generation,
                'note': 'Committee-only raw relationship no longer implies a Joel edge.',
            })

    # -------------------------------------------------------------------------
    # Step H: Write outputs + report
    # -------------------------------------------------------------------------
    NODE_COLS = [
        'node_id', 'first_name', 'last_name', 'email',
        'phd_institution_raw', 'phd_institution_canon',
        'current_employer_raw', 'current_employer_canon',
        'phd_year', 'country', 'us_state',
        'generation', 'generation_q8', 'generation_q8_raw', 'has_students', 'is_respondent',
    ]
    EDGE_COLS = ['source_id', 'target_id', 'edge_type', 'confidence']
    UNRESOLVED_COLS = ['source_id', 'target_id', 'reason', 'raw_q11', 'respondent', 'gen', 'note']
    DISCREPANCY_COLS = [
        'response_id', 'node_id', 'category', 'first_name', 'last_name',
        'raw_q8', 'raw_q11', 'raw_q12',
        'generation_q8', 'generation_q8_raw', 'final_generation', 'note',
    ]

    node_rows = sorted(nodes.values(), key=lambda row: row['node_id'])
    clean_edges.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    unresolved_edges.sort(
        key=lambda row: (
            row.get('target_id', ''),
            row.get('source_id', ''),
            row.get('reason', ''),
            row.get('raw_q11', ''),
        )
    )
    discrepancy_rows.sort(
        key=lambda row: (
            row.get('response_id', ''),
            row.get('category', ''),
            row.get('node_id', ''),
        )
    )

    with open(nodes_out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=NODE_COLS)
        w.writeheader()
        for n in node_rows:
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

    with open(discrepancy_out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=DISCREPANCY_COLS)
        w.writeheader()
        for row in discrepancy_rows:
            w.writerow({k: row.get(k, '') for k in DISCREPANCY_COLS})

    # Summary
    n_respondent = sum(1 for n in nodes.values() if n['is_respondent'])
    n_q12a_only  = sum(1 for n in nodes.values() if not n['is_respondent'] and n['node_id'] != 'JM-ROOT')
    conf_counts  = Counter(e[3] for e in clean_edges)

    print(f"\n=== Summary ===")
    print(f"  Nodes : {len(nodes)} total  ({n_respondent} respondents, {n_q12a_only} Q12a-only, 1 root)")
    print(f"  Edges : {len(clean_edges)} total  ({dict(conf_counts)})")
    print(f"  Unresolved : {len(unresolved_edges)}")
    print(f"  Discrepancies : {len(discrepancy_rows)}")

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
    print(f"  {discrepancy_out}")


if __name__ == '__main__':
    main()
