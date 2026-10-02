// =========================================================================
// modules/sales/returns.js
// Sales return entry: searching/selecting the original sale bill,
// picking items to return, saving the return bill, and listing
// previously saved sales return bills.
// =========================================================================

let srSelectedBill = null;

// ─── ENTRY MODE SWITCH: find-by-bill vs scan/enter barcode ─────────────

function switchSalesReturnMode(mode) {
  const isBarcode = mode === 'barcode';
  document.getElementById('sr-mode-bill').classList.toggle('active', !isBarcode);
  document.getElementById('sr-mode-barcode').classList.toggle('active', isBarcode);
  document.getElementById('sr-bill-mode-panel').style.display = isBarcode ? 'none' : '';
  document.getElementById('sr-barcode-mode-panel').style.display = isBarcode ? '' : 'none';
  if (isBarcode) setTimeout(() => focusSalesReturnScanInput(), 150);
}

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

// ─── BARCODE SCAN/ENTER → CART (mirrors purchase return flow) ──────────
// Looks items up via /api/barcode_lookup_sold, which only matches units
// currently marked 'sold' -- so only barcodes actually sold to a
// customer can be queued here, same guarantee purchase returns get from
// /api/barcode_lookup against 'available' stock.

let srCart = [];
let srScanTimer = null;

function focusSalesReturnScanInput() {
  const inp = document.getElementById('src-bc-scan');
  if (inp) { inp.value = ''; inp.focus(); updateSalesReturnScanLabel('focused'); }
}

function updateSalesReturnScanLabel(state) {
  const label = document.getElementById('src-scan-gun-label');
  if (!label) return;
  if (state === 'focused') {
    label.textContent = '🟢 Scanner active — scan a barcode now';
  } else if (state === 'blur') {
    label.textContent = '🔴 Scanner paused — click here to activate';
  } else {
    label.textContent = 'Scanner ready — scan a barcode';
  }
}

function onSalesReturnScanInput(inputEl) {
  clearTimeout(srScanTimer);
  srScanTimer = setTimeout(() => {
    const code = inputEl.value.trim();
    inputEl.value = '';
    if (code) lookupAndAddSalesReturnCode(code);
  }, 80);
}

document.addEventListener('focusin', (e) => {
  if (e.target && e.target.id === 'src-bc-scan') updateSalesReturnScanLabel('focused');
});
document.addEventListener('focusout', (e) => {
  if (e.target && e.target.id === 'src-bc-scan') updateSalesReturnScanLabel('blur');
});

function switchSalesReturnInputTab(tab) {
  document.getElementById('src-sitab-enter').classList.toggle('active', tab === 'enter');
  document.getElementById('src-sitab-scan').classList.toggle('active', tab === 'scan');
  document.getElementById('src-bc-enter-panel').style.display = tab === 'enter' ? '' : 'none';
  document.getElementById('src-bc-scan-panel').style.display  = tab === 'scan'  ? '' : 'none';
  if (tab === 'scan') {
    setTimeout(() => focusSalesReturnScanInput(), 150);
  }
}

