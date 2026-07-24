// =========================================================================
// main.js
// App-wide shared state (current tab, current mode, the in-memory
// purchase/sale entry lists used across many modules), the core
// loading/rendering of those entry lists, and the app's startup
// (DOMContentLoaded) sequence. Loaded last so every other module's
// functions are already defined when startup runs.
// =========================================================================

let currentMain = 'dashboard';
let currentSub = null;
let purchaseMode = 'cash';      // Default to cash
let saleMode = 'cash';          // Default to cash
let itemRowCount = 0;
let itemSizeData = {};
let scannedItems = [];
let showPurchasePrice = false; // Purchase Price total row hidden by default

// ─── PURCHASE & SELL ENTRIES (shared across modules) ─────────────────────────────────────────

let entries = [];
let currentType = 'purchase';
let currentMode = 'cash';
let sellEntries = [];
let departments = [];
let purchaseQuery = '';
let purchaseFilters = {};
let sellQuery = '';
let sellFilters = {};

async function loadEntries() {
  const res = await fetch(`/api/entries?type=purchase&mode=${currentMode}`);
  entries = await res.json();
  renderPurchase();
  if (currentType === 'analyze') renderAnalyzePurchase();
}

async function loadSellEntries() {
  const res = await fetch(`/api/entries?type=sell&mode=${currentMode}`);
  sellEntries = await res.json();
  renderSell();
  if (currentType === 'analyze') renderAnalyzeSell();
}

// Lightweight versions of the two functions above: they only pull the
// aggregate numbers (count/qty/totals) that the Purchase Stats / Sell
// Stats cards on Reports > Analyze show, via a single SQL SUM query on the
// server (/api/entries/stats) -- not every matching row. Opening the
// Reports tab used to call loadEntries()+loadSellEntries() (full 275k+ /
// 310k+ row fetches) just to fill in these five numbers each; that was the
// actual remaining cause of "Reports tab bahut der se open hota hai".
// The full-row loadEntries()/loadSellEntries() above are still used, but
// only where the real row data is needed (currently: the Sold Items view).
async function loadPurchaseStats() {
  const res = await fetch(`/api/entries/stats?type=purchase&mode=${currentMode}`);
  const s = await res.json();
  updateStats(s.count, s.qty, s.buyTotal, s.sellTotal, s.profit);
}

async function loadSellStats() {
  const res = await fetch(`/api/entries/stats?type=sell&mode=${currentMode}`);
  const s = await res.json();
  updateSellStats(s.count, s.qty, s.buyTotal, s.sellTotal, s.profit);
}

// Fetches only purchase rows with sold > 0 (server-side filtered -- see
// sold_only param in routes/legacy.py) for the Sold Items view. Deliberately
// separate from loadEntries(): that function also recomputes the Purchase
// Stats cards from whatever it just fetched, so reusing it here would make
// those cards wrongly show only the sold subset instead of the true totals.
async function loadSoldEntries() {
  const res = await fetch(`/api/entries?type=purchase&mode=${currentMode}&sold_only=1`);
  entries = await res.json();
}

function renderPurchase() {
  // Purchase Stats cards (also shown at the top of Reports > Analyze) are
  // computed with a plain loop every single time, regardless of which tab
  // is on screen -- this scan is cheap even for thousands of rows.
  let tQty = 0, tBuy = 0, tSell = 0, tProfit = 0;
  for (const e of entries) {
    tQty += +e.qty; tBuy += +e.buyTotal; tSell += +e.sellTotal; tProfit += +e.profit;
  }
  updateStats(entries.length, tQty, tBuy, tSell, tProfit);

  // The old Purchase-tab list table (#tbody/#tfoot/#empty-msg/#count-badge)
  // was already removed from purchases.html -- entries are only browsed via
  // Reports > Purchase & Sales reports now (see the comment in
  // purchases.html). Those elements no longer exist in the DOM at all, so
  // there is nothing left to rebuild here; the stats above are the only
  // thing this function still needs to produce. (Previously this still
  // built an `entries.map(...)` HTML string for a permanently-hidden
  // placeholder table on every call -- on 275k+ rows that alone was a real
  // chunk of the "feels laggy" time, for a table nobody could ever see.)
}

function renderSell() {
  // Sell Stats cards (also shown at the top of Reports > Analyze) are
  // computed with a plain loop every single time, regardless of which tab
  // is on screen -- this scan is cheap even for thousands of rows.
  let tQty = 0, tBuy = 0, tSell = 0, tProfit = 0;
  for (const e of sellEntries) {
    tQty += +e.qty; tBuy += +e.buyTotal; tSell += +e.sellTotal; tProfit += +e.profit;
  }
  updateSellStats(sellEntries.length, tQty, tBuy, tSell, tProfit);

  // Same situation as renderPurchase() above: the old Sell-tab list table
  // (#sell-tbody/#sell-tfoot/#sell-empty-msg/#sell-count-badge) was already
  // removed from sales.html -- entries are only browsed via Reports >
  // Purchase & Sales reports now. Nothing left to rebuild here; stats above
  // are all this function still needs to produce.
}

function updateStats(count, qty, buy, sell, profit) {
  document.getElementById('s-entries').textContent = count;
  document.getElementById('s-qty').textContent     = qty;
  document.getElementById('s-purchase').textContent= fmt(buy);
  document.getElementById('s-sell').textContent    = fmt(sell);
  document.getElementById('s-profit').textContent  = fmt(profit);
}

function updateSellStats(count, qty, buy, sell, profit) {
  document.getElementById('ss-entries').textContent = count;
  document.getElementById('ss-qty').textContent     = qty;
  document.getElementById('ss-purchase').textContent= fmt(buy);
  document.getElementById('ss-sell').textContent    = fmt(sell);
  document.getElementById('ss-profit').textContent  = fmt(profit);
}

// ─── APP STARTUP ─────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  // Date filter toggle
  const periodSelect = document.getElementById('dashboard-period');
  const customRange = document.getElementById('custom-date-range');
  if (periodSelect) {
    periodSelect.addEventListener('change', function() {
      if (this.value === 'custom') {
        customRange.style.display = 'flex';
      } else {
        customRange.style.display = 'none';
      }
    });
  }
  // Initial load
  loadDashboard();
  loadDepartments().then(() => {
    addItemRow();
  }).catch(() => {
    addItemRow();
  });
  loadParties();
  loadAccounts();
  // loadItems() intentionally NOT called here -- Items is a large-data
  // tab and already loads on-demand when it's opened (core/navigation.js:
  // 'items-stock' / 'items-list'). Calling it unconditionally at startup
  // meant it loaded even while sitting on the Dashboard tab.
  // loadVouchers() intentionally NOT called here -- it already loads
  // on-demand when the Tally/Vouchers tab is opened (core/navigation.js).
  // Calling it unconditionally at startup meant every single page load
  // ran the expensive per-row-subquery /api/vouchers query even if the
  // person never opens the Tally tab -- this was likely the single
  // biggest contributor to "app lags on open" at real-world data volume.
  populateYearDropdown();
  // Default dates for reports
  const today = new Date().toISOString().split('T')[0];
  const firstDay = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0];
  document.querySelectorAll('#tb-date, #bs-date, #db-date').forEach(el => { if (el) el.value = today; });
  document.querySelectorAll('#pl-from-date, #ls-from-date').forEach(el => { if (el) el.value = firstDay; });
  document.querySelectorAll('#pl-to-date, #ls-to-date').forEach(el => { if (el) el.value = today; });
});