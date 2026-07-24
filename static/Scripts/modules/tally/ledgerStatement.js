// =========================================================================
// modules/tally/ledgerStatement.js
// Tally Ledger Statement report: loading and rendering.
// =========================================================================

let lsPage = 1;
let lsTotal = 0;
const LS_PAGE_SIZE = 100;

// Only the current page's rows are ever held/rendered -- moving to another
// page (Prev/Next or typing a page number) replaces them, it doesn't
// accumulate pages on top of each other. Same pattern as Voucher List.
async function loadLedgerStatement(reset = true) {
    if (reset) lsPage = 1;
    const ledgerId = document.getElementById('ls-ledger').value;
    const from = document.getElementById('ls-from-date').value;
    const to = document.getElementById('ls-to-date').value;
    if (!ledgerId) { showToast('Select a ledger', '#ef4444'); return; }
    try {
        let url = `/api/tally/ledger_statement?ledger_id=${ledgerId}`;
        if (from) url += `&from=${from}`;
        if (to) url += `&to=${to}`;
        url += `&page=${lsPage}&limit=${LS_PAGE_SIZE}`;
        const res = await fetch(url);
        const data = await res.json();
        // {entries,total,page,limit,opening_balance,opening_ledger} when
        // page & limit are passed, same convention as /api/vouchers.
        const rows = data.entries !== undefined ? data.entries : data;
        lsTotal = data.total !== undefined ? data.total : rows.length;
        renderLedgerStatement(rows, ledgerId === 'all', data.opening_balance || 0, data.opening_ledger || null);
        renderPaginationBar('ledger-statement-pagination', lsPage, LS_PAGE_SIZE, lsTotal, gotoLedgerStatementPage);
    } catch (err) {
        showToast('Error loading ledger statement', '#ef4444');
    }
}

async function gotoLedgerStatementPage(page) {
    lsPage = page;
    await loadLedgerStatement(false);
}

function renderLedgerStatement(data, showAllLedgers, openingBalance, openingLedger) {
    const container = document.getElementById('ledger-statement-content');
    if (!container) return;
    if (!data || data.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--color-text-tertiary)">No transactions found for this ledger.</div>';
        return;
    }
    let html = `
        <div style="overflow-x:auto;margin-top:1rem">
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead><tr>${showAllLedgers ? '<th>Ledger</th>' : ''}<th>Date</th><th>Voucher No.</th><th>Type</th><th>Narration</th><th style="text-align:right">Debit</th><th style="text-align:right">Credit</th><th style="text-align:right">Balance</th></tr></thead>
                <tbody>
    `;
    // Carries in from the previous page: 0 / null on page 1, otherwise the
    // running balance (and, in "all ledgers" mode, which ledger it belongs
    // to) as of the last row of the previous page.
    let balance = openingBalance || 0;
    let prevLedger = openingLedger || null;
    data.forEach(row => {
        if (showAllLedgers && row.ledger_name !== prevLedger) {
            balance = 0;
            prevLedger = row.ledger_name;
        }
        balance += (row.debit || 0) - (row.credit || 0);
        html += `<tr>
            ${showAllLedgers ? `<td>${row.ledger_name || ''}</td>` : ''}
            <td>${row.date}</td>
            <td>${row.voucher_number}</td>
            <td>${row.voucher_type}</td>
            <td>${row.narration || ''}</td>
            <td style="text-align:right">${row.debit ? fmt(row.debit) : '—'}</td>
            <td style="text-align:right">${row.credit ? fmt(row.credit) : '—'}</td>
            <td style="text-align:right;font-weight:500">${fmt(balance)}</td>
        </tr>`;
    });
    html += `</tbody></table></div>`;
    container.innerHTML = html;
}

