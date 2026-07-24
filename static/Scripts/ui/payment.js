// =========================================================================
// ui/payment.js
// Borrow lists (shared between purchases and sales) and the payment
// modal used to record a partial/full payment against a borrow entry.
// =========================================================================

let borrowPage = { purchase: 1, sales: 1 };
const BORROW_PAGE_SIZE = 100; // matches Voucher List / Ledgers -- 100 rows per page

async function loadBorrowData(type) {
    const prefix = type === 'purchase' ? 'pborrow' : 'sborrow';

    // --- Update Summary Cards ---
    try {
        const sumRes = await fetch(`/api/borrow/summary?type=${type}`);
        const sumData = await sumRes.json();
        document.getElementById(`${prefix}-total`).textContent = fmt(sumData.total_borrow);
        document.getElementById(`${prefix}-pending-count`).textContent = sumData.pending_bills;
        document.getElementById(`${prefix}-paid-today`).textContent = fmt(sumData.paid_today);
        document.getElementById(`${prefix}-overdue-count`).textContent = sumData.overdue_bills;
    } catch (e) {
        console.error('Error loading borrow summary:', e);
    }

    // --- Build query parameters ---
    const search = document.getElementById(`${prefix}-search`).value.trim();
    const dateFrom = document.getElementById(`${prefix}-date-from`).value;
    const dateTo = document.getElementById(`${prefix}-date-to`).value;
    const status = document.getElementById(`${prefix}-status`).value;
    const sort = document.getElementById(`${prefix}-sort`).value;

    const params = new URLSearchParams();
    params.append('type', type);
    if (search) params.append('search', search);
    if (dateFrom) params.append('date_from', dateFrom);
    if (dateTo) params.append('date_to', dateTo);
    if (status && status !== '') params.append('status', status);
    if (sort) params.append('sort', sort);
    params.append('page', borrowPage[type] || 1);
    params.append('limit', BORROW_PAGE_SIZE);

    try {
        const res = await fetch(`/api/borrow/list?${params.toString()}`);
        const data = await res.json();
        renderBorrowTable(type, data);
    } catch (e) {
        console.error('Error loading borrow list:', e);
    }
}

function renderBorrowTable(type, data) {
    const prefix = type === 'purchase' ? 'pborrow' : 'sborrow';
    const tbody = document.getElementById(`${prefix}-tbody`);
    const empty = document.getElementById(`${prefix}-empty`);
    const pagination = document.getElementById(`${prefix}-pagination`);

    if (!data || data.rows.length === 0) {
        tbody.innerHTML = '';
        empty.style.display = 'flex';
        pagination.innerHTML = '';
        pagination.style.display = 'none';
        return;
    }
    empty.style.display = 'none';

    let html = '';
    data.rows.forEach(row => {
        const statusClass = row.display_status ? row.display_status.toLowerCase() : 'pending';
        const statusBadge = `<span class="status-badge ${statusClass}">${row.display_status || row.status}</span>`;

        html += `<tr class="status-${statusClass}">
            <td>${row.created_at ? row.created_at.slice(0,10) : '-'}</td>
            <td><strong>${row.bill_no || '-'}</strong></td>
            <td>${row.party_name || '-'}</td>
            <td>${row.phone || '-'}</td>
            <td>${fmt(row.total)}</td>
            <td>${fmt(row.paid)}</td>
            <td>${fmt(row.balance)}</td>
            <td>${row.due_date || '-'}</td>
            <td>${statusBadge}</td>
            <td>
                <div class="borrow-actions">
                    ${row.status !== 'Paid' ? `<button class="btn-pay" onclick="openPaymentModal('${type}', ${row.id})"><i class="ti ti-credit-card"></i> Pay</button>` : ''}
                    <button class="btn-history" onclick="viewPaymentHistory('${type}', ${row.id},'${(row.party_name||'').replace(/'/g,'')}','${row.bill_no||''}',${row.total||0},${row.paid||0},${row.balance||0},'${row.display_status||row.status||''}','${row.due_date||''}')"><i class="ti ti-clock"></i></button>
                </div>
            </td>
        </tr>`;
    });
    tbody.innerHTML = html;

    // Pagination -- same Prev/Next + "Page X of Y" bar as Voucher List /
    // Manage Ledgers, 100 rows per page.
    renderPaginationBar(pagination.id, data.page, BORROW_PAGE_SIZE, data.total, (page) => loadBorrowPage(type, page));
}

