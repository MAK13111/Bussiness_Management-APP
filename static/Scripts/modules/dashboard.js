// =========================================================================
// modules/dashboard.js
// Loads and renders the main Dashboard panel: summary stats, charts,
// and the recent purchases / sells lists.
// =========================================================================

let dashboardCharts = {};

async function loadDashboard() {
  const skeleton = document.getElementById('dashboard-skeleton');
  const content = document.getElementById('dashboard-content');
  if (skeleton) skeleton.style.display = 'block';
  if (content) content.style.display = 'none';

  const period = document.getElementById('dashboard-period')?.value || 'today';
  let url = '/api/dashboard?period=' + period;
  if (period === 'custom') {
    const from = document.getElementById('from-date')?.value;
    const to = document.getElementById('to-date')?.value;
    if (from && to) url += `&from=${from}&to=${to}`;
  }

  try {
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.text();
      console.error('Dashboard API error:', err);
      showErrorInDashboard('Failed to load data.');
      return;
    }
    const data = await res.json();
    if (data.error) {
      console.error('Dashboard error:', data.error);
      showErrorInDashboard('Error: ' + data.error);
      return;
    }

    if (skeleton) skeleton.style.display = 'none';
    if (content) content.style.display = 'block';

    function setText(id, value) {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    }

    // Update the "Today's" / "This Week's" / etc. prefix on the KPI cards
    // so the labels always match what period is actually being shown.
    const periodLabels = {
      today: "Today's",
      week: "This Week's",
      month: "This Month's",
      custom: "Selected Period's"
    };
    const periodLabelText = periodLabels[period] || "Today's";
    setText('kpi-period-label-1', periodLabelText);
    setText('kpi-period-label-2', periodLabelText);
    setText('kpi-period-label-3', periodLabelText);
    setText('kpi-period-label-4', periodLabelText);
    setText('kpi-period-label-5', periodLabelText);
    setText('kpi-period-label-6', periodLabelText);

    // KPI Cards
    setText('kpi-today-sales', fmt(data.kpi.periodSales));
    setText('kpi-today-purchases', fmt(data.kpi.periodPurchases));
    setText('kpi-today-profit', fmt(data.kpi.periodProfit));
    setText('kpi-cash', fmt(data.kpi.cashInHand));
    setText('kpi-receivable', fmt(data.kpi.receivable));
    setText('kpi-payable', fmt(data.kpi.payable));
    setText('kpi-total-receivable', fmt(data.kpi.totalReceivable));
    setText('kpi-total-payable', fmt(data.kpi.totalPayable));
    setText('kpi-stock-qty', data.kpi.stockQty || 0);
    setText('kpi-stock-value', fmt(data.kpi.stockValue));

    // Stock Summary
    setText('stock-total-products', data.stockSummary.totalProducts || 0);
    setText('stock-total-qty', data.stockSummary.totalQuantity || 0);
    setText('stock-total-value', fmt(data.stockSummary.totalValue));
    setText('stock-low-items', data.stockSummary.lowStockItems || 0);
    setText('stock-out-items', data.stockSummary.outOfStockItems || 0);
    setText('stock-top-selling', data.stockSummary.topSellingProduct || 'N/A');

    // Financial Summary
    setText('fin-cash', fmt(data.financial.cash));
    setText('fin-bank', fmt(data.financial.bank));
    setText('fin-receivable', fmt(data.financial.receivable));
    setText('fin-payable', fmt(data.financial.payable));
    setText('fin-gst', fmt(data.financial.gstPayable));

    // Profit Summary
    setText('profit-income', fmt(data.profitSummary.income));
    setText('profit-expenses', fmt(data.profitSummary.expenses));
    setText('profit-gross', fmt(data.profitSummary.grossProfit));
    setText('profit-net', fmt(data.profitSummary.netProfit));

    // Lists
    renderList('dash-recent-activities', data.recentActivities, (a) =>
      `${a.date} – ${a.type} ${a.party ? '· ' + a.party : ''}`
    );
    renderList('dash-recent-purchases', data.recentPurchases, (p) =>
      `${p.date} – ${p.party} ${p.invoiceNo ? '('+p.invoiceNo+')' : ''} – ${fmt(p.buyTotal)}`
    );
    renderList('dash-recent-sales', data.recentSales, (s) =>
      `${s.date} – ${s.customerName} ${s.billNo ? '('+s.billNo+')' : ''} – ${fmt(s.sellTotal)}`
    );
    renderList('dash-low-stock-alert', data.lowStockAlerts, (item) =>
      `${item.name} – Available: ${item.available} / Min: ${item.min}`
    );

    // Business Summary -- counts/amounts now come straight from the API
    // (data.todayBusiness, computed with SQL COUNT/SUM). Previously this was
    // derived by filtering the 5-row "recent purchases/sales" list down to
    // today's date, which undercounted whenever more than 5 bills happened
    // today. JS here only formats, it doesn't compute.
    const biz = data.todayBusiness || { purchaseCount: 0, purchaseAmount: 0, salesCount: 0, salesAmount: 0 };
    setText('biz-purchase-count', biz.purchaseCount);
    setText('biz-sales-count', biz.salesCount);
    setText('biz-purchase-amount', fmt(biz.purchaseAmount));
    setText('biz-sales-amount', fmt(biz.salesAmount));
    // NOTE: biz-profit uses the selected period's profit (kpi.periodProfit), so it
    // only lines up exactly with biz-purchase/sales-amount when period === 'today'.
    setText('biz-profit', fmt(data.kpi.periodProfit));

    // Top Selling Products
    const topList = document.getElementById('top-products-list');
    if (topList) {
      if (data.topProducts && data.topProducts.length) {
        topList.innerHTML = data.topProducts.map((p, i) =>
          `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:13px;">
            <span>${i+1}. ${p.name}</span>
            <span>${p.qty} qty · ${fmt(p.revenue)}</span>
          </div>`
        ).join('');
      } else {
        topList.textContent = 'No sales data.';
      }
    }

    renderCharts(data.charts);

  } catch (err) {
    console.error('Dashboard load error:', err);
    showErrorInDashboard('Error loading dashboard. Check console.');
    if (skeleton) skeleton.style.display = 'none';
    if (content) content.style.display = 'block';
  }
}

