#!/usr/bin/env python3
"""
viz_network.py — Render interactive genealogy HTML from Network_Nodes + Network_Edges CSVs.

Output: Output/mokyr-genealogy-{date}.html  (self-contained, D3 inlined)
"""

import csv
import json
import sys
import hashlib
import argparse
import base64
import re
from datetime import datetime
from pathlib import Path
try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    urlopen = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_NODES_DATE_RE = re.compile(r"^Network_Nodes_(\d{6})\.csv$")
_EDGES_DATE_RE = re.compile(r"^Network_Edges_(\d{6})\.csv$")

D3_URL    = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"
# SHA-256 of d3.min.js v7.9.0 from cdnjs.  Verified against CDN on first run.
# If this hash is empty the script will print the actual hash and ask you to pin it.
D3_SHA256 = "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _resolve_viz_date(date_arg: str | None, nodes_arg: str | None, edges_arg: str | None) -> str:
    if date_arg:
        return date_arg

    explicit_dates = {
        token for token in (
            _extract_date_token(nodes_arg),
            _extract_date_token(edges_arg),
        )
        if token
    }
    if len(explicit_dates) > 1:
        sys.exit(
            "ERROR: --nodes and --edges imply different dates. "
            "Pass --date explicitly or provide aligned inputs."
        )
    if explicit_dates:
        return explicit_dates.pop()

    derived_dir = PROJECT_ROOT / "Data" / "Derived"
    latest_nodes = _latest_matching_date(derived_dir, _NODES_DATE_RE)
    latest_edges = _latest_matching_date(derived_dir, _EDGES_DATE_RE)
    if not latest_nodes or not latest_edges:
        sys.exit(
            "ERROR: Could not infer a default date from network inputs. "
            "Pass --date explicitly."
        )
    if latest_nodes != latest_edges:
        sys.exit(
            "ERROR: Latest node and edge files have different dates "
            f"({latest_nodes} vs {latest_edges}). Pass --date or explicit paths."
        )
    print(f"INFO: Using latest common network date: {latest_nodes}")
    return latest_nodes


