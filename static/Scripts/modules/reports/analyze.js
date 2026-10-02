// =========================================================================
// modules/reports/analyze.js
// "Purchase & Sales reports" tab: switching between Purchases/Sells/Sold
// sub-views and rendering each of them, including the Sold search box.
// =========================================================================

let currentAnalyzeTab = 'purchases';

function switchAnalyzeTab(tab) {
  currentAnalyzeTab = tab;

  // Toggle active state on the tabs
  document.getElementById('atab-purchases').classList.toggle('active', tab === 'purchases');
  document.getElementById('atab-sells').classList.toggle('active', tab === 'sells');
  document.getElementById('atab-replace').classList.toggle('active', tab === 'replace');
  document.getElementById('atab-sold').classList.toggle('active', tab === 'sold');
  const atabDeleted = document.getElementById('atab-deleted');
  if (atabDeleted) atabDeleted.classList.toggle('active', tab === 'deleted');

  // Show/hide sub-panels
  const purchasesPanel = document.getElementById('analyze-purchases-panel');
  const sellsPanel = document.getElementById('analyze-sells-panel');
  const replacePanel = document.getElementById('analyze-replace-panel');
  const soldPanel = document.getElementById('analyze-sold-panel');
  const deletedPanel = document.getElementById('analyze-deleted-panel');
  purchasesPanel.style.display = tab === 'purchases' ? '' : 'none';
  sellsPanel.style.display     = tab === 'sells'     ? '' : 'none';
  replacePanel.style.display   = tab === 'replace'   ? '' : 'none';
  soldPanel.style.display      = tab === 'sold'      ? '' : 'none';
  if (deletedPanel) deletedPanel.style.display = tab === 'deleted' ? '' : 'none';

  // Load data
  if (tab === 'purchases') {
    showSubTabLoader(purchasesPanel);
    loadReportPurchaseBills(getReportFilterParams()).finally(() => hideSubTabLoader(purchasesPanel));
  }
  if (tab === 'sells') {
    showSubTabLoader(sellsPanel);
    loadReportSaleBills(getReportFilterParams()).finally(() => hideSubTabLoader(sellsPanel));
  }
  if (tab === 'replace') {
    showSubTabLoader(replacePanel);
    loadReportReplaceBills(getReportFilterParams()).finally(() => hideSubTabLoader(replacePanel));
  }
  if (tab === 'sold') {
    showSubTabLoader(soldPanel);
    loadAnalyzeSold().finally(() => hideSubTabLoader(soldPanel));
  }
  if (tab === 'deleted') {
    if (deletedPanel) showSubTabLoader(deletedPanel);
    loadReportDeletedBills(getReportFilterParams()).finally(() => hideSubTabLoader(deletedPanel));
  }
}


function renderAnalyzePurchase() {
  const tbody = document.getElementById('analyze-p-tbody');
  const tfoot = document.getElementById('analyze-p-tfoot');
  const empty = document.getElementById('analyze-p-empty');
  const resultInfo = document.getElementById('p-result-info');
  const filtered = getFilteredPurchaseEntries();
  const isFiltered = filtered.length !== entries.length || purchaseQuery || Object.keys(purchaseFilters).some(k => purchaseFilters[k]);
  if (entries.length === 0) {
    tbody.innerHTML = '';
    tfoot.innerHTML = '';
    empty.style.display = 'block';
    resultInfo.style.display = 'none';
    return;
  }
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--color-text-tertiary);padding:2rem">No results found. Try different search terms.</td></tr>`;
    tfoot.innerHTML = '';
    empty.style.display = 'none';
    resultInfo.style.display = 'block';
    resultInfo.textContent = `0 of ${entries.length} entries match`;
    return;
  }
  empty.style.display = 'none';
  if (isFiltered) {
    resultInfo.style.display = 'block';
    resultInfo.textContent = `${filtered.length} of ${entries.length} entries`;
  } else {
    resultInfo.style.display = 'none';
  }
  const q = purchaseQuery;
  let tQty = 0, tBuy = 0, tSell = 0, tProfit = 0;
  tbody.innerHTML = filtered.map((e, i) => {
    tQty += +e.qty; tBuy += +e.buyTotal; tSell += +e.sellTotal; tProfit += +e.profit;
    const soldQty = +e.sold || 0;
    const soldBadge = soldQty > 0 ? `<span class="margin-badge" style="background:#14532d;color:#4ade80;font-size:10px">${soldQty} sold</span>` : '—';
    return `<tr>
      <td style="color:var(--color-text-secondary)">${i+1}</td>
      <td title="${e.party||''}">${hl(e.party, q)}</td>
      <td title="${e.item||''}">${hl(e.item, q)}</td>
      <td>${e.size||'—'}</td>
      <td>${e.qty}</td>
      <td>${soldBadge}</td>
      <td>${fmt(e.sellUnit)}</td>
      <td><button class="info-btn" onclick="showPurchaseDetail(${e.id})" title="Details"><i class="ti ti-info-circle"></i></button></td>
      <td><button class="bc-btn" onclick="showBarcodes(${e.id})" title="View Barcodes" style="padding:0 8px"><i class="ti ti-barcode"></i></button></td>
      <td><button class="del-btn" onclick="deleteEntry(${e.id})" aria-label="Delete"><i class="ti ti-trash"></i></button></td>
    </tr>`;

  }).join('');
  tfoot.innerHTML = `<tr class="grand-row">
    <td colspan="4" style="color:var(--color-text-secondary);font-size:12px">${isFiltered ? 'Filtered total' : 'Grand total'}</td>
    <td>${tQty}</td><td>${fmt(tSell)}</td><td></td><td></td><td></td><td></td><td></td>
  </tr>`;
}

