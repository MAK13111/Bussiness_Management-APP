// =========================================================================
// modules/items/stock.js
// Stock valuation report: loading, rendering, and searching.
//
// Paginated in pages of 100 items (same convention as the Reports tab's
// bill lists and the Purchase/Sale "Bills (date wise)" panels) instead of
// fetching every distinct item's stock valuation in one go.
// =========================================================================

let stkPage = 1;
let stkTotal = 0;
let stkTotalValue = 0;
let stkAllRows = [];
let stkSearch = '';
const STK_PAGE_SIZE = 100;
let stkSearchDebounce = null;
let stkCachedTotalValue = null; // cached from page 1, reused on page turns
let stkCachedTotal = null;      // cached item count, skips 3s COUNT on page turns

// Only the current page's rows are ever held/rendered -- moving to another
// page (Prev/Next or typing a page number) replaces them, it doesn't
// accumulate pages on top of each other.
// reset=true (default): fresh open/search -- goes back to page 1.
async function loadStockValuation(reset = true) {
  if (reset) { stkPage = 1; stkCachedTotalValue = null; stkCachedTotal = null; }

  showPageLoader('stock-tbody', stkAllRows.length || STK_PAGE_SIZE);

  try {
    const p = new URLSearchParams();
    if (stkSearch) p.set('search', stkSearch);
    p.set('page', stkPage);
    p.set('limit', STK_PAGE_SIZE);
    // Send cached values on page turns so the server skips the expensive
    // COUNT(*) (3s) and total_value SUM (1.3s) scans.
    if (stkPage > 1) {
      if (stkCachedTotalValue !== null) p.set('totalValue', stkCachedTotalValue);
      if (stkCachedTotal !== null)      p.set('knownTotal', stkCachedTotal);
    }
    const res = await fetch('/api/items/stock?' + p.toString());
    const data = await res.json();
    const rows = data.items !== undefined ? data.items : data;
    stkTotal = data.total !== undefined ? data.total : rows.length;
    stkTotalValue = data.totalValue !== undefined ? data.totalValue : rows.reduce((s, i) => s + (i.stockValue || 0), 0);
    // Cache from page 1 for reuse on subsequent page turns
    if (stkPage === 1) {
      stkCachedTotalValue = stkTotalValue;
      stkCachedTotal = stkTotal;
    }
    stkAllRows = rows;
    renderStockValuation(stkAllRows);
    renderPaginationBar('stock-pagination', stkPage, STK_PAGE_SIZE, stkTotal, gotoStockPage);
  } catch (err) { console.error('Error loading stock:', err); }
  finally { hidePageLoader('stock-tbody'); }
}

async function gotoStockPage(page) {
  stkPage = page;
  await loadStockValuation(false);
}

function renderStockValuation(data) {
  const tbody = document.getElementById('stock-tbody');
  const empty = document.getElementById('stock-empty');
  if (!data || data.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
    document.getElementById('stock-total-items').textContent = '0';
    document.getElementById('stock-total-value').textContent = '₹0.00';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = data.map((item, i) => {
    return `<tr>
      <td>${i + 1}</td>
      <td>${item.name}</td>
      <td>${item.department || '—'}</td>
      <td>${item.unit || '—'}</td>
      <td>${item.stock || 0}</td>
      <td>${fmt(item.avgBuyRate || 0)}</td>
      <td>${fmt(item.stockValue || 0)}</td>
    </tr>`;
  }).join('');
  // Totals reflect every matching item (from the server), not just the
  // page(s) loaded so far into the browser.
  document.getElementById('stock-total-items').textContent = stkTotal;
  document.getElementById('stock-total-value').textContent = fmt(stkTotalValue);
}

// Search is sent to the server (instead of just hiding rows on the page
// already loaded) so it matches against the whole dataset, same approach
// as the Reports tab's bill lists.
function filterStock() {
  const search = document.getElementById('stock-search').value.trim();
  clearTimeout(stkSearchDebounce);
  stkSearchDebounce = setTimeout(() => {
    stkSearch = search;
    loadStockValuation(true);
  }, 250);
}
