// =========================================================================
// modules/purchases/returns.js
// Purchase return entry: searching/selecting the original invoice,
// picking items to return, saving the return bill, and listing
// previously saved purchase return bills.
// =========================================================================

let prSelectedInvoice = null;

async function searchPurchaseInvoices() {
  const q = document.getElementById('pr-search-input').value.trim();
  const resultsEl = document.getElementById('pr-invoice-results');
  document.getElementById('pr-items-section').style.display = 'none';
  prSelectedInvoice = null;
  if (!q) { resultsEl.innerHTML = ''; return; }
  resultsEl.innerHTML = '<div class="invoice-result-empty">Searching...</div>';
  try {
    const res = await fetch('/api/purchase_invoices/search?q=' + encodeURIComponent(q));
    const rows = await res.json();
    if (!rows.length) {
      resultsEl.innerHTML = '<div class="invoice-result-empty">No matching purchase bills found.</div>';
      return;
    }
    const groups = {};
    rows.forEach(r => {
      const key = r.sourceTable + '||' + r.purchase_id;
      if (!groups[key]) groups[key] = { table: r.sourceTable, purchaseId: r.purchase_id, invoiceNo: r.invoiceNo, party: r.party, count: 0 };
      groups[key].count++;
    });
    resultsEl.innerHTML = Object.values(groups).map(g => `
      <div class="invoice-result-card" onclick="selectPurchaseInvoice('${g.table}', ${g.purchaseId}, this)">
        <span>${g.invoiceNo || '(no invoice no.)'} — ${g.party || 'Unknown party'} — ${g.count} item${g.count>1?'s':''}</span>
        <span class="ir-select">Select</span>
      </div>
    `).join('');
  } catch(e) { resultsEl.innerHTML = '<div class="invoice-result-empty">Search failed. Try again.</div>'; }
}

async function selectPurchaseInvoice(table, purchaseId, clickedEl) {
  try {
    const res = await fetch(`/api/purchase_invoices/${table}/${purchaseId}`);
    if (!res.ok) throw new Error('Bill not found');
    const items = await res.json();
    prSelectedInvoice = { table, purchaseId, items };
    document.querySelectorAll('#pr-invoice-results .invoice-result-card').forEach(el => el.classList.remove('selected'));
    if (clickedEl) clickedEl.classList.add('selected');
    renderPurchaseReturnItems();
  } catch(e) { showToast('Could not load invoice items', '#dc2626'); }
}

function renderPurchaseReturnItems() {
  const listEl = document.getElementById('pr-items-list');
  const sectionEl = document.getElementById('pr-items-section');
  if (!prSelectedInvoice || !prSelectedInvoice.items.length) {
    sectionEl.style.display = 'none';
    return;
  }
  sectionEl.style.display = '';
  listEl.innerHTML = prSelectedInvoice.items.map((it, idx) => {
    const available = Math.max(0, (it.qty || 0) - (it.sold || 0));
    return `
    <div class="return-item-row">
      <input type="checkbox" id="pr-chk-${idx}" onchange="onPurchaseReturnRowToggle(${idx})" ${available <= 0 ? 'disabled' : ''}/>
      <span class="ri-name">${it.item || '—'}</span>
      <span class="ri-meta">${it.size || '—'}</span>
      <span class="ri-meta">${available} available</span>
      <input type="number" id="pr-qty-${idx}" min="1" max="${available}" value="1" disabled oninput="updatePurchaseReturnSummary()"/>
    </div>
  `;
  }).join('');
  updatePurchaseReturnSummary();
}

function onPurchaseReturnRowToggle(idx) {
  const chk = document.getElementById(`pr-chk-${idx}`);
  const qtyInput = document.getElementById(`pr-qty-${idx}`);
  qtyInput.disabled = !chk.checked;
  updatePurchaseReturnSummary();
}

