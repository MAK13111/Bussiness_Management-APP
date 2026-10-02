// =========================================================================
// modules/items/oldStock.js
// "Old data stock" sub-tab: shows the whole legacy old_data table
// (imported from Old_Data/old_purchase_data.xlsx) with search + pagination.
// =========================================================================

let oldStkPage = 1;
let oldStkSearch = '';
let oldStkDebounce = null;
const OLD_STK_PAGE_SIZE = 100;

function _odEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function loadOldDataStock(reset = true) {
  if (reset) oldStkPage = 1;
  const params = new URLSearchParams({ page: oldStkPage, limit: OLD_STK_PAGE_SIZE });
  if (oldStkSearch) params.set('search', oldStkSearch);

  showPageLoader('old-stock-tbody', OLD_STK_PAGE_SIZE);
  try {
    const res = await fetch(`/api/old_data?${params.toString()}`);
    const data = await res.json();
    renderOldDataStock(data, (oldStkPage - 1) * OLD_STK_PAGE_SIZE);
    renderPaginationBar('old-stock-pagination', oldStkPage, OLD_STK_PAGE_SIZE, data.total || 0, gotoOldStockPage);
  } catch (err) { console.error('Error loading old data stock:', err); }
  finally { hidePageLoader('old-stock-tbody'); }
}

async function gotoOldStockPage(page) {
  oldStkPage = page;
  await loadOldDataStock(false);
}

function renderOldDataStock(data, offset) {
  const rows = data.items || [];
  const tbody = document.getElementById('old-stock-tbody');
  const empty = document.getElementById('old-stock-empty');

  document.getElementById('old-stock-total-items').textContent = data.total || 0;
  document.getElementById('old-stock-total-qty').textContent = fmtNum(data.total_qty || 0);
  document.getElementById('old-stock-total-value').textContent = fmt(data.total_value || 0);

  if (!rows.length) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = rows.map((r, i) => {
    const remaining = r.remaining || 0;
    const stockClass = remaining <= 0 ? 'overdue' : 'paid';
    return `<tr>
      <td>${offset + i + 1}</td>
      <td>${_odEsc(r.uniqee_id)}</td>
      <td>${_odEsc(r.item_code)}</td>
      <td>${r.size ? `<span class="item-size-badge">${_odEsc(r.size)}</span>` : '—'}</td>
      <td>${fmt(r.buy_mrp || 0)}</td>
      <td>${fmt(r.sell_mrp || 0)}</td>
      <td><span class="status-badge ${stockClass}">${remaining}</span></td>
      <td>${r.sold || 0}</td>
      <td>${r.is_return ? 'Yes' : 'No'}</td>
      <td>${fmt(remaining * (r.buy_mrp || 0))}</td>
    </tr>`;
  }).join('');
}

function filterOldStock() {
  const search = document.getElementById('old-stock-search').value.trim();
  clearTimeout(oldStkDebounce);
  oldStkDebounce = setTimeout(() => {
    oldStkSearch = search;
    loadOldDataStock(true);
  }, 250);
}