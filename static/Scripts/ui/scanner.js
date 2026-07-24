// =========================================================================
// ui/scanner.js
// Barcode-scanner input handling for the sale flow: reading scan-gun
// input, looking up items by barcode, and managing the scanned-items list.
// =========================================================================

let currentBarcodeInputTab = 'enter';

function switchBarcodeInputTab(tab) {
  currentBarcodeInputTab = tab;
  document.getElementById('sitab-enter').classList.toggle('active', tab === 'enter');
  document.getElementById('sitab-scan').classList.toggle('active', tab === 'scan');
  document.getElementById('bc-enter-panel').style.display = tab === 'enter' ? '' : 'none';
  document.getElementById('bc-scan-panel').style.display  = tab === 'scan'  ? '' : 'none';
  if (tab === 'scan') {
    setTimeout(() => focusScanInput(), 150);
  }
}

async function lookupAndAddBarcodeCode(code) {
  const statusEl = document.getElementById('bc-scan-status');
  if (!code) return;

  setStatus(statusEl, '⏳ Looking up...', 'info');
  try {
    const res = await fetch(`/api/barcode_lookup?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      const bc = data.barcode;
      // Same exact barcode already in cart — warn karo
      if (scannedItems.find(x => x.code === bc.code)) {
        setStatus(statusEl, `⚠ Yeh barcode already cart mein hai.`, 'warn');
        return;
      }
      // Alag barcode but same item+size — qty badhao
      const existing = scannedItems.find(x => x.purchase_item_id === bc.purchase_item_id);
      if (existing) {
        existing.qty += 1;
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
        renderScannedItems();
        return;
      }
      scannedItems.push({ code: bc.code, item: bc.item, size: bc.size, party: bc.party,
        sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
        purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code] });
      setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' ('+bc.size+')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
      renderScannedItems();
    } else if (data.status === 'already_sold') {
      setStatus(statusEl, '✗ ' + data.message, 'error');
    } else {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
}

// ─── BARCODE / PRODUCT NAME LIVE SEARCH ──────────────────────────────
// Config for each input that supports this search: which suggestion
// list element it fills, and whether it should match 'available' stock
// (selling / giving an item) or 'sold' stock (returning an item).
const PRODUCT_SEARCH_CONFIG = {
  enter: { inputId: 'f-bc-enter', listId: 'bc-enter-suggestions', status: 'available' },
  old:   { inputId: 'f-bc-old',   listId: 'bc-old-suggestions',   status: 'sold' },
  new:   { inputId: 'f-bc-new',   listId: 'bc-new-suggestions',   status: 'available' }
};

let productSearchTimer = null;
const productSearchMatches = { enter: [], old: [], new: [] };
const selectedProductMatch = { enter: null, old: null, new: null };

// Called on every keystroke in a barcode/product-name input.
function onProductSearchInput(key, value) {
  selectedProductMatch[key] = null;
  clearTimeout(productSearchTimer);
  const query = (value || '').trim();
  if (query.length < 2) {
    renderProductSuggestions(key, []);
    return;
  }
  productSearchTimer = setTimeout(() => fetchProductSuggestions(key, query), 250);
}

async function fetchProductSuggestions(key, query) {
  const cfg = PRODUCT_SEARCH_CONFIG[key];
  if (!cfg) return;
  try {
    const res = await fetch(`/api/product_search?query=${encodeURIComponent(query)}&status=${cfg.status}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      renderProductSuggestions(key, data.matches || []);
    }
  } catch (err) {
    // Search suggestions failing silently is fine — exact barcode Add still works.
  }
}

function renderProductSuggestions(key, matches) {
  productSearchMatches[key] = matches;
  const cfg = PRODUCT_SEARCH_CONFIG[key];
  const listEl = document.getElementById(cfg.listId);
  if (!listEl) return;

  if (!matches.length) {
    listEl.style.display = 'none';
    listEl.innerHTML = '';
    return;
  }

  listEl.style.display = '';
  listEl.innerHTML = matches.map((m, idx) => `
    <div class="product-suggest-row" onclick="selectProductSuggestion('${key}', ${idx})">
      <span class="product-suggest-name">${m.item || '—'}${m.size ? '<span class="product-suggest-size">(' + m.size + ')</span>' : ''}</span>
      <span class="product-suggest-meta">${m.party || '—'}</span>
      <span class="product-suggest-price">${fmt(m.sell_unit)}</span>
    </div>
  `).join('');
}

