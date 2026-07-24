// =========================================================================
// core/navigation.js
// Handles switching the active main tab and sub-tab, and rendering the
// sub-tab buttons for whichever main tab is currently active.
// =========================================================================

// Kisi bhi sub-tab id par seedha jaane ke liye — pehle uska sahi main-tab
// switch karta hai (agar current main-tab se alag ho), phir us sub-tab par
// switch karta hai. Dashboard ke Quick Action buttons isi function ko use karte hain.
function goToSub(subId) {
  const targetMain = SUB_TO_MAIN[subId];
  if (targetMain && targetMain !== currentMain) {
    switchMain(targetMain);
  }
  switchSub(subId);
}

function switchMain(main) {
  currentMain = main;
  document.querySelectorAll('.sidebar-link').forEach(btn => btn.classList.remove('active'));
  document.querySelector(`.sidebar-link[data-main="${main}"]`)?.classList.add('active');
  document.querySelectorAll('.main-panel').forEach(p => p.style.display = 'none');
  if (main === 'dashboard') {
    document.getElementById('dashboard-panel').style.display = 'block';
  } else {
    const panel = document.getElementById(`${main}-main-panel`);
    if (panel) panel.style.display = 'block';
  }
  renderSubTabs(main);
  const tabs = MAIN_SUB_TABS[main] || [];
  if (tabs.length) switchSub(tabs[0].id);
  const titleMap = { dashboard: 'Dashboard', purchases: 'Purchases', sales: 'Sells', 'items-stock': 'Items & Stock', parties: 'Parties', departments: 'Departments', reports: 'Reports', tally: 'Tally Accounting', settings: 'Settings' };
  document.getElementById('main-page-title').textContent = titleMap[main] || main;
  if (main === 'dashboard') loadDashboard();
  // NOTE: purchases/sales/items-stock/reports/tally used to also trigger their
  // main load function (loadEntries/loadSellEntries/loadItems/loadVouchers)
  // right here -- but switchSub(tabs[0].id) below already loads the default
  // sub-tab's data. That meant every one of these unbounded fetch+render
  // calls ran TWICE per tab open (and for Reports, whose default sub-tab
  // 'analyze' itself calls loadEntries()+loadSellEntries()+loadReportPurchaseBills(),
  // loadEntries()/loadSellEntries() were running FOUR times). On a shop with
  // thousands of bills, this doubled/quadrupled work is what made opening a
  // large-data tab feel like it was lagging every other tab too. Removed as
  // redundant; switchSub still loads everything the visible panel needs.
}

function renderSubTabs(main) {
  const wrapper = document.getElementById('sub-tabs-wrapper');
  if (!wrapper) return;
  const tabs = MAIN_SUB_TABS[main] || [];
  wrapper.innerHTML = tabs.map(tab =>
    `<button class="sub-tab-btn" data-sub="${tab.id}" onclick="switchSub('${tab.id}')">
      <i class="${tab.icon}"></i> ${tab.label}
    </button>`
  ).join('');
  wrapper.style.display = tabs.length ? '' : 'none';
}

