# Outreach Response Check — 031126

- Current raw export: `Mokyr_Survey_Responses_031126_Raw.csv`
- Baseline raw export: `Mokyr_Survey_Responses_022226_Raw.csv`
- Matching method: ResponseId delta between raw exports, then match by known email plus normalized/fuzzy name variants.
- Important caveat: this is list membership tracking, not a verified sent-email log.

## New Activity Since Baseline

- New raw response records: 35
- New completed responses: 34
- New incomplete starts: 1
- Completed responses matched to outreach union: 34
- Completed responses unmatched: 0
- Incomplete starts matched to outreach union: 0

## Outreach Universe

- Non-respondent file rows: 143
- Avner file rows: 30
- Overlap between the two files: 22
- Unique people across both files: 150

## Completed Respondents By Membership

- Non-respondent only: 20
- In both files: 12
- Avner only: 2

## Avner `send_now` Bucket

- Responded since baseline: 14
- Total `send_now` rows: 25
- Share of `send_now` rows with a completed response in this snapshot: 56.0%

## Non-Respondent Actions Represented Among Completed Responders

- `FIND_EMAIL_THEN_RESEND`: 13
- `STANDARD_FOLLOW_UP`: 9
- `RESEND_CORRECTED_EMAIL`: 5
- `INVESTIGATE`: 1
- `PERSONALIZED_FOLLOW_UP`: 1
- `PERSONAL_ASK_FROM_MOKYR`: 1
- `SEND_WITH_UPDATED_FORMAT`: 1
- `TRY_CORRECTED_EMAIL`: 1

## Alias / Fuzzy Matches Worth Noting

- `Burke Evans` -> `Burkett Evans` (name_prefix)
- `Tom Geraghty` -> `Thomas Geraghty` (name_nickname)
- `Oeivind "Evan" Schoeyen` -> `Øivind Schøyen` (name_fuzzy_full)

## Unmatched New Activity

- `2026-03-10 07:46:53` | finished=`False` progress=`6` | (blank name) | (blank email)
