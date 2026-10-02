// =========================================================================
// ui/pagination.js
// Shared "Prev | Page [x] of Y | Next" bar used by every server-paginated
// list in the app (Purchases/Sales bills, Items, Stock Valuation, Reports
// bill lists). Replaces the old "Load next 100" pattern: switching page
// now shows ONLY that page's rows -- the previous page's data is cleared,
// nothing is appended/accumulated.
//
// Usage:
//   renderPaginationBar('pb-pagination', page, pageSize, total, (newPage) => {
//     ...fetch newPage and re-render...
//   });
//
// Call this after every successful fetch, passing the page/total the
// server just returned. Pass total=0 (or omit) to hide the bar.
//
// Loader usage:
//   showPageLoader('pb-bills-wrapper', currentRowCount);  // before fetch
//   hidePageLoader('pb-bills-wrapper');                   // after fetch
// =========================================================================

// ── Pagination Loader ─────────────────────────────────────────────────────
// Shows a shimmer skeleton inside `wrapperId` while the next page is loading.
// Displayed only if the fetch takes longer than LOADER_DELAY_MS (avoids
// flashing a spinner on fast responses).

const LOADER_DELAY_MS = 250; // only show loader if fetch takes > 250ms
const _loaderTimers = {};    // wrapperId -> setTimeout handle

/**
 * Call BEFORE starting a page fetch.
 * Replaces the wrapper content with a skeleton shimmer after LOADER_DELAY_MS.
 * @param {string} wrapperId  - id of the bills wrapper div
 * @param {number} [rowHint]  - how many skeleton rows to render (defaults to 5)
 */
function showPageLoader(wrapperId, rowHint) {
  // Disable pagination buttons immediately so user can't double-click
  document.querySelectorAll('.pg-btn').forEach(btn => btn.disabled = true);

  // Delay the visual skeleton so instant fetches don't flash
  _loaderTimers[wrapperId] = setTimeout(() => {
    const wrapper = document.getElementById(wrapperId);
    if (!wrapper) return;
    const count = Math.min(Math.max(rowHint || 5, 3), 12);
    wrapper.innerHTML = _buildSkeletonHTML(count);
  }, LOADER_DELAY_MS);
}

/**
 * Call AFTER the page fetch completes (success or error).
 * Cancels the pending skeleton timer (if still waiting) and re-enables buttons.
 * @param {string} wrapperId  - id of the bills wrapper div
 */
function hidePageLoader(wrapperId) {
  clearTimeout(_loaderTimers[wrapperId]);
  delete _loaderTimers[wrapperId];
  // Buttons are re-enabled naturally when renderPaginationBar re-renders them
}

function _buildSkeletonHTML(count) {
  // Each skeleton row mimics a collapsed bill card with shimmering blocks
  const row = `
    <div class="pg-skeleton-card">
      <div class="pg-skeleton-row">
        <span class="pg-skel pg-skel-badge"></span>
        <span class="pg-skel pg-skel-date"></span>
        <span class="pg-skel pg-skel-name"></span>
        <span class="pg-skel pg-skel-amount"></span>
      </div>
    </div>`;
  return `<div class="pg-skeleton-wrap">${row.repeat(count)}</div>`;
}

// ── Pagination Bar ────────────────────────────────────────────────────────

function renderPaginationBar(containerId, page, pageSize, total, onGoto) {
  const el = document.getElementById(containerId);
  if (!el) return;

  const totalPages = Math.max(1, Math.ceil((total || 0) / pageSize));

  if (!total || totalPages <= 1) {
    el.style.display = 'none';
    el.innerHTML = '';
    return;
  }

  el.style.display = 'flex';
  el.classList.add('pg-bar');
  el.innerHTML = `
    <button type="button" class="pg-btn pg-prev" ${page <= 1 ? 'disabled' : ''}>
      <i class="ti ti-chevron-left"></i> Prev
    </button>
    <span class="pg-info">
      Page
      <input type="number" class="pg-input" min="1" max="${totalPages}" value="${page}" inputmode="numeric">
      of ${totalPages}
    </span>
    <button type="button" class="pg-btn pg-next" ${page >= totalPages ? 'disabled' : ''}>
      Next <i class="ti ti-chevron-right"></i>
    </button>
  `;

  const prevBtn = el.querySelector('.pg-prev');
  const nextBtn = el.querySelector('.pg-next');
  const input = el.querySelector('.pg-input');

  prevBtn.onclick = () => { if (page > 1) onGoto(page - 1); };
  nextBtn.onclick = () => { if (page < totalPages) onGoto(page + 1); };

  let navigated = false;
  const goToTyped = () => {
    if (navigated) return;
    let v = parseInt(input.value, 10);
    if (isNaN(v) || v < 1) v = 1;
    if (v > totalPages) v = totalPages;
    if (v !== page) {
      navigated = true;
      onGoto(v);
    } else {
      input.value = page; // snap back if it was invalid/unchanged
    }
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      input.blur(); // Triggers blur event which calls goToTyped() once
    }
  });
  input.addEventListener('blur', goToTyped);
}
