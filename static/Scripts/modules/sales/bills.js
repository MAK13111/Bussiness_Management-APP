// =========================================================================
// modules/sales/bills.js
// Sale "Bills (date wise)" panel: loading and rendering bills for the
// selected mode (cash/credit), plus filtering.
//
// Paginated in pages of 100 bills (the server pages over `sales` rows,
// then attaches each page's items) instead of fetching every matching row
// in one go -- on a shop with thousands of bills, that single unbounded
// fetch+render was the main cause of this panel (and the rest of the app,
// while it was still rendering) feeling laggy.
//
// Only the current page's rows are ever held/rendered -- moving to another
// page (Prev/Next or typing a page number) replaces them, it doesn't
// accumulate pages on top of each other.
// =========================================================================

let sbMode = 'cash';
let sbRows = [];
let sbPage = 1;
let sbTotal = 0;
let sbLastParams = null; // date filters currently in effect, reused across page changes
let sbBillsByUid = {}; // uid -> grouped bill object, so Show Bill can rebuild the receipt without a re-fetch
const SB_PAGE_SIZE = 100;

function switchSaleBillsMode(mode) {
  sbMode = mode;
  document.getElementById('sb-mode-cash').classList.toggle('active', mode === 'cash');
  document.getElementById('sb-mode-credit').classList.toggle('active', mode === 'credit');
  loadSaleBills();
}

// reset=true (default): fresh open/filter -- goes back to page 1.
// reset=false: internal use when jumping directly to a specific page.
async function loadSaleBills(params, reset = true) {
  if (reset) { sbPage = 1; sbLastParams = params; sbTotal = 0; }
  const p = new URLSearchParams(sbLastParams ? sbLastParams.toString() : '');
  p.set('type', 'sell');
  p.set('mode', sbMode);
  p.set('page', sbPage);
  p.set('limit', SB_PAGE_SIZE);
  if (!reset && sbTotal > 0) p.set('total', sbTotal);

  // Show skeleton loader after 250ms if the fetch is slow
  showPageLoader('sb-bills-wrapper', sbRows.length || SB_PAGE_SIZE);

  try {
    const res = await fetch('/api/entries?' + p.toString());
    const data = await res.json();
    // /api/entries returns {entries,total,page,limit} when page & limit are
    // passed, same convention as /api/reports/sales and /api/items.
    const rows = data.entries !== undefined ? data.entries : data;
    sbTotal = data.total !== undefined ? data.total : rows.length;
    sbRows = rows;
    renderSaleBills(sbRows);
    renderPaginationBar('sb-pagination', sbPage, SB_PAGE_SIZE, sbTotal, gotoSaleBillsPage);
  } catch (e) {
    console.error('Error loading sale bills:', e);
  } finally {
    hidePageLoader('sb-bills-wrapper');
  }
}

async function gotoSaleBillsPage(page) {
  sbPage = page;
  await loadSaleBills(sbLastParams, false);
}

