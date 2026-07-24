// =========================================================================
// modules/purchases/entry.js
// Purchase bill entry form: adding/removing item rows, recalculating
// row & grand totals (including GST), auto-filling the bill number,
// and saving a new purchase entry.
// =========================================================================

async function addEntry() {
    const header = {
        party: document.getElementById('f-party').value.trim(),
        seller_no: document.getElementById('f-seller-no').value.trim(),
        seller_address: document.getElementById('f-seller-address').value.trim(),
        gst_no: document.getElementById('f-gst-no').value.trim(),
        invoice_no: document.getElementById('f-invoice-no').value.trim(),
        date: document.getElementById('f-purchase-date').value || todayLocalDate(),
        department: document.getElementById('f-department')?.value || '',
        cgst: parseFloat(document.getElementById('g-cgst').value) || 0,
        sgst: parseFloat(document.getElementById('g-sgst').value) || 0,
        igst: parseFloat(document.getElementById('g-igst').value) || 0,
        discount: parseFloat(document.getElementById('f-purchase-discount').value) || 0
    };
    
    const items = [];
    document.querySelectorAll("#items-container .item-row").forEach(row => {
        const id = row.id.replace('item-row-', '');
        const item = document.getElementById(`ir-item-${id}`).value.trim();
        const buy = parseFloat(document.getElementById(`ir-buy-${id}`).value) || 0;
        const margin = parseFloat(document.getElementById(`ir-margin-${id}`).value) || 0;
        const sellPrice = parseFloat(document.getElementById(`ir-sell-${id}`).value) || 0;
        const sizes = itemSizeData[id] || [];
        sizes.forEach(sizeEntry => {
            items.push({
                item: item,
                size: sizeEntry.size,
                qty: parseFloat(sizeEntry.qty) || 0,
                buy: buy,
                margin: margin,
                sell_price: sellPrice,
                cgst: header.cgst,
                sgst: header.sgst,
                igst: header.igst,
                department: sizeEntry.dept || header.department
            });
        });
    });
    
    if (items.length === 0) {
        showToast('Add at least one item', '#ef4444');
        return;
    }
    if (!header.party) {
        showToast('Party name required', '#ef4444');
        return;
    }

    try {
        // Use the current purchase mode from the global variable
        const res = await fetch('/api/purchase_bill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ header, items, mode: purchaseMode })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Purchase saved (${items.length} items)`);
            // Clear form
            document.getElementById('f-party').value = '';
            document.getElementById('f-seller-no').value = '';
            document.getElementById('f-seller-address').value = '';
            document.getElementById('f-gst-no').value = '';
            document.getElementById('f-invoice-no').value = '';
            document.getElementById('f-purchase-date').value = todayLocalDate();
            document.getElementById('f-purchase-discount').value = '';
            document.getElementById('items-container').innerHTML = '';
            itemRowCount = 0;
            Object.keys(itemSizeData).forEach(k => delete itemSizeData[k]);
            addItemRow();
            recalcGrand();

            // Show barcodes of this purchase right in the panel
            if (data.purchase_id) showPurchaseSavedBarcodes(data.purchase_id);
            // Parties tab ko bhi turant refresh karo (naya/auto-created party turant dikhe)
            loadParties();
            
            // If credit purchase, refresh borrow list and dashboard
            if (purchaseMode === 'credit') {
                loadPurchaseBorrow();
                loadDashboard();
            }
            
            // Refresh reports ONLY if the Analyze panel is actually visible,
            // and only the cheap SQL-aggregate stats (loadPurchaseStats) --
            // not the old loadEntries()+renderAnalyzePurchase(), which
            // fetched all 275k+ purchase rows AND re-filtered/re-sorted them
            // in JS just to update a hidden, unused table. If Sold Items
            // happens to be the open inner tab, refresh that too since it's
            // the one Analyze view that actually needs full row data.
            if (document.getElementById('analyze-panel')?.style?.display !== 'none') {
                loadPurchaseStats();
                if (currentAnalyzeTab === 'sold') loadSoldEntries().then(renderAnalyzeSold);
            }
        } else {
            showToast(data.msg || 'Error saving purchase', '#ef4444');
        }
    } catch (e) {
        console.error('Purchase error:', e);
        showToast('Server error: ' + e.message, '#ef4444');
    }
}

