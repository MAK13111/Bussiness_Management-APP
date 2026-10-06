const SELL_DISCOUNT_CTX = {
  items: () => scannedItems,
  exactTotalKey: 'saleExactFinalTotal',
  discountId: 'f-discount',
  saleAmountId: 'f-sale-amount',
  discountAmountId: 'f-discount-amount',
  previewId: 'discount-preview',
  presetScope: '#discount-section',
  breakdownSectionId: 'discount-breakdown-section',
  breakdownListId: 'discount-breakdown-list',
  unitFieldPrefix: 'bd-unit-',
  totalFieldPrefix: 'bd-total-',
  afterLabel: 'Final',
  rerenderList: () => renderScannedItems(),
};

const REPLACE_DISCOUNT_CTX = {
  items: () => replaceNewItems,
  exactTotalKey: 'replaceExactFinalTotal',
  discountId: 'f-replace-discount',
  saleAmountId: 'f-replace-sale-amount',
  discountAmountId: 'f-replace-discount-amount',
  previewId: 'replace-discount-preview',
  presetScope: '#replace-discount-section',
  breakdownSectionId: 'replace-discount-breakdown-section',
  breakdownListId: 'replace-discount-breakdown-list',
  unitFieldPrefix: 'rbd-unit-',
  totalFieldPrefix: 'rbd-total-',
  afterLabel: 'Give Total',
  rerenderList: () => renderReplaceItems(),
};

// Undiscounted total of all items in this context (sum of sell_unit * qty).
function computeCtxSubtotal(ctx) {
  return (ctx.items() || []).reduce((sum, itm) => sum + (itm.sell_unit || 0) * (itm.qty || 1), 0);
}

function setCtxDiscount(ctx, val) {
  const el = document.getElementById(ctx.discountId);
  if (!el) return;
  el.value = val || '';
  onCtxDiscountInput(ctx);
}

function onCtxDiscountInput(ctx) {
  // Typing the % directly means there's no separately-typed exact rupee
  // target anymore -- let the % drive the total as before.
  if (document.activeElement && document.activeElement.id === ctx.discountId) {
    window[ctx.exactTotalKey] = null;
  }
  const discount = parseFloat(document.getElementById(ctx.discountId)?.value) || 0;
  const preview = document.getElementById(ctx.previewId);
  const discAmtEl = document.getElementById(ctx.discountAmountId);
  const subtotal = computeCtxSubtotal(ctx);

  document.querySelectorAll(`${ctx.presetScope} .disc-preset:not(.disc-preset-clear)`).forEach(btn => {
    btn.classList.toggle('active', parseFloat(btn.textContent) === discount);
  });

  if (discount <= 0) {
    if (preview) preview.innerHTML = '<span style="color:var(--color-text-tertiary)">No discount applied</span>';
    if (discAmtEl && document.activeElement !== discAmtEl) discAmtEl.value = '';
    // No discount active -- any manual per-item price edits no longer apply.
    (ctx.items() || []).forEach(it => delete it.lineTotalOverride);
    ctx.rerenderList();
    renderCtxDiscountBreakdown(ctx);
    return;
  }
  if (discount >= 100) {
    if (preview) preview.innerHTML = '<span style="color:var(--color-text-danger)"><i class="ti ti-alert-circle"></i> Max 99.9% allowed</span>';
    return;
  }

  // When an exact Sale/Give Amount or Discount Amount was typed, or an
  // item's price was manually edited in the breakdown list below, use
  // that exact total directly instead of recomputing from the rounded
  // discount % -- round-tripping through the rounded % (e.g. 14.29%)
  // causes drift, like 700 * 14.29 / 100 = 100.03 instead of the exact
  // 100 the user entered.
  let saved, after;
  const exactTotal = window[ctx.exactTotalKey];
  if (exactTotal !== null && exactTotal !== undefined) {
    after = exactTotal;
    saved = round2(subtotal - after);
  } else {
    saved = round2(subtotal * discount / 100);
    after = round2(subtotal - saved);
  }

  if (discAmtEl && document.activeElement !== discAmtEl) discAmtEl.value = saved > 0 ? saved : '';

  if (preview) {
    preview.innerHTML = saved > 0
      ? `<span style="color:var(--color-text-success);font-weight:600"><i class="ti ti-rosette-discount"></i> Save ${fmt(saved)}</span>
         <span style="color:var(--color-text-tertiary);margin-left:8px">→ ${ctx.afterLabel}: <strong style="color:var(--color-text-primary)">${fmt(after)}</strong></span>`
      : `<span style="color:var(--color-text-secondary)">${discount}% discount will be applied</span>`;
  }

  ctx.rerenderList();
  renderCtxDiscountBreakdown(ctx);
}