function loadBorrowPage(type, page) {
    if (page < 1) return;
    borrowPage[type] = page;
    loadBorrowData(type);
}

function applyBorrowFilters(type) {
    borrowPage[type] = 1; // reset to first page
    loadBorrowData(type);
}

function resetBorrowFilters(type) {
    const prefix = type === 'purchase' ? 'pborrow' : 'sborrow';
    document.getElementById(`${prefix}-search`).value = '';
    document.getElementById(`${prefix}-date-from`).value = '';
    document.getElementById(`${prefix}-date-to`).value = '';
    document.getElementById(`${prefix}-status`).value = '';
    document.getElementById(`${prefix}-sort`).value = 'date_desc';
    borrowPage[type] = 1;
    loadBorrowData(type);
}

function setBorrowDateFilter(type, period) {
    const prefix = type === 'purchase' ? 'pborrow' : 'sborrow';
    const today = new Date();
    let from = new Date(today);
    let to = new Date(today);
    if (period === 'today') {
        // keep as today
    } else if (period === 'yesterday') {
        from.setDate(from.getDate() - 1);
        to = new Date(from);
    } else if (period === 'week') {
        from.setDate(from.getDate() - from.getDay());
    } else if (period === 'month') {
        from.setDate(1);
    } else if (period === 'lastmonth') {
        from.setMonth(from.getMonth() - 1);
        from.setDate(1);
        to = new Date(from.getFullYear(), from.getMonth() + 1, 0);
    }
    document.getElementById(`${prefix}-date-from`).value = from.toISOString().slice(0,10);
    document.getElementById(`${prefix}-date-to`).value = to.toISOString().slice(0,10);
    applyBorrowFilters(type);
}

// ─── PAYMENT MODAL ─────────────────────────────────────────

let currentPayment = { type: null, borrowId: null };

function openPaymentModal(type, borrowId) {
    currentPayment.type = type;
    currentPayment.borrowId = borrowId;

    // Fetch the specific borrow record to populate details
    fetch(`/api/borrow/list?type=${type}&id=${borrowId}`)
        .then(res => res.json())
        .then(data => {
            const row = data.rows[0];
            if (!row) return;
            document.getElementById('pay-party').textContent = row.party_name || '-';
            document.getElementById('pay-billno').textContent = row.bill_no || '-';
            document.getElementById('pay-total').textContent = fmt(row.total);
            document.getElementById('pay-paid').textContent = fmt(row.paid);
            document.getElementById('pay-balance').textContent = fmt(row.balance);
            document.getElementById('pay-amount').value = '';
            document.getElementById('pay-date').value = new Date().toISOString().split('T')[0];
            document.getElementById('pay-mode').value = 'Cash';
            document.getElementById('pay-ref').value = '';
            document.getElementById('pay-notes').value = '';

            // Load payment history
            loadPaymentHistory(type, borrowId);

            document.getElementById('payment-modal').classList.add('active');
        })
        .catch(e => console.error('Error loading borrow details:', e));
}

function closePaymentModal() {
    document.getElementById('payment-modal').classList.remove('active');
}

async function loadPaymentHistory(type, borrowId) {
    const container = document.getElementById('pay-history');
    const list = document.getElementById('pay-history-list');
    try {
        const res = await fetch(`/api/borrow/history?borrow_type=${type}&borrow_id=${borrowId}`);
        const data = await res.json();
        if (data.length === 0) {
            container.style.display = 'none';
            return;
        }
        container.style.display = 'block';
        list.innerHTML = data.map(p => `
            <li>
                <span class="pay-date">${p.payment_date}</span>
                <span class="pay-amount">${fmt(p.amount)}</span>
                <span class="pay-mode">${p.payment_mode}${p.reference_no ? ' · '+p.reference_no : ''}</span>
            </li>
        `).join('');
    } catch (e) {
        container.style.display = 'none';
    }
}