def _fetch_d3(d3_path=None):
    """Return (js_bytes, actual_sha256_hex).  Exits on failure."""
    if d3_path:
        p = Path(d3_path)
        if not p.exists():
            sys.exit(f"ERROR: --d3-path file not found: {p}")
        data = p.read_bytes()
        actual = _sha256_hex(data)
        if D3_SHA256 and actual != D3_SHA256:
            sys.exit(
                f"ERROR: D3 SHA-256 mismatch for local file {p}\n"
                f"  Expected : {D3_SHA256}\n"
                f"  Actual   : {actual}\n"
                "Update D3_SHA256 in viz_network.py to the Actual value above."
            )
        return data.decode('utf-8'), actual

    # Fetch from CDN
    print(f"Fetching D3 from {D3_URL} ...")
    try:
        req = Request(D3_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
    except URLError as e:
        sys.exit(
            f"ERROR: Could not fetch D3 from CDN ({e}).\n"
            f"Download manually:\n"
            f"  curl -o /tmp/d3.min.js '{D3_URL}'\n"
            f"Then rerun with: --d3-path /tmp/d3.min.js"
        )

    actual = _sha256_hex(data)
    if D3_SHA256 and actual != D3_SHA256:
        sys.exit(
            f"ERROR: D3 SHA-256 mismatch (CDN).\n"
            f"  Expected : {D3_SHA256}\n"
            f"  Actual   : {actual}\n"
            "Update D3_SHA256 in viz_network.py to the Actual value above.\n"
            "Or set D3_SHA256 = '' to skip verification (not recommended for production)."
        )
    if not D3_SHA256:
        print(f"INFO: D3 SHA-256 = {actual}")
        print("      Pin this hash by setting D3_SHA256 in viz_network.py.")
    return data.decode('utf-8'), actual


def _safe_json(obj) -> str:
    """JSON-serialize and escape </  to prevent </script> breakout."""
    s = json.dumps(obj, ensure_ascii=False)
    return s.replace("</", "<\\/")


def _data_url(path: Path, mime_type: str) -> str:
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode('ascii')
    return f"data:{mime_type};base64,{encoded}"


def _load_nodes(nodes_csv: Path) -> list:
    """Load node rows; exclude email from output."""
    nodes = []
    with open(nodes_csv, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            gen = row['generation']
            try:
                gen = int(gen)
            except (ValueError, TypeError):
                gen = None
            populated_detail_fields = sum(
                1
                for value in (
                    row['email'],
                    row['phd_institution_canon'] or row['phd_institution_raw'],
                    row['phd_year'],
                    row['current_employer_canon'] or row['current_employer_raw'],
                    row['country'],
                    row['us_state'],
                )
                if str(value or '').strip()
            )
            nodes.append({
                'id':           row['node_id'],
                'label':        f"{row['first_name']} {row['last_name']}".strip(),
                'generation':   gen,
                'has_students': row['has_students'].lower() in ('true', '1', 'yes'),
                'is_respondent': row['is_respondent'].lower() in ('true', '1', 'yes'),
                'institution':  row['phd_institution_canon'] or row['phd_institution_raw'],
                'employer':     row['current_employer_canon'] or row['current_employer_raw'],
                'phd_year':     row['phd_year'],
                'country':      row['country'],
                'us_state':     row['us_state'],
                'nonrespondent_field_count': populated_detail_fields,
                'show_nonrespondent': populated_detail_fields >= 2,
                # email intentionally excluded
            })
    return nodes


def _load_edges(edges_csv: Path) -> list:
    edges = []
    with open(edges_csv, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            edges.append({
                'source':     row['source_id'],
                'target':     row['target_id'],
                'edge_type':  row['edge_type'],
                'confidence': row['confidence'],
            })
    return edges


def _build_html(nodes: list, edges: list, d3_js: str) -> str:
    nodes_json = _safe_json(nodes)
    edges_json = _safe_json(edges)
    wordmark_photo_data_url = _data_url(
        PROJECT_ROOT / "mokyr-legacy-site/assets/images/joel-mokyr-168x210.jpg",
        "image/jpeg",
    )

    return f"""<!DOCTYPE html>
<!-- INTERNAL USE ONLY: personal academic data. Do not distribute. -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mokyr Academic Genealogy</title>
<style>
  :root {{
    --bg: #fbfbf8;
    --text: #101216;
    --muted: rgba(16, 18, 22, 0.64);
    --soft: rgba(16, 18, 22, 0.44);
    --line: rgba(16, 18, 22, 0.08);
    --line-strong: rgba(16, 18, 22, 0.15);
    --accent: #d6bc7b;
    --accent-deep: #9b7f42;
    --card-shadow: 0 16px 40px rgba(16, 18, 22, 0.06);
    --radius-xl: 32px;
    --radius-lg: 22px;
    --radius-md: 16px;
    --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
    --ease-card: cubic-bezier(0.16, 1, 0.3, 1);
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ height: 100%; }}
  body {{
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    font-family: "Neue Haas Grotesk Text Pro", "Avenir Next", "Helvetica Neue", sans-serif;
    display: flex;
    flex-direction: column;
    overflow-x: hidden;
    overflow-y: auto;
  }}
  a {{ color: inherit; text-decoration: none; }}

  .site-header,
  .viz-controls,
  .legend-strip,
  .viz-intro-inner,
  .site-footer {{
    width: min(calc(100% - 48px), 1240px);
    margin: 0 auto;
    flex-shrink: 0;
  }}
  .site-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 24px 0 10px;
  }}
  .compact-header {{ padding-bottom: 0; }}
  .wordmark {{
    display: inline-flex;
    align-items: center;
    gap: 14px;
  }}
  .wordmark-mark {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 38px;
    height: 38px;
    flex-shrink: 0;
    overflow: hidden;
    border-radius: 50%;
    border: 1.5px solid rgba(16, 18, 22, 0.12);
    background-color: #c3ab77;
    background-image: url("{wordmark_photo_data_url}");
    background-position: center 18%;
    background-repeat: no-repeat;
    background-size: cover;
    box-shadow: 0 8px 20px rgba(17, 19, 24, 0.12);
    color: transparent;
    font-size: 0;
    line-height: 0;
  }}
  .wordmark-text {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .wordmark-title {{
    font-size: 0.98rem;
    letter-spacing: 0;
  }}
  .wordmark-subtitle {{
    color: rgba(16, 18, 22, 0.56);
    font-size: 0.72rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }}
  .back-link {{
    padding: 11px 16px;
    border: 1px solid var(--line);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.74);
    color: var(--muted);
    font-size: 0.92rem;
    transition:
      border-color 200ms var(--ease-out),
      color 200ms var(--ease-out),
      transform 200ms var(--ease-out);
  }}
  .back-link:hover {{
    color: var(--text);
    border-color: var(--line-strong);
    transform: translateY(-1px);
  }}

  #viz-shell {{
    position: relative;
    flex: 0 0 auto;
    min-height: 0;
    overflow: hidden;
  }}

  .viz-intro {{
    width: 100%;
    flex-shrink: 0;
    padding: 28px 0;
  }}
  .viz-intro-title {{
    margin: 6px 0 10px;
    color: var(--text);
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    font-size: 2.25rem;
    font-weight: 400;
    line-height: 1.04;
  }}
  .viz-intro-lead {{
    max-width: 58ch;
    margin: 0;
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.6;
  }}

  .viz-controls {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 0 16px;
  }}
  .viz-controls-right {{
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 10px;
  }}
  .privacy-pill {{
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 11px 16px;
    border: 1px solid var(--line);
    border-radius: 999px;
    background: #ffffff;
    color: var(--muted);
    cursor: pointer;
    transition:
      border-color 200ms var(--ease-out),
      background 200ms var(--ease-out),
      color 200ms var(--ease-out),
      transform 200ms var(--ease-out);
  }}
  .privacy-pill:hover {{
    border-color: var(--line-strong);
    transform: translateY(-1px);
  }}
  .privacy-pill.active {{
    border-color: var(--accent);
    color: var(--accent-deep);
    background: rgba(214, 188, 123, 0.08);
  }}
  .privacy-pill:focus-within {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(214, 188, 123, 0.18);
  }}
  .privacy-pill input[type=checkbox] {{
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    border: 0;
    opacity: 0;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    overflow: hidden;
    white-space: nowrap;
  }}
  .pill-label {{
    font-size: 12px;
    line-height: 1;
    letter-spacing: 0.16em;
    text-transform: uppercase;
  }}
  .viz-search-wrap {{
    display: flex; flex-direction: column; align-items: flex-start;
  }}
  #search {{
    width: min(420px, 100%);
    padding: 12px 18px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: #ffffff;
    color: var(--text);
    font-size: 14px;
    box-shadow: var(--card-shadow);
    transition:
      border-color 200ms var(--ease-out),
      box-shadow 200ms var(--ease-out);
  }}
  #search:focus {{
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(214, 188, 123, 0.18);
  }}
  #search::placeholder {{ color: var(--soft); }}

  .legend-strip {{
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }}
  .legend-strip-inner {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 0;
    white-space: nowrap;
    overflow-x: auto;
    scrollbar-width: none;
  }}
  .legend-strip-inner::-webkit-scrollbar {{ display: none; }}
  .legend-entry {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--muted);
    flex-shrink: 0;
  }}
  .legend-entry strong {{
    color: var(--text);
  }}
  .legend-divider {{
    color: var(--soft);
    flex-shrink: 0;
  }}
  .legend-dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}

  #tooltip {{
    position: absolute; pointer-events: none; z-index: 20;
    background: #ffffff;
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    box-shadow: var(--card-shadow);
    padding: 10px 14px; font-size: 13px;
    max-width: 280px; line-height: 1.5;
    display: none;
  }}

  #stats {{
    position: absolute; top: 12px; right: 12px; z-index: 10;
    background: #ffffff;
    border: 1px solid var(--line);
    border-radius: 999px;
    box-shadow: var(--card-shadow);
    padding: 10px 16px;
    font-size: 12px;
    color: var(--muted);
  }}
  #stats span {{
    color: var(--text);
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    font-size: 1.05rem;
  }}

  #person-panel {{
    position: absolute; top: 64px; right: 12px; bottom: 12px; z-index: 10;
    width: min(360px, calc(100vw - 24px));
    background: #ffffff;
    border: 1px solid var(--line);
    border-radius: var(--radius-xl);
    box-shadow: var(--card-shadow);
    display: flex; flex-direction: column; gap: 16px;
    padding: 38px;
    overflow: hidden;
    opacity: 0.98;
    transform: translateY(8px);
    transition:
      transform 240ms var(--ease-card),
      opacity 240ms var(--ease-card);
  }}
  #person-panel.is-open {{
    opacity: 1;
    transform: translateY(0);
  }}
  .panel-header {{
    display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  }}
  .eyebrow {{
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: rgba(16, 18, 22, 0.46);
    margin-bottom: 8px;
  }}
  #person-title {{
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    font-size: 24px; line-height: 1.1; color: var(--text); font-weight: 400;
  }}
  #person-subtitle {{
    margin-top: 8px; font-size: 13px; color: var(--muted); line-height: 1.5;
  }}
  #panel-close {{
    border: 1px solid var(--line); border-radius: 999px;
    padding: 8px 12px;
    background: #ffffff;
    color: var(--muted); font-size: 12px; cursor: pointer;
    transition:
      border-color 200ms var(--ease-out),
      color 200ms var(--ease-out);
  }}
  #panel-close:hover:not(:disabled) {{
    color: var(--text);
    border-color: var(--line-strong);
  }}
  #panel-close:disabled {{
    opacity: 0.45; cursor: default;
  }}
  #person-empty {{
    color: var(--muted); font-size: 14px; line-height: 1.55;
  }}
  #person-content {{
    overflow-y: auto;
    display: flex; flex-direction: column; gap: 18px;
    padding-right: 4px;
  }}
  .detail-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }}
  .detail-item {{
    background: #ffffff;
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    padding: 10px 12px;
    min-height: 68px;
  }}
  .detail-label {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.14em;
    color: var(--muted); margin-bottom: 8px;
  }}
  .detail-value {{
    font-size: 14px; line-height: 1.4; color: var(--text); font-weight: 500;
    word-break: break-word;
  }}
  .panel-section {{
    display: flex; flex-direction: column; gap: 12px;
  }}
  .panel-section h3 {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.14em;
    color: var(--muted);
  }}
  .relationship-list {{
    display: flex; flex-direction: column; gap: 8px;
  }}
  .relationship-item {{
    background: #ffffff;
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    padding: 10px 12px;
    color: var(--text);
    line-height: 1.4;
  }}
  .relationship-empty {{
    color: var(--muted);
    font-size: 14px;
  }}

  #graph {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
  }}
  .link {{
    stroke: rgba(16, 18, 22, 0.12);
    stroke-width: 1;
    fill: none;
    transition:
      opacity 220ms var(--ease-out),
      stroke 220ms var(--ease-out);
  }}
  .link.highlighted {{ stroke: rgba(214, 188, 123, 0.55); stroke-width: 1.5; }}
  /* Fainter stroke for edges sourced from Q12a free-text listings (edge_type='q12a'); 0.5 * 0.12 base alpha = ~0.06 effective. */
  .link.q12a {{ stroke-dasharray: none; stroke-opacity: 0.5; }}
  .node circle {{
    stroke-width: 1.5px;
    cursor: pointer;
    transition:
      opacity 220ms var(--ease-out),
      stroke 220ms var(--ease-out);
  }}
  .node.hidden {{ display: none; }}
  .node.dimmed circle {{ opacity: 0.2; }}
  .node.dimmed text {{ opacity: 0.15; }}
  .node text {{
    font-family: "Neue Haas Grotesk Text Pro", "Avenir Next", "Helvetica Neue", sans-serif;
    font-size: 11px; fill: var(--text); pointer-events: none;
    paint-order: stroke; stroke: #fbfbf8; stroke-width: 3px;
    transition:
      opacity 220ms var(--ease-out),
      fill 220ms var(--ease-out);
  }}
  .highlighted circle {{ stroke: var(--accent) !important; stroke-width: 2.5px !important; }}
  .node.selected circle {{
    stroke: rgba(214, 188, 123, 0.6) !important; stroke-width: 3.5px !important;
  }}
  .node.selected text {{ fill: var(--text); font-weight: 700; }}

  .site-footer {{
    padding: 16px 0 24px;
    border-top: 1px solid var(--line);
    font-size: 0.8rem;
    color: var(--soft);
  }}
  .footer-credit {{ margin: 0; }}

  @media (max-width: 900px) {{
    #person-panel {{
      top: auto; left: 12px; right: 12px; bottom: 12px; width: auto;
      max-height: min(46vh, 380px);
      padding: 28px;
    }}
  }}

  @media (max-width: 760px) {{
    .site-header,
    .viz-controls,
    .legend-strip,
    .viz-intro-inner,
    .site-footer {{
      width: min(calc(100% - 32px), 1240px);
    }}
    .site-header {{
      flex-direction: column;
      align-items: flex-start;
      gap: 12px;
      padding: 18px 0 8px;
    }}
    .site-footer {{
      padding: 14px 0 18px;
    }}
    .viz-controls {{
      flex-direction: column;
      align-items: stretch;
      gap: 12px;
      padding: 10px 0 14px;
    }}
    .viz-intro {{
      padding: 20px 0;
    }}
    .viz-intro-title {{
      font-size: 1.5rem;
    }}
    .viz-controls-right {{
      justify-content: flex-start;
    }}
    .viz-search-wrap,
    #search {{
      width: 100%;
    }}
    .wordmark {{
      gap: 12px;
    }}
    .wordmark-mark {{
      width: 34px;
      height: 34px;
      font-size: 0.94rem;
    }}
    .wordmark-title {{
      font-size: 0.94rem;
    }}
    .wordmark-subtitle {{
      font-size: 0.68rem;
    }}
  }}

  @media (max-width: 560px) {{
    .privacy-pill {{
      padding: 10px 14px;
    }}
    #person-panel {{
      max-height: 52vh;
      padding: 24px;
    }}
    #stats {{
      max-width: calc(100vw - 24px);
    }}
    .detail-grid {{
      grid-template-columns: 1fr;
    }}
  }}
</style>
</head>
<body>

<header class="site-header compact-header">
  <a class="wordmark" href="../" aria-label="Return to home">
    <span class="wordmark-mark">M</span>
    <span class="wordmark-text">
      <span class="wordmark-title">Joel Mokyr</span>
      <span class="wordmark-subtitle">An 80th Birthday Celebration</span>
    </span>
  </a>
  <a class="back-link" href="../">Back to welcome</a>
</header>

<div class="viz-controls" aria-label="Network controls">
  <div class="viz-search-wrap">
    <input id="search" type="text" placeholder="Search by name…">
  </div>
  <div class="viz-controls-right">
    <label class="privacy-pill">
      <input type="checkbox" id="showLabels">
      <span class="pill-label">Labels</span>
    </label>
    <label class="privacy-pill">
      <input type="checkbox" id="layoutConcentric" checked aria-label="Concentric layout active. Press Enter to switch to force layout.">
      <span class="pill-label">Concentric</span>
    </label>
  </div>
</div>

<div class="legend-strip" aria-label="Generation legend">
  <div class="legend-strip-inner">
    <div class="legend-entry"><span class="legend-dot" style="background:#d6bc7b"></span><strong>Joel</strong></div>
    <span class="legend-divider" aria-hidden="true">&middot;</span>
    <div class="legend-entry"><span class="legend-dot" style="background:#1f242d"></span><strong>Gen 1</strong></div>
    <span class="legend-divider" aria-hidden="true">&middot;</span>
    <div class="legend-entry"><span class="legend-dot" style="background:#4a5161"></span><strong>Gen 2</strong></div>
    <span class="legend-divider" aria-hidden="true">&middot;</span>
    <div class="legend-entry"><span class="legend-dot" style="background:#8a92a3"></span><strong>Gen 3</strong></div>
    <span class="legend-divider" aria-hidden="true">&middot;</span>
    <div class="legend-entry"><span class="legend-dot" style="background:#c9ced8"></span><strong>Gen 4+</strong></div>
  </div>
</div>

<section class="viz-intro" aria-label="Network introduction">
  <div class="viz-intro-inner">
    <div class="eyebrow">The Network</div>
    <h1 class="viz-intro-title">Four generations, charted.</h1>
    <p class="viz-intro-lead">388 scholars, traced through Joel's advising lineage.</p>
  </div>
</section>

<main id="viz-shell">
  <div id="stats">
    <span id="stat-nodes"></span> nodes &nbsp;·&nbsp;
    <span id="stat-edges"></span> edges
  </div>

  <aside id="person-panel" aria-live="polite">
    <div class="panel-header">
      <div>
        <div class="eyebrow">Person Details</div>
        <h3 id="person-title">Select a person</h3>
        <div id="person-subtitle">Click a node to inspect the latest details and direct relationships.</div>
      </div>
      <button id="panel-close" type="button" disabled>Clear</button>
    </div>
    <div id="person-empty">
      The panel will show person-level metadata from the node file plus direct advisors and direct students from the current network edges.
    </div>
    <div id="person-content" hidden></div>
  </aside>

  <div id="tooltip"></div>
  <svg id="graph"></svg>
</main>

<footer class="site-footer">
  <p class="footer-credit">For Joel's 80th. Project led by Ran Abramitzky. I thank Jensen Ahokovi for his superb assistance.</p>
</footer>

<script>
// ── inline D3 ──────────────────────────────────────────────────────────────
{d3_js}
// ── data ───────────────────────────────────────────────────────────────────
const RAW_NODES = {nodes_json};
const RAW_EDGES = {edges_json};
// ──────────────────────────────────────────────────────────────────────────

function connectedNodeIdsFromRoot(nodes, edges, rootId) {{
  const knownNodeIds = new Set(nodes.map(node => node.id));
  const childrenById = new Map();

  edges.forEach(edge => {{
    if (!knownNodeIds.has(edge.source) || !knownNodeIds.has(edge.target)) return;
    if (!childrenById.has(edge.source)) childrenById.set(edge.source, []);
    childrenById.get(edge.source).push(edge.target);
  }});

  if (!knownNodeIds.has(rootId)) return new Set();

  const seen = new Set([rootId]);
  const stack = [rootId];

  while (stack.length) {{
    const current = stack.pop();
    (childrenById.get(current) || []).forEach(childId => {{
      if (seen.has(childId)) return;
      seen.add(childId);
      stack.push(childId);
    }});
  }}

  return seen;
}}

const CONNECTED_NODE_IDS = connectedNodeIdsFromRoot(RAW_NODES, RAW_EDGES, 'JM-ROOT');
const NETWORK_NODES = RAW_NODES.filter(node => CONNECTED_NODE_IDS.has(node.id));
const NETWORK_EDGES = RAW_EDGES.filter(edge => (
  CONNECTED_NODE_IDS.has(edge.source) && CONNECTED_NODE_IDS.has(edge.target)
));

const NODE_BY_ID = new Map(NETWORK_NODES.map(node => [node.id, node]));

function buildPrimaryParentByNode(nodes, edges) {{
  const parentsByNode = new Map();

  function ensureParents(nodeId) {{
    if (!parentsByNode.has(nodeId)) parentsByNode.set(nodeId, []);
    return parentsByNode.get(nodeId);
  }}

  edges.forEach(edge => {{
    ensureParents(edge.target).push(edge.source);
  }});

  function selectPrimaryAdvisor(nodeId, parentIds) {{
    const node = NODE_BY_ID.get(nodeId) || {{}};
    const candidates = parentIds.map(parentId => {{
      const parent = NODE_BY_ID.get(parentId) || {{}};
      return {{
        id: parentId,
        label: parent.label || parentId,
        generation: parent.generation ?? 99,
        isRoot: parentId === 'JM-ROOT',
      }};
    }});
    const rootCandidates = candidates.filter(candidate => candidate.isRoot);
    const nonRootCandidates = candidates.filter(candidate => !candidate.isRoot);
    let pool = candidates;
    if (rootCandidates.length && nonRootCandidates.length) {{
      if (node.generation === 1) return rootCandidates[0].id;
      pool = nonRootCandidates;
    }}
    const maxGeneration = Math.max(...pool.map(candidate => candidate.generation));
    const highestGeneration = pool.filter(candidate => candidate.generation === maxGeneration);
    highestGeneration.sort((a, b) => a.label.localeCompare(b.label));
    return highestGeneration[0].id;
  }}

  const primaryParentByNode = new Map();
  nodes.forEach(node => {{
    if (node.id === 'JM-ROOT') return;
    const dedupedParents = [...new Set(parentsByNode.get(node.id) || [])];
    if (!dedupedParents.length) return;
    primaryParentByNode.set(
      node.id,
      dedupedParents.length === 1 ? dedupedParents[0] : selectPrimaryAdvisor(node.id, dedupedParents)
    );
  }});

  return primaryParentByNode;
}}

function buildRelationshipMaps(nodes, edges) {{
  const advisorsByNode = new Map();
  const studentsByNode = new Map();
  const primaryParentByNode = buildPrimaryParentByNode(nodes, edges);

  primaryParentByNode.forEach((parentId, nodeId) => {{
    advisorsByNode.set(nodeId, new Set([parentId]));
    if (!studentsByNode.has(parentId)) studentsByNode.set(parentId, new Set());
    studentsByNode.get(parentId).add(nodeId);
  }});

  return {{ advisorsByNode, studentsByNode }};
}}

const RELATIONSHIPS = buildRelationshipMaps(NETWORK_NODES, NETWORK_EDGES);

const GEN_COLOR = {{
  0: '#d6bc7b',
  1: '#1f242d',
  2: '#4a5161',
  3: '#8a92a3',
}};
function nodeColor(d) {{
  if (d.generation === null || d.generation === undefined) return '#c9ced8';
  return GEN_COLOR[d.generation] || '#c9ced8';
}}
function nodeRadius(d) {{
  if (d.id === 'JM-ROOT') return 18;
  if (d.has_students) return 10;
  return 6;
}}

// ── state ──────────────────────────────────────────────────────────────────
let showLabels  = false;
let searchTerm  = '';
let layoutMode  = 'concentric';
let selectedNodeId = null;
let hoveredNodeId = null;

let simulation;
let currentNodeSelection = null;
let currentLinkSelection = null;
let currentNeighborIds = new Map();
let currentAlwaysVisibleLabelIds = new Set();
let currentSimNodes = [];
let currentSimEdges = [];
let currentShellWidth = 0;
let currentShellHeight = 0;

// ── build visible sets ─────────────────────────────────────────────────────
function visibleNodeIds() {{
  return new Set(NETWORK_NODES.filter(n => (
    n.id === 'JM-ROOT' || n.is_respondent || n.show_nonrespondent
  )).map(n => n.id));
}}
function visibleEdges(vids) {{
  return NETWORK_EDGES.filter(e => {{
    if (!vids.has(e.source) || !vids.has(e.target)) return false;
    if (e.confidence === 'medium') return false;
    return true;
  }});
}}

// ── D3 setup ───────────────────────────────────────────────────────────────
const svg = d3.select('#graph');
const g   = svg.append('g');
const vizShellEl = document.getElementById('viz-shell');
const footerEl = document.querySelector('.site-footer');
const panelEl = document.getElementById('person-panel');
const panelTitleEl = document.getElementById('person-title');
const panelSubtitleEl = document.getElementById('person-subtitle');
const panelEmptyEl = document.getElementById('person-empty');
const panelContentEl = document.getElementById('person-content');
const panelCloseEl = document.getElementById('panel-close');
const layoutToggleEl = document.getElementById('layoutConcentric');
const controlPillInputs = Array.from(document.querySelectorAll('.privacy-pill input[type="checkbox"]'));

// Arrowhead marker
svg.append('defs').append('marker')
  .attr('id', 'arrow')
  .attr('viewBox', '0 -5 10 10')
  .attr('refX', 20).attr('refY', 0)
  .attr('markerWidth', 6).attr('markerHeight', 6)
  .attr('orient', 'auto')
  .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', 'rgba(16, 18, 22, 0.12)');

// Zoom + pan
const zoom = d3.zoom()
  .scaleExtent([0.05, 4])
  .on('zoom', (event) => {{ g.attr('transform', event.transform); }});
svg.call(zoom);

const linkG = g.append('g').attr('class', 'links');
const nodeG = g.append('g').attr('class', 'nodes');

function buildNeighborIds(edges) {{
  const neighborIds = new Map();

  function ensureSet(nodeId) {{
    if (!neighborIds.has(nodeId)) neighborIds.set(nodeId, new Set());
    return neighborIds.get(nodeId);
  }}

  edges.forEach(edge => {{
    ensureSet(edge.source).add(edge.target);
    ensureSet(edge.target).add(edge.source);
  }});

  return neighborIds;
}}

function edgeEndpointId(endpoint) {{
  return typeof endpoint === 'object' ? endpoint.id : endpoint;
}}

function syncShellHeight() {{
  const shellTop = vizShellEl.getBoundingClientRect().top;
  const footerHeight = footerEl ? footerEl.getBoundingClientRect().height : 0;
  const availableHeight = Math.max(420, Math.floor(window.innerHeight - shellTop - footerHeight));
  vizShellEl.style.height = availableHeight + 'px';
  return {{
    width: vizShellEl.clientWidth || window.innerWidth,
    height: vizShellEl.clientHeight || availableHeight,
  }};
}}

function ringRadius(generation, width, height) {{
  const radii = [0, 180, 320, 460, 580];
  const normalizedGeneration = Math.max(0, Math.min(4, Number(generation) || 0));
  if (normalizedGeneration === 0) return 0;

  const viewportMin = Math.min(window.innerWidth || width, window.innerHeight || height);
  const scale = Math.min(1, viewportMin / 900);
  return radii[normalizedGeneration] * scale;
}}

function fitGraphToViewport(width, height) {{
  if (layoutMode === 'concentric') {{
    const rootNode = currentSimNodes.find(node => node.id === 'JM-ROOT');
    if (rootNode) {{
      const padding = 40;
      const maxDx = d3.max(currentSimNodes, node => Math.abs((node.x || 0) - rootNode.x) + nodeRadius(node) + 18) || 1;
      const maxDy = d3.max(currentSimNodes, node => Math.abs((node.y || 0) - rootNode.y) + nodeRadius(node) + 18) || 1;
      const scale = Math.min(
        (width - padding * 2) / (maxDx * 2),
        (height - padding * 2) / (maxDy * 2)
      );
      const targetCenterX = width / 2;
      const targetCenterY = window.innerWidth <= 900 ? height * 0.32 : height / 2;
      const tx = targetCenterX - scale * rootNode.x;
      const ty = targetCenterY - scale * rootNode.y;

      svg.transition()
        .duration(240)
        .ease(d3.easeCubicOut)
        .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
      return;
    }}
  }}

  const bbox = g.node().getBBox();
  if (!bbox.width || !bbox.height) return;

  const scale = Math.min(width / bbox.width, height / bbox.height) * 0.85;
  const tx = (width - scale * (bbox.x * 2 + bbox.width)) / 2;
  const ty = (height - scale * (bbox.y * 2 + bbox.height)) / 2;

  svg.transition()
    .duration(240)
    .ease(d3.easeCubicOut)
    .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}}

function applyLayoutForces(width, height) {{
  currentShellWidth = width;
  currentShellHeight = height;
  if (!simulation) return;

  const linkStrength = layoutMode === 'concentric' ? 0.1 : 0.5;
  const chargeStrength = layoutMode === 'concentric' ? -60 : -220;
  const collidePadding = layoutMode === 'concentric' ? 6 : 8;

  simulation
    .force('link', d3.forceLink(currentSimEdges).id(d => d.id).distance(80).strength(linkStrength))
    .force('charge', d3.forceManyBody().strength(chargeStrength))
    .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + collidePadding));

  if (layoutMode === 'concentric') {{
    simulation.force('center', null);
    simulation.force(
      'radial',
      d3.forceRadial(d => ringRadius(d.generation, width, height), width / 2, height / 2).strength(0.8)
    );
  }} else {{
    simulation.force('radial', null);
    simulation.force('center', d3.forceCenter(width / 2, height / 2));
  }}
}}

function render() {{
  const shellSize = syncShellHeight();
  const W = shellSize.width;
  const H = shellSize.height;

  const vids   = visibleNodeIds();
  if (selectedNodeId && !vids.has(selectedNodeId)) {{
    selectedNodeId = null;
  }}
  if (hoveredNodeId && !vids.has(hoveredNodeId)) {{
    hoveredNodeId = null;
    hideTooltip();
  }}
  const vNodes = NETWORK_NODES.filter(n => vids.has(n.id));
  const vEdges = visibleEdges(vids);

  // Build id->node index for simulation
  const nodeById = new Map(vNodes.map(n => [n.id, Object.assign({{}}, n)]));
  const simEdges = vEdges.map(e => ({{
    source: e.source, target: e.target,
    edge_type: e.edge_type, confidence: e.confidence,
  }}));
  const simNodes = Array.from(nodeById.values());

  currentNeighborIds = buildNeighborIds(vEdges);
  currentAlwaysVisibleLabelIds = new Set(
    simNodes.filter(d => Number(d.generation) === 0).map(d => d.id)
  );
  currentSimNodes = simNodes;
  currentSimEdges = simEdges;

  // Update stats
  document.getElementById('stat-nodes').textContent = simNodes.length;
  document.getElementById('stat-edges').textContent = simEdges.length;

  // Stop previous simulation
  if (simulation) simulation.stop();

  simulation = d3.forceSimulation(simNodes)
    .alphaDecay(0.03);
  applyLayoutForces(W, H);

  // ── links ──────────────────────────────────────────────────────────────
  const link = linkG.selectAll('line')
    .data(simEdges, e => e.source + '->' + e.target)
    .join('line')
      .attr('class', e => 'link' + (e.edge_type === 'q12a' ? ' q12a' : ''))
      .attr('marker-end', 'url(#arrow)');
  currentLinkSelection = link;

  // ── nodes ──────────────────────────────────────────────────────────────
  const node = nodeG.selectAll('g.node')
    .data(simNodes, d => d.id)
    .join(
      enter => {{
        const ng = enter.append('g').attr('class', 'node');
        ng.append('circle');
        ng.append('text').attr('dy', '0.35em').attr('x', d => nodeRadius(d) + 4);
        ng.call(d3.drag()
          .on('start', dragstarted)
          .on('drag',  dragged)
          .on('end',   dragended));
        ng.on('click', (event, d) => {{
            if (event.defaultPrevented) return;
            selectNode(d.id);
          }})
          .on('mouseenter', handleNodeEnter)
          .on('mousemove', handleNodeMove)
          .on('mouseleave', handleNodeLeave);
        return ng;
      }}
    );
  currentNodeSelection = node;

  node.select('circle')
    .attr('r', nodeRadius)
    .attr('fill', nodeColor)
    .attr('stroke', d => d3.color(nodeColor(d)).brighter(0.4));

  node.select('text')
    .attr('x', d => nodeRadius(d) + 4)
    .text(d => d.label);

  updateGraphState();
  renderPersonPanel();

  simulation.on('tick', () => {{
    link
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);
    node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
    updateLabelVisibility();
  }});

  // Fit to viewport after initial settle
  simulation.on('end', () => {{
    fitGraphToViewport(W, H);
  }});
}}

function matchesSearch(d, q) {{
  return d.label.toLowerCase().includes(q)
      || (d.institution || '').toLowerCase().includes(q)
      || (d.employer || '').toLowerCase().includes(q)
      || (d.country || '').toLowerCase().includes(q)
      || (d.us_state || '').toLowerCase().includes(q);
}}

function updateLabelVisibility() {{
  if (!currentNodeSelection) return;

  if (showLabels) {{
    currentNodeSelection.select('text').style('display', null);
    return;
  }}

  const visibleLabelIds = new Set(currentAlwaysVisibleLabelIds);
  [hoveredNodeId, selectedNodeId].filter(Boolean).forEach(nodeId => {{
    visibleLabelIds.add(nodeId);
    (currentNeighborIds.get(nodeId) || []).forEach(relatedNodeId => visibleLabelIds.add(relatedNodeId));
  }});

  currentNodeSelection.select('text')
    .style('display', d => visibleLabelIds.has(d.id) ? null : 'none');
}}

function updateGraphState() {{
  if (!currentNodeSelection) return;

  const q = searchTerm.trim().toLowerCase();
  const focusedNodeIds = new Set([hoveredNodeId, selectedNodeId].filter(Boolean));

  currentNodeSelection.each(function(d) {{
    const match = q ? matchesSearch(d, q) : false;
    d3.select(this)
      .classed('highlighted', q ? match : false)
      .classed('dimmed', q ? !match : false)
      .classed('selected', d.id === selectedNodeId);
  }});

  if (currentLinkSelection) {{
    currentLinkSelection.classed('highlighted', d => {{
      if (!focusedNodeIds.size) return false;
      const sourceId = edgeEndpointId(d.source);
      const targetId = edgeEndpointId(d.target);
      return focusedNodeIds.has(sourceId) || focusedNodeIds.has(targetId);
    }});
  }}

  updateLabelVisibility();
}}

function selectNode(nodeId) {{
  selectedNodeId = nodeId;
  updateGraphState();
  renderPersonPanel();
}}

function clearSelection() {{
  selectedNodeId = null;
  updateGraphState();
  renderPersonPanel();
}}

function formatGeneration(generation) {{
  if (generation === null || generation === undefined) return '';
  if (generation === 0) return 'Generation 0 (root)';
  return 'Generation ' + generation;
}}

function displayValue(value, fallback = '') {{
  return value && String(value).trim() ? String(value).trim() : fallback;
}}

function formatPersonSubtitle(node) {{
  const summary = displayValue(node.employer) || displayValue(node.institution);
  const location = [displayValue(node.us_state), displayValue(node.country)].filter(Boolean).join(', ');
  const parts = [summary, location].filter(Boolean);
  if (parts.length) return parts.join(' • ');
  return formatGeneration(node.generation) || 'No additional details available.';
}}

function relatedNodes(map, nodeId) {{
  return Array
    .from(map.get(nodeId) || [])
    .map(id => NODE_BY_ID.get(id))
    .filter(Boolean)
    .sort((a, b) => a.label.localeCompare(b.label));
}}

function buildDetailItem(label, value) {{
  const item = document.createElement('div');
  item.className = 'detail-item';

  const labelEl = document.createElement('div');
  labelEl.className = 'detail-label';
  labelEl.textContent = label;

  const valueEl = document.createElement('div');
  valueEl.className = 'detail-value';
  valueEl.textContent = displayValue(value);

  item.appendChild(labelEl);
  item.appendChild(valueEl);
  return item;
}}

function buildRelationshipSection(title, people) {{
  const section = document.createElement('section');
  section.className = 'panel-section';

  const heading = document.createElement('h3');
  heading.textContent = title + ' (' + people.length + ')';
  section.appendChild(heading);

  if (!people.length) {{
    const empty = document.createElement('div');
    empty.className = 'relationship-empty';
    empty.textContent = 'None listed';
    section.appendChild(empty);
    return section;
  }}

  const list = document.createElement('div');
  list.className = 'relationship-list';

  people.forEach(person => {{
    const item = document.createElement('div');
    item.className = 'relationship-item';
    item.textContent = person.label;
    list.appendChild(item);
  }});

  section.appendChild(list);
  return section;
}}

function renderPersonPanel() {{
  const node = selectedNodeId ? NODE_BY_ID.get(selectedNodeId) : null;
  panelContentEl.replaceChildren();
  panelEl.classList.toggle('is-open', Boolean(node));

  if (!node) {{
    panelTitleEl.textContent = 'Select a person';
    panelSubtitleEl.textContent = 'Click a node to inspect the latest details and direct relationships.';
    panelEmptyEl.hidden = false;
    panelContentEl.hidden = true;
    panelCloseEl.disabled = true;
    return;
  }}

  panelTitleEl.textContent = node.label;
  panelSubtitleEl.textContent = formatPersonSubtitle(node);
  panelEmptyEl.hidden = true;
  panelContentEl.hidden = false;
  panelCloseEl.disabled = false;

  const detailGrid = document.createElement('section');
  detailGrid.className = 'detail-grid';
  [
    ['Generation', formatGeneration(node.generation)],
    ['PhD institution', node.institution],
    ['PhD year', node.phd_year],
    ['Current employer', node.employer],
    ['Country', node.country],
    ['US state', node.us_state],
  ].forEach(([label, value]) => {{
    if (!displayValue(value)) return;
    detailGrid.appendChild(buildDetailItem(label, value));
  }});

  if (detailGrid.childElementCount) {{
    panelContentEl.appendChild(detailGrid);
  }}
  panelContentEl.appendChild(
    buildRelationshipSection('Direct advisors', relatedNodes(RELATIONSHIPS.advisorsByNode, node.id))
  );
  panelContentEl.appendChild(
    buildRelationshipSection('Direct students', relatedNodes(RELATIONSHIPS.studentsByNode, node.id))
  );
}}

// ── tooltip (textContent only — no innerHTML) ──────────────────────────────
const tooltipEl = document.getElementById('tooltip');

function showTooltip(event, d) {{
  tooltipEl.innerHTML = '';  // clear

  const lines = [d.label];
  const generationText = formatGeneration(d.generation);
  if (generationText) lines.push(generationText);
  if (d.institution) lines.push('PhD: ' + d.institution + (d.phd_year ? ' (' + d.phd_year + ')' : ''));
  if (d.employer)    lines.push('At: ' + d.employer);
  if (d.country)     lines.push(d.country);

  lines.forEach((line, i) => {{
    const div = document.createElement('div');
    div.textContent = line;
    if (i === 0) div.style.fontWeight = 'bold';
    tooltipEl.appendChild(div);
  }});

  tooltipEl.style.display = 'block';
  _moveTooltip(event);
}}

function handleNodeEnter(event, d) {{
  hoveredNodeId = d.id;
  showTooltip(event, d);
  updateGraphState();
}}

function handleNodeMove(event) {{
  _moveTooltip(event);
}}

function _moveTooltip(event) {{
  const x = event.clientX + 14;
  const y = event.clientY - 10;
  const w = tooltipEl.offsetWidth;
  const vw = window.innerWidth;
  tooltipEl.style.left = (x + w > vw ? x - w - 28 : x) + 'px';
  tooltipEl.style.top  = y + 'px';
}}

function hideTooltip() {{
  tooltipEl.style.display = 'none';
}}

function handleNodeLeave() {{
  hoveredNodeId = null;
  hideTooltip();
  updateGraphState();
}}

svg.on('mousemove', (event) => {{
  if (tooltipEl.style.display !== 'none') _moveTooltip(event);
}});

// ── drag handlers ──────────────────────────────────────────────────────────
function dragstarted(event, d) {{
  if (!event.active) simulation.alphaTarget(0.3).restart();
  d.fx = d.x; d.fy = d.y;
}}
function dragged(event, d) {{ d.fx = event.x; d.fy = event.y; }}
function dragended(event, d) {{
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null; d.fy = null;
}}

function syncControlPills() {{
  controlPillInputs.forEach(input => {{
    const pill = input.closest('.privacy-pill');
    if (pill) pill.classList.toggle('active', input.checked);
  }});

  if (layoutToggleEl) {{
    layoutToggleEl.setAttribute(
      'aria-label',
      layoutToggleEl.checked
        ? 'Concentric layout active. Press Enter to switch to force layout.'
        : 'Force layout active. Press Enter to switch to concentric layout.'
    );
  }}
}}

// ── controls ───────────────────────────────────────────────────────────────
document.getElementById('showLabels').addEventListener('change', e => {{
  syncControlPills();
  showLabels = e.target.checked;
  updateLabelVisibility();
}});
layoutToggleEl.addEventListener('change', e => {{
  syncControlPills();
  layoutMode = e.target.checked ? 'concentric' : 'force';
  applyLayoutForces(currentShellWidth || vizShellEl.clientWidth || window.innerWidth, currentShellHeight || vizShellEl.clientHeight || window.innerHeight);
  if (simulation) simulation.alpha(1).restart();
}});
document.getElementById('search').addEventListener('input', e => {{
  searchTerm = e.target.value;
  updateGraphState();
}});
controlPillInputs.forEach(input => {{
  input.addEventListener('keydown', event => {{
    if (event.key !== 'Enter') return;
    event.preventDefault();
    event.currentTarget.click();
  }});
}});
panelCloseEl.addEventListener('click', clearSelection);
window.addEventListener('keydown', event => {{
  if (event.key === 'Escape') clearSelection();
}});

window.addEventListener('resize', render);

// ── initial render ─────────────────────────────────────────────────────────
syncControlPills();
render();
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate self-contained Mokyr genealogy HTML visualization"
    )
    parser.add_argument('--date', default=None,
                        help="Date suffix matching network CSV filenames (MMDDYY, defaults to latest common node/edge date)")
    parser.add_argument('--output', default=None,
                        help="Output HTML path (default: Output/mokyr-genealogy-{date}.html)")
    parser.add_argument('--d3-path', default=None,
                        help="Local path to d3.min.js (skips CDN fetch; still verifies SHA-256)")
    parser.add_argument('--nodes', default=None,
                        help="Override path to Network_Nodes CSV")
    parser.add_argument('--edges', default=None,
                        help="Override path to Network_Edges CSV")
    args = parser.parse_args()

    date = _resolve_viz_date(args.date, args.nodes, args.edges)
    nodes_csv  = PROJECT_ROOT / (args.nodes or f"Data/Derived/Network_Nodes_{date}.csv")
    edges_csv  = PROJECT_ROOT / (args.edges or f"Data/Derived/Network_Edges_{date}.csv")
    output_path = PROJECT_ROOT / (args.output or f"Output/mokyr-genealogy-{date}.html")

    for p in (nodes_csv, edges_csv):
        if not p.exists():
            sys.exit(f"ERROR: Input file not found: {p}\nRun build_network.py first.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load data
    print(f"Loading nodes : {nodes_csv}")
    nodes = _load_nodes(nodes_csv)
    print(f"Loading edges : {edges_csv}")
    edges = _load_edges(edges_csv)
    print(f"  {len(nodes)} nodes, {len(edges)} edges")

    # Verify no emails in output data
    for n in nodes:
        assert 'email' not in n, "BUG: email field present in node output"

    # Fetch/load D3
    d3_js, actual_hash = _fetch_d3(args.d3_path)
    print(f"D3 loaded (SHA-256: {actual_hash})")

    # Build and write HTML
    html = _build_html(nodes, edges, d3_js)
    output_path.write_text(html, encoding='utf-8')
    print(f"\nOutput: {output_path}")
    print("Open in browser to view the genealogy network.")

    # Verify no email addresses appear in HTML source
    import re as _re
    email_pattern = _re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    matches = email_pattern.findall(html)
    if matches:
        print(f"WARNING: Possible email address(es) in HTML output: {matches[:5]}")
    else:
        print("Verified: no email addresses in HTML output.")


if __name__ == '__main__':
    main()