function switchSub(subId) {
  currentSub = subId;
  document.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.sub === subId);
  });

  const mainPanelId = currentMain === 'dashboard' ? 'dashboard-panel' : `${currentMain}-main-panel`;
  const mainPanel = document.getElementById(mainPanelId);
  if (mainPanel) {
    mainPanel.querySelectorAll('.sub-panel').forEach(p => {
      p.classList.remove('active');
      p.style.display = 'none';
    });
  } else {
    document.querySelectorAll('.sub-panel').forEach(p => {
      p.classList.remove('active');
      p.style.display = 'none';
    });
  }

  const tabDef = MAIN_SUB_TABS[currentMain]?.find(t => t.id === subId);
  let panelEl = null;
  if (tabDef) {
    panelEl = document.getElementById(tabDef.panel);
  }
  if (!panelEl) {
    panelEl = document.getElementById(subId + '-panel');
  }
  if (panelEl) {
    panelEl.classList.add('active');
    panelEl.style.display = 'block';
  }

  // Load functions
  // Instead of calling each load function directly, they are collected into
  // `loaders` below. Any synchronous setup (e.g. setting a default date
  // field) still runs immediately -- only the actual data-fetching calls
  // are deferred behind the spinner overlay.
  const loaders = [];
  // NOTE: 'purchase' (Add Purchase form) and 'sell' (Add Sale form) used to
  // push loadEntries()/loadSellEntries() here too. On this database (275k+
  // purchase items, 310k+ sale items) that meant every time either "add
  // entry" form was opened, the browser fetched and JSON-parsed the ENTIRE
  // purchase or sale table over the network -- even though this form panel
  // has no table or stat cards left to show that data in (those were
  // already removed from purchases.html/sales.html; only the Reports >
  // Analyze tab still has the stat cards and list that need it). That
  // pointless full-table fetch was the actual remaining cause of "purchase
  // entry panel jaldi nahi khulta" -- removed. autoFillBillNo() (cheap,
  // no bulk data) still runs for 'sell'.
  if (subId === 'sell') autoFillBillNo();
  // Stats-only (fast SQL SUM, no bulk row transfer) for the two stat-card
  // blocks -- loadReportPurchaseBills is the already-paginated bill-cards
  // list. Sold Items (its own inner tab) lazy-loads the full purchase rows
  // it actually needs the first time that tab is opened -- see
  // switchAnalyzeTab() in reports/analyze.js.
  if (subId === 'analyze') loaders.push(loadPurchaseStats, loadSellStats, loadReportPurchaseBills);
  if (subId === 'purchase-bills') loaders.push(loadPurchaseBills);
  if (subId === 'sale-bills') loaders.push(loadSaleBills);
  if (subId === 'purchase-return-bills') loaders.push(loadPurchaseReturnBills);
  if (subId === 'sales-return-bills') loaders.push(loadSalesReturnBills);
  if (subId === 'purchase-borrow') loaders.push(loadPurchaseBorrow);
  if (subId === 'sales-borrow') loaders.push(loadSalesBorrow);
  if (subId === 'items-list') loaders.push(loadItems);
  if (subId === 'item-stock') loaders.push(loadStockValuation);
  if (subId === 'settings-backup') loaders.push(loadBackups);
  if (subId === 'settings-export') loaders.push(loadExportTables);
  if (subId === 'settings-users') loaders.push(loadUsers);
  if (subId === 'settings-accounts') loaders.push(loadAccounts);
  if (subId === 'settings-shop-info') loaders.push(loadShopInfo);
  if (subId === 'monthly-report') { populateYearDropdown(); loaders.push(loadMonthlyReport); }
  if (subId === 'profit-report') loaders.push(loadProfitReport);
  if (subId === 'tally-ledgers') loaders.push(loadLedgers);
  if (subId === 'voucher-list') loaders.push(loadVouchers);
  if (subId === 'voucher-payment' || subId === 'voucher-receipt' ||
      subId === 'voucher-contra' || subId === 'voucher-journal') {
    loaders.push(loadLedgers, refreshLedgerOptions, loadVouchers);
  }
  if (subId === 'tally-trial-balance') {
    const today = new Date().toISOString().split('T')[0];
    const tbDate = document.getElementById('tb-date');
    if (tbDate) tbDate.value = today;
    loaders.push(loadTrialBalance);
  }
  if (subId === 'tally-balance-sheet') {
    const today = new Date().toISOString().split('T')[0];
    const bsDate = document.getElementById('bs-date');
    if (bsDate) bsDate.value = today;
    loaders.push(loadBalanceSheet);
  }
  if (subId === 'tally-profit-loss') {
    const now = new Date();
    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0];
    const today = now.toISOString().split('T')[0];
    const plFrom = document.getElementById('pl-from-date');
    const plTo = document.getElementById('pl-to-date');
    if (plFrom) plFrom.value = firstDay;
    if (plTo) plTo.value = today;
    loaders.push(loadProfitLoss);
  }
  if (subId === 'ledger-statement') {
    const now = new Date();
    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split('T')[0];
    const today = now.toISOString().split('T')[0];
    const lsFrom = document.getElementById('ls-from-date');
    const lsTo = document.getElementById('ls-to-date');
    if (lsFrom) lsFrom.value = firstDay;
    if (lsTo) lsTo.value = today;
    loaders.push(loadLedgers, loadLedgerStatement);
  }
  if (subId === 'day-book') {
    const today = new Date().toISOString().split('T')[0];
    const dbDate = document.getElementById('db-date');
    if (dbDate) dbDate.value = today;
    loaders.push(loadDayBook);
  }

  // Run all of this sub-tab's data-fetching calls together, showing a
  // spinner over the panel for as long as they take so no stale data from
  // a previous visit is visible in the meantime.
  if (loaders.length && panelEl) {
    showSubTabLoader(panelEl);
    Promise.all(loaders.map(fn => fn()))
      .catch(err => console.error(`Error loading data for sub-tab "${subId}":`, err))
      .finally(() => hideSubTabLoader(panelEl));
  }
}

// Shows a small spinner overlay on top of the given panel and hides
// whatever content is currently behind it (e.g. data from a previously
// visited sub-tab), so no stale data is visible while a fresh fetch is in
// flight. Works on any panel element, not just top-level .sub-panel
// elements -- it gives the panel relative positioning itself if it
// doesn't already have any, so the overlay covers exactly that panel.
function showSubTabLoader(panelEl) {
  if (!panelEl) return;
  if (getComputedStyle(panelEl).position === 'static') {
    panelEl.style.position = 'relative';
  }
  panelEl.classList.add('sub-panel-loading');
  let overlay = panelEl.querySelector(':scope > .sub-panel-loader-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.className = 'sub-panel-loader-overlay';
    overlay.innerHTML = '<div class="sub-panel-loader-spinner"></div>';
    panelEl.appendChild(overlay);
  }
  overlay.style.display = 'flex';
}

// Hides the spinner overlay added by showSubTabLoader and reveals the
// panel's content again, once the fresh data has finished loading and
// rendering.
function hideSubTabLoader(panelEl) {
  if (!panelEl) return;
  panelEl.classList.remove('sub-panel-loading');
  const overlay = panelEl.querySelector(':scope > .sub-panel-loader-overlay');
  if (overlay) overlay.style.display = 'none';
}