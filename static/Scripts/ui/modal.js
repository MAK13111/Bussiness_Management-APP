// =========================================================================
// ui/modal.js
// Edit modals for purchase/sale entries and purchase/sale bills.
// Two related flows live here: a quick edit opened from the
// Analyze/Reports list (openEditPurchase/openEditSell), and the fuller
// bill-edit modal opened from the Bills panel (openPurchaseEdit/
// openSaleEdit), which share the editType/editId/editItems state and
// the closeEditModal/submitEdit dispatcher.
// =========================================================================

function openEditPurchase(id) {
  const e = entries.find(x => x.id === id);
  if (!e) return;
  const body = `
    <div style="display:grid;gap:12px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Date</label><input id="ep-date" class="edit-input" type="date" value="${(e.date||'').slice(0,10)}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Party Name</label><input id="ep-party" class="edit-input" type="text" value="${e.party||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Item Name</label><input id="ep-item" class="edit-input" type="text" value="${e.item||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Size</label><input id="ep-size" class="edit-input" type="text" value="${e.size||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Qty</label><input id="ep-qty" class="edit-input" type="number" min="1" value="${e.qty||1}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Buy / Unit (₹)</label><input id="ep-buy" class="edit-input" type="number" min="0" step="0.01" value="${e.buy||0}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Margin (%)</label><input id="ep-margin" class="edit-input" type="number" min="0" step="0.1" value="${(+e.margin||0).toFixed(1)}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Department</label><input id="ep-dept" class="edit-input" type="text" value="${e.department||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Seller No.</label><input id="ep-sellerno" class="edit-input" type="text" value="${e.sellerNo||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Invoice No.</label><input id="ep-invoice" class="edit-input" type="text" value="${e.invoiceNo||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">CGST (%)</label><input id="ep-cgst" class="edit-input" type="number" min="0" step="0.01" value="${(+e.cgst||0).toFixed(2)}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">SGST (%)</label><input id="ep-sgst" class="edit-input" type="number" min="0" step="0.01" value="${(+e.sgst||0).toFixed(2)}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">IGST (%)</label><input id="ep-igst" class="edit-input" type="number" min="0" step="0.01" value="${(+e.igst||0).toFixed(2)}"/></div>
      </div>
      <div><label style="font-size:12px;color:var(--color-text-secondary)">Seller Address</label><input id="ep-selleraddr" class="edit-input" type="text" value="${e.sellerAddress||''}" style="width:100%"/></div>
      <button class="add-btn" style="margin-top:4px" onclick="saveEditPurchase(${id})"><i class="ti ti-check"></i> Save Changes</button>
    </div>`;
  openDrawer('Edit Purchase — #' + id, body);
}

