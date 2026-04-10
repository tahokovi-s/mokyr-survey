# Mokyr Legacy Site

Static website scaffold for Joel Mokyr's private 80th birthday reveal.

## Structure

- `index.html` — welcome page
- `family/index.html` — branded wrapper around the genealogy visualization
- `tributes/index.html` — placeholder page
- `about/index.html` — placeholder page
- `network/mokyr-genealogy.html` — bundled self-contained network export
- `assets/` — shared CSS, JS, and preview image

## Local preview

Serve this directory as a static site:

```bash
cd mokyr-legacy-site
python3 -m http.server 8000
```

Then open `http://localhost:8000/`.

## Deploy to Netlify

1. Move or copy this directory into its own private GitHub repo.
2. Connect that private repo to Netlify.
3. Set the publish directory to the repo root.
4. In Netlify, enable site-wide password protection before sharing any URL.
5. Keep the generated Netlify subdomain private until reveal day.

## Updating the visualization

When the underlying network changes in the research repo, replace:

- `network/mokyr-genealogy.html`
- `assets/images/network-preview.png`

with the newest exported HTML and screenshot.

## Updating bibliometric data

The bibliometric panel is generated from the research repo and can be written
directly into the site tree:

```bash
python3 Code/Bibliometrics/build_openalex_panel.py \
  --date 040126 \
  --manual-decisions Data/Derived/OpenAlex_All_Decisions_040126.csv \
  --website-output mokyr-legacy-site/assets/data/bibliometric-panel.json
```

That JSON is designed to be a static website input, so the site does not need
to call OpenAlex live. The website copy is filtered: rows that are unresolved or
flagged as suspicious remain available for roster completeness, but
`public_ready=false` and public-facing top-paper / topic fields are suppressed.
