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
    overflow: hidden;
  }}
  a {{ color: inherit; text-decoration: none; }}

  .site-header,
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
    border-radius: 50%;
    border: 1px solid rgba(16, 18, 22, 0.12);
    background: var(--accent);
    box-shadow: 0 8px 20px rgba(17, 19, 24, 0.12);
    color: #fbfbf8;
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    font-size: 1rem;
    font-weight: 600;
    line-height: 1;
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
    transition: border-color 180ms ease, transform 180ms ease, color 180ms ease;
  }}
  .back-link:hover {{
    color: var(--text);
    border-color: var(--line-strong);
    transform: translateY(-1px);
  }}

  #viz-shell {{
    position: relative;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }}

  #controls {{
    position: absolute; top: 12px; left: 12px; z-index: 10;
    display: flex; flex-direction: column; align-items: flex-start;
  }}
  #controls label {{
    font-size: 13px;
    line-height: 1.45;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text);
  }}
  #controls input[type=checkbox] {{
    width: 15px;
    height: 15px;
    cursor: pointer;
    accent-color: var(--accent-deep);
  }}
  #settings-trigger {{
    width: 40px;
    height: 40px;
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 0;
    background: #ffffff;
    color: var(--text);
    font-size: 20px;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: var(--card-shadow);
    transition: border-color 180ms ease, background 180ms ease, color 180ms ease;
  }}
  #settings-trigger.active {{
    background: rgba(214, 188, 123, 0.16);
    border-color: rgba(214, 188, 123, 0.42);
    color: var(--accent-deep);
  }}
  #settings-panel {{
    position: absolute;
    top: 50px;
    left: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 250px;
    padding: 12px 14px 14px;
    background: #ffffff;
    border: 1px solid var(--line);
    border-radius: var(--radius-lg);
    box-shadow: var(--card-shadow);
  }}
  #settings-panel[hidden] {{ display: none; }}
  .settings-title {{
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: rgba(16, 18, 22, 0.46);
    margin-bottom: 2px;
  }}
  #search {{
    padding: 8px 10px;
    border-radius: 12px;
    border: 1px solid var(--line);
    background: var(--bg);
    color: var(--text);
    font-size: 13px;
    width: 100%;
  }}
  #search::placeholder {{ color: var(--soft); }}

  #legend {{
    position: absolute; bottom: 16px; left: 12px; z-index: 10;
    background: #ffffff;
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    box-shadow: var(--card-shadow);
    padding: 10px 14px;
    font-size: 12px;
    max-width: min(280px, calc(100vw - 24px));
  }}
  #legend h3 {{
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 6px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 7px; margin-bottom: 4px; }}
  .legend-item:last-child {{ margin-bottom: 0; }}
  .legend-dot {{ width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; }}

  #tooltip {{
    position: absolute; pointer-events: none; z-index: 20;
    background: #ffffff;
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: var(--radius-lg);
    box-shadow: var(--card-shadow);
    padding: 8px 12px; font-size: 13px;
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
    border-radius: var(--radius-lg);
    box-shadow: var(--card-shadow);
    display: flex; flex-direction: column; gap: 16px;
    padding: 16px;
    overflow: hidden;
  }}
  .panel-header {{
    display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  }}
  .panel-eyebrow {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em;
    color: rgba(16, 18, 22, 0.46); margin-bottom: 6px;
  }}
  #person-title {{
    font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    font-size: 24px; line-height: 1.1; color: var(--text); font-weight: 400;
  }}
  #person-subtitle {{
    margin-top: 6px; font-size: 13px; color: var(--muted);
  }}
  #panel-close {{
    border: 1px solid var(--line); border-radius: 999px;
    padding: 8px 12px;
    background: #ffffff;
    color: var(--muted); font-size: 12px; cursor: pointer;
    transition: border-color 180ms ease, color 180ms ease;
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
    display: flex; flex-direction: column; gap: 16px;
    padding-right: 4px;
  }}
  .detail-grid {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }}
  .detail-item {{
    background: var(--bg);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 10px 12px;
    min-height: 72px;
  }}
  .detail-label {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin-bottom: 8px;
  }}
  .detail-value {{
    font-size: 14px; line-height: 1.4; color: var(--text); font-weight: 600;
    word-break: break-word;
  }}
  .panel-section {{
    display: flex; flex-direction: column; gap: 10px;
  }}
  .panel-section h3 {{
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted);
  }}
  .relationship-list {{
    display: flex; flex-direction: column; gap: 8px;
  }}
  .relationship-item {{
    background: var(--bg);
    border: 1px solid var(--line);
    border-radius: 12px;
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
  .link {{ stroke: rgba(16, 18, 22, 0.12); stroke-opacity: 1; fill: none; }}
  /* 0.6 compensates for base .link alpha drop to 0.12; preserves medium/high-confidence distinction. */
  .link.q12a {{ stroke-dasharray: 4 3; stroke-opacity: 0.6; }}
  .node circle {{ stroke-width: 1.5px; cursor: pointer; }}
  .node.hidden {{ display: none; }}
  .node.dimmed circle {{ opacity: 0.2; }}
  .node.dimmed text {{ opacity: 0.15; }}
  .node text {{
    font-family: "Neue Haas Grotesk Text Pro", "Avenir Next", "Helvetica Neue", sans-serif;
    font-size: 11px; fill: var(--text); pointer-events: none;
    paint-order: stroke; stroke: #fbfbf8; stroke-width: 3px;
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
    }}
  }}

  @media (max-width: 760px) {{
    .site-header,
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
    #settings-panel {{
      min-width: min(250px, calc(100vw - 24px));
    }}
    #person-panel {{
      max-height: 52vh;
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

