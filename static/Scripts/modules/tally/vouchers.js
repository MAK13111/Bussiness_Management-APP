// =========================================================================
// modules/tally/vouchers.js
// Tally vouchers: listing, viewing, deleting, filtering, and saving
// Payment / Receipt / Contra / Journal vouchers. Includes helper
// functions to resolve (or auto-create) the ledgers a voucher needs.
// =========================================================================

let editingVoucherId = null;
let editingVoucherType = null;
let editingVoucherSide = null; // 'DEBIT' (From side) or 'CREDIT' (To side) — only used for JOURNAL

let vchPage = 1;
let vchTotal = 0;
const VCH_PAGE_SIZE = 100;

// Only the current page's vouchers are ever held/rendered -- moving to
// another page (Prev/Next or typing a page number) replaces them, it
// doesn't accumulate pages on top of each other.
async function loadVouchers(reset = true) {
  if (reset) vchPage = 1;
  try {
    const type = document.getElementById('voucher-type-filter').value;
    const from = document.getElementById('voucher-date-from').value;
    const to = document.getElementById('voucher-date-to').value;
    const party = document.getElementById('voucher-party-search').value.trim();
    const status = document.getElementById('voucher-status-filter').value;

    const p = new URLSearchParams();
    if (type) p.set('type', type);
    if (from) p.set('from', from);
    if (to) p.set('to', to);
    if (party) p.set('party', party);
    if (status) p.set('status', status);
    p.set('page', vchPage);
    p.set('limit', VCH_PAGE_SIZE);

    const res = await fetch('/api/vouchers?' + p.toString());
    const data = await res.json();
    // {entries,total,page,limit} when page & limit are passed, same
    // convention as /api/reports/purchases and /api/items.
    const vouchers = data.entries !== undefined ? data.entries : data;
    vchTotal = data.total !== undefined ? data.total : vouchers.length;
    renderVouchers(vouchers);
    renderPaginationBar('voucher-list-pagination', vchPage, VCH_PAGE_SIZE, vchTotal, gotoVouchersPage);
  } catch(err) {
    console.error('Error loading vouchers:', err);
  }
}

async function gotoVouchersPage(page) {
  vchPage = page;
  await loadVouchers(false);
}

function renderVouchers(vouchers) {
  const tbody = document.getElementById('voucher-list-tbody');
  const empty = document.getElementById('voucher-list-empty');
  
  if (!vouchers || vouchers.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }
  
  empty.style.display = 'none';
  tbody.innerHTML = vouchers.map((v, i) => `
    <tr>
      <td>${i+1}</td>
      <td><span style="font-weight:500;color:var(--color-text-info)">${v.voucher_number}</span></td>
      <td>${v.date || '—'}</td>
      <td><span class="margin-badge" style="background:var(--color-background-info);color:var(--color-text-info)">${v.voucher_type}</span></td>
      <td>${v.party_name || '—'}</td>
      <td>${fmt(v.amount || 0)}</td>
      <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${v.narration || '—'}</td>
      <td>
        <button class="info-btn" onclick="viewVoucher(${v.id})"><i class="ti ti-eye"></i></button>
        <button class="edit-btn" onclick="editVoucher(${v.id})"><i class="ti ti-pencil"></i></button>
        <button class="del-btn" onclick="deleteVoucher(${v.id})"><i class="ti ti-trash"></i></button>
      </td>
    </tr>
  `).join('');
}

async function viewVoucher(id) {
    try {
        const res = await fetch(`/api/vouchers/${id}`);
        if (!res.ok) {
            if (res.status === 404) {
                showToast('Voucher not found', '#ef4444');
            } else {
                showToast('Error loading voucher', '#ef4444');
            }
            return;
        }
        const data = await res.json();
        let html = `
            <div style="margin-bottom:1rem">
                <strong>Voucher #${data.voucher_number}</strong> (${data.voucher_type})<br>
                Date: ${data.date}<br>
                Ref: ${data.reference || '—'}<br>
                Narration: ${data.narration || '—'}
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead><tr><th>Ledger</th><th>Debit</th><th>Credit</th></tr></thead>
                <tbody>
        `;
        data.entries.forEach(e => {
            html += `<tr><td>${e.ledger_name}</td><td>${fmt(e.debit)}</td><td>${fmt(e.credit)}</td></tr>`;
        });
        html += `</tbody></table>`;
        openDrawer('Voucher Details', html);
    } catch (err) {
        showToast('Error loading voucher', '#ef4444');
        console.error(err);
    }
}