async function saveEditPurchase(id) {
  const payload = {
    date: document.getElementById('ep-date').value,
    party: document.getElementById('ep-party').value.trim(),
    item: document.getElementById('ep-item').value.trim(),
    size: document.getElementById('ep-size').value.trim(),
    qty: document.getElementById('ep-qty').value,
    buy: document.getElementById('ep-buy').value,
    margin: document.getElementById('ep-margin').value,
    department: document.getElementById('ep-dept').value.trim(),
    sellerNo: document.getElementById('ep-sellerno').value.trim(),
    invoiceNo: document.getElementById('ep-invoice').value.trim(),
    cgst: document.getElementById('ep-cgst').value,
    sgst: document.getElementById('ep-sgst').value,
    igst: document.getElementById('ep-igst').value,
    sellerAddress: document.getElementById('ep-selleraddr').value.trim(),
  };
  try {
    const res = await fetch(`/api/entries/${id}?type=purchase&mode=${currentMode}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeDrawer();
      showToast('✓ Purchase updated!');
      loadEntries();
    } else {
      showToast('Error updating entry!', '#ef4444');
    }
  } catch(err) {
    showToast('Error updating entry!', '#ef4444');
  }
}

function openEditSell(id) {
  const e = sellEntries.find(x => x.id === id);
  if (!e) return;
  const body = `
    <div style="display:grid;gap:12px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Date</label><input id="es-date" class="edit-input" type="date" value="${(e.date||'').slice(0,10)}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Customer Name</label><input id="es-custname" class="edit-input" type="text" value="${e.customerName||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Customer No.</label><input id="es-custno" class="edit-input" type="text" value="${e.customerNo||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Payment Mode</label><select id="es-payment" class="edit-input"><option value="Cash" ${(e.paymentMode||'Cash')==='Cash'?'selected':''}>Cash</option><option value="Online" ${e.paymentMode==='Online'?'selected':''}>Online</option></select></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Bill No.</label><input id="es-billno" class="edit-input" type="text" value="${e.billNo||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Item Name</label><input id="es-item" class="edit-input" type="text" value="${e.item||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Size</label><input id="es-size" class="edit-input" type="text" value="${e.size||''}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Qty</label><input id="es-qty" class="edit-input" type="number" min="1" value="${e.qty||1}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Buy / Unit (₹)</label><input id="es-buy" class="edit-input" type="number" min="0" step="0.01" value="${e.buy||0}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Margin (%)</label><input id="es-margin" class="edit-input" type="number" min="0" step="0.1" value="${(+e.margin||0).toFixed(1)}"/></div>
        <div><label style="font-size:12px;color:var(--color-text-secondary)">Discount (%)</label><input id="es-discount" class="edit-input" type="number" min="0" max="100" step="0.1" value="${(+e.discount||0).toFixed(1)}"/></div>
      </div>
      <button class="add-btn" style="margin-top:4px" onclick="saveEditSell(${id})"><i class="ti ti-check"></i> Save Changes</button>
    </div>`;
  openDrawer('Edit Sell — #' + id, body);
}

async function saveEditSell(id) {
  const payload = {
    date: document.getElementById('es-date').value,
    customerName: document.getElementById('es-custname').value.trim(),
    customerNo: document.getElementById('es-custno').value.trim(),
    paymentMode: document.getElementById('es-payment').value,
    billNo: document.getElementById('es-billno').value.trim(),
    item: document.getElementById('es-item').value.trim(),
    size: document.getElementById('es-size').value.trim(),
    qty: document.getElementById('es-qty').value,
    buy: document.getElementById('es-buy').value,
    margin: document.getElementById('es-margin').value,
    discount: document.getElementById('es-discount').value,
  };
  try {
    const res = await fetch(`/api/entries/${id}?type=sell&mode=${currentMode}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeDrawer();
      showToast('✓ Sell updated!');
      loadSellEntries();
    } else {
      showToast('Error updating entry!', '#ef4444');
    }
  } catch(err) {
    showToast('Error updating entry!', '#ef4444');
  }
}

// ─── BILL EDIT MODAL (Purchase / Sale) ─────────────────────────────────────────

let editType = null; // 'purchase' or 'sale'
let editId = null;
let editItems = []; // local array for dynamic item rows

function closeEditModal() {
  document.getElementById('edit-modal').style.display = 'none';
  editType = null;
  editId = null;
  editItems = [];
}

async function openPurchaseEdit(purchaseId) {
  editType = 'purchase';
  editId = purchaseId;
  document.getElementById('edit-modal-title').textContent = 'Edit Purchase Bill #' + purchaseId;
  document.getElementById('edit-modal-body').innerHTML = '<div style="text-align:center;padding:1rem;">Loading...</div>';
  document.getElementById('edit-modal').style.display = 'flex';

  try {
    const res = await fetch(`/api/purchase_bill/${purchaseId}`);
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || 'Failed to load purchase', '#ef4444');
      closeEditModal();
      return;
    }
    const data = await res.json();
    const header = data.header;
    const items = data.items;
    editItems = items.map(it => ({ ...it })); // copy
    renderEditPurchaseForm(header, items);
  } catch (e) {
    showToast('Error loading purchase', '#ef4444');
    closeEditModal();
  }
}

