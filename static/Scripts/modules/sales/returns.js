// =========================================================================
// modules/sales/returns.js
// Sales return entry: searching/selecting the original sale bill,
// picking items to return, saving the return bill, and listing
// previously saved sales return bills.
// =========================================================================

let srSelectedBill = null;

async function searchSaleBills() {
  const q = document.getElementById('sr-search-input').value.trim();
  const resultsEl = document.getElementById('sr-bill-results');
  document.getElementById('sr-items-section').style.display = 'none';
  srSelectedBill = null;
  if (!q) { resultsEl.innerHTML = ''; return; }
  resultsEl.innerHTML = '<div class="invoice-result-empty">Searching...</div>';
  try {
    const res = await fetch('/api/sale_bills/search?q=' + encodeURIComponent(q));
    const rows = await res.json();
    if (!rows.length) {
      resultsEl.innerHTML = '<div class="invoice-result-empty">No matching sale bills found.</div>';
      return;
    }
    const groups = {};
    rows.forEach(r => {
      const key = r.sourceTable + '||' + (r.billNo || '');
      if (!groups[key]) groups[key] = { table: r.sourceTable, billNo: r.billNo, customerName: r.customerName, count: 0 };
      groups[key].count++;
    });
    resultsEl.innerHTML = Object.values(groups).map(g => `
      <div class="invoice-result-card" onclick="selectSaleBill('${g.table}', '${(g.billNo||'').replace(/'/g,"\\'")}')">
        <span>${g.billNo || '(no bill no.)'} — ${g.customerName || 'Unknown customer'} — ${g.count} item${g.count>1?'s':''}</span>
        <span class="ir-select">Select</span>
      </div>
    `).join('');
  } catch(e) { resultsEl.innerHTML = '<div class="invoice-result-empty">Search failed. Try again.</div>'; }
}

async function selectSaleBill(table, billNo) {
  try {
    const res = await fetch(`/api/sale_bills/${table}/${encodeURIComponent(billNo)}`);
    const items = await res.json();
    srSelectedBill = { table, billNo, items };
    document.querySelectorAll('#sr-bill-results .invoice-result-card').forEach(el => el.classList.remove('selected'));
    const cards = document.querySelectorAll('#sr-bill-results .invoice-result-card');
    cards.forEach(c => { if (c.textContent.includes(billNo || '(no bill no.)')) c.classList.add('selected'); });
    renderSalesReturnItems();
  } catch(e) { showToast('Could not load bill items', '#dc2626'); }
}

function renderSalesReturnItems() {
  const listEl = document.getElementById('sr-items-list');
  const sectionEl = document.getElementById('sr-items-section');
  if (!srSelectedBill || !srSelectedBill.items.length) {
    sectionEl.style.display = 'none';
    return;
  }
  sectionEl.style.display = '';
  listEl.innerHTML = srSelectedBill.items.map((it, idx) => `
    <div class="return-item-row">
      <input type="checkbox" id="sr-chk-${idx}" onchange="onSalesReturnRowToggle(${idx})"/>
      <span class="ri-name">${it.item || '—'}</span>
      <span class="ri-meta">${it.size || '—'}</span>
      <span class="ri-meta">${it.qty}</span>
      <input type="number" id="sr-qty-${idx}" min="1" max="${it.qty}" value="1" disabled oninput="updateSalesReturnSummary()"/>
    </div>
  `).join('');
  updateSalesReturnSummary();
}

function onSalesReturnRowToggle(idx) {
  const chk = document.getElementById(`sr-chk-${idx}`);
  const qtyInput = document.getElementById(`sr-qty-${idx}`);
  qtyInput.disabled = !chk.checked;
  updateSalesReturnSummary();
}

function updateSalesReturnSummary() {
  if (!srSelectedBill) return;
  let count = 0, total = 0;
  srSelectedBill.items.forEach((it, idx) => {
    const chk = document.getElementById(`sr-chk-${idx}`);
    if (chk && chk.checked) {
      let qty = parseFloat(document.getElementById(`sr-qty-${idx}`).value) || 0;
      if (qty > it.qty) qty = it.qty;
      if (qty < 1) qty = 1;
      document.getElementById(`sr-qty-${idx}`).value = qty;
      count++;
      total += qty * (it.sellUnit || 0);
    }
  });
  document.getElementById('sr-summary').textContent = count ? `${count} item${count>1?'s':''} selected · Return total: ${fmt(total)}` : 'No items selected';
}

