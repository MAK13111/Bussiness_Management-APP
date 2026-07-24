// =========================================================================
// modules/tally/trialBalance.js
// Tally Trial Balance report: loading and rendering.
// =========================================================================

async function loadTrialBalance() {
  const date = document.getElementById('tb-date').value;
  const content = document.getElementById('trial-balance-content');
  content.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-tertiary)">Loading...</div>';
  
  try {
    const url = date ? `/api/tally/trial_balance?as_on_date=${date}` : '/api/tally/trial_balance';
    const res = await fetch(url);
    const data = await res.json();
    renderTrialBalance(data);
  } catch(err) {
    content.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-danger)">Error loading trial balance</div>';
  }
}

function renderTrialBalance(data) {
  const container = document.getElementById('trial-balance-content');
  if (!container) return;
  
  let html = `
    <div style="overflow-x:auto;margin-top:1rem">
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr><th>Ledger Name</th><th>Group</th><th style="text-align:right">Debit</th><th style="text-align:right">Credit</th></tr></thead>
        <tbody>
  `;
  let totalDebit = 0, totalCredit = 0;
  data.forEach(row => {
    totalDebit += row.debit || 0;
    totalCredit += row.credit || 0;
    html += `<tr><td>${row.ledger_name}</td><td>${row.group_name}</td><td style="text-align:right">${row.debit ? fmt(row.debit) : '—'}</td><td style="text-align:right">${row.credit ? fmt(row.credit) : '—'}</td></tr>`;
  });
  html += `
        </tbody>
        <tfoot>
          <tr style="font-weight:600;border-top:2px solid var(--color-border-secondary)">
            <td colspan="2">Total</td>
            <td style="text-align:right">${fmt(totalDebit)}</td>
            <td style="text-align:right">${fmt(totalCredit)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
    <div style="margin-top:12px;padding:10px;background:${Math.abs(totalDebit - totalCredit) < 0.01 ? 'var(--color-background-success)' : 'var(--color-background-danger)'};border-radius:var(--border-radius-md);text-align:center">
      ${Math.abs(totalDebit - totalCredit) < 0.01 ? '✅ Trial Balance Balanced' : `⚠️ Difference: ${fmt(Math.abs(totalDebit - totalCredit))}`}
    </div>
  `;
  container.innerHTML = html;
}

