const revealTargets = [
  ...document.querySelectorAll("[data-reveal]"),
  ...document.querySelectorAll("[data-reveal-group]"),
];

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const homeGate = document.querySelector(".page-home .entry-gate");
const homeMain = document.querySelector(".page-home .home-main");

if (document.body.classList.contains("page-home")) {
  const exploreHome = () => {
    document.body.classList.add("is-explored");
    window.setTimeout(
      () => {
        if (homeGate) {
          homeGate.setAttribute("hidden", "");
        }
        if (homeMain) {
          homeMain.focus({ preventScroll: true });
        }
      },
      prefersReducedMotion ? 0 : 1000
    );
  };

  if (homeGate) {
    homeGate.addEventListener("click", exploreHome, { once: true });
  } else {
    document.body.classList.add("is-explored");
  }
}

if (prefersReducedMotion) {
  revealTargets.forEach((element) => element.classList.add("is-visible"));
} else {
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          return;
        }
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      });
    },
    { threshold: 0.18 }
  );

  revealTargets.forEach((element) => revealObserver.observe(element));
}

const countUpElements = document.querySelectorAll("[data-count-to]");

const formatCount = (element, value) => {
  if (element.dataset.numberFormat === "plain") {
    return String(value);
  }

  return value.toLocaleString();
};

const animateCount = (element) => {
  if (element.dataset.counted === "true") {
    return;
  }

  const target = Number(element.dataset.countTo);
  if (!Number.isFinite(target)) {
    return;
  }

  element.dataset.counted = "true";

  if (prefersReducedMotion) {
    element.textContent = formatCount(element, target);
    return;
  }

  const duration = 1200;
  const start = performance.now();

  const frame = (time) => {
    const progress = Math.min((time - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = Math.round(target * eased);

    element.textContent = formatCount(element, value);

    if (progress < 1) {
      window.requestAnimationFrame(frame);
    }
  };

  window.requestAnimationFrame(frame);
};

if (countUpElements.length) {
  if (prefersReducedMotion) {
    countUpElements.forEach(animateCount);
  } else {
    const countObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }
          animateCount(entry.target);
          countObserver.unobserve(entry.target);
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -80px 0px" }
    );

    countUpElements.forEach((element) => countObserver.observe(element));
  }
}

const countryViewRoots = [...document.querySelectorAll("[data-country-view-root]")];

countryViewRoots.forEach((root) => {
  const buttons = [...root.querySelectorAll("[data-country-view-button]")];
  const panels = [...root.querySelectorAll("[data-country-view-panel]")];

  if (!buttons.length || !panels.length) {
    return;
  }

  const activateCountryView = (button) => {
    const view = button.dataset.countryViewButton;

    buttons.forEach((candidate) => {
      const isActive = candidate === button;
      candidate.classList.toggle("is-active", isActive);
      candidate.setAttribute("aria-selected", isActive ? "true" : "false");
      candidate.setAttribute("tabindex", isActive ? "0" : "-1");
    });

    panels.forEach((panel) => {
      if (panel.dataset.countryViewPanel === view) {
        panel.removeAttribute("hidden");
        panel.classList.add("is-active");
      } else {
        panel.setAttribute("hidden", "");
        panel.classList.remove("is-active");
      }
    });
  };

  const focusCountryButton = (button) => {
    if (!button) {
      return;
    }

    button.focus();
    activateCountryView(button);
  };

  buttons.forEach((button, index) => {
    button.addEventListener("click", () => activateCountryView(button));

    button.addEventListener("keydown", (event) => {
      const { key } = event;

      if (key === "ArrowRight" || key === "ArrowDown") {
        event.preventDefault();
        focusCountryButton(buttons[(index + 1) % buttons.length]);
      } else if (key === "ArrowLeft" || key === "ArrowUp") {
        event.preventDefault();
        focusCountryButton(buttons[(index - 1 + buttons.length) % buttons.length]);
      } else if (key === "Home") {
        event.preventDefault();
        focusCountryButton(buttons[0]);
      } else if (key === "End") {
        event.preventDefault();
        focusCountryButton(buttons[buttons.length - 1]);
      }
    });
  });

  const initialButton =
    buttons.find((button) => button.getAttribute("aria-selected") === "true") || buttons[0];

  activateCountryView(initialButton);
});