<main id="viz-shell">
  <div id="controls">
    <button id="settings-trigger" type="button" aria-expanded="false" aria-controls="settings-panel" aria-label="Settings">&#9881;</button>
    <div id="settings-panel" hidden>
      <div class="settings-title">Settings</div>
      <input id="search" type="text" placeholder="Search by name…">
      <label>
        <input type="checkbox" id="showMokyrDirect"> Show only Mokyr direct links
      </label>
      <label>
        <input type="checkbox" id="showLabels" checked> Show name labels
      </label>
      <label>
        <input type="checkbox" id="showMedium"> Show medium-confidence links
      </label>
    </div>
  </div>

  <div id="legend">
    <h3>Generation</h3>
    <div class="legend-item"><div class="legend-dot" style="background:#d6bc7b"></div> Gen 0 — Joel Mokyr (root)</div>
    <div class="legend-item"><div class="legend-dot" style="background:#1f242d"></div> Gen 1 — Direct students</div>
    <div class="legend-item"><div class="legend-dot" style="background:#4a5161"></div> Gen 2</div>
    <div class="legend-item"><div class="legend-dot" style="background:#8a92a3"></div> Gen 3</div>
    <div class="legend-item"><div class="legend-dot" style="background:#c9ced8"></div> Gen 4+</div>
  </div>

  <div id="stats">
    <span id="stat-nodes"></span> nodes &nbsp;·&nbsp;
    <span id="stat-edges"></span> edges
  </div>

  <aside id="person-panel" aria-live="polite">
    <div class="panel-header">
      <div>
        <div class="panel-eyebrow">Person Details</div>
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
  <p class="footer-credit">For Joel's 80th. Survey led by Ran Abramitzky.</p>
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
const MOKYR_DIRECT_IDS = new Set(
  ['JM-ROOT', ...NETWORK_EDGES.filter(edge => edge.source === 'JM-ROOT').map(edge => edge.target)]
);

function buildRelationshipMaps(edges) {{
  const advisorsByNode = new Map();
  const studentsByNode = new Map();

  function ensureSet(map, key) {{
    if (!map.has(key)) map.set(key, new Set());
    return map.get(key);
  }}

  edges.forEach(edge => {{
    ensureSet(studentsByNode, edge.source).add(edge.target);
    ensureSet(advisorsByNode, edge.target).add(edge.source);
  }});

  return {{ advisorsByNode, studentsByNode }};
}}

const RELATIONSHIPS = buildRelationshipMaps(NETWORK_EDGES);

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
let showMokyrDirect = false;
let showLabels  = true;
let showMedium  = false;
let showSettings = false;
let searchTerm  = '';
let selectedNodeId = null;

// ── build visible sets ─────────────────────────────────────────────────────
function visibleNodeIds() {{
  let visibleNodes = NETWORK_NODES.filter(n => (
    n.id === 'JM-ROOT' || n.is_respondent || n.show_nonrespondent
  ));

  if (showMokyrDirect) {{
    visibleNodes = visibleNodes.filter(n => MOKYR_DIRECT_IDS.has(n.id));
  }}

  return new Set(visibleNodes.map(n => n.id));
}}
function visibleEdges(vids) {{
  return NETWORK_EDGES.filter(e => {{
    if (!vids.has(e.source) || !vids.has(e.target)) return false;
    if (!showMedium && e.confidence === 'medium') return false;
    return true;
  }});
}}

// ── D3 setup ───────────────────────────────────────────────────────────────
const svg = d3.select('#graph');
const g   = svg.append('g');
const vizShellEl = document.getElementById('viz-shell');
const panelTitleEl = document.getElementById('person-title');
const panelSubtitleEl = document.getElementById('person-subtitle');
const panelEmptyEl = document.getElementById('person-empty');
const panelContentEl = document.getElementById('person-content');
const panelCloseEl = document.getElementById('panel-close');
const settingsTriggerEl = document.getElementById('settings-trigger');
const settingsPanelEl = document.getElementById('settings-panel');

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

let simulation;

