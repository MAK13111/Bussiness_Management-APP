// =========================================================================
// modules/tally/dayBook.js
// Tally Day Book report: loading and rendering.
// =========================================================================

async function loadDayBook() {
    const date = document.getElementById('db-date').value || new Date().toISOString().split('T')[0];
    try {
        const res = await fetch(`/api/tally/day_book?date=${date}`);
        const data = await res.json();
        renderDayBook(data);
    } catch (err) {
        showToast('Error loading day book', '#ef4444');
    }
}

function renderDayBook(data) {
    const container = document.getElementById('day-book-content');
    if (!container) return;
    if (!data || data.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--color-text-tertiary)">No transactions on this day.</div>';
        return;
    }
    let html = `
        <div style="overflow-x:auto;margin-top:1rem">
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead><tr><th>#</th><th>Voucher No.</th><th>Type</th><th>Party</th><th>Amount</th><th>Narration</th><th></th></tr></thead>
                <tbody>
    `;
    data.forEach((row, i) => {
        html += `<tr>
            <td>${i+1}</td>
            <td>${row.voucher_number}</td>
            <td>${row.voucher_type}</td>
            <td>${row.party_name || '—'}</td>
            <td>${fmt(row.amount || 0)}</td>
            <td>${row.narration || ''}</td>
            <td><button class="info-btn" onclick="viewVoucher(${row.id})"><i class="ti ti-eye"></i></button></td>
        </tr>`;
    });
    html += `</tbody></table></div>`;
    container.innerHTML = html;
}