const tierForCountryCount = (count) => {
  if (count >= 100) return "largest";
  if (count >= 10) return "large";
  if (count >= 4) return "medium";
  return "small";
};

const countryMapRoots = [...document.querySelectorAll("[data-country-map-root]")];

countryMapRoots.forEach((root) => {
  const map = root.querySelector("[data-country-map]");
  const sourceRows = [...root.querySelectorAll("[data-country-map-source] [data-country-iso]")];

  if (!map || !sourceRows.length) {
    return;
  }

  const tooltip = map.querySelector(".country-map-tooltip");
  const loading = map.querySelector("[data-country-map-loading]");
  const fallback = map.querySelector(".country-map-fallback");
  const tooltipId = tooltip?.id || "country-map-tooltip";
  const countryData = sourceRows
    .map((row) => ({
      iso: row.dataset.countryIso,
      name: row.dataset.countryName || row.querySelector("span")?.textContent?.trim() || row.dataset.countryIso,
      count: Number(row.dataset.countryCount || row.querySelector("b")?.textContent?.replace(/[^\d]/g, "") || 0),
    }))
    .filter((country) => country.iso && country.count > 0);

  const hideTooltip = () => {
    if (tooltip) tooltip.hidden = true;
  };

  const positionTooltip = (clientX, clientY) => {
    if (!tooltip) return;

    const mapRect = map.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();
    const x = Math.max(8, Math.min(clientX - mapRect.left + 16, mapRect.width - tipRect.width - 8));
    const y = Math.max(8, Math.min(clientY - mapRect.top + 16, mapRect.height - tipRect.height - 8));
    tooltip.style.transform = `translate(${x}px, ${y}px)`;
  };

  const showTooltip = (country, clientX, clientY) => {
    if (!tooltip) return;

    const count = Number(country.dataset.count || 0);
    tooltip.innerHTML = `<strong>${country.dataset.country}</strong><span>${count.toLocaleString()} mapped scholar${count === 1 ? "" : "s"}</span>`;
    tooltip.hidden = false;
    positionTooltip(clientX, clientY);
  };

  const installCountrySvg = (svg) => {
    if (!svg) {
      throw new Error("Map SVG missing root element");
    }

    svg.querySelectorAll("style").forEach((style) => style.remove());
    svg.classList.add("country-world-map");
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Countries with mapped scholars shaded by current residence count.");

    svg.querySelectorAll(".country").forEach((country) => {
      country.setAttribute("vector-effect", "non-scaling-stroke");
    });

    countryData.forEach(({ iso, name, count }) => {
      const country = svg.querySelector(`#${iso}`) || svg.querySelector(`.${iso}`) || svg.querySelector(`#${iso}-circle`);
      if (!country) return;

      country.classList.add("country-map-country");
      country.dataset.country = name;
      country.dataset.count = String(count);
      country.dataset.tier = tierForCountryCount(count);
      country.setAttribute("tabindex", "0");
      country.setAttribute("aria-describedby", tooltipId);
      country.setAttribute("aria-label", `${name}: ${count.toLocaleString()} mapped scholar${count === 1 ? "" : "s"}`);

      country.addEventListener("pointerenter", (event) => showTooltip(country, event.clientX, event.clientY));
      country.addEventListener("pointermove", (event) => showTooltip(country, event.clientX, event.clientY));
      country.addEventListener("pointerleave", hideTooltip);
      country.addEventListener("click", (event) => {
        event.preventDefault();
        showTooltip(country, event.clientX, event.clientY);
      });
      country.addEventListener("mouseenter", (event) => showTooltip(country, event.clientX, event.clientY));
      country.addEventListener("mousemove", (event) => showTooltip(country, event.clientX, event.clientY));
      country.addEventListener("mouseleave", hideTooltip);
      country.addEventListener("focus", () => {
        const rect = country.getBoundingClientRect();
        showTooltip(country, rect.left + rect.width / 2, rect.top + rect.height / 2);
      });
      country.addEventListener("blur", hideTooltip);
      country.addEventListener("keydown", (event) => {
        if (event.key === "Escape") hideTooltip();
      });
    });

    map.insertBefore(svg, fallback || loading || tooltip);
    map.classList.add("is-loaded");
  };

  const embeddedSvg = document.getElementById("country-world-map-template")?.content?.querySelector("svg");

  if (embeddedSvg) {
    installCountrySvg(embeddedSvg.cloneNode(true));
    return;
  }

  fetch(new URL("../assets/images/world-map-equal-earth.svg?v=20260515b", window.location.href))
    .then((response) => {
      if (!response.ok) throw new Error(`Map request failed: ${response.status}`);
      return response.text();
    })
    .then((svgText) => {
      const parsed = new DOMParser().parseFromString(svgText, "image/svg+xml");
      installCountrySvg(parsed.querySelector("svg"));
    })
    .catch(() => {
      if (loading) loading.textContent = "Interactive map unavailable in this browser context.";
    });
});

