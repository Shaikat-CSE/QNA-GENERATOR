(() => {
  const inputs = document.querySelectorAll("[data-search-input]");

  for (const input of inputs) {
    const scope = input.closest(".section-block, .site-main");
    const container = scope ? scope.querySelector("[data-search-container]") : null;
    if (!container) {
      continue;
    }

    const items = Array.from(container.querySelectorAll("[data-search-item]"));
    input.addEventListener("input", () => {
      const query = input.value.trim().toLowerCase();
      for (const item of items) {
        const haystack = (item.getAttribute("data-search") || "").toLowerCase();
        item.classList.toggle("is-hidden", Boolean(query) && !haystack.includes(query));
      }
    });
  }

  const toggles = document.querySelectorAll("[data-toggle-target]");
  for (const toggle of toggles) {
    toggle.addEventListener("click", () => {
      const targetSelector = toggle.getAttribute("data-toggle-target");
      if (!targetSelector) {
        return;
      }
      const target = document.querySelector(targetSelector);
      if (!target) {
        return;
      }
      target.toggleAttribute("hidden");
    });
  }
})();
