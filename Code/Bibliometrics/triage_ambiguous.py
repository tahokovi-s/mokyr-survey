#!/usr/bin/env python3
"""
Triage ambiguous OpenAlex matches for the Mokyr genealogy project.

Reads:
  - Data/Derived/OpenAlex_Scholar_Matches_040126.csv
  - Data/Derived/OpenAlex_Match_Review_040126.csv

Writes:
  - Data/Derived/OpenAlex_Ambiguous_Decisions_040126.csv
"""
import csv
import re
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# =====================================================================
# Read data
# =====================================================================
ambiguous = {}
with open(PROJECT_ROOT / "Data/Derived/OpenAlex_Scholar_Matches_040126.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row["match_status"] == "ambiguous_manual_review":
            ambiguous[row["node_id"]] = row

candidates = {}
with open(PROJECT_ROOT / "Data/Derived/OpenAlex_Match_Review_040126.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        nid = row["node_id"]
        if nid in ambiguous:
            if nid not in candidates:
                candidates[nid] = []
            candidates[nid].append(row)

print(f"Ambiguous scholars: {len(ambiguous)}")
print(f"Scholars with candidates in review file: {len(candidates)}")

# =====================================================================
# Helper functions
# =====================================================================

def safe_float(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return 0.0

def safe_int(x):
    try:
        return int(x)
    except (ValueError, TypeError):
        return 0

def normalize_name(name):
    """Lowercase, strip diacritics, remove punctuation except spaces for comparison."""
    # Strip diacritics via NFKD decomposition
    nfkd = unicodedata.normalize('NFKD', name)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Replace hyphens and dots with spaces, then collapse whitespace
    result = stripped.lower()
    result = re.sub(r'[-.]', ' ', result)
    result = re.sub(r'[^a-z\s]', '', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result

def names_match(scholar_name, candidate_name):
    """Check if candidate display name is a plausible match for scholar name."""
    sn = normalize_name(scholar_name)
    cn = normalize_name(candidate_name)
    if sn == cn:
        return True
    s_parts = sn.split()
    c_parts = cn.split()

    # Handle parenthetical maiden/alternative names: "Martha (Weidner) Williams"
    base_scholar = re.sub(r'\(.*?\)', '', scholar_name).strip()
    if normalize_name(base_scholar) == cn:
        return True

    # Check if last name tokens match (handle compound last names)
    if not s_parts or not c_parts:
        return False

    # If candidate has more name parts, check if scholar name is a subset
    # e.g., "Jonas Mueller Gastell" matches "Jonas Mueller-Gastell"
    if len(s_parts) >= 2 and len(c_parts) >= 2:
        # Last name match (or last 2 tokens match for compound names)
        if s_parts[-1] == c_parts[-1]:
            # First name match
            if s_parts[0] == c_parts[0]:
                return True
            # First initial match
            if s_parts[0][0] == c_parts[0][0]:
                return True
        # Compound last name: scholar "Rojas Ampuero" vs candidate "Rojas-Ampuero"
        # After normalization both become "rojas ampuero"
        if s_parts[-2:] == c_parts[-2:] and s_parts[0] == c_parts[0]:
            return True

    # Handle "E Burke Evans" vs "Burke Evans" (initial prepended)
    if len(c_parts) == len(s_parts) + 1:
        # Candidate has an extra initial at the start
        if len(c_parts[0]) <= 2 and s_parts == c_parts[1:]:
            return True
        # Or extra part at end
        if s_parts[0] == c_parts[0] and s_parts[-1] == c_parts[-1]:
            return True
    if len(s_parts) == len(c_parts) + 1:
        if len(s_parts[0]) <= 2 and c_parts == s_parts[1:]:
            return True
        if s_parts[0] == c_parts[0] and s_parts[-1] == c_parts[-1]:
            return True

    # Check if candidate name contains all scholar name parts (superset)
    if all(sp in c_parts for sp in s_parts):
        return True
    # Check if scholar name contains all candidate name parts
    if all(cp in s_parts for cp in c_parts):
        return True

    # Handle "Manjunath A.N" vs "A.N. Manjunath" (reversed order)
    if set(s_parts) == set(c_parts):
        return True

    return False

def candidate_is_clearly_different_field(cand):
    """Check if a candidate is clearly from a wrong field."""
    insts = cand.get("candidate_institutions", "").lower()
    med_markers = ["hospital", "medical center", "cancer", "health", "clinical", "medicine",
                   "surgery", "pathology", "pharmaceutical", "biotech", "biology"]
    med_count = sum(1 for m in med_markers if m in insts)
    return med_count >= 3

def has_strong_institution_confirmation(cand, scholar):
    """Check if a candidate has strong institution confirmation."""
    inst_matches = cand.get("institution_matches", "")
    cand_insts = cand.get("candidate_institutions", "").lower()
    cand_current = cand.get("candidate_current_institution", "").lower()
    scholar_phd = scholar.get("phd_institution", "").lower()
    scholar_emp = scholar.get("current_employer", "").lower()

    if scholar_emp and scholar_emp in cand_current:
        return True
    if scholar_phd and scholar_phd in cand_insts:
        return True
    if inst_matches:
        for m in inst_matches.split(';'):
            m = m.strip()
            if ' \u2194 ' in m:
                left, right = m.split(' \u2194 ', 1)
                left_l, right_l = left.strip().lower(), right.strip().lower()
                if left_l == right_l:
                    return True
                if scholar_phd and (scholar_phd in left_l or scholar_phd in right_l):
                    return True
                if scholar_emp and (scholar_emp in left_l or scholar_emp in right_l):
                    return True
    return False

# =====================================================================
# Priority scholar manual overrides
# =====================================================================
manual_decisions = {}

manual_decisions["R-R_3rdAHSYGOxuYdn9"] = (
    "approve_match",
    "https://openalex.org/A5048483497",
    "Top candidate Joyce Burnette (82 works, h=9) matches Wabash College employer, earliest pub 1995 aligns with 1994 PhD. "
    "#2 has only 4 works and earliest_pub=1903 (disambiguation artifact). Clear match for the economic historian."
)

manual_decisions["R-R_3J1KEWYwi7MlWAr"] = (
    "approve_match",
    "https://openalex.org/A5045080620",
    "Top candidate Noel D. Johnson (100 works, h=23) matches both Washington University in St. Louis (PhD) and "
    "George Mason University (employer). #2 has only 2 works. Clear match for the institutional economist."
)

manual_decisions["R-R_6sun43Nt3zxrBjz"] = (
    "approve_match",
    "https://openalex.org/A5009802601",
    "Top candidate Ariell Zimran (36 works, h=9) matches Vanderbilt University employer, Stanford in institutions, "
    "NBER affiliated. #2/#3 are fragmented records (3 and 1 works) of the same person. Clear match."
)

manual_decisions["R-R_1dZmHM5Ijog1O2P"] = (
    "approve_match",
    "https://openalex.org/A5008303831",
    "Top candidate Rick Szostak (250 works, h=21) matches University of Alberta employer, "
    "earliest pub 1984 aligns with 1985 PhD. #2 (28 works, Fritz Haber Institute) is a chemist. Clear match."
)

manual_decisions["R-R_5pRTCtHI6BuJWFy"] = (
    "needs_more_review",
    "",
    "TIED at 0.95 with 25 candidates. #1 David Y. Yang (123 works, h=29) matches Stanford+Harvard but current "
    "institution is Portland State (suspicious for the Harvard political economist). #2 (27 works, h=14) at UC Berkeley. "
    "The real David Y. Yang profile may be contaminated with other David Yangs. Manual verification required."
)

manual_decisions["R-R_2kpoi5m38XN9OVj"] = (
    "approve_match",
    "https://openalex.org/A5079631802",
    "Top candidate Michael Andrews (58 works, h=14) matches UMBC (current employer) and has NBER affiliation. "
    "#2 (39 works, h=9) is at Fermilab (particle physics) -- wrong field. Approving #1 as the innovation economist."
)

manual_decisions["R-R_4h5t2xzDbtqYGpC"] = (
    "approve_match",
    "https://openalex.org/A5064840657",
    "Top candidate K. Kivanc Karaman (13 works, h=7, 627 citations) at Bogazici University matches employer. "
    "Diacritics in Bogazici caused institution scoring to miss match. #2 (53 works) is a different Karaman "
    "in medical/ecology fields. Score gap 0.20. Clear match for the economic historian."
)

# --- Additional manual overrides from detailed review ---

# Jason Long: #1 (25 works, h=9) at Wheaton College-IL, matches both Northwestern and Wheaton College.
# #2 (88 works, h=16) at UNC Chapel Hill is medical. Gap is 0.10. Clear econ historian match.
manual_decisions["R-R_38lGgfW7OORiymR"] = (
    "approve_match",
    "https://openalex.org/A5002587032",
    "Top candidate Jason Long (25 works, h=9) matches Wheaton College employer and Northwestern PhD. "
    "#2 (88 works) at UNC is medical/epidemiology. NBER and Harvard affiliations confirm economic historian."
)

# Jonas Mueller-Gastell: #1 (5 works, h=2) at Stanford Medicine, Stanford match, NBER. #2 (2 works) also Stanford.
# Both are fragments of the same person. #1 has more works and NBER. Approve #1.
manual_decisions["R-R_7hpMFfLRqduWfAJ"] = (
    "approve_match",
    "https://openalex.org/A5060662571",
    "Top candidate Jonas Mueller Gastell (5 works, h=2) at Stanford with NBER affiliation. "
    "#2 (2 works) is a fragment of the same person also at Stanford. Approve dominant profile."
)

# Moramay LOPEZ-ALONSO: #1 (35 works, h=9) matches Rice University employer. Clear match.
manual_decisions["R-R_6j7NkZayMiXGhwf"] = (
    "approve_match",
    "https://openalex.org/A5027696994",
    "Top candidate Moramay Lopez-Alonso (35 works, h=9) matches Rice University employer. "
    "Diacritics in Lopez vs Lopez caused name mismatch. #2 (4 works) is a fragment. Clear economic historian."
)

# Fernanda Rojas Ampuero: #1 (2 works) at UW-Madison, matches employer. #2/#3 are fragments at same institution.
manual_decisions["R-R_375Risx7k3TSn1n"] = (
    "approve_match",
    "https://openalex.org/A5049497279",
    "Top candidate Fernanda Rojas-Ampuero (2 works) at UW-Madison matches employer. "
    "Hyphen vs space caused name mismatch. #2/#3 are fragments at same institution. Clear match."
)

# Scott Baker: #1 (1512 works, h=40) at Northwestern, Stanford match. But 1512 works is suspiciously high --
# this may be a mega-profile. #2 has 75838 works (clearly aggregated). The real Scott Baker (policy uncertainty)
# is Northwestern/Stanford economist. But this profile may be polluted. Needs review.
manual_decisions["R-R_1thdRkZWMU7Gk4F"] = (
    "needs_more_review",
    "",
    "Top candidate Scott Baker (1512 works, h=40) at Northwestern matches Stanford and UW-Madison, but 1512 works "
    "is suspiciously high for an economist (PhD 2014). Profile may be contaminated with other Scott Bakers. "
    "#2 has 75838 works (clearly aggregated). Manual verification required."
)

# Nicola Bianchi: #1 (540 works, h=66) at U Padua, Northwestern match. But 540 works is too high for PhD 2015.
# #2 (64 works, h=12) at NBER, also Northwestern match, plus Kellogg, Bank of Italy, Einaudi.
# #2 is clearly the Northwestern economist. Override to approve #2.
manual_decisions["R-R_6Cmxwigf3ojJFcU"] = (
    "approve_match",
    "https://openalex.org/A5084375497",
    "Approving #2 Nicola Bianchi (64 works, h=12) at NBER/Northwestern/Kellogg/Einaudi. "
    "#1 (540 works, h=66) at U Padua is contaminated with non-economist publications. "
    "#2's affiliations (Kellogg, Bank of Italy, Hoover Institution) match the Northwestern labor economist."
)

# Michael Bailey: #1 (144 works, h=42) has Stanford match but current at Atlanta Technical College (wrong).
# #3 (67 works, h=22) at Meta(Israel), has NBER, Princeton, UNC -- this is the FB/Meta economist.
# But #1 includes a wide range of institutions. Needs review to pick correct profile.
manual_decisions["R-R_5bTQAFcivjTDjHI"] = (
    "needs_more_review",
    "",
    "Top candidate Michael Bailey (144 works, h=42) matches Stanford but current at Atlanta Technical College (wrong). "
    "#3 (67 works, h=22) at Meta/NBER/Princeton matches the FB economist better. "
    "Multiple contaminated profiles. Manual verification needed to pick correct OpenAlex ID."
)

# Michelle Poland: #1 (2 works, h=1) at U Leicester, weak match. #2 (17 works, h=7) at U Otago matches PhD inst.
# #2 is clearly the right person. Override to approve #2.
manual_decisions["R-R_9SHOLlPkXmthmWw"] = (
    "approve_match",
    "https://openalex.org/A5110619252",
    "Approving #2 Michelle Poland (17 works, h=7) at University of Otago which matches PhD institution. "
    "#1 (2 works) at U Leicester has no Otago connection. #2 also has Victoria U Wellington and NZ government affiliations."
)

# Lukas Rosenberger: #1 (4 works) at LMU Munich matches employer but no inst score (LMU vs Ludwig-Maximilians).
# This is clearly the correct person. The institution name is just different in OpenAlex.
manual_decisions["R-R_2gNg19tZDogUQj3"] = (
    "approve_match",
    "https://openalex.org/A5083009283",
    "Top candidate Lukas Rosenberger (4 works) at Ludwig-Maximilians-Universitaet Muenchen matches LMU Munich employer. "
    "Inst scoring missed the match due to name variant. #2 (1 work) at TU Darmstadt is a different person."
)

# Tom Zohar: #1 (7 works, h=2) at CEMFI matches employer. Stanford Medicine also in institutions.
# The institution scoring missed CEMFI because employer is listed as "CEMFI" vs "Centro de Estudios Monetarios y Financieros".
manual_decisions["R-R_2gsW5LWcqFuSjQt"] = (
    "approve_match",
    "https://openalex.org/A5036126997",
    "Top candidate Tom Zohar (7 works, h=2) at Centro de Estudios Monetarios y Financieros (CEMFI) matches employer. "
    "Also has Stanford Medicine and Technion affiliations. Inst scoring missed due to CEMFI abbreviation vs full name."
)

# Jonathan Hartley: #1 (7 works, h=1) at Stanford, perfect score. #2 (5 works, h=1) also at Stanford/NY Fed.
# Both are fragmented profiles of the same person. #1 has more works. Approve.
manual_decisions["R-R_11MnENdbOxOicDt"] = (
    "approve_match",
    "https://openalex.org/A5111736456",
    "Top candidate Jonathan Hartley (7 works, h=1) at Stanford, perfect score 1.0. "
    "#2 (5 works) at NY Fed/Stanford is a fragment of the same person. Approving dominant profile."
)

# Mihai Codreanu: #1 (5 works, h=1) at Stanford, perfect score. #2 (2 works) also Stanford.
# #1 name is "Mihai Alexandru Codreanu" -- has middle name but still a match. Fragments.
manual_decisions["R-R_538rSXwymTmoHyo"] = (
    "approve_match",
    "https://openalex.org/A5019274626",
    "Top candidate Mihai Alexandru Codreanu (5 works, h=1) at Stanford/IFS, perfect score 1.0. "
    "#2 (2 works) also at Stanford is a fragment. Approving dominant profile."
)

# Giuliana Freschi: #1 (2 works) at Scuola Superiore Sant'Anna, perfect score. #2 (1 work) also at same inst.
# Fragments. Approve #1.
manual_decisions["R-R_8wEpbcdJmUQ12nU"] = (
    "approve_match",
    "https://openalex.org/A5062858037",
    "Top candidate Giuliana Freschi (2 works) at Scuola Superiore Sant'Anna, perfect score 1.0. "
    "#2 (1 work) at same institution is a fragment. Approving dominant profile."
)

# Beau Bressler: #1 (3 works, h=2) at UC Davis, score 0.95. #2 (1 work) also UC Davis.
# Both matched. #1 has more works. Fragments of same person.
manual_decisions["S-R_7vrtdVnraeOr681-0006"] = (
    "approve_match",
    "https://openalex.org/A5052613498",
    "Top candidate Beau Bressler (3 works, h=2) at UC Davis, score 0.95 with institution match. "
    "#2 (1 work) also at UC Davis is a fragment. Approving dominant profile."
)

# Jonah Rexer: #1 (9 works, h=4) at World Bank, matches UPenn PhD and World Bank employer. NBER, Princeton.
# #2 (7 works, h=2) is a near-duplicate also matching UPenn. #1 is the main profile.
manual_decisions["R-R_3Ig9MrQcm6rlFwE"] = (
    "approve_match",
    "https://openalex.org/A5039218505",
    "Top candidate Jonah Rexer (9 works, h=4) at World Bank matches both UPenn (PhD) and World Bank (employer). "
    "NBER and Princeton affiliations. #2 (7 works) is a near-duplicate fragment. Clear match."
)

# Felipe Flores-Golfin: #1 (1 work, h=1) at PPIC, UPenn match. #2 (1 work) also UPenn.
# Tied with 1 work each. Both are fragments. #1 has PPIC (plausible for econ PhD from UPenn).
manual_decisions["S-R_3uvEz6kA5E8QDAt-0005"] = (
    "approve_match",
    "https://openalex.org/A5038281770",
    "Top candidate Felipe Flores-Golfin (1 work, h=1) at PPIC with UPenn match. "
    "#2 (1 work) also at UPenn is a fragment. Both plausible; approving #1 as main profile."
)

# Gabrielle Vasey: #1 (2 works, h=2) at Concordia, matches employer. #2 (1 work) also Concordia.
# Fragment. Approve #1.
manual_decisions["S-R_3uvEz6kA5E8QDAt-0006"] = (
    "approve_match",
    "https://openalex.org/A5019283023",
    "Top candidate Gabrielle Vasey (2 works, h=2) at Concordia University matches employer. "
    "#2 (1 work) at same institution is a fragment. Approving dominant profile."
)

# Yiyu Xing: #1 is "Yang Xing" (wrong first name!). #3 is "Yiyu Xing" (1 work) at Auburn, matches PhD inst.
# Should approve #3 not #1.
manual_decisions["R-R_5rSgL56O7Vx738t"] = (
    "needs_more_review",
    "",
    "Top candidate is 'Yang Xing' (wrong first name). #3 'Yiyu Xing' (1 work) at Auburn matches PhD institution "
    "but has only 1 work. The correct person likely has a small OpenAlex footprint. "
    "Candidate #3 (A5126689490) is plausible but manual verification recommended."
)

# Yiling Zhao: #1 (2 works) at Peking University, matches employer. #2 (1 work) also Peking U.
# Tied at 0.95. Fragments. Approve #1 as dominant.
manual_decisions["R-R_8vAMxshvqdjTXbz"] = (
    "approve_match",
    "https://openalex.org/A5126914732",
    "Top candidate Yiling Zhao (2 works) at Peking University matches employer. "
    "#2 (1 work) also at Peking U is a fragment. Approving dominant profile."
)

# Lingyu Kong: #1 (13 works, h=3) at U South Australia, matches U Adelaide (nearby).
# #2 (21 works, h=7) at Georgia Tech -- different location.
# #1 has U Adelaide in institutions list. Close call but #1 is likely correct.
manual_decisions["R-R_4EjmiZhCDxnx0Hs"] = (
    "approve_match",
    "https://openalex.org/A5066985344",
    "Top candidate Lingyu Kong (13 works, h=3) at U South Australia with U Adelaide in institutions matches PhD. "
    "#2 (21 works, h=7) at Georgia Tech is a different field (engineering). Zhongnan U of Economics confirms economics."
)

# Prateek Raj: #1 (14 works, h=2) at IIM Bangalore. Scholar is at UCL, PhD from UCL.
# #1 has IIM Bangalore + U Chicago + UCL in institutions. UCL match! Approve.
manual_decisions["R-R_2pDk1R2mGaXSFnr"] = (
    "approve_match",
    "https://openalex.org/A5065987614",
    "Top candidate Prateek Raj (14 works, h=2) at IIM Bangalore with University College London and "
    "University of Chicago in institutions. UCL matches both PhD and employer. Clear economics profile."
)

# Isabelle Sin: #1 (78 works, h=16) at Te Papa/Motu/CSIRO/NBER/Victoria U Wellington.
# Stanford PhD, employer is Ministry for Regulation NZ.
# Victoria U Wellington and Motu (NZ think tank) are consistent. NBER affiliation confirms economist. Approve.
manual_decisions["R-R_4pT1HyRG1hLQfM4"] = (
    "approve_match",
    "https://openalex.org/A5058102117",
    "Top candidate Isabelle Sin (78 works, h=16) has Victoria U Wellington, Motu Economic and Public Policy Research, "
    "NBER, and CSIRO affiliations -- consistent with NZ-based economist. #2 (14 works) also has Motu. "
    "Approving #1 as the dominant profile."
)

# Marshall Mo: #1 (3 works, h=1) at Stanford, score 0.95. #2 (1 work) also Stanford. Fragments. Approve #1.
manual_decisions["R-R_1XMskugHKPRopcl"] = (
    "approve_match",
    "https://openalex.org/A5119028316",
    "Top candidate Marshall Mo (3 works, h=1) at Stanford, score 0.95 with institution match. "
    "#2 (1 work) at Stanford is a fragment. Approving dominant profile."
)

# Tamar Matiashvili: #1 (2 works, h=1) at Stanford, perfect score. #2 (1 work) also Stanford. Fragments.
manual_decisions["R-R_3oFtutggiZQ5yai"] = (
    "approve_match",
    "https://openalex.org/A5117267879",
    "Top candidate Tamar Matiashvili (2 works, h=1) at Stanford, perfect score 1.0. "
    "#2 (1 work) also at Stanford is a fragment. Approving dominant profile."
)

# Alejandro Martinez Marquina: #1 (3 works) at USC, score 0.95, inst match. #2 (1 work) also USC. Fragments.
manual_decisions["R-R_768qH0fn45TmphK"] = (
    "approve_match",
    "https://openalex.org/A5109103668",
    "Top candidate Alejandro Martinez Marquina (3 works) at USC matches employer, score 0.95. "
    "#2 (1 work) also at USC is a fragment. Approving dominant profile."
)

# Megumi Murakami: #1 (1 work) at U Tokyo matches employer. But #2 (4 works, h=1) at Northwestern matches PhD.
# The Northwestern economist's main profile might be #2. Needs review.
manual_decisions["R-R_9E64zhBSbZHTSAI"] = (
    "needs_more_review",
    "",
    "#1 (1 work) at U Tokyo matches employer but only 1 work. #2 (4 works, h=1) at Northwestern matches PhD institution. "
    "Both are plausible. The correct profile may be #2 (Northwestern) rather than #1. Manual verification needed."
)

# Yifan Mao: #1 (1 work) at Northwestern Polytechnical University (not Northwestern University!). False match.
# Scholar is at Northwestern University, PhD 2029. #2 (77 works, h=13) is medical. All candidates are wrong field or wrong inst.
manual_decisions["R-R_56EPferr6LDSK41"] = (
    "needs_more_review",
    "",
    "Top candidate at Northwestern Polytechnical University (China), NOT Northwestern University. "
    "False institution match. Scholar is an early-career PhD student (2029). No plausible candidate found."
)

# Zhihao Xu: #1 (81 works, h=11) has Tsinghua match but at Zhejiang International Studies U. Scholar at Tsinghua School of Social Sciences.
# #2 (77 works, h=21) at Notre Dame has no relevant match. #1 has the Tsinghua connection. But 81 works
# seems high and field may be wrong. Needs review.
manual_decisions["R-R_9i4H75l7IKGKK6n"] = (
    "needs_more_review",
    "",
    "#1 (81 works, h=11) has Tsinghua in institutions but 81 works may indicate wrong field. "
    "Scholar at Tsinghua School of Social Sciences, PhD from UCLA in 2021. Manual verification needed."
)

# Mengru Wang: #1 (5 works, h=2) at National U of Defense Technology. Scholar at NUS.
# The institution match is false (NUS vs NUDT). 25 candidates. Needs review.
manual_decisions["R-R_4qvJlnzRuwNMop0"] = (
    "needs_more_review",
    "",
    "Top candidate at National U of Defense Technology, not National U of Singapore. "
    "False institution match (NUS vs NUDT). 25 candidates with common Chinese name. Manual disambiguation required."
)

# =====================================================================
# Automated decision logic
# =====================================================================
decisions = []

for nid in sorted(ambiguous.keys()):
    scholar = ambiguous[nid]
    cands = candidates.get(nid, [])
    full_name = scholar["full_name"]

    if nid in manual_decisions:
        dec, proposed_id, reason = manual_decisions[nid]
        decisions.append({
            "node_id": nid,
            "full_name": full_name,
            "current_openalex_id": "",
            "proposed_openalex_id": proposed_id,
            "decision": dec,
            "reason": reason,
            "reviewer": "auto_audit_agent_2"
        })
        continue

    if not cands:
        decisions.append({
            "node_id": nid,
            "full_name": full_name,
            "current_openalex_id": "",
            "proposed_openalex_id": "",
            "decision": "needs_more_review",
            "reason": "No candidates found in review file.",
            "reviewer": "auto_audit_agent_2"
        })
        continue

    top = cands[0]
    top_score = safe_float(top["candidate_score"])
    top_name = top["candidate_display_name"]
    top_works = safe_int(top["candidate_works_count"])
    top_cited = safe_int(top["candidate_cited_by_count"])
    top_h = safe_int(top["candidate_h_index"])
    top_inst_score = safe_float(top["institution_score"])
    top_timing = safe_float(top["timing_score"])
    top_id = top["candidate_openalex_id"]
    top_current_inst = top.get("candidate_current_institution", "")
    top_insts = top.get("candidate_institutions", "")
    top_inst_matches = top.get("institution_matches", "")
    top_timing_note = top.get("timing_note", "")

    second_score = 0.0
    second_name = ""
    second_works = 0
    second_id = ""
    second_insts = ""
    second_inst_matches = ""
    if len(cands) > 1:
        second = cands[1]
        second_score = safe_float(second["candidate_score"])
        second_name = second["candidate_display_name"]
        second_works = safe_int(second["candidate_works_count"])
        second_id = second["candidate_openalex_id"]
        second_insts = second.get("candidate_institutions", "")
        second_inst_matches = second.get("institution_matches", "")

    scholar_phd = scholar.get("phd_institution", "")
    scholar_emp = scholar.get("current_employer", "")
    scholar_year = scholar.get("phd_year", "")
    n_cands = safe_int(scholar.get("candidate_count", "0"))
    score_gap = top_score - second_score

    name_ok = names_match(full_name, top_name)
    has_inst_confirm = has_strong_institution_confirmation(top, scholar)

    decision = None
    reason = ""
    proposed_id = ""

    # Rule 0: Reject if name doesn't match at all
    if not name_ok:
        decision = "needs_more_review"
        reason = f"Top candidate name '{top_name}' does not closely match scholar name '{full_name}'."

    # Rule 1: Very high score (>=0.95) with institution confirmation and gap >= 0.05
    if decision is None and top_score >= 0.95 and has_inst_confirm and score_gap >= 0.05:
        decision = "approve_match"
        proposed_id = top_id
        reason = (f"Score {top_score:.2f} with institution confirmation ({top_inst_matches or top_current_inst}), "
                  f"gap {score_gap:.2f} vs #2. {top_works} works, h={top_h}.")

    # Rule 2: High score (>=0.95) tied, but #2 is fragment or different person
    if decision is None and top_score >= 0.95 and score_gap < 0.05:
        if second_works > 0 and top_works >= 5 * second_works and top_works >= 10:
            if has_inst_confirm or top_inst_score > 0:
                decision = "approve_match"
                proposed_id = top_id
                reason = (f"Score {top_score:.2f} tied with #2 ({second_score:.2f}), but #1 has {top_works} works vs "
                          f"#2's {second_works} works (fragment/minor homonym). Institution: {top_inst_matches or top_current_inst}.")
            else:
                if top_works >= 10 * second_works:
                    decision = "approve_match"
                    proposed_id = top_id
                    reason = (f"Score {top_score:.2f} tied with #2, but #1 has {top_works} works vs #2's {second_works} "
                              f"(overwhelmingly dominant profile). No institution match but name is exact.")
        elif len(cands) > 1 and candidate_is_clearly_different_field(cands[1]) and not candidate_is_clearly_different_field(top):
            if has_inst_confirm:
                decision = "approve_match"
                proposed_id = top_id
                reason = (f"Score {top_score:.2f} tied with #2, but #2 is from a different field (medical/bio). "
                          f"#1 has institution confirmation ({top_inst_matches or top_current_inst}).")

    # Rule 3: Score 0.85-0.94 with institution confirmation and gap >= 0.10
    if decision is None and top_score >= 0.85 and has_inst_confirm and score_gap >= 0.10:
        decision = "approve_match"
        proposed_id = top_id
        reason = (f"Score {top_score:.2f} with institution confirmation, gap {score_gap:.2f} vs #2. "
                  f"{top_works} works, h={top_h}.")

    # Rule 4: Score 0.85-0.94 with institution confirmation, gap >= 0.05 but < 0.10
    if decision is None and top_score >= 0.85 and has_inst_confirm and score_gap >= 0.05:
        if top_works >= 3 * max(second_works, 1):
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Score {top_score:.2f} with institution confirmation, gap {score_gap:.2f}. "
                      f"#1 has {top_works} works vs #2's {second_works}. Institution: {top_inst_matches or top_current_inst}.")
        else:
            decision = "needs_more_review"
            reason = (f"Score {top_score:.2f} with institution confirmation but small gap {score_gap:.2f} "
                      f"and #2 has comparable works ({second_works} vs {top_works}).")

    # Rule 5: Score 0.75 with single candidate or large gap
    if decision is None and top_score >= 0.75 and n_cands == 1:
        if name_ok and (has_inst_confirm or top_inst_score > 0):
            decision = "approve_match"
            proposed_id = top_id
            reason = f"Single candidate with score {top_score:.2f}, name match, and institution signal. {top_works} works."
        elif name_ok and top_timing > 0 and top_works >= 3:
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Single candidate with score {top_score:.2f}, exact name match, timing match "
                      f"({top_timing_note}), {top_works} works.")
        else:
            decision = "needs_more_review"
            reason = (f"Single candidate with score {top_score:.2f} but insufficient institution/timing confirmation. "
                      f"{top_works} works at {top_current_inst}.")

    # Rule 6: Score 0.75 with 2+ candidates but decent gap
    if decision is None and top_score >= 0.75 and score_gap >= 0.15:
        if name_ok and has_inst_confirm:
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Score {top_score:.2f} with gap {score_gap:.2f}, institution confirmation. "
                      f"{top_works} works at {top_current_inst}.")
        elif name_ok and top_timing > 0:
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Score {top_score:.2f} with gap {score_gap:.2f}, timing match ({top_timing_note}). "
                      f"{top_works} works at {top_current_inst}.")

    # Rule 7: Very common names with 25 candidates and tied scores
    if decision is None and n_cands >= 25 and score_gap < 0.05:
        decision = "needs_more_review"
        reason = (f"Common name with {n_cands} candidates, scores tied ({top_score:.2f} vs {second_score:.2f}). "
                  f"Manual disambiguation required.")

    # Rule 8: Score >= 0.95 with no institution match but clear gap
    if decision is None and top_score >= 0.95 and score_gap >= 0.08:
        if name_ok and top_works >= 5:
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Score {top_score:.2f} with gap {score_gap:.2f}, exact name match, {top_works} works (h={top_h}). "
                      f"At {top_current_inst}.")

    # Rule 9: Score >= 1.0 (perfect) with any gap
    if decision is None and top_score >= 1.0:
        if score_gap >= 0.05:
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Perfect score {top_score:.2f} with gap {score_gap:.2f}. {top_works} works at {top_current_inst}.")
        elif second_works > 0 and top_works >= 3 * second_works:
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Perfect score {top_score:.2f}, tied with #2 but #1 has {top_works} works vs {second_works}. "
                      f"At {top_current_inst}.")

    # Rule 10: Early-career/current students (phd_year >= 2025) with single candidate
    if decision is None and scholar_year and safe_int(scholar_year) >= 2025 and n_cands <= 3:
        if name_ok and top_works <= 5:
            if top_score >= 0.70:
                decision = "needs_more_review"
                reason = (f"Early-career scholar (PhD {scholar_year}), top candidate has {top_works} works at {top_current_inst}. "
                          f"Score {top_score:.2f}. Limited publication record makes matching uncertain.")

    # Rule 11: Score >= 0.85 with institution match and works dominance
    if decision is None and top_score >= 0.85 and has_inst_confirm:
        if top_works >= 10 and (second_works == 0 or top_works >= 3 * second_works):
            decision = "approve_match"
            proposed_id = top_id
            reason = (f"Score {top_score:.2f} with institution confirmation, {top_works} works (h={top_h}). "
                      f"Dominant profile. Institution: {top_inst_matches or top_current_inst}.")

    # Rule 12: Score >= 0.85, tied but #2 has no institution match
    if decision is None and top_score >= 0.85 and score_gap < 0.05:
        if has_inst_confirm:
            second_has_inst = False
            if len(cands) > 1:
                second_has_inst = has_strong_institution_confirmation(cands[1], scholar)
            if not second_has_inst:
                decision = "approve_match"
                proposed_id = top_id
                reason = (f"Score {top_score:.2f} tied with #2 ({second_score:.2f}), but only #1 has institution confirmation "
                          f"({top_inst_matches or top_current_inst}). {top_works} works.")

    # Rule 13: Single candidate with score 0.65 and name match
    if decision is None and n_cands == 1 and top_score >= 0.65:
        if name_ok and top_works >= 3:
            decision = "needs_more_review"
            reason = (f"Single candidate with score {top_score:.2f}, name matches, {top_works} works at {top_current_inst}. "
                      f"Below threshold, manual verification recommended.")
        elif name_ok:
            decision = "needs_more_review"
            reason = (f"Single candidate with score {top_score:.2f}, name matches, but only {top_works} works. "
                      f"Insufficient evidence for auto-approval.")

    # Rule 14: Score < 0.65 with no institution match
    if decision is None and top_score < 0.65 and not has_inst_confirm:
        if n_cands >= 25:
            decision = "needs_more_review"
            reason = (f"Low score {top_score:.2f}, no institution match, {n_cands} candidates. "
                      f"Common name requires manual disambiguation.")
        else:
            decision = "reject_match"
            reason = (f"Low score {top_score:.2f}, no institution match, top candidate at {top_current_inst}. "
                      f"No plausible match found.")

    # Default: needs_more_review
    if decision is None:
        decision = "needs_more_review"
        parts = [f"Score {top_score:.2f}"]
        if second_score > 0:
            parts.append(f"vs #2 {second_score:.2f} (gap {score_gap:.2f})")
        if has_inst_confirm:
            parts.append("inst confirmed")
        else:
            parts.append("no inst confirmation")
        parts.append(f"{n_cands} candidates")
        parts.append(f"#1: {top_works} works at {top_current_inst or '(unknown)'}")
        reason = "; ".join(parts) + ". Did not meet auto-approval criteria."

    decisions.append({
        "node_id": nid,
        "full_name": full_name,
        "current_openalex_id": "",
        "proposed_openalex_id": proposed_id,
        "decision": decision,
        "reason": reason,
        "reviewer": "auto_audit_agent_2"
    })