async function editVoucher(id) {
  try {
    const res = await fetch(`/api/vouchers/${id}`);
    if (!res.ok) { showToast('Voucher not found', '#ef4444'); return; }
    const data = await res.json();
    const entries = data.entries || [];

    editingVoucherId = data.id;
    editingVoucherType = data.voucher_type;

    if (data.voucher_type === 'PAYMENT') {
      switchSub('voucher-payment');
      document.getElementById('vp-date').value = data.date || '';
      document.getElementById('vp-ref').value = data.reference || '';
      document.getElementById('vp-narration').value = data.narration || '';
      document.getElementById('vp-party-ledger').value = entries[0] ? entries[0].ledger_name : '';
      document.getElementById('vp-mode').value = entries[1] ? entries[1].ledger_name : '';
      document.getElementById('vp-amount').value = entries[0] ? entries[0].debit : '';
      const saveBtn = document.getElementById('vp-save-btn');
      if (saveBtn) saveBtn.innerHTML = '<i class="ti ti-check"></i> Update Payment';
      const cancelBtn = document.getElementById('vp-cancel-edit-btn');
      if (cancelBtn) cancelBtn.style.display = 'inline-flex';

    } else if (data.voucher_type === 'RECEIPT') {
      switchSub('voucher-receipt');
      document.getElementById('vr-date').value = data.date || '';
      document.getElementById('vr-ref').value = data.reference || '';
      document.getElementById('vr-narration').value = data.narration || '';
      document.getElementById('vr-mode').value = entries[0] ? entries[0].ledger_name : '';
      document.getElementById('vr-party-ledger').value = entries[1] ? entries[1].ledger_name : '';
      document.getElementById('vr-amount').value = entries[0] ? entries[0].debit : '';
      const saveBtn = document.getElementById('vr-save-btn');
      if (saveBtn) saveBtn.innerHTML = '<i class="ti ti-check"></i> Update Receipt';
      const cancelBtn = document.getElementById('vr-cancel-edit-btn');
      if (cancelBtn) cancelBtn.style.display = 'inline-flex';

    } else if (data.voucher_type === 'CONTRA') {
      switchSub('voucher-contra');
      document.getElementById('vc-date').value = data.date || '';
      document.getElementById('vc-ref').value = data.reference || '';
      document.getElementById('vc-narration').value = data.narration || '';
      document.getElementById('vc-to-account').value = entries[0] ? entries[0].ledger_name : '';
      document.getElementById('vc-from-account').value = entries[1] ? entries[1].ledger_name : '';
      document.getElementById('vc-amount').value = entries[0] ? entries[0].debit : '';
      const saveBtn = document.getElementById('vc-save-btn');
      if (saveBtn) saveBtn.innerHTML = '<i class="ti ti-check"></i> Update Contra';
      const cancelBtn = document.getElementById('vc-cancel-edit-btn');
      if (cancelBtn) cancelBtn.style.display = 'inline-flex';

    } else if (data.voucher_type === 'JOURNAL') {
      switchSub('voucher-journal');
      document.getElementById('vj-date').value = data.date || '';
      document.getElementById('vj-ref').value = data.reference || '';
      document.getElementById('vj-narration').value = data.narration || '';

      // A JOURNAL voucher now holds only ONE entry — either a debit (From)
      // or a credit (To) line — since From/To are saved as separate vouchers.
      const entry = entries[0] || {};
      const isDebitSide = (entry.debit || 0) > 0;
      editingVoucherSide = isDebitSide ? 'DEBIT' : 'CREDIT';

      document.getElementById('vj-from-account').value = isDebitSide ? (entry.ledger_name || '') : '';
      document.getElementById('vj-to-account').value   = isDebitSide ? '' : (entry.ledger_name || '');
      document.getElementById('vj-amount').value = isDebitSide ? entry.debit : entry.credit;

      const saveBtn = document.getElementById('vj-save-btn');
      if (saveBtn) saveBtn.innerHTML = '<i class="ti ti-check"></i> Update Journal';
      const cancelBtn = document.getElementById('vj-cancel-edit-btn');
      if (cancelBtn) cancelBtn.style.display = 'inline-flex';

    } else {
      showToast('Editing not supported for this voucher type', '#ef4444');
      editingVoucherId = null;
      editingVoucherType = null;
    }
  } catch (err) {
    showToast('Error loading voucher for edit', '#ef4444');
    console.error(err);
  }
}

