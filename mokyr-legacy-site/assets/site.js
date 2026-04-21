const revealTargets = [
  ...document.querySelectorAll("[data-reveal]"),
  ...document.querySelectorAll("[data-reveal-group]"),
];

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

const storySteps = [...document.querySelectorAll("[data-story-step]")];
const storyNavItems = [...document.querySelectorAll("[data-story-nav-item]")];

if (storySteps.length && storyNavItems.length) {
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
