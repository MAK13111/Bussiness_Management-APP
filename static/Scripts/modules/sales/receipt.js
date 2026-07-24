// =========================================================================
// modules/sales/receipt.js
// Builds and prints the printable sale receipt, and saves a sale made
// through the barcode-scanner flow.
// =========================================================================

let lastReceiptHTML = '';

// ---- Number to words (Indian Rupees) ----------------------------------
function numberToWordsIN(num) {
  const ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
    'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen'];
  const tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety'];

  function twoDigits(n) {
    if (n < 20) return ones[n];
    return tens[Math.floor(n / 10)] + (n % 10 ? ' ' + ones[n % 10] : '');
  }
  function threeDigits(n) {
    let str = '';
    if (n >= 100) {
      str += ones[Math.floor(n / 100)] + ' Hundred';
      n %= 100;
      if (n) str += ' ';
    }
    if (n) str += twoDigits(n);
    return str;
  }

  n = Math.floor(num);
  if (n === 0) return 'Zero';

  let parts = [];
  const crore = Math.floor(n / 10000000); n %= 10000000;
  const lakh = Math.floor(n / 100000); n %= 100000;
  const thousand = Math.floor(n / 1000); n %= 1000;
  const hundred = n;

  if (crore) parts.push(threeDigits(crore) + ' Crore');
  if (lakh) parts.push(threeDigits(lakh) + ' Lakh');
  if (thousand) parts.push(threeDigits(thousand) + ' Thousand');
  if (hundred) parts.push(threeDigits(hundred));

  return parts.join(' ');
}

function amountInWords(amount) {
  amount = round2(amount);
  const rupees = Math.floor(amount);
  const paise = Math.round((amount - rupees) * 100);
  let words = numberToWordsIN(rupees) + ' Rupee' + (rupees === 1 ? '' : 's');
  if (paise > 0) {
    words += ' and ' + numberToWordsIN(paise) + ' Paise';
  }
  return words + ' Only';
}