function renderEditPurchaseForm(header, items) {
  const body = document.getElementById('edit-modal-body');
  // Build header fields
  let html = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:1rem;">
      <div class="field"><label>Date</label><input type="date" id="edit-date" value="${(header.date || '').slice(0,10)}" /></div>
      <div class="field"><label>Party *</label><input type="text" id="edit-party" value="${header.party || ''}" /></div>
      <div class="field"><label>Seller No.</label><input type="text" id="edit-seller-no" value="${header.seller_no || ''}" /></div>
      <div class="field"><label>Seller Address</label><input type="text" id="edit-seller-addr" value="${header.seller_address || ''}" /></div>
      <div class="field"><label>Invoice No.</label><input type="text" id="edit-invoice-no" value="${header.invoice_no || ''}" /></div>
      <div class="field"><label>CGST (%)</label><input type="number" id="edit-cgst" step="0.01" value="${header.cgst_rate || 0}" /></div>
      <div class="field"><label>SGST (%)</label><input type="number" id="edit-sgst" step="0.01" value="${header.sgst_rate || 0}" /></div>
      <div class="field"><label>IGST (%)</label><input type="number" id="edit-igst" step="0.01" value="${header.igst_rate || 0}" /></div>
      <div class="field"><label>Discount from Supplier (%)</label><input type="number" id="edit-discount" step="0.1" min="0" max="99.9" value="${header.discount || 0}" /></div>
    </div>
    <div style="margin:1rem 0 0.5rem 0;font-weight:600;font-size:14px;">Items</div>
    <div style="font-size:12px;color:var(--color-text-tertiary);margin-bottom:8px">Buy price below is the original price per unit (before discount) — same as when the bill was created.</div>
    <div id="edit-items-container"></div>
    <button class="add-item-btn" onclick="addEditItemRow()"><i class="ti ti-plus"></i> Add item</button>
  `;
  body.innerHTML = html;

  // Render items
  const container = document.getElementById('edit-items-container');
  items.forEach((it, idx) => {
    addEditItemRow(it, idx);
  });
  // Attach save button
  document.getElementById('edit-save-btn').onclick = function() { submitEdit(); };
}

function addEditItemRow(prefill = null, index = null) {
  const container = document.getElementById('edit-items-container');
  if (!container) return;
  const idx = index !== null ? index : container.children.length;
  const it = prefill || {};
  const isSale = (editType === 'sale');
  // For purchases, show the original (pre-discount) price the user typed —
  // not the stored buy_price, which already has the discount baked in.
  const buyPriceForField = (!isSale && it.original_buy_price != null) ? it.original_buy_price : (it.buy_price || 0);
  const row = document.createElement('div');
  row.className = 'item-row';
  row.dataset.index = idx;
  // Build fields based on type
  let fieldsHTML = `
    <div class="field"><label>Item name</label><input type="text" class="edit-item-name" value="${it.item || ''}" /></div>
    <div class="field"><label>Size</label><input type="text" class="edit-item-size" value="${it.size || ''}" /></div>
    <div class="field"><label>Qty</label><input type="number" class="edit-item-qty" step="1" min="1" value="${it.qty || 1}" /></div>
    <div class="field"><label>Buy price</label><input type="number" class="edit-item-buy" step="0.01" min="0" value="${buyPriceForField}" /></div>
    <div class="field"><label>Margin (%)</label><input type="number" class="edit-item-margin" step="0.1" min="0" value="${it.margin || 0}" /></div>
    <div class="field"><label>Sell price</label><input type="number" class="edit-item-sell" step="0.01" min="0" value="${it.sell_price || 0}" /></div>
  `;
  if (isSale) {
    fieldsHTML += `
      <div class="field"><label>Discount (%)</label><input type="number" class="edit-item-discount" step="0.1" min="0" value="${it.discount || 0}" /></div>
    `;
  } else {
    fieldsHTML += `
      <div class="field"><label>CGST (%)</label><input type="number" class="edit-item-cgst" step="0.01" min="0" value="${it.cgst || 0}" /></div>
      <div class="field"><label>SGST (%)</label><input type="number" class="edit-item-sgst" step="0.01" min="0" value="${it.sgst || 0}" /></div>
      <div class="field"><label>IGST (%)</label><input type="number" class="edit-item-igst" step="0.01" min="0" value="${it.igst || 0}" /></div>
      <div class="field"><label>Department</label><input type="text" class="edit-item-dept" value="${it.department || ''}" /></div>
    `;
  }

  row.innerHTML = `
    <div class="item-row-header">
      <span class="item-row-num">Item #${idx+1}</span>
      <button class="item-row-del" onclick="removeEditItemRow(this)" title="Remove"><i class="ti ti-trash"></i></button>
    </div>
    <div class="fields" style="margin-bottom:0;grid-template-columns:1fr 1fr 1fr 1fr;">
      ${fieldsHTML}
    </div>
    <input type="hidden" class="edit-item-id" value="${it.id || ''}" />
  `;
  container.appendChild(row);
  updateEditItemRowNumbers();
}

function removeEditItemRow(btn) {
  const row = btn.closest('.item-row');
  if (row) {
    row.remove();
    updateEditItemRowNumbers();
  }
}

function updateEditItemRowNumbers() {
  const rows = document.querySelectorAll('#edit-items-container .item-row');
  rows.forEach((row, i) => {
    const num = row.querySelector('.item-row-num');
    if (num) num.textContent = `Item #${i+1}`;
    row.dataset.index = i;
  });
}

