// lineage-stats.js - generated from Network_Nodes_040126.csv and Network_Edges_040126.csv.
// Provides one site-wide source of truth for public lineage counts.

window.LINEAGE_STATS = {"scholarCount": 387, "descendantCount": 387, "personCount": 388, "generationCount": 4, "directStudentCount": 78, "generation1Count": 78, "generation2Count": 167, "generation3Count": 137, "generation4Count": 5, "generationOneToThreeScholarCount": 382};

(function () {
  const stats = window.LINEAGE_STATS || {};
  const numberFormatter = new Intl.NumberFormat('en-US');

  function formatValue(value) {
    return typeof value === 'number' ? numberFormatter.format(value) : String(value || '');
  }

  function renderTemplate(template) {
    return String(template || '').replace(/\{([A-Za-z0-9_]+)\}/g, function (_, key) {
      return formatValue(stats[key]);
    });
  }

  function hydrate(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-lineage-stat]').forEach(function (element) {
      const key = element.getAttribute('data-lineage-stat');
      const value = stats[key];
      if (value === undefined || value === null) return;
      element.textContent = formatValue(value);
      if (element.hasAttribute('data-count-to')) {
        element.setAttribute('data-count-to', String(value));
      }
    });

    scope.querySelectorAll('[data-lineage-template]').forEach(function (element) {
      element.textContent = renderTemplate(element.getAttribute('data-lineage-template'));
    });
  }

  hydrate(document);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { hydrate(document); });
  }
})();
