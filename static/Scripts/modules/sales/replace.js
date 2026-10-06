// =========================================================================
// modules/sales/replace.js
// Item Replace / Exchange flow inside the scan-sell panel: the customer
// returns a previously sold item (scanned by barcode, must currently be
// 'sold') and takes a new item instead (scanned by barcode, must currently
// be 'available'). Shows a running difference:
//   positive -> customer pays the shop
//   negative -> shop refunds the customer
// and saves a Replace Bill on confirm.
// =========================================================================

let replaceOldItems = [];
let replaceNewItems = [];

function switchSellPanelMode(mode) {
  const isReplace = mode === 'replace';
  document.getElementById('sell-panel-mode-sell').classList.toggle('active', !isReplace);
  document.getElementById('sell-panel-mode-replace').classList.toggle('active', isReplace);
  document.getElementById('sell-barcode-panel').style.display = isReplace ? 'none' : '';
  document.getElementById('replace-panel').style.display = isReplace ? '' : 'none';
  if (isReplace) loadReplaceBills();
}

async function lookupAndAddReplaceBarcode(side, inputId) {
  const input = document.getElementById(inputId);
  const statusEl = document.getElementById(side === 'old' ? 'bc-old-status' : 'bc-new-status');

  // A product was picked from the name-search suggestion list — add that
  // instead of treating the input text as a literal barcode number.
  if (selectedProductMatch[side]) {
    await addSelectedProductToReplaceList(side, statusEl, input);
    return;
  }

  const code = (input ? input.value.trim() : '');
  if (!code) return;

  const list = side === 'old' ? replaceOldItems : replaceNewItems;
  const endpoint = side === 'old' ? '/api/barcode_lookup_sold' : '/api/barcode_lookup';
  console.log(endpoint)

  setStatus(statusEl, '⏳ Looking up...', 'info');
  try {
    const res = await fetch(`${endpoint}?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      const bc = data.barcode;
      if (list.find(x => x.code === bc.code)) {
        setStatus(statusEl, `⚠ This barcode is already in the list.`, 'warn');
        if (input) { input.value = ''; input.focus(); }
        return;
      }
      const existing = list.find(x => x.purchase_item_id === bc.purchase_item_id);
      if (existing) {
        existing.qty += 1;
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
      } else {
        list.push({
          code: bc.code, item: bc.item, size: bc.size,
          sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
          purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code]
        });
        setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' (' + bc.size + ')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
      }
      renderReplaceItems();
    } else if (data.status === 'not_sold' || data.status === 'already_sold') {
      setStatus(statusEl, '✗ ' + data.message, 'error');
    } else {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
  if (input) { input.value = ''; input.focus(); }
}

// Adds the currently selected name-search suggestion (Replace/Exchange
// old or new panel) to the relevant list, claiming a fresh unused
// barcode of that product batch.
async function addSelectedProductToReplaceList(side, statusEl, input) {
  const match = selectedProductMatch[side];
  const list = side === 'old' ? replaceOldItems : replaceNewItems;
  setStatus(statusEl, '⏳ Looking up...', 'info');
  const existing = list.find(x => x.purchase_item_id === match.purchase_item_id);
  const usedCodes = existing ? (existing.scanned_codes || [existing.code]) : [];
  try {
    const data = await resolveSelectedProductMatch(side, usedCodes);
    if (data && data.status === 'ok') {
      const bc = data.barcode;
      if (existing) {
        existing.qty += 1;
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
      } else {
        list.push({
          code: bc.code, item: bc.item, size: bc.size,
          sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
          purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code]
        });
        setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' (' + bc.size + ')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
      }
      renderReplaceItems();
    } else {
      setStatus(statusEl, '✗ ' + ((data && data.message) || 'No more matching units found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
  clearProductSuggestions(side);
  if (input) { input.value = ''; input.focus(); }
}

function removeReplaceItem(side, idx) {
  const list = side === 'old' ? replaceOldItems : replaceNewItems;
  list.splice(idx, 1);
  renderReplaceItems();
}

function renderReplaceSide(side) {
  const list = side === 'old' ? replaceOldItems : replaceNewItems;
  const sectionEl = document.getElementById(`replace-${side}-section`);
  const listEl = document.getElementById(`replace-${side}-list`);
  const totalRowEl = document.getElementById(`replace-${side}-total-row`);
  const emptyEl = document.getElementById(`replace-${side}-empty`);

  if (!list.length) {
    if (sectionEl) sectionEl.style.display = 'none';
    if (emptyEl) emptyEl.style.display = '';
    return { total: 0, original: 0 };
  }
  if (sectionEl) sectionEl.style.display = '';
  if (emptyEl) emptyEl.style.display = 'none';

  // Discount / per-item price overrides only apply to the Give ('new') side.
  const discount = side === 'new' ? (parseFloat(document.getElementById('f-replace-discount')?.value) || 0) : 0;

  let total = 0;
  let original = 0;
  listEl.innerHTML = list.map((itm, idx) => {
    const qty = itm.qty || 1;
    const originalPrice = round2(itm.sell_unit * qty);
    const lineTotal = side === 'new' ? getReplaceItemDiscountedTotal(itm, discount) : originalPrice;
    total += lineTotal;
    original += originalPrice;
    const isOverridden = side === 'new' && itm.lineTotalOverride != null && !isNaN(itm.lineTotalOverride);
    const discBadge = side !== 'new' ? '' : (isOverridden
      ? `<span class="margin-badge" style="background:var(--color-bg-accent);color:var(--color-text-success);font-size:10px">✎ edited</span>`
      : (discount > 0 ? `<span class="margin-badge" style="background:var(--color-bg-accent);color:#ef4444;font-size:10px">${discount}%↓</span>` : ''));
    return `<div class="replace-item-row" style="display:grid;grid-template-columns:2fr 1fr 0.7fr 1fr;gap:0;align-items:center;padding:8px 14px;border-bottom:1px solid var(--color-border-secondary);font-size:13px">
      <span style="color:var(--color-text-primary);font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${itm.item || ''}">${itm.item || '—'}</span>
      <span style="color:var(--color-text-secondary)">${itm.size || '—'}</span>
      <span style="display:flex;align-items:center;gap:4px">
        <button onclick="openItemBarcodeModal('${side}', ${idx})" style="padding:0 4px;font-size:13px;cursor:pointer;background:none;border:none;color:var(--color-text-secondary)">−</button>
        <span style="min-width:20px;text-align:center">${qty}</span>
        <button onclick="openItemBarcodeModal('${side}', ${idx})" style="padding:0 4px;font-size:13px;cursor:pointer;background:none;border:none;color:var(--color-text-secondary)">+</button>
      </span>
      <span style="display:flex;align-items:center;justify-content:space-between;gap:4px">
        <span>${fmt(lineTotal)} ${discBadge}</span>
        <button class="item-row-del" onclick="removeReplaceItem('${side}', ${idx})" title="Remove" style="padding:2px 4px"><i class="ti ti-x"></i></button>
      </span>
    </div>`;
  }).join('');

  total = round2(total);
  original = round2(original);
  const label = side === 'old' ? 'Return Total' : 'Give Total';
  totalRowEl.innerHTML = `<span>${label}: <strong>${fmt(total)}</strong></span>`;
  return { total, original };
}

function renderReplaceItems() {
  const oldResult = renderReplaceSide('old');
  const newResult = renderReplaceSide('new');
  const oldTotal = oldResult.total;
  const rawNewTotal = newResult.original;
  const newTotal = newResult.total;

  const discount = parseFloat(document.getElementById('f-replace-discount')?.value) || 0;

  const discPreview = document.getElementById('replace-discount-preview');
  const saleAmtEl = document.getElementById('f-replace-sale-amount');
  const discAmtEl = document.getElementById('f-replace-discount-amount');
  if (discPreview) {
    if (discount <= 0) {
      discPreview.innerHTML = '<span style="color:var(--color-text-tertiary)">No discount applied</span>';
      if (saleAmtEl && document.activeElement !== saleAmtEl) saleAmtEl.value = '';
      if (discAmtEl && document.activeElement !== discAmtEl) discAmtEl.value = '';
    } else if (discount >= 100) {
      discPreview.innerHTML = '<span style="color:var(--color-text-danger)"><i class="ti ti-alert-circle"></i> Max 99.9% allowed</span>';
    } else {
      const saved = round2(rawNewTotal - newTotal);
      discPreview.innerHTML = saved > 0
        ? `<span style="color:var(--color-text-success);font-weight:600"><i class="ti ti-rosette-discount"></i> Save ${fmt(saved)}</span>
           <span style="color:var(--color-text-tertiary);margin-left:8px">→ Give Total: <strong style="color:var(--color-text-primary)">${fmt(newTotal)}</strong></span>`
        : `<span style="color:var(--color-text-secondary)">${discount}% discount will be applied</span>`;
      if (saleAmtEl && document.activeElement !== saleAmtEl) saleAmtEl.value = newTotal > 0 ? newTotal : '';
      if (discAmtEl && document.activeElement !== discAmtEl) discAmtEl.value = saved > 0 ? saved : '';
    }
  }

  renderReplaceDiscountBreakdown();

  const difference = round2(newTotal - oldTotal);
  const summaryEl = document.getElementById('replace-summary-row');
  if (!summaryEl) return;

  const color = difference > 0 ? '#ef4444' : (difference < 0 ? '#16a34a' : 'var(--color-text-secondary)');
  const label = difference > 0
    ? `Customer pays: ${fmt(difference)}`
    : difference < 0
      ? `Refund to customer: ${fmt(Math.abs(difference))}`
      : 'No amount due either side';

  summaryEl.innerHTML = `
    <span>Return Total: <strong>${fmt(oldTotal)}</strong></span>
    <span>Give Total: <strong>${fmt(newTotal)}</strong>${discount > 0 ? ` <span style="color:var(--color-text-tertiary);font-size:12px">(${discount}% off ${fmt(rawNewTotal)})</span>` : ''}</span>
    <span style="color:${color}">${label} (${difference > 0 ? '+' : ''}${fmt(difference)})</span>
  `;

  const totalReplacePrice = round2(oldTotal + newTotal);
  const totalPriceEl = document.getElementById('replace-total-price-row');
  if (totalPriceEl) {
    totalPriceEl.innerHTML = `<span>Total Replace Price: <strong style="color:var(--color-text-primary)">${fmt(totalReplacePrice)}</strong></span>`;
  }
}

function clearReplaceItems() {
  replaceOldItems = [];
  replaceNewItems = [];
  window.replaceExactFinalTotal = null;
  const noteEl = document.getElementById('f-replace-note');
  if (noteEl) noteEl.value = '';
  const discEl = document.getElementById('f-replace-discount');
  if (discEl) discEl.value = '';
  const saleAmtEl = document.getElementById('f-replace-sale-amount');
  if (saleAmtEl) saleAmtEl.value = '';
  const discAmtEl = document.getElementById('f-replace-discount-amount');
  if (discAmtEl) discAmtEl.value = '';
  document.querySelectorAll('#replace-discount-section .disc-preset').forEach(b => b.classList.remove('active'));
  renderReplaceItems();
  const s1 = document.getElementById('bc-old-status');
  const s2 = document.getElementById('bc-new-status');
  if (s1) s1.textContent = '';
  if (s2) s2.textContent = '';
  clearProductSuggestions('old');
  clearProductSuggestions('new');
  const totalPriceEl = document.getElementById('replace-total-price-row');
  if (totalPriceEl) totalPriceEl.innerHTML = '';
}

async function saveReplaceSale() {
  if (!replaceOldItems.length && !replaceNewItems.length) {
    showToast('Add at least one item to replace', '#dc2626');
    return;
  }
  const payload = {
    customerName: document.getElementById('f-customer-name')?.value.trim() || '',
    customerNo: document.getElementById('f-customer-no')?.value.trim() || '',
    note: document.getElementById('f-replace-note')?.value.trim() || '',
    discount: Math.round(parseFloat(document.getElementById('f-replace-discount')?.value) || 0),
    // Exact Give Amount if the user typed one (or edited a per-item price) --
    // same idea as Sell's final_total, so rounding doesn't drift the total.
    finalGiveTotal: (window.replaceExactFinalTotal != null && !isNaN(window.replaceExactFinalTotal))
      ? round2(window.replaceExactFinalTotal) : null,
    oldItems: replaceOldItems,
    newItems: replaceNewItems.map(it => {
      const discount = Math.round(parseFloat(document.getElementById('f-replace-discount')?.value) || 0);
      return {
        ...it,
        line_total_override: round2(getReplaceItemDiscountedTotal(it, discount))
      };
    })
  };
  try {
    const res = await fetch('/api/replace_sale', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.status === 'ok') {
      const diff = data.difference;
      const msg = diff > 0
        ? `Replace bill ${data.replaceBillNo} saved. Customer pays ${fmt(diff)}.`
        : diff < 0
          ? `Replace bill ${data.replaceBillNo} saved. Refund customer ${fmt(Math.abs(diff))}.`
          : `Replace bill ${data.replaceBillNo} saved. No amount due either side.`;
      showToast(msg);
      clearReplaceItems();
      loadReplaceBills();
    } else {
      showToast(data.message || 'Could not save replace bill', '#dc2626');
    }
  } catch (e) {
    showToast('Could not save replace bill', '#dc2626');
  }
}

// ─── REPLACE BILLS HISTORY ─────────────────────────────────────────

let replaceBillsAllRows = [];

async function loadReplaceBills() {
  try {
    const res = await fetch('/api/replace_bills');
    replaceBillsAllRows = await res.json();
    renderReplaceBills(replaceBillsAllRows);
  } catch (e) { /* ignore */ }
}

function renderReplaceBills(rows) {
  const tbody = document.getElementById('replace-bills-tbody');
  const emptyEl = document.getElementById('replace-bills-empty');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  tbody.innerHTML = rows.map((e, i) => {
    const diff = e.difference || 0;
    const diffColor = diff > 0 ? '#ef4444' : (diff < 0 ? '#16a34a' : 'inherit');
    return `<tr>
      <td>${i + 1}</td>
      <td>${e.replaceBillNo || '—'}</td>
      <td>${(e.date || '—').slice(0, 16)}</td>
      <td>${e.customerName || '—'}</td>
      <td>${fmt(e.oldTotal)}</td>
      <td>${fmt(e.newTotal)}</td>
      <td style="color:${diffColor}">${diff > 0 ? '+' : ''}${fmt(diff)}</td>
      <td>${e.note || '—'}</td>
    </tr>`;
  }).join('');
}