// Raw (unrounded) discounted total for a line -- internal helper only,
// used to build the ₹10-rounded breakdown totals below. Never call this
// directly outside computeCtxBreakdownTotals(); everywhere else (item
// list, receipt, save-to-DB) must go through getCtxItemDiscountedTotal()
// so every part of the app agrees on the exact same number.
function getCtxItemRawDiscountedTotal(ctx, itm, discount) {
  if (itm.lineTotalOverride != null && !isNaN(itm.lineTotalOverride)) {
    return round2(itm.lineTotalOverride);
  }
  const qty = itm.qty || 1;

  const exactTotal = window[ctx.exactTotalKey];
  if (exactTotal !== null && exactTotal !== undefined) {
    const subtotal = computeCtxSubtotal(ctx);
    const lineSubtotal = (itm.sell_unit || 0) * qty;
    if (subtotal > 0) {
      return round2(lineSubtotal / subtotal * exactTotal);
    }
  }

  const discountedUnit = round2(itm.sell_unit * (1 - discount / 100));
  return round2(discountedUnit * qty);
}

function getCtxItemDiscountedTotal(ctx, itm, discount) {
  if (itm.lineTotalOverride != null && !isNaN(itm.lineTotalOverride)) {
    return round2(itm.lineTotalOverride);
  }
  if (!discount || discount <= 0) {
    return getCtxItemRawDiscountedTotal(ctx, itm, discount);
  }
  const items = ctx.items() || [];
  const idx = items.indexOf(itm);
  if (idx === -1) return getCtxItemRawDiscountedTotal(ctx, itm, discount);
  return computeCtxBreakdownTotals(ctx, discount)[idx];
}

// Line totals for the breakdown list, rounded to the nearest ₹10.
// Manually-edited (✎ edited) lines are kept exactly as typed and left
// out of the rounding. Every other line is rounded to the nearest ₹10,
// then whatever ₹10-rounding leftover remains is dropped entirely onto
// the LAST non-edited line -- automatically, no up/down choice needed --
// so the whole list still adds up to exactly the Final/Give Total.
function computeCtxBreakdownTotals(ctx, discount) {
  const items = ctx.items() || [];
  const exactTotal = window[ctx.exactTotalKey];
  const subtotal = computeCtxSubtotal(ctx);
  const target = (exactTotal !== null && exactTotal !== undefined)
    ? Math.min(exactTotal, subtotal)
    : round2(subtotal * (1 - discount / 100));

  const isAuto = items.map(itm => !(itm.lineTotalOverride != null && !isNaN(itm.lineTotalOverride)));
  const exact = items.map(itm => getCtxItemRawDiscountedTotal(ctx, itm, discount));
  const totals = exact.map((v, i) => {
    const maxLine = round2((items[i].sell_unit || 0) * (items[i].qty || 1));
    const val = isAuto[i] ? Math.round(v / 10) * 10 : v;
    return Math.min(val, maxLine);
  });

  const autoIdxs = items.map((_, i) => i).filter(i => isAuto[i]);
  if (autoIdxs.length > 0) {
    const fixedSum = totals.reduce((s, v, i) => (isAuto[i] ? s : s + v), 0);
    const autoRoundedSum = totals.reduce((s, v, i) => (isAuto[i] ? s + v : s), 0);
    const diff = round2(target - fixedSum - autoRoundedSum);
    const lastAuto = autoIdxs[autoIdxs.length - 1];
    const maxLastLine = round2((items[lastAuto].sell_unit || 0) * (items[lastAuto].qty || 1));
    totals[lastAuto] = Math.min(round2(totals[lastAuto] + diff), maxLastLine);
  }
  return totals;
}