function addItemRow(prefill = {}) {
  itemRowCount++;
  const idx = itemRowCount;
  itemSizeData[idx] = prefill.sizes || [];
  const container = document.getElementById('items-container');
  const div = document.createElement('div');
  div.className = 'item-row';
  div.id = `item-row-${idx}`;
  div.innerHTML = `
    <div class="item-row-header">
      <span class="item-row-num">ITEM #${idx}</span>
      <button class="item-row-del" onclick="removeItemRow(${idx})" title="Remove item"><i class="ti ti-trash"></i></button>
    </div>
    <div class="fields" style="margin-bottom:0">
      <div class="field"><label>Item name</label><input id="ir-item-${idx}" type="text" placeholder="e.g. Cotton fabric" value="${prefill.item||''}"/></div>
      <div class="field">
        <label>Purchase price / unit (₹)</label>
        <input id="ir-buy-${idx}" type="number" placeholder="0.00" min="0" step="0.01" value="${prefill.buy||''}" oninput="recalcRow(${idx})"/>
        <span id="ir-effbuy-${idx}" style="display:none;font-size:11px;color:var(--color-text-tertiary);margin-top:2px"></span>
      </div>
      <div class="field"><label>Margin (%)</label><input id="ir-margin-${idx}" type="number" placeholder="e.g. 20" min="0" step="0.1" value="${prefill.margin||''}" oninput="recalcRow(${idx})"/></div>
      <div class="field"><label>Sell price / unit (₹)</label><input id="ir-sell-${idx}" type="number" placeholder="0.00" min="0" step="0.01" value="" oninput="recalcFromSell(${idx})"/></div>
      <div class="field" style="display:flex;flex-direction:column;justify-content:flex-end">
        <label>Sizes</label>
        <button class="size-modal-btn" id="ir-size-btn-${idx}" onclick="openSizeModal(${idx})" type="button">
          <i class="ti ti-ruler"></i>
          <span id="ir-size-label-${idx}">Add Sizes</span>
        </button>
      </div>
    </div>
    <div class="item-calcs" id="ir-calcs-${idx}">
      <span class="item-calc-chip">Buy total: <span id="ir-c-buytotal-${idx}">₹0.00</span></span>
      <span class="sep">·</span>
      <span class="item-calc-chip">GST total: <span id="ir-c-gsttotal-${idx}">₹0.00</span></span>
      <span class="sep">·</span>
      <span class="item-calc-chip">Sell total: <span id="ir-c-selltotal-${idx}">₹0.00</span></span>
      <span class="sep">·</span>
      <span class="item-calc-chip profit-chip">Profit: <span id="ir-c-profit-${idx}">₹0.00</span></span>
    </div>
  `;
  container.appendChild(div);
  updateDeleteBtns();
  updateSizeLabel(idx);
}

function removeItemRow(idx) {
  const el = document.getElementById(`item-row-${idx}`);
  if (el) el.remove();
  delete itemSizeData[idx];
  updateDeleteBtns();
  recalcGrand();
}

function updateDeleteBtns() {
  const rows = document.querySelectorAll("#items-container .item-row");
  rows.forEach(r => {
    const btn = r.querySelector('.item-row-del');
    if (btn) btn.style.display = rows.length > 1 ? '' : 'none';
  });
  rows.forEach((r, i) => {
    const numEl = r.querySelector('.item-row-num');
    if (numEl) numEl.textContent = `ITEM #${i + 1}`;
  });
}

