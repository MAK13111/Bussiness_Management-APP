// =========================================================================
// ui/scanner.js
// Barcode-scanner input handling for the sale flow: reading scan-gun
// input, looking up items by barcode, and managing the scanned-items list.
// =========================================================================

let currentBarcodeInputTab = 'enter';

// ─── SMART BARCODE ROUTING HELPERS ───────────────────────────────────────────
// If the entered code contains any letter (A-Z / a-z) → it's an Old Stock
// item code from the legacy xlsx database (old_data table).
// If the code is purely digits with length >= 5 → it's a regular barcode.

function _isOldDataCode(code) {
  return /[a-zA-Z]/.test(code);
}

function _isNewBarcode(code) {
  return /^\d{5,}$/.test(code);
}

function _escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── OLD DATA DUPLICATE ITEM PICKER MODAL ─────────────────────────────────────
let _activeOldDataMatches = null;
let _activeOldDataStatusEl = null;
let _activeOldDataInputEl = null;
let _activeOldDataCallback = null;

function showOldDataDuplicatePicker(matches, statusEl, inputEl, onSelectCallback = null, actionType = 'sell') {
  const modal = document.getElementById('old-data-picker-modal');
  const listEl = document.getElementById('old-data-picker-list');
  const introEl = document.getElementById('old-data-picker-intro');
  const titleEl = document.getElementById('old-data-picker-title');
  const subtitleEl = document.getElementById('old-data-picker-subtitle');
  const iconEl = document.getElementById('old-data-picker-icon');
  const searchWrap = document.getElementById('old-data-search-wrap');
  const searchInput = document.getElementById('old-data-picker-search');
  const searchClear = document.getElementById('old-data-search-clear');
  if (!modal || !listEl) return;

  const itemCode = matches && matches[0] ? (matches[0].code || matches[0].item) : '';
  const isReturn = (actionType === 'return');

  if (titleEl) {
    titleEl.textContent = isReturn ? 'Select Old Stock Item to Return' : 'Select Item Variant';
  }
  if (subtitleEl) {
    subtitleEl.textContent = isReturn
      ? 'Choose which record matches the returned item'
      : 'Found multiple records in Old Stock with different prices';
  }
  if (iconEl) {
    iconEl.className = isReturn ? 'ti ti-rotate-clockwise' : 'ti ti-layers-difference';
  }

  if (introEl) {
    introEl.innerHTML = `
      <span>Found <span class="old-data-count-pill">${matches.length} Options</span> for</span>
      <span class="old-data-item-pill"><i class="ti ti-barcode"></i> ${_escapeHtml(itemCode)}</span>
      <span style="color:var(--color-text-tertiary);font-size:12px;">• Please choose the item to ${isReturn ? 'return' : 'sell'}:</span>
    `;
  }

  // Reset search filter
  if (searchInput) searchInput.value = '';
  if (searchClear) searchClear.style.display = 'none';
  if (searchWrap) {
    searchWrap.style.display = (matches.length > 3) ? 'flex' : 'none';
  }

  const btnActionText = isReturn ? 'Return' : 'Choose';
  const btnIcon = isReturn ? 'ti-rotate-clockwise' : 'ti-check';

  listEl.innerHTML = matches.map((m, idx) => {
    const stockBadge = m.remaining > 0
      ? `<span class="picker-card-stock in-stock"><span class="picker-stock-dot"></span> <strong>${m.remaining}</strong> in stock</span>`
      : `<span class="picker-card-stock out-of-stock"><span class="picker-stock-dot"></span> 0 in stock (${m.sold || 0} sold)</span>`;

    const uidText = m.uniqee_id ? `UID #${m.uniqee_id}` : `ID #${m.id}`;
    const sizeBadge = m.size
      ? `<span class="picker-card-size"><i class="ti ti-ruler-2" style="font-size:11px"></i> Size <strong>${_escapeHtml(m.size)}</strong></span>`
      : '';

    const shortcutNumber = idx < 9 ? (idx + 1) : '•';
    const searchTokens = `${m.item || ''} ${m.code || ''} ${m.size || ''} ${m.uniqee_id || ''} ${m.id || ''} ${m.sell_unit || ''} ${m.buy_unit || ''}`.toLowerCase();

    return `
      <div class="old-data-picker-card" 
           tabindex="0"
           data-index="${idx}"
           data-search="${_escapeHtml(searchTokens)}"
           onclick="selectOldDataPickerItem(${idx})"
           onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();selectOldDataPickerItem(${idx})}">
        
        <div class="picker-card-left">
          <div class="picker-shortcut-badge" title="Shortcut: Press ${shortcutNumber}">${shortcutNumber}</div>
          
          <div class="picker-card-details">
            <div class="picker-card-top-row">
              <span class="picker-card-name" title="${_escapeHtml(m.item || m.code)}">${_escapeHtml(m.item || m.code)}</span>
              ${sizeBadge}
              <span class="picker-card-uid">${uidText}</span>
            </div>
            
            <div class="picker-card-meta-row">
              ${stockBadge}
              ${m.buy_unit ? `<span class="picker-meta-item"><span style="color:var(--color-text-tertiary);">Cost / MRP:</span> <strong>${fmt(m.buy_unit)}</strong></span>` : ''}
              ${m.sold != null ? `<span class="picker-meta-item"><span style="color:var(--color-text-tertiary);">Sold:</span> <strong>${m.sold}</strong></span>` : ''}
              ${m.party && m.party !== 'Old Stock' ? `<span class="picker-meta-item"><span style="color:var(--color-text-tertiary);">Party:</span> ${_escapeHtml(m.party)}</span>` : ''}
            </div>
          </div>
        </div>

        <div class="picker-card-right">
          <div class="picker-price-block">
            <div class="picker-price-label">${isReturn ? 'Return Price' : 'Sale Price'}</div>
            <div class="picker-price-value">${fmt(m.sell_unit)}</div>
          </div>
          <button type="button" class="picker-btn-action" onclick="event.stopPropagation();selectOldDataPickerItem(${idx})">
            <i class="ti ${btnIcon}"></i> ${btnActionText}
          </button>
        </div>

      </div>
    `;
  }).join('');

  _activeOldDataMatches = matches;
  _activeOldDataStatusEl = statusEl;
  _activeOldDataInputEl = inputEl;
  _activeOldDataCallback = onSelectCallback;

  modal.style.display = 'flex';
  modal.classList.add('active');

  setTimeout(() => {
    const firstCard = listEl.querySelector('.old-data-picker-card');
    if (firstCard) firstCard.focus();
  }, 80);
}