function render() {{
  const W = vizShellEl.clientWidth || window.innerWidth;
  const H = vizShellEl.clientHeight || window.innerHeight;

  const vids   = visibleNodeIds();
  if (selectedNodeId && !vids.has(selectedNodeId)) {{
    selectedNodeId = null;
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

  // Update stats
  document.getElementById('stat-nodes').textContent = simNodes.length;
  document.getElementById('stat-edges').textContent = simEdges.length;

  // Stop previous simulation
  if (simulation) simulation.stop();

  simulation = d3.forceSimulation(simNodes)
    .force('link', d3.forceLink(simEdges).id(d => d.id).distance(80).strength(0.5))
    .force('charge', d3.forceManyBody().strength(-220))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + 8))
    .alphaDecay(0.03);

  // ── links ──────────────────────────────────────────────────────────────
  const link = linkG.selectAll('line')
    .data(simEdges, e => e.source + '->' + e.target)
    .join('line')
      .attr('class', e => 'link' + (e.edge_type === 'q12a' ? ' q12a' : ''))
      .attr('marker-end', 'url(#arrow)');

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
          .on('mousemove', showTooltip)
          .on('mouseleave', hideTooltip);
        return ng;
      }}
    );

  node.select('circle')
    .attr('r', nodeRadius)
    .attr('fill', nodeColor)
    .attr('stroke', d => d3.color(nodeColor(d)).brighter(0.4));

  node.select('text')
    .attr('x', d => nodeRadius(d) + 4)
    .text(d => d.label)
    .style('display', showLabels ? null : 'none');

  updateNodeStyles(node);
  renderPersonPanel();

  simulation.on('tick', () => {{
    link
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);
    node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
  }});

  // Fit to viewport after initial settle
  simulation.on('end', () => {{
    const bbox = g.node().getBBox();
    if (!bbox.width) return;
    const scale  = Math.min(W / bbox.width, H / bbox.height) * 0.85;
    const tx = (W - scale * (bbox.x * 2 + bbox.width))  / 2;
    const ty = (H - scale * (bbox.y * 2 + bbox.height)) / 2;
    svg.transition().duration(600)
       .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }});
}}

function matchesSearch(d, q) {{
  return d.label.toLowerCase().includes(q)
      || (d.institution || '').toLowerCase().includes(q)
      || (d.employer || '').toLowerCase().includes(q)
      || (d.country || '').toLowerCase().includes(q)
      || (d.us_state || '').toLowerCase().includes(q);
}}

function updateNodeStyles(node) {{
  const q = searchTerm.trim().toLowerCase();
  node.each(function(d) {{
    const match = q ? matchesSearch(d, q) : false;
    d3.select(this)
      .classed('highlighted', q ? match : false)
      .classed('dimmed', q ? !match : false)
      .classed('selected', d.id === selectedNodeId);
  }});
}}

function selectNode(nodeId) {{
  selectedNodeId = nodeId;
  updateNodeStyles(nodeG.selectAll('g.node'));
  renderPersonPanel();
}}

function clearSelection() {{
  selectedNodeId = null;
  updateNodeStyles(nodeG.selectAll('g.node'));
  renderPersonPanel();
}}

function renderSettingsPanel() {{
  settingsPanelEl.hidden = !showSettings;
  settingsTriggerEl.classList.toggle('active', showSettings);
  settingsTriggerEl.setAttribute('aria-expanded', showSettings ? 'true' : 'false');
}}

function formatGeneration(generation) {{
  if (generation === null || generation === undefined) return '';
  if (generation === 0) return 'Generation 0 (root)';
  return 'Generation ' + generation;
}}

function displayValue(value, fallback = '') {{
  return value && String(value).trim() ? String(value).trim() : fallback;
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

  if (!node) {{
    panelTitleEl.textContent = 'Select a person';
    panelSubtitleEl.textContent = 'Click a node to inspect the latest details and direct relationships.';
    panelEmptyEl.hidden = false;
    panelContentEl.hidden = true;
    panelCloseEl.disabled = true;
    return;
  }}

  panelTitleEl.textContent = node.label;
  panelSubtitleEl.textContent = formatGeneration(node.generation);
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

// ── controls ───────────────────────────────────────────────────────────────
settingsTriggerEl.addEventListener('click', () => {{
  showSettings = !showSettings;
  renderSettingsPanel();
}});
document.getElementById('showMokyrDirect').addEventListener('change', e => {{
  showMokyrDirect = e.target.checked; render();
}});
document.getElementById('showLabels').addEventListener('change', e => {{
  showLabels = e.target.checked;
  nodeG.selectAll('g.node text').style('display', showLabels ? null : 'none');
}});
document.getElementById('showMedium').addEventListener('change', e => {{
  showMedium = e.target.checked; render();
}});
document.getElementById('search').addEventListener('input', e => {{
  searchTerm = e.target.value;
  updateNodeStyles(nodeG.selectAll('g.node'));
}});
panelCloseEl.addEventListener('click', clearSelection);
window.addEventListener('keydown', event => {{
  if (event.key === 'Escape') clearSelection();
}});

window.addEventListener('resize', render);

// ── initial render ─────────────────────────────────────────────────────────
renderSettingsPanel();
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