async function savePayment() {
    const amount = parseFloat(document.getElementById('pay-amount').value);
    if (!amount || amount <= 0) {
        showToast('Enter a valid positive amount', '#ef4444');
        return;
    }
    const payment_date = document.getElementById('pay-date').value;
    const payment_mode = document.getElementById('pay-mode').value;
    const reference_no = document.getElementById('pay-ref').value.trim();
    const notes = document.getElementById('pay-notes').value.trim();

    const payload = {
        borrow_type: currentPayment.type,
        borrow_id: currentPayment.borrowId,
        amount: amount,
        payment_date: payment_date,
        payment_mode: payment_mode,
        reference_no: reference_no,
        notes: notes
    };

    try {
        const res = await fetch('/api/borrow/payment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'ok') {
            const label = data.payment_status === 'Paid' ? 'Bill fully paid!' : 'Partial payment recorded';
            const color = data.payment_status === 'Paid' ? '#16a34a' : '#2563eb';
            showToast(label, color);
            closePaymentModal();
            loadBorrowData(currentPayment.type);
        } else {
            showToast(data.error || 'Payment failed', '#ef4444');
        }

    } catch (e) {
        showToast('Network error', '#ef4444');
    }
}

function viewPaymentHistory(type, borrowId, party, bill, total, paid, balance, status, due) {
    const m = { party, bill, total, paid, balance, status, due };
    const statusColor = {
        'Paid':    { bg: 'var(--color-background-success)', text: 'var(--color-text-success)' },
        'Partial': { bg: 'var(--color-background-info)',    text: 'var(--color-text-info)'    },
        'Overdue': { bg: 'var(--color-background-danger)',  text: 'var(--color-text-danger)'  },
        'Pending': { bg: 'var(--color-background-tertiary)', text: 'var(--color-text-secondary)' }
    };
    const sc = statusColor[m.status] || statusColor['Pending'];

    fetch(`/api/borrow/history?borrow_type=${type}&borrow_id=${borrowId}`)
        .then(res => res.json())
        .then(payments => {
            let payRows = '';
            if (!payments || payments.length === 0) {
                payRows = `<tr><td colspan="4" style="text-align:center;padding:1.5rem;color:var(--color-text-tertiary);font-style:italic">No payments recorded yet</td></tr>`;
            } else {
                payments.forEach(p => {
                    payRows += `
                    <tr style="border-bottom:1px solid var(--color-border-tertiary,rgba(255,255,255,.06));transition:background .15s" onmouseover="this.style.background='var(--color-background-tertiary)'" onmouseout="this.style.background='transparent'">
                        <td style="padding:10px 12px;font-size:13px">
                            <div style="font-weight:500">${p.payment_date || '-'}</div>
                            ${p.notes ? `<div style="font-size:11px;color:var(--color-text-tertiary);margin-top:2px">${p.notes}</div>` : ''}
                        </td>
                        <td style="padding:10px 12px;text-align:right">
                            <span style="font-weight:700;font-size:14px;color:var(--color-text-success)">${fmt(p.amount)}</span>
                        </td>
                        <td style="padding:10px 12px">
                            <span style="display:inline-flex;align-items:center;gap:5px;background:var(--color-background-info);color:var(--color-text-info);border-radius:6px;padding:2px 8px;font-size:12px;font-weight:500">
                                ${p.payment_mode === 'Cash' ? '💵' : p.payment_mode === 'UPI' ? '📲' : p.payment_mode === 'Bank' ? '🏦' : p.payment_mode === 'Card' ? '💳' : '💰'}
                                ${p.payment_mode || '-'}
                            </span>
                        </td>
                        <td style="padding:10px 12px;font-size:12px;color:var(--color-text-secondary)">${p.reference_no || '—'}</td>
                    </tr>`;
                });
            }

            const totalVal = parseFloat(m.total) || 0;
            const paidVal  = parseFloat(m.paid)  || 0;
            const pct      = totalVal > 0 ? Math.min(100, (paidVal / totalVal) * 100) : 0;
            const pctStr   = pct.toFixed(0);

            const html = `
            <div style="background:var(--color-background-secondary,#161618);border-radius:16px;width:min(520px,94vw);max-height:86vh;overflow:hidden;display:flex;flex-direction:column;box-shadow:var(--shadow-card)">

                <div style="padding:1.25rem 1.5rem 0;background:var(--color-background-gradient,linear-gradient(135deg,#6366f1,#4f46e5));border-radius:16px 16px 0 0;position:relative">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start">
                        <div>
                            <div style="font-size:11px;font-weight:600;letter-spacing:.08em;color:rgba(255,255,255,.6);text-transform:uppercase;margin-bottom:4px">Payment History</div>
                            <div style="font-size:18px;font-weight:700;color:#fff">${m.party || 'Party'}</div>
                            <div style="font-size:12px;color:rgba(255,255,255,.7);margin-top:2px">Bill: <strong>${m.bill || '-'}</strong>${m.due && m.due !== '-' ? ' &nbsp;·&nbsp; Due: <strong>' + m.due + '</strong>' : ''}</div>
                        </div>
                        <button onclick="this.closest('[data-ph-overlay]').remove()" style="background:rgba(255,255,255,.15);border:none;color:#fff;width:30px;height:30px;border-radius:50%;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px;backdrop-filter:blur(4px)">✕</button>
                    </div>

                    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:1rem;padding-bottom:1rem">
                        <div style="background:rgba(0,0,0,.2);border-radius:10px;padding:10px;text-align:center;backdrop-filter:blur(4px)">
                            <div style="font-size:11px;color:rgba(255,255,255,.6);margin-bottom:3px">Total</div>
                            <div style="font-size:15px;font-weight:700;color:#fff">${fmt(m.total)}</div>
                        </div>
                        <div style="background:rgba(0,0,0,.2);border-radius:10px;padding:10px;text-align:center;backdrop-filter:blur(4px)">
                            <div style="font-size:11px;color:rgba(255,255,255,.6);margin-bottom:3px">Paid</div>
                            <div style="font-size:15px;font-weight:700;color:#86efac">${fmt(m.paid)}</div>
                        </div>
                        <div style="background:rgba(0,0,0,.2);border-radius:10px;padding:10px;text-align:center;backdrop-filter:blur(4px)">
                            <div style="font-size:11px;color:rgba(255,255,255,.6);margin-bottom:3px">Balance</div>
                            <div style="font-size:15px;font-weight:700;color:${parseFloat(m.balance) > 0 ? '#fca5a5' : '#86efac'}">${fmt(m.balance)}</div>
                        </div>
                    </div>

                    <div style="padding-bottom:1rem">
                        <div style="display:flex;justify-content:space-between;font-size:11px;color:rgba(255,255,255,.6);margin-bottom:5px">
                            <span>Payment progress</span>
                            <span>${pctStr}% paid</span>
                        </div>
                        <div style="background:rgba(0,0,0,.3);border-radius:99px;height:7px;overflow:hidden">
                            <div style="height:100%;width:${pctStr}%;background:${pct>=100?'#86efac':'#818cf8'};border-radius:99px"></div>
                        </div>
                    </div>

                    <div style="position:absolute;top:1.25rem;left:50%;transform:translateX(-50%)">
                        <span style="background:${sc.bg};color:${sc.text};font-size:11px;font-weight:600;letter-spacing:.06em;padding:3px 10px;border-radius:99px;text-transform:uppercase">${m.status || 'Pending'}</span>
                    </div>
                </div>

                <div style="overflow-y:auto;flex:1;padding:0 .5rem .5rem">
                    <table style="width:100%;border-collapse:collapse">
                        <thead>
                            <tr style="position:sticky;top:0;background:var(--color-background-secondary)">
                                <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;letter-spacing:.07em;color:var(--color-text-tertiary);text-transform:uppercase;border-bottom:1px solid var(--color-border-secondary)">Date</th>
                                <th style="padding:10px 12px;text-align:right;font-size:11px;font-weight:600;letter-spacing:.07em;color:var(--color-text-tertiary);text-transform:uppercase;border-bottom:1px solid var(--color-border-secondary)">Amount</th>
                                <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;letter-spacing:.07em;color:var(--color-text-tertiary);text-transform:uppercase;border-bottom:1px solid var(--color-border-secondary)">Mode</th>
                                <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:600;letter-spacing:.07em;color:var(--color-text-tertiary);text-transform:uppercase;border-bottom:1px solid var(--color-border-secondary)">Ref</th>
                            </tr>
                        </thead>
                        <tbody>${payRows}</tbody>
                    </table>
                </div>

                <div style="padding:.75rem 1.5rem;border-top:1px solid var(--color-border-secondary);display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:12px;color:var(--color-text-tertiary)">${payments ? payments.length : 0} payment${payments && payments.length !== 1 ? 's' : ''} recorded</span>
                    <button onclick="this.closest('[data-ph-overlay]').remove()" style="background:var(--color-background-tertiary);border:1px solid var(--color-border-secondary);color:var(--color-text-primary);padding:6px 18px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:500">Close</button>
                </div>
            </div>`;

            const overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:1rem;backdrop-filter:blur(3px)';
            overlay.setAttribute('data-ph-overlay', '1');
            overlay.innerHTML = html;
            overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
            document.body.appendChild(overlay);
        })
        .catch(e => {
            console.error(e);
            showToast('Could not load payment history', '#ef4444');
        });
}