// Instant client-side filter
window.filterOldDataPicker = function(query) {
  const modal = document.getElementById('old-data-picker-modal');
  if (!modal) return;
  const q = (query || '').trim().toLowerCase();
  const clearBtn = document.getElementById('old-data-search-clear');
  if (clearBtn) clearBtn.style.display = q ? 'flex' : 'none';

  const cards = modal.querySelectorAll('.old-data-picker-card');
  let visibleCount = 0;

  cards.forEach(card => {
    const text = (card.getAttribute('data-search') || '').toLowerCase();
    const matches = !q || text.includes(q);
    card.style.display = matches ? 'flex' : 'none';
    if (matches) visibleCount++;
  });

  let emptyEl = document.getElementById('old-data-picker-empty');
  if (visibleCount === 0) {
    if (!emptyEl) {
      emptyEl = document.createElement('div');
      emptyEl.id = 'old-data-picker-empty';
      emptyEl.className = 'picker-empty-state';
      emptyEl.innerHTML = `<i class="ti ti-search-off"></i><span>No matching items found for "<strong>${_escapeHtml(query)}</strong>"</span>`;
      const listEl = document.getElementById('old-data-picker-list');
      if (listEl) listEl.appendChild(emptyEl);
    } else {
      emptyEl.style.display = 'flex';
      emptyEl.innerHTML = `<i class="ti ti-search-off"></i><span>No matching items found for "<strong>${_escapeHtml(query)}</strong>"</span>`;
    }
  } else if (emptyEl) {
    emptyEl.style.display = 'none';
  }
};

window.clearOldDataPickerFilter = function() {
  const input = document.getElementById('old-data-picker-search');
  if (input) {
    input.value = '';
    input.focus();
    window.filterOldDataPicker('');
  }
};

function selectOldDataPickerItem(idx) {
  const matches = _activeOldDataMatches;
  const statusEl = _activeOldDataStatusEl;
  const inputEl = _activeOldDataInputEl;
  const callback = _activeOldDataCallback;
  if (!matches || !matches[idx]) return;

  const chosen = matches[idx];
  closeOldDataPickerModal();

  if (callback && typeof callback === 'function') {
    callback(chosen);
  } else {
    _addOldDataItemToCart(chosen, statusEl);
  }

  if (inputEl) {
    inputEl.value = '';
    inputEl.focus();
  }
}

function closeOldDataPickerModal() {
  const modal = document.getElementById('old-data-picker-modal');
  if (modal) {
    modal.style.display = 'none';
    modal.classList.remove('active');
  }
  _activeOldDataMatches = null;
  _activeOldDataCallback = null;
  if (_activeOldDataInputEl) {
    _activeOldDataInputEl.focus();
  }
}

