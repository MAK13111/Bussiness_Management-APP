let dashboardCharts = {};

async function loadDashboard() {
  const skeleton = document.getElementById('dashboard-skeleton');
  const content = document.getElementById('dashboard-content');
  if (skeleton) skeleton.style.display = 'none';
  if (content) content.style.display = 'block';

  ['kpi-today-sales', 'kpi-today-purchases', 'kpi-today-profit', 'kpi-cash', 'kpi-receivable', 'kpi-payable'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '₹0.00';
  });

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

    const periodLabels = {
      today: "Today's",
      week: "This Week's",
      month: "This Month's",
      lastmonth: "Last Month's",
      alltime: "All Time",
      custom: "Selected Period's"
    };
    const periodLabelText = periodLabels[period] || "Today's";
    setText('kpi-period-label-1', periodLabelText);
    setText('kpi-period-label-2', periodLabelText);
    setText('kpi-period-label-3', periodLabelText);
    setText('kpi-period-label-4', periodLabelText);
    setText('kpi-period-label-5', periodLabelText);
    setText('kpi-period-label-6', periodLabelText);

    // KPI — exact keys from previous app contract
    const kpi = data.kpi || {};
    setText('kpi-today-sales', fmt(kpi.periodSales));
    setText('kpi-today-purchases', fmt(kpi.periodPurchases));
    setText('kpi-today-profit', fmt(kpi.periodProfit));
    setText('kpi-cash', fmt(kpi.cashSales));
    setText('kpi-receivable', fmt(kpi.receivable));
    setText('kpi-payable', fmt(kpi.payable));
    setText('kpi-total-receivable', fmt(kpi.totalReceivable));
    setText('kpi-total-payable', fmt(kpi.totalPayable));
    setText('kpi-stock-qty', kpi.stockQty || 0);
    setText('kpi-stock-value', fmt(kpi.stockValue));

    // Stock Summary
    const stock = data.stockSummary || {};
    setText('dash-stock-total-products', stock.totalProducts || 0);
    setText('dash-stock-total-qty', stock.totalQuantity || 0);
    setText('dash-stock-total-value', fmt(stock.totalValue));
    setText('dash-stock-low-items', stock.lowStockItems || 0);
    setText('dash-stock-out-items', stock.outOfStockItems || 0);
    setText('dash-stock-top-selling', stock.topSellingProduct || 'N/A');

    // Profit Summary
    const profit = data.profitSummary || {};
    setText('profit-income', fmt(profit.income));
    setText('profit-expenses', fmt(profit.expenses));
    setText('profit-gross', fmt(profit.grossProfit));
    setText('profit-net', fmt(profit.netProfit));

    // Lists
    renderList('dash-recent-activities', data.recentActivities, (a) =>
      `${a.date} – ${a.type} ${a.party ? '· ' + a.party : ''}`
    );
    renderList('dash-recent-purchases', data.recentPurchases, (p) =>
      `${p.date} – ${p.party} ${p.invoiceNo ? '(' + p.invoiceNo + ')' : ''} – ${fmt(p.buyTotal)}`
    );
    renderList('dash-recent-sales', data.recentSales, (s) =>
      `${s.date} – ${s.customerName} ${s.billNo ? '(' + s.billNo + ')' : ''} – ${fmt(s.sellTotal)}`
    );
    renderList('dash-low-stock-alert', data.lowStockAlerts, (item) =>
      `${item.name} – Available: ${item.available} / Min: ${item.min}`
    );

    // Business Summary (today only, from API)
    const biz = data.todayBusiness || {
      purchaseCount: 0, purchaseAmount: 0, salesCount: 0, salesAmount: 0
    };
    setText('biz-purchase-count', biz.purchaseCount);
    setText('biz-sales-count', biz.salesCount);
    setText('biz-purchase-amount', fmt(biz.purchaseAmount));
    setText('biz-sales-amount', fmt(biz.salesAmount));
    setText('biz-profit', fmt(kpi.periodProfit));

    // Top Selling Products
    const topList = document.getElementById('top-products-list');
    if (topList) {
      const tops = data.topProducts || [];
      if (tops.length) {
        topList.innerHTML = tops.map((p, i) =>
          `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:13px;">
            <span>${i + 1}. ${p.name}</span>
            <span>${p.qty} qty · ${fmt(p.revenue)}</span>
          </div>`
        ).join('');
      } else {
        topList.textContent = 'No sales data.';
      }
    }

    renderCharts(data.charts || {});

  } catch (err) {
    console.error('Dashboard load error:', err);
    showErrorInDashboard('Error loading dashboard. Check console.');
    if (skeleton) skeleton.style.display = 'none';
    if (content) content.style.display = 'block';
  }
}

function renderCharts(chartData) {
  if (!chartData) return;

  // Sales vs Purchases (last 7 days)
  const ctx1 = document.getElementById('salesVsPurchaseChart');
  if (ctx1) {
    if (dashboardCharts.salesVsPurchase) dashboardCharts.salesVsPurchase.destroy();
    const rows = chartData.salesVsPurchase || [];
    dashboardCharts.salesVsPurchase = new Chart(ctx1, {
      type: 'bar',
      data: {
        labels: rows.map(d => (d.date || '').slice(5)),
        datasets: [
          { label: 'Sales', data: rows.map(d => d.sales), backgroundColor: '#4ade80', borderRadius: 4 },
          {
            label: 'Purchases',
            data: rows.map(d => d.purchases),
            backgroundColor: '#f87171',
            borderRadius: 4,
            // stash the GST-inclusive amount per bar so the tooltip can show it
            purchasesWithGst: rows.map(d => d.purchasesWithGst)
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#a0a0b0' } },
          tooltip: {
            callbacks: {
              label: function(context) {
                if (context.dataset.label === 'Purchases') {
                  const withGst = context.dataset.purchasesWithGst
                    ? context.dataset.purchasesWithGst[context.dataIndex]
                    : null;
                  return `Purchases: ${fmt(context.parsed.y)} (with GST: ${fmt(withGst)})`;
                }
                return `${context.dataset.label}: ${fmt(context.parsed.y)}`;
              }
            }
          }
        },
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
    const rows = chartData.monthlyProfit || [];
    dashboardCharts.monthlyProfit = new Chart(ctx2, {
      type: 'line',
      data: {
        labels: rows.map(d => d.month),
        datasets: [{
          label: 'Profit',
          data: rows.map(d => d.profit),
          borderColor: '#818cf8',
          tension: 0.2,
          fill: false
        }]
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
        datasets: [{
          data: modes.map(d => d.amount),
          backgroundColor: ['#4ade80', '#818cf8', '#fbbf24', '#f87171']
        }]
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
  const containers = document.querySelectorAll(
    '#dashboard-content [id^="dash-"], #dashboard-content [id^="kpi-"], #dashboard-content [id^="stock-"], #dashboard-content [id^="profit-"], #dashboard-content [id^="biz-"]'
  );
  containers.forEach(el => {
    if (el.textContent === 'Loading...' || el.textContent === 'Loading') {
      el.textContent = msg;
    }
  });
}