// ---- Receipt builder -----------------------------------------------------
function buildReceiptHTML(shopInfo, header, items, discount, saleId) {
  shopInfo = shopInfo || {};
  discount = discount || 0;
  let rowsHtml = '';
  let subTotal = 0;

  items.forEach((it, idx) => {
    const rate = round2(it.sell_unit);
    const qty = it.qty || 1;
    const amount = round2(rate * qty);
    subTotal += amount;
    const discRate = round2(rate * (1 - discount / 100));
    const discAmount = round2(amount * (1 - discount / 100));
    const nameLine = `${it.item || '—'}${it.size ? ' (' + it.size + ')' : ''}`;
    rowsHtml += `
      <tr style="border-bottom:1px dotted #999">
        <td style="padding:5px 2px;font-size:10.5px;text-align:center;color:#000">${idx + 1}</td>
        <td style="padding:5px 2px;font-size:10.5px;color:#000">${nameLine}</td>
        <td style="padding:5px 2px;font-size:10.5px;text-align:center;color:#000">${qty}</td>
        <td style="padding:5px 2px;font-size:10.5px;text-align:right;color:#000">${fmtNum(rate)}</td>
        <td style="padding:5px 2px;font-size:10.5px;text-align:right;color:#000">${fmtNum(discAmount)}</td>
      </tr>`;
  });

  subTotal = round2(subTotal);
  const discountAmt = round2(subTotal * discount / 100);
  const grandTotal = round2(subTotal - discountAmt);

  let amountPaid = grandTotal;
  if (header.payment_mode === 'Split') {
    amountPaid = round2((header.cash_amount || 0) + (header.online_amount || 0));
  } else if (header.payment_mode === 'Credit') {
    amountPaid = round2(header.advance_amount || 0);
  }

  const now = new Date();
  const timeStr = header.time || now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

  return `
    <div class="receipt-box" style="font-family:Arial,Helvetica,sans-serif;width:76mm;margin:0 auto;padding:3mm;background:#fff;color:#000;box-sizing:border-box">
    <style>.receipt-box tbody tr:hover td { background: transparent !important; }</style>
      <div style="text-align:center;margin-bottom:5px;color:#000">
        ${shopInfo.shop_name ? `<div style="font-size:15px;font-weight:800;letter-spacing:0.3px;color:#000">${shopInfo.shop_name.toUpperCase()}</div>` : ''}
        ${shopInfo.address ? `<div style="font-size:10.5px;margin-top:3px;color:#000">${shopInfo.address}</div>` : ''}
        ${shopInfo.phone ? `<div style="font-size:10.5px;color:#000">Phone: ${shopInfo.phone}</div>` : ''}
        ${shopInfo.gst_no ? `<div style="font-size:10.5px;color:#000">GSTIN: ${shopInfo.gst_no}</div>` : ''}
      </div>

      <div style="text-align:center;font-size:12px;font-weight:700;letter-spacing:1.5px;margin:10px 0;display:flex;align-items:center;justify-content:center;gap:6px;color:#000">
        <span style="flex:1;border-top:1px solid #000"></span>
        <span>SALE RECEIPT</span>
        <span style="flex:1;border-top:1px solid #000"></span>
      </div>

      <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px;color:#000">
        <span><b>Bill No.</b> : ${header.bill_no || saleId}</span>
        <span><b>Date</b> : ${header.date || ''}</span>
      </div>
      <div style="text-align:right;font-size:11px;margin-bottom:3px;color:#000"><b>Time</b> : ${timeStr}</div>
      <div style="font-size:11px;margin-bottom:2px;color:#000"><b>Customer</b> :${header.customer_name ? '${header.customer_name}':'Cash'}</div>
      ${header.customer_no ? `<div style="font-size:11px;margin-bottom:2px;color:#000"><b>Mobile</b> : ${header.customer_no}</div>` : ''}
      ${header.payment_mode ? `<div style="font-size:11px;margin-bottom:2px;color:#000"><b>Payment Mode</b> : ${header.payment_mode}</div>` : ''}
      ${header.payment_mode === 'Split' ? `<div style="font-size:11px;margin-bottom:2px;color:#000"><b>Cash</b> : ₹ ${fmtNum(header.cash_amount || 0)} &nbsp;&nbsp; <b>Online</b> : ₹ ${fmtNum(header.online_amount || 0)}</div>` : ''}

      <div style="border-top:1px solid #000;margin:7px 0"></div>

      <table style="width:100%;border-collapse:collapse;color:#000">
        <thead>
          <tr style="background:#e9e9e9">
            <td style="padding:4px 2px;font-size:10.5px;font-weight:700;text-align:center;color:#000">S.No</td>
            <td style="padding:4px 2px;font-size:10.5px;font-weight:700;color:#000">Item Description</td>
            <td style="padding:4px 2px;font-size:10.5px;font-weight:700;text-align:center;color:#000">Qty</td>
            <td style="padding:4px 2px;font-size:10.5px;font-weight:700;text-align:right;color:#000">Rate</td>
            <td style="padding:4px 2px;font-size:10.5px;font-weight:700;text-align:right;color:#000">Amt</td>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>

      <div style="border-top:1px dashed #000;margin:7px 0"></div>

      <div style="display:flex;justify-content:flex-end">
        <div style="width:65%">
          <div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0;color:#000">
            <span>Sub Total</span><span>: ₹ ${fmtNum(subTotal)}</span>
          </div>
          ${discount > 0 ? `<div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0;color:#000">
            <span>Discount (${discount}%)</span><span>: ₹ ${fmtNum(discountAmt)}</span>
          </div>` : ''}
          <div style="display:flex;justify-content:space-between;font-size:11px;padding:2px 0;color:#000">
            <span><b>Amount Paid</b></span><span>: ₹ <b>${fmtNum(amountPaid)}</b></span>
          </div>
        </div>
      </div>

      <div style="font-size:10.5px;margin-top:10px;color:#000">
        <b>Amount In Words</b> : ${amountInWords(grandTotal)}
      </div>

      <div style="text-align:center;font-size:12px;font-weight:700;margin-top:12px;color:#000">
        ${shopInfo.footer_note || 'Thank You! Visit Again!!'}
      </div>
    </div>`;
}

async function renderSaleReceipt(header, items, discount, saleId) {
  let shopInfo = {};
  try {
    shopInfo = await fetch('/api/shop_settings').then(r => r.json());
  } catch (e) { /* ignore — receipt still works without shop info */ }
  lastReceiptHTML = buildReceiptHTML(shopInfo, header, items, discount, saleId);
  const wrap = document.getElementById('last-sale-receipt-wrap');
  const preview = document.getElementById('last-sale-receipt-preview');
  if (preview) preview.innerHTML = lastReceiptHTML;
  if (wrap) wrap.style.display = '';
}

function printSaleReceipt() {
  if (!lastReceiptHTML) { showToast('No receipt to print yet', '#ef4444'); return; }
  const w = window.open('', '_blank');
  w.document.write(`<!DOCTYPE html><html><head><title>Receipt</title>
    <style>
      * { box-sizing: border-box; }
      @page { size: 80mm auto; margin: 0; }
      html, body { width: 80mm; margin: 0; padding: 0; }
      body { padding: 3mm 0 10mm 0; }
      button { display: block; margin: 4mm auto 0; padding: 8px 22px; cursor: pointer; }
      @media print {
        html, body { width: 80mm; }
        body { padding: 0; }
        button { display: none; }
      }
    </style>
    </head><body>${lastReceiptHTML}
    <button onclick="window.print()">Print</button>
    </body></html>`);
  w.document.close();
}

let isSavingSale = false;