# =====================================================================
# Summary
# =====================================================================
approve_count = sum(1 for d in decisions if d["decision"] == "approve_match")
review_count = sum(1 for d in decisions if d["decision"] == "needs_more_review")
reject_count = sum(1 for d in decisions if d["decision"] == "reject_match")

print(f"\nDecision summary:")
print(f"  approve_match: {approve_count}")
print(f"  needs_more_review: {review_count}")
print(f"  reject_match: {reject_count}")
print(f"  TOTAL: {len(decisions)}")

print(f"\n{'='*80}")
print("APPROVED MATCHES:")
print(f"{'='*80}")
for d in decisions:
    if d["decision"] == "approve_match":
        print(f"  {d['full_name']} -> {d['proposed_openalex_id']}")
        print(f"    {d['reason'][:150]}")

print(f"\n{'='*80}")
print("REJECTED:")
print(f"{'='*80}")
for d in decisions:
    if d["decision"] == "reject_match":
        print(f"  {d['full_name']}: {d['reason'][:150]}")

print(f"\n{'='*80}")
print("NEEDS MORE REVIEW:")
print(f"{'='*80}")
for d in decisions:
    if d["decision"] == "needs_more_review":
        print(f"  {d['full_name']}: {d['reason'][:150]}")

# =====================================================================
# Write output CSV
# =====================================================================
output_path = PROJECT_ROOT / "Data/Derived/OpenAlex_Ambiguous_Decisions_040126.csv"
fieldnames = ["node_id", "full_name", "current_openalex_id", "proposed_openalex_id", "decision", "reason", "reviewer"]
with open(output_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for d in decisions:
        writer.writerow(d)

print(f"\nWrote {len(decisions)} decisions to {output_path}")
