// =========================================================================
// modules/tally/profitLoss.js
// Tally Profit & Loss report: loading and rendering.
// =========================================================================

async function loadProfitLoss() {
  const from = document.getElementById('pl-from-date').value;
  const to = document.getElementById('pl-to-date').value;
  const content = document.getElementById('profit-loss-content');
  
  if (!from || !to) { showToast('Select both dates', '#ef4444'); return; }
  content.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-tertiary)">Loading...</div>';
  
  try {
    const res = await fetch(`/api/tally/profit_loss?from_date=${from}&to_date=${to}`);
    const data = await res.json();
    renderProfitLoss(data);
  } catch(err) {
    content.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-danger)">Error loading profit & loss</div>';
  }
}

function renderProfitLoss(data) {
  const container = document.getElementById('profit-loss-content');
  if (!container) return;
  
  let html = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:10px">
      <div>
        <h4 style="color:#4ade80">INCOME</h4>
        <div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:10px">
  `;
  data.income.forEach(item => {
    html += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:13px">
      <span>${item.ledger_name}</span>
      <span style="color:#4ade80">${fmt(item.balance)}</span>
    </div>`;
  });
  html += `
          <div style="display:flex;justify-content:space-between;padding:8px 0;font-weight:600;border-top:2px solid var(--color-border-secondary)">
            <span>Total Income</span>
            <span style="color:#4ade80">${fmt(data.total_income)}</span>
          </div>
        </div>
      </div>
      <div>
        <h4 style="color:#f87171">EXPENSES</h4>
        <div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:10px">
  `;
  data.expenses.forEach(item => {
    html += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:13px">
      <span>${item.ledger_name}</span>
      <span style="color:#f87171">${fmt(item.balance)}</span>
    </div>`;
  });
  html += `
          <div style="display:flex;justify-content:space-between;padding:8px 0;font-weight:600;border-top:2px solid var(--color-border-secondary)">
            <span>Total Expenses</span>
            <span style="color:#f87171">${fmt(data.total_expenses)}</span>
          </div>
        </div>
      </div>
    </div>
    ${(() => {
      const net = data.net_profit || 0;
      if (Math.abs(net) < 0.01) {
        return `<div style="margin-top:16px;padding:16px;background:rgba(59, 130, 246, 0.15);border:1px solid rgba(59, 130, 246, 0.3);border-radius:var(--border-radius-md);text-align:center;font-size:18px;font-weight:600;color:#60a5fa">
          ⚖️ NO PROFIT / NO LOSS: ${fmt(0)}
        </div>`;
      } else if (net > 0) {
        return `<div style="margin-top:16px;padding:16px;background:var(--color-background-success);border-radius:var(--border-radius-md);text-align:center;font-size:18px;font-weight:600;color:#4ade80">
          ✅ NET PROFIT: ${fmt(net)}
        </div>`;
      } else {
        return `<div style="margin-top:16px;padding:16px;background:var(--color-background-danger);border-radius:var(--border-radius-md);text-align:center;font-size:18px;font-weight:600;color:#f87171">
          ⚠️ NET LOSS: ${fmt(Math.abs(net))}
        </div>`;
      }
    })()}
  `;
  container.innerHTML = html;
}

