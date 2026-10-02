// =========================================================================
// modules/settings/thermalPrinter.js
// Manage Thermal Printer tab (USB VID / PID) + sending a sale receipt to it.
// =========================================================================

function _tpSetStatus(msg, ok) {
  const el = document.getElementById('tp-status');
  if (!el) return;
  el.textContent = msg || '';
  el.style.color = ok ? '#16a34a' : '#ef4444';
}

function _tpReadForm() {
  return {
    vendor_id: document.getElementById('tp-vid').value.trim(),
    product_id: document.getElementById('tp-pid').value.trim(),
    paper_width: parseInt(document.getElementById('tp-paper-width').value, 10) || 80,
    auto_cut: document.getElementById('tp-auto-cut').value === '1',
    enabled: document.getElementById('tp-enabled').value === '1'
  };
}

async function loadThermalPrinter() {
  try {
    const res = await fetch('/api/thermal_printer_settings');
    const cfg = await res.json();
    document.getElementById('tp-vid').value = cfg.vendor_id || '';
    document.getElementById('tp-pid').value = cfg.product_id || '';
    document.getElementById('tp-paper-width').value = String(cfg.paper_width || 80);
    document.getElementById('tp-auto-cut').value = cfg.auto_cut ? '1' : '0';
    document.getElementById('tp-enabled').value = cfg.enabled ? '1' : '0';
    _tpSetStatus('', true);
  } catch (err) { console.error('Error loading thermal printer settings:', err); }
}

async function saveThermalPrinter() {
  try {
    const res = await fetch('/api/thermal_printer_settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_tpReadForm())
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToast('Thermal printer settings saved');
      loadThermalPrinter();
    } else {
      showToast(data.message || 'Error saving thermal printer settings', '#ef4444');
    }
  } catch (err) { showToast('Error saving thermal printer settings', '#ef4444'); }
}

async function testThermalPrinter() {
  _tpSetStatus('Sending test page...', true);
  try {
    const form = _tpReadForm();
    const res = await fetch('/api/thermal_printer/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form)
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.status === 'ok') _tpSetStatus('Test page sent. Check the printer.', true);
    else _tpSetStatus(data.message || 'Test print failed', false);
  } catch (err) { _tpSetStatus('Test print failed', false); }
}

// Builds the same numbers the on-screen receipt shows (see buildReceiptHTML
// in modules/sales/receipt.js) and posts them to the server for printing.
function buildThermalPayload(header, items, discount, saleId) {
  discount = discount || 0;
  let subTotal = 0;
  const rows = items.map(it => {
    const rate = round2(it.sell_unit);
    const qty = it.qty || 1;
    subTotal += round2(rate * qty);
    return {
      item: it.item || '',
      size: it.size || '',
      qty: qty,
      rate: rate,
      amount: round2(getItemDiscountedTotal(it, discount))
    };
  });
  subTotal = round2(subTotal);
  const grandTotal = round2(rows.reduce((sum, r) => sum + r.amount, 0));
  const discountAmt = round2(subTotal - grandTotal);

  let amountPaid = grandTotal;
  if (header.payment_mode === 'Split') {
    amountPaid = round2((header.cash_amount || 0) + (header.online_amount || 0));
  } else if (header.payment_mode === 'Credit') {
    amountPaid = round2(header.advance_amount || 0);
  }

  return {
    header: header,
    saleId: saleId,
    time: header.time || new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
    items: rows,
    subTotal: subTotal,
    discount: discount,
    discountAmt: discountAmt,
    amountPaid: amountPaid,
    amountInWords: amountInWords(grandTotal)
  };
}

// Returns 'ok' (printed), 'disabled' (thermal printing is off, caller should
// use the normal browser print) or 'error' (a toast has already been shown).
async function printSaleReceiptThermal(header, items, discount, saleId) {
  try {
    const res = await fetch('/api/thermal_printer/print', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildThermalPayload(header, items, discount, saleId))
    });
    const data = await res.json().catch(() => ({}));
    if (data.status === 'ok') { showToast('Receipt sent to thermal printer'); return 'ok'; }
    if (data.status === 'disabled') return 'disabled';
    showToast(data.message || 'Thermal print failed. Use Print Receipt to try again.', '#ef4444');
    return 'error';
  } catch (err) {
    showToast('Thermal print failed. Use Print Receipt to try again.', '#ef4444');
    return 'error';
  }
}