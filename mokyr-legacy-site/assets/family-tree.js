/**
 * family-tree.js
 * Drives the /family page: mode switching (tree / network) and the
 * expandable family-tree UI.  Depends on GENEALOGY global from genealogy-data.js.
 */

(function () {
  "use strict";

  // ── DOM references ──────────────────────────────────────────────────────────
  const treePanel     = document.getElementById("ft-tree-panel");
  const networkPanel  = document.getElementById("ft-network-panel");
  const networkShell  = document.getElementById("ft-network-frame-shell");
  const treeRoot      = document.getElementById("ft-tree-root");
  const searchInput   = document.getElementById("ft-search");
  const tileBtns      = Array.from(document.querySelectorAll(".ft-tile"));

  // ── State ───────────────────────────────────────────────────────────────────
  let networkInjected = false;
  let searchTimer     = null;

  // ── Helpers ─────────────────────────────────────────────────────────────────

  /**
   * Build a concise meta string: "Institution · Year", "Institution", "Year", or "".
   */
  function buildMeta(node) {
    const inst = node.institution || node.employer || "";
    const year = node.phd_year || "";
    if (inst && year) return inst + " \u00b7 " + year;
    if (inst) return inst;
    if (year) return String(year);
    return "";
  }

  /**
   * Sort an array of node ids so that:
   * 1. people with descendants come first
   * 2. those people are ordered by descendant count, highest to lowest
   * 3. zero-descendant people follow alphabetically by label
   */
  function sortByDescThenLabel(ids) {
    return ids.slice().sort(function (a, b) {
      const da = GENEALOGY.descendantCountById[a] || 0;
      const db = GENEALOGY.descendantCountById[b] || 0;
      const aHasDesc = da > 0;
      const bHasDesc = db > 0;

      if (aHasDesc !== bHasDesc) return aHasDesc ? -1 : 1;
      if (aHasDesc && db !== da) return db - da;

      const la = (GENEALOGY.peopleById[a] || {}).label || "";
      const lb = (GENEALOGY.peopleById[b] || {}).label || "";
      return la.localeCompare(lb);
    });
  }

  // ── Node builders ────────────────────────────────────────────────────────────

  /**
   * Build the root node element for Joel Mokyr and append it to treeRoot.
   */
  function buildRootNode() {
    const id     = GENEALOGY.ROOT_ID;
    const node   = GENEALOGY.peopleById[id] || {};
    const desc   = GENEALOGY.descendantCountById[id] || 0;
    const meta   = buildMeta(node);

    const wrapper = document.createElement("div");
    wrapper.className        = "ft-node ft-node--root";
    wrapper.setAttribute("role",          "treeitem");
    wrapper.setAttribute("aria-expanded", "false");
    wrapper.setAttribute("data-id",       id);
    wrapper.setAttribute("tabindex",      "0");

    const btn = document.createElement("button");
    btn.className = "ft-card ft-card--root";
    btn.type      = "button";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls",  "ft-children-" + id);

    const inner = document.createElement("div");
    inner.className = "ft-card-inner";

    const info = document.createElement("div");
    info.className = "ft-node-info";

    const labelEl = document.createElement("span");
    labelEl.className   = "ft-label";
    labelEl.textContent = node.label || "Joel Mokyr";
    info.appendChild(labelEl);

    if (meta) {
      const metaEl = document.createElement("span");
      metaEl.className   = "ft-meta";
      metaEl.textContent = meta;
      info.appendChild(metaEl);
    }

    inner.appendChild(info);

    if (desc > 0) {
      const badge = document.createElement("span");
      badge.className = "ft-badge";
      badge.setAttribute("aria-label", desc + " total descendants");
      badge.textContent = desc;
      inner.appendChild(badge);
    }

    btn.appendChild(inner);
    wrapper.appendChild(btn);

    // Helper callout
    const helper = document.createElement("p");
    helper.className = "ft-helper";
    helper.id        = "ft-helper";
    helper.textContent = "Click Joel Mokyr to open the tree.";
    wrapper.appendChild(helper);

    // Children container
    const ul = document.createElement("ul");
    ul.className = "ft-children";
    ul.id        = "ft-children-" + id;
    ul.setAttribute("role", "group");
    ul.hidden    = true;
    wrapper.appendChild(ul);

    treeRoot.appendChild(wrapper);

    // Events
    btn.addEventListener("click",   function () { handleRootClick(wrapper, btn, ul, helper); });
    btn.addEventListener("keydown",  function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        btn.click();
      }
    });
    wrapper.addEventListener("keydown", function (e) {
      if (e.target === wrapper && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        btn.click();
      }
    });
  }

  /**
   * Build a single branch <li> node.
   */
  function buildBranchNode(id) {
    const node  = GENEALOGY.peopleById[id] || {};
    const desc  = GENEALOGY.descendantCountById[id] || 0;
    const meta  = buildMeta(node);
    const coAdv = GENEALOGY.secondaryAdvisorById ? GENEALOGY.secondaryAdvisorById[id] : null;

    const li = document.createElement("li");
    li.className        = "ft-node";
    li.setAttribute("role",          "treeitem");
    li.setAttribute("aria-expanded", "false");
    li.setAttribute("data-id",       id);
    li.setAttribute("tabindex",      "-1");

    const btn = document.createElement("button");
    btn.className = "ft-card";
    btn.type      = "button";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls",  "ft-children-" + id);

    const expandIcon = document.createElement("span");
    expandIcon.className             = "ft-expand-icon";
    expandIcon.setAttribute("aria-hidden", "true");
    expandIcon.textContent           = "\u25b6"; // ▶

    const inner = document.createElement("div");
    inner.className = "ft-card-inner";

    const info = document.createElement("div");
    info.className = "ft-node-info";

    const labelEl = document.createElement("span");
    labelEl.className   = "ft-label";
    labelEl.textContent = node.label || id;
    info.appendChild(labelEl);

    if (meta) {
      const metaEl = document.createElement("span");
      metaEl.className   = "ft-meta";
      metaEl.textContent = meta;
      info.appendChild(metaEl);
    }

    inner.appendChild(info);

    if (desc > 0) {
      const badge = document.createElement("span");
      badge.className = "ft-badge";
      badge.setAttribute("aria-label", desc + " total descendants");
      badge.textContent = desc;
      inner.appendChild(badge);
    }

    btn.appendChild(expandIcon);
    btn.appendChild(inner);
    li.appendChild(btn);

    if (coAdv) {
      const coNote = document.createElement("p");
      coNote.className   = "ft-co-note";
      coNote.textContent = "Also supervised by: " + coAdv;
      li.appendChild(coNote);
    }

    const ul = document.createElement("ul");
    ul.className = "ft-children";
    ul.id        = "ft-children-" + id;
    ul.setAttribute("role", "group");
    ul.hidden    = true;
    li.appendChild(ul);

    // Events
    btn.addEventListener("click", function () { handleBranchClick(li, btn, expandIcon, ul); });
    btn.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        btn.click();
      }
    });
    li.addEventListener("keydown", function (e) {
      if (e.target === li && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        btn.click();
      }
    });

    return li;
  }

  // ── Expand / collapse helpers ────────────────────────────────────────────────

  /**
   * Collapse a branch node: hide children, purge them from the DOM, reset aria.
   */
  function collapseNode(li) {
    const btn  = li.querySelector(":scope > .ft-card");
    const icon = btn ? btn.querySelector(".ft-expand-icon") : null;
    const ul   = li.querySelector(":scope > .ft-children");

    li.setAttribute("aria-expanded", "false");
    if (btn)  { btn.setAttribute("aria-expanded", "false"); btn.classList.remove("is-expanded"); }
    if (icon) { icon.classList.remove("is-expanded"); }
    if (ul)   { ul.hidden = true; ul.innerHTML = ""; }
  }

  /**
   * Render child nodes into a <ul> using the tree ordering rule:
   * descendants first, then descendant count desc, then alphabetical for zero-descendant nodes.
   */
  function renderChildren(id, ul) {
    // Only include children whose primary parent is this node, to avoid showing
    // co-advised people under their secondary advisor's branch.
    const allChildIds = GENEALOGY.childrenById[id] || [];
    const childIds    = allChildIds.filter(function (cid) {
      return GENEALOGY.primaryParentById[cid] === id;
    });
    const sorted = sortByDescThenLabel(childIds);
    sorted.forEach(function (childId) {
      ul.appendChild(buildBranchNode(childId));
    });
  }

  /**
   * Expand root (Joel Mokyr): render all Gen 1 nodes with descendants first,
   * sorted most-to-least, then alphabetical for zero-descendant people.
   */
  function handleRootClick(wrapper, btn, ul, helper) {
    const isExpanded = wrapper.getAttribute("aria-expanded") === "true";

    if (isExpanded) {
      // Collapse: hide and purge children, restore helper
      ul.hidden    = true;
      ul.innerHTML = "";
      wrapper.setAttribute("aria-expanded", "false");
      btn.setAttribute("aria-expanded", "false");
      btn.classList.remove("is-expanded");
      if (helper) helper.hidden = false;
    } else {
      // Expand: render Gen 1 nodes with descendants first, then alphabetical among zero-descendant people
      ul.innerHTML = "";
      renderChildren(GENEALOGY.ROOT_ID, ul);
      ul.hidden    = false;
      wrapper.setAttribute("aria-expanded", "true");
      btn.setAttribute("aria-expanded", "true");
      btn.classList.add("is-expanded");
      if (helper) helper.hidden = true;
    }
  }

  /**
   * Expand or collapse a branch node (Gen 1+).
   * Collapses any expanded sibling before expanding self.
   */
  function handleBranchClick(li, btn, expandIcon, ul) {
    const isExpanded = li.getAttribute("aria-expanded") === "true";

    if (isExpanded) {
      collapseNode(li);
    } else {
      // Collapse any expanded sibling at the same depth
      const parent = li.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children);
        siblings.forEach(function (sib) {
          if (sib !== li && sib.getAttribute("aria-expanded") === "true") {
            collapseNode(sib);
          }
        });
      }

      // Expand self
      renderChildren(li.getAttribute("data-id"), ul);
      ul.hidden    = false;
      li.setAttribute("aria-expanded", "true");
      btn.setAttribute("aria-expanded", "true");
      btn.classList.add("is-expanded");
      expandIcon.classList.add("is-expanded");
    }
  }

  // ── Search ───────────────────────────────────────────────────────────────────

  /**
   * Given a node id, walk up to find all ancestor ids that are already rendered
   * in the DOM as ft-node elements, returning them root-first.
   */
  function getAncestorIds(id) {
    const ancestors = [];
    let current = GENEALOGY.primaryParentById ? GENEALOGY.primaryParentById[id] : null;
    while (current && current !== GENEALOGY.ROOT_ID) {
      ancestors.unshift(current);
      current = GENEALOGY.primaryParentById ? GENEALOGY.primaryParentById[current] : null;
    }
    if (current === GENEALOGY.ROOT_ID) {
      ancestors.unshift(GENEALOGY.ROOT_ID);
    }
    return ancestors;
  }

  /**
   * Ensure a node's branch is expanded (used during search to make matches visible).
   * Walks the ancestor chain and expands any collapsed ancestor.
   */
  function ensureVisible(id) {
    const ancestorIds = getAncestorIds(id);

    ancestorIds.forEach(function (ancId) {
      const ancEl = treeRoot.querySelector('[data-id="' + ancId + '"]');
      if (!ancEl) return;

      const isExpanded = ancEl.getAttribute("aria-expanded") === "true";
      if (isExpanded) return;

      if (ancId === GENEALOGY.ROOT_ID) {
        // Expand root
        const btn    = ancEl.querySelector(":scope > .ft-card");
        const ul     = ancEl.querySelector(":scope > .ft-children");
        const helper = ancEl.querySelector(".ft-helper");
        handleRootClick(ancEl, btn, ul, helper);
      } else {
        const btn      = ancEl.querySelector(":scope > .ft-card");
        const icon     = btn ? btn.querySelector(".ft-expand-icon") : null;
        const ul       = ancEl.querySelector(":scope > .ft-children");
        if (btn && ul) handleBranchClick(ancEl, btn, icon, ul);
      }
    });

    // Also expand the matched node's immediate parent if needed so the node itself shows
    const parentId = GENEALOGY.primaryParentById ? GENEALOGY.primaryParentById[id] : null;
    if (parentId) {
      const parentEl = treeRoot.querySelector('[data-id="' + parentId + '"]');
      if (parentEl && parentEl.getAttribute("aria-expanded") !== "true") {
        const btn  = parentEl.querySelector(":scope > .ft-card");
        const icon = btn ? btn.querySelector(".ft-expand-icon") : null;
        const ul   = parentEl.querySelector(":scope > .ft-children");
        if (btn && ul) handleBranchClick(parentEl, btn, icon, ul);
      }
    }
  }

  function runSearch(query) {
    // Clear previous highlights
    treeRoot.querySelectorAll(".ft-match").forEach(function (el) {
      el.classList.remove("ft-match");
    });

    if (!query) {
      treeRoot.classList.remove("ft-search-active");
      return;
    }

    treeRoot.classList.add("ft-search-active");

    const lower   = query.toLowerCase();
    const allIds  = Object.keys(GENEALOGY.peopleById);
    const matches = allIds.filter(function (id) {
      const label = (GENEALOGY.peopleById[id].label || "").toLowerCase();
      return label.includes(lower);
    });

    // If few matches and root has been expanded, ensure branches are open
    const rootEl    = treeRoot.querySelector('[data-id="' + GENEALOGY.ROOT_ID + '"]');
    const rootOpen  = rootEl && rootEl.getAttribute("aria-expanded") === "true";

    if (matches.length < 20 && rootOpen) {
      matches.forEach(function (id) {
        ensureVisible(id);
      });
    }

    // Highlight matches that are now in the DOM
    matches.forEach(function (id) {
      const el = treeRoot.querySelector('[data-id="' + id + '"]');
      if (el) el.classList.add("ft-match");
    });
  }

  searchInput.addEventListener("input", function () {
    clearTimeout(searchTimer);
    const query = searchInput.value.trim();
    searchTimer = setTimeout(function () { runSearch(query); }, 200);
  });

  // ── Mode switching ───────────────────────────────────────────────────────────

  function activateMode(mode) {
    const isTree    = mode === "tree";
    const isNetwork = mode === "network";

    tileBtns.forEach(function (btn) {
      const isActive = btn.getAttribute("data-mode") === mode;
      btn.classList.toggle("is-active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });

    if (isTree) {
      treePanel.removeAttribute("hidden");
      networkPanel.setAttribute("hidden", "");
    } else {
      treePanel.setAttribute("hidden", "");
      networkPanel.removeAttribute("hidden");
    }

    // Lazy-inject network iframe
    if (isNetwork && !networkInjected) {
      const iframe = document.createElement("iframe");
      iframe.src   = "../network/mokyr-genealogy.html";
      iframe.title = "Joel Mokyr academic genealogy visualization";
      networkShell.appendChild(iframe);
      networkInjected = true;
    }

    history.replaceState(null, "", isNetwork ? "#network" : "#tree");
  }

  tileBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      activateMode(btn.getAttribute("data-mode"));
    });
  });

  // ── Init ─────────────────────────────────────────────────────────────────────

  function init() {
    // Guard: if GENEALOGY is not yet defined, bail gracefully
    if (typeof GENEALOGY === "undefined") {
      console.warn("family-tree.js: GENEALOGY global not found. Is genealogy-data.js loaded?");
      return;
    }

    buildRootNode();

    // Hash-based initial mode
    const hash = window.location.hash;
    if (hash === "#network") {
      activateMode("network");
    } else {
      activateMode("tree");
    }
  }

  document.addEventListener("DOMContentLoaded", init);

})();
