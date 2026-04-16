#!/usr/bin/env python3
"""Generate a self-contained HTML reviewer for OpenAlex manual decisions."""

from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from html import escape as html_escape
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CODE_ROOT = PROJECT_ROOT / "Code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from Bibliometrics.openalex_review_pipeline import (  # noqa: E402
    APPROVE_ACTION,
    DECISION_FIELDNAMES,
    DEFER_ACTION,
    PROJECT_ROOT,
    REJECT_ACTION,
    default_reviewer,
    extract_date_token,
    filter_matches_by_status,
    load_csv,
    load_review_snapshot,
    lock_date_token,
    normalize_openalex_id,
    parse_status_list,
    resolve_path,
    safe_float,
    split_flags,
    top_papers_for_node_author,
)


MODE_FLAGGED = "flagged"
MODE_CLAUDE_FOLLOWUP = "claude_followup"
MODE_UNRESOLVED = "unresolved"
FLAGGED_KEEP_DECISION = "keep_match"
FLAGGED_REJECT_DECISION = "reject_match"
FLAGGED_DEFER_DECISION = "needs_more_review"
FLAGGED_PATTERN = re.compile(r"^OpenAlex_Flagged_For_Review_(\d{6})\.csv$")
CLAUDE_FOLLOWUP_PATTERN = re.compile(r"^OpenAlex_Claude_Review_Followup_(\d{6})\.csv$")
DEFAULT_UNRESOLVED_STATUSES = "needs_manual_review,ambiguous_manual_review"

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root {
      --bg: #f3efe6;
      --paper: #fffdf8;
      --ink: #1d1b16;
      --muted: #6c6559;
      --line: #d9cfbf;
      --accent: #0e5a8a;
      --accent-soft: #dceaf5;
      --green: #0b7a53;
      --green-soft: #ddf2ea;
      --red: #a6332a;
      --red-soft: #f7dfdc;
      --yellow: #9a6a08;
      --yellow-soft: #f4ead1;
      --shadow: 0 16px 32px rgba(29, 27, 22, 0.08);
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(14, 90, 138, 0.08), transparent 30%),
        linear-gradient(180deg, #f8f4eb, var(--bg));
    }
    a {
      color: var(--accent);
      text-decoration-thickness: 1px;
    }
    button,
    input,
    textarea {
      font: inherit;
    }
    .shell {
      min-height: 100vh;
      padding: 28px;
    }
    .header {
      position: sticky;
      top: 0;
      z-index: 5;
      margin-bottom: 20px;
      padding: 16px 18px;
      background: rgba(255, 253, 248, 0.95);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }
    .header-top {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 12px;
    }
    h1 {
      margin: 0;
      font-size: 1.4rem;
      line-height: 1.1;
    }
    .meta {
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.45;
    }
    .progress-track {
      width: 100%;
      height: 12px;
      border-radius: 999px;
      background: #ebe2d3;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      width: 0;
      background: linear-gradient(90deg, #0e5a8a, #1f7c9d);
      transition: width 120ms ease-out;
    }
    .stat-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }
    .stat {
      padding: 7px 10px;
      border-radius: 999px;
      background: #efe6d6;
      color: var(--ink);
      font-size: 0.92rem;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .button {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--paper);
      color: var(--ink);
      padding: 10px 14px;
      cursor: pointer;
      box-shadow: 0 2px 0 rgba(0, 0, 0, 0.03);
      transition: transform 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
    }
    .button:hover {
      border-color: #b9ab95;
    }
    .button.active {
      box-shadow: inset 0 0 0 2px rgba(29, 27, 22, 0.12);
      transform: translateY(1px);
    }
    .button-primary {
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }
    .button-green {
      background: var(--green);
      border-color: var(--green);
      color: white;
    }
    .button-red {
      background: var(--red);
      border-color: var(--red);
      color: white;
    }
    .button-muted {
      background: #d6d0c8;
      border-color: #d6d0c8;
    }
    .viewer {
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .viewer-inner {
      display: grid;
      grid-template-columns: minmax(280px, 0.95fr) minmax(320px, 1.25fr);
    }
    .panel {
      padding: 24px;
    }
    .panel-left {
      background:
        linear-gradient(180deg, rgba(14, 90, 138, 0.05), rgba(14, 90, 138, 0)),
        #f8f2e8;
      border-right: 1px solid var(--line);
    }
    .name {
      margin: 0 0 12px;
      font-size: clamp(1.7rem, 3vw, 2.6rem);
      line-height: 1.05;
    }
    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 18px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 0.88rem;
      background: #ede4d4;
      color: var(--ink);
    }
    .chip-status {
      background: var(--accent-soft);
      color: #133b58;
    }
    .chip-flag {
      background: var(--yellow-soft);
      color: var(--yellow);
    }
    .chip-success {
      background: var(--green-soft);
      color: var(--green);
    }
    .chip-danger {
      background: var(--red-soft);
      color: var(--red);
    }
    .section {
      margin-bottom: 18px;
    }
    .section h2 {
      margin: 0 0 8px;
      font-size: 0.95rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
    }
    dl {
      margin: 0;
      display: grid;
      grid-template-columns: minmax(110px, 130px) 1fr;
      gap: 8px 12px;
    }
    dt {
      color: var(--muted);
    }
    dd {
      margin: 0;
    }
    .note {
      margin: 0;
      padding: 14px 16px;
      border-radius: 14px;
      background: #f4ede0;
      border: 1px solid #e1d4bf;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .candidate-list {
      display: grid;
      gap: 14px;
    }
    .candidate {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      background: #fffdfa;
    }
    .candidate.current {
      border-color: #93b6cf;
      box-shadow: inset 0 0 0 1px rgba(14, 90, 138, 0.14);
      background: #f7fbfe;
    }
    .candidate-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 10px;
    }
    .candidate-title {
      margin: 0;
      font-size: 1.1rem;
    }
    .radio-line {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }
    .score-badge {
      min-width: 62px;
      text-align: center;
      padding: 6px 8px;
      border-radius: 999px;
      font-size: 0.88rem;
      font-weight: 700;
    }
    .score-green {
      background: var(--green-soft);
      color: var(--green);
    }
    .score-yellow {
      background: var(--yellow-soft);
      color: var(--yellow);
    }
    .score-red {
      background: var(--red-soft);
      color: var(--red);
    }
    .candidate-meta {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 8px 10px;
      margin: 10px 0 0;
      font-size: 0.95rem;
    }
    .candidate-meta strong {
      display: block;
      font-size: 0.8rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 2px;
    }
    .list {
      margin: 10px 0 0;
      padding-left: 18px;
    }
    .list li {
      margin-bottom: 5px;
      line-height: 1.45;
    }
    .textarea {
      width: 100%;
      min-height: 120px;
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: white;
      resize: vertical;
    }
    .decision-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }
    .decision-summary {
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.4;
    }
    .footer-nav {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 16px 22px 22px;
      border-top: 1px solid var(--line);
      background: rgba(248, 242, 232, 0.65);
    }
    .empty {
      padding: 36px;
      text-align: center;
    }
    .overlay {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
      background: rgba(21, 19, 15, 0.42);
      z-index: 20;
    }
    .overlay.show {
      display: flex;
    }
    .dialog {
      width: min(440px, 100%);
      padding: 24px;
      border-radius: 22px;
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }
    .dialog h2 {
      margin: 0 0 8px;
    }
    .dialog p {
      margin: 0 0 16px;
      line-height: 1.5;
      color: var(--muted);
    }
    .dialog-actions {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
    }
    @media (max-width: 980px) {
      .viewer-inner {
        grid-template-columns: 1fr;
      }
      .panel-left {
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div id="resumeOverlay" class="overlay">
      <div class="dialog">
        <h2>Resume saved session?</h2>
        <p id="resumeMessage"></p>
        <div class="dialog-actions">
          <button class="button" id="startFreshButton" type="button">Start Fresh</button>
          <button class="button button-primary" id="resumeButton" type="button">Resume</button>
        </div>
      </div>
    </div>

    <div class="header">
      <div class="header-top">
        <div>
          <h1>__TITLE__</h1>
          <div class="meta" id="headerMeta"></div>
        </div>
        <div class="controls">
          <button class="button" id="prevButton" type="button">Prev</button>
          <button class="button" id="nextButton" type="button">Next</button>
          <button class="button" id="jumpPendingButton" type="button">Jump to Next Pending</button>
          <button class="button button-primary" id="exportButton" type="button">Export Decisions CSV</button>
        </div>
      </div>
      <div class="progress-track" aria-hidden="true">
        <div class="progress-fill" id="progressFill"></div>
      </div>
      <div class="stat-row" id="statRow"></div>
      <div class="meta" id="helperMeta" style="margin-top: 10px;"></div>
    </div>

    <div id="viewerRoot"></div>
  </div>

  <script>
    const payload = __PAYLOAD_JSON__;
    const MODE_FLAGGED = "flagged";
    const MODE_CLAUDE_FOLLOWUP = "claude_followup";
    const MODE_UNRESOLVED = "unresolved";
    const ACTION_APPROVE = "__APPROVE_ACTION__";
    const ACTION_REJECT = "__REJECT_ACTION__";
    const ACTION_DEFER = "__DEFER_ACTION__";
    const FLAGGED_KEEP = "keep_match";
    const FLAGGED_REJECT = "reject_match";
    const FLAGGED_DEFER = "needs_more_review";

    const storageKey = payload.storage_key;
    const records = payload.records;
    const reviewer = payload.reviewer;

    let state = {};
    let currentIndex = 0;

    const viewerRoot = document.getElementById("viewerRoot");
    const progressFill = document.getElementById("progressFill");
    const statRow = document.getElementById("statRow");
    const headerMeta = document.getElementById("headerMeta");
    const helperMeta = document.getElementById("helperMeta");
    const resumeOverlay = document.getElementById("resumeOverlay");
    const resumeMessage = document.getElementById("resumeMessage");

    function escapeHtml(value) {
      return String(value == null ? "" : value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function emptyStateFor(record) {
      return {
        action: "",
        selected_openalex_id: record.preselected_openalex_id || "",
        notes: "",
      };
    }

    function hydrateState(rawState) {
      const hydrated = {};
      for (const record of records) {
        const blank = emptyStateFor(record);
        const saved = rawState && rawState[record.node_id] ? rawState[record.node_id] : null;
        hydrated[record.node_id] = {
          action: saved && typeof saved.action === "string" ? saved.action : blank.action,
          selected_openalex_id:
            saved && typeof saved.selected_openalex_id === "string"
              ? saved.selected_openalex_id
              : blank.selected_openalex_id,
          notes: saved && typeof saved.notes === "string" ? saved.notes : blank.notes,
        };
      }
      return hydrated;
    }

    function saveState() {
      window.localStorage.setItem(storageKey, JSON.stringify(state));
      renderHeader();
    }

    function decidedEntries() {
      return records.filter((record) => state[record.node_id] && state[record.node_id].action);
    }

    function counts() {
      let reviewed = 0;
      let positive = 0;
      let rejected = 0;
      let deferred = 0;
      for (const record of records) {
        const decisionState = state[record.node_id];
        if (!decisionState || !decisionState.action) {
          continue;
        }
        reviewed += 1;
        if (payload.mode === MODE_FLAGGED) {
          if (decisionState.action === FLAGGED_KEEP) {
            positive += 1;
          } else if (decisionState.action === FLAGGED_REJECT) {
            rejected += 1;
          } else if (decisionState.action === FLAGGED_DEFER) {
            deferred += 1;
          }
          continue;
        }
        if (decisionState.action === ACTION_APPROVE) {
          positive += 1;
        } else if (decisionState.action === ACTION_REJECT) {
          rejected += 1;
        } else if (decisionState.action === ACTION_DEFER) {
          deferred += 1;
        }
      }
      return { reviewed, positive, rejected, deferred };
    }

    function scoreClass(score) {
      if (score >= 0.75) {
        return "score-green";
      }
      if (score >= 0.65) {
        return "score-yellow";
      }
      return "score-red";
    }

    function renderHeader() {
      const totals = counts();
      const totalCount = records.length;
      const percent = totalCount ? (totals.reviewed / totalCount) * 100 : 0;
      const positiveLabel = payload.mode === MODE_FLAGGED ? "kept" : "approved";
      progressFill.style.width = `${percent}%`;
      headerMeta.textContent = payload.header_context;
      helperMeta.textContent = payload.helper_note || "";

      const parts = [
        `${totals.reviewed} / ${totalCount} reviewed`,
        `${totals.positive} ${positiveLabel}`,
        `${totals.rejected} rejected`,
        `${totals.deferred} deferred`,
      ];
      statRow.innerHTML = parts.map((part) => `<div class="stat">${escapeHtml(part)}</div>`).join("");
    }

    function decisionLabel(action) {
      if (payload.mode === MODE_FLAGGED) {
        if (action === FLAGGED_KEEP) {
          return "Keep Match";
        }
        if (action === FLAGGED_REJECT) {
          return "Reject Match";
        }
        if (action === FLAGGED_DEFER) {
          return "Needs More Review";
        }
        return "Pending";
      }
      if (action === ACTION_APPROVE) {
        return "Approve Selected";
      }
      if (action === ACTION_REJECT) {
        return "No Match";
      }
      if (action === ACTION_DEFER) {
        return "Defer";
      }
      return "Pending";
    }

    function move(delta) {
      if (!records.length) {
        return;
      }
      currentIndex = (currentIndex + delta + records.length) % records.length;
      renderViewer();
    }

    function jumpToNextPending() {
      if (!records.length) {
        return;
      }
      for (let offset = 1; offset <= records.length; offset += 1) {
        const index = (currentIndex + offset) % records.length;
        const record = records[index];
        if (!(state[record.node_id] && state[record.node_id].action)) {
          currentIndex = index;
          renderViewer();
          return;
        }
      }
    }

    function setAction(action) {
      const record = records[currentIndex];
      const decisionState = state[record.node_id];

      if (payload.mode === MODE_FLAGGED) {
        const selectedId = record.selected_openalex_id || decisionState.selected_openalex_id || "";
        if ((action === FLAGGED_KEEP || action === FLAGGED_DEFER) && !selectedId) {
          window.alert("This flagged row has no selected OpenAlex profile to keep or defer.");
          return;
        }
        decisionState.selected_openalex_id = selectedId;
      } else {
        const checked = document.querySelector('input[name="candidate"]:checked');
        const selectedId = checked ? checked.value : decisionState.selected_openalex_id || "";
        if (action === ACTION_APPROVE && !selectedId) {
          window.alert("Choose a candidate before approving.");
          return;
        }
        decisionState.selected_openalex_id = selectedId;
      }

      decisionState.action = action;
      state[record.node_id] = decisionState;
      saveState();
      renderViewer();
    }

    function onCandidateChange(selectedId) {
      const record = records[currentIndex];
      state[record.node_id].selected_openalex_id = selectedId;
      saveState();
    }

    function onNotesChange(value) {
      const record = records[currentIndex];
      state[record.node_id].notes = value;
      saveState();
    }

    function csvEscape(value) {
      const text = String(value == null ? "" : value);
      if (/[",\\n]/.test(text)) {
        return `"${text.replaceAll('"', '""')}"`;
      }
      return text;
    }

    function canonicalDecision(record, decisionState) {
      const currentId = record.current_openalex_id || "";
      const selectedId = decisionState.selected_openalex_id || "";

      if (decisionState.action === ACTION_APPROVE) {
        if (!selectedId) {
          throw new Error(`Approve Selected requires a candidate for ${record.node_id}.`);
        }
        if (currentId && selectedId === currentId) {
          return "keep_match";
        }
        if (currentId) {
          return "replace_match";
        }
        return "approve_match";
      }
      if (decisionState.action === ACTION_REJECT) {
        return "reject_match";
      }
      if (decisionState.action === ACTION_DEFER) {
        return "needs_more_review";
      }
      throw new Error(`Unsupported action ${decisionState.action}.`);
    }

    function proposedOpenAlexId(record, decisionState) {
      if (decisionState.action === ACTION_APPROVE) {
        return decisionState.selected_openalex_id || "";
      }
      if (decisionState.action === ACTION_DEFER) {
        return decisionState.selected_openalex_id || record.current_openalex_id || "";
      }
      return "";
    }

    function exportRow(record, decisionState) {
      if (payload.mode === MODE_FLAGGED) {
        const selectedId = record.selected_openalex_id || decisionState.selected_openalex_id || "";
        if ((decisionState.action === FLAGGED_KEEP || decisionState.action === FLAGGED_DEFER) && !selectedId) {
          throw new Error(`Flagged row ${record.node_id} is missing the selected OpenAlex profile.`);
        }
        return {
          node_id: record.node_id,
          full_name: record.full_name,
          current_openalex_id: record.export_current_openalex_id || selectedId,
          proposed_openalex_id: decisionState.action === FLAGGED_REJECT ? "" : selectedId,
          decision: decisionState.action,
          reason: (decisionState.notes || "").trim() || record.default_reason || "",
          reviewer,
        };
      }

      return {
        node_id: record.node_id,
        full_name: record.full_name,
        current_openalex_id: record.current_openalex_id || "",
        proposed_openalex_id: proposedOpenAlexId(record, decisionState),
        decision: canonicalDecision(record, decisionState),
        reason: (decisionState.notes || "").trim() || record.default_reason || "",
        reviewer,
      };
    }

    function exportCsv() {
      const decided = decidedEntries();
      if (!decided.length) {
        window.alert("Record at least one decision before exporting.");
        return;
      }

      const header = payload.decision_header;
      const lines = [header.join(",")];

      for (const record of decided) {
        const decisionState = state[record.node_id];
        const row = exportRow(record, decisionState);
        lines.push(header.map((field) => csvEscape(row[field] || "")).join(","));
      }

      const blob = new Blob([lines.join("\\n") + "\\n"], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = payload.export_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    function renderActionButton(action, label, buttonClass, currentAction) {
      const active = action === currentAction ? " active" : "";
      return `<button class="button ${buttonClass}${active}" data-action="${escapeHtml(action)}" type="button">${escapeHtml(label)}</button>`;
    }

    function renderList(items, emptyText) {
      if (!items || !items.length) {
        return `<p class="note">${escapeHtml(emptyText)}</p>`;
      }
      return `<ul class="list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    }

    function renderFlags(flags) {
      if (!flags || !flags.length) {
        return '<span class="chip">no suspicious flags</span>';
      }
      return flags.map((flag) => `<span class="chip chip-flag">${escapeHtml(flag)}</span>`).join("");
    }

    function renderClaudeRecommendation(record) {
      if (!record.claude_recommendation) {
        return "";
      }
      const recommendation = record.claude_recommendation;
      const suggestedCandidate = recommendation.selected_display_name || recommendation.selected_openalex_id || "none";
      return `
        <div class="section">
          <h2>Claude Recommendation</h2>
          <div class="chip-row">
            <span class="chip chip-status">${escapeHtml(recommendation.decision || "n/a")}</span>
            <span class="chip chip-flag">${escapeHtml(`confidence ${recommendation.confidence || "n/a"}`)}</span>
            ${recommendation.model ? `<span class="chip">${escapeHtml(recommendation.model)}</span>` : ""}
          </div>
          <p class="note">${escapeHtml(recommendation.note || "No recommendation note provided.")}</p>
          <p class="decision-summary">Suggested candidate: <strong>${escapeHtml(suggestedCandidate)}</strong></p>
        </div>
      `;
    }

    function renderCurrentMatch(record) {
      if (!record.current_openalex_id) {
        return '<p class="note">No current OpenAlex profile is attached to this row.</p>';
      }
      return `
        <div class="candidate current">
          <div class="candidate-head">
            <div>
              <p class="candidate-title">${escapeHtml(record.current_openalex_display_name || record.current_openalex_id)}</p>
              <div class="chip-row">
                <span class="chip chip-success">Current provisional match</span>
              </div>
            </div>
            <a href="${escapeHtml(record.current_openalex_id)}" target="_blank" rel="noopener noreferrer">OpenAlex</a>
          </div>
          <div class="candidate-meta">
            <div><strong>Works</strong>${escapeHtml(record.current_stats.works_count || "n/a")}</div>
            <div><strong>Citations</strong>${escapeHtml(record.current_stats.cited_by_count || "n/a")}</div>
            <div><strong>H-Index</strong>${escapeHtml(record.current_stats.h_index || "n/a")}</div>
            <div><strong>Institution</strong>${escapeHtml(record.current_stats.current_institution || "n/a")}</div>
          </div>
          ${renderList(record.current_top_papers, "No top-paper preview available.")}
        </div>
      `;
    }

    function renderUnresolvedCandidates(record, decisionState) {
      if (!record.candidates || !record.candidates.length) {
        return '<p class="note">No candidate rows are available for this scholar.</p>';
      }

      return record.candidates.map((candidate) => `
        <div class="candidate ${candidate.is_current ? "current" : ""}">
          <div class="radio-line">
            <input
              type="radio"
              id="cand-${escapeHtml(candidate.dom_id)}"
              name="candidate"
              value="${escapeHtml(candidate.openalex_id)}"
              ${decisionState.selected_openalex_id === candidate.openalex_id ? "checked" : ""}
            >
            <label for="cand-${escapeHtml(candidate.dom_id)}" style="flex: 1;">
              <span class="score-badge ${scoreClass(candidate.score)}">${escapeHtml(candidate.score_text)}</span>
            </label>
          </div>
          <div class="candidate-head">
            <div>
              <p class="candidate-title">${escapeHtml(candidate.display_name || candidate.openalex_id)}</p>
              <div class="chip-row">
                <span class="chip chip-status">rank ${escapeHtml(candidate.rank)}</span>
                <span class="chip">${escapeHtml(candidate.name_match_type || "candidate")}</span>
                ${candidate.is_current ? '<span class="chip chip-success">current</span>' : ""}
                ${record.claude_selected_openalex_id && candidate.openalex_id === record.claude_selected_openalex_id ? '<span class="chip chip-status">Claude suggested</span>' : ""}
              </div>
            </div>
            <a href="${escapeHtml(candidate.openalex_id)}" target="_blank" rel="noopener noreferrer">OpenAlex</a>
          </div>
          <div class="candidate-meta">
            <div><strong>Institution</strong>${escapeHtml(candidate.current_institution || "n/a")}</div>
            <div><strong>Works</strong>${escapeHtml(candidate.works_count || "0")}</div>
            <div><strong>Citations</strong>${escapeHtml(candidate.cited_by_count || "0")}</div>
            <div><strong>H-Index</strong>${escapeHtml(candidate.h_index || "0")}</div>
            <div><strong>Name Score</strong>${escapeHtml(candidate.name_score)}</div>
            <div><strong>Institution Score</strong>${escapeHtml(candidate.institution_score)}</div>
            <div><strong>Timing Score</strong>${escapeHtml(candidate.timing_score)}</div>
            <div><strong>Timing Note</strong>${escapeHtml(candidate.timing_note || "n/a")}</div>
          </div>
          <p class="decision-summary">${escapeHtml(candidate.institutions || "No institution list available.")}</p>
          ${renderList(candidate.top_papers, "No top-paper preview available.")}
        </div>
      `).join("");
    }

    function renderUnresolvedView(record, decisionState) {
      return `
        <div class="viewer">
          <div class="viewer-inner">
            <section class="panel panel-left">
              <div class="meta">Scholar ${currentIndex + 1} of ${records.length}</div>
              <h2 class="name">${escapeHtml(record.full_name)}</h2>
              <div class="chip-row">
                <span class="chip">${escapeHtml(`node ${record.node_id}`)}</span>
                <span class="chip">${escapeHtml(`generation ${record.generation || "n/a"}`)}</span>
                <span class="chip chip-status">${escapeHtml(record.match_status)}</span>
              </div>

              <div class="section">
                <h2>Scholar Context</h2>
                <dl>
                  <dt>PhD</dt><dd>${escapeHtml(record.phd_institution || "n/a")}</dd>
                  <dt>PhD Year</dt><dd>${escapeHtml(record.phd_year || "n/a")}</dd>
                  <dt>Employer</dt><dd>${escapeHtml(record.current_employer || "n/a")}</dd>
                  <dt>Advisor</dt><dd>${escapeHtml(record.advisor || "n/a")}</dd>
                  <dt>Candidate Count</dt><dd>${escapeHtml(record.candidate_count || "0")}</dd>
                </dl>
              </div>

              <div class="section">
                <h2>Flags</h2>
                <div class="chip-row">${renderFlags(record.suspicious_flags)}</div>
              </div>

              <div class="section">
                <h2>Review Note</h2>
                <p class="note">${escapeHtml(record.review_notes || "No review note provided.")}</p>
              </div>

              ${renderClaudeRecommendation(record)}

              <div class="section">
                <h2>Current Match</h2>
                ${renderCurrentMatch(record)}
              </div>
            </section>

            <section class="panel">
              <div class="section">
                <h2>Candidate Review</h2>
                <div class="candidate-list">${renderUnresolvedCandidates(record, decisionState)}</div>
              </div>

              <div class="section">
                <h2>Reviewer Notes</h2>
                <textarea class="textarea" id="notesBox" placeholder="Add decision notes or corrections here.">${escapeHtml(decisionState.notes)}</textarea>
              </div>

              <div class="section">
                <h2>Decision</h2>
                <div class="decision-bar">
                  ${renderActionButton(ACTION_APPROVE, "Approve Selected", "button-green", decisionState.action)}
                  ${renderActionButton(ACTION_REJECT, "No Match", "button-red", decisionState.action)}
                  ${renderActionButton(ACTION_DEFER, "Defer", "button-muted", decisionState.action)}
                </div>
                <div class="decision-summary">Current decision: <strong>${escapeHtml(decisionLabel(decisionState.action))}</strong></div>
              </div>
            </section>
          </div>

          <div class="footer-nav">
            <div class="meta">Selected candidate: ${escapeHtml(decisionState.selected_openalex_id || "none")}</div>
            <div class="controls">
              <button class="button" id="prevButtonBottom" type="button">Prev</button>
              <button class="button" id="nextButtonBottom" type="button">Next</button>
            </div>
          </div>
        </div>
      `;
    }

    function renderFlaggedView(record, decisionState) {
      const scoreBadge = record.selected_candidate_score_text
        ? `<span class="score-badge ${scoreClass(record.selected_candidate_score_value)}">${escapeHtml(record.selected_candidate_score_text)}</span>`
        : "";
      const candidatePreviewHtml = record.candidate_preview.length
        ? `
          <div class="section">
            <h2>Stored Candidate Preview</h2>
            ${renderList(record.candidate_preview, "No stored candidate preview is available.")}
          </div>
        `
        : "";

      return `
        <div class="viewer">
          <div class="viewer-inner">
            <section class="panel panel-left">
              <div class="meta">Flagged row ${currentIndex + 1} of ${records.length}</div>
              <h2 class="name">${escapeHtml(record.full_name)}</h2>
              <div class="chip-row">
                <span class="chip">${escapeHtml(`node ${record.node_id}`)}</span>
                <span class="chip">${escapeHtml(`generation ${record.generation || "n/a"}`)}</span>
                <span class="chip chip-status">${escapeHtml(record.match_status || "matched")}</span>
                <span class="chip chip-danger">${escapeHtml(record.audit_verdict || "flag")}</span>
                <span class="chip chip-flag">${escapeHtml(`confidence ${record.audit_confidence || "n/a"}`)}</span>
              </div>

              <div class="section">
                <h2>Scholar Context</h2>
                <dl>
                  <dt>PhD</dt><dd>${escapeHtml(record.phd_institution || "n/a")}</dd>
                  <dt>PhD Year</dt><dd>${escapeHtml(record.phd_year || "n/a")}</dd>
                  <dt>Employer</dt><dd>${escapeHtml(record.current_employer || "n/a")}</dd>
                  <dt>Advisor</dt><dd>${escapeHtml(record.advisor || "n/a")}</dd>
                  <dt>Original Decision</dt><dd>${escapeHtml(record.original_decision || "n/a")}</dd>
                </dl>
              </div>

              <div class="section">
                <h2>Flags</h2>
                <div class="chip-row">${renderFlags(record.suspicious_flags)}</div>
              </div>

              <div class="section">
                <h2>Original Review Note</h2>
                <p class="note">${escapeHtml(record.original_reason || "No original note available.")}</p>
              </div>

              <div class="section">
                <h2>Audit Note</h2>
                <p class="note">${escapeHtml(record.audit_note || "No audit note available.")}</p>
              </div>
            </section>

            <section class="panel">
              <div class="section">
                <h2>Selected OpenAlex Profile</h2>
                <div class="candidate current">
                  <div class="candidate-head">
                    <div>
                      <p class="candidate-title">${escapeHtml(record.selected_display_name || record.selected_openalex_id || "No selected profile")}</p>
                      <div class="chip-row">
                        ${scoreBadge}
                        <span class="chip chip-success">currently selected profile</span>
                      </div>
                    </div>
                    ${record.selected_openalex_id
                      ? `<a href="${escapeHtml(record.selected_openalex_id)}" target="_blank" rel="noopener noreferrer">OpenAlex</a>`
                      : ""}
                  </div>
                  <div class="candidate-meta">
                    <div><strong>Institution</strong>${escapeHtml(record.selected_candidate_current_institution || "n/a")}</div>
                    <div><strong>Works</strong>${escapeHtml(record.selected_candidate_works_count || "0")}</div>
                    <div><strong>Citations</strong>${escapeHtml(record.selected_candidate_cited_by_count || "0")}</div>
                    <div><strong>H-Index</strong>${escapeHtml(record.selected_candidate_h_index || "0")}</div>
                  </div>
                  <p class="decision-summary">${escapeHtml(record.selected_candidate_institutions || "No institution list available.")}</p>
                  ${renderList(record.top_papers, "No top-paper preview is stored for this flagged row.")}
                </div>
              </div>

              ${candidatePreviewHtml}

              <div class="section">
                <h2>Reviewer Notes</h2>
                <textarea class="textarea" id="notesBox" placeholder="Add follow-up notes or corrections here.">${escapeHtml(decisionState.notes)}</textarea>
              </div>

              <div class="section">
                <h2>Decision</h2>
                <div class="decision-bar">
                  ${renderActionButton(FLAGGED_KEEP, "Keep Match", "button-green", decisionState.action)}
                  ${renderActionButton(FLAGGED_REJECT, "Reject Match", "button-red", decisionState.action)}
                  ${renderActionButton(FLAGGED_DEFER, "Needs More Review", "button-muted", decisionState.action)}
                </div>
                <div class="decision-summary">Current decision: <strong>${escapeHtml(decisionLabel(decisionState.action))}</strong></div>
              </div>
            </section>
          </div>

          <div class="footer-nav">
            <div class="meta">Selected profile: ${escapeHtml(record.selected_openalex_id || "none")}</div>
            <div class="controls">
              <button class="button" id="prevButtonBottom" type="button">Prev</button>
              <button class="button" id="nextButtonBottom" type="button">Next</button>
            </div>
          </div>
        </div>
      `;
    }

    function bindDynamicControls() {
      for (const radio of document.querySelectorAll('input[name="candidate"]')) {
        radio.addEventListener("change", (event) => onCandidateChange(event.target.value));
      }
      const notesBox = document.getElementById("notesBox");
      if (notesBox) {
        notesBox.addEventListener("input", (event) => onNotesChange(event.target.value));
      }
      for (const button of document.querySelectorAll("[data-action]")) {
        button.addEventListener("click", () => setAction(button.dataset.action));
      }
      document.getElementById("prevButtonBottom").addEventListener("click", () => move(-1));
      document.getElementById("nextButtonBottom").addEventListener("click", () => move(1));
    }

    function renderViewer() {
      if (!records.length) {
        viewerRoot.innerHTML = `
          <div class="viewer">
            <div class="empty">
              <h2>${escapeHtml(payload.empty_title)}</h2>
              <p>${escapeHtml(payload.empty_message)}</p>
            </div>
          </div>
        `;
        renderHeader();
        return;
      }

      const record = records[currentIndex];
      const decisionState = state[record.node_id] || emptyStateFor(record);
      state[record.node_id] = decisionState;

      viewerRoot.innerHTML =
        payload.mode === MODE_FLAGGED
          ? renderFlaggedView(record, decisionState)
          : renderUnresolvedView(record, decisionState);

      bindDynamicControls();
      renderHeader();
    }

    function startFresh() {
      state = hydrateState(null);
      saveState();
      renderViewer();
    }

    function startWithSaved(savedState) {
      state = hydrateState(savedState);
      saveState();
      renderViewer();
    }

    function boot() {
      document.getElementById("prevButton").addEventListener("click", () => move(-1));
      document.getElementById("nextButton").addEventListener("click", () => move(1));
      document.getElementById("jumpPendingButton").addEventListener("click", jumpToNextPending);
      document.getElementById("exportButton").addEventListener("click", exportCsv);

      const rawSaved = window.localStorage.getItem(storageKey);
      if (!rawSaved) {
        startFresh();
        return;
      }

      let savedState = null;
      try {
        savedState = JSON.parse(rawSaved);
      } catch (error) {
        window.localStorage.removeItem(storageKey);
        startFresh();
        return;
      }

      const savedCount = records.filter((record) => savedState && savedState[record.node_id] && savedState[record.node_id].action).length;
      if (!savedCount) {
        startFresh();
        return;
      }

      resumeMessage.textContent = `${savedCount} of ${records.length} queued rows already have saved decisions.`;
      resumeOverlay.classList.add("show");
      document.getElementById("resumeButton").addEventListener("click", () => {
        resumeOverlay.classList.remove("show");
        startWithSaved(savedState);
      });
      document.getElementById("startFreshButton").addEventListener("click", () => {
        window.localStorage.removeItem(storageKey);
        resumeOverlay.classList.remove("show");
        startFresh();
      });
    }

    boot();
  </script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a self-contained OpenAlex review HTML tool")
    parser.add_argument(
        "--mode",
        default=MODE_CLAUDE_FOLLOWUP,
        choices=(MODE_CLAUDE_FOLLOWUP, MODE_FLAGGED, MODE_UNRESOLVED),
        help="Review mode: Claude follow-up queue, flagged re-review queue, or unresolved candidate review (default: claude_followup)",
    )
    parser.add_argument("--date", default=None, help="Date suffix for snapshot files (MMDDYY)")
    parser.add_argument("--followup", default=None, help="Optional path to OpenAlex_Claude_Review_Followup CSV")
    parser.add_argument("--flagged", default=None, help="Optional path to OpenAlex_Flagged_For_Review CSV")
    parser.add_argument("--matches", default=None, help="Optional path to OpenAlex_Scholar_Matches CSV")
    parser.add_argument("--review", default=None, help="Optional path to OpenAlex_Match_Review CSV")
    parser.add_argument("--top-papers", default=None, help="Optional path to OpenAlex_Top_Papers CSV")
    parser.add_argument(
        "--status",
        default=DEFAULT_UNRESOLVED_STATUSES,
        help="Comma-separated match statuses for unresolved mode",
    )
    parser.add_argument("--reviewer", default="", help="Reviewer label embedded in exported decisions")
    parser.add_argument("--output-html", default=None, help="Optional output HTML path")
    parser.add_argument("--title", default=None, help="Optional page title")
    parser.add_argument("--open", action="store_true", help="Open the generated HTML in the default browser")
    return parser


def resolve_dated_input_path(
    raw_path: str | None,
    *,
    default_name: str,
    date_token: str,
    required: bool,
) -> Path | None:
    default_path = PROJECT_ROOT / "Data" / "Derived" / default_name
    path = resolve_path(raw_path, default_path)
    token = extract_date_token(path.name)
    if token and token != date_token:
        raise ValueError(
            f"Path {path} is for date {token}, but the locked review snapshot date is {date_token}."
        )
    if path.exists():
        return path
    if raw_path:
        raise FileNotFoundError(f"Requested input file was not found: {path}")
    if required:
        raise FileNotFoundError(f"Required input file was not found: {path}")
    return None


def format_top_paper_lines(rows: list[dict[str, str]], *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for row in rows[:limit]:
        title = (row.get("title", "") or "").strip()
        year = (row.get("publication_year", "") or "").strip()
        if not title:
            continue
        line = title
        if year:
            line += f" ({year})"
        lines.append(line)
    return lines


def split_preview_items(raw_value: str) -> list[str]:
    text = (raw_value or "").strip()
    if not text or text == "[]":
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def parse_candidate_preview(raw_value: str) -> list[str]:
    text = (raw_value or "").strip()
    if not text or text == "[]":
        return []

    if text.startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            lines: list[str] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                display_name = str(item.get("display_name", "") or item.get("openalex_id", "")).strip()
                score = str(item.get("candidate_score", "")).strip()
                institution = str(
                    item.get("current_institution", "") or item.get("institution_matches", "")
                ).strip()
                line = display_name or "candidate"
                if score:
                    line += f" | score {score}"
                if institution:
                    line += f" | {institution}"
                lines.append(line)
            if lines:
                return lines

    return split_preview_items(text)


def populate_current_institutions(snapshot: Any, match_rows: list[dict[str, str]]) -> None:
    for match_row in match_rows:
        node_id = (match_row.get("node_id", "") or "").strip()
        current_id = normalize_openalex_id(match_row.get("openalex_id", ""))
        if not current_id:
            continue
        for candidate_row in snapshot.review_by_node.get(node_id, []):
            candidate_id = normalize_openalex_id(candidate_row.get("candidate_openalex_id", ""))
            if candidate_id == current_id:
                match_row["__current_institution"] = (
                    candidate_row.get("candidate_current_institution", "") or ""
                ).strip()
                break


def build_unresolved_record(snapshot: Any, match_row: dict[str, str]) -> dict[str, Any]:
    node_id = (match_row.get("node_id", "") or "").strip()
    current_id = normalize_openalex_id(match_row.get("openalex_id", ""))
    current_top_papers = top_papers_for_node_author(snapshot, node_id=node_id, openalex_id=current_id)

    candidates = []
    for candidate_row in snapshot.review_by_node.get(node_id, []):
        candidate_id = normalize_openalex_id(candidate_row.get("candidate_openalex_id", ""))
        candidate_top_papers = top_papers_for_node_author(snapshot, node_id=node_id, openalex_id=candidate_id)
        score = safe_float(candidate_row.get("candidate_score", ""))
        candidates.append(
            {
                "dom_id": f"{node_id}-{(candidate_row.get('candidate_rank', '') or 'candidate').strip()}",
                "rank": (candidate_row.get("candidate_rank", "") or "").strip(),
                "score": score,
                "score_text": f"{score:.2f}" if candidate_row.get("candidate_score", "") else "n/a",
                "name_score": (candidate_row.get("name_score", "") or "").strip(),
                "institution_score": (candidate_row.get("institution_score", "") or "").strip(),
                "timing_score": (candidate_row.get("timing_score", "") or "").strip(),
                "timing_note": (candidate_row.get("timing_note", "") or "").strip(),
                "name_match_type": (candidate_row.get("name_match_type", "") or "").strip(),
                "openalex_id": candidate_id,
                "display_name": (candidate_row.get("candidate_display_name", "") or "").strip(),
                "works_count": (candidate_row.get("candidate_works_count", "") or "").strip(),
                "cited_by_count": (candidate_row.get("candidate_cited_by_count", "") or "").strip(),
                "h_index": (candidate_row.get("candidate_h_index", "") or "").strip(),
                "current_institution": (candidate_row.get("candidate_current_institution", "") or "").strip(),
                "institutions": (candidate_row.get("candidate_institutions", "") or "").strip(),
                "is_current": bool(current_id and candidate_id and candidate_id == current_id),
                "top_papers": format_top_paper_lines(candidate_top_papers),
            }
        )

    preselected_id = ""
    if (match_row.get("match_status", "") or "").strip() == "needs_manual_review" and current_id:
        preselected_id = current_id

    return {
        "node_id": node_id,
        "full_name": (match_row.get("full_name", "") or "").strip(),
        "generation": (match_row.get("generation", "") or "").strip(),
        "advisor": (match_row.get("advisor", "") or "").strip(),
        "phd_institution": (match_row.get("phd_institution", "") or "").strip(),
        "phd_year": (match_row.get("phd_year", "") or "").strip(),
        "current_employer": (match_row.get("current_employer", "") or "").strip(),
        "match_status": (match_row.get("match_status", "") or "").strip(),
        "review_notes": (match_row.get("review_notes", "") or "").strip(),
        "default_reason": (match_row.get("review_notes", "") or "").strip(),
        "candidate_count": (match_row.get("candidate_count", "") or "").strip(),
        "suspicious_flags": split_flags(match_row.get("suspicious_flags", "")),
        "current_openalex_id": current_id,
        "current_openalex_display_name": (match_row.get("openalex_display_name", "") or "").strip(),
        "current_stats": {
            "works_count": (match_row.get("works_count", "") or "").strip(),
            "cited_by_count": (match_row.get("cited_by_count", "") or "").strip(),
            "h_index": (match_row.get("h_index", "") or "").strip(),
            "current_institution": (match_row.get("__current_institution", "") or "").strip(),
        },
        "current_top_papers": format_top_paper_lines(current_top_papers),
        "preselected_openalex_id": preselected_id,
        "candidates": candidates,
    }


def build_followup_record(
    snapshot: Any,
    followup_row: dict[str, str],
    match_row: dict[str, str],
) -> dict[str, Any]:
    record = build_unresolved_record(snapshot, match_row)
    recommended_id = normalize_openalex_id(
        followup_row.get("proposed_openalex_id", "") or followup_row.get("selected_openalex_id", "")
    )
    recommended_decision = (followup_row.get("decision", "") or "").strip()
    if recommended_decision in {"keep_match", "replace_match", "approve_match"} and recommended_id:
        record["preselected_openalex_id"] = recommended_id
    else:
        record["preselected_openalex_id"] = ""

    record["default_reason"] = (followup_row.get("claude_note", "") or "").strip() or record["default_reason"]
    record["claude_selected_openalex_id"] = recommended_id
    record["claude_recommendation"] = {
        "decision": recommended_decision,
        "action": (followup_row.get("claude_action", "") or "").strip(),
        "confidence": (followup_row.get("claude_confidence", "") or "").strip(),
        "note": (followup_row.get("claude_note", "") or "").strip(),
        "model": (followup_row.get("claude_model", "") or "").strip(),
        "selected_openalex_id": recommended_id,
        "selected_display_name": (followup_row.get("selected_display_name", "") or "").strip(),
    }
    return record


def build_flagged_record(
    flagged_row: dict[str, str],
    match_row: dict[str, str] | None,
) -> dict[str, Any]:
    match_context = match_row or {}
    selected_id = normalize_openalex_id(
        flagged_row.get("selected_openalex_id", "")
        or flagged_row.get("proposed_openalex_id", "")
        or flagged_row.get("current_openalex_id", "")
    )
    score = safe_float(flagged_row.get("selected_candidate_score", ""))
    score_text = (flagged_row.get("selected_candidate_score", "") or "").strip()
    original_reason = (
        (flagged_row.get("reason", "") or "").strip()
        or (flagged_row.get("review_notes", "") or "").strip()
    )
    default_reason = (flagged_row.get("audit_note", "") or "").strip() or original_reason

    return {
        "node_id": (flagged_row.get("node_id", "") or "").strip(),
        "full_name": (flagged_row.get("full_name", "") or "").strip()
        or (match_context.get("full_name", "") or "").strip(),
        "generation": (match_context.get("generation", "") or "").strip(),
        "advisor": (match_context.get("advisor", "") or "").strip(),
        "phd_institution": (match_context.get("phd_institution", "") or "").strip(),
        "phd_year": (match_context.get("phd_year", "") or "").strip(),
        "current_employer": (match_context.get("current_employer", "") or "").strip(),
        "match_status": (flagged_row.get("match_status", "") or "").strip()
        or (match_context.get("match_status", "") or "").strip(),
        "original_decision": (flagged_row.get("decision", "") or "").strip(),
        "original_reason": original_reason,
        "suspicious_flags": split_flags(flagged_row.get("suspicious_flags", "")),
        "selected_openalex_id": selected_id,
        "selected_display_name": (flagged_row.get("selected_display_name", "") or "").strip(),
        "selected_candidate_score_value": score,
        "selected_candidate_score_text": f"{score:.2f}" if score_text else "",
        "selected_candidate_current_institution": (
            flagged_row.get("selected_candidate_current_institution", "") or ""
        ).strip(),
        "selected_candidate_institutions": (
            flagged_row.get("selected_candidate_institutions", "") or ""
        ).strip(),
        "selected_candidate_works_count": (
            flagged_row.get("selected_candidate_works_count", "") or ""
        ).strip(),
        "selected_candidate_cited_by_count": (
            flagged_row.get("selected_candidate_cited_by_count", "") or ""
        ).strip(),
        "selected_candidate_h_index": (flagged_row.get("selected_candidate_h_index", "") or "").strip(),
        "audit_verdict": (flagged_row.get("audit_verdict", "") or "").strip(),
        "audit_confidence": (flagged_row.get("audit_confidence", "") or "").strip(),
        "audit_note": (flagged_row.get("audit_note", "") or "").strip(),
        "top_papers": split_preview_items(flagged_row.get("top_papers_preview", "")),
        "candidate_preview": parse_candidate_preview(flagged_row.get("candidate_preview", "")),
        "default_reason": default_reason,
        "preselected_openalex_id": selected_id,
        "export_current_openalex_id": selected_id,
    }


def render_html(*, title: str, payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    safe_title = html_escape(title, quote=True)
    return (
        HTML_TEMPLATE.replace("__TITLE__", safe_title)
        .replace("__PAYLOAD_JSON__", payload_json)
        .replace("__APPROVE_ACTION__", APPROVE_ACTION)
        .replace("__REJECT_ACTION__", REJECT_ACTION)
        .replace("__DEFER_ACTION__", DEFER_ACTION)
    )


def resolve_output_path(mode: str, date_token: str, raw_output: str | None) -> Path:
    if raw_output:
        path = Path(raw_output)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    if mode == MODE_CLAUDE_FOLLOWUP:
        default_name = f"openalex_claude_followup_review_{date_token}.html"
    elif mode == MODE_FLAGGED:
        default_name = f"openalex_flagged_review_{date_token}.html"
    else:
        default_name = f"openalex_review_{date_token}.html"
    return PROJECT_ROOT / "tmp" / "openalex_review" / default_name


def default_title(mode: str) -> str:
    if mode == MODE_CLAUDE_FOLLOWUP:
        return "OpenAlex Claude Follow-up Review"
    if mode == MODE_FLAGGED:
        return "OpenAlex Further Review"
    return "OpenAlex Match Review"


def prepare_followup_payload(args: argparse.Namespace, reviewer: str) -> tuple[dict[str, Any], Path, int]:
    date_token = lock_date_token(
        args.date,
        args.followup,
        args.matches,
        args.review,
        args.top_papers,
        fallback_pattern=CLAUDE_FOLLOWUP_PATTERN,
    )
    followup_path = resolve_dated_input_path(
        args.followup,
        default_name=f"OpenAlex_Claude_Review_Followup_{date_token}.csv",
        date_token=date_token,
        required=True,
    )
    snapshot = load_review_snapshot(
        date_token=date_token,
        matches_path=args.matches,
        review_path=args.review,
        top_papers_path=args.top_papers,
    )

    followup_rows = load_csv(followup_path)
    match_rows: list[dict[str, str]] = []
    for row in followup_rows:
        node_id = (row.get("node_id", "") or "").strip()
        if node_id not in snapshot.matches_by_node:
            raise ValueError(f"Claude follow-up row references node_id not present in snapshot: {node_id}")
        match_rows.append(snapshot.matches_by_node[node_id])

    populate_current_institutions(snapshot, match_rows)
    records = [
        build_followup_record(
            snapshot,
            row,
            snapshot.matches_by_node[(row.get("node_id", "") or "").strip()],
        )
        for row in followup_rows
    ]

    payload = {
        "mode": MODE_CLAUDE_FOLLOWUP,
        "date_token": snapshot.paths.date_token,
        "reviewer": reviewer,
        "storage_key": f"openalex_review::{MODE_CLAUDE_FOLLOWUP}::{snapshot.paths.date_token}",
        "header_context": f"Date {snapshot.paths.date_token} | reviewer {reviewer} | queue claude_followup",
        "helper_note": (
            "This queue contains Claude low/medium-confidence or deferred unresolved recommendations; "
            "candidate lists remain editable."
        ),
        "decision_header": DECISION_FIELDNAMES,
        "export_filename": f"openalex_claude_followup_review_decisions_{snapshot.paths.date_token}.csv",
        "empty_title": "No Claude follow-up rows are available.",
        "empty_message": "Run review_unresolved_cases.py first, or point --followup at a dated OpenAlex_Claude_Review_Followup CSV.",
        "records": records,
    }
    return payload, followup_path, len(records)


def prepare_flagged_payload(args: argparse.Namespace, reviewer: str) -> tuple[dict[str, Any], Path, int]:
    date_token = lock_date_token(
        args.date,
        args.flagged,
        args.matches,
        fallback_pattern=FLAGGED_PATTERN,
    )
    flagged_path = resolve_dated_input_path(
        args.flagged,
        default_name=f"OpenAlex_Flagged_For_Review_{date_token}.csv",
        date_token=date_token,
        required=True,
    )
    matches_path = resolve_dated_input_path(
        args.matches,
        default_name=f"OpenAlex_Scholar_Matches_{date_token}.csv",
        date_token=date_token,
        required=False,
    )

    flagged_rows = load_csv(flagged_path)
    matches_rows = load_csv(matches_path) if matches_path else []
    matches_by_node = {
        (row.get("node_id", "") or "").strip(): row
        for row in matches_rows
        if (row.get("node_id", "") or "").strip()
    }
    records = [
        build_flagged_record(row, matches_by_node.get((row.get("node_id", "") or "").strip()))
        for row in flagged_rows
    ]

    if matches_path is None:
        print(
            f"Warning: matches context file for {date_token} was not found; flagged reviewer will show reduced scholar context.",
            file=sys.stderr,
        )

    payload = {
        "mode": MODE_FLAGGED,
        "date_token": date_token,
        "reviewer": reviewer,
        "storage_key": f"openalex_review::{MODE_FLAGGED}::{date_token}",
        "header_context": f"Date {date_token} | reviewer {reviewer} | queue flagged_for_review",
        "helper_note": "This queue contains only rows the audit flagged for further manual classification.",
        "decision_header": DECISION_FIELDNAMES,
        "export_filename": f"openalex_flagged_review_decisions_{date_token}.csv",
        "empty_title": "No flagged rows are available.",
        "empty_message": "Run the audit first, or point --flagged at a dated OpenAlex_Flagged_For_Review CSV.",
        "records": records,
    }
    return payload, flagged_path, len(records)


def prepare_unresolved_payload(args: argparse.Namespace, reviewer: str) -> tuple[dict[str, Any], Path, int]:
    statuses = parse_status_list(args.status)
    snapshot = load_review_snapshot(
        date_token=args.date,
        matches_path=args.matches,
        review_path=args.review,
        top_papers_path=args.top_papers,
    )

    matches_rows = filter_matches_by_status(snapshot, statuses)
    populate_current_institutions(snapshot, matches_rows)
    records = [build_unresolved_record(snapshot, row) for row in matches_rows]
    status_key = "-".join(statuses)
    payload = {
        "mode": MODE_UNRESOLVED,
        "date_token": snapshot.paths.date_token,
        "reviewer": reviewer,
        "storage_key": f"openalex_review::{MODE_UNRESOLVED}::{snapshot.paths.date_token}::{status_key}",
        "header_context": (
            f"Date {snapshot.paths.date_token} | reviewer {reviewer} | statuses {', '.join(statuses)}"
        ),
        "helper_note": "Candidate choices come from the dated review snapshot and may be capped at five candidates per scholar.",
        "decision_header": DECISION_FIELDNAMES,
        "export_filename": f"openalex_review_decisions_{snapshot.paths.date_token}.csv",
        "empty_title": "No scholars match the requested statuses.",
        "empty_message": "Adjust --status or regenerate the underlying review snapshot.",
        "records": records,
    }
    return payload, snapshot.paths.matches_path, len(records)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    reviewer = (args.reviewer or "").strip() or default_reviewer()
    if args.mode == MODE_CLAUDE_FOLLOWUP:
        payload, source_path, record_count = prepare_followup_payload(args, reviewer)
    elif args.mode == MODE_FLAGGED:
        payload, source_path, record_count = prepare_flagged_payload(args, reviewer)
    else:
        payload, source_path, record_count = prepare_unresolved_payload(args, reviewer)

    title = args.title or default_title(args.mode)
    output_path = resolve_output_path(args.mode, payload["date_token"], args.output_html)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_html(title=title, payload=payload),
        encoding="utf-8",
    )

    print(f"Wrote review HTML: {output_path}")
    print(f"Mode:              {args.mode}")
    print(f"Date token:        {payload['date_token']}")
    print(f"Source file:       {source_path}")
    print(f"Queued rows:       {record_count}")
    if args.mode == MODE_UNRESOLVED:
        statuses = parse_status_list(args.status)
        print(f"Statuses:          {', '.join(statuses)}")
    if args.open:
        webbrowser.open(output_path.resolve().as_uri())
        print("Opened review HTML in the default browser.")


if __name__ == "__main__":
    main()
