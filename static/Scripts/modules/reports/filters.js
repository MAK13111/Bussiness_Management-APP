// =========================================================================
// modules/reports/filters.js
// Shared date-range filters for the Reports tab, plus the "Bills
// (date wise)" lists shown inside the Reports section for both
// purchases and sales.
// =========================================================================

function setReportDate(period) {
  const today = new Date();
  let from = new Date(today);
  let to = new Date(today);
  if (period === 'today') {
    // keep as today
  } else if (period === 'yesterday') {
    from.setDate(from.getDate() - 1);
    to = new Date(from);
  } else if (period === 'week') {
    from.setDate(from.getDate() - from.getDay());
    to = new Date(today);
  } else if (period === 'month') {
    from.setDate(1);
    to = new Date(today);
  } else if (period === 'lastmonth') {
    from.setMonth(from.getMonth() - 1);
    from.setDate(1);
    to = new Date(from.getFullYear(), from.getMonth() + 1, 0);
  }
  document.getElementById('report-date-from').value = from.toISOString().slice(0, 10);
  document.getElementById('report-date-to').value = to.toISOString().slice(0, 10);
  applyReportFilters();
}

function getReportFilterParams() {
  const from = document.getElementById('report-date-from')?.value || '';
  const to = document.getElementById('report-date-to')?.value || '';
  const party = document.getElementById('report-search-party')?.value.trim() || '';
  const bill = document.getElementById('report-search-bill')?.value.trim() || '';
  const product = document.getElementById('report-search-product')?.value.trim() || '';
  const payment = document.getElementById('report-payment-type')?.value || '';
  const sort = document.getElementById('report-sort')?.value || 'date_desc';

  const params = new URLSearchParams();
  if (from) params.append('date_from', from);
  if (to) params.append('date_to', to);
  if (party) params.append('party', party);
  if (bill) params.append('invoice_no', bill);
  if (product) params.append('item', product);
  if (payment) params.append('payment_type', payment);
  if (sort) params.append('sort', sort);
  return params;
}

function applyReportFilters() {
  const params = getReportFilterParams();

  // Determine which report tab is active
  const activeTab = document.querySelector('.analyze-tab.active');
  if (activeTab && activeTab.id === 'atab-purchases') {
    loadReportPurchaseBills(params);
  } else if (activeTab && activeTab.id === 'atab-sells') {
    loadReportSaleBills(params);
  } else if (activeTab && activeTab.id === 'atab-replace') {
    loadReportReplaceBills(params);
  } else if (activeTab && activeTab.id === 'atab-deleted') {
    loadReportDeletedBills(params);
  }
}


function resetReportFilters() {
  document.getElementById('report-date-from').value = '';
  document.getElementById('report-date-to').value = '';
  document.getElementById('report-search-party').value = '';
  document.getElementById('report-search-bill').value = '';
  document.getElementById('report-search-product').value = '';
  document.getElementById('report-payment-type').value = '';
  document.getElementById('report-sort').value = 'date_desc';
  applyReportFilters();
}

// ─── CHUNKED RENDERER HELPER ──────────────────────────────────────────────
// Renders `items` into `wrapper` using `buildHtml(item)` for each element,
// but splits the work into chunks of `chunkSize` to keep the browser
// thread responsive.  The first chunk is painted synchronously (so the
// first 25 cards appear instantly); subsequent chunks are appended in
// successive ~16 ms setTimeout callbacks (one per animation frame).
//
// @param {HTMLElement} wrapper    - target container (cleared first)
// @param {Array}       items      - data items to render
// @param {Function}    buildHtml  - (item) => HTML string for one item
// @param {number}      chunkSize  - items per chunk (default 25)
function renderChunked(wrapper, items, buildHtml, chunkSize = 25) {
  wrapper.innerHTML = '';
  if (!items.length) return;

  // Paint first chunk synchronously so the user sees content instantly.
  const firstChunk = items.slice(0, chunkSize);
  wrapper.insertAdjacentHTML('beforeend', firstChunk.map(buildHtml).join(''));

  // Append remaining chunks one per setTimeout tick (~16ms each).
  let offset = chunkSize;
  function appendNext() {
    if (offset >= items.length) return;
    const chunk = items.slice(offset, offset + chunkSize);
    wrapper.insertAdjacentHTML('beforeend', chunk.map(buildHtml).join(''));
    offset += chunkSize;
    if (offset < items.length) setTimeout(appendNext, 16);
  }
  if (items.length > chunkSize) setTimeout(appendNext, 16);
}

