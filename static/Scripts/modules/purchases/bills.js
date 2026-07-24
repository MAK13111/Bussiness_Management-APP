// =========================================================================
// modules/purchases/bills.js
// Purchase "Bills (date wise)" panel: loading and rendering bills for
// the selected mode (cash/credit), plus filtering and detail toggling.
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

let pbMode = 'cash';
let pbRows = [];
let pbPage = 1;
let pbTotal = 0;
let pbLastParams = null; // date filters currently in effect, reused across page changes
const PB_PAGE_SIZE = 100;

function switchPurchaseBillsMode(mode) {
  pbMode = mode;
  document.getElementById('pb-mode-cash').classList.toggle('active', mode === 'cash');
  document.getElementById('pb-mode-credit').classList.toggle('active', mode === 'credit');
  loadPurchaseBills();
}

// reset=true (default): fresh open/filter -- goes back to page 1.
// reset=false: internal use when jumping directly to a specific page.
async function loadPurchaseBills(params, reset = true) {
  if (reset) { pbPage = 1; pbLastParams = params; }
  const p = new URLSearchParams(pbLastParams ? pbLastParams.toString() : '');
  p.set('type', 'purchase');
  p.set('mode', pbMode);
  p.set('page', pbPage);
  p.set('limit', PB_PAGE_SIZE);
  try {
    const res = await fetch('/api/entries?' + p.toString());
    const data = await res.json();
    // /api/entries returns {entries,total,page,limit} when page & limit are
    // passed, same convention as /api/reports/purchases and /api/items.
    const rows = data.entries !== undefined ? data.entries : data;
    pbTotal = data.total !== undefined ? data.total : rows.length;
    pbRows = rows;
    renderPurchaseBills(pbRows);
    renderPaginationBar('pb-pagination', pbPage, PB_PAGE_SIZE, pbTotal, gotoPurchaseBillsPage);
  } catch (e) {
    console.error('Error loading purchase bills:', e);
  }
}

async function gotoPurchaseBillsPage(page) {
  pbPage = page;
  await loadPurchaseBills(pbLastParams, false);
}

function renderPurchaseBills(rows) {
  const wrapper = document.getElementById('pb-bills-wrapper');
  const emptyEl = document.getElementById('pb-empty');
  if (!rows.length) {
    if (wrapper) wrapper.innerHTML = '';
    if (emptyEl) emptyEl.style.display = '';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  let idxSeed = 0;

  // Group by purchase_id (primary key), same as Reports panel.
  const groups = new Map();
  rows.forEach(e => {
    const pid = e.purchase_id;
    const key = pid != null ? pid : (e.invoice_no || e.invoiceNo || '') + '|' + (e.date + '|' + (e.party || ''));
    if (!groups.has(key)) {
      groups.set(key, {
        purchase_id: pid,
        invoiceNo: e.invoice_no || e.invoiceNo || '',
        party: e.party || '',
        date: e.date || '',
        department: e.department || '',
        items: []
      });
    }
    groups.get(key).items.push(e);
  });

  wrapper.innerHTML = Array.from(groups.values()).map(bill => {
    const grandTotal = bill.items.reduce((s, i) => s + (parseFloat(i.buyTotal) || 0), 0);
    const totalQty = bill.items.reduce((s, i) => s + (parseInt(i.qty) || 0), 0);
    const totalSold = bill.items.reduce((s, i) => s + (parseInt(i.sold) || 0), 0);
    const dateFormatted = bill.date ? new Date(bill.date).toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' }) : '—';

    const itemRows = bill.items.map((itm, idx) => {
      const remaining = Math.max(0, (itm.qty || 0) - (+itm.sold || 0));
      const remainPct = itm.qty > 0 ? Math.round((remaining / itm.qty) * 100) : 0;
      // Color-code remaining stock: green >50%, amber 20-50%, red <20%
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

    const uid = 'pb-' + bill.purchase_id;

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
            ${bill.department ? `<span class="pb-meta-chip pb-dept-chip"><i class="ti ti-building"></i>${bill.department}</span>` : ''}
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

// Date filters are sent to the server (instead of filtering only whatever
// page happens to already be loaded in the browser) so the range matches
// against the whole dataset, same approach as the Reports tab's bill lists.
async function applyPurchaseBillsFilter() {
  const from = document.getElementById('pb-date-from').value;
  const to = document.getElementById('pb-date-to').value;
  const params = new URLSearchParams(pbLastParams ? pbLastParams.toString() : '');
  if (from) params.set('date_from', from); else params.delete('date_from');
  if (to) params.set('date_to', to); else params.delete('date_to');
  await loadPurchaseBills(params, true);
  const infoEl = document.getElementById('pb-result-info');
  if (from || to) {
    infoEl.style.display = '';
    infoEl.textContent = `Showing ${pbTotal} matching bill${pbTotal === 1 ? '' : 's'}`;
  } else {
    infoEl.style.display = 'none';
  }
}

async function resetPurchaseBillsFilter() {
  document.getElementById('pb-date-from').value = '';
  document.getElementById('pb-date-to').value = '';
  document.getElementById('pb-result-info').style.display = 'none';
  const params = new URLSearchParams(pbLastParams ? pbLastParams.toString() : '');
  params.delete('date_from');
  params.delete('date_to');
  await loadPurchaseBills(params, true);
}

function toggleBillDetail(uid) {
    const el = document.getElementById(uid);
    if (!el) return;
    const opening = el.style.display === 'none';
    el.style.display = opening ? 'block' : 'none';
    const btn = document.getElementById('btn-' + uid);
    if (btn) btn.classList.toggle('open', opening);
}