function renderAnalyzeSell() {
  const tbody = document.getElementById('analyze-s-tbody');
  const tfoot = document.getElementById('analyze-s-tfoot');
  const empty = document.getElementById('analyze-s-empty');
  const resultInfo = document.getElementById('s-result-info');
  const filtered = getFilteredSellEntries();
  const isFiltered = sellQuery.length > 0 || Object.keys(sellFilters).some(k => sellFilters[k]);
  if (sellEntries.length === 0) {
    tbody.innerHTML = '';
    tfoot.innerHTML = '';
    empty.style.display = 'block';
    resultInfo.style.display = 'none';
    return;
  }
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--color-text-tertiary);padding:2rem">No results found. Try different search terms.</td></tr>`;
    tfoot.innerHTML = '';
    empty.style.display = 'none';
    resultInfo.style.display = 'block';
    resultInfo.textContent = `0 of ${sellEntries.length} entries match`;
    return;
  }
  empty.style.display = 'none';
  if (isFiltered) {
    resultInfo.style.display = 'block';
    resultInfo.textContent = `${filtered.length} of ${sellEntries.length} entries`;
  } else {
    resultInfo.style.display = 'none';
  }
  const q = sellQuery;
  let tQty = 0, tBuy = 0, tSell = 0, tProfit = 0;
  tbody.innerHTML = filtered.map((e, i) => {
    tQty += +e.qty; tBuy += +e.buyTotal; tSell += +e.sellTotal; tProfit += +e.profit;
    const discBadge = e.discount && +e.discount > 0 ? ` <span class="margin-badge" style="background:var(--color-bg-accent);color:var(--color-text-danger);font-size:10px">${(+e.discount).toFixed(0)}%↓</span>` : '';
    return `<tr>
      <td style="color:var(--color-text-secondary)">${i+1}</td>
      <td>${e.date||'—'}</td>
      <td title="${e.customerName||''}">${hl(e.customerName, q)}</td>
      <td>${hl(e.customerNo, q)}</td>
      <td title="${e.item||''}">${e.item||'—'}</td>
      <td>${e.qty}</td>
      <td>${fmt(e.sellUnit)}${discBadge}</td>
      <td class="profit-cell">${fmt(e.profit)}</td>
      <td><button class="info-btn" onclick="showSellDetail(${sellEntries.indexOf(e)})" title="Details"><i class="ti ti-info-circle"></i></button></td>
      <td><button class="edit-btn" onclick="openEditSell(${e.id})" title="Edit"><i class="ti ti-pencil"></i></button></td>
      <td><button class="del-btn" onclick="deleteSellEntry(${e.id})" aria-label="Delete"><i class="ti ti-trash"></i></button></td>
    </tr>`;
  }).join('');
  tfoot.innerHTML = `<tr class="grand-row">
    <td colspan="5" style="color:var(--color-text-secondary);font-size:12px">${isFiltered ? 'Filtered total' : 'Grand total'}</td>
    <td>${tQty}</td><td>${fmt(tSell)}</td><td class="profit-cell">${fmt(tProfit)}</td><td></td><td></td><td></td>
  </tr>`;
}

// ─── SOLD ITEMS VIEW ─────────────────────────────────────────
// Fetched page-by-page + searched on the server (sold_only=1 filter in
// SQL), NOT loaded fully into the browser -- a shop can have 100k+ sold
// line items over time, and the old approach pulled every single one.

let soldQuery = '';
const SOLD_PAGE_SIZE = 100;
let soldPage = 1;
let soldRows = [];
let soldTotal = 0;
let soldTotals = { totalSold: 0, totalRevenue: 0 };

function onSoldSearch() {
  soldQuery = document.getElementById('sold-search').value.trim();
  document.getElementById('sold-clear-btn').style.display = soldQuery ? '' : 'none';
  soldPage = 1; // new search -- always start back at page 1
  loadAnalyzeSold();
}