// ─── PER-ITEM PRICE-AFTER-DISCOUNT BREAKDOWN (editable) ──────────────────
// Opens below the discount section once a discount is applied, showing
// what each line actually sells for. If an item's quantity is more than
// 1, both its per-unit price and line total are shown as separate,
// independently editable fields.
function renderCtxDiscountBreakdown(ctx) {
  const section = document.getElementById(ctx.breakdownSectionId);
  const listEl = document.getElementById(ctx.breakdownListId);
  if (!section || !listEl) return;

  const discount = parseFloat(document.getElementById(ctx.discountId)?.value) || 0;
  const items = ctx.items() || [];

  if (discount <= 0 || items.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';

  // Rewriting innerHTML below destroys and recreates every input node --
  // including the one the user is currently typing in -- which drops
  // focus after every single keystroke. Remember which field (and cursor
  // position, where supported) was focused so it can be restored after
  // the re-render instead of leaving the user stuck after one character.
  const activeEl = document.activeElement;
  const activeId = activeEl && listEl.contains(activeEl) ? activeEl.id : null;
  let activeSelStart = null, activeSelEnd = null;
  if (activeId) {
    try {
      activeSelStart = activeEl.selectionStart;
      activeSelEnd = activeEl.selectionEnd;
    } catch (e) {
      // input[type=number] doesn't support selection in some browsers --
      // refocusing without restoring the cursor position is still a fix.
    }
  }

  const breakdownTotals = computeCtxBreakdownTotals(ctx, discount);

  listEl.innerHTML = items.map((itm, idx) => {
    const qty = itm.qty || 1;
    const maxUnit = itm.sell_unit || 0;
    const maxTotal = round2(maxUnit * qty);
    const lineTotal = Math.min(breakdownTotals[idx], maxTotal);
    const unitPrice = Math.min(round2(lineTotal / qty), maxUnit);
    const isOverridden = itm.lineTotalOverride != null && !isNaN(itm.lineTotalOverride);
    const editedBadge = isOverridden
      ? `<span class="margin-badge" style="background:var(--color-bg-accent);color:var(--color-text-success);font-size:10px">✎ edited</span>`
      : '';

    const unitFieldId = `${ctx.unitFieldPrefix}${idx}`;
    const totalFieldId = `${ctx.totalFieldPrefix}${idx}`;
    const unitFocused = document.activeElement && document.activeElement.id === unitFieldId;
    const totalFocused = document.activeElement && document.activeElement.id === totalFieldId;

    const fieldsHtml = qty > 1
      ? `<div class="discount-breakdown-field">
           <label>Unit Price (Max ${fmt(maxUnit)})</label>
           <input id="${unitFieldId}" type="text" inputmode="decimal" pattern="[0-9]*\\.?[0-9]*" max="${maxUnit}"
             value="${unitFocused ? document.getElementById(unitFieldId).value : unitPrice}"
             oninput="onCtxBreakdownFieldInputByName('${ctx === SELL_DISCOUNT_CTX ? 'sell' : 'replace'}', ${idx}, 'unit', this.value)"/>
         </div>
         <div class="discount-breakdown-field">
           <label>Total (Max ${fmt(maxTotal)})</label>
           <input id="${totalFieldId}" type="text" inputmode="decimal" pattern="[0-9]*\\.?[0-9]*" max="${maxTotal}"
             value="${totalFocused ? document.getElementById(totalFieldId).value : lineTotal}"
             oninput="onCtxBreakdownFieldInputByName('${ctx === SELL_DISCOUNT_CTX ? 'sell' : 'replace'}', ${idx}, 'total', this.value)"/>
         </div>`
      : `<div class="discount-breakdown-field">
           <label>Price (Max ${fmt(maxTotal)})</label>
           <input id="${totalFieldId}" type="text" inputmode="decimal" pattern="[0-9]*\\.?[0-9]*" max="${maxTotal}"
             value="${totalFocused ? document.getElementById(totalFieldId).value : lineTotal}"
             oninput="onCtxBreakdownFieldInputByName('${ctx === SELL_DISCOUNT_CTX ? 'sell' : 'replace'}', ${idx}, 'total', this.value)"/>
         </div>`;

    return `<div class="discount-breakdown-row">
      <div class="discount-breakdown-info">
        <span class="scanned-item-name">${itm.item || '—'}${itm.size ? ' <span class="scanned-item-size">'+itm.size+'</span>' : ''}</span>
        <span class="scanned-item-size">Qty: ${qty}</span>
        ${editedBadge}
      </div>
      <div class="discount-breakdown-fields">${fieldsHtml}</div>
    </div>`;
  }).join('');

  if (activeId) {
    const restored = document.getElementById(activeId);
    if (restored) {
      restored.focus();
      if (activeSelStart != null && activeSelEnd != null) {
        try {
          restored.setSelectionRange(activeSelStart, activeSelEnd);
        } catch (e) {
          // Same input[type=number] limitation as above -- focus is
          // already restored, so typing continues to work regardless.
        }
      }
    }
  }
}

function onCtxBreakdownFieldInput(ctx, idx, field, value) {
  const itm = (ctx.items() || [])[idx];
  if (!itm) return;
  const qty = itm.qty || 1;
  let num = parseFloat(value);

  // Cap: a sale/give-time price/total can never exceed the item's normal
  // (undiscounted) real sale price -- entering more than that would mean
  // charging above the listed price under the "discount" workflow.
  const maxUnit = itm.sell_unit || 0;
  const maxTotal = round2(maxUnit * qty);
  const limit = field === 'unit' ? maxUnit : maxTotal;

  if (!isNaN(num) && num >= 0) {
    if (num > limit) {
      num = limit;
      showToast(`Price can't exceed the real price (${fmt(limit)})`, '#dc2626');
      // Reflect the clamped value back into the field the user is typing in.
      const fieldId = field === 'unit' ? `${ctx.unitFieldPrefix}${idx}` : `${ctx.totalFieldPrefix}${idx}`;
      const fieldEl = document.getElementById(fieldId);
      if (fieldEl) fieldEl.value = num;
    }
  }

  if (isNaN(num) || num < 0) {
    // Cleared / invalid input -- drop the override and fall back to the
    // normal discount% price for this line.
    delete itm.lineTotalOverride;
  } else if (field === 'unit') {
    itm.lineTotalOverride = round2(num * qty);
  } else {
    itm.lineTotalOverride = round2(num);
  }

  const discount = parseFloat(document.getElementById(ctx.discountId)?.value) || 0;
  const items = ctx.items() || [];
  const hasAbsorber = items.some((it, i) =>
    i !== idx && !(it.lineTotalOverride != null && !isNaN(it.lineTotalOverride))
  );

  if (!hasAbsorber) {
    // No other item in the list can absorb this edit -- let it change
    // the overall Sale/Give Amount instead, same as before.
    const grandTotal = items.reduce((sum, it) => sum + getCtxItemDiscountedTotal(ctx, it, discount), 0);
    window[ctx.exactTotalKey] = round2(grandTotal);

    // The Sale/Give Amount just moved -- keep the Discount % and Discount
    // Amount fields in sync with it instead of leaving them showing the
    // old, now-stale numbers.
    const subtotal = computeCtxSubtotal(ctx);
    if (subtotal > 0) {
      let newDiscountPct = Math.round((1 - window[ctx.exactTotalKey] / subtotal) * 100 * 100) / 100;
      newDiscountPct = Math.min(Math.max(newDiscountPct, 0), 99.9);
      document.getElementById(ctx.discountId).value = newDiscountPct;
    }
    // onCtxDiscountInput() recomputes the Discount Amount field and
    // preview from window[ctx.exactTotalKey], and re-renders the item
    // list and this breakdown list itself -- no need to call separately.
    onCtxDiscountInput(ctx);
    return;
  }
  // else: leave window[ctx.exactTotalKey] untouched -- the Sale/Give
  // Amount stays exactly where it was, and computeCtxBreakdownTotals()
  // shifts the difference onto the last non-edited item in the list.

  ctx.rerenderList();
  renderCtxDiscountBreakdown(ctx);
}

// User typed a Sale/Give Amount directly — back-calculate the equivalent
// discount % so both fields (and the item list) stay consistent.
function onCtxSaleAmountInput(ctx) {
  const saleAmtEl = document.getElementById(ctx.saleAmountId);
  if (!saleAmtEl) return;
  let saleAmt = parseFloat(saleAmtEl.value);
  const subtotal = computeCtxSubtotal(ctx);

  if (isNaN(saleAmt) || subtotal <= 0) return;

  if (saleAmt > subtotal) {
    saleAmt = subtotal;
    saleAmtEl.value = subtotal;
    showToast(`Sale Amount can't exceed total real price (${fmt(subtotal)})`, '#dc2626');
  }

  let discount = Math.round((1 - (saleAmt / subtotal)) * 100 * 100) / 100;
  if (discount < 0) discount = 0;
  if (discount > 99.9) discount = 99.9;

  document.getElementById(ctx.discountId).value = discount;
  window[ctx.exactTotalKey] = round2(saleAmt);
  onCtxDiscountInput(ctx);
}

// User typed a Discount Amount directly — back-calculate the equivalent
// discount % so all fields (and the item list) stay consistent.
function onCtxDiscountAmountInput(ctx) {
  const discAmtEl = document.getElementById(ctx.discountAmountId);
  if (!discAmtEl) return;
  const discAmt = parseFloat(discAmtEl.value);
  const subtotal = computeCtxSubtotal(ctx);

  if (isNaN(discAmt) || subtotal <= 0) return;

  let discount = Math.round((discAmt / subtotal) * 100 * 100) / 100;
  if (discount < 0) discount = 0;
  if (discount > 99.9) discount = 99.9;

  document.getElementById(ctx.discountId).value = discount;
  window[ctx.exactTotalKey] = round2(subtotal - discAmt);
  onCtxDiscountInput(ctx);
}

// The breakdown list's inline oninput= attributes can't close over the
// ctx object directly (it's rebuilt as an HTML string), so they look it
// up by a plain 'sell' | 'replace' name instead.
function onCtxBreakdownFieldInputByName(name, idx, field, value) {
  onCtxBreakdownFieldInput(name === 'replace' ? REPLACE_DISCOUNT_CTX : SELL_DISCOUNT_CTX, idx, field, value);
}

// ─── SELL TAB — thin wrappers around the shared engine above ─────────────
function setDiscount(val) { setCtxDiscount(SELL_DISCOUNT_CTX, val); }
function onDiscountInput() { onCtxDiscountInput(SELL_DISCOUNT_CTX); }
function computeSubtotal() { return computeCtxSubtotal(SELL_DISCOUNT_CTX); }
function getItemDiscountedTotal(itm, discount) { return getCtxItemDiscountedTotal(SELL_DISCOUNT_CTX, itm, discount); }
function computeBreakdownTotals(discount) { return computeCtxBreakdownTotals(SELL_DISCOUNT_CTX, discount); }
function renderDiscountBreakdown() { renderCtxDiscountBreakdown(SELL_DISCOUNT_CTX); }
function onBreakdownFieldInput(idx, field, value) { onCtxBreakdownFieldInput(SELL_DISCOUNT_CTX, idx, field, value); }
function onSaleAmountInput() { onCtxSaleAmountInput(SELL_DISCOUNT_CTX); }
function onDiscountAmountInput() { onCtxDiscountAmountInput(SELL_DISCOUNT_CTX); }

// ─── REPLACE / EXCHANGE TAB — thin wrappers around the SAME shared engine,
// scoped to the "Give Item" (new) side via REPLACE_DISCOUNT_CTX ─────────
function setReplaceDiscount(val) { setCtxDiscount(REPLACE_DISCOUNT_CTX, val); }
function onReplaceDiscountInput() { onCtxDiscountInput(REPLACE_DISCOUNT_CTX); }
function computeReplaceSubtotal() { return computeCtxSubtotal(REPLACE_DISCOUNT_CTX); }
function getReplaceItemDiscountedTotal(itm, discount) { return getCtxItemDiscountedTotal(REPLACE_DISCOUNT_CTX, itm, discount); }
function computeReplaceBreakdownTotals(discount) { return computeCtxBreakdownTotals(REPLACE_DISCOUNT_CTX, discount); }
function renderReplaceDiscountBreakdown() { renderCtxDiscountBreakdown(REPLACE_DISCOUNT_CTX); }
function onReplaceBreakdownFieldInput(idx, field, value) { onCtxBreakdownFieldInput(REPLACE_DISCOUNT_CTX, idx, field, value); }
function onReplaceSaleAmountInput() { onCtxSaleAmountInput(REPLACE_DISCOUNT_CTX); }
function onReplaceDiscountAmountInput() { onCtxDiscountAmountInput(REPLACE_DISCOUNT_CTX); }

function toggleSplitPayment() {
  const mode = document.getElementById('f-payment-mode').value;
  const splitFields = document.getElementById('split-payment-fields');
  const advanceFields = document.getElementById('credit-advance-fields');
  splitFields.style.display = (mode === 'Split') ? '' : 'none';
  if (mode !== 'Split') {
    document.getElementById('f-cash-amount').value = '';
    document.getElementById('f-online-amount').value = '';
    const indicator = document.getElementById('split-balance-indicator');
    if (indicator) indicator.textContent = '';
  }
  if (advanceFields) advanceFields.style.display = (mode === 'Partial') ? '' : 'none';
  if (mode !== 'Partial') {
    const advInput = document.getElementById('f-credit-advance-amount');
    if (advInput) advInput.value = '';
  }
  const modeLabel = document.getElementById('sidebar-mode-label');
  if (modeLabel) modeLabel.textContent = (mode === 'Partial') ? 'Credit mode' : 'Cash mode';
  renderScannedItems();
}