// Keyboard navigation (Escape, Up/Down arrow keys, 1-9 shortcuts, / to search)
document.addEventListener('keydown', (e) => {
  const modal = document.getElementById('old-data-picker-modal');
  if (!modal || modal.style.display === 'none') return;

  if (e.key === 'Escape') {
    e.preventDefault();
    const searchInput = document.getElementById('old-data-picker-search');
    if (searchInput && searchInput.value) {
      clearOldDataPickerFilter();
    } else {
      closeOldDataPickerModal();
    }
    return;
  }

  const isSearchActive = (document.activeElement && document.activeElement.id === 'old-data-picker-search');

  // Focus search with '/' if not already typing
  if (e.key === '/' && !isSearchActive) {
    const searchInput = document.getElementById('old-data-picker-search');
    if (searchInput && searchInput.offsetParent !== null) {
      e.preventDefault();
      searchInput.focus();
      return;
    }
  }

  // Arrow key navigation between visible cards
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const visibleCards = Array.from(modal.querySelectorAll('.old-data-picker-card:not([style*="display: none"])'));
    if (!visibleCards.length) return;
    
    if (isSearchActive) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        visibleCards[0].focus();
        return;
      }
    } else {
      const currentIdx = visibleCards.indexOf(document.activeElement);
      e.preventDefault();
      if (e.key === 'ArrowDown') {
        const nextCard = (currentIdx >= 0 && currentIdx < visibleCards.length - 1) ? visibleCards[currentIdx + 1] : visibleCards[0];
        nextCard.focus();
      } else {
        const prevCard = (currentIdx > 0) ? visibleCards[currentIdx - 1] : visibleCards[visibleCards.length - 1];
        prevCard.focus();
      }
      return;
    }
  }

  // Quick 1-9 picking (only when not typing in the search box)
  if (!isSearchActive && _activeOldDataMatches && _activeOldDataMatches.length > 0) {
    const num = parseInt(e.key, 10);
    if (!isNaN(num) && num >= 1 && num <= 9) {
      const visibleCards = Array.from(modal.querySelectorAll('.old-data-picker-card:not([style*="display: none"])'));
      if (visibleCards[num - 1]) {
        e.preventDefault();
        const originalIdx = parseInt(visibleCards[num - 1].getAttribute('data-index'), 10);
        selectOldDataPickerItem(originalIdx);
      }
    }
  }
});

function changeOldDataQty(idx, delta) {
  const itm = scannedItems[idx];
  if (!itm) return;
  const newQty = (itm.qty || 1) + delta;
  delete itm.lineTotalOverride;
  if (newQty <= 0) {
    removeScannedItem(idx);
    return;
  }
  itm.qty = newQty;
  renderScannedItems();
}

// Shared helper: add an old_data item to the scanned cart.
// bc = the barcode object returned by /api/old_data_lookup.
function _addOldDataItemToCart(bc, statusEl) {
  // If the same exact old_data record (by id) is already in cart, bump qty.
  // Matching by old_data_id keeps distinct rows with duplicate item_code distinct
  // (e.g. different sizes, or same size at different prices).
  const existing = scannedItems.find(x => x.is_old_data && ((x.old_data_id && x.old_data_id === bc.id) || (x.purchase_item_id && x.purchase_item_id === bc.id)));
  if (existing) {
    existing.qty += 1;
    delete existing.lineTotalOverride;
    setStatus(statusEl, `✓ Qty updated: ${existing.item} (Price: ${fmt(existing.sell_unit)}) × ${existing.qty}`, 'ok');
    renderScannedItems();
    return;
  }
  scannedItems.push({
    code:             bc.code,
    item:             bc.item || bc.code,
    size:             bc.size || '',
    party:            bc.party || 'Old Stock',
    sell_unit:        bc.sell_unit,
    buy_unit:         bc.buy_unit,
    margin:           0,
    purchase_item_id: bc.id || bc.purchase_item_id,
    qty:              1,
    scanned_codes:    [bc.code],
    is_old_data:      true,           // tells sale-submit to route to old_data table
    old_data_id:      bc.id || bc.purchase_item_id, // old_data.id for stock decrement
    uniqee_id:        bc.uniqee_id || null,
    remaining:        bc.remaining,
  });
  setStatus(statusEl, `✓ Added (Old Stock): ${bc.item || bc.code} — ${fmt(bc.sell_unit)}`, 'ok');
  renderScannedItems();
}
// ─────────────────────────────────────────────────────────────────────────────