function clearSoldSearch() {
  document.getElementById('sold-search').value = '';
  soldQuery = '';
  document.getElementById('sold-clear-btn').style.display = 'none';
  soldPage = 1;
  loadAnalyzeSold();
}

function gotoSoldPage(page) {
  soldPage = page;
  loadAnalyzeSold();
}

async function loadAnalyzeSold() {
  const p = new URLSearchParams();
  p.set('type', 'purchase');
  p.set('sold_only', '1');
  p.set('page', soldPage);
  p.set('limit', SOLD_PAGE_SIZE);
  if (soldQuery) p.set('search', soldQuery);
  const statsParams = new URLSearchParams();
  if (soldQuery) statsParams.set('search', soldQuery);

  showPageLoader('analyze-sold-tbody', soldRows.length || SOLD_PAGE_SIZE);

  try {
    const [entriesRes, statsRes] = await Promise.all([
      fetch('/api/entries?' + p.toString()),
      fetch('/api/sold_items/stats?' + statsParams.toString())
    ]);
    const data = await entriesRes.json();
    soldRows = data.entries !== undefined ? data.entries : data;
    soldTotal = data.total !== undefined ? data.total : soldRows.length;
    soldTotals = await statsRes.json();
  } catch (e) {
    console.error('Error loading sold items:', e);
    soldRows = [];
    soldTotal = 0;
    soldTotals = { totalSold: 0, totalRevenue: 0 };
  } finally {
    hidePageLoader('analyze-sold-tbody');
  }
  renderAnalyzeSold();
}

function renderAnalyzeSold() {
  const tbody = document.getElementById('analyze-sold-tbody');
  const tfoot = document.getElementById('analyze-sold-tfoot');
  const empty = document.getElementById('analyze-sold-empty');
  const resultInfo = document.getElementById('sold-result-info');

  if (soldTotal === 0) {
    tbody.innerHTML = '';
    tfoot.innerHTML = '';
    empty.style.display = 'block';
    resultInfo.style.display = 'none';
    renderPaginationBar('analyze-sold-pagination', 1, SOLD_PAGE_SIZE, 0, gotoSoldPage);
    return;
  }
  empty.style.display = 'none';
  if (soldQuery) {
    resultInfo.style.display = 'block';
    resultInfo.textContent = `${soldTotal} sold item${soldTotal === 1 ? '' : 's'} match`;
  } else {
    resultInfo.style.display = 'none';
  }

  const startIdx = (soldPage - 1) * SOLD_PAGE_SIZE;

  // Chunked rendering: first 25 rows appear instantly, remaining rows
  // are appended in 16ms increments so the browser stays responsive.
  const CHUNK = 25;
  const buildRow = (e, i) => {
    const soldQty = +e.sold || 0;
    const sellRevenue = round2(soldQty * +e.sellUnit);
    const q = soldQuery.toLowerCase();
    return `<tr>
      <td style="color:var(--color-text-secondary)">${startIdx + i + 1}</td>
      <td title="${e.party||''}">${hl(e.party, q)}</td>
      <td title="${e.item||''}">${hl(e.item, q)}</td>
      <td>${e.size||'—'}</td>
      <td><span class="margin-badge" style="background:#14532d;color:#4ade80">${soldQty}</span></td>
      <td>${fmt(e.sellUnit)}</td>
      <td class="profit-cell">${fmt(sellRevenue)}</td>
      <td style="color:var(--color-text-secondary)">${(e.date||'—').slice(0,10)}</td>
    </tr>`;
  };

  tbody.innerHTML = '';
  const firstChunk = soldRows.slice(0, CHUNK);
  tbody.insertAdjacentHTML('beforeend', firstChunk.map((e, i) => buildRow(e, i)).join(''));

  if (soldRows.length > CHUNK) {
    let offset = CHUNK;
    function appendSoldChunk() {
      const chunk = soldRows.slice(offset, offset + CHUNK);
      tbody.insertAdjacentHTML('beforeend', chunk.map((e, i) => buildRow(e, offset + i)).join(''));
      offset += CHUNK;
      if (offset < soldRows.length) setTimeout(appendSoldChunk, 16);
    }
    setTimeout(appendSoldChunk, 16);
  }

  // Totals in the footer come from the server (whole matching set), not
  // just this page's rows.
  tfoot.innerHTML = `<tr class="grand-row">
    <td colspan="4" style="color:var(--color-text-secondary);font-size:12px">Total</td>
    <td><span class="margin-badge" style="background:#14532d;color:#4ade80">${soldTotals.totalSold || 0}</span></td>
    <td></td>
    <td class="profit-cell">${fmt(soldTotals.totalRevenue || 0)}</td>
    <td></td>
  </tr>`;

  renderPaginationBar('analyze-sold-pagination', soldPage, SOLD_PAGE_SIZE, soldTotal, gotoSoldPage);
}

