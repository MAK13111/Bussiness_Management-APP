// =========================================================================
// modules/tally/balanceSheet.js
// Tally Balance Sheet report: loading and rendering.
// =========================================================================

async function loadBalanceSheet() {
  const date = document.getElementById('bs-date').value;
  const content = document.getElementById('balance-sheet-content');
  content.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-tertiary)">Loading...</div>';
  
  try {
    const url = date ? `/api/tally/balance_sheet?as_on_date=${date}` : '/api/tally/balance_sheet';
    const res = await fetch(url);
    const data = await res.json();
    renderBalanceSheet(data);
  } catch(err) {
    content.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-danger)">Error loading balance sheet</div>';
  }
}

function renderBalanceSheet(data) {
  const container = document.getElementById('balance-sheet-content');
  if (!container) return;
  
  let html = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:10px">
      <div>
        <h4 style="color:var(--color-text-primary);margin-bottom:10px">LIABILITIES & EQUITY</h4>
        <div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:10px">
  `;
  [...data.liabilities, ...data.equity].forEach(item => {
    html += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:13px">
      <span>${item.ledger}</span>
      <span>${fmt(item.balance)}</span>
    </div>`;
  });
  html += `
          <div style="display:flex;justify-content:space-between;padding:8px 0;font-weight:600;border-top:2px solid var(--color-border-secondary)">
            <span>Total Liabilities</span>
            <span>${fmt(data.total_liabilities + data.total_equity)}</span>
          </div>
        </div>
      </div>
      <div>
        <h4 style="color:var(--color-text-primary);margin-bottom:10px">ASSETS</h4>
        <div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:10px">
  `;
  data.assets.forEach(item => {
    html += `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:0.5px solid var(--color-border-tertiary);font-size:13px">
      <span>${item.ledger}</span>
      <span>${fmt(item.balance)}</span>
    </div>`;
  });
  html += `
          <div style="display:flex;justify-content:space-between;padding:8px 0;font-weight:600;border-top:2px solid var(--color-border-secondary)">
            <span>Total Assets</span>
            <span>${fmt(data.total_assets)}</span>
          </div>
        </div>
      </div>
    </div>
    <div style="margin-top:16px;padding:12px;background:${Math.abs(data.total_assets - (data.total_liabilities + data.total_equity)) < 0.01 ? 'var(--color-background-success)' : 'var(--color-background-danger)'};border-radius:var(--border-radius-md);text-align:center">
      ${Math.abs(data.total_assets - (data.total_liabilities + data.total_equity)) < 0.01 ? '✅ Balance Sheet Balanced' : `⚠️ Difference: ${fmt(Math.abs(data.total_assets - (data.total_liabilities + data.total_equity)))}`}
    </div>
  `;
  container.innerHTML = html;
}