const storySteps = [...document.querySelectorAll("[data-story-step]")];
const storyNavItems = [...document.querySelectorAll("[data-story-nav-item]")];

const setActiveStoryStep = (stepId) => {
  storyNavItems.forEach((item) => {
    const isActive = item.dataset.storyNavItem === stepId;
    item.classList.toggle("is-active", isActive);
    if (isActive) {
      item.setAttribute("aria-current", "location");
    } else {
      item.removeAttribute("aria-current");
    }
  });
};

if (storySteps.length) {
  setActiveStoryStep(storySteps[0].dataset.storyStep);

  const storyObserver = new IntersectionObserver(
    (entries) => {
      const visibleEntries = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);

      if (!visibleEntries.length) {
        return;
      }

      setActiveStoryStep(visibleEntries[0].target.dataset.storyStep);
    },
    {
      rootMargin: "-30% 0px -30% 0px",
      threshold: [0.2, 0.45, 0.7],
    }
  );

  storySteps.forEach((step) => storyObserver.observe(step));
}

const presentationStart = document.querySelector("[data-presentation-start]");
const presentationControls = document.querySelector("[data-presentation-controls]");
const presentationPrev = document.querySelector("[data-presentation-prev]");
const presentationNext = document.querySelector("[data-presentation-next]");
const presentationExit = document.querySelector("[data-presentation-exit]");
const presentationCounter = document.querySelector("[data-presentation-counter]");

