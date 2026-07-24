// =========================================================================
// ui/discount.js
// Discount input handling and the split cash/online payment toggle,
// used on the sale entry forms.
// =========================================================================

function setDiscount(val) {
  document.getElementById('f-discount').value = val || '';
  onDiscountInput();
}

// Undiscounted total of all scanned items (sum of sell_unit * qty)
function computeSubtotal() {
  return (scannedItems || []).reduce((sum, itm) => sum + (itm.sell_unit || 0) * (itm.qty || 1), 0);
}

function onDiscountInput() {
  const discount = parseFloat(document.getElementById('f-discount').value) || 0;
  const preview  = document.getElementById('discount-preview');
  const discAmtEl = document.getElementById('f-discount-amount');
  const subtotal = computeSubtotal();

  document.querySelectorAll('.disc-preset:not(.disc-preset-clear)').forEach(btn => {
    btn.classList.toggle('active', parseFloat(btn.textContent) === discount);
  });

  if (discount <= 0) {
    preview.innerHTML = '<span style="color:var(--color-text-tertiary)">No discount applied</span>';
    if (discAmtEl && document.activeElement !== discAmtEl) discAmtEl.value = '';
    renderScannedItems();
    return;
  }
  if (discount >= 100) {
    preview.innerHTML = '<span style="color:var(--color-text-danger)"><i class="ti ti-alert-circle"></i> Max 99.9% allowed</span>';
    return;
  }

  const saved = round2(subtotal * discount / 100);
  const after = round2(subtotal - saved);

  if (discAmtEl && document.activeElement !== discAmtEl) discAmtEl.value = saved > 0 ? saved : '';

  preview.innerHTML = saved > 0
    ? `<span style="color:var(--color-text-success);font-weight:600"><i class="ti ti-rosette-discount"></i> Save ${fmt(saved)}</span>
       <span style="color:var(--color-text-tertiary);margin-left:8px">→ Final: <strong style="color:var(--color-text-primary)">${fmt(after)}</strong></span>`
    : `<span style="color:var(--color-text-secondary)">${discount}% discount will be applied</span>`;

  renderScannedItems();
}

// User typed a Sale Amount directly — back-calculate the equivalent
// discount % so both fields (and the item list) stay consistent.
function onSaleAmountInput() {
  const saleAmtEl = document.getElementById('f-sale-amount');
  if (!saleAmtEl) return;
  const saleAmt = parseFloat(saleAmtEl.value);
  const subtotal = computeSubtotal();

  if (isNaN(saleAmt) || subtotal <= 0) return;

  // Rounding to only 2 decimals here would re-derive a slightly different
  // rupee amount when converted back (e.g. typing ₹250 on a ₹280 bill →
  // 10.71% → ₹250.01 instead of exactly ₹250). 4 decimals keeps the
  // round-trip accurate to the rupee for realistic bill amounts.
  let discount = Math.round((1 - (saleAmt / subtotal)) * 100 * 10000) / 10000;
  if (discount < 0) discount = 0;
  if (discount > 99.9) discount = 99.9;

  document.getElementById('f-discount').value = discount;
  onDiscountInput();
}

// User typed a Discount Amount directly — back-calculate the equivalent
// discount % so all fields (and the item list) stay consistent.
function onDiscountAmountInput() {
  const discAmtEl = document.getElementById('f-discount-amount');
  if (!discAmtEl) return;
  const discAmt = parseFloat(discAmtEl.value);
  const subtotal = computeSubtotal();

  if (isNaN(discAmt) || subtotal <= 0) return;

  let discount = Math.round((discAmt / subtotal) * 100 * 10000) / 10000;
  if (discount < 0) discount = 0;
  if (discount > 99.9) discount = 99.9;

  document.getElementById('f-discount').value = discount;
  onDiscountInput();
}

function toggleSplitPayment() {
  const mode = document.getElementById('f-payment-mode').value;
  const splitFields = document.getElementById('split-payment-fields');
  splitFields.style.display = (mode === 'Split') ? '' : 'none';
  if (mode !== 'Split') {
    document.getElementById('f-cash-amount').value = '';
    document.getElementById('f-online-amount').value = '';
    const indicator = document.getElementById('split-balance-indicator');
    if (indicator) indicator.textContent = '';
  }
  renderScannedItems();
}

// ─── REPLACE / EXCHANGE DISCOUNT (applies to the "Give Item" side only) ───

function setReplaceDiscount(val) {
  const el = document.getElementById('f-replace-discount');
  if (!el) return;
  el.value = val || '';
  onReplaceDiscountInput();
}

function onReplaceDiscountInput() {
  const discount = parseFloat(document.getElementById('f-replace-discount')?.value) || 0;
  document.querySelectorAll('#replace-discount-section .disc-preset:not(.disc-preset-clear)').forEach(btn => {
    btn.classList.toggle('active', parseFloat(btn.textContent) === discount);
  });
  renderReplaceItems();
}