// Computes the grand total (after discount) the same way the receipt does,
// so validation and the credit/cash decision always match what's printed.
function calcSaleTotal(items, discountPct) {
    let subTotal = 0;
    items.forEach(it => {
        const sellUnit = (it.sell_unit && it.sell_unit > 0) ? it.sell_unit : it.buy_unit * (1 + (it.margin || 0) / 100);
        const rate = round2(sellUnit);
        subTotal += rate * (it.qty || 1);
    });
    subTotal = round2(subTotal);
    const discountAmt = round2(subTotal * (discountPct || 0) / 100);
    return round2(subTotal - discountAmt);
}

async function saveScannedSell() {
    if (isSavingSale) return;
    if (scannedItems.length === 0) {
        showToast('Pehle kuch items scan karo.', '#ef4444');
        return;
    }

    const discount = parseFloat(document.getElementById('f-discount').value) || 0;
    const grandTotal = calcSaleTotal(scannedItems, discount);

    // Decide the effective mode: a Credit Sale where the full amount is
    // received right away is saved as a normal Cash Sale instead.
    let effectiveMode = saleMode;
    let advanceAmount = 0;
    if (saleMode === 'credit') {
        advanceAmount = parseFloat(document.getElementById('f-credit-advance-amount').value) || 0;
        if (advanceAmount > 0 && advanceAmount >= grandTotal) {
            effectiveMode = 'cash';
        }
    }

    const paymentMode = effectiveMode === 'cash'
        ? (saleMode === 'credit' ? 'Cash' : document.getElementById('f-payment-mode').value)
        : 'Credit';

    const header = {
        customer_name: document.getElementById('f-customer-name').value.trim(),
        customer_no: document.getElementById('f-customer-no').value.trim(),
        bill_no: document.getElementById('f-bill-no').value.trim(),
        date: document.getElementById('f-sale-date').value || todayLocalDate(),
        payment_mode: paymentMode,
        discount: discount,
        cash_amount: paymentMode === 'Split' ? (parseFloat(document.getElementById('f-cash-amount').value) || 0) : null,
        online_amount: paymentMode === 'Split' ? (parseFloat(document.getElementById('f-online-amount').value) || 0) : null,
        // Only relevant when the sale is actually saved as Credit (partial payment received now)
        advance_amount: effectiveMode === 'credit' ? advanceAmount : null
    };

    // Expand items — qty ke hisab se saare scanned codes bhejo
    const items = scannedItems.map(it => ({
        item: it.item,
        size: it.size,
        qty: it.qty || 1,
        buy_price: it.buy_unit,
        margin: it.margin,
        sell_price: it.sell_unit,
        code: it.code,
        purchase_item_id: it.purchase_item_id,
        scanned_codes: it.scanned_codes || [it.code]
    }));

    // Validate: for cash sales, if split, check amounts
    if (effectiveMode === 'cash') {
        const mode = document.getElementById('f-payment-mode').value;
        if (mode === 'Split') {
            const cashAmt = parseFloat(document.getElementById('f-cash-amount').value) || 0;
            const onlineAmt = parseFloat(document.getElementById('f-online-amount').value) || 0;
            if (Math.abs(cashAmt + onlineAmt - grandTotal) > 0.5) {
                showToast('Split amounts must add up to total bill.', '#ef4444');
                return;
            }
        }
    }

    isSavingSale = true;
    const saveBtn = document.getElementById('btn-save-scanned-sell');
    if (saveBtn) saveBtn.disabled = true;
    try {
        const res = await fetch('/api/sale_bill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ header, items, mode: effectiveMode })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`Sale saved (${items.length} items)`);
            await renderSaleReceipt(header, scannedItems.slice(), header.discount, data.sale_id);
            printSaleReceipt();
            clearScannedItems();
            document.getElementById('f-sale-date').value = todayLocalDate();
            // Clear split fields
            document.getElementById('f-cash-amount').value = '';
            document.getElementById('f-online-amount').value = '';
            document.getElementById('split-payment-fields').style.display = 'none';
            document.getElementById('f-payment-mode').value = 'Cash';
            // Clear credit advance field
            document.getElementById('f-credit-advance-amount').value = '';
            autoFillBillNo();
            if (effectiveMode === 'credit') {
                loadSalesBorrow();
            }
            // Dashboard KPIs depend on both cash/credit totals, so refresh either way
            loadDashboard();
            // loadSellStats() only pulls the SQL-aggregate totals for the
            // Sell Stats cards -- see the matching note in
            // modules/purchases/entry.js for why loadSellEntries() (full
            // 310k+ row fetch) isn't called here unconditionally anymore.
            if (document.getElementById('analyze-panel')?.style?.display !== 'none') {
                loadSellStats();
            }
        } else {
            showToast(data.msg || 'Error saving sale', '#ef4444');
        }
    } catch (e) {
        showToast('Server error', '#ef4444');
    } finally {
        isSavingSale = false;
        if (saveBtn) saveBtn.disabled = false;
    }
}