function cancelVoucherEdit() {
  editingVoucherId = null;
  editingVoucherType = null;
  editingVoucherSide = null;

  ['vp', 'vr', 'vc', 'vj'].forEach(prefix => {
    const saveBtn = document.getElementById(`${prefix}-save-btn`);
    const cancelBtn = document.getElementById(`${prefix}-cancel-edit-btn`);
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (saveBtn) {
      const labelMap = { vp: 'Payment', vr: 'Receipt', vc: 'Contra', vj: 'Journal' };
      saveBtn.innerHTML = `<i class="ti ti-check"></i> Save ${labelMap[prefix]}`;
    }
  });

  ['vp-date','vp-ref','vp-narration','vp-party-ledger','vp-mode','vp-amount',
   'vr-date','vr-ref','vr-narration','vr-mode','vr-party-ledger','vr-amount',
   'vc-date','vc-ref','vc-narration','vc-to-account','vc-from-account','vc-amount',
   'vj-date','vj-ref','vj-narration','vj-to-account','vj-from-account','vj-amount'
  ].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
}

async function deleteVoucher(id) {
  if (!confirm('Delete this voucher?')) return;
  try {
    const res = await fetch(`/api/tally/voucher/${id}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Voucher deleted');
      loadVouchers();
    } else {
      showToast('Cannot delete posted voucher', '#ef4444');
    }
  } catch(err) {
    showToast('Error deleting voucher', '#ef4444');
  }
}


async function resolveOrCreateLedger(name, ledgers, defaultGroup) {
    name = (name || '').trim();
    if (!name) throw new Error('Account name required');

    const found = ledgers.find(l => l.name.toLowerCase() === name.toLowerCase());
    if (found) return found.id;

    // Naya naam type kiya gaya — naya ledger auto-create karo
    const createRes = await fetch('/api/tally/ledgers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, group: defaultGroup || 'Sundry Creditors', opening_balance: 0 })
    });
    const created = await createRes.json();
    if (!created.id) throw new Error(created.error || `Could not create "${name}" ledger`);
    loadLedgers();
    return created.id;
}

async function resolveCashBankLedger(modeName, ledgers) {
    const name = (modeName || '').trim();
    if (!name) throw new Error('Enter or select a payment mode');

    const found = ledgers.find(l => l.name.toLowerCase() === name.toLowerCase());
    if (found) return found.id;

    // Mode doesn't exist yet — auto-create it (Cash stays Cash-in-Hand, anything else becomes a Bank ledger)
    const accType = name.toLowerCase() === 'cash' ? 'cash' : 'bank';
    const createRes = await fetch('/api/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, type: accType, openingBalance: 0 })
    });
    const created = await createRes.json();
    if (!created.id) throw new Error(created.error || `Could not create "${name}" ledger`);
    loadLedgers();
    return created.id;
}

async function savePaymentVoucher() {
    const date = document.getElementById('vp-date').value;
    const mode = document.getElementById('vp-mode').value;
    const partyName = document.getElementById('vp-party-ledger').value.trim();
    const amount = parseFloat(document.getElementById('vp-amount').value);
    const ref = document.getElementById('vp-ref').value.trim();
    const narration = document.getElementById('vp-narration').value.trim();

    // --- Validations ---
    if (!date) { showToast('Date required', '#ef4444'); return; }
    if (!mode || !mode.trim()) { showToast('Enter or select Payment Mode', '#ef4444'); return; }
    if (!partyName) { showToast('Enter Paid To name', '#ef4444'); return; }
    if (isNaN(amount) || amount <= 0) { showToast('Enter valid positive amount', '#ef4444'); return; }

    // Find cash/bank ledger + resolve or auto-create party ledger
    let cashLedgerId = null;
    let partyLedgerId = null;
    try {
        const res = await fetch('/api/tally/ledgers');
        const ledgers = await res.json();

        // Find existing mode ledger, or auto-create a new one (e.g. a new bank name)
        cashLedgerId = await resolveCashBankLedger(mode, ledgers);

        // Find party ledger by name (case-insensitive)
        const partyFound = ledgers.find(l => l.name.toLowerCase() === partyName.toLowerCase());
        if (partyFound) {
            partyLedgerId = partyFound.id;
        } else {
            // Auto-create ledger for this party under "Sundry Creditors"
            const createRes = await fetch('/api/tally/ledgers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: partyName, group: 'Sundry Creditors', opening_balance: 0 })
            });
            const created = await createRes.json();
            if (!created.id) {
                showToast('Could not create ledger for party', '#ef4444');
                return;
            }
            partyLedgerId = created.id;
            loadLedgers();
        }
    } catch (err) {
        showToast(err.message || 'Error fetching ledgers', '#ef4444');
        return;
    }

    const data = {
        voucher_type: 'PAYMENT',
        date: date,
        reference: ref,
        narration: narration,
        entries: [
            { ledger_id: parseInt(partyLedgerId, 10), debit: amount, credit: 0 },
            { ledger_id: parseInt(cashLedgerId, 10), debit: 0, credit: amount }
        ]
    };

    const isEditing = editingVoucherId !== null && editingVoucherType === 'PAYMENT';
    const url = isEditing ? `/api/vouchers/${editingVoucherId}` : '/api/vouchers';
    const method = isEditing ? 'PUT' : 'POST';

    try {
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        // Read response as text first to capture any non-JSON errors
        const responseText = await res.text();

        let result;
        try {
            result = JSON.parse(responseText);
        } catch (e) {
            showToast('Server error: ' + responseText, '#ef4444');
            return;
        }

        if (res.ok) {
            showToast(isEditing ? 'Payment voucher updated' : 'Payment voucher saved');
            if (isEditing) {
                cancelVoucherEdit();
            } else {
                // Clear form
                document.getElementById('vp-date').value = '';
                document.getElementById('vp-amount').value = '';
                document.getElementById('vp-ref').value = '';
                document.getElementById('vp-narration').value = '';
            }
            loadVouchers();
        } else {
            showToast(result.error || 'Error saving payment', '#ef4444');
        }
    } catch (err) {
        showToast('Network error', '#ef4444');
        console.error(err);
    }
}

async function saveReceiptVoucher() {
    const date = document.getElementById('vr-date').value;
    const mode = document.getElementById('vr-mode').value;
    const partyName = document.getElementById('vr-party-ledger').value.trim();
    const amount = parseFloat(document.getElementById('vr-amount').value);
    const ref = document.getElementById('vr-ref').value.trim();
    const narration = document.getElementById('vr-narration').value.trim();

    if (!date) { showToast('Date required', '#ef4444'); return; }
    if (!mode || !mode.trim()) { showToast('Enter or select Receive In mode', '#ef4444'); return; }
    if (!partyName) { showToast('Enter or select Received From ledger', '#ef4444'); return; }
    if (isNaN(amount) || amount <= 0) { showToast('Enter valid amount', '#ef4444'); return; }

    let cashLedgerId = null;
    let partyLedgerId = null;
    try {
        const res = await fetch('/api/tally/ledgers');
        const ledgers = await res.json();
        cashLedgerId = await resolveCashBankLedger(mode, ledgers);
        partyLedgerId = await resolveOrCreateLedger(partyName, ledgers, 'Sundry Debtors');
    } catch (err) { showToast(err.message || 'Error fetching ledgers', '#ef4444'); return; }

    const data = {
        voucher_type: 'RECEIPT',
        date: date,
        reference: ref,
        narration: narration,
        entries: [
            { ledger_id: cashLedgerId, debit: amount, credit: 0 },
            { ledger_id: partyLedgerId, debit: 0, credit: amount }
        ]
    };

    const isEditing = editingVoucherId !== null && editingVoucherType === 'RECEIPT';
    const url = isEditing ? `/api/vouchers/${editingVoucherId}` : '/api/vouchers';
    const method = isEditing ? 'PUT' : 'POST';

    try {
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await res.json();
        if (res.ok) {
            showToast(isEditing ? 'Receipt updated' : 'Receipt saved');
            if (isEditing) {
                cancelVoucherEdit();
            } else {
                document.getElementById('vr-date').value = '';
                document.getElementById('vr-amount').value = '';
                document.getElementById('vr-ref').value = '';
                document.getElementById('vr-narration').value = '';
            }
            loadVouchers();
        } else {
            showToast(result.error || 'Error', '#ef4444');
        }
    } catch (err) { showToast('Network error', '#ef4444'); }
}

async function saveContraVoucher() {
    const date = document.getElementById('vc-date').value;
    const fromName = document.getElementById('vc-from-account').value.trim();
    const toName = document.getElementById('vc-to-account').value.trim();
    const amount = parseFloat(document.getElementById('vc-amount').value);
    const ref = document.getElementById('vc-ref').value.trim();
    const narration = document.getElementById('vc-narration').value.trim();

    if (!date) { showToast('Date required', '#ef4444'); return; }
    if (!fromName || !toName) { showToast('Enter or select both accounts', '#ef4444'); return; }
    if (fromName.toLowerCase() === toName.toLowerCase()) { showToast('Cannot transfer to same account', '#ef4444'); return; }
    if (isNaN(amount) || amount <= 0) { showToast('Enter valid amount', '#ef4444'); return; }

    let fromId = null, toId = null;
    try {
        const res = await fetch('/api/tally/ledgers');
        const ledgers = await res.json();
        fromId = await resolveOrCreateLedger(fromName, ledgers, 'Bank Accounts');
        toId = await resolveOrCreateLedger(toName, ledgers, 'Bank Accounts');
    } catch (err) { showToast(err.message || 'Error resolving accounts', '#ef4444'); return; }

    const data = {
        voucher_type: 'CONTRA',
        date: date,
        reference: ref,
        narration: narration,
        entries: [
            { ledger_id: toId, debit: amount, credit: 0 },
            { ledger_id: fromId, debit: 0, credit: amount }
        ]
    };

    const isEditing = editingVoucherId !== null && editingVoucherType === 'CONTRA';
    const url = isEditing ? `/api/vouchers/${editingVoucherId}` : '/api/vouchers';
    const method = isEditing ? 'PUT' : 'POST';

    try {
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await res.json();
        if (res.ok) {
            showToast(isEditing ? 'Contra updated' : 'Contra saved');
            if (isEditing) {
                cancelVoucherEdit();
            } else {
                document.getElementById('vc-date').value = '';
                document.getElementById('vc-amount').value = '';
                document.getElementById('vc-ref').value = '';
                document.getElementById('vc-narration').value = '';
            }
            loadVouchers();
        } else {
            showToast(result.error || 'Error', '#ef4444');
        }
    } catch (err) { showToast('Network error', '#ef4444'); }
}

async function saveJournalVoucher() {
    const date = document.getElementById('vj-date').value;
    const fromName = document.getElementById('vj-from-account').value.trim();
    const toName = document.getElementById('vj-to-account').value.trim();
    const amount = parseFloat(document.getElementById('vj-amount').value);
    const ref = document.getElementById('vj-ref').value.trim();
    const narration = document.getElementById('vj-narration').value.trim();

    if (!date) { showToast('Date required', '#ef4444'); return; }

    const isEditing = editingVoucherId !== null && editingVoucherType === 'JOURNAL';

    // ── EDIT MODE: sirf ek side (From/debit ya To/credit) update hoti hai,
    // kyunki har side apne aap mein ek alag, single-sided voucher hai. ──
    if (isEditing) {
        const editingDebitSide = editingVoucherSide === 'DEBIT';
        const ledgerName = editingDebitSide ? fromName : toName;

        if (!ledgerName) { showToast('Enter or select ledger', '#ef4444'); return; }
        if (isNaN(amount) || amount <= 0) { showToast('Enter valid amount', '#ef4444'); return; }

        let ledgerId = null;
        try {
            const res = await fetch('/api/tally/ledgers');
            const ledgers = await res.json();
            ledgerId = await resolveOrCreateLedger(ledgerName, ledgers, 'Sundry Creditors');
        } catch (err) { showToast(err.message || 'Error resolving account', '#ef4444'); return; }

        const data = {
            voucher_type: 'JOURNAL',
            date: date,
            reference: ref,
            narration: narration,
            entries: [
                editingDebitSide
                    ? { ledger_id: ledgerId, debit: amount, credit: 0 }
                    : { ledger_id: ledgerId, debit: 0, credit: amount }
            ]
        };

        try {
            const res = await fetch(`/api/vouchers/${editingVoucherId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const result = await res.json();
            if (res.ok) {
                showToast('Journal updated');
                cancelVoucherEdit();
                loadVouchers();
            } else {
                showToast(result.error || 'Error', '#ef4444');
            }
        } catch (err) { showToast('Network error', '#ef4444'); }
        return;
    }

    // ── CREATE MODE: From ke liye ek alag voucher (sirf debit) aur To ke
    // liye ek alag voucher (sirf credit) — dono ke liye same entered amount. ──
    if (!fromName || !toName) { showToast('Enter or select both accounts', '#ef4444'); return; }
    if (fromName.toLowerCase() === toName.toLowerCase()) { showToast('Cannot transfer to same account', '#ef4444'); return; }
    if (isNaN(amount) || amount <= 0) { showToast('Enter valid amount', '#ef4444'); return; }

    let fromId = null, toId = null;
    try {
        const res = await fetch('/api/tally/ledgers');
        const ledgers = await res.json();
        fromId = await resolveOrCreateLedger(fromName, ledgers, 'Sundry Creditors');
        toId = await resolveOrCreateLedger(toName, ledgers, 'Sundry Creditors');
    } catch (err) { showToast(err.message || 'Error resolving accounts', '#ef4444'); return; }

    const fromVoucherData = {
        voucher_type: 'JOURNAL',
        date: date,
        reference: ref,
        narration: narration,
        entries: [{ ledger_id: fromId, debit: amount, credit: 0 }]
    };
    const toVoucherData = {
        voucher_type: 'JOURNAL',
        date: date,
        reference: ref,
        narration: narration,
        entries: [{ ledger_id: toId, debit: 0, credit: amount }]
    };

    try {
        const [fromRes, toRes] = await Promise.all([
            fetch('/api/vouchers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fromVoucherData) }),
            fetch('/api/vouchers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(toVoucherData) })
        ]);
        const fromResult = await fromRes.json();
        const toResult = await toRes.json();
        if (fromRes.ok && toRes.ok) {
            showToast('Journal saved (2 vouchers: From-debit & To-credit)');
            document.getElementById('vj-date').value = '';
            document.getElementById('vj-amount').value = '';
            document.getElementById('vj-ref').value = '';
            document.getElementById('vj-narration').value = '';
            document.getElementById('vj-from-account').value = '';
            document.getElementById('vj-to-account').value = '';
            loadVouchers();
        } else {
            showToast((fromResult && fromResult.error) || (toResult && toResult.error) || 'Error', '#ef4444');
        }
    } catch (err) { showToast('Network error', '#ef4444'); }
}