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

const previewCard = document.querySelector("[data-preview-card]");

if (previewCard && !prefersReducedMotion) {
  const resetCard = () => {
    previewCard.style.transform = "";
  };

  previewCard.addEventListener("pointermove", (event) => {
    const bounds = previewCard.getBoundingClientRect();
    const rotateY = ((event.clientX - bounds.left) / bounds.width - 0.5) * 10;
    const rotateX = (0.5 - (event.clientY - bounds.top) / bounds.height) * 8;

    previewCard.style.transform =
      `perspective(1600px) rotateY(${rotateY.toFixed(2)}deg) rotateX(${rotateX.toFixed(2)}deg)`;
  });

  previewCard.addEventListener("pointerleave", resetCard);
  previewCard.addEventListener("pointercancel", resetCard);
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
      { threshold: 0.45 }
    );

    countUpElements.forEach((element) => countObserver.observe(element));
  }
}

const storySteps = [...document.querySelectorAll("[data-story-step]")];
const storyNavItems = [...document.querySelectorAll("[data-story-nav-item]")];

if (storySteps.length && storyNavItems.length) {
  const setActiveStoryStep = (stepId) => {
    storyNavItems.forEach((item) => {
      item.classList.toggle("is-active", item.dataset.storyNavItem === stepId);
    });
  };

  setActiveStoryStep(storySteps[0].dataset.storyStep);

  if (!prefersReducedMotion) {
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
}