async function saveSalesReturnBill() {
  if (!srSelectedBill) { showToast('Select a bill first', '#dc2626'); return; }
  const reason = document.getElementById('sr-reason').value.trim();
  const items = [];
  srSelectedBill.items.forEach((it, idx) => {
    const chk = document.getElementById(`sr-chk-${idx}`);
    if (chk && chk.checked) {
      const qty = parseFloat(document.getElementById(`sr-qty-${idx}`).value) || 0;
      items.push({ originalTable: srSelectedBill.table, originalId: it.id, qty });
    }
  });
  if (!items.length) { showToast('Select at least one item to return', '#dc2626'); return; }
  try {
    const res = await fetch('/api/sales_return_bill', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ items, reason })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Return bill ${data.returnBillNo} saved`);
      document.getElementById('sr-search-input').value = '';
      document.getElementById('sr-reason').value = '';
      document.getElementById('sr-bill-results').innerHTML = '';
      document.getElementById('sr-items-section').style.display = 'none';
      srSelectedBill = null;
      loadSalesReturnBills();
    } else {
      showToast(data.message || 'Could not save return bill', '#dc2626');
    }
  } catch(e) { showToast('Could not save return bill', '#dc2626'); }
}

// ─── SALES RETURN BILLS LIST ─────────────────────────────────────────

let srbRows = [];
let srbPage = 1;
let srbTotal = 0;
const SRB_PAGE_SIZE = 100;

async function loadSalesReturnBills(reset = true) {
  if (reset) srbPage = 1;
  const from = document.getElementById('srb-date-from').value;
  const to = document.getElementById('srb-date-to').value;
  const p = new URLSearchParams();
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);
  p.set('page', srbPage);
  p.set('limit', SRB_PAGE_SIZE);
  const res = await fetch('/api/sales_returns?' + p.toString());
  const data = await res.json();
  // {entries,total,page,limit} when page & limit are passed, same
  // convention as /api/reports/sales and /api/items.
  const rows = data.entries !== undefined ? data.entries : data;
  srbTotal = data.total !== undefined ? data.total : rows.length;
  srbRows = rows;
  renderSalesReturnBills(srbRows);
  renderPaginationBar('srb-pagination', srbPage, SRB_PAGE_SIZE, srbTotal, gotoSalesReturnBillsPage);
  const infoEl = document.getElementById('srb-result-info');
  if (from || to) {
    infoEl.style.display = '';
    infoEl.textContent = `Showing ${srbTotal} matching return bill${srbTotal === 1 ? '' : 's'}`;
  } else {
    infoEl.style.display = 'none';
  }
}

async function gotoSalesReturnBillsPage(page) {
  srbPage = page;
  await loadSalesReturnBills(false);
}

function renderSalesReturnBills(rows) {
  const tbody = document.getElementById('srb-tbody');
  const emptyEl = document.getElementById('srb-empty');
  if (!rows.length) {
    tbody.innerHTML = '';
    emptyEl.style.display = '';
    return;
  }
  emptyEl.style.display = 'none';
  tbody.innerHTML = rows.map((e, i) => `
    <tr>
      <td>${i+1}</td>
      <td>${e.returnBillNo || '—'}</td>
      <td>${e.customerName || '—'}</td>
      <td>${e.item || '—'}</td>
      <td>${e.size || '—'}</td>
      <td>${e.qty}</td>
      <td>${fmt(e.sellTotal)}</td>
      <td>${e.reason || '—'}</td>
      <td>${e.date || '—'}</td>
    </tr>
  `).join('');
}

function applySalesReturnBillsFilter() {
  loadSalesReturnBills(true);
}

function resetSalesReturnBillsFilter() {
  document.getElementById('srb-date-from').value = '';
  document.getElementById('srb-date-to').value = '';
  document.getElementById('srb-result-info').style.display = 'none';
  loadSalesReturnBills(true);
}