async function lookupAndAddSalesReturnBarcode(inputId) {
  const input = document.getElementById(inputId);
  const statusEl = document.getElementById('src-bc-enter-status');
  const code = (input ? input.value.trim() : '');
  if (!code) return;

  // If code has any alphabetic characters (A-Z), open the selection window like during sale
  if (/[a-zA-Z]/.test(code)) {
    setStatus(statusEl, '⏳ Checking Old Stock...', 'info');
    try {
      const res = await fetch(`/api/old_data_lookup?code=${encodeURIComponent(code)}`);
      const data = await res.json();
      if (res.ok && (data.status === 'ok' || data.status === 'multiple_prices') && data.matches && data.matches.length > 0) {
        showOldDataDuplicatePicker(data.matches, statusEl, input, (chosen) => {
          // User selected item, now we have the uniqee_id -> repeat same process
          const uid = chosen.uniqee_id || chosen.id;
          if (input) { input.value = uid; }
          lookupAndAddSalesReturnCode(uid, statusEl);
        }, 'return');
        return;
      } else {
        setStatus(statusEl, '✗ ' + (data.message || 'Old Stock item not found.'), 'error');
        return;
      }
    } catch (err) {
      setStatus(statusEl, '✗ Server error. Try again.', 'error');
      return;
    }
  }

  setStatus(statusEl, '⏳ Looking up...', 'info');
  try {
    const res = await fetch(`/api/barcode_lookup_sold?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      addBarcodeToSalesReturnCart(data.barcode, statusEl);
      if (input) { input.value = ''; input.focus(); }
    } else {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
}

async function lookupAndAddSalesReturnCode(code, targetStatusEl) {
  const statusEl = targetStatusEl || document.getElementById('src-scan-status') || document.getElementById('src-bc-enter-status');
  if (!code) return;

  // If code has any alphabetic characters (A-Z), open the selection window like during sale
  if (/[a-zA-Z]/.test(String(code))) {
    setStatus(statusEl, '⏳ Checking Old Stock...', 'info');
    try {
      const res = await fetch(`/api/old_data_lookup?code=${encodeURIComponent(code)}`);
      const data = await res.json();
      if (res.ok && (data.status === 'ok' || data.status === 'multiple_prices') && data.matches && data.matches.length > 0) {
        showOldDataDuplicatePicker(data.matches, statusEl, document.getElementById('src-bc-scan'), (chosen) => {
          // User selected item, now we have the uniqee_id -> repeat same process
          const uid = chosen.uniqee_id || chosen.id;
          lookupAndAddSalesReturnCode(uid, statusEl);
        }, 'return');
        return;
      } else {
        setStatus(statusEl, '✗ ' + (data.message || 'Old Stock item not found.'), 'error');
        return;
      }
    } catch (err) {
      setStatus(statusEl, '✗ Server error. Try again.', 'error');
      return;
    }
  }

  setStatus(statusEl, '⏳ Looking up...', 'info');
  try {
    const res = await fetch(`/api/barcode_lookup_sold?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      addBarcodeToSalesReturnCart(data.barcode, statusEl);
    } else {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
}

function addBarcodeToSalesReturnCart(bc, statusEl) {
  if (bc.is_old_data) {
    const existing = srCart.find(row => row.is_old_data && (row.purchase_item_id === bc.purchase_item_id || row.item === bc.item));
    if (existing) {
      existing.qty += 1;
      existing.scanned_codes.push(bc.code);
      setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
    } else {
      srCart.push({
        purchase_item_id: bc.purchase_item_id,
        item: bc.item, size: bc.size,
        sell_unit: bc.sell_unit,
        qty: 1, scanned_codes: [bc.code],
        is_old_data: true,
        sold_item_id: bc.sold_item_id
      });
      setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' ('+bc.size+')' : ''}`, 'ok');
    }
    renderSalesReturnCart();
    return;
  }

  // Same exact barcode already queued for return — warn instead of double-counting.
  if (srCart.some(row => row.scanned_codes.includes(bc.code))) {
    setStatus(statusEl, '⚠ This barcode is already in the return list.', 'warn');
    return;
  }
  // Different barcode but same item batch — bump that row's qty instead of a duplicate row.
  const existing = srCart.find(row => row.purchase_item_id === bc.purchase_item_id);
  if (existing) {
    existing.qty += 1;
    existing.scanned_codes.push(bc.code);
    setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
  } else {
    srCart.push({
      purchase_item_id: bc.purchase_item_id,
      item: bc.item, size: bc.size,
      sell_unit: bc.sell_unit,
      qty: 1, scanned_codes: [bc.code]
    });
    setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' ('+bc.size+')' : ''}`, 'ok');
  }
  renderSalesReturnCart();
}

// +/- claims or releases one real sold barcode of the same item batch, so a
// qty bump without rescanning still claims (or releases) an exact, real unit.
async function changeSalesReturnQty(idx, delta) {
  const row = srCart[idx];
  if (!row) return;
  const newQty = (row.qty || 1) + delta;
  if (newQty < 1) { removeSalesReturnRow(idx); return; }

  if (delta > 0) {
    if (row.is_old_data) {
      row.scanned_codes.push(row.scanned_codes[0] || String(row.purchase_item_id));
      row.qty = newQty;
      renderSalesReturnCart();
      return;
    }
    try {
      const exclude = row.scanned_codes.join(',');
      const res = await fetch(`/api/barcode_by_item?purchase_item_id=${row.purchase_item_id}&status=sold&exclude=${encodeURIComponent(exclude)}`);
      const data = await res.json();
      if (data.status === 'ok') {
        row.scanned_codes.push(data.barcode.code);
        row.qty = newQty;
        renderSalesReturnCart();
      } else {
        showToast(data.message || 'No more sold units available to return for this item.', '#dc2626');
      }
    } catch (err) {
      showToast('Could not check stock. Try again.', '#dc2626');
    }
  } else {
    row.scanned_codes.pop();
    row.qty = newQty;
    renderSalesReturnCart();
  }
}

function removeSalesReturnRow(idx) {
  srCart.splice(idx, 1);
  renderSalesReturnCart();
}

function renderSalesReturnCart() {
  const section = document.getElementById('src-cart-section');
  const listEl = document.getElementById('src-cart-list');
  const countBadge = document.getElementById('src-cart-count-badge');
  const summaryEl = document.getElementById('src-summary');

  if (srCart.length === 0) {
    section.style.display = 'none';
    summaryEl.textContent = 'No items scanned';
    return;
  }
  section.style.display = '';

  let totalUnits = 0, totalValue = 0;
  listEl.innerHTML = srCart.map((row, idx) => {
    totalUnits += row.qty;
    const lineTotal = round2(row.sell_unit * row.qty);
    totalValue += lineTotal;
    return `<div class="scanned-item-row">
      <div class="scanned-item-info">
        <span class="scanned-item-name">${row.item || '—'}${row.size ? ' <span class="scanned-item-size">'+row.size+'</span>' : ''}</span>
      </div>
      <div class="scanned-item-qty">
        <button onclick="changeSalesReturnQty(${idx}, -1)" style="padding:0 6px;font-size:14px;cursor:pointer">−</button>
        <span style="min-width:28px;text-align:center;display:inline-block">${row.qty}</span>
        <button onclick="changeSalesReturnQty(${idx}, 1)" style="padding:0 6px;font-size:14px;cursor:pointer">+</button>
      </div>
      <div class="scanned-item-price">${fmt(lineTotal)}</div>
      <button class="item-row-del" onclick="removeSalesReturnRow(${idx})" title="Remove"><i class="ti ti-x"></i></button>
    </div>`;
  }).join('');

  countBadge.textContent = totalUnits + ' unit' + (totalUnits > 1 ? 's' : '');
  summaryEl.textContent = `${totalUnits} item${totalUnits>1?'s':''} · Return total: ${fmt(totalValue)}`;
}

async function saveSalesReturnBarcodeBill() {
  if (!srCart.length) { showToast('Scan at least one item to return', '#dc2626'); return; }
  const reason = document.getElementById('src-reason').value.trim();
  // Flatten every claimed barcode into its own line -- the backend resolves
  // the originating sale from the barcode itself, one physical unit per line.
  const items = [];
  srCart.forEach(row => {
    row.scanned_codes.forEach(code => items.push({ barcode: code }));
  });
  try {
    const res = await fetch('/api/sales_return_bill', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ items, reason })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Return bill ${data.returnBillNo} saved`);
      srCart = [];
      document.getElementById('src-reason').value = '';
      renderSalesReturnCart();
      loadSalesReturnBills();
      loadDashboard();
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
      <td>${e.item || '—'}</td>
      <td>${e.qty}</td>
      <td>${fmt(e.sellTotal)}</td>
      <td>${e.date || '—'}</td>
      <td><button class="bc-btn" style="padding:4px 10px;font-size:12px" onclick="showReturnBills('sale',${i})"><i class="ti ti-info-circle"></i> More info</button></td>
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