function recalcRow(idx) {
  const sizes  = itemSizeData[idx] || [];
  const qty    = sizes.reduce((sum, s) => sum + (parseFloat(s.qty) || 0), 0);
  const buy    = parseFloat(document.getElementById(`ir-buy-${idx}`)?.value)    || 0;
  const margin = parseFloat(document.getElementById(`ir-margin-${idx}`)?.value) || 0;
  const { cgst, sgst, igst } = getCommonGST();
  const discount = getPurchaseDiscount();

  // Sell price is always based on the price you entered (before discount) —
  // a supplier discount never reduces your selling price or margin.
  const sellUnit  = roundToNearest5(buy * (1 + margin / 100));
  const sellTotal = qty * sellUnit;

  // Actual cost after the supplier discount — this drives Buy Total, GST,
  // profit, and the amount payable to the party.
  const effectiveBuy = buy * (1 - discount / 100);
  const buyTotal = qty * effectiveBuy;
  const profit   = sellTotal - buyTotal;
  const gstTotal = buyTotal * (1 + (cgst + sgst + igst) / 100);

  // Margin se Sell/unit field ko auto-fill karo
  const sellInput = document.getElementById(`ir-sell-${idx}`);
  if (sellInput) sellInput.value = sellUnit ? sellUnit.toFixed(2) : '';

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = fmt(val); };
  set(`ir-c-buytotal-${idx}`, buyTotal);
  set(`ir-c-gsttotal-${idx}`, gstTotal);
  set(`ir-c-selltotal-${idx}`, sellTotal);
  set(`ir-c-profit-${idx}`, profit);
  updateEffectiveBuyHint(idx, buy, discount, effectiveBuy);
  recalcGrand();
}

function recalcFromSell(idx) {
  const sizes  = itemSizeData[idx] || [];
  const qty    = sizes.reduce((sum, s) => sum + (parseFloat(s.qty) || 0), 0);
  const buy    = parseFloat(document.getElementById(`ir-buy-${idx}`)?.value)  || 0;
  const sell   = parseFloat(document.getElementById(`ir-sell-${idx}`)?.value) || 0;
  const { cgst, sgst, igst } = getCommonGST();
  const discount = getPurchaseDiscount();

  const margin = buy > 0 ? ((sell / buy) - 1) * 100 : 0;
  const marginInput = document.getElementById(`ir-margin-${idx}`);
  if (marginInput) marginInput.value = margin ? margin.toFixed(2) : '0';

  const effectiveBuy = buy * (1 - discount / 100);
  const buyTotal  = qty * effectiveBuy;
  const sellTotal = qty * sell;
  const profit    = sellTotal - buyTotal;
  const gstTotal  = buyTotal * (1 + (cgst + sgst + igst) / 100);

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = fmt(val); };
  set(`ir-c-buytotal-${idx}`, buyTotal);
  set(`ir-c-gsttotal-${idx}`, gstTotal);
  set(`ir-c-selltotal-${idx}`, sellTotal);
  set(`ir-c-profit-${idx}`, profit);
  updateEffectiveBuyHint(idx, buy, discount, effectiveBuy);
  recalcGrand();
}

function recalcGrand() {
  let totalBuy = 0, totalGst = 0, totalSell = 0, totalProfit = 0;
  const { cgst, sgst, igst } = getCommonGST();
  const discount = getPurchaseDiscount();
  document.querySelectorAll("#items-container .item-row").forEach(row => {
    const id = row.id.replace('item-row-', '');
    const sizes  = itemSizeData[id] || [];
    const qty    = sizes.reduce((sum, s) => sum + (parseFloat(s.qty) || 0), 0);
    const buy      = parseFloat(document.getElementById(`ir-buy-${id}`)?.value)  || 0;
    const sellUnit = parseFloat(document.getElementById(`ir-sell-${id}`)?.value) || 0;
    const effectiveBuy = buy * (1 - discount / 100);
    const buyTotal  = qty * effectiveBuy;
    const sellTotal = qty * sellUnit;
    totalBuy    += buyTotal;
    totalGst    += buyTotal * (1 + (cgst + sgst + igst) / 100);
    totalSell   += sellTotal;
    totalProfit += sellTotal - buyTotal;
  });
  document.getElementById('c-buytotal').textContent  = fmt(totalBuy);
  document.getElementById('c-gsttotal').textContent  = fmt(totalGst);
  document.getElementById('c-selltotal').textContent = fmt(totalSell);
  document.getElementById('c-profit').textContent    = fmt(totalProfit);
}