function renderSaleBills(rows) {
  const wrapper = document.getElementById('sb-bills-wrapper');
  const emptyEl = document.getElementById('sb-empty');
  if (!rows.length) {
    if (wrapper) wrapper.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  // Group by sale_id (primary key), same as Reports panel.
  const groups = new Map();
  rows.forEach(e => {
    const sid = e.sale_id;
    const key = sid != null ? sid : (e.bill_no || e.billNo || '') + '|' + (e.date + '|' + (e.customer_name || e.customerName || ''));
    if (!groups.has(key)) {
      groups.set(key, {
        sale_id: sid,
        billNo: e.bill_no || e.billNo || '',
        customerName: e.customer_name || e.customerName || '',
        customerNo: e.customer_no || e.customerNo || '',
        date: e.date || '',
        paymentMode: e.payment_mode || e.paymentMode || '',
        status: e.status || '',
        discountPct: parseFloat(e.discount) || 0,
        subTotal: parseFloat(e.subTotal) || 0,
        cashAmount: parseFloat(e.cashAmount) || 0,
        onlineAmount: parseFloat(e.onlineAmount) || 0,
        paidAmount: parseFloat(e.paidAmount) || 0,
        remainingAmount: parseFloat(e.remainingAmount) || 0,
        items: []
      });
    }
    groups.get(key).items.push(e);
  });

  // Payment mode badge color
  const payColor = { Cash: '#4ade80', Online: '#818cf8', Split: '#fbbf24', Credit: '#f87171' };

  wrapper.innerHTML = Array.from(groups.values()).map(bill => {
    const grandTotal = bill.items.reduce((s, i) => s + (parseFloat(i.sellTotal) || 0), 0);
    const totalQty   = bill.items.reduce((s, i) => s + (parseInt(i.qty)        || 0), 0);
    // Format date nicely, e.g. "29 Jun 2026"
    const dateFormatted = bill.date
      ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
      : '—';
    // Payment mode chip color: green for cash, blue for credit/UPI
    const pmLower = (bill.paymentMode || '').toLowerCase();
    const pmColor  = pmLower === 'cash' ? '#4ade80' : pmLower.includes('credit') ? '#f87171' : '#60a5fa';
    const pmBg     = pmLower === 'cash' ? '4ade80'  : pmLower.includes('credit') ? 'f87171'  : '60a5fa';

    const itemRows = bill.items.map((itm, idx) => `
      <tr class="sb-item-row">
        <td class="sb-td sb-td-center sb-td-idx">${idx + 1}</td>
        <td class="sb-td sb-td-name">${itm.item || '—'}</td>
        <td class="sb-td sb-td-center sb-td-size">${itm.size || '—'}</td>
        <td class="sb-td sb-td-center">${itm.qty}</td>
        <td class="sb-td sb-td-right sb-td-rate">${fmt(itm.sellUnit)}</td>
        <td class="sb-td sb-td-right sb-td-total">${fmt(itm.sellTotal)}</td>
      </tr>
    `).join('');

    const uid = 'sb-' + bill.sale_id;
    sbBillsByUid[uid] = bill;

    const subInfo = [{ icon: 'user', text: bill.customerName || 'Cash' }];
    if (bill.customerNo) subInfo.push({ icon: 'phone', size: '12px', text: bill.customerNo, textStyle: 'font-size:12px; color:var(--color-text-secondary);' });

    return buildInvoiceCardHTML({
      prefix: 'sb',
      uid,
      headerLabel: 'Bill',
      headerNo: `#${bill.billNo || 'N/A'}`,
      subInfo,
      chips: [
        { icon: 'calendar', text: dateFormatted },
        {
          icon: pmLower === 'cash' ? 'coin' : pmLower.includes('credit') ? 'credit-card' : 'device-mobile',
          text: bill.paymentMode || '—',
          className: 'sb-pm-chip',
          style: `color:${pmColor}; border-color:${pmColor}33; background:#${pmBg}12;`,
        },
        { icon: 'package', text: `${bill.items.length} item${bill.items.length !== 1 ? 's' : ''}`, className: 'sb-items-chip' },
        { icon: 'currency-rupee', text: fmt(grandTotal), style: 'font-weight:700;color:var(--color-text-primary)' },
      ],
      tableHeaders: [
        { label: '#', align: 'center', width: '36px' },
        { label: 'Item' },
        { label: 'Size', align: 'center' },
        { label: 'Qty', align: 'center' },
        { label: 'Rate', align: 'right' },
        { label: 'Total', align: 'right' },
      ],
      itemRowsHtml: itemRows,
      footerStats: [
        { label: 'Items Sold', value: totalQty },
        { label: 'Payment', value: bill.paymentMode || '—', style: `color:${pmColor};` },
      ],
      totalLabel: 'Grand Total',
      totalAmount: fmt(grandTotal),
      footerButtons: [
        { icon: 'file-text', label: 'Details', title: 'View full bill details', onclick: `showSaleBillDetail('${uid}')` },
        { icon: 'printer', label: 'Show Bill', title: 'Show bill', onclick: `showSaleBillReceipt('${uid}')` },
      ],
    });
  }).join('');
}

// Opens the centered bill-preview modal with a full breakdown of one sale
// bill already loaded in this panel -- subtotal, discount, grand total,
// payment mode/split, and paid/remaining for Credit or Partial bills.
// This is separate from "Show Bill" (which prints a thermal-style
// receipt); Details is for reviewing the numbers on screen.
async function showSaleBillDetail(uid) {
  const bill = sbBillsByUid[uid];
  if (!bill) { showToast('Could not find that bill', '#dc2626'); return; }

  let shopInfo = {};
  try { shopInfo = await fetch('/api/shop_settings').then(r => r.json()); } catch (e) { /* ignore — detail still works without shop info */ }

  const html = buildSaleBillDetailHTML(shopInfo, bill);
  openBillPreviewModal(html, `Bill #${bill.billNo || bill.sale_id}`);
}

// Opens the centered bill-preview modal for a bill already loaded in this
// list, reusing the same receipt template the scan-sell flow prints from
// (buildReceiptHTML in modules/sales/receipt.js) so a re-printed bill
// looks identical to the one handed over at time of sale. The bill is
// only shown for review here — printing happens separately, only if the
// "Print" button inside the modal is clicked (see ui/billPreview.js).
async function showSaleBillReceipt(uid) {
  const bill = sbBillsByUid[uid];
  if (!bill) { showToast('Could not find that bill', '#dc2626'); return; }

  let shopInfo = {};
  try { shopInfo = await fetch('/api/shop_settings').then(r => r.json()); } catch (e) { /* ignore — receipt still works without shop info */ }

  const header = {
    bill_no: bill.billNo,
    date: bill.date,
    customer_name: bill.customerName,
    customer_no: bill.customerNo,
    payment_mode: bill.paymentMode,
  };
  const items = bill.items.map(it => ({
    item: it.item, size: it.size, qty: it.qty, sell_unit: it.sellUnit
  }));
  const html = buildReceiptHTML(shopInfo, header, items, 0, bill.sale_id);

  openBillPreviewModal(html, `Bill #${bill.billNo || bill.sale_id}`, true);
}

// Date filters are sent to the server (instead of filtering only whatever
// page happens to already be loaded in the browser) so the range matches
// against the whole dataset, same approach as the Reports tab's bill lists.
async function applySaleBillsFilter() {
  const from = document.getElementById('sb-date-from').value;
  const to = document.getElementById('sb-date-to').value;
  const params = new URLSearchParams(sbLastParams ? sbLastParams.toString() : '');
  if (from) params.set('date_from', from); else params.delete('date_from');
  if (to) params.set('date_to', to); else params.delete('date_to');
  await loadSaleBills(params, true);
  const infoEl = document.getElementById('sb-result-info');
  if (from || to) {
    infoEl.style.display = '';
    infoEl.textContent = `Showing ${sbTotal} matching bill${sbTotal === 1 ? '' : 's'}`;
  } else {
    infoEl.style.display = 'none';
  }
}

async function resetSaleBillsFilter() {
  document.getElementById('sb-date-from').value = '';
  document.getElementById('sb-date-to').value = '';
  document.getElementById('sb-result-info').style.display = 'none';
  const params = new URLSearchParams(sbLastParams ? sbLastParams.toString() : '');
  params.delete('date_from');
  params.delete('date_to');
  await loadSaleBills(params, true);
}
