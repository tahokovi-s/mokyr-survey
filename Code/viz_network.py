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
from pathlib import Path
try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    urlopen = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATE = "022226"

D3_URL    = "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"
# SHA-256 of d3.min.js v7.9.0 from cdnjs.  Verified against CDN on first run.
# If this hash is empty the script will print the actual hash and ask you to pin it.
D3_SHA256 = "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; overflow: hidden; }}

  #controls {{
    position: absolute; top: 12px; left: 12px; z-index: 10;
    background: rgba(0,0,0,0.6); border-radius: 8px; padding: 12px 16px;
    display: flex; flex-direction: column; gap: 8px; min-width: 220px;
  }}
  #controls h2 {{ font-size: 14px; color: #ccc; margin-bottom: 4px; }}
  #controls label {{ font-size: 13px; cursor: pointer; display: flex; align-items: center; gap: 6px; }}
  #controls input[type=checkbox] {{ width: 15px; height: 15px; cursor: pointer; }}
  #search {{
    padding: 5px 8px; border-radius: 5px; border: 1px solid #555;
    background: #2a2a3e; color: #eee; font-size: 13px; width: 100%;
  }}
  #search::placeholder {{ color: #888; }}

  #legend {{
    position: absolute; bottom: 16px; left: 12px; z-index: 10;
    background: rgba(0,0,0,0.6); border-radius: 8px; padding: 10px 14px;
    font-size: 12px;
  }}
  #legend h3 {{ font-size: 12px; color: #aaa; margin-bottom: 6px; }}
  .legend-item {{ display: flex; align-items: center; gap: 7px; margin-bottom: 4px; }}
  .legend-dot {{ width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; }}
  .legend-dot.dashed {{ background: transparent !important; border: 2px dashed #aaa; }}

  #tooltip {{
    position: absolute; pointer-events: none; z-index: 20;
    background: rgba(0,0,0,0.85); color: #eee;
    padding: 8px 12px; border-radius: 6px; font-size: 13px;
    max-width: 280px; line-height: 1.5;
    display: none;
  }}

  #stats {{
    position: absolute; top: 12px; right: 12px; z-index: 10;
    background: rgba(0,0,0,0.5); border-radius: 8px;
    padding: 8px 14px; font-size: 12px; color: #aaa;
  }}

  svg {{ width: 100vw; height: 100vh; display: block; }}
  .link {{ stroke: #888; stroke-opacity: 0.45; fill: none; }}
  .link.q12a {{ stroke-dasharray: 4 3; stroke-opacity: 0.3; }}
  .node circle {{ stroke-width: 1.5px; cursor: pointer; }}
  .node circle.q12a-only {{ stroke-dasharray: 4 2; }}
  .node.hidden {{ display: none; }}
  .node.dimmed circle {{ opacity: 0.2; }}
  .node.dimmed text {{ opacity: 0.15; }}
  .node text {{
    font-size: 10px; fill: #ddd; pointer-events: none;
    paint-order: stroke; stroke: #1a1a2e; stroke-width: 3px;
  }}
  .highlighted circle {{ stroke: #fff !important; stroke-width: 2.5px !important; }}
</style>
</head>
<body>

<div id="controls">
  <h2>Mokyr Genealogy Network</h2>
  <input id="search" type="text" placeholder="Search by name…">
  <label>
    <input type="checkbox" id="showQ12a"> Show uncontacted students
  </label>
  <label>
    <input type="checkbox" id="showLabels" checked> Show name labels
  </label>
  <label>
    <input type="checkbox" id="showMedium" checked> Show medium-confidence edges
  </label>
</div>

<div id="legend">
  <h3>Generation</h3>
  <div class="legend-item"><div class="legend-dot" style="background:#f5c518"></div> Gen 0 — Joel Mokyr (root)</div>
  <div class="legend-item"><div class="legend-dot" style="background:#4a9eff"></div> Gen 1 — Direct students</div>
  <div class="legend-item"><div class="legend-dot" style="background:#50c878"></div> Gen 2</div>
  <div class="legend-item"><div class="legend-dot" style="background:#ff8c42"></div> Gen 3</div>
  <div class="legend-item"><div class="legend-dot" style="background:#aaa"></div> Gen 4+ or unknown</div>
  <div class="legend-item"><div class="legend-dot dashed"></div> Uncontacted student</div>
</div>

<div id="stats">
  <span id="stat-nodes"></span> nodes &nbsp;·&nbsp;
  <span id="stat-edges"></span> edges
</div>

<div id="tooltip"></div>
<svg id="graph"></svg>

<script>
// ── inline D3 ──────────────────────────────────────────────────────────────
{d3_js}
// ── data ───────────────────────────────────────────────────────────────────
const RAW_NODES = {nodes_json};
const RAW_EDGES = {edges_json};
// ──────────────────────────────────────────────────────────────────────────

const GEN_COLOR = {{
  0: '#f5c518',
  1: '#4a9eff',
  2: '#50c878',
  3: '#ff8c42',
}};
function nodeColor(d) {{
  if (d.generation === null || d.generation === undefined) return '#888';
  return GEN_COLOR[d.generation] || '#aaa';
}}
function nodeRadius(d) {{
  if (d.id === 'JM-ROOT') return 18;
  if (d.has_students) return 10;
  return 6;
}}

// ── state ──────────────────────────────────────────────────────────────────
let showQ12a    = false;
let showLabels  = true;
let showMedium  = true;
let searchTerm  = '';

// ── build visible sets ─────────────────────────────────────────────────────
function visibleNodeIds() {{
  return new Set(
    RAW_NODES
      .filter(n => showQ12a || n.is_respondent || n.id === 'JM-ROOT')
      .map(n => n.id)
  );
}}
function visibleEdges(vids) {{
  return RAW_EDGES.filter(e => {{
    if (!vids.has(e.source) || !vids.has(e.target)) return false;
    if (!showMedium && e.confidence === 'medium') return false;
    return true;
  }});
}}

// ── D3 setup ───────────────────────────────────────────────────────────────
const svg = d3.select('#graph');
const g   = svg.append('g');

// Arrowhead marker
svg.append('defs').append('marker')
  .attr('id', 'arrow')
  .attr('viewBox', '0 -5 10 10')
  .attr('refX', 20).attr('refY', 0)
  .attr('markerWidth', 6).attr('markerHeight', 6)
  .attr('orient', 'auto')
  .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#888');

// Zoom + pan
const zoom = d3.zoom()
  .scaleExtent([0.05, 4])
  .on('zoom', (event) => {{ g.attr('transform', event.transform); }});
svg.call(zoom);

const linkG = g.append('g').attr('class', 'links');
const nodeG = g.append('g').attr('class', 'nodes');

let simulation;

function render() {{
  const W = window.innerWidth;
  const H = window.innerHeight;

  const vids   = visibleNodeIds();
  const vNodes = RAW_NODES.filter(n => vids.has(n.id));
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
        ng.on('mousemove', showTooltip)
          .on('mouseleave', hideTooltip);
        return ng;
      }}
    );

  node.select('circle')
    .attr('r', nodeRadius)
    .attr('fill', nodeColor)
    .attr('stroke', d => d3.color(nodeColor(d)).brighter(0.4))
    .classed('q12a-only', d => !d.is_respondent && d.id !== 'JM-ROOT');

  node.select('text')
    .attr('x', d => nodeRadius(d) + 4)
    .text(d => d.label)
    .style('display', showLabels ? null : 'none');

  applySearch(node);

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

function applySearch(node) {{
  const q = searchTerm.trim().toLowerCase();
  if (!q) {{
    node.classed('highlighted', false).classed('dimmed', false);
    return;
  }}
  node.each(function(d) {{
    const match = d.label.toLowerCase().includes(q)
                || (d.institution || '').toLowerCase().includes(q)
                || (d.employer || '').toLowerCase().includes(q);
    d3.select(this).classed('highlighted', match).classed('dimmed', !match);
  }});
}}

// ── tooltip (textContent only — no innerHTML) ──────────────────────────────
const tooltipEl = document.getElementById('tooltip');

function showTooltip(event, d) {{
  tooltipEl.innerHTML = '';  // clear

  const lines = [
    d.label,
    d.generation !== null && d.generation !== undefined
      ? 'Generation: ' + d.generation : 'Generation: unknown',
  ];
  if (d.institution) lines.push('PhD: ' + d.institution + (d.phd_year ? ' (' + d.phd_year + ')' : ''));
  if (d.employer)    lines.push('At: ' + d.employer);
  if (d.country)     lines.push(d.country);
  if (!d.is_respondent && d.id !== 'JM-ROOT') lines.push('[uncontacted student]');

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
document.getElementById('showQ12a').addEventListener('change', e => {{
  showQ12a = e.target.checked; render();
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
  applySearch(nodeG.selectAll('g.node'));
}});

window.addEventListener('resize', render);

// ── initial render ─────────────────────────────────────────────────────────
render();
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate self-contained Mokyr genealogy HTML visualization"
    )
    parser.add_argument('--date', default=DEFAULT_DATE,
                        help="Date suffix matching network CSV filenames (MMDDYY)")
    parser.add_argument('--output', default=None,
                        help="Output HTML path (default: Output/mokyr-genealogy-{date}.html)")
    parser.add_argument('--d3-path', default=None,
                        help="Local path to d3.min.js (skips CDN fetch; still verifies SHA-256)")
    parser.add_argument('--nodes', default=None,
                        help="Override path to Network_Nodes CSV")
    parser.add_argument('--edges', default=None,
                        help="Override path to Network_Edges CSV")
    args = parser.parse_args()

    date = args.date
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
