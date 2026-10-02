let prCart = [];

let prScanTimer = null;

function focusPurchaseReturnScanInput() {
  const inp = document.getElementById('pr-bc-scan');
  if (inp) { inp.value = ''; inp.focus(); updatePurchaseReturnScanLabel('focused'); }
}

function updatePurchaseReturnScanLabel(state) {
  const label = document.getElementById('pr-scan-gun-label');
  if (!label) return;
  if (state === 'focused') {
    label.textContent = '🟢 Scanner active — scan a barcode now';
  } else if (state === 'blur') {
    label.textContent = '🔴 Scanner paused — click here to activate';
  } else {
    label.textContent = 'Scanner ready — scan a barcode';
  }
}

function onPurchaseReturnScanInput(inputEl) {
  clearTimeout(prScanTimer);
  prScanTimer = setTimeout(() => {
    const code = inputEl.value.trim();
    inputEl.value = '';
    if (code) lookupAndAddPurchaseReturnCode(code);
  }, 80);
}

document.addEventListener('focusin', (e) => {
  if (e.target && e.target.id === 'pr-bc-scan') updatePurchaseReturnScanLabel('focused');
});
document.addEventListener('focusout', (e) => {
  if (e.target && e.target.id === 'pr-bc-scan') updatePurchaseReturnScanLabel('blur');
});

// ─── ENTER / SCAN TAB SWITCH ─────────────────────────────────────────

function switchPurchaseReturnInputTab(tab) {
  document.getElementById('pr-sitab-enter').classList.toggle('active', tab === 'enter');
  document.getElementById('pr-sitab-scan').classList.toggle('active', tab === 'scan');
  document.getElementById('pr-bc-enter-panel').style.display = tab === 'enter' ? '' : 'none';
  document.getElementById('pr-bc-scan-panel').style.display  = tab === 'scan'  ? '' : 'none';
  if (tab === 'scan') {
    setTimeout(() => focusPurchaseReturnScanInput(), 150);
  }
}

// ─── MANUAL BARCODE ENTRY → CART ────────────────────────────────────