function getEditPurchaseItemsData() {
  const rows = document.querySelectorAll('#edit-items-container .item-row');
  const items = [];
  rows.forEach(row => {
    const id = row.querySelector('.edit-item-id')?.value || '';
    const item = row.querySelector('.edit-item-name')?.value || '';
    const size = row.querySelector('.edit-item-size')?.value || '';
    const qty = parseFloat(row.querySelector('.edit-item-qty')?.value) || 0;
    const buy = parseFloat(row.querySelector('.edit-item-buy')?.value) || 0;
    const margin = parseFloat(row.querySelector('.edit-item-margin')?.value) || 0;
    const sell = parseFloat(row.querySelector('.edit-item-sell')?.value) || 0;
    const cgst = parseFloat(row.querySelector('.edit-item-cgst')?.value) || 0;
    const sgst = parseFloat(row.querySelector('.edit-item-sgst')?.value) || 0;
    const igst = parseFloat(row.querySelector('.edit-item-igst')?.value) || 0;
    if (item.trim() && qty > 0 && buy >= 0) {
      items.push({ id: id ? parseInt(id) : null, item, size, qty, buy, margin, sell_price: sell, cgst, sgst, igst, department });
    }
  });
  return items;
}

function getEditSaleItemsData() {
  const rows = document.querySelectorAll('#edit-items-container .item-row');
  const items = [];
  rows.forEach(row => {
    const id = row.querySelector('.edit-item-id')?.value || '';
    const item = row.querySelector('.edit-item-name')?.value || '';
    const size = row.querySelector('.edit-item-size')?.value || '';
    const qty = parseFloat(row.querySelector('.edit-item-qty')?.value) || 0;
    const buyPrice = parseFloat(row.querySelector('.edit-item-buy')?.value) || 0;
    const margin = parseFloat(row.querySelector('.edit-item-margin')?.value) || 0;
    const sell = parseFloat(row.querySelector('.edit-item-sell')?.value) || 0;
    const discount = parseFloat(row.querySelector('.edit-item-discount')?.value) || 0;
    if (item.trim() && qty > 0 && buyPrice >= 0) {
      items.push({
        id: id ? parseInt(id) : null,
        item,
        size,
        qty,
        buy_price: buyPrice,     // backend expects 'buy_price'
        margin,
        sell_price: sell,
        discount
      });
    }
  });
  return items;
}

async function submitEdit() {
  if (editType === 'purchase') {
    await submitPurchaseEdit();
  } else if (editType === 'sale') {
    await submitSaleEdit();
  } else if (editType === 'replace') {
    await submitReplaceEdit();
  }
}

