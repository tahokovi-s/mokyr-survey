# Communications Directory

Reorganized 2026-03-12 from a flat file layout into the following structure.

## Structure

```
Communications/
├── Drafts/
│   ├── Advisor_Outreach/    # Outbound email drafts for advisor/student outreach
│   ├── Survey_Outreach/     # Outbound email drafts for general survey waves
│   └── Templates/           # Reusable email templates
├── Memos/
│   ├── Avner/               # Memos related to Avner student outreach review
│   ├── Internal_Status/     # Wave status updates sent to Ran
│   └── Outreach/            # Strategy memos for follow-up outreach
├── Reports/
│   └── Generated/           # Machine-generated reports (e.g., outreach response checks)
├── Incoming/
│   ├── Bounces/             # Undeliverable email bounce notifications (PDFs)
│   ├── Forwards/            # Forwarded inbound emails (PDFs)
│   └── Replies/             # Inbound reply emails (PDFs)
└── README.md                # This file
```

## Notes

- Bounce PDFs may share similar subject lines but have different checksums; all are kept.
- Date suffixes on incoming PDFs were inferred from filesystem timestamps where filenames lacked explicit dates.
- Generated reports are written by `Code/Outreach/check_outreach_responses.py` into `Reports/Generated/`.
- Migration manifest: `Logs/Communications_Reorg_031226/Communications_Reorg_Manifest_031226.csv`.