function switchBarcodeInputTab(tab) {
  currentBarcodeInputTab = tab;
  document.getElementById('sitab-enter').classList.toggle('active', tab === 'enter');
  document.getElementById('sitab-scan').classList.toggle('active', tab === 'scan');
  document.getElementById('bc-enter-panel').style.display = tab === 'enter' ? '' : 'none';
  document.getElementById('bc-scan-panel').style.display = tab === 'scan' ? '' : 'none';
  if (tab === 'scan') {
    setTimeout(() => focusScanInput(), 150);
  }
}

async function lookupAndAddBarcodeCode(code) {
  // ── SCAN TAB: smart routing ──
  const statusEl = document.getElementById('bc-scan-status');
  if (!code) return;

  setStatus(statusEl, '⏳ Looking up...', 'info');

  // ── Route: Old Stock (letters in code) ───────────────────────────────────
  if (_isOldDataCode(code)) {
    try {
      const res  = await fetch(`/api/old_data_lookup?code=${encodeURIComponent(code)}`);
      const data = await res.json();
      if (res.ok && (data.status === 'ok' || data.status === 'multiple_prices')) {
        if ((data.requires_selection || data.has_different_prices || data.has_different_sizes) && data.matches && data.matches.length > 1) {
          showOldDataDuplicatePicker(data.matches, statusEl, document.getElementById('f-bc-scan'));
          return;
        }
        _addOldDataItemToCart(data.barcode, statusEl);
      } else {
        setStatus(statusEl, '✗ ' + (data.message || 'Old Stock item not found.'), 'error');
      }
    } catch (err) {
      setStatus(statusEl, '✗ Server error. Try again.', 'error');
    }
    return;
  }

  // ── Route: Regular barcode ───────────────────────────────────────────────
  try {
    const res  = await fetch(`/api/barcode_lookup?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      if (data.has_different_prices && data.matches && data.matches.length > 1) {
        showOldDataDuplicatePicker(data.matches, statusEl, document.getElementById('f-bc-scan'));
        return;
      }
      if (data.barcode && data.barcode.is_old_data) {
        _addOldDataItemToCart(data.barcode, statusEl);
        return;
      }
      const bc = data.barcode;
      // Same exact barcode already in cart — increase qty
      const sameBarcode = scannedItems.find(x => x.code === bc.code);
      if (sameBarcode) {
        sameBarcode.qty = (sameBarcode.qty || 1) + 1;
        delete sameBarcode.lineTotalOverride;
        setStatus(statusEl, `✓ Qty updated: ${sameBarcode.item} × ${sameBarcode.qty}`, 'ok');
        renderScannedItems();
        return;
      }
      // Different barcode but same item+size — increase qty
      const existing = scannedItems.find(x => x.purchase_item_id === bc.purchase_item_id);
      if (existing) {
        existing.qty += 1;
        delete existing.lineTotalOverride;
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
        renderScannedItems();
        return;
      }
      scannedItems.push({
        code: bc.code, item: bc.item, size: bc.size, party: bc.party,
        sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
        purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code]
      });
      setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' (' + bc.size + ')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
      renderScannedItems();
    } else if (res.ok && data.status === 'multiple_prices') {
      showOldDataDuplicatePicker(data.matches || data.all_matches, statusEl, document.getElementById('f-bc-scan'));
      return;
    } else if (data.status === 'already_sold' || data.status === 'deleted') {
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
  enter: { inputId: 'f-bc-enter', listId: 'bc-enter-suggestions', status: 'available', allowBarcode: false },
  product: { inputId: 'f-product-search', listId: 'bc-product-suggestions', status: 'available', allowBarcode: false },
  old: { inputId: 'f-bc-old', listId: 'bc-old-suggestions', status: 'sold', allowBarcode: true },
  new: { inputId: 'f-bc-new', listId: 'bc-new-suggestions', status: 'available', allowBarcode: true }
};

let productSearchTimer = null;
const productSearchMatches = { enter: [], product: [], old: [], new: [] };
const selectedProductMatch = { enter: null, product: null, old: null, new: null };

// Called on every keystroke in a barcode/product-name input.
function onProductSearchInput(key, value) {
  selectedProductMatch[key] = null;
  clearTimeout(productSearchTimer);
  const statusIds = { enter: 'bc-enter-status', product: 'bc-product-status', old: 'bc-old-status', new: 'bc-new-status' };
  const statusEl = document.getElementById(statusIds[key] || (key + '-status'));
  if (statusEl) statusEl.textContent = '';

  const query = (value || '').trim();
  if (query.length < 2) {
    clearProductSuggestions(key);
    return;
  }
  productSearchTimer = setTimeout(() => fetchProductSuggestions(key, query), 250);
}

async function fetchProductSuggestions(key, query) {
  const cfg = PRODUCT_SEARCH_CONFIG[key];
  if (!cfg) return [];
  try {
    const allowBcParam = cfg.allowBarcode === false ? '&allow_barcode=0' : '';
    const res = await fetch(`/api/product_search?query=${encodeURIComponent(query)}&status=${cfg.status}${allowBcParam}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      const matches = data.matches || [];
      renderProductSuggestions(key, matches);
      return matches;
    }
  } catch (err) {
    // Search suggestions failing silently is fine — exact barcode Add still works.
  }
  return [];
}

