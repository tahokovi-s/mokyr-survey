/**
 * family-tree.js
 * Drives the /family page:
 *   - Tablist mode switching (Family Tree / Network Map) with keyboard support.
 *   - Disclosure-widget tree (nested <ul> + buttons with aria-expanded).
 *   - Search with polite live-region announcements and ancestor auto-expansion.
 *   - Mobile-aware network fallback (no iframe injection on small screens).
 * Depends on the GENEALOGY global from genealogy-data.js.
 */

(function () {
  "use strict";

  // ── DOM references ──────────────────────────────────────────────────────────
  const tabs            = Array.from(document.querySelectorAll('.ft-tab[role="tab"]'));
  const treePanel       = document.getElementById("ft-tree-panel");
  const networkPanel    = document.getElementById("ft-network-panel");
  const networkShell    = document.getElementById("ft-network-frame-shell");
  const networkFallback = document.getElementById("ft-network-fallback");
  const treeRoot        = document.getElementById("ft-tree-root");
  const searchInput     = document.getElementById("ft-search");
  const searchStatus    = document.getElementById("ft-search-status");

  const MOBILE_MQ = window.matchMedia("(max-width: 639px)");
  const REDUCED_MOTION_MQ = window.matchMedia("(prefers-reduced-motion: reduce)");

  // ── State ───────────────────────────────────────────────────────────────────
  let networkInjected    = false;
  let searchTimer        = null;
  let lastAnnouncedCount = -1;
  let rootAutoExpanded   = false;

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function isMobile() { return MOBILE_MQ.matches; }
  function prefersReducedMotion() { return REDUCED_MOTION_MQ.matches; }

  function firstRenderedChildCard(ul) {
    if (!ul) return null;
    return ul.querySelector(":scope > .ft-node > .ft-card") || ul;
  }

  function buildMeta(node) {
    const inst = node.institution || node.employer || "";
    const year = node.phd_year || "";
    if (inst && year) return inst + " \u00b7 " + year;
    if (inst) return inst;
    if (year) return String(year);
    return "";
  }

  function avatarInitials(node) {
    const label = (node.label || "").trim();
    if (!label) return "";
    const parts = label.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function buildAvatar(node, options) {
    const opts = options || {};
    const avatar = document.createElement("span");
    avatar.className = "ft-avatar" + (opts.root ? " ft-avatar--root" : "");
    avatar.setAttribute("aria-hidden", "true");

    const fallback = document.createElement("span");
    fallback.className = "ft-avatar-fallback";
    fallback.textContent = avatarInitials(node);
    avatar.appendChild(fallback);

    if (node.photo_url) {
      const img = document.createElement("img");
      img.src = node.photo_url;
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      img.addEventListener("error", function () {
        img.remove();
        avatar.classList.add("ft-avatar--fallback");
      }, { once: true });
      avatar.appendChild(img);
    } else {
      avatar.classList.add("ft-avatar--fallback");
    }

    return avatar;
  }

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

  // ── Node builders (disclosure semantics) ────────────────────────────────────

  function buildRootNode() {
    const id   = GENEALOGY.ROOT_ID;
    const node = GENEALOGY.peopleById[id] || {};
    const desc = GENEALOGY.descendantCountById[id] || 0;
    const meta = buildMeta(node);

    const wrapper = document.createElement("div");
    wrapper.className = "ft-node ft-node--root";
    wrapper.setAttribute("data-id", id);

    const btn = document.createElement("button");
    btn.className = "ft-card ft-card--root";
    btn.type      = "button";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "ft-children-" + id);

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

    btn.appendChild(buildAvatar(node, { root: true }));
    btn.appendChild(inner);
    wrapper.appendChild(btn);

    const helper = document.createElement("p");
    helper.className   = "ft-helper";
    helper.id          = "ft-helper";
    helper.textContent = "Click Joel Mokyr to open the tree.";
    wrapper.appendChild(helper);

    const ul = document.createElement("ul");
    ul.className = "ft-children ft-children--root";
    ul.id        = "ft-children-" + id;
    ul.hidden    = true;
    wrapper.appendChild(ul);

    treeRoot.appendChild(wrapper);

    btn.addEventListener("click", function () {
      toggleRoot(wrapper, btn, ul, helper);
    });
  }

  function buildBranchNode(id) {
    const node  = GENEALOGY.peopleById[id] || {};
    const desc  = GENEALOGY.descendantCountById[id] || 0;
    const meta  = buildMeta(node);
    const hasChildren = desc > 0;

    const li = document.createElement("li");
    li.className = "ft-node";
    li.setAttribute("data-id", id);

    const btn = document.createElement("button");
    btn.className = "ft-card";
    btn.type      = "button";
    if (hasChildren) {
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("aria-controls", "ft-children-" + id);
    }

    const expandIcon = document.createElement("span");
    expandIcon.className = "ft-expand-icon";
    expandIcon.setAttribute("aria-hidden", "true");
    expandIcon.textContent = hasChildren ? "\u25b8" : "\u00b7"; // ▸ or middle dot
    if (!hasChildren) expandIcon.classList.add("ft-expand-icon--leaf");

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
    btn.appendChild(buildAvatar(node));
    btn.appendChild(inner);
    li.appendChild(btn);

    if (hasChildren) {
      const ul = document.createElement("ul");
      ul.className = "ft-children";
      ul.id        = "ft-children-" + id;
      ul.hidden    = true;
      li.appendChild(ul);

      btn.addEventListener("click", function () {
        toggleBranch(li, btn, expandIcon, ul);
      });
    }

    return li;
  }

  // ── Expand / collapse ───────────────────────────────────────────────────────

  function collapseBranch(li) {
    const btn  = li.querySelector(":scope > .ft-card");
    const icon = btn ? btn.querySelector(".ft-expand-icon") : null;
    const ul   = li.querySelector(":scope > .ft-children");
    if (btn && btn.hasAttribute("aria-expanded")) {
      btn.setAttribute("aria-expanded", "false");
      btn.classList.remove("is-expanded");
    }
    if (icon) icon.classList.remove("is-expanded");
    if (ul)   { ul.hidden = true; ul.innerHTML = ""; }
  }

  function renderChildren(id, ul) {
    const allChildIds = GENEALOGY.childrenById[id] || [];
    const childIds    = allChildIds.filter(function (cid) {
      return GENEALOGY.primaryParentById[cid] === id;
    });
    const sorted = sortByDescThenLabel(childIds);
    sorted.forEach(function (childId) {
      ul.appendChild(buildBranchNode(childId));
    });
  }

  function toggleRoot(wrapper, btn, ul, helper) {
    const isExpanded = btn.getAttribute("aria-expanded") === "true";
    if (isExpanded) {
      ul.hidden    = true;
      ul.innerHTML = "";
      btn.setAttribute("aria-expanded", "false");
      btn.classList.remove("is-expanded");
      if (helper) helper.hidden = false;
    } else {
      ul.innerHTML = "";
      renderChildren(GENEALOGY.ROOT_ID, ul);
      ul.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      btn.classList.add("is-expanded");
      if (helper) helper.hidden = true;
      if (isMobile()) scrollTargetIntoView(firstRenderedChildCard(ul), "start");
    }
  }

  function openBranch(li, btn, expandIcon, ul) {
    renderChildren(li.getAttribute("data-id"), ul);
    ul.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    btn.classList.add("is-expanded");
    if (expandIcon) expandIcon.classList.add("is-expanded");
  }

  function toggleBranch(li, btn, expandIcon, ul) {
    const isExpanded = btn.getAttribute("aria-expanded") === "true";
    if (isExpanded) {
      collapseBranch(li);
      return;
    }
    // Collapse any expanded sibling at the same depth to keep single-open
    // progressive reveal during normal browsing.
    const parent = li.parentElement;
    if (parent) {
      Array.from(parent.children).forEach(function (sib) {
        if (sib !== li) {
          const sibBtn = sib.querySelector(":scope > .ft-card");
          if (sibBtn && sibBtn.getAttribute("aria-expanded") === "true") {
            collapseBranch(sib);
          }
        }
      });
    }
    openBranch(li, btn, expandIcon, ul);
    if (isMobile()) scrollTargetIntoView(firstRenderedChildCard(ul), "start");
  }

  function scrollTargetIntoView(target, block) {
    if (!target) return;
    // Defer two frames so nested branches have fully laid out before scroll.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        const behavior = prefersReducedMotion() ? "auto" : "smooth";
        try {
          target.scrollIntoView({ behavior: behavior, block: block || "nearest", inline: "nearest" });
        } catch (_) {
          target.scrollIntoView();
        }
      });
    });
  }

  // ── Search ──────────────────────────────────────────────────────────────────

  function getAncestorIds(id) {
    const ancestors = [];
    let current = GENEALOGY.primaryParentById ? GENEALOGY.primaryParentById[id] : null;
    while (current && current !== GENEALOGY.ROOT_ID) {
      ancestors.unshift(current);
      current = GENEALOGY.primaryParentById ? GENEALOGY.primaryParentById[current] : null;
    }
    if (current === GENEALOGY.ROOT_ID) ancestors.unshift(GENEALOGY.ROOT_ID);
    return ancestors;
  }

  function expandNodeIfCollapsed(ancEl) {
    if (!ancEl) return;
    const btn = ancEl.querySelector(":scope > .ft-card");
    if (!btn || btn.getAttribute("aria-expanded") !== "false") return;
    if (ancEl.classList.contains("ft-node--root")) {
      const ul     = ancEl.querySelector(":scope > .ft-children");
      const helper = ancEl.querySelector(".ft-helper");
      toggleRoot(ancEl, btn, ul, helper);
    } else {
      const icon = btn.querySelector(".ft-expand-icon");
      const ul   = ancEl.querySelector(":scope > .ft-children");
      // Use openBranch, not toggleBranch — otherwise multi-match search
      // reveals would collapse previously-opened sibling branches.
      if (ul) openBranch(ancEl, btn, icon, ul);
    }
  }

  function ensureVisible(id) {
    const ancestorIds = getAncestorIds(id);
    ancestorIds.forEach(function (ancId) {
      const ancEl = treeRoot.querySelector('[data-id="' + ancId + '"]');
      expandNodeIfCollapsed(ancEl);
    });
    const parentId = GENEALOGY.primaryParentById ? GENEALOGY.primaryParentById[id] : null;
    if (parentId) {
      expandNodeIfCollapsed(treeRoot.querySelector('[data-id="' + parentId + '"]'));
    }
  }

  function announceSearch(count, query) {
    if (!searchStatus) return;
    if (!query) {
      searchStatus.textContent = "";
      lastAnnouncedCount = -1;
      return;
    }
    if (count === lastAnnouncedCount) return;
    lastAnnouncedCount = count;
    let message;
    if (count === 0)      message = "No results found.";
    else if (count === 1) message = "1 result found.";
    else                  message = count + " results found.";
    searchStatus.textContent = message;
  }

  function runSearch(rawQuery) {
    const query = (rawQuery || "").trim();

    // Clear previous highlights up front.
    treeRoot.querySelectorAll(".ft-match").forEach(function (el) {
      el.classList.remove("ft-match");
    });

    if (!query) {
      treeRoot.classList.remove("ft-search-active");
      announceSearch(0, "");
      rootAutoExpanded = false;
      return;
    }

    treeRoot.classList.add("ft-search-active");

    const lower   = query.toLowerCase();
    const allIds  = Object.keys(GENEALOGY.peopleById);
    const matches = allIds.filter(function (id) {
      const label = (GENEALOGY.peopleById[id].label || "").toLowerCase();
      return label.includes(lower);
    });

    // Auto-expand root when the user begins a meaningful search and root
    // is still collapsed — otherwise matches can never surface.
    const rootEl   = treeRoot.querySelector('[data-id="' + GENEALOGY.ROOT_ID + '"]');
    const rootBtn  = rootEl ? rootEl.querySelector(":scope > .ft-card") : null;
    const rootOpen = rootBtn && rootBtn.getAttribute("aria-expanded") === "true";

    if (!rootOpen && matches.length > 0 && !rootAutoExpanded) {
      expandNodeIfCollapsed(rootEl);
      rootAutoExpanded = true;
    }

    const rootOpenNow = rootBtn && rootBtn.getAttribute("aria-expanded") === "true";

    // Expand ancestor paths when the match set is small enough to be useful.
    if (matches.length > 0 && matches.length < 20 && rootOpenNow) {
      matches.forEach(function (id) { ensureVisible(id); });
    }

    // Highlight whatever is now rendered.
    matches.forEach(function (id) {
      const el = treeRoot.querySelector('[data-id="' + id + '"]');
      if (el) el.classList.add("ft-match");
    });

    announceSearch(matches.length, query);
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      clearTimeout(searchTimer);
      const query = searchInput.value;
      searchTimer = setTimeout(function () { runSearch(query); }, 200);
    });
  }

  // ── Tab (mode) switching ────────────────────────────────────────────────────

  function shouldInjectIframe() {
    return !isMobile();
  }

  function syncNetworkPanelView() {
    if (!networkPanel) return;
    const mobile = isMobile();
    if (networkShell)    networkShell.hidden    = mobile;
    if (networkFallback) networkFallback.hidden = !mobile;
    if (!mobile && !networkInjected && !networkPanel.hasAttribute("hidden")) {
      injectNetworkIframe();
    }
  }

  function injectNetworkIframe() {
    if (networkInjected || !networkShell) return;
    const iframe = document.createElement("iframe");
    iframe.src   = "../network/mokyr-genealogy.html";
    iframe.title = "Joel Mokyr academic genealogy visualization";
    iframe.setAttribute("loading", "lazy");
    networkShell.appendChild(iframe);
    networkInjected = true;
  }

  function activateMode(mode, options) {
    const opts        = options || {};
    const focusPanel  = !!opts.focusPanel;
    const updateHash  = opts.updateHash !== false;
    const isTree      = mode === "tree";
    const isNetwork   = mode === "network";

    tabs.forEach(function (tab) {
      const tabMode   = tab.getAttribute("data-ft-mode");
      const isActive  = tabMode === mode;
      tab.classList.toggle("is-active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
      tab.setAttribute("tabindex", isActive ? "0" : "-1");
    });

    if (isTree) {
      treePanel.removeAttribute("hidden");
      if (networkPanel) networkPanel.setAttribute("hidden", "");
    } else if (isNetwork) {
      if (networkPanel) networkPanel.removeAttribute("hidden");
      treePanel.setAttribute("hidden", "");
      // Sync visibility of shell vs fallback based on viewport.
      syncNetworkPanelView();
      if (shouldInjectIframe()) injectNetworkIframe();
    }

    if (updateHash) {
      history.replaceState(null, "", isNetwork ? "#network" : "#tree");
    }

    if (focusPanel) {
      const panel = isNetwork ? networkPanel : treePanel;
      if (panel && typeof panel.focus === "function") {
        panel.focus({ preventScroll: true });
      }
    }
  }

  function focusTab(tab) {
    if (!tab) return;
    tab.focus();
    activateMode(tab.getAttribute("data-ft-mode"), { focusPanel: false });
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      activateMode(tab.getAttribute("data-ft-mode"), { focusPanel: false });
    });
    tab.addEventListener("keydown", function (e) {
      const key = e.key;
      if (key === "ArrowRight" || key === "ArrowDown") {
        e.preventDefault();
        focusTab(tabs[(index + 1) % tabs.length]);
      } else if (key === "ArrowLeft" || key === "ArrowUp") {
        e.preventDefault();
        focusTab(tabs[(index - 1 + tabs.length) % tabs.length]);
      } else if (key === "Home") {
        e.preventDefault();
        focusTab(tabs[0]);
      } else if (key === "End") {
        e.preventDefault();
        focusTab(tabs[tabs.length - 1]);
      } else if (key === "Enter" || key === " ") {
        e.preventDefault();
        activateMode(tab.getAttribute("data-ft-mode"), { focusPanel: true });
      }
    });
  });

  // React to viewport crossing the mobile breakpoint while network panel is open.
  if (typeof MOBILE_MQ.addEventListener === "function") {
    MOBILE_MQ.addEventListener("change", function () {
      if (networkPanel && !networkPanel.hasAttribute("hidden")) {
        syncNetworkPanelView();
      }
    });
  }

  // ── Init ────────────────────────────────────────────────────────────────────

  function init() {
    if (typeof GENEALOGY === "undefined") {
      console.warn("family-tree.js: GENEALOGY global not found. Is genealogy-data.js loaded?");
      return;
    }

    buildRootNode();

    const hash = window.location.hash;
    if (hash === "#tree") {
      activateMode("tree", { updateHash: false });
    } else {
      activateMode("network", { updateHash: false });
    }
  }

  document.addEventListener("DOMContentLoaded", init);

})();
