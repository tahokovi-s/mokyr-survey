#!/usr/bin/env python3
"""Generate mokyr-legacy-site/assets/genealogy-data.js from network CSVs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from genealogy_payload import (
    PROJECT_ROOT,
    assert_no_email_fields,
    load_edges,
    load_nodes,
    resolve_network_date,
    safe_json,
)


GENEALOGY_RUNTIME_JS = r"""
// GENEALOGY global
// Exposes a single GENEALOGY object built from the raw data above.
// All derived fields are computed once at load time.

const GENEALOGY = (() => {

  const ROOT_ID = 'JM-ROOT';

  const peopleById = {};
  for (const node of RAW_NODES) peopleById[node.id] = node;

  const _parentsRaw = {};
  const _childrenDedup = {};
  for (const e of RAW_EDGES) {
    if (!_parentsRaw[e.target]) _parentsRaw[e.target] = [];
    if (!_childrenDedup[e.source]) _childrenDedup[e.source] = [];
    _parentsRaw[e.target].push(e.source);
    if (!_childrenDedup[e.source].includes(e.target)) {
      _childrenDedup[e.source].push(e.target);
    }
  }
  const childrenById = _childrenDedup;

  function _selectPrimary(childId, parentIds) {
    const childGen = (peopleById[childId] || {}).generation ?? 99;
    const cands = parentIds.map(pid => ({
      id: pid,
      label: (peopleById[pid] || {}).label || pid,
      generation: (peopleById[pid] || {}).generation ?? 99,
      isRoot: pid === ROOT_ID,
    }));
    const rootCands = cands.filter(c => c.isRoot);
    const nonRootCands = cands.filter(c => !c.isRoot);
    let pool;
    if (rootCands.length && nonRootCands.length) {
      if (childGen === 1) return rootCands[0].id;
      pool = nonRootCands;
    } else {
      pool = cands;
    }
    const maxGen = Math.max(...pool.map(c => c.generation));
    const high = pool.filter(c => c.generation === maxGen);
    high.sort((a, b) => a.label.localeCompare(b.label));
    return high[0].id;
  }

  const primaryParentById = {};
  for (const node of RAW_NODES) {
    if (node.id === ROOT_ID) continue;
    const rawParents = _parentsRaw[node.id] || [];
    const dedup = [...new Set(rawParents)];
    if (dedup.length === 0) continue;
    primaryParentById[node.id] = dedup.length === 1 ? dedup[0] : _selectPrimary(node.id, dedup);
  }

  const descendantCountById = {};
  for (const node of RAW_NODES) {
    const visited = new Set();
    const stack = [node.id];
    while (stack.length) {
      const cur = stack.pop();
      const kids = childrenById[cur] || [];
      for (const kid of kids) {
        if (!visited.has(kid)) {
          visited.add(kid);
          stack.push(kid);
        }
      }
    }
    descendantCountById[node.id] = visited.size;
  }

  const lineageIds = new Set([ROOT_ID]);
  const lineageStack = [ROOT_ID];
  while (lineageStack.length) {
    const cur = lineageStack.pop();
    const kids = childrenById[cur] || [];
    for (const kid of kids) {
      if (!lineageIds.has(kid)) {
        lineageIds.add(kid);
        lineageStack.push(kid);
      }
    }
  }

  const generationCounts = {};
  for (const node of RAW_NODES) {
    if (node.id === ROOT_ID || !lineageIds.has(node.id)) continue;
    const generation = Number(node.generation) || 0;
    if (!generation) continue;
    generationCounts[generation] = (generationCounts[generation] || 0) + 1;
  }

  const lineageScholarCount = descendantCountById[ROOT_ID] || 0;
  const lineagePersonCount = lineageScholarCount + 1;
  const generationCount = Math.max(0, ...Object.keys(generationCounts).map(Number));
  const directStudentCount = (childrenById[ROOT_ID] || []).length;
  const stats = {
    scholarCount: lineageScholarCount,
    descendantCount: lineageScholarCount,
    personCount: lineagePersonCount,
    generationCount,
    directStudentCount,
    generation1Count: generationCounts[1] || 0,
    generation2Count: generationCounts[2] || 0,
    generation3Count: generationCounts[3] || 0,
    generation4Count: generationCounts[4] || 0,
    generationOneToThreeScholarCount:
      (generationCounts[1] || 0) + (generationCounts[2] || 0) + (generationCounts[3] || 0),
  };

  return {
    ROOT_ID,
    peopleById,
    childrenById,
    primaryParentById,
    descendantCountById,
    stats,
  };
})();