// User picked a row from the temporary suggestion list — just marks it
// selected; the actual add-to-cart happens when the Add button is pressed.
function selectProductSuggestion(key, idx) {
  const match = productSearchMatches[key][idx];
  if (!match) return;
  selectedProductMatch[key] = match;

  const cfg = PRODUCT_SEARCH_CONFIG[key];
  const input = document.getElementById(cfg.inputId);
  if (input) {
    input.value = `${match.item}${match.size ? ' (' + match.size + ')' : ''}`;
  }

  const listEl = document.getElementById(cfg.listId);
  if (listEl) {
    Array.from(listEl.children).forEach((row, i) => row.classList.toggle('selected', i === idx));
  }
}

function clearProductSuggestions(key) {
  selectedProductMatch[key] = null;
  productSearchMatches[key] = [];
  const cfg = PRODUCT_SEARCH_CONFIG[key];
  const listEl = document.getElementById(cfg.listId);
  if (listEl) { listEl.style.display = 'none'; listEl.innerHTML = ''; }
}

// Turns the currently selected suggestion into a fresh, not-yet-used
// barcode of that same product batch, excluding codes already claimed
// for it in the current cart/list.
async function resolveSelectedProductMatch(key, alreadyUsedCodes) {
  const match = selectedProductMatch[key];
  if (!match) return null;
  const cfg = PRODUCT_SEARCH_CONFIG[key];
  const exclude = (alreadyUsedCodes || []).join(',');
  const res = await fetch(`/api/barcode_by_item?purchase_item_id=${match.purchase_item_id}&status=${cfg.status}&exclude=${encodeURIComponent(exclude)}`);
  return res.json();
}