function recalcGSTAll() {
  const { total } = getCommonGST();
  const rateEl = document.getElementById('g-total-rate');
  if (rateEl) rateEl.textContent = total + '%';
  document.querySelectorAll("#items-container .item-row").forEach(row => {
    const id = row.id.replace('item-row-', '');
    recalcRow(id);
  });
}

function getCommonGST() {
  const cgst = parseFloat(document.getElementById('g-cgst')?.value) || 0;
  const sgst = parseFloat(document.getElementById('g-sgst')?.value) || 0;
  const igst = parseFloat(document.getElementById('g-igst')?.value) || 0;
  return { cgst, sgst, igst, total: cgst + sgst + igst };
}

// Supplier discount (%) — reduces the actual purchase cost only.
// It never changes the sell price, which stays based on the price you
// entered per item plus margin.
function getPurchaseDiscount() {
  return parseFloat(document.getElementById('f-purchase-discount')?.value) || 0;
}

// Shows the discounted per-unit purchase price right under the
// "Purchase price / unit" field, so the effect of the supplier discount
// is visible immediately — same idea as how margin auto-updates the
// sell price field.
function updateEffectiveBuyHint(idx, buy, discount, effectiveBuy) {
  const hint = document.getElementById(`ir-effbuy-${idx}`);
  if (!hint) return;
  if (discount > 0 && buy > 0) {
    hint.style.display = '';
    hint.innerHTML = `<i class="ti ti-arrow-down" style="font-size:10px"></i> After ${discount}% discount: <strong style="color:var(--color-text-success)">${fmt(effectiveBuy)}</strong>/unit`;
  } else {
    hint.style.display = 'none';
    hint.textContent = '';
  }
}

// Live summary line next to the discount input — shown the same way the
// sale-side discount preview shows the effect on the sale amount, but
// here it reflects the effect on the purchase cost / amount payable.
function onPurchaseDiscountInput() {
  const discount = getPurchaseDiscount();
  const preview  = document.getElementById('purchase-discount-preview');

  if (preview) {
    if (discount <= 0) {
      preview.innerHTML = 'Reduces the purchase cost / amount payable to the party only — your sale price stays based on the price you entered per item.';
    } else if (discount >= 100) {
      preview.innerHTML = '<span style="color:var(--color-text-danger)"><i class="ti ti-alert-circle"></i> Max 99.9% allowed</span>';
    } else {
      let grossBuy = 0;
      document.querySelectorAll('#items-container .item-row').forEach(row => {
        const id  = row.id.replace('item-row-', '');
        const sizes = itemSizeData[id] || [];
        const qty = sizes.reduce((sum, s) => sum + (parseFloat(s.qty) || 0), 0);
        const buy = parseFloat(document.getElementById(`ir-buy-${id}`)?.value) || 0;
        grossBuy += qty * buy;
      });
      const saved = grossBuy * discount / 100;
      const after = grossBuy - saved;
      preview.innerHTML = saved > 0
        ? `<span style="color:var(--color-text-success);font-weight:600"><i class="ti ti-rosette-discount"></i> Save ${fmt(saved)}</span>
           <span style="color:var(--color-text-tertiary);margin-left:8px">→ Net payable: <strong style="color:var(--color-text-primary)">${fmt(after)}</strong></span>`
        : `${discount}% discount will be applied to purchase cost`;
    }
  }

  recalcGSTAll();
}

// Attach the listener directly here as well, so the recalculation runs
// even if the inline oninput attribute on the input tag is ever missing.
const purchaseDiscountInputEl = document.getElementById('f-purchase-discount');
if (purchaseDiscountInputEl) {
  purchaseDiscountInputEl.addEventListener('input', onPurchaseDiscountInput);
}

async function autoFillBillNo() {
  const input = document.getElementById('f-bill-no');
  if (!input || input.value.trim()) return;
  try {
    const res = await fetch('/api/generate_bill_no');
    const data = await res.json();
    input.value = data.billNo;
  } catch (e) { console.warn(e); }
}

// Default the Date field to today when the page loads
const purchaseDateInput = document.getElementById('f-purchase-date');
if (purchaseDateInput) purchaseDateInput.value = todayLocalDate();