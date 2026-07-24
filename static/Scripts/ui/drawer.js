// =========================================================================
// ui/drawer.js
// Generic side-drawer used to show purchase/sell entry details.
// =========================================================================

function openDrawer(title, bodyHTML) {
  document.getElementById('drawer-title').textContent = title;
  document.getElementById('drawer-body').innerHTML = bodyHTML;
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
}

function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
}

function drawerSection(title, rows) {
  const rowsHTML = rows.map(([label, val, cls='']) =>
    `<div class="drawer-row"><span class="drawer-label">${label}</span><span class="drawer-val ${cls}">${val}</span></div>`
  ).join('');
  return `<div class="drawer-section"><div class="drawer-section-title">${title}</div>${rowsHTML}</div>`;
}

function showPurchaseDetail(id) {
  const e = entries.find(x => x.id === id);
  if (!e) return;
  const body = `
    ${drawerSection('Basic Info', [
      ['Date', e.date || '—'],
      ['Party', e.party || '—'],
      ['Item', e.item || '—'],
      ['Size', e.size || '—'],
      ['Qty', e.qty != null ? e.qty : '—'],
      ['Department', e.department || '—']
    ])}
    ${drawerSection('Pricing', [
      ['Buy / Unit', fmt(e.buy)],
      ['Buy Total', fmt(e.buyTotal)],
      ['Margin', e.margin ? (+e.margin).toFixed(1) + '%' : '—'],
      ['Sell / Unit', fmt(e.sellUnit)],
      ['Sell Total', fmt(e.sellTotal)],
      ['Profit', e.profit != null ? fmt(e.profit) : '—', 'profit'],
      ['CGST', e.cgst ? (+e.cgst).toFixed(2) + '%' : '—'],
      ['SGST', e.sgst ? (+e.sgst).toFixed(2) + '%' : '—'],
      ['IGST', e.igst ? (+e.igst).toFixed(2) + '%' : '—'],
      ['Total + GST', fmt(e.totalWithGST || e.buyTotal)]
    ])}
    ${drawerSection('Seller Info', [
      ['Seller No.', e.sellerNo || '—'],
      ['Invoice No.', e.invoiceNo || '—'],
      ['Address', e.sellerAddress || '—']
    ])}
    <button class="bc-btn" style="width:100%;justify-content:center;margin-top:4px" onclick="closeDrawer();switchType('analyze');setTimeout(()=>showBarcodes(${e.id}),300)">
      <i class="ti ti-barcode"></i> View ${e.qty} Barcodes in Reports
    </button>`;
  openDrawer((e.item || e.party || 'Entry') + ' — Purchase Details', body);
}

function showSellDetail(idx) {
  const e = sellEntries[idx];
  if (!e) return;
  const body = [
    drawerSection('Customer Info', [
      ['Date', e.date || '—'],
      ['Customer Name', e.customerName || '—'],
      ['Customer No.', e.customerNo || '—'],
      ['Payment Mode', e.paymentMode || '—'],
      ['Bill No.', e.billNo || '—']
    ]),
    drawerSection('Item Info', [
      ['Item Name', e.item || '—'],
      ['Size', e.size || '—'],
      ['Quantity', e.qty]
    ]),
    drawerSection('Pricing', [
      ['Buy / Unit', fmt(e.buy)],
      ['Buy Total', fmt(e.buyTotal)],
      ['Margin', (+e.margin).toFixed(1) + '%'],
      ['Discount', e.discount && +e.discount > 0 ? (+e.discount).toFixed(1) + '%' : '—'],
      ['Sell / Unit', fmt(e.sellUnit)],
      ['Sell Total', fmt(e.sellTotal)],
      ['Profit', fmt(e.profit), +e.profit >= 0 ? 'profit' : 'danger']
    ])
  ].join('');
  openDrawer((e.customerName || 'Customer') + ' — Sell Details', body);
}

