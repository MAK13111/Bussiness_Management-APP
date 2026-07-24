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
// =========================================================================

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

  // Typing a page number is enough -- no separate "Go" button. It jumps as
  // soon as the value is committed (Enter, or clicking/tabbing away).
  const goToTyped = () => {
    let v = parseInt(input.value, 10);
    if (!v || v < 1) v = 1;
    if (v > totalPages) v = totalPages;
    if (v !== page) {
      onGoto(v);
    } else {
      input.value = page; // snap back if it was invalid/unchanged
    }
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); goToTyped(); }
  });
  input.addEventListener('blur', goToTyped);
}
