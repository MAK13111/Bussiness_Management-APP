// =========================================================================
// ui/modal.js
// Edit modals for purchase/sale entries and purchase bills.
// Two related flows live here: a quick edit opened from the
// Analyze/Reports list (openEditPurchase/openEditSell), and the fuller
// bill-edit modal opened from the Purchase Bills panel (openPurchaseEdit),
// which uses the editType/editId/editItems state and the
// closeEditModal/submitEdit dispatcher.
// =========================================================================

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

let editType = null; // 'purchase'
let editId = null;
let editItems = []; // local array for dynamic item rows

function closeEditModal() {
  document.getElementById('edit-modal').style.display = 'none';
  editType = null;
  editId = null;
  editItems = [];
}

// Bill edit modal functionality removed in favor of direct Delete action.
