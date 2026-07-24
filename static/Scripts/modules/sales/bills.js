// =========================================================================
// modules/sales/bills.js
// Sale "Bills (date wise)" panel: loading and rendering bills for the
// selected mode (cash/credit), plus filtering.
//
// Paginated in pages of 100 rows (same convention as the Reports tab's
// bill lists) instead of fetching every matching row in one go -- on a
// shop with thousands of bills, that single unbounded fetch+render was
// the main cause of this panel (and the rest of the app, while it was
// still rendering) feeling laggy.
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
  if (reset) { sbPage = 1; sbLastParams = params; }
  const p = new URLSearchParams(sbLastParams ? sbLastParams.toString() : '');
  p.set('type', 'sell');
  p.set('mode', sbMode);
  p.set('page', sbPage);
  p.set('limit', SB_PAGE_SIZE);
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
            <span class="sb-meta-chip sb-pm-chip" style="color:${pmColor}; border-color:${pmColor}33; background:#${pmBg}12;">
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
                <span class="sb-footer-stat-val" style="color:${pmColor};">${bill.paymentMode || '—'}</span>
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
