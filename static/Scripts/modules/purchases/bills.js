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
let pbBillsByUid = {}; // uid -> grouped bill object, so Details can rebuild the breakdown without a re-fetch
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
  if (reset) { pbPage = 1; pbLastParams = params; pbTotal = 0; }
  const p = new URLSearchParams(pbLastParams ? pbLastParams.toString() : '');
  p.set('type', 'purchase');
  p.set('mode', pbMode);
  p.set('page', pbPage);
  p.set('limit', PB_PAGE_SIZE);
  if (!reset && pbTotal > 0) p.set('total', pbTotal);

  // Show skeleton loader after 250ms if the fetch is slow
  showPageLoader('pb-bills-wrapper', pbRows.length || PB_PAGE_SIZE);

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
  } finally {
    hidePageLoader('pb-bills-wrapper');
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
        sellerNo: e.sellerNo || e.seller_no || '',
        sellerAddress: e.sellerAddress || e.seller_address || '',
        sellerGstNo: e.sellerGstNo || e.seller_gst_no || '',
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
    groups.get(key).items.push(e);
  });

  wrapper.innerHTML = Array.from(groups.values()).map(bill => {
    const grandTotal = bill.items.reduce((s, i) => s + (parseFloat(i.buyTotal) || 0), 0);
    const grandTotalWithGST = parseFloat(bill.items[0]?.totalWithGST) || grandTotal;
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
          <td class="pb-td pb-td-center" style="font-weight:600; color:#818cf8;">${itm.margin != null ? itm.margin + '%' : '0%'}</td>
          <td class="pb-td pb-td-right pb-td-total">${fmt(itm.buyTotal)}</td>
        </tr>
      `;
    }).join('');

    const uid = 'pb-' + bill.purchase_id;
    pbBillsByUid[uid] = bill;

    const chips = [
      { icon: 'calendar', text: dateFormatted },
    ];
    if (bill.department) chips.push({ icon: 'building', text: bill.department, className: 'pb-dept-chip' });
    chips.push({ icon: 'package', text: `${bill.items.length} item${bill.items.length !== 1 ? 's' : ''}`, className: 'pb-items-chip' });
    chips.push({ icon: 'currency-rupee', text: fmt(grandTotal), style: 'font-weight:700;color:var(--color-text-primary)' });

    return buildInvoiceCardHTML({
      prefix: 'pb',
      uid,
      headerLabel: 'Invoice',
      headerNo: `#${bill.invoiceNo || 'N/A'}`,
      subInfo: [{ icon: 'building-store', text: bill.party || '—' }],
      chips,
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
        { icon: 'file-text', label: 'Details', title: 'View full bill details', onclick: `showPurchaseBillDetail('${uid}')` },
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
  }).join('');
}

async function deletePurchaseBill(purchaseId) {
  if (!confirm('Are you sure you want to delete this purchase bill? All associated stock items and Tally transactions will be permanently deleted.')) {
    return;
  }
  try {
    const res = await fetch(`/api/purchase_bill/${purchaseId}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      showToast('Purchase bill deleted successfully');
      if (typeof loadPurchaseBills === 'function') loadPurchaseBills();
      if (typeof loadReportPurchaseBills === 'function') loadReportPurchaseBills();
    } else {
      showToast(data.message || 'Error deleting purchase bill', '#dc2626');
    }
  } catch (e) {
    showToast('Network error deleting purchase bill', '#dc2626');
  }
}


// Opens the centered bill-preview modal with a full breakdown of one
// purchase bill already loaded in this panel -- subtotal, discount,
// CGST/SGST/IGST and the final GST-inclusive total, plus payment status.
// Shares buildPurchaseBillDetailHTML with the Reports > Purchase Bills
// panel (see ui/billPreview.js) so both look identical.
async function showPurchaseBillDetail(uid) {
  const bill = pbBillsByUid[uid];
  if (!bill) { showToast('Could not find that bill', '#dc2626'); return; }

  let shopInfo = {};
  try { shopInfo = await fetch('/api/shop_settings').then(r => r.json()); } catch (e) { /* ignore — detail still works without shop info */ }

  const html = buildPurchaseBillDetailHTML(shopInfo, bill);
  openBillPreviewModal(html, `Invoice #${bill.invoiceNo || bill.purchase_id}`);
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