if (
  storySteps.length &&
  presentationStart &&
  presentationControls &&
  presentationPrev &&
  presentationNext &&
  presentationExit
) {
  let presentationIndex = 0;
  let presentationScrollY = 0;
  let presentationUsedFullscreen = false;
  let presentationRevealTimer = null;
  const presentationContentDelay = prefersReducedMotion ? 0 : 950;

  const clampPresentationIndex = (index) =>
    Math.max(0, Math.min(storySteps.length - 1, index));

  const getCurrentStoryIndex = () => {
    const hash = window.location.hash ? decodeURIComponent(window.location.hash.slice(1)) : "";
    const hashIndex = storySteps.findIndex((step) => step.id === hash);

    if (hashIndex >= 0) {
      return hashIndex;
    }

    let closestIndex = 0;
    let closestDistance = Infinity;

    storySteps.forEach((step, index) => {
      const distance = Math.abs(step.getBoundingClientRect().top);
      if (distance < closestDistance) {
        closestDistance = distance;
        closestIndex = index;
      }
    });

    return closestIndex;
  };

  const revealPresentationSlide = (slide) => {
    slide.classList.add("is-visible");
    slide.querySelectorAll("[data-reveal], [data-reveal-group]").forEach((element) => {
      element.classList.add("is-visible");
    });
    slide.querySelectorAll("[data-count-to]").forEach(animateCount);
  };

  const updatePresentationHash = (slide) => {
    if (!slide.id) {
      return;
    }

    const nextUrl = `${window.location.pathname}${window.location.search}#${slide.id}`;
    window.history.replaceState(null, "", nextUrl);
  };

  const setPresentationContentReady = (slide) => {
    if (presentationRevealTimer) {
      window.clearTimeout(presentationRevealTimer);
      presentationRevealTimer = null;
    }

    storySteps.forEach((step) => step.classList.remove("is-presentation-content-ready"));

    if (!slide) {
      return;
    }

    const markReady = () => {
      slide.classList.add("is-presentation-content-ready");
      presentationRevealTimer = null;
    };

    if (presentationContentDelay === 0) {
      markReady();
    } else {
      presentationRevealTimer = window.setTimeout(markReady, presentationContentDelay);
    }
  };

  const updatePresentationSlide = (index, options) => {
    const opts = options || {};
    presentationIndex = clampPresentationIndex(index);

    storySteps.forEach((step, stepIndex) => {
      const isActive = stepIndex === presentationIndex;
      step.classList.toggle("is-presentation-active", isActive);
      step.classList.toggle("is-presentation-before", stepIndex < presentationIndex);
      step.classList.toggle("is-presentation-after", stepIndex > presentationIndex);

      if (isActive) {
        step.removeAttribute("aria-hidden");
        revealPresentationSlide(step);
      } else {
        step.setAttribute("aria-hidden", "true");
      }
    });

    const activeSlide = storySteps[presentationIndex];
    setPresentationContentReady(activeSlide);
    setActiveStoryStep(activeSlide.dataset.storyStep);

    if (presentationCounter) {
      presentationCounter.textContent = `${presentationIndex + 1} / ${storySteps.length}`;
    }

    presentationPrev.disabled = presentationIndex === 0;
    presentationNext.disabled = presentationIndex === storySteps.length - 1;

    if (opts.updateHash !== false) {
      updatePresentationHash(activeSlide);
    }
  };

  const enterPresentation = async () => {
    presentationScrollY = window.scrollY;
    presentationControls.hidden = false;
    presentationStart.setAttribute("aria-pressed", "true");
    document.documentElement.classList.add("presentation-lock");
    document.body.classList.add("is-presentation-arming", "is-presenting");
    updatePresentationSlide(getCurrentStoryIndex(), { updateHash: true });
    window.requestAnimationFrame(() => {
      document.body.classList.remove("is-presentation-arming");
    });

    try {
      if (document.documentElement.requestFullscreen && !document.fullscreenElement) {
        await document.documentElement.requestFullscreen({ navigationUI: "hide" });
        presentationUsedFullscreen = !!document.fullscreenElement;
      }
    } catch (error) {
      presentationUsedFullscreen = false;
      // Presentation mode still works when the browser declines fullscreen.
    }
  };

  const exitPresentation = async (options) => {
    const opts = options || {};

    if (!document.body.classList.contains("is-presenting")) {
      return;
    }

    document.documentElement.classList.remove("presentation-lock");
    document.body.classList.remove("is-presenting", "is-presentation-arming");
    presentationControls.hidden = true;
    presentationStart.setAttribute("aria-pressed", "false");

    if (presentationRevealTimer) {
      window.clearTimeout(presentationRevealTimer);
      presentationRevealTimer = null;
    }

    storySteps.forEach((step) => {
      step.classList.remove(
        "is-presentation-active",
        "is-presentation-before",
        "is-presentation-after",
        "is-presentation-content-ready"
      );
      step.removeAttribute("aria-hidden");
    });

    if (!opts.skipFullscreen && document.fullscreenElement && document.exitFullscreen) {
      try {
        await document.exitFullscreen();
      } catch (error) {
        // Leaving the slide layout is the important part; fullscreen may already be gone.
      }
    }

    presentationUsedFullscreen = false;

    window.requestAnimationFrame(() => {
      const activeSlide = storySteps[presentationIndex];
      if (activeSlide) {
        activeSlide.scrollIntoView({ block: "start", behavior: "auto" });
      } else {
        window.scrollTo({ top: presentationScrollY, behavior: "auto" });
      }
    });
  };

  presentationStart.addEventListener("click", () => {
    enterPresentation();
  });

  presentationPrev.addEventListener("click", () => {
    updatePresentationSlide(presentationIndex - 1);
  });

  presentationNext.addEventListener("click", () => {
    updatePresentationSlide(presentationIndex + 1);
  });

  presentationExit.addEventListener("click", () => {
    exitPresentation();
  });

  document.addEventListener("keydown", (event) => {
    if (!document.body.classList.contains("is-presenting")) {
      return;
    }

    if (event.metaKey || event.ctrlKey || event.altKey) {
      return;
    }

    const activeElement = document.activeElement;
    const activeTag = activeElement ? activeElement.tagName : "";

    if ((activeTag === "BUTTON" || activeTag === "A") && (event.key === " " || event.key === "Enter")) {
      return;
    }

    if (event.key === "ArrowRight" || event.key === "ArrowDown" || event.key === "PageDown" || event.key === " ") {
      event.preventDefault();
      updatePresentationSlide(presentationIndex + 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp" || event.key === "PageUp") {
      event.preventDefault();
      updatePresentationSlide(presentationIndex - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      updatePresentationSlide(0);
    } else if (event.key === "End") {
      event.preventDefault();
      updatePresentationSlide(storySteps.length - 1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      exitPresentation();
    }
  });

  document.addEventListener("fullscreenchange", () => {
    if (document.fullscreenElement) {
      presentationUsedFullscreen = true;
      return;
    }

    presentationUsedFullscreen = false;
  });

  if (new URLSearchParams(window.location.search).get("present") === "1") {
    window.requestAnimationFrame(() => {
      enterPresentation();
    });
  }
}

const lineagePanel = document.querySelector("#lineage");
const lineageTabs = lineagePanel
  ? [...lineagePanel.querySelectorAll('[role="tab"]')]
  : [];

if (lineageTabs.length) {
  const activateLineageTab = (tab, options) => {
    const opts = options || {};
    const focusPanel = !!opts.focusPanel;

    lineageTabs.forEach((candidate) => {
      const panelId = candidate.getAttribute("aria-controls");
      const panel = panelId ? document.getElementById(panelId) : null;
      const isActive = candidate === tab;

      candidate.classList.toggle("is-active", isActive);
      candidate.setAttribute("aria-selected", isActive ? "true" : "false");
      candidate.setAttribute("tabindex", isActive ? "0" : "-1");

      if (!panel) {
        return;
      }

      if (isActive) {
        panel.removeAttribute("hidden");
      } else {
        panel.setAttribute("hidden", "");
      }
    });

    if (focusPanel) {
      const panelId = tab.getAttribute("aria-controls");
      const panel = panelId ? document.getElementById(panelId) : null;
      if (panel && typeof panel.focus === "function") {
        panel.focus({ preventScroll: true });
      }
    }
  };

  const focusLineageTab = (tab) => {
    if (!tab) {
      return;
    }

    tab.focus();
    activateLineageTab(tab, { focusPanel: false });
  };

  lineageTabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      activateLineageTab(tab, { focusPanel: false });
    });

    tab.addEventListener("keydown", (event) => {
      const { key } = event;

      if (key === "ArrowRight" || key === "ArrowDown") {
        event.preventDefault();
        focusLineageTab(lineageTabs[(index + 1) % lineageTabs.length]);
      } else if (key === "ArrowLeft" || key === "ArrowUp") {
        event.preventDefault();
        focusLineageTab(lineageTabs[(index - 1 + lineageTabs.length) % lineageTabs.length]);
      } else if (key === "Home") {
        event.preventDefault();
        focusLineageTab(lineageTabs[0]);
      } else if (key === "End") {
        event.preventDefault();
        focusLineageTab(lineageTabs[lineageTabs.length - 1]);
      } else if (key === "Enter" || key === " ") {
        event.preventDefault();
        activateLineageTab(tab, { focusPanel: true });
      }
    });
  });

  const initialLineageTab =
    lineageTabs.find((tab) => tab.getAttribute("aria-selected") === "true") ||
    lineageTabs[0];

  activateLineageTab(initialLineageTab, { focusPanel: false });
}