function updatePurchaseReturnSummary() {
  if (!prSelectedInvoice) return;
  let count = 0, total = 0;
  prSelectedInvoice.items.forEach((it, idx) => {
    const chk = document.getElementById(`pr-chk-${idx}`);
    if (chk && chk.checked) {
      const available = Math.max(0, (it.qty || 0) - (it.sold || 0));
      let qty = parseFloat(document.getElementById(`pr-qty-${idx}`).value) || 0;
      if (qty > available) qty = available;
      if (qty < 1) qty = 1;
      document.getElementById(`pr-qty-${idx}`).value = qty;
      count++;
      total += qty * (it.buy || 0);
    }
  });
  document.getElementById('pr-summary').textContent = count ? `${count} item${count>1?'s':''} selected · Return total: ${fmt(total)}` : 'No items selected';
}

async function savePurchaseReturnBill() {
  if (!prSelectedInvoice) { showToast('Select an invoice first', '#dc2626'); return; }
  const reason = document.getElementById('pr-reason').value.trim();
  const items = [];
  prSelectedInvoice.items.forEach((it, idx) => {
    const chk = document.getElementById(`pr-chk-${idx}`);
    if (chk && chk.checked) {
      const qty = parseFloat(document.getElementById(`pr-qty-${idx}`).value) || 0;
      items.push({ originalTable: prSelectedInvoice.table, originalId: it.id, qty });
    }
  });
  if (!items.length) { showToast('Select at least one item to return', '#dc2626'); return; }
  try {
    const res = await fetch('/api/purchase_return_bill', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ items, reason })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Return bill ${data.returnBillNo} saved`);
      document.getElementById('pr-search-input').value = '';
      document.getElementById('pr-reason').value = '';
      document.getElementById('pr-invoice-results').innerHTML = '';
      document.getElementById('pr-items-section').style.display = 'none';
      prSelectedInvoice = null;
      loadPurchaseReturnBills();
      loadPurchaseBills();
      loadReportPurchaseBills();
      loadDashboard();
    } else {
      showToast(data.message || 'Could not save return bill', '#dc2626');
    }
  } catch(e) { showToast('Could not save return bill', '#dc2626'); }
}

// ─── PURCHASE RETURN BILLS LIST ─────────────────────────────────────────

let prbRows = [];
let prbPage = 1;
let prbTotal = 0;
const PRB_PAGE_SIZE = 100;

async function loadPurchaseReturnBills(reset = true) {
  if (reset) prbPage = 1;
  const from = document.getElementById('prb-date-from').value;
  const to = document.getElementById('prb-date-to').value;
  const p = new URLSearchParams();
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);
  p.set('page', prbPage);
  p.set('limit', PRB_PAGE_SIZE);
  const res = await fetch('/api/purchase_returns?' + p.toString());
  const data = await res.json();
  // {entries,total,page,limit} when page & limit are passed, same
  // convention as /api/reports/purchases and /api/items.
  const rows = data.entries !== undefined ? data.entries : data;
  prbTotal = data.total !== undefined ? data.total : rows.length;
  prbRows = rows;
  renderPurchaseReturnBills(prbRows);
  renderPaginationBar('prb-pagination', prbPage, PRB_PAGE_SIZE, prbTotal, gotoPurchaseReturnBillsPage);
  const infoEl = document.getElementById('prb-result-info');
  if (from || to) {
    infoEl.style.display = '';
    infoEl.textContent = `Showing ${prbTotal} matching return bill${prbTotal === 1 ? '' : 's'}`;
  } else {
    infoEl.style.display = 'none';
  }
}

async function gotoPurchaseReturnBillsPage(page) {
  prbPage = page;
  await loadPurchaseReturnBills(false);
}

function renderPurchaseReturnBills(rows) {
  const tbody = document.getElementById('prb-tbody');
  const emptyEl = document.getElementById('prb-empty');
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
      <td>${e.party || '—'}</td>
      <td>${e.item || '—'}</td>
      <td>${e.size || '—'}</td>
      <td>${e.qty}</td>
      <td>${fmt(e.buyTotal)}</td>
      <td>${e.reason || '—'}</td>
      <td>${e.date || '—'}</td>
    </tr>
  `).join('');
}

function applyPurchaseReturnBillsFilter() {
  loadPurchaseReturnBills(true);
}

function resetPurchaseReturnBillsFilter() {
  document.getElementById('prb-date-from').value = '';
  document.getElementById('prb-date-to').value = '';
  document.getElementById('prb-result-info').style.display = 'none';
  loadPurchaseReturnBills(true);
}

