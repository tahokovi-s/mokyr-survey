# Avner Greif Student Email Recovery: RA Audit Memo

**Date:** March 8, 2026
**Scope:** 30 Avner-linked students from `Avner_Student_Email_Recovery_030826.csv`
**Output:** `Data/Derived/Avner_Student_Email_Recovery_RA_Audit_030826.csv`

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Confirmed current (verified from official source) | 16 |
| Improved replacement (better email found) | 6 |
| Probable name correction (identity resolved, email found) | 4 |
| Plausible but unverified | 1 |
| Org contact only (no personal email available) | 1 |
| Unresolved | 1 |
| Identity ambiguous | 1 |
| **Total** | **30** |

**High confidence:** 26 of 30 rows
**Medium confidence:** 2 (Jeff Minner as duplicate, Robert Eberhart advisor link unconfirmed)
**Low confidence:** 2 (Diego Sasson gmail unverified, Katherine de Fontaine identity unclear)

---

## Changes Relative to Prior Recovery File

**10 rows changed** out of 30:

### New emails recovered (previously unresolved)

| Name (Avner list) | Corrected Name | Email Found | Confidence |
|--------------------|---------------|-------------|------------|
| Suamitra Jha | **Saumitra Jha** | saumitra@stanford.edu | High |
| Jeff David Miner | **Jeffrey Miner** | jeffrey.miner@wku.edu | High |
| George Qian | **George Qiao** | gqiao@amherst.edu | High |
| Gregory Beshrov | **Gregory Besharov** | gb87@cornell.edu | High |
| Jeff Minner | Likely = Jeff David Miner | jeffrey.miner@wku.edu | Medium |
| Robert Ebhart | Likely **Robert Eberhart** | reberhart@sandiego.edu | Medium |

### Email replacements (prior email was stale or wrong)

| Name | Prior Email | New Email | Reason |
|------|-----------|-----------|--------|
| Cristian Santesteban | cristian.santesteban@uai.cl | csante@uw.edu | No UAI affiliation found; now Affiliate Faculty at UW |
| Lars Boerner | l.boerner@lse.ac.uk | lars.boerner@wiwi.uni-halle.de | Left LSE ~2016; at Halle-Wittenberg since 2018 |
| Kivanc Karaman | kivanc.karaman@bogazici.edu.tr | kivanc.karaman@boun.edu.tr | Domain correction (boun.edu.tr is official) |
| Elizabeth Sin | isabelle.sin@gmail.com | isabelle.sin@motu.org.nz | Institutional email; upgraded from personal gmail |

---

## Names Remaining Unresolved

1. **Mu Yang** (Stanford GSB, ~2003) -- Name too common. No trace in any academic directory, SSRN, RePEc, or Google Scholar. May have left academia entirely or uses different professional name.

2. **Katherine de Fontaine** (Unknown) -- Only person with this name found online is a hospitality consultant with no Stanford/economics connection. Identity cannot be confirmed.

---

## Rows Needing Manual Advisor Help

These require Avner Greif to confirm identity or provide contact info:

1. **Mu Yang** -- Avner should confirm full name, approximate PhD year, and any known subsequent career path.

2. **Katherine de Fontaine** -- Avner should confirm whether this person exists, their field, and any name variants. The hospitality consultant at hat-kdf.com may or may not be the right person.

3. **Jeff Minner** -- Avner should confirm whether this is the same person as Jeff David Miner (probable duplicate with surname misspelling).

4. **Robert Eberhart** -- Avner should confirm the advisor relationship. Robert Eberhart's Stanford PhD (2014, Management Science) was under Eisenhardt/Eesley, not Greif. His research in institutional theory overlaps Greif's interests, but committee membership is unconfirmed.

5. **Irena Asmundson** -- Currently at Stanford SIEPR, but no personal email is publicly available (SIEPR profile is login-walled). The only public contact is her consulting firm inbox (info@pi-economics.com). Avner or another Stanford colleague could provide her Stanford email directly.

---

## Rows Where Avner's List Has a Misspelling or Wrong Identity

| Avner List Name | Correct Name | Nature of Error |
|-----------------|-------------|-----------------|
| Gregory Beshrov | Gregory Besharov | Surname misspelling |
| Suamitra Jha | Saumitra Jha | First name letter transposition |
| Deigo Sasson | Diego Sasson | First name typo |
| George Qian | George Qiao | Surname error (Qian vs Qiao) |
| Elizabeth Sin | Isabelle Sin | Wrong first name entirely |
| Jeff Minner | Jeff David Miner (probable) | Surname misspelling + likely duplicate |
| Robert Ebhart | Robert Eberhart (probable) | Surname misspelling |
| Christown (NZ) | Christchurch | Affiliation/city misspelling |

---

## Critical Note: Elizabeth Sin = Isabelle Sin (Already Responded)

"Elizabeth Sin" on Avner's list is actually **Isabelle (Izi) Sin**, who is already a survey respondent (R-R_4pT1HyRG1hLQfM4). She listed Avner Greif as her PhD advisor in Q11. She is a Senior Fellow at Motu Economic and Public Policy Research in Wellington, NZ. **No outreach is needed for this person.**

---

## Rows Needing Human Decision Before Mailing

| Name | Issue | Decision Needed |
|------|-------|----------------|
| Elizabeth Sin / Isabelle Sin | Already responded to survey | Remove from outreach list |
| Jeff Minner | Probable duplicate of Jeff David Miner | Confirm with Avner, then remove if duplicate |
| Robert Eberhart | Advisor link to Greif unconfirmed | Confirm with Avner before contacting |
| Katherine de Fontaine | Identity cannot be verified | Ask Avner for clarification before any contact |
| Diego Sasson | Only personal gmail available; now in finance (ExodusPoint) | Decision on whether to use unverified gmail |
| Irena Asmundson | Only org inbox available (info@pi-economics.com) | Try org inbox or ask Stanford colleague for her SIEPR email |

---

## Methodology

Three parallel RA-style subagent teams audited 10 names each:
- **Group A:** Unresolved and low-confidence cases (hardest)
- **Group B:** Medium-confidence cases + cross-verification of some high-confidence
- **Group C:** High-confidence verification

Each agent searched: university/employer directories, faculty pages, personal academic sites, SSRN, RePEc, NBER, Google Scholar, conference programs, and CVs. No generic people-search sites were used. Emails were only assigned when found on or corroborated by official institutional sources.

Prior recovery file preserved at: `Data/Derived/Avner_Student_Email_Recovery_030826.csv`