function renderProductSuggestions(key, matches) {
  productSearchMatches[key] = matches;
  const cfg = PRODUCT_SEARCH_CONFIG[key];
  if (!cfg) return;
  const listEl = document.getElementById(cfg.listId);
  if (!listEl) return;

  if (!matches.length) {
    listEl.style.display = '';
    listEl.innerHTML = '<div class="product-suggest-empty">Not Found</div>';
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
    input.focus();
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
  if (cfg) {
    const listEl = document.getElementById(cfg.listId);
    if (listEl) { listEl.style.display = 'none'; listEl.innerHTML = ''; }
  }
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
  // ── ENTER TAB: smart routing ──
  const input    = document.getElementById(inputId);
  const statusId = inputId === 'f-bc-enter' ? 'bc-enter-status' : 'bc-scan-status';
  const statusEl = document.getElementById(statusId);

  const code = (input ? input.value.trim() : '');
  if (!code) return;

  setStatus(statusEl, '⏳ Looking up...', 'info');

  // ── Route: Old Stock (letters in code) ───────────────────────────────────
  if (_isOldDataCode(code)) {
    try {
      const res  = await fetch(`/api/old_data_lookup?code=${encodeURIComponent(code)}`);
      const data = await res.json();
      if (res.ok && (data.status === 'ok' || data.status === 'multiple_prices')) {
        if ((data.requires_selection || data.has_different_prices || data.has_different_sizes) && data.matches && data.matches.length > 1) {
          showOldDataDuplicatePicker(data.matches, statusEl, input);
          return;
        }
        _addOldDataItemToCart(data.barcode, statusEl);
      } else {
        setStatus(statusEl, '✗ ' + (data.message || 'Old Stock item not found.'), 'error');
      }
    } catch (err) {
      setStatus(statusEl, '✗ Server error. Try again.', 'error');
    }
    if (input) { input.value = ''; input.focus(); }
    return;
  }

  // ── Route: Regular barcode ───────────────────────────────────────────────
  try {
    const res  = await fetch(`/api/barcode_lookup?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      if (data.has_different_prices && data.matches && data.matches.length > 1) {
        showOldDataDuplicatePicker(data.matches, statusEl, input);
        return;
      }
      if (data.barcode && data.barcode.is_old_data) {
        _addOldDataItemToCart(data.barcode, statusEl);
        if (input) { input.value = ''; input.focus(); }
        return;
      }
      const bc = data.barcode;
      // Same exact barcode already in cart — increase qty
      const sameBarcode = scannedItems.find(x => x.code === bc.code);
      if (sameBarcode) {
        sameBarcode.qty = (sameBarcode.qty || 1) + 1;
        delete sameBarcode.lineTotalOverride;
        setStatus(statusEl, `✓ Qty updated: ${sameBarcode.item} × ${sameBarcode.qty}`, 'ok');
        renderScannedItems();
        if (input) { input.value = ''; input.focus(); }
        return;
      }
      // Different barcode but same item+size — increase qty
      const existing = scannedItems.find(x => x.purchase_item_id === bc.purchase_item_id);
      if (existing) {
        existing.qty += 1;
        delete existing.lineTotalOverride;
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
        renderScannedItems();
        if (input) { input.value = ''; input.focus(); }
        return;
      }
      scannedItems.push({
        code: bc.code, item: bc.item, size: bc.size, party: bc.party,
        sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
        purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code]
      });

      setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' (' + bc.size + ')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
      renderScannedItems();
    } else if (res.ok && data.status === 'multiple_prices') {
      showOldDataDuplicatePicker(data.matches || data.all_matches, statusEl, input);
      return;
    } else if (data.status === 'already_sold' || data.status === 'deleted') {
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
async function lookupAndAddProductSearch(key = 'product') {
  clearTimeout(productSearchTimer);
  const cfg = PRODUCT_SEARCH_CONFIG[key];
  if (!cfg) return;
  const input = document.getElementById(cfg.inputId);
  const statusIds = { product: 'bc-product-status', enter: 'bc-enter-status' };
  const statusEl = document.getElementById(statusIds[key] || (key + '-status'));
  const query = (input ? input.value : '').trim();

  if (!query) {
    setStatus(statusEl, 'Please enter a product name to search.', 'warn');
    return;
  }

  // If not yet selected and matches not loaded, fetch immediately
  if (!selectedProductMatch[key] && (!productSearchMatches[key] || !productSearchMatches[key].length)) {
    const matches = await fetchProductSuggestions(key, query);
    productSearchMatches[key] = matches || [];
  }

  if (!selectedProductMatch[key]) {
    const matches = productSearchMatches[key] || [];
    if (matches.length === 1) {
      selectedProductMatch[key] = matches[0];
    } else if (matches.length > 1) {
      setStatus(statusEl, 'Please select a product from the suggestions list.', 'warn');
      return;
    } else {
      setStatus(statusEl, '✗ Not Found', 'error');
      const listEl = document.getElementById(cfg.listId);
      if (listEl) {
        listEl.style.display = '';
        listEl.innerHTML = '<div class="product-suggest-empty">Not Found</div>';
      }
      return;
    }
  }

  await addSelectedProductToScannedItems(key, statusEl, input);
}

async function addSelectedProductToScannedItems(key, statusEl, input) {
  const match = selectedProductMatch[key];
  if (!match) return;
  setStatus(statusEl, '⏳ Looking up...', 'info');
  const existing = scannedItems.find(x => x.purchase_item_id === match.purchase_item_id);
  const usedCodes = existing ? (existing.scanned_codes || [existing.code]) : [];
  try {
    const data = await resolveSelectedProductMatch(key, usedCodes);
    if (data && data.status === 'ok') {
      const bc = data.barcode;
      if (existing) {
        existing.qty += 1;
        // Qty changed -- a manual per-item price edit from before no longer applies.
        delete existing.lineTotalOverride;
        existing.scanned_codes = existing.scanned_codes || [existing.code];
        existing.scanned_codes.push(bc.code);
        setStatus(statusEl, `✓ Qty updated: ${existing.item} × ${existing.qty}`, 'ok');
      } else {
        scannedItems.push({
          code: bc.code, item: bc.item, size: bc.size, party: bc.party,
          sell_unit: bc.sell_unit, buy_unit: bc.buy_unit, margin: bc.margin,
          purchase_item_id: bc.purchase_item_id, qty: 1, scanned_codes: [bc.code]
        });
        setStatus(statusEl, `✓ Added: ${bc.item}${bc.size ? ' (' + bc.size + ')' : ''} — ${fmt(bc.sell_unit)}`, 'ok');
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
  // Qty changed -- a manual per-item price edit from before no longer applies.
  delete scannedItems[idx].lineTotalOverride;
  if (!newQty || newQty < 1) { scannedItems[idx].qty = 1; renderScannedItems(); return; }
  scannedItems[idx].qty = newQty;
  renderScannedItems();
}

// Handles the +/- buttons next to the qty field. Both buttons open the
// same "Manage Barcodes" popup for this line -- qty is never guessed
// automatically anymore. In the popup, scanning/entering a barcode number
// selects (adds) it if it isn't already in this item's list, or removes it
// if it is -- see submitItemBarcodeModalInput(). This single modal drives
// the Sell panel's cart, the Replace/Exchange panel's Return ('old') and
// Give ('new') lists, AND the Purchase Return panel's cart ('pr'), so
// every qty +/- control across Sales and Purchase Return behaves
// identically -- source tells it which list it's operating on.
let barcodeModalSource = 'sell'; // 'sell' | 'old' | 'new' | 'pr'
let barcodeModalIdx = null;

function getBarcodeModalList(source) {
  if (source === 'old') return replaceOldItems;
  if (source === 'new') return replaceNewItems;
  if (source === 'pr') return prCart;
  return scannedItems;
}

function rerenderBarcodeModalSource(source) {
  if (source === 'old' || source === 'new') renderReplaceItems();
  else if (source === 'pr') renderPurchaseReturnCart();
  else renderScannedItems();
}

function openItemBarcodeModal(source, idx) {
  const list = getBarcodeModalList(source);
  const itm = list[idx];
  if (!itm) return;
  itm.scanned_codes = itm.scanned_codes || [itm.code];
  barcodeModalSource = source;
  barcodeModalIdx = idx;

  const titlePrefix = source === 'old' ? 'Manage Barcodes — Return: '
    : source === 'new' ? 'Manage Barcodes — Give: '
      : source === 'pr' ? 'Manage Barcodes — Purchase Return: '
        : 'Manage Barcodes — ';
  document.getElementById('item-barcode-modal-title').textContent =
    `${titlePrefix}${itm.item || ''}${itm.size ? ' (' + itm.size + ')' : ''}`;
  document.getElementById('item-barcode-modal-meta').textContent =
    `Qty: ${itm.qty || 1} · scan/enter a barcode below to select it, or scan an already-selected one again to remove it.`;
  document.getElementById('ibm-status').textContent = '';
  document.getElementById('ibm-input').value = '';

  renderItemBarcodeModalChips();

  const modal = document.getElementById('item-barcode-modal');
  modal.style.display = 'flex';
  setTimeout(() => document.getElementById('ibm-input').focus(), 100);
}

function closeItemBarcodeModal() {
  document.getElementById('item-barcode-modal').style.display = 'none';
  barcodeModalIdx = null;
}

function renderItemBarcodeModalChips() {
  const itm = getBarcodeModalList(barcodeModalSource)[barcodeModalIdx];
  const chipsEl = document.getElementById('item-barcode-modal-chips');
  if (!itm || !chipsEl) return;
  const codes = itm.scanned_codes || [itm.code];
  chipsEl.innerHTML = codes.map(code => `
    <span style="display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:6px;background:var(--color-background-tertiary);border:1px solid var(--color-border-secondary);font-family:monospace;font-size:12px;">
      ${code}
      <i class="ti ti-x" style="cursor:pointer;color:var(--color-text-danger)" onclick="removeItemBarcodeModalChip('${code}')"></i>
    </span>
  `).join('');
}

// Clicking the × on a chip removes that exact barcode directly.
function removeItemBarcodeModalChip(code) {
  const list = getBarcodeModalList(barcodeModalSource);
  const itm = list[barcodeModalIdx];
  if (!itm) return;
  itm.scanned_codes = itm.scanned_codes || [itm.code];
  if (itm.scanned_codes.length <= 1) {
    setStatus(document.getElementById('ibm-status'),
      'there must one barcode in the list— if you want to remove the item then click "×" (remove item) button.', 'warn');
    return;
  }
  itm.scanned_codes = itm.scanned_codes.filter(c => c !== code);
  itm.qty = itm.scanned_codes.length;
  // Qty changed -- a manual per-item price edit from before no longer applies.
  delete itm.lineTotalOverride;
  if (!itm.scanned_codes.includes(itm.code)) itm.code = itm.scanned_codes[0];
  renderItemBarcodeModalChips();
  rerenderBarcodeModalSource(barcodeModalSource);
}

// The single field in the popup: scanning/entering a barcode toggles it --
// adds it to this item if it's a valid, unused barcode of the same
// product batch, or removes it if it's already selected for this item.
// Which lookup endpoint validates "unused/available" depends on the list:
// the Sell cart and the Replace 'new' (Give) list both draw from
// available stock via /api/barcode_lookup; the Replace 'old' (Return)
// list draws from already-sold stock via /api/barcode_lookup_sold.
async function submitItemBarcodeModalInput() {
  const source = barcodeModalSource;
  const list = getBarcodeModalList(source);
  const itm = list[barcodeModalIdx];
  const input = document.getElementById('ibm-input');
  const statusEl = document.getElementById('ibm-status');
  if (!itm || !input) return;

  const raw = input.value.trim();
  if (!raw) return;
  const code = String(parseInt(raw, 10));
  if (code === 'NaN') {
    setStatus(statusEl, '✗ Invalid barcode.', 'error');
    return;
  }

  itm.scanned_codes = itm.scanned_codes || [itm.code];

  // Already selected for this item -- scanning it again de-selects it.
  if (itm.scanned_codes.includes(code)) {
    removeItemBarcodeModalChip(code);
    showToast(`✓ Removed: ${code}`);
    closeItemBarcodeModal();
    return;
  }

  // Not selected yet -- validate it belongs to this same item and isn't
  // already claimed by any other line in the list, then add it.
  setStatus(statusEl, '⏳ Checking...', 'info');
  const endpoint = source === 'old' ? '/api/barcode_lookup_sold' : '/api/barcode_lookup';
  try {
    const res = await fetch(`${endpoint}?code=${encodeURIComponent(code)}`);
    const data = await res.json();
    if (!res.ok || data.status !== 'ok') {
      setStatus(statusEl, '✗ ' + (data.message || 'Barcode not found.'), 'error');
      return;
    }
    const bc = data.barcode;
    if (bc.purchase_item_id !== itm.purchase_item_id) {
      setStatus(statusEl, '✗ The selected Barcode is not of this item.', 'error');
      return;
    }
    const usedElsewhere = list.some(other => (other.scanned_codes || [other.code]).includes(code));
    if (usedElsewhere) {
      setStatus(statusEl, '⚠ The barcode is already in the list.', 'warn');
      return;
    }
    itm.scanned_codes.push(code);
    itm.qty = itm.scanned_codes.length;
    // Qty changed -- a manual per-item price edit from before no longer applies.
    delete itm.lineTotalOverride;
    rerenderBarcodeModalSource(source);
    showToast(`✓ Added: ${code}`);
    closeItemBarcodeModal();
    return;
  } catch (err) {
    setStatus(statusEl, '✗ Server error. Try again.', 'error');
    return;
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
  const discSec = document.getElementById('discount-section');
  const discBreakdown = document.getElementById('discount-breakdown-section');
  const discount = parseFloat(document.getElementById('f-discount')?.value) || 0;

  if (scannedItems.length === 0) {
    if (section) section.style.display = 'none';
    if (discSec) discSec.style.display = 'none';
    if (discBreakdown) discBreakdown.style.display = 'none';
    return;
  }
  if (section) section.style.display = '';
  if (discSec) discSec.style.display = '';
  countBadge.textContent = scannedItems.length + ' item' + (scannedItems.length > 1 ? 's' : '');

  let grandSell = 0;       // actual sale total AFTER discount — used for Sale Amount sync / split-payment check
  let grandOriginal = 0;   // original total BEFORE discount — used only for the on-screen display
  let grandBuy = 0;
  listEl.innerHTML = scannedItems.map((itm, idx) => {
    const qty = itm.qty || 1;
    const originalPrice = round2(itm.sell_unit * qty);
    // Honors a manual per-item price edit from the discount breakdown list
    // (see ui/discount.js) if one was made, otherwise the plain discount%.
    const discountedPrice = getItemDiscountedTotal(itm, discount);
    grandSell += discountedPrice;
    grandOriginal += originalPrice;
    grandBuy += itm.buy_unit * qty;
    const isOverridden = itm.lineTotalOverride != null && !isNaN(itm.lineTotalOverride);
    const discBadge = isOverridden
      ? `<span class="margin-badge" style="background:var(--color-bg-accent);color:var(--color-text-success);font-size:10px">✎ edited</span>`
      : (discount > 0
        ? `<span class="margin-badge" style="background:var(--color-bg-accent);color:#ef4444;font-size:10px">${discount}%↓</span>`
        : '');
    return `<div class="scanned-item-row">
      <div class="scanned-item-info">
        <span class="scanned-item-name">${itm.item || '—'}${itm.size ? ' <span class="scanned-item-size">' + itm.size + '</span>' : ''}</span>
        <span class="scanned-item-code" style="word-break:break-word;white-space:normal">${itm.is_old_data && itm.size ? _escapeHtml(itm.size) + ' · ' : ''}${(itm.scanned_codes && itm.scanned_codes.length ? itm.scanned_codes : [itm.code]).join(', ')}</span>
      </div>
      <div class="scanned-item-qty">
        ${itm.is_old_data ? `
          <button onclick="changeOldDataQty(${idx}, -1)" style="padding:0 6px;font-size:14px;cursor:pointer" title="Decrease">−</button>
          <span style="min-width:28px;text-align:center;display:inline-block;font-weight:600">${qty}</span>
          <button onclick="changeOldDataQty(${idx}, 1)" style="padding:0 6px;font-size:14px;cursor:pointer" title="Increase">+</button>
        ` : `
          <button onclick="openItemBarcodeModal('sell', ${idx})" style="padding:0 6px;font-size:14px;cursor:pointer">−</button>
          <span style="min-width:28px;text-align:center;display:inline-block">${qty}</span>
          <button onclick="openItemBarcodeModal('sell', ${idx})" style="padding:0 6px;font-size:14px;cursor:pointer">+</button>
        `}
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
    const cashAmt = parseFloat(document.getElementById('f-cash-amount').value) || 0;
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
    <span style="margin-left:auto">Final Sale Amount: <strong style="color:var(--color-text-success)">${fmt(Math.round(grandSell))}</strong></span>
  `;

  const saleAmtEl = document.getElementById('f-sale-amount');
  if (saleAmtEl && document.activeElement !== saleAmtEl) {
    const exactTotal = window.saleExactFinalTotal;
    saleAmtEl.value = (exactTotal !== null && exactTotal !== undefined)
      ? exactTotal
      : (grandSell > 0 ? grandSell : '');
  }

  renderDiscountBreakdown();
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
    const s3 = document.getElementById('bc-product-status');
    if (s1) s1.textContent = '';
    if (s2) s2.textContent = '';
    if (s3) s3.textContent = '';
  }
}

function clearScannedItems() {
  scannedItems = [];
  renderScannedItems();
  const s1 = document.getElementById('bc-enter-status');
  const s2 = document.getElementById('bc-scan-status');
  const s3 = document.getElementById('bc-product-status');
  if (s1) s1.textContent = '';
  if (s2) s2.textContent = '';
  if (s3) s3.textContent = '';
  clearProductSuggestions('enter');
  clearProductSuggestions('product');
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