async function lookupAndAddPurchaseReturnBarcode(inputId) {
  const input = document.getElementById(inputId);
  const statusEl = document.getElementById('pr-bc-enter-status');
  const code = (input ? input.value.trim() : '');
  if (!code) return;
  setStatus(statusEl, '⏳ Looking up...', 'info');
  try {
    const res = await fetch(`/api/barcode_lookup?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      addBarcodeToPurchaseReturnCart(data.barcode, statusEl);
      if (input) { input.value = ''; input.focus(); }
    } else {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
}

// ─── SCAN-GUN → CART ─────────────────────────────────────────────────

async function lookupAndAddPurchaseReturnCode(code) {
  const statusEl = document.getElementById('pr-scan-status');
  if (!code) return;
  setStatus(statusEl, '⏳ Looking up...', 'info');
  try {
    const res = await fetch(`/api/barcode_lookup?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      addBarcodeToPurchaseReturnCart(data.barcode, statusEl);
    } else {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
}

function addBarcodeToPurchaseReturnCart(bc, statusEl) {
  // Same exact barcode already queued for return — warn instead of double-counting.
  if (prCart.some(row => row.scanned_codes.includes(bc.code))) {
    setStatus(statusEl, '⚠ This barcode is already in the return list.', 'warn');
    return;
  }
  // Different barcode but same item batch — bump that row's qty instead of a duplicate row.
  const existing = prCart.find(row => row.purchase_item_id === bc.purchase_item_id);
  if (existing) {
    existing.qty += 1;
    existing.scanned_codes.push(bc.code);
    setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
  } else {
    prCart.push({
      purchase_item_id: bc.purchase_item_id,
      item: bc.item, size: bc.size, party: bc.party,
      buy_unit: bc.buy_unit,
      invoiceNo: bc.invoiceNo, invoiceDate: bc.invoiceDate,
      qty: 1, scanned_codes: [bc.code]
    });
    setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' ('+bc.size+')' : ''}`, 'ok');
  }
  renderPurchaseReturnCart();
}

// +/- both open the same "Manage Barcodes" popup used by the Sales panel
// (see ui/scanner.js openItemBarcodeModal, source 'pr') -- qty is never
// guessed automatically. In the popup, scanning/entering a barcode number
// selects it (if unused stock of this same item batch) or de-selects it
// if it's already in the list.
function changePurchaseReturnQty(idx) {
  openItemBarcodeModal('pr', idx);
}

function removePurchaseReturnRow(idx) {
  prCart.splice(idx, 1);
  renderPurchaseReturnCart();
}

function renderPurchaseReturnCart() {
  const section = document.getElementById('pr-cart-section');
  const listEl = document.getElementById('pr-cart-list');
  const countBadge = document.getElementById('pr-cart-count-badge');
  const summaryEl = document.getElementById('pr-summary');

  if (prCart.length === 0) {
    section.style.display = 'none';
    summaryEl.textContent = 'No items scanned';
    return;
  }
  section.style.display = '';

  let totalUnits = 0, totalValue = 0;
  listEl.innerHTML = prCart.map((row, idx) => {
    totalUnits += row.qty;
    const lineTotal = round2(row.buy_unit * row.qty);
    totalValue += lineTotal;
    return `<div class="scanned-item-row">
      <div class="scanned-item-info">
        <span class="scanned-item-name">${row.item || '—'}${row.size ? ' <span class="scanned-item-size">'+row.size+'</span>' : ''}</span>
        <span class="scanned-item-code" style="word-break:break-word;white-space:normal">${(row.scanned_codes && row.scanned_codes.length ? row.scanned_codes : []).join(', ')}</span>
        <span style="font-size:11px;color:var(--color-text-tertiary)">${row.party || '—'}${row.invoiceNo ? ' · Inv ' + row.invoiceNo : ''}${row.invoiceDate ? ' (' + row.invoiceDate + ')' : ''}</span>
      </div>
      <div class="scanned-item-qty">
        <button onclick="changePurchaseReturnQty(${idx})" style="padding:0 6px;font-size:14px;cursor:pointer">−</button>
        <span style="min-width:28px;text-align:center;display:inline-block">${row.qty}</span>
        <button onclick="changePurchaseReturnQty(${idx})" style="padding:0 6px;font-size:14px;cursor:pointer">+</button>
      </div>
      <div class="scanned-item-price">${fmt(lineTotal)}</div>
      <button class="item-row-del" onclick="removePurchaseReturnRow(${idx})" title="Remove"><i class="ti ti-x"></i></button>
    </div>`;
  }).join('');

  countBadge.textContent = totalUnits + ' unit' + (totalUnits > 1 ? 's' : '');
  summaryEl.textContent = `${totalUnits} item${totalUnits>1?'s':''} · Return total: ${fmt(totalValue)}`;
}

async function savePurchaseReturnBill() {
  if (!prCart.length) { showToast('Scan at least one item to return', '#dc2626'); return; }
  const reason = document.getElementById('pr-reason').value.trim();
  // Flatten every claimed barcode into its own line -- the backend's
  // barcode path returns exactly one physical unit per barcode, so a row
  // with qty 3 becomes 3 separate { barcode } entries here.
  const items = [];
  prCart.forEach(row => {
    row.scanned_codes.forEach(code => items.push({ barcode: code }));
  });
  try {
    const res = await fetch('/api/purchase_return_bill', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ items, reason })
    });
    const data = await res.json();
    if (data.status === 'ok') {
      showToast(`Return bill ${data.returnBillNo} saved`);
      prCart = [];
      document.getElementById('pr-reason').value = '';
      renderPurchaseReturnCart();
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
      <td>${e.item || '—'}</td>
      <td>${e.qty}</td>
      <td>${fmt(e.buyTotal)}</td>
      <td>${e.date || '—'}</td>
      <td><button class="bc-btn" style="padding:4px 10px;font-size:12px" onclick="showReturnBills('purchase',${i})"><i class="ti ti-info-circle"></i> More info</button></td>
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

