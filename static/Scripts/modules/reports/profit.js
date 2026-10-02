// =========================================================================
// modules/reports/profit.js
// Profit report: loading, rendering, and resetting the date filter.
// =========================================================================

let prPage = 1;
const PR_PAGE_SIZE = 100;

async function loadProfitReport(page) {
  if (page !== undefined) prPage = page;
  const from = document.getElementById('pr-date-from').value;
  const to = document.getElementById('pr-date-to').value;

  showPageLoader('pr-tbody', PR_PAGE_SIZE);

  try {
    const p = new URLSearchParams();
    if (from) p.set('from', from);
    if (to) p.set('to', to);
    p.set('page', prPage);
    p.set('limit', PR_PAGE_SIZE);
    const res = await fetch(`/api/reports/profit?${p.toString()}`);
    const data = await res.json();
    renderProfitReport(data);
    renderPaginationBar('pr-pagination', data.page || prPage, PR_PAGE_SIZE, data.total || 0, loadProfitReport);
  } catch(err) { console.error('Error loading profit report:', err); }
  finally { hidePageLoader('pr-tbody'); }
}

function renderProfitReport(data) {
  const tbody = document.getElementById('pr-tbody');
  const empty = document.getElementById('pr-empty');
  if (!data || !data.entries || data.entries.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
    document.getElementById('pr-total-purchases').textContent = '₹0.00';
    document.getElementById('pr-total-sales').textContent = '₹0.00';
    document.getElementById('pr-total-profit').textContent = '₹0.00';
    document.getElementById('pr-profit-margin').textContent = '0%';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = data.entries.map((e, i) => `
    <tr><td>${((data.page || 1) - 1) * PR_PAGE_SIZE + i + 1}</td><td>${e.date || '—'}</td><td>${e.party || e.customerName || '—'}</td><td>${e.item || '—'}</td><td>${e.qty || 0}</td><td>${fmt(e.buyTotal || 0)}</td><td>${fmt(e.sellTotal || 0)}</td><td class="profit-cell">${fmt(e.profit || 0)}</td></tr>
  `).join('');
  document.getElementById('pr-total-purchases').textContent = fmt(data.totals.purchases || 0);
  document.getElementById('pr-total-sales').textContent = fmt(data.totals.sales || 0);
  document.getElementById('pr-total-profit').textContent = fmt(data.totals.profit || 0);
  const margin = data.totals.marginPct ?? 0;
  document.getElementById('pr-profit-margin').textContent = margin.toFixed(1) + '%';
}

function resetProfitReport() {
  document.getElementById('pr-date-from').value = '';
  document.getElementById('pr-date-to').value = '';
  prPage = 1;
  loadProfitReport();
}

