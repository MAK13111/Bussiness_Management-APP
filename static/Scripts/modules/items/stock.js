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

// Only the current page's rows are ever held/rendered -- moving to another
// page (Prev/Next or typing a page number) replaces them, it doesn't
// accumulate pages on top of each other.
// reset=true (default): fresh open/search -- goes back to page 1.
async function loadStockValuation(reset = true) {
  if (reset) { stkPage = 1; }
  try {
    const p = new URLSearchParams();
    if (stkSearch) p.set('search', stkSearch);
    p.set('page', stkPage);
    p.set('limit', STK_PAGE_SIZE);
    const res = await fetch('/api/items/stock?' + p.toString());
    const data = await res.json();
    // /api/items/stock returns {items,total,totalValue,page,limit} when
    // page & limit are passed, same convention as /api/entries.
    const rows = data.items !== undefined ? data.items : data;
    stkTotal = data.total !== undefined ? data.total : rows.length;
    stkTotalValue = data.totalValue !== undefined ? data.totalValue : rows.reduce((s, i) => s + (i.stockValue || 0), 0);
    stkAllRows = rows;
    renderStockValuation(stkAllRows);
    renderPaginationBar('stock-pagination', stkPage, STK_PAGE_SIZE, stkTotal, gotoStockPage);
  } catch(err) { console.error('Error loading stock:', err); }
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
      <td>${i+1}</td>
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
