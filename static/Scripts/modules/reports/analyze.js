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

  // Show/hide sub-panels
  const purchasesPanel = document.getElementById('analyze-purchases-panel');
  const sellsPanel = document.getElementById('analyze-sells-panel');
  const replacePanel = document.getElementById('analyze-replace-panel');
  const soldPanel = document.getElementById('analyze-sold-panel');
  purchasesPanel.style.display = tab === 'purchases' ? '' : 'none';
  sellsPanel.style.display     = tab === 'sells'     ? '' : 'none';
  replacePanel.style.display   = tab === 'replace'   ? '' : 'none';
  soldPanel.style.display      = tab === 'sold'      ? '' : 'none';

  // Load data — Purchases, Sells and Replace now show bill cards. Same as
  // the top-level sub-tabs, the panel being switched to shows a spinner
  // (hiding any bill cards left over from a previous visit) until its own
  // fresh data has finished loading, instead of letting stale cards flash
  // on screen first.
  if (tab === 'purchases') {
    showSubTabLoader(purchasesPanel);
    loadReportPurchaseBills().finally(() => hideSubTabLoader(purchasesPanel));
  }
  if (tab === 'sells') {
    showSubTabLoader(sellsPanel);
    loadReportSaleBills().finally(() => hideSubTabLoader(sellsPanel));
  }
  if (tab === 'replace') {
    showSubTabLoader(replacePanel);
    loadReportReplaceBills().finally(() => hideSubTabLoader(replacePanel));
  }
  if (tab === 'sold') {
    // Sold Items is the one Analyze sub-view that genuinely needs the full
    // purchase rows (to find every item with sold > 0), not just the stat
    // totals. Fetch them lazily, the first time this tab is opened, instead
    // of on every Reports tab visit -- loadEntries() pulls all 275k+ rows,
    // which the other three sub-tabs (bill cards + stats) don't need at all.
    showSubTabLoader(soldPanel);
    loadEntries().then(renderAnalyzeSold).finally(() => hideSubTabLoader(soldPanel));
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
      <td style="color:var(--color-text-secondary)">${(e.date||'—').slice(0,10)}</td>
      <td><button class="info-btn" onclick="showPurchaseDetail(${e.id})" title="Details"><i class="ti ti-info-circle"></i></button></td>
      <td><button class="bc-btn" onclick="showBarcodes(${e.id})" title="View Barcodes" style="padding:0 8px"><i class="ti ti-barcode"></i></button></td>
      <td><button class="edit-btn" onclick="openEditPurchase(${e.id})" title="Edit"><i class="ti ti-pencil"></i></button></td>
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

let soldQuery = '';

// Sold Items is rendered entirely client-side (all rows already loaded via
// loadEntries()), so pagination here just slices the filtered array --
// no server round-trip needed, unlike the bill-card pagination above.
const SOLD_PAGE_SIZE = 100;
let soldPage = 1;

function onSoldSearch() {
  soldQuery = document.getElementById('sold-search').value.trim();
  document.getElementById('sold-clear-btn').style.display = soldQuery ? '' : 'none';
  soldPage = 1; // new search -- always start back at page 1
  renderAnalyzeSold();
}

function clearSoldSearch() {
  document.getElementById('sold-search').value = '';
  soldQuery = '';
  document.getElementById('sold-clear-btn').style.display = 'none';
  soldPage = 1;
  renderAnalyzeSold();
}

function gotoSoldPage(page) {
  soldPage = page;
  renderAnalyzeSold();
}

function renderAnalyzeSold() {
  const tbody = document.getElementById('analyze-sold-tbody');
  const tfoot = document.getElementById('analyze-sold-tfoot');
  const empty = document.getElementById('analyze-sold-empty');
  const resultInfo = document.getElementById('sold-result-info');
  const allSold = entries.filter(e => (+e.sold || 0) > 0);
  const q = soldQuery.toLowerCase();
  const filtered = q ? allSold.filter(e => (e.item||'').toLowerCase().includes(q) || (e.size||'').toLowerCase().includes(q) || (e.party||'').toLowerCase().includes(q)) : allSold;
  if (allSold.length === 0) {
    tbody.innerHTML = '';
    tfoot.innerHTML = '';
    empty.style.display = 'block';
    resultInfo.style.display = 'none';
    renderPaginationBar('analyze-sold-pagination', 1, SOLD_PAGE_SIZE, 0, gotoSoldPage);
    return;
  }
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--color-text-tertiary);padding:2rem">No results found.</td></tr>`;
    tfoot.innerHTML = '';
    empty.style.display = 'none';
    resultInfo.style.display = 'block';
    resultInfo.textContent = `0 of ${allSold.length} sold items match`;
    renderPaginationBar('analyze-sold-pagination', 1, SOLD_PAGE_SIZE, 0, gotoSoldPage);
    return;
  }
  empty.style.display = 'none';
  if (q) {
    resultInfo.style.display = 'block';
    resultInfo.textContent = `${filtered.length} of ${allSold.length} sold items`;
  } else {
    resultInfo.style.display = 'none';
  }

  // Totals in the footer always reflect the full filtered set, not just the
  // rows on the current page -- same convention as the Purchases/Sells tabs.
  let totalSold = 0, totalRevenue = 0;
  filtered.forEach(e => {
    totalSold += (+e.sold || 0);
    totalRevenue += round2((+e.sold || 0) * +e.sellUnit);
  });

  // Clamp the page in case a search/filter shrank the result set below the
  // page we were previously on.
  const totalPages = Math.max(1, Math.ceil(filtered.length / SOLD_PAGE_SIZE));
  if (soldPage > totalPages) soldPage = totalPages;
  const startIdx = (soldPage - 1) * SOLD_PAGE_SIZE;
  const pageRows = filtered.slice(startIdx, startIdx + SOLD_PAGE_SIZE);

  tbody.innerHTML = pageRows.map((e, i) => {
    const soldQty = +e.sold || 0;
    const sellRevenue = round2(soldQty * +e.sellUnit);
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
  }).join('');
  tfoot.innerHTML = `<tr class="grand-row">
    <td colspan="4" style="color:var(--color-text-secondary);font-size:12px">Total</td>
    <td><span class="margin-badge" style="background:#14532d;color:#4ade80">${totalSold}</span></td>
    <td></td>
    <td class="profit-cell">${fmt(totalRevenue)}</td>
    <td></td>
  </tr>`;

  renderPaginationBar('analyze-sold-pagination', soldPage, SOLD_PAGE_SIZE, filtered.length, gotoSoldPage);
}