// ─── REPORT - PURCHASE BILLS LIST ─────────────────────────────────────────

let rpbAllRows = [];
let rpbPage = 1;
let rpbTotal = 0;
let rpbLastParams = null; // filters currently in effect, reused across page changes
let rpbBillsByUid = {}; // uid -> grouped bill object, so Details can rebuild the breakdown without a re-fetch
const REPORT_BILLS_PAGE_SIZE = 100;

// Only the current page's rows are ever held/rendered -- moving to another
// page (Prev/Next or typing a page number) replaces them, it doesn't
// accumulate pages on top of each other.
// reset=true (default): fresh search/filter -- goes back to page 1.
// reset=false: internal use when jumping directly to a specific page.
async function loadReportPurchaseBills(params, reset = true) {
  if (reset) { rpbPage = 1; rpbLastParams = params; }
  const p = new URLSearchParams(rpbLastParams ? rpbLastParams.toString() : '');
  p.set('page', rpbPage);
  p.set('limit', REPORT_BILLS_PAGE_SIZE);
  const url = '/api/reports/purchases?' + p.toString();

  showPageLoader('rpb-bills-wrapper', rpbAllRows.length || REPORT_BILLS_PAGE_SIZE);

  try {
    const res = await fetch(url);
    const data = await res.json();
    // /api/reports/purchases returns {entries,total,page,limit} when
    // page & limit are passed, same convention as /api/items.
    const rows = data.entries !== undefined ? data.entries : data;
    rpbTotal = data.total !== undefined ? data.total : rows.length;
    rpbAllRows = rows;
    renderReportPurchaseBills(rpbAllRows);
    renderPaginationBar('rpb-pagination', rpbPage, REPORT_BILLS_PAGE_SIZE, rpbTotal, gotoReportPurchaseBillsPage);
  } catch (e) {
    console.error('Error loading purchase reports:', e);
  } finally {
    hidePageLoader('rpb-bills-wrapper');
  }
}

async function gotoReportPurchaseBillsPage(page) {
  rpbPage = page;
  await loadReportPurchaseBills(rpbLastParams, false);
}

function renderReportPurchaseBills(rows) {
  // Collapsed header shows only basic info; clicking it expands the
  // detailed item table (Sold/Remaining columns), same data as the
  // Purchases tab "Bills (date wise)" panel. No edit button here.
  const wrapper = document.getElementById('rpb-bills-wrapper');
  const emptyEl = document.getElementById('rpb-empty');
  if (!rows.length) {
    if (wrapper) wrapper.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  // Group by purchase_id (primary key) to ensure each bill is unique
  const groups = new Map();
  rows.forEach(e => {
    const pid = e.purchase_id;
    if (!groups.has(pid)) {
      groups.set(pid, {
        purchase_id: pid,
        invoiceNo: e.invoice_no || e.invoiceNo || '',
        party: e.party || '',
        sellerNo: e.seller_no || e.sellerNo || '',
        sellerAddress: e.seller_address || e.sellerAddress || '',
        sellerGstNo: e.seller_gst_no || e.sellerGstNo || '',
        date: e.date || '',
        department: e.department || '',
        status: e.status || '',
        cgst: parseFloat(e.cgst) || 0,
        sgst: parseFloat(e.sgst) || 0,
        igst: parseFloat(e.igst) || 0,
        discountPct: parseFloat(e.discount) || 0,
        totalAfterDiscount: parseFloat(e.totalAfterDiscount) || 0,
        totalWithGST: parseFloat(e.totalWithGST) || 0,
        paidAmount: parseFloat(e.paidAmount) || 0,
        remainingAmount: parseFloat(e.remainingAmount) || 0,
        items: []
      });
    }
    groups.get(pid).items.push(e);
  });

  // Build an ordered array of bill objects for chunked rendering.
  const billList = Array.from(groups.values());

  renderChunked(wrapper, billList, (bill) => {
    const grandTotal = bill.items.reduce((s, i) => s + (parseFloat(i.buyTotal) || 0), 0);
    const totalQty = bill.items.reduce((s, i) => s + (parseInt(i.qty) || 0), 0);
    const totalSold = bill.items.reduce((s, i) => s + (parseInt(i.sold) || 0), 0);
    const dateFormatted = bill.date ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
    const uid = 'rpb-' + bill.purchase_id;
    rpbBillsByUid[uid] = bill;

    const itemRows = bill.items.map((itm, idx) => {
      const remaining = Math.max(0, (itm.qty || 0) - (+itm.sold || 0));
      const remainPct = itm.qty > 0 ? Math.round((remaining / itm.qty) * 100) : 0;
      const stockColor = remainPct > 50 ? '#4ade80' : remainPct > 20 ? '#fbbf24' : '#f87171';
      return `
        <tr class="pb-item-row">
          <td class="pb-td pb-td-center pb-td-idx">${idx + 1}</td>
          <td class="pb-td pb-td-name">${itm.item || '—'}</td>
          <td class="pb-td pb-td-center pb-td-size">${itm.size || '—'}</td>
          <td class="pb-td pb-td-center">${itm.qty}</td>
          <td class="pb-td pb-td-center pb-td-sold">${+itm.sold || 0}</td>
          <td class="pb-td pb-td-center">
            <span class="pb-remaining-badge" style="color:${stockColor}; border-color:${stockColor}22; background:${stockColor}11;">
              ${remaining}
            </span>
          </td>
          <td class="pb-td pb-td-right pb-td-rate">${fmt(itm.buy)}</td>
          <td class="pb-td pb-td-center" style="font-weight:600; color:#818cf8;">${itm.margin != null ? itm.margin + '%' : '0%'}</td>
          <td class="pb-td pb-td-right pb-td-total">${fmt(itm.buyTotal)}</td>
        </tr>
      `;
    }).join('');

    // Same purchase_payments-derived GST total as the Purchases tab panel
    // (routes/purchases.py joins it into every row of a bill).
    const grandTotalWithGST = parseFloat(bill.items[0]?.totalWithGST) || grandTotal;

    return buildInvoiceCardHTML({
      prefix: 'pb',
      uid,
      headerLabel: 'Invoice',
      headerNo: `#${bill.invoiceNo || 'N/A'}`,
      subInfo: [{ icon: 'building-store', text: bill.party || '—' }],
      chips: [
        { icon: 'calendar', text: dateFormatted },
        { icon: 'package', text: `${bill.items.length} item${bill.items.length !== 1 ? 's' : ''}`, className: 'pb-items-chip' },
        { icon: 'currency-rupee', text: fmt(grandTotal), style: 'font-weight:700;color:var(--color-text-primary)' },
      ],
      tableHeaders: [
        { label: '#', align: 'center', width: '36px' },
        { label: 'Item' },
        { label: 'Size', align: 'center' },
        { label: 'Qty', align: 'center' },
        { label: 'Sold', align: 'center' },
        { label: 'Remaining', align: 'center' },
        { label: 'Rate', align: 'right' },
        { label: 'Margin', align: 'center' },
        { label: 'Total', align: 'right' },
      ],
      itemRowsHtml: itemRows,
      footerStats: [
        { label: 'Total Qty', value: totalQty },
        { label: 'Sold', value: totalSold },
        { label: 'Remaining', value: totalQty - totalSold },
      ],
      totalLabel: 'Grand Total',
      totalAmount: fmt(grandTotal),
      totalWithGSTAmount: fmt(grandTotalWithGST),
      footerButtons: [
        { icon: 'file-text', label: 'Details', title: 'View full bill details', onclick: `showReportPurchaseBillDetail('${uid}')` },
        { icon: 'barcode', label: 'Show Barcode', title: 'Show barcodes', onclick: `showBillBarcodes(${bill.purchase_id})` },
        {
          icon: 'trash',
          label: 'Delete',
          title: totalSold > 0 ? 'Cannot delete: items of this bill have been sold' : 'Delete bill',
          onclick: `deletePurchaseBill(${bill.purchase_id})`,
          dull: totalSold > 0,
          disabledMessage: 'Not able to delete this bill because one or more items of this bill have been sold.'
        },
      ],
    });
  });
}


async function showReportPurchaseBillDetail(uid) {
  const bill = rpbBillsByUid[uid];
  if (!bill) { showToast('Could not find that bill', '#dc2626'); return; }

  let shopInfo = {};
  try { shopInfo = await fetch('/api/shop_settings').then(r => r.json()); } catch (e) { /* ignore — detail still works without shop info */ }

  const html = buildPurchaseBillDetailHTML(shopInfo, bill);
  openBillPreviewModal(html, `Invoice #${bill.invoiceNo || bill.purchase_id}`);
}



// ─── REPORT - SALE BILLS LIST ─────────────────────────────────────────

let rsbAllRows = [];
let rsbPage = 1;
let rsbTotal = 0;
let rsbLastParams = null; // filters currently in effect, reused across page changes
let rsbBillsByUid = {}; // uid -> grouped bill object, so Show Bill can rebuild the receipt without a re-fetch

// Only the current page's rows are ever held/rendered -- moving to another
// page (Prev/Next or typing a page number) replaces them, it doesn't
// accumulate pages on top of each other.
// reset=true (default): fresh search/filter -- goes back to page 1.
// reset=false: internal use when jumping directly to a specific page.
async function loadReportSaleBills(params, reset = true) {
  if (reset) { rsbPage = 1; rsbLastParams = params; }
  const p = new URLSearchParams(rsbLastParams ? rsbLastParams.toString() : '');
  p.set('page', rsbPage);
  p.set('limit', REPORT_BILLS_PAGE_SIZE);
  const url = '/api/reports/sales?' + p.toString();

  showPageLoader('rsb-bills-wrapper', rsbAllRows.length || REPORT_BILLS_PAGE_SIZE);

  try {
    const res = await fetch(url);
    const data = await res.json();
    const rows = data.entries !== undefined ? data.entries : data;
    rsbTotal = data.total !== undefined ? data.total : rows.length;
    rsbAllRows = rows;
    renderReportSaleBills(rsbAllRows);
    renderPaginationBar('rsb-pagination', rsbPage, REPORT_BILLS_PAGE_SIZE, rsbTotal, gotoReportSaleBillsPage);
  } catch (e) {
    console.error('Error loading sale reports:', e);
  } finally {
    hidePageLoader('rsb-bills-wrapper');
  }
}

async function gotoReportSaleBillsPage(page) {
  rsbPage = page;
  await loadReportSaleBills(rsbLastParams, false);
}

function renderReportSaleBills(rows) {
  // Collapsed header shows only basic info; clicking it expands the
  // detailed item table, same data as the Sales tab "Bills (date wise)"
  // panel. No edit button here.
  const wrapper = document.getElementById('rsb-bills-wrapper');
  const emptyEl = document.getElementById('rsb-empty');
  if (!rows.length) {
    if (wrapper) wrapper.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  // Group by sale_id (primary key).
  const groups = new Map();
  rows.forEach(e => {
    const sid = e.sale_id;
    if (!groups.has(sid)) {
      groups.set(sid, {
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
    groups.get(sid).items.push(e);
  });

  // Payment mode badge color
  const payColor = { Cash: '#4ade80', Online: '#818cf8', Split: '#fbbf24', Credit: '#f87171' };

  const saleBillList = Array.from(groups.values());

  renderChunked(wrapper, saleBillList, (bill) => {
    const grandTotal = bill.items.reduce((s, i) => s + (parseFloat(i.sellTotal) || 0), 0);
    const totalQty = bill.items.reduce((s, i) => s + (parseInt(i.qty) || 0), 0);
    const dateFormatted = bill.date
      ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
      : '—';
    const pColor = payColor[bill.paymentMode] || 'var(--color-text-secondary)';
    const uid = 'rsb-' + bill.sale_id;
    rsbBillsByUid[uid] = bill;
    const pmLower = (bill.paymentMode || '').toLowerCase();

    const itemRows = bill.items.map((itm, idx) => `
      <tr class="sb-item-row">
        <td class="sb-td sb-td-center sb-td-idx">${idx + 1}</td>
        <td class="sb-td sb-td-name">${itm.item || '—'}</td>
        <td class="sb-td sb-td-center sb-td-size">${itm.size || '—'}</td>
        <td class="sb-td sb-td-center">${itm.qty}</td>
        <td class="sb-td sb-td-right sb-td-rate">${fmt(itm.sellUnit)}</td>
        <td class="sb-td sb-td-right sb-td-total">${fmt(itm.sellTotal)}</td>
      </tr>`).join('');

    const pmBg = pmLower === 'cash' ? '4ade80' : pmLower.includes('credit') ? 'f87171' : '60a5fa';
    const subInfo = [{ icon: 'user', text: bill.customerName || 'Walk-in Customer' }];
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
          style: `color:${pColor}; border-color:${pColor}33; background:#${pmBg}12;`,
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
        { label: 'Payment', value: bill.paymentMode || '—', style: `color:${pColor};` },
      ],
      totalLabel: 'Grand Total',
      totalAmount: fmt(grandTotal),
      footerButtons: [
        { icon: 'file-text', label: 'Details', title: 'View full bill details', onclick: `showReportSaleBillDetail('${uid}')` },
        { icon: 'printer', label: 'Show Bill', title: 'Show bill', onclick: `showReportSaleBillReceipt('${uid}')` },
      ],
    });
  });
}

// Opens the centered bill-preview modal with a full breakdown of one sale
// bill loaded in this report list -- subtotal, discount, grand total,
// payment mode/split, and paid/remaining for Credit or Partial bills.
async function showReportSaleBillDetail(uid) {
  const bill = rsbBillsByUid[uid];
  if (!bill) { showToast('Could not find that bill', '#dc2626'); return; }

  let shopInfo = {};
  try { shopInfo = await fetch('/api/shop_settings').then(r => r.json()); } catch (e) { /* ignore — detail still works without shop info */ }

  const html = buildSaleBillDetailHTML(shopInfo, bill);
  openBillPreviewModal(html, `Bill #${bill.billNo || bill.sale_id}`);
}

// Opens the centered bill-preview modal for a bill already loaded in this
// report list, reusing the same receipt template the scan-sell flow prints
// from (buildReceiptHTML in modules/sales/receipt.js). The bill is only
// shown for review here — printing happens separately, only if the
// "Print" button inside the modal is clicked (see ui/billPreview.js).
async function showReportSaleBillReceipt(uid) {
  const bill = rsbBillsByUid[uid];
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



// ─── REPORT - REPLACE BILLS LIST ─────────────────────────────────────────

let rrbAllRows = [];

async function loadReportReplaceBills(params) {
  const url = '/api/reports/replace_bills?' + (params ? params.toString() : '');
  try {
    const res = await fetch(url);
    const rows = await res.json();
    rrbAllRows = rows;
    renderReportReplaceBills(rows);
  } catch (e) {
    console.error('Error loading replace bill reports:', e);
  }
}

function renderReportReplaceBills(rows) {
  // Same card style as Sale Bills, expanded to show the Returned (old)
  // and New-item-given tables plus the price difference.
  const wrapper = document.getElementById('rrb-bills-wrapper');
  const emptyEl = document.getElementById('rrb-empty');
  if (!rows.length) {
    if (wrapper) wrapper.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  renderChunked(wrapper, rows, (bill) => {
    const oldItems = (bill.items || []).filter(i => i.side === 'old');
    const newItems = (bill.items || []).filter(i => i.side === 'new');
    const totalItems = oldItems.length + newItems.length;
    const dateFormatted = bill.date
      ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
      : '—';
    const diff = +bill.difference || 0;
    const diffColor = diff > 0 ? '#f87171' : (diff < 0 ? '#4ade80' : 'var(--color-text-secondary)');
    const diffLabel = diff > 0 ? 'Customer Pays' : (diff < 0 ? 'Shop Refunds' : 'No Difference');
    const uid = 'rrb-' + bill.id;

    const buildRows = (items) => items.map((itm, idx) => `
      <tr class="sb-item-row">
        <td class="sb-td sb-td-center sb-td-idx">${idx + 1}</td>
        <td class="sb-td sb-td-name">${itm.item || '—'}</td>
        <td class="sb-td sb-td-center sb-td-size">${itm.size || '—'}</td>
        <td class="sb-td sb-td-center">${itm.qty}</td>
        <td class="sb-td sb-td-right sb-td-rate">${fmt(itm.sell_price)}</td>
        <td class="sb-td sb-td-right sb-td-total">${fmt(itm.sell_total)}</td>
      </tr>`).join('');

    return `
      <div class="sb-invoice-card">
        <div class="sb-invoice-header" style="cursor:pointer" onclick="toggleBillDetail('${uid}')">
          <div class="sb-invoice-header-left">
            <div class="sb-invoice-no-wrap">
              <span class="sb-invoice-label">Replace</span>
              <span class="sb-invoice-no">#${bill.replaceBillNo || 'N/A'}</span>
            </div>
            <div class="sb-customer-wrap">
              <i class="ti ti-user" style="color:var(--color-text-tertiary); font-size:13px;"></i>
              <span class="sb-customer-name">${bill.customerName || 'Walk-in Customer'}</span>
            </div>
            ${bill.customerNo ? `
            <div class="sb-customer-wrap">
              <i class="ti ti-phone" style="color:var(--color-text-tertiary); font-size:12px;"></i>
              <span style="font-size:12px; color:var(--color-text-secondary);">${bill.customerNo}</span>
            </div>` : ''}
          </div>
          <div class="sb-invoice-header-right">
            <span class="sb-meta-chip"><i class="ti ti-calendar"></i>${dateFormatted}</span>
            <span class="sb-meta-chip sb-pm-chip" style="color:${diffColor}; border-color:${diffColor}33; background:${diffColor}12;">
              <i class="ti ti-replace"></i>${diffLabel}
            </span>
            <span class="sb-meta-chip sb-items-chip"><i class="ti ti-package"></i>${totalItems} item${totalItems !== 1 ? 's' : ''}</span>
            <span class="sb-meta-chip" style="font-weight:700;color:${diffColor}"><i class="ti ti-currency-rupee"></i>${diff > 0 ? '+' : ''}${fmt(diff)}</span>
            <button onclick="event.stopPropagation();toggleBillDetail('${uid}')" id="btn-${uid}" style="background:none;border:none;color:var(--color-accent);cursor:pointer;padding:2px 4px;font-size:16px" title="View details"><i class="ti ti-chevron-down"></i></button>
          </div>
        </div>
        <div id="${uid}" style="display:none">
          ${oldItems.length ? `
          <div style="padding:8px 12px 0;font-size:11px;font-weight:600;color:var(--color-text-tertiary);text-transform:uppercase;letter-spacing:.5px"><i class="ti ti-arrow-back-up"></i> Returned Items</div>
          <div class="sb-table-wrap">
            <table class="sb-table">
              <thead><tr><th class="sb-th sb-th-center" style="width:36px">#</th><th class="sb-th">Item</th><th class="sb-th sb-th-center">Size</th><th class="sb-th sb-th-center">Qty</th><th class="sb-th sb-th-right">Rate</th><th class="sb-th sb-th-right">Total</th></tr></thead>
              <tbody>${buildRows(oldItems)}</tbody>
            </table>
          </div>` : ''}
          ${newItems.length ? `
          <div style="padding:8px 12px 0;font-size:11px;font-weight:600;color:var(--color-text-tertiary);text-transform:uppercase;letter-spacing:.5px"><i class="ti ti-arrow-forward-up"></i> New Items Given</div>
          <div class="sb-table-wrap">
            <table class="sb-table">
              <thead><tr><th class="sb-th sb-th-center" style="width:36px">#</th><th class="sb-th">Item</th><th class="sb-th sb-th-center">Size</th><th class="sb-th sb-th-center">Qty</th><th class="sb-th sb-th-right">Rate</th><th class="sb-th sb-th-right">Total</th></tr></thead>
              <tbody>${buildRows(newItems)}</tbody>
            </table>
          </div>` : ''}
          <div class="sb-invoice-footer">
            <div class="sb-footer-stats">
              <span class="sb-footer-stat">
                <span class="sb-footer-stat-label">Old Total</span>
                <span class="sb-footer-stat-val">${fmt(bill.oldTotal)}</span>
              </span>
              <span class="sb-footer-divider"></span>
              <span class="sb-footer-stat">
                <span class="sb-footer-stat-label">New Total</span>
                <span class="sb-footer-stat-val">${fmt(bill.newTotal)}</span>
              </span>
              <span class="sb-footer-divider"></span>
              <span class="sb-footer-stat">
                <span class="sb-footer-stat-label">Total Replace Price</span>
                <span class="sb-footer-stat-val">${fmt((+bill.oldTotal || 0) + (+bill.newTotal || 0))}</span>
              </span>
              ${bill.note ? `<span class="sb-footer-divider"></span><span class="sb-footer-stat"><span class="sb-footer-stat-label">Note</span><span class="sb-footer-stat-val">${bill.note}</span></span>` : ''}
            </div>
            <div class="sb-invoice-total">
              <span class="sb-total-label">${diffLabel}</span>
              <span class="sb-total-amount" style="color:${diffColor}">${diff > 0 ? '+' : ''}${fmt(diff)}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  });
}

// ─── REPORT - DELETED BILLS LIST ──────────────────────────────────────────

let rdbPage = 1;
let rdbTotal = 0;
let rdbLastParams = null;

async function loadReportDeletedBills(params, reset = true) {
  if (reset) { rdbPage = 1; rdbLastParams = params; }
  const p = new URLSearchParams(rdbLastParams ? rdbLastParams.toString() : '');
  p.set('page', rdbPage);
  p.set('limit', REPORT_BILLS_PAGE_SIZE);
  const url = '/api/reports/deleted_purchases?' + p.toString();

  showPageLoader('rdb-bills-wrapper', REPORT_BILLS_PAGE_SIZE);

  try {
    const res = await fetch(url);
    const data = await res.json();
    const rows = data.entries || [];
    rdbTotal = data.total !== undefined ? data.total : rows.length;

    renderReportDeletedBills(rows);
    const infoEl = document.getElementById('rdb-result-info');
    if (infoEl) {
      infoEl.style.display = rdbTotal > 0 ? '' : 'none';
      infoEl.textContent = `Total ${rdbTotal} deleted bill${rdbTotal === 1 ? '' : 's'}`;
    }
    renderPaginationBar('rdb-pagination', rdbPage, REPORT_BILLS_PAGE_SIZE, rdbTotal, gotoReportDeletedBillsPage);
  } catch (e) {
    console.error('Error loading deleted bills:', e);
  } finally {
    hidePageLoader('rdb-bills-wrapper');
  }
}

async function gotoReportDeletedBillsPage(page) {
  rdbPage = page;
  await loadReportDeletedBills(rdbLastParams, false);
}

function renderReportDeletedBills(rows) {
  const wrapper = document.getElementById('rdb-bills-wrapper');
  const emptyEl = document.getElementById('rdb-empty');
  if (!rows.length) {
    if (wrapper) wrapper.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  const groups = new Map();
  rows.forEach(e => {
    const pid = e.purchase_id;
    if (!groups.has(pid)) {
      groups.set(pid, {
        purchase_id: pid,
        invoiceNo: e.invoice_no || '',
        party: e.party || '',
        date: e.date || '',
        items: []
      });
    }
    groups.get(pid).items.push(e);
  });

  const billList = Array.from(groups.values());

  renderChunked(wrapper, billList, (bill) => {
    const grandTotal = bill.items.reduce((s, i) => s + (parseFloat(i.buyTotal) || 0), 0);
    const totalQty = bill.items.reduce((s, i) => s + (parseInt(i.qty) || 0), 0);
    const dateFormatted = bill.date ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
    const uid = 'rdb-' + bill.purchase_id;

    const itemRows = bill.items.map((itm, idx) => `
      <tr class="pb-item-row" style="opacity: 0.8;">
        <td class="pb-td pb-td-center pb-td-idx">${idx + 1}</td>
        <td class="pb-td pb-td-name">${itm.item || '—'}</td>
        <td class="pb-td pb-td-center pb-td-size">${itm.size || '—'}</td>
        <td class="pb-td pb-td-center">${itm.qty}</td>
        <td class="pb-td pb-td-right pb-td-rate">${fmt(itm.buy)}</td>
        <td class="pb-td pb-td-right pb-td-total">${fmt(itm.buyTotal)}</td>
      </tr>
    `).join('');

    return buildInvoiceCardHTML({
      prefix: 'pb',
      uid,
      headerLabel: 'DELETED INVOICE',
      headerNo: `#${bill.invoiceNo || bill.purchase_id}`,
      subInfo: [{ icon: 'building-store', text: bill.party || '—' }],
      chips: [
        { icon: 'calendar', text: dateFormatted },
        { icon: 'package', text: `${bill.items.length} item${bill.items.length !== 1 ? 's' : ''}`, className: 'pb-items-chip' },
        { icon: 'trash', text: 'DELETED', style: 'background:rgba(239,68,68,0.12);color:#ef4444;border-color:rgba(239,68,68,0.3);font-weight:700' },
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
        { label: 'Total Qty', value: totalQty },
        { label: 'Status', value: '<span style="color:#ef4444;font-weight:600">Deleted</span>' },
      ],
      totalLabel: 'Original Total',
      totalAmount: fmt(grandTotal),
      footerButtons: [],
    });
  });
}


