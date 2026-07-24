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
    document.getElementById('report-date-from').value = from.toISOString().slice(0,10);
    document.getElementById('report-date-to').value = to.toISOString().slice(0,10);
    applyReportFilters();
}

function applyReportFilters() {
    const from = document.getElementById('report-date-from').value;
    const to = document.getElementById('report-date-to').value;
    const party = document.getElementById('report-search-party').value.trim();
    const bill = document.getElementById('report-search-bill').value.trim();
    const product = document.getElementById('report-search-product').value.trim();
    const payment = document.getElementById('report-payment-type').value;
    const sort = document.getElementById('report-sort').value;

    const params = new URLSearchParams();
    if (from) params.append('date_from', from);
    if (to) params.append('date_to', to);
    if (party) params.append('party', party);
    if (bill) params.append('invoice_no', bill);
    if (product) params.append('item', product);
    if (payment) params.append('payment_type', payment);
    if (sort) params.append('sort', sort);

    // Determine which report tab is active
    const activeTab = document.querySelector('.analyze-tab.active');
    if (activeTab && activeTab.id === 'atab-purchases') {
        loadReportPurchaseBills(params);
    } else if (activeTab && activeTab.id === 'atab-sells') {
        loadReportSaleBills(params);
    } else if (activeTab && activeTab.id === 'atab-replace') {
        loadReportReplaceBills(params);
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

// ─── REPORT - PURCHASE BILLS LIST ─────────────────────────────────────────

let rpbMode = 'cash';
let rpbAllRows = [];
let rpbPage = 1;
let rpbTotal = 0;
let rpbLastParams = null; // filters currently in effect, reused across page changes
const REPORT_BILLS_PAGE_SIZE = 100;

function switchReportPurchaseBillsMode(mode) {
  rpbMode = mode;
  document.getElementById('rpb-mode-cash').classList.toggle('active', mode === 'cash');
  document.getElementById('rpb-mode-credit').classList.toggle('active', mode === 'credit');
  loadReportPurchaseBills();
}

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
        date: e.date || '',
        department: e.department || '',
        items: []
      });
    }
    groups.get(pid).items.push(e);
  });

  wrapper.innerHTML = Array.from(groups.values()).map(bill => {
    const grandTotal = bill.items.reduce((s, i) => s + (parseFloat(i.buyTotal) || 0), 0);
    const totalQty = bill.items.reduce((s, i) => s + (parseInt(i.qty) || 0), 0);
    const totalSold = bill.items.reduce((s, i) => s + (parseInt(i.sold) || 0), 0);
    const dateFormatted = bill.date ? new Date(bill.date).toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' }) : '—';
    const uid = 'rpb-' + bill.purchase_id;

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
          <td class="pb-td pb-td-right pb-td-total">${fmt(itm.buyTotal)}</td>
        </tr>
      `;
    }).join('');

    return `
      <div class="pb-invoice-card">
        <div class="pb-invoice-header" style="cursor:pointer" onclick="toggleBillDetail('${uid}')">
          <div class="pb-invoice-header-left">
            <div class="pb-invoice-no-wrap">
              <span class="pb-invoice-label">Invoice</span>
              <span class="pb-invoice-no">#${bill.invoiceNo || 'N/A'}</span>
            </div>
            <div class="pb-party-wrap">
              <i class="ti ti-building-store" style="color:var(--color-text-tertiary); font-size:13px;"></i>
              <span class="pb-party-name">${bill.party || '—'}</span>
            </div>
          </div>
          <div class="pb-invoice-header-right">
            <span class="pb-meta-chip"><i class="ti ti-calendar"></i>${dateFormatted}</span>
            <span class="pb-meta-chip pb-items-chip"><i class="ti ti-package"></i>${bill.items.length} item${bill.items.length !== 1 ? 's' : ''}</span>
            <span class="pb-meta-chip" style="font-weight:700;color:var(--color-text-primary)"><i class="ti ti-currency-rupee"></i>${fmt(grandTotal)}</span>
            <button onclick="event.stopPropagation();toggleBillDetail('${uid}')" id="btn-${uid}" style="background:none;border:none;color:var(--color-accent);cursor:pointer;padding:2px 4px;font-size:16px" title="View details"><i class="ti ti-chevron-down"></i></button>
          </div>
        </div>
        <div id="${uid}" style="display:none">
          <div class="pb-table-wrap">
            <table class="pb-table">
              <thead>
                <tr>
                  <th class="pb-th pb-th-center" style="width:36px">#</th>
                  <th class="pb-th">Item</th>
                  <th class="pb-th pb-th-center">Size</th>
                  <th class="pb-th pb-th-center">Qty</th>
                  <th class="pb-th pb-th-center">Sold</th>
                  <th class="pb-th pb-th-center">Remaining</th>
                  <th class="pb-th pb-th-right">Rate</th>
                  <th class="pb-th pb-th-right">Total</th>
                </tr>
              </thead>
              <tbody>${itemRows}</tbody>
            </table>
          </div>
          <div class="pb-invoice-footer">
            <div class="pb-footer-stats">
              <span class="pb-footer-stat"><span class="pb-footer-stat-label">Total Qty</span><span class="pb-footer-stat-val">${totalQty}</span></span>
              <span class="pb-footer-divider"></span>
              <span class="pb-footer-stat"><span class="pb-footer-stat-label">Sold</span><span class="pb-footer-stat-val">${totalSold}</span></span>
              <span class="pb-footer-divider"></span>
              <span class="pb-footer-stat"><span class="pb-footer-stat-label">Remaining</span><span class="pb-footer-stat-val">${totalQty - totalSold}</span></span>
            </div>
            <div class="pb-invoice-total">
              <span class="pb-total-label">Grand Total</span>
              <span class="pb-total-amount">${fmt(grandTotal)}</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;justify-self:end;">
              <button class="pb-footer-edit-btn" onclick="event.stopPropagation();showBillBarcodes(${bill.purchase_id})" title="Show barcodes">
                <i class="ti ti-barcode"></i> Show Barcode
              </button>
              <button class="pb-footer-edit-btn" onclick="event.stopPropagation();openPurchaseEdit(${bill.purchase_id})" title="Edit bill">
                <i class="ti ti-pencil"></i> Edit
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

async function applyReportPurchaseBillsFilter() {
  const from = document.getElementById('rpb-date-from').value;
  const to = document.getElementById('rpb-date-to').value;
  // Sent to the server (instead of filtering only the rows already
  // loaded in the browser) so the date range matches against the whole
  // dataset, not just whatever page happens to be on screen so far.
  const params = new URLSearchParams(rpbLastParams ? rpbLastParams.toString() : '');
  if (from) params.set('date_from', from); else params.delete('date_from');
  if (to) params.set('date_to', to); else params.delete('date_to');
  await loadReportPurchaseBills(params, true);
  const infoEl = document.getElementById('rpb-result-info');
  if (from || to) {
    infoEl.style.display = '';
    infoEl.textContent = `Showing ${rpbTotal} matching bill${rpbTotal === 1 ? '' : 's'}`;
  } else {
    infoEl.style.display = 'none';
  }
}

async function resetReportPurchaseBillsFilter() {
  document.getElementById('rpb-date-from').value = '';
  document.getElementById('rpb-date-to').value = '';
  document.getElementById('rpb-result-info').style.display = 'none';
  const params = new URLSearchParams(rpbLastParams ? rpbLastParams.toString() : '');
  params.delete('date_from');
  params.delete('date_to');
  await loadReportPurchaseBills(params, true);
}

// ─── REPORT - SALE BILLS LIST ─────────────────────────────────────────

let rsbMode = 'cash';
let rsbAllRows = [];
let rsbPage = 1;
let rsbTotal = 0;
let rsbLastParams = null; // filters currently in effect, reused across page changes

function switchReportSaleBillsMode(mode) {
  rsbMode = mode;
  document.getElementById('rsb-mode-cash').classList.toggle('active', mode === 'cash');
  document.getElementById('rsb-mode-credit').classList.toggle('active', mode === 'credit');
  loadReportSaleBills();
}

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
    try {
        const res = await fetch(url);
        const data = await res.json();
        // /api/reports/sales returns {entries,total,page,limit} when
        // page & limit are passed, same convention as /api/items.
        const rows = data.entries !== undefined ? data.entries : data;
        rsbTotal = data.total !== undefined ? data.total : rows.length;
        rsbAllRows = rows;
        renderReportSaleBills(rsbAllRows);
        renderPaginationBar('rsb-pagination', rsbPage, REPORT_BILLS_PAGE_SIZE, rsbTotal, gotoReportSaleBillsPage);
    } catch (e) {
        console.error('Error loading sale reports:', e);
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
        items: []
      });
    }
    groups.get(sid).items.push(e);
  });

  // Payment mode badge color
  const payColor = { Cash: '#4ade80', Online: '#818cf8', Split: '#fbbf24', Credit: '#f87171' };

  wrapper.innerHTML = Array.from(groups.values()).map(bill => {
    const grandTotal  = bill.items.reduce((s, i) => s + (parseFloat(i.sellTotal) || 0), 0);
    const totalQty    = bill.items.reduce((s, i) => s + (parseInt(i.qty)        || 0), 0);
    const dateFormatted = bill.date
      ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
      : '—';
    const pColor = payColor[bill.paymentMode] || 'var(--color-text-secondary)';
    const uid = 'rsb-' + bill.sale_id;
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

    return `
      <div class="sb-invoice-card">
        <div class="sb-invoice-header" style="cursor:pointer" onclick="toggleBillDetail('${uid}')">
          <div class="sb-invoice-header-left">
            <div class="sb-invoice-no-wrap">
              <span class="sb-invoice-label">Bill</span>
              <span class="sb-invoice-no">#${bill.billNo || 'N/A'}</span>
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
            <span class="sb-meta-chip sb-pm-chip" style="color:${pColor}; border-color:${pColor}33; background:#${(bill.paymentMode||'').toLowerCase()==='cash'?'4ade80':(bill.paymentMode||'').toLowerCase().includes('credit')?'f87171':'60a5fa'}12;">
              <i class="ti ti-${pmLower === 'cash' ? 'coin' : pmLower.includes('credit') ? 'credit-card' : 'device-mobile'}"></i>
              ${bill.paymentMode || '—'}
            </span>
            <span class="sb-meta-chip sb-items-chip"><i class="ti ti-package"></i>${bill.items.length} item${bill.items.length !== 1 ? 's' : ''}</span>
            <span class="sb-meta-chip" style="font-weight:700;color:var(--color-text-primary)"><i class="ti ti-currency-rupee"></i>${fmt(grandTotal)}</span>
            <button onclick="event.stopPropagation();toggleBillDetail('${uid}')" id="btn-${uid}" style="background:none;border:none;color:var(--color-accent);cursor:pointer;padding:2px 4px;font-size:16px" title="View details"><i class="ti ti-chevron-down"></i></button>
          </div>
        </div>
        <div id="${uid}" style="display:none">
          <div class="sb-table-wrap">
            <table class="sb-table">
              <thead>
                <tr>
                  <th class="sb-th sb-th-center" style="width:36px">#</th>
                  <th class="sb-th">Item</th>
                  <th class="sb-th sb-th-center">Size</th>
                  <th class="sb-th sb-th-center">Qty</th>
                  <th class="sb-th sb-th-right">Rate</th>
                  <th class="sb-th sb-th-right">Total</th>
                </tr>
              </thead>
              <tbody>${itemRows}</tbody>
            </table>
          </div>
          <div class="sb-invoice-footer">
            <div class="sb-footer-stats">
              <span class="sb-footer-stat">
                <span class="sb-footer-stat-label">Items Sold</span>
                <span class="sb-footer-stat-val">${totalQty}</span>
              </span>
              <span class="sb-footer-divider"></span>
              <span class="sb-footer-stat">
                <span class="sb-footer-stat-label">Payment</span>
                <span class="sb-footer-stat-val" style="color:${pColor};">${bill.paymentMode || '—'}</span>
              </span>
            </div>
            <div class="sb-invoice-total">
              <span class="sb-total-label">Grand Total</span>
              <span class="sb-total-amount">${fmt(grandTotal)}</span>
            </div>
            <button class="sb-footer-edit-btn" onclick="event.stopPropagation();openSaleEdit(${bill.sale_id})" title="Edit bill">
              <i class="ti ti-pencil"></i> Edit
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

async function applyReportSaleBillsFilter() {
  const from = document.getElementById('rsb-date-from').value;
  const to = document.getElementById('rsb-date-to').value;
  // Sent to the server (instead of filtering only the rows already
  // loaded in the browser) so the date range matches against the whole
  // dataset, not just whatever page happens to be on screen so far.
  const params = new URLSearchParams(rsbLastParams ? rsbLastParams.toString() : '');
  if (from) params.set('date_from', from); else params.delete('date_from');
  if (to) params.set('date_to', to); else params.delete('date_to');
  await loadReportSaleBills(params, true);
  const infoEl = document.getElementById('rsb-result-info');
  if (from || to) {
    infoEl.style.display = '';
    infoEl.textContent = `Showing ${rsbTotal} matching bill${rsbTotal === 1 ? '' : 's'}`;
  } else {
    infoEl.style.display = 'none';
  }
}

async function resetReportSaleBillsFilter() {
  document.getElementById('rsb-date-from').value = '';
  document.getElementById('rsb-date-to').value = '';
  document.getElementById('rsb-result-info').style.display = 'none';
  const params = new URLSearchParams(rsbLastParams ? rsbLastParams.toString() : '');
  params.delete('date_from');
  params.delete('date_to');
  await loadReportSaleBills(params, true);
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

  wrapper.innerHTML = rows.map(bill => {
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
            <button class="sb-footer-edit-btn" onclick="event.stopPropagation();openReplaceEdit(${bill.id})" title="Edit bill">
              <i class="ti ti-pencil"></i> Edit
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function applyReportReplaceBillsFilter() {
  const from = document.getElementById('rrb-date-from').value;
  const to = document.getElementById('rrb-date-to').value;
  let rows = rrbAllRows;
  if (from) rows = rows.filter(e => (e.date || '').slice(0,10) >= from);
  if (to)   rows = rows.filter(e => (e.date || '').slice(0,10) <= to);
  renderReportReplaceBills(rows);
  const infoEl = document.getElementById('rrb-result-info');
  if (from || to) {
    infoEl.style.display = '';
    infoEl.textContent = `Showing ${rows.length} of ${rrbAllRows.length} bills`;
  } else {
    infoEl.style.display = 'none';
  }
}

function resetReportReplaceBillsFilter() {
  document.getElementById('rrb-date-from').value = '';
  document.getElementById('rrb-date-to').value = '';
  document.getElementById('rrb-result-info').style.display = 'none';
  renderReportReplaceBills(rrbAllRows);
}