window.GENEALOGY = GENEALOGY;
"""


def _project_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def build_lineage_stats(nodes: list[dict], edges: list[dict]) -> dict:
    root_id = "JM-ROOT"
    node_ids = {node["id"] for node in nodes}
    children_by_id: dict[str, set[str]] = {}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if source not in node_ids or target not in node_ids:
            continue
        children_by_id.setdefault(source, set()).add(target)

    connected_ids = {root_id}
    stack = [root_id]
    while stack:
        current = stack.pop()
        for child_id in children_by_id.get(current, set()):
            if child_id in connected_ids:
                continue
            connected_ids.add(child_id)
            stack.append(child_id)

    node_by_id = {node["id"]: node for node in nodes}
    generation_values = []
    for node_id in connected_ids:
        if node_id == root_id:
            continue
        generation = node_by_id[node_id].get("generation")
        if isinstance(generation, int):
            generation_values.append(generation)

    generation_counts: dict[int, int] = {}
    for generation in generation_values:
        generation_counts[generation] = generation_counts.get(generation, 0) + 1

    scholar_count = max(0, len(connected_ids) - 1)
    return {
        "scholarCount": scholar_count,
        "descendantCount": scholar_count,
        "personCount": len(connected_ids),
        "generationCount": max(generation_values) if generation_values else 0,
        "directStudentCount": len(children_by_id.get(root_id, set()) & connected_ids),
        "generation1Count": generation_counts.get(1, 0),
        "generation2Count": generation_counts.get(2, 0),
        "generation3Count": generation_counts.get(3, 0),
        "generation4Count": generation_counts.get(4, 0),
        "generationOneToThreeScholarCount": sum(
            count for generation, count in generation_counts.items() if 1 <= generation <= 3
        ),
    }


def build_lineage_stats_asset(stats: dict, date_token: str) -> str:
    return (
        f"// lineage-stats.js - generated from Network_Nodes_{date_token}.csv "
        f"and Network_Edges_{date_token}.csv.\n"
        "// Provides one site-wide source of truth for public lineage counts.\n\n"
        f"window.LINEAGE_STATS = {safe_json(stats)};\n\n"
        "(function () {\n"
        "  const stats = window.LINEAGE_STATS || {};\n"
        "  const numberFormatter = new Intl.NumberFormat('en-US');\n"
        "\n"
        "  function formatValue(value) {\n"
        "    return typeof value === 'number' ? numberFormatter.format(value) : String(value || '');\n"
        "  }\n"
        "\n"
        "  function renderTemplate(template) {\n"
        "    return String(template || '').replace(/\\{([A-Za-z0-9_]+)\\}/g, function (_, key) {\n"
        "      return formatValue(stats[key]);\n"
        "    });\n"
        "  }\n"
        "\n"
        "  function hydrate(root) {\n"
        "    const scope = root || document;\n"
        "    scope.querySelectorAll('[data-lineage-stat]').forEach(function (element) {\n"
        "      const key = element.getAttribute('data-lineage-stat');\n"
        "      const value = stats[key];\n"
        "      if (value === undefined || value === null) return;\n"
        "      element.textContent = formatValue(value);\n"
        "      if (element.hasAttribute('data-count-to')) {\n"
        "        element.setAttribute('data-count-to', String(value));\n"
        "      }\n"
        "    });\n"
        "\n"
        "    scope.querySelectorAll('[data-lineage-template]').forEach(function (element) {\n"
        "      element.textContent = renderTemplate(element.getAttribute('data-lineage-template'));\n"
        "    });\n"
        "  }\n"
        "\n"
        "  hydrate(document);\n"
        "  if (document.readyState === 'loading') {\n"
        "    document.addEventListener('DOMContentLoaded', function () { hydrate(document); });\n"
        "  }\n"
        "})();\n"
    )


def build_asset(nodes: list[dict], edges: list[dict], date_token: str) -> str:
    return (
        f"// genealogy-data.js - generated from Network_Nodes_{date_token}.csv, "
        f"Network_Edges_{date_token}.csv, and the dated headshot manifest.\n"
        "// RAW_NODES and RAW_EDGES are generated data; do not hand-edit them.\n"
        "// Re-run Code/Network/build_genealogy_data_asset.py after network or photo changes.\n\n"
        "// Raw data\n"
        f"const RAW_NODES = {safe_json(nodes)};\n"
        f"const RAW_EDGES = {safe_json(edges)};\n"
        f"{GENEALOGY_RUNTIME_JS}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static Family Tree genealogy-data.js")
    parser.add_argument("--date", default=None, help="Network snapshot date (MMDDYY; defaults to latest common date)")
    parser.add_argument("--nodes", default=None, help="Override Network_Nodes CSV path")
    parser.add_argument("--edges", default=None, help="Override Network_Edges CSV path")
    parser.add_argument("--photo-manifest", default=None, help="Override headshot manifest path")
    parser.add_argument("--output", default="mokyr-legacy-site/assets/genealogy-data.js",
                        help="Output JS path")
    parser.add_argument("--stats-output", default="mokyr-legacy-site/assets/lineage-stats.js",
                        help="Output site-wide lineage stats JS path")
    args = parser.parse_args()

    date_token = resolve_network_date(args.date, args.nodes, args.edges)
    nodes_csv = _project_path(args.nodes, PROJECT_ROOT / "Data" / "Derived" / f"Network_Nodes_{date_token}.csv")
    edges_csv = _project_path(args.edges, PROJECT_ROOT / "Data" / "Derived" / f"Network_Edges_{date_token}.csv")
    output_path = _project_path(args.output, PROJECT_ROOT / "mokyr-legacy-site" / "assets" / "genealogy-data.js")
    stats_output_path = _project_path(args.stats_output, PROJECT_ROOT / "mokyr-legacy-site" / "assets" / "lineage-stats.js")

    for path in (nodes_csv, edges_csv):
        if not path.exists():
            sys.exit(f"ERROR: input file not found: {path}")

    print(f"Loading nodes : {nodes_csv}")
    nodes = load_nodes(nodes_csv, date_token=date_token, photo_manifest_path=args.photo_manifest)
    print(f"Loading edges : {edges_csv}")
    edges = load_edges(edges_csv)
    assert_no_email_fields(nodes)

    js = build_asset(nodes, edges, date_token)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(js, encoding="utf-8")
    print(f"Output: {output_path}")

    stats = build_lineage_stats(nodes, edges)
    stats_js = build_lineage_stats_asset(stats, date_token)
    stats_output_path.parent.mkdir(parents=True, exist_ok=True)
    stats_output_path.write_text(stats_js, encoding="utf-8")
    print(f"Stats output: {stats_output_path}")
    print(
        "Lineage stats: "
        f"{stats['scholarCount']} scholars, "
        f"{stats['personCount']} people including Joel, "
        f"{stats['generationCount']} generations, "
        f"{stats['directStudentCount']} direct students."
    )

    email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
    matches = email_pattern.findall(js + "\n" + stats_js)
    if matches:
        print(f"WARNING: Possible email address(es) in genealogy data output: {matches[:5]}")
    else:
        print("Verified: no email addresses in genealogy data output.")


if __name__ == "__main__":
    main()