async function submitPurchaseEdit() {
  const header = {
    party: document.getElementById('edit-party').value.trim(),
    seller_no: document.getElementById('edit-seller-no').value.trim(),
    seller_address: document.getElementById('edit-seller-addr').value.trim(),
    invoice_no: document.getElementById('edit-invoice-no').value.trim(),
    date: document.getElementById('edit-date').value,
    cgst: parseFloat(document.getElementById('edit-cgst').value) || 0,
    sgst: parseFloat(document.getElementById('edit-sgst').value) || 0,
    igst: parseFloat(document.getElementById('edit-igst').value) || 0,
    discount: parseFloat(document.getElementById('edit-discount').value) || 0
  };
  const items = getEditPurchaseItemsData();
  if (!header.party) { showToast('Party name required', '#ef4444'); return; }
  if (!items.length) { showToast('At least one item required', '#ef4444'); return; }

  try {
    const res = await fetch(`/api/purchase_bill/${editId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ header, items })
    });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      showToast('Purchase bill updated successfully');
      closeEditModal();
      loadReportPurchaseBills(); // refresh reports
      if (typeof loadPurchaseBills === 'function') loadPurchaseBills(); // refresh Purchase tab bills panel
    } else {
      showToast(data.msg || 'Error updating purchase', '#ef4444');
    }
  } catch (e) {
    showToast('Network error', '#ef4444');
  }
}

async function openSaleEdit(saleId) {
  editType = 'sale';
  editId = saleId;
  document.getElementById('edit-modal-title').textContent = 'Edit Sale Bill #' + saleId;
  document.getElementById('edit-modal-body').innerHTML = '<div style="text-align:center;padding:1rem;">Loading...</div>';
  document.getElementById('edit-modal').style.display = 'flex';

  try {
    const res = await fetch(`/api/sale_bill/${saleId}`);
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || 'Failed to load sale', '#ef4444');
      closeEditModal();
      return;
    }
    const data = await res.json();
    const header = data.header;
    const items = data.items;
    editItems = items.map(it => ({ ...it }));
    renderEditSaleForm(header, items);
  } catch (e) {
    showToast('Error loading sale', '#ef4444');
    closeEditModal();
  }
}

function renderEditSaleForm(header, items) {
  const body = document.getElementById('edit-modal-body');
  let html = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:1rem;">
      <div class="field"><label>Date</label><input type="date" id="edit-sale-date" value="${(header.date || '').slice(0,10)}" /></div>
      <div class="field"><label>Customer Name</label><input type="text" id="edit-sale-customer" value="${header.customer_name || ''}" /></div>
      <div class="field"><label>Customer No.</label><input type="text" id="edit-sale-custno" value="${header.customer_no || ''}" /></div>
      <div class="field"><label>Bill No.</label><input type="text" id="edit-sale-billno" value="${header.bill_no || ''}" /></div>
      <div class="field"><label>Payment Mode</label>
        <select id="edit-sale-payment">
          <option value="Cash" ${header.payment_mode === 'Cash' ? 'selected' : ''}>Cash</option>
          <option value="Online" ${header.payment_mode === 'Online' ? 'selected' : ''}>Online</option>
          <option value="Split" ${header.payment_mode === 'Split' ? 'selected' : ''}>Split</option>
          <option value="Credit" ${header.payment_mode === 'Credit' ? 'selected' : ''}>Credit</option>
        </select>
      </div>
      <div class="field"><label>Discount (%)</label><input type="number" id="edit-sale-discount" step="0.1" min="0" value="${header.discount || 0}" /></div>
    </div>
    <div style="margin:1rem 0 0.5rem 0;font-weight:600;font-size:14px;">Items</div>
    <div id="edit-items-container"></div>
    <button class="add-item-btn" onclick="addEditItemRow()"><i class="ti ti-plus"></i> Add item</button>
  `;
  body.innerHTML = html;

  const container = document.getElementById('edit-items-container');
  items.forEach((it, idx) => {
    addEditItemRow(it, idx);
  });
  document.getElementById('edit-save-btn').onclick = function() { submitEdit(); };
}

async function submitSaleEdit() {
  const header = {
    customer_name: document.getElementById('edit-sale-customer').value.trim(),
    customer_no: document.getElementById('edit-sale-custno').value.trim(),
    bill_no: document.getElementById('edit-sale-billno').value.trim(),
    date: document.getElementById('edit-sale-date').value,
    payment_mode: document.getElementById('edit-sale-payment').value,
    discount: parseFloat(document.getElementById('edit-sale-discount').value) || 0
  };
  const items = getEditSaleItemsData();
  if (!items.length) { showToast('At least one item required', '#ef4444'); return; }

  try {
    const res = await fetch(`/api/sale_bill/${editId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ header, items })
    });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      showToast('Sale bill updated successfully');
      closeEditModal();
      loadReportSaleBills();
    } else {
      showToast(data.msg || 'Error updating sale', '#ef4444');
    }
  } catch (e) {
    showToast('Network error', '#ef4444');
  }
}

// ─── BILL EDIT MODAL (Replace Bill) ─────────────────────────────────────────
// Editable: date, customer, note, discount and each item's qty/rate.
// Barcode/stock status is left untouched — only billing figures change.

async function openReplaceEdit(replaceBillId) {
  editType = 'replace';
  editId = replaceBillId;
  document.getElementById('edit-modal-title').textContent = 'Edit Replace Bill #' + replaceBillId;
  document.getElementById('edit-modal-body').innerHTML = '<div style="text-align:center;padding:1rem;">Loading...</div>';
  document.getElementById('edit-modal').style.display = 'flex';

  try {
    const res = await fetch(`/api/replace_bill/${replaceBillId}`);
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || 'Failed to load replace bill', '#ef4444');
      closeEditModal();
      return;
    }
    const header = await res.json();
    renderEditReplaceForm(header);
  } catch (e) {
    showToast('Error loading replace bill', '#ef4444');
    closeEditModal();
  }
}

function renderEditReplaceForm(header) {
  const body = document.getElementById('edit-modal-body');
  const oldItems = (header.items || []).filter(i => i.side === 'old');
  const newItems = (header.items || []).filter(i => i.side === 'new');

  const buildItemRows = (items) => items.map((it) => `
    <div class="item-row" data-side="${it.side}">
      <div class="item-row-header">
        <span class="item-row-num">${it.item || '—'}${it.size ? ' (' + it.size + ')' : ''} <span style="font-weight:400;color:var(--color-text-tertiary);font-size:12px">${it.barcode_code || ''}</span></span>
      </div>
      <div class="fields" style="margin-bottom:0;grid-template-columns:1fr 1fr;">
        <div class="field"><label>Qty</label><input type="number" class="edit-rb-qty" step="1" min="1" value="${it.qty || 1}" /></div>
        <div class="field"><label>Rate (₹)</label><input type="number" class="edit-rb-rate" step="0.01" min="0" value="${it.sell_price || 0}" /></div>
      </div>
      <input type="hidden" class="edit-rb-id" value="${it.id || ''}" />
      <input type="hidden" class="edit-rb-side" value="${it.side || ''}" />
    </div>
  `).join('');

  let html = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:1rem;">
      <div class="field"><label>Date</label><input type="date" id="edit-rb-date" value="${(header.date || '').slice(0,10)}" /></div>
      <div class="field"><label>Customer Name</label><input type="text" id="edit-rb-customer" value="${header.customerName || ''}" /></div>
      <div class="field"><label>Customer No.</label><input type="text" id="edit-rb-custno" value="${header.customerNo || ''}" /></div>
      <div class="field"><label>Discount on New Item(s) (%)</label><input type="number" id="edit-rb-discount" step="0.1" min="0" max="99.9" value="${header.discount || 0}" /></div>
      <div class="field" style="grid-column:1 / -1"><label>Note</label><input type="text" id="edit-rb-note" value="${header.note || ''}" /></div>
    </div>
    ${oldItems.length ? `<div style="margin:1rem 0 0.5rem 0;font-weight:600;font-size:14px;"><i class="ti ti-arrow-back-up"></i> Returned Items</div>${buildItemRows(oldItems)}` : ''}
    ${newItems.length ? `<div style="margin:1rem 0 0.5rem 0;font-weight:600;font-size:14px;"><i class="ti ti-arrow-forward-up"></i> New Items Given</div>${buildItemRows(newItems)}` : ''}
  `;
  body.innerHTML = html;
  document.getElementById('edit-save-btn').onclick = function() { submitEdit(); };
}

async function submitReplaceEdit() {
  const header = {
    date: document.getElementById('edit-rb-date').value,
    customerName: document.getElementById('edit-rb-customer').value.trim(),
    customerNo: document.getElementById('edit-rb-custno').value.trim(),
    note: document.getElementById('edit-rb-note').value.trim(),
    discount: parseFloat(document.getElementById('edit-rb-discount').value) || 0
  };
  const rows = document.querySelectorAll('#edit-modal-body .item-row');
  const items = [];
  rows.forEach(row => {
    const id = row.querySelector('.edit-rb-id')?.value;
    const side = row.querySelector('.edit-rb-side')?.value;
    const qty = parseFloat(row.querySelector('.edit-rb-qty')?.value) || 1;
    const sell_price = parseFloat(row.querySelector('.edit-rb-rate')?.value) || 0;
    if (id) items.push({ id: parseInt(id), side, qty, sell_price });
  });
  if (!items.length) { showToast('No items found to update', '#ef4444'); return; }

  try {
    const res = await fetch(`/api/replace_bill/${editId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ header, items })
    });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      showToast('Replace bill updated successfully');
      closeEditModal();
      loadReportReplaceBills();
    } else {
      showToast(data.message || 'Error updating replace bill', '#ef4444');
    }
  } catch (e) {
    showToast('Network error', '#ef4444');
  }
}