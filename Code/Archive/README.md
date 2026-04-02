# Code/Archive

Historical scripts that are no longer part of the active pipeline. Preserved
for reference and auditability.

## Wave_Campaigns/

One-off scripts tied to specific survey waves. Each has hard-coded paths
and dates that correspond to the wave it was built for.

| Script | Wave | Why archived |
|--------|------|--------------|
| `generate_wave5.py` | Wave 5 | Wave-specific contact-list builder; superseded by the general pipeline |
| `wave4_fuzzy_match.py` | Wave 4 | One-off duplicate-checking script with fixed Wave 4 inputs |
| `wave4_sanity_check.py` | Wave 4 | One-off QA script with hard-coded paths and dates |

## Superseded/

Scripts whose functionality has been replaced by a newer workflow.

| Script | Replaced by |
|--------|-------------|
| `recover_missing_emails.py` | Manual `Email_Recovery_{date}.csv` workflow fed into `build_network.py --email-recovery` |
