// =========================================================================
// modules/reports/profit.js
// Profit report: loading, rendering, and resetting the date filter.
// =========================================================================

async function loadProfitReport() {
  const from = document.getElementById('pr-date-from').value;
  const to = document.getElementById('pr-date-to').value;
  try {
    const res = await fetch(`/api/reports/profit?from=${from}&to=${to}`);
    const data = await res.json();
    renderProfitReport(data);
  } catch(err) { console.error('Error loading profit report:', err); }
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
    <tr><td>${i+1}</td><td>${e.date || '—'}</td><td>${e.party || e.customerName || '—'}</td><td>${e.item || '—'}</td><td>${e.qty || 0}</td><td>${fmt(e.buyTotal || 0)}</td><td>${fmt(e.sellTotal || 0)}</td><td class="profit-cell">${fmt(e.profit || 0)}</td></tr>
  `).join('');
  document.getElementById('pr-total-purchases').textContent = fmt(data.totals.purchases || 0);
  document.getElementById('pr-total-sales').textContent = fmt(data.totals.sales || 0);
  document.getElementById('pr-total-profit').textContent = fmt(data.totals.profit || 0);
  // Margin % now comes from the API (core/calculations.py::profit_margin_pct) --
  // JS only formats it for display, doesn't compute it.
  const margin = data.totals.marginPct ?? 0;
  document.getElementById('pr-profit-margin').textContent = margin.toFixed(1) + '%';
}

function resetProfitReport() {
  document.getElementById('pr-date-from').value = '';
  document.getElementById('pr-date-to').value = '';
  loadProfitReport();
}

