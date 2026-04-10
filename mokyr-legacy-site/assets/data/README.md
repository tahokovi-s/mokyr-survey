# Website Data

This directory is for generated static data files consumed by the website.

Current intended file:

- `bibliometric-panel.json` — exported by
  `Code/Bibliometrics/build_openalex_panel.py`

Example refresh:

```bash
python3 Code/Bibliometrics/build_openalex_panel.py \
  --date 040126 \
  --manual-decisions Data/Derived/OpenAlex_All_Decisions_040126.csv \
  --website-output mokyr-legacy-site/assets/data/bibliometric-panel.json
```

The site copy is a filtered export. It retains roster rows but sets
`public_ready=false` and suppresses topic / top-paper content for unresolved or
suspicious matches.