function renderCharts(chartData) {
  // Sales vs Purchase
  const ctx1 = document.getElementById('salesVsPurchaseChart');
  if (ctx1) {
    if (dashboardCharts.salesVsPurchase) dashboardCharts.salesVsPurchase.destroy();
    dashboardCharts.salesVsPurchase = new Chart(ctx1, {
      type: 'bar',
      data: {
        labels: chartData.salesVsPurchase.map(d => d.date.slice(5)),
        datasets: [
          { label: 'Sales', data: chartData.salesVsPurchase.map(d => d.sales), backgroundColor: '#4ade80', borderRadius: 4 },
          { label: 'Purchases', data: chartData.salesVsPurchase.map(d => d.purchases), backgroundColor: '#f87171', borderRadius: 4 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#a0a0b0' } } },
        scales: {
          y: { ticks: { color: '#a0a0b0' }, grid: { color: '#2a2a32' } },
          x: { ticks: { color: '#a0a0b0' }, grid: { display: false } }
        }
      }
    });
  }

  // Monthly Profit
  const ctx2 = document.getElementById('monthlyProfitChart');
  if (ctx2) {
    if (dashboardCharts.monthlyProfit) dashboardCharts.monthlyProfit.destroy();
    dashboardCharts.monthlyProfit = new Chart(ctx2, {
      type: 'line',
      data: {
        labels: chartData.monthlyProfit.map(d => d.month),
        datasets: [{ label: 'Profit', data: chartData.monthlyProfit.map(d => d.profit), borderColor: '#818cf8', tension: 0.2, fill: false }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#a0a0b0' } } },
        scales: {
          y: { ticks: { color: '#a0a0b0' }, grid: { color: '#2a2a32' } },
          x: { ticks: { color: '#a0a0b0' }, grid: { display: false } }
        }
      }
    });
  }

  // Payment Mode Distribution
  const ctx3 = document.getElementById('paymentModeChart');
  if (ctx3) {
    if (dashboardCharts.paymentMode) dashboardCharts.paymentMode.destroy();
    const modes = chartData.paymentModeDistribution || [];
    dashboardCharts.paymentMode = new Chart(ctx3, {
      type: 'doughnut',
      data: {
        labels: modes.map(d => d.mode),
        datasets: [{ data: modes.map(d => d.amount), backgroundColor: ['#4ade80', '#818cf8', '#fbbf24', '#f87171'] }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#a0a0b0' } } }
      }
    });
  }
}

function renderList(containerId, items, formatter) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!items || items.length === 0) {
    el.textContent = 'No data available.';
    return;
  }
  el.innerHTML = items.map((item, idx) => `
    <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:12px">
      <span>${formatter(item, idx)}</span>
    </div>
  `).join('');
}

function showErrorInDashboard(msg) {
  const containers = document.querySelectorAll('#dashboard-content [id^="dash-"], #dashboard-content [id^="kpi-"], #dashboard-content [id^="stock-"], #dashboard-content [id^="fin-"], #dashboard-content [id^="profit-"], #dashboard-content [id^="biz-"]');
  containers.forEach(el => {
    if (el.textContent === 'Loading...' || el.textContent === 'Loading') {
      el.textContent = msg;
    }
  });
}