async function lookupAndAddBarcode(inputId) {
  const input = document.getElementById(inputId);
  const statusId = inputId === 'f-bc-enter' ? 'bc-enter-status' : 'bc-scan-status';
  const statusEl = document.getElementById(statusId);

  // A product was picked from the name-search suggestion list — add that
  // instead of treating the input text as a literal barcode number.
  if (inputId === 'f-bc-enter' && selectedProductMatch.enter) {
    await addSelectedProductToScannedItems('enter', statusEl, input);
    return;
  }

  const code = (input ? input.value.trim() : '');
  if (!code) return;

  setStatus(statusEl, '⏳ Looking up...', 'info');
  try {
    const res = await fetch(`/api/barcode_lookup?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      const bc = data.barcode;
      // Same exact barcode already in cart — warn karo
      if (scannedItems.find(x => x.code === bc.code)) {
        setStatus(statusEl, `⚠ Yeh barcode already cart mein hai.`, 'warn');
        if (input) { input.value = ''; input.focus(); }
        return;
      }
      // Alag barcode but same item+size — qty badhao
      const existing = scannedItems.find(x => x.purchase_item_id === bc.purchase_item_id);
      if (existing) {
        existing.qty += 1;
        // Track every scanned barcode so the backend can mark each one as sold
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
        renderScannedItems();
        if (input) { input.value = ''; input.focus(); }
        return;
      }
      scannedItems.push({ code: bc.code, item: bc.item, size: bc.size, party: bc.party,
        sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
        purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code] });

      setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' ('+bc.size+')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
      renderScannedItems();
    } else if (data.status === 'already_sold') {
      setStatus(statusEl, '✗ ' + data.message, 'error');
    } else {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
  if (input) { input.value = ''; input.focus(); }
}

// Adds the currently selected name-search suggestion (Sale entry panel) to
// the cart, claiming a fresh unused barcode of that product batch.
async function addSelectedProductToScannedItems(key, statusEl, input) {
  const match = selectedProductMatch[key];
  setStatus(statusEl, '⏳ Looking up...', 'info');
  const existing = scannedItems.find(x => x.purchase_item_id === match.purchase_item_id);
  const usedCodes = existing ? (existing.scanned_codes || [existing.code]) : [];
  try {
    const data = await resolveSelectedProductMatch(key, usedCodes);
    if (data && data.status === 'ok') {
      const bc = data.barcode;
      if (existing) {
        existing.qty += 1;
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
      } else {
        scannedItems.push({ code: bc.code, item: bc.item, size: bc.size, party: bc.party,
          sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
          purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code] });
        setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' ('+bc.size+')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
      }
      renderScannedItems();
    } else {
      setStatus(statusEl, '✗ ' + ((data && data.message) || 'No more stock available for this product.'), 'error');
    }
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
  }
  clearProductSuggestions(key);
  if (input) { input.value = ''; input.focus(); }
}

function updateScannedQty(idx, val) {
  if (!scannedItems[idx]) return;
  const newQty = parseInt(val, 10);
  if (!newQty || newQty < 1) { scannedItems[idx].qty = 1; renderScannedItems(); return; }
  scannedItems[idx].qty = newQty;
  renderScannedItems();
}

// Handles the +/- buttons next to the qty field. Increasing qty claims one
// more real, unused barcode of the same product batch (so the exact stock
// units sold always match scanned_codes); decreasing qty releases the most
// recently claimed one.
async function changeScannedQty(idx, delta) {
  const itm = scannedItems[idx];
  if (!itm) return;
  const newQty = (itm.qty || 1) + delta;
  if (newQty < 1) return;

  itm.scanned_codes = itm.scanned_codes || [itm.code];

  if (delta > 0) {
    try {
      const exclude = itm.scanned_codes.join(',');
      const res = await fetch(`/api/barcode_by_item?purchase_item_id=${itm.purchase_item_id}&status=available&exclude=${encodeURIComponent(exclude)}`);
      const data = await res.json();
      if (data.status === 'ok') {
        itm.scanned_codes.push(data.barcode.code);
        itm.qty = newQty;
        renderScannedItems();
      } else {
        showToast(data.message || 'No more stock available for this product.', '#dc2626');
      }
    } catch (err) {
      showToast('Could not check stock. Try again.', '#dc2626');
    }
  } else {
    itm.scanned_codes.pop();
    itm.qty = newQty;
    renderScannedItems();
  }
}

function setStatus(el, msg, type) {
  if (!el) return;
  const colors = { ok: '#16a34a', error: '#ef4444', warn: '#d97706', info: 'var(--color-text-secondary)' };
  el.textContent = msg;
  el.style.color = colors[type] || colors.info;
}

function renderScannedItems() {
  const section = document.getElementById('scanned-items-section');
  const listEl = document.getElementById('scanned-items-list');
  const countBadge = document.getElementById('scanned-count-badge');
  const totalRow = document.getElementById('scanned-total-row');
  const discount = parseFloat(document.getElementById('f-discount')?.value) || 0;

  if (scannedItems.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';
  countBadge.textContent = scannedItems.length + ' item' + (scannedItems.length > 1 ? 's' : '');

  let grandSell = 0;       // actual sale total AFTER discount — used for Sale Amount sync / split-payment check
  let grandOriginal = 0;   // original total BEFORE discount — used only for the on-screen display
  let grandBuy = 0;
  listEl.innerHTML = scannedItems.map((itm, idx) => {
    const qty = itm.qty || 1;
    const originalPrice = round2(itm.sell_unit * qty);
    const discountedUnit = round2(itm.sell_unit * (1 - discount / 100));
    const discountedPrice = round2(discountedUnit * qty);
    grandSell += discountedPrice;
    grandOriginal += originalPrice;
    grandBuy += itm.buy_unit * qty;
    const discBadge = discount > 0
      ? `<span class="margin-badge" style="background:var(--color-bg-accent);color:#ef4444;font-size:10px">${discount}%↓</span>`
      : '';
    return `<div class="scanned-item-row">
      <div class="scanned-item-info">
        <span class="scanned-item-name">${itm.item || '—'}${itm.size ? ' <span class="scanned-item-size">'+itm.size+'</span>' : ''}</span>
        <span class="scanned-item-code">${itm.code}</span>
      </div>
      <div class="scanned-item-qty">
        <button onclick="changeScannedQty(${idx}, -1)" style="padding:0 6px;font-size:14px;cursor:pointer">−</button>
        <span style="min-width:28px;text-align:center;display:inline-block">${qty}</span>
        <button onclick="changeScannedQty(${idx}, 1)" style="padding:0 6px;font-size:14px;cursor:pointer">+</button>
      </div>
      <div class="scanned-item-price">
        ${fmt(originalPrice)} ${discBadge}
        ${showPurchasePrice ? `<div style="font-size:11px;color:#16a34a;margin-top:2px">PP: ${fmt(round2(itm.buy_unit * qty))}</div>` : ''}
      </div>
      <button class="item-row-del" onclick="removeScannedItem(${idx})" title="Remove"><i class="ti ti-x"></i></button>
    </div>`;
  }).join('');

  // Split payment balance indicator
  const payMode = document.getElementById('f-payment-mode').value;
  const indicator = document.getElementById('split-balance-indicator');
  if (payMode === 'Split' && indicator) {
    const cashAmt   = parseFloat(document.getElementById('f-cash-amount').value)   || 0;
    const onlineAmt = parseFloat(document.getElementById('f-online-amount').value) || 0;
    const remaining = round2(grandSell - cashAmt - onlineAmt);
    indicator.textContent = remaining === 0
      ? '✓ Split amounts match total'
      : `Remaining: ₹${remaining}  (Total: ₹${grandSell})`;
    indicator.style.color = remaining === 0 ? '#16a34a' : '#ef4444';
  } else if (indicator) {
    indicator.textContent = '';
  }

  totalRow.innerHTML = `
    <span>Total: <strong>${fmt(grandOriginal)}</strong></span>
    ${showPurchasePrice ? `<span style="color:#16a34a">Purchase Price: ${fmt(grandBuy)}</span>` : ''}
    <span style="margin-left:auto">Final Sale Amount: <strong style="color:var(--color-text-success)">${fmt(grandSell)}</strong></span>
  `;

  // Keep the Sale Amount field in sync with the current discounted total,
  // but don't fight the user while they're actively typing into it.
  const saleAmtEl = document.getElementById('f-sale-amount');
  if (saleAmtEl && document.activeElement !== saleAmtEl) {
    saleAmtEl.value = grandSell > 0 ? grandSell : '';
  }
}

function togglePurchasePriceVisibility() {
  const checkbox = document.getElementById('toggle-purchase-price');
  showPurchasePrice = !!(checkbox && checkbox.checked);
  renderScannedItems();
}

function removeScannedItem(idx) {
  scannedItems.splice(idx, 1);
  renderScannedItems();
  if (scannedItems.length === 0) {
    const s1 = document.getElementById('bc-enter-status');
    const s2 = document.getElementById('bc-scan-status');
    if (s1) s1.textContent = '';
    if (s2) s2.textContent = '';
  }
}

function clearScannedItems() {
  scannedItems = [];
  renderScannedItems();
  const s1 = document.getElementById('bc-enter-status');
  const s2 = document.getElementById('bc-scan-status');
  if (s1) s1.textContent = '';
  if (s2) s2.textContent = '';
  clearProductSuggestions('enter');
}

function getScannedItems() {
    return scannedItems || [];
}

// ─── SCAN-GUN INPUT HANDLING ─────────────────────────────────────────

let scanBuffer = '';
let scanTimer = null;

function focusScanInput() {
  const inp = document.getElementById('f-bc-scan');
  if (inp) { inp.value = ''; inp.focus(); updateScanGunLabel('focused'); }
}

function updateScanGunLabel(state) {
  const label = document.getElementById('scan-gun-label');
  if (!label) return;
  if (state === 'focused') {
    label.textContent = '🟢 Scanner active — scan a barcode now';
  } else if (state === 'blur') {
    label.textContent = '🔴 Scanner paused — click here to activate';
  } else {
    label.textContent = 'Scanner ready — scan a barcode';
  }
}

function onScanInput(inputEl) {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(() => {
    const code = inputEl.value.trim();
    inputEl.value = '';
    if (code) {
      lookupAndAddBarcodeCode(code);
    }
  }, 80);
}

document.addEventListener('focusin', (e) => {
  if (e.target && e.target.id === 'f-bc-scan') {
    updateScanGunLabel('focused');
  }
});

document.addEventListener('focusout', (e) => {
  if (e.target && e.target.id === 'f-bc-scan') {
    updateScanGunLabel('blur');
  }
});

