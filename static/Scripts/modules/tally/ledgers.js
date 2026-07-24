// =========================================================================
// modules/tally/ledgers.js
// Tally ledgers: loading, rendering, creating, editing, deleting, and
// keeping account-group / ledger dropdowns across the app up to date.
// =========================================================================

let currentLedgers = [];
let editingLedgerId = null;

let ledgerListPage = 1;
let ledgerListTotal = 0;
const LEDGER_LIST_PAGE_SIZE = 100;

async function loadLedgers() {
  let ledgers = [];
  try {
    // Full list -- needed everywhere else (party datalists, payment-mode
    // datalists, ledger selects/dropdowns), so it stays unpaginated.
    const res = await fetch('/api/tally/ledgers');
    ledgers = await res.json();
    currentLedgers = ledgers;
    // The "Manage Ledgers" list itself is loaded/rendered separately, 100
    // at a time, with its own Prev/Next bar (same pattern as Voucher List).
    loadLedgerListPage(ledgerListPage);
    populateLedgerDropdowns(ledgers);
    populateAccountGroups();
    refreshLedgerOptions();
  } catch (err) {
    console.error('Error loading ledgers:', err);
    showToast('Error loading ledgers', '#ef4444');
  }
  const dl = document.getElementById('vp-party-datalist');
    if (dl) {
        const ledgerOpts = ledgers.map(l => `<option value="${l.name}"></option>`).join('');
        dl.innerHTML = ledgerOpts;
        fetch('/api/purchase_parties')
            .then(r => r.json())
            .then(parties => {
                const partyOpts = parties
                    .filter(p => !ledgers.find(l => l.name === p))
                    .map(p => `<option value="${p}"></option>`).join('');
                dl.innerHTML = ledgerOpts + partyOpts;
            })
            .catch(() => {});
    }

  // Payment Mode datalists: Cash + all existing Bank ledgers
  const modeLedgers = ledgers.filter(l => l.group_name === 'Cash-in-Hand' || l.group_name === 'Bank Accounts');
  ['vp-mode-datalist', 'vr-mode-datalist'].forEach(id => {
      const mdl = document.getElementById(id);
      if (mdl) mdl.innerHTML = modeLedgers.map(l => `<option value="${l.name}"></option>`).join('');
  });

  // Receipt / Contra / Journal account datalists: all ledgers, by name
  const allLedgerOpts = ledgers.map(l => `<option value="${l.name}"></option>`).join('');
  ['vr-party-datalist', 'vc-from-datalist', 'vc-to-datalist', 'vj-from-datalist', 'vj-to-datalist'].forEach(id => {
      const adl = document.getElementById(id);
      if (adl) adl.innerHTML = allLedgerOpts;
  });
}

// Loads and renders ONE page (100 at a time) of the "Manage Ledgers" list,
// with Prev/Next + "Page X of Y" -- mirrors loadVouchers()/gotoVouchersPage()
// in modules/tally/vouchers.js. Only this page's rows are ever rendered;
// switching pages replaces them, it doesn't accumulate.
async function loadLedgerListPage(page = 1) {
  ledgerListPage = page;
  const list = document.getElementById('ledger-list');
  if (list) list.innerHTML = '<div style="color:var(--color-text-tertiary);font-size:13px">Loading ledgers...</div>';
  try {
    const res = await fetch(`/api/tally/ledgers?page=${ledgerListPage}&limit=${LEDGER_LIST_PAGE_SIZE}`);
    const data = await res.json();
    const ledgers = data.entries !== undefined ? data.entries : data;
    ledgerListTotal = data.total !== undefined ? data.total : ledgers.length;
    renderLedgers(ledgers);
    renderPaginationBar('ledger-list-pagination', ledgerListPage, LEDGER_LIST_PAGE_SIZE, ledgerListTotal, loadLedgerListPage);
  } catch (err) {
    console.error('Error loading ledger list page:', err);
    showToast('Error loading ledgers', '#ef4444');
  }
}

function renderLedgers(ledgers) {
  const list = document.getElementById('ledger-list');
  if (!list) return;
  
  if (!ledgers || ledgers.length === 0) {
    list.innerHTML = '<div style="color:var(--color-text-tertiary);font-size:13px">No ledgers found.</div>';
    return;
  }
  
  list.innerHTML = ledgers.map(l => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:0.5px solid var(--color-border-tertiary)">
      <div>
        <div style="font-weight:500;color:var(--color-text-primary)">${l.name}</div>
        <div style="font-size:11px;color:var(--color-text-tertiary)">${l.group_name || 'Sundry'} • ${l.balance_type}</div>
      </div>
      <div>
        <button class="edit-btn" onclick="editLedger(${l.id})"><i class="ti ti-pencil"></i></button>
        <button class="del-btn" onclick="deleteLedger(${l.id})"><i class="ti ti-trash"></i></button>
      </div>
    </div>
  `).join('');
}

async function resetLedgerForm() {
  document.getElementById('ledger-new-name').value = '';
  document.getElementById('ledger-new-group').value = '';
  document.getElementById('ledger-new-balance').value = '0';
  document.getElementById('ledger-new-balance-type').value = 'Debit';
  document.getElementById('ledger-new-contact').value = '';
  document.getElementById('ledger-new-phone').value = '';
  document.getElementById('ledger-new-email').value = '';
  document.getElementById('ledger-new-address').value = '';
  document.getElementById('ledger-new-gst').value = '';
  document.getElementById('ledger-new-pan').value = '';
}

async function createLedger() {
  const data = {
    name: document.getElementById('ledger-new-name').value.trim(),
    group_id: document.getElementById('ledger-new-group').value || null,
    opening_balance: parseFloat(document.getElementById('ledger-new-balance').value) || 0,
    balance_type: document.getElementById('ledger-new-balance-type').value,
    contact_person: document.getElementById('ledger-new-contact').value.trim(),
    phone: document.getElementById('ledger-new-phone').value.trim(),
    email: document.getElementById('ledger-new-email').value.trim(),
    address: document.getElementById('ledger-new-address').value.trim(),
    gst_no: document.getElementById('ledger-new-gst').value.trim(),
    pan_no: document.getElementById('ledger-new-pan').value.trim()
  };

  if (!data.name) { showToast('Ledger name required', '#ef4444'); return; }

  const isEditing = editingLedgerId !== null;
  const url = isEditing ? `/api/tally/ledgers/${editingLedgerId}` : '/api/tally/ledgers';
  const method = isEditing ? 'PUT' : 'POST';

  try {
    const res = await fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (res.ok) {
      showToast(isEditing ? 'Ledger updated' : 'Ledger created');
      if (isEditing) {
        cancelLedgerEdit();
      } else {
        resetLedgerForm();
      }
      loadLedgers();
    } else {
      const errData = await res.json();
      showToast(errData.error || (isEditing ? 'Error updating ledger' : 'Error creating ledger'), '#ef4444');
    }
  } catch (err) {
    showToast(isEditing ? 'Error updating ledger' : 'Error creating ledger', '#ef4444');
  }
}

async function deleteLedger(id) {
  if (!confirm('Delete this ledger? It cannot be used in any voucher.')) return;
  try {
    const res = await fetch(`/api/tally/ledgers/${id}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Ledger deleted');
      loadLedgers();
    } else {
      const data = await res.json();
      showToast(data.error || 'Cannot delete', '#ef4444');
    }
  } catch (err) {
    showToast('Error deleting ledger', '#ef4444');
  }
}

function editLedger(id) {
  const ledger = currentLedgers.find(l => l.id === id);
  if (!ledger) { showToast('Ledger not found', '#ef4444'); return; }

  editingLedgerId = id;

  document.getElementById('ledger-new-name').value = ledger.name || '';
  document.getElementById('ledger-new-group').value = ledger.group_id || '';
  document.getElementById('ledger-new-balance').value = ledger.opening_balance || 0;
  document.getElementById('ledger-new-balance-type').value = ledger.balance_type || 'Debit';
  document.getElementById('ledger-new-contact').value = ledger.contact_person || '';
  document.getElementById('ledger-new-phone').value = ledger.phone || '';
  document.getElementById('ledger-new-email').value = ledger.email || '';
  document.getElementById('ledger-new-address').value = ledger.address || '';
  document.getElementById('ledger-new-gst').value = ledger.gst_no || '';
  document.getElementById('ledger-new-pan').value = ledger.pan_no || '';

  const saveBtn = document.getElementById('ledger-save-btn');
  if (saveBtn) saveBtn.innerHTML = '<i class="ti ti-check"></i> Update Ledger';
  const cancelBtn = document.getElementById('ledger-cancel-edit-btn');
  if (cancelBtn) cancelBtn.style.display = 'inline-flex';

  document.getElementById('ledger-new-name').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function cancelLedgerEdit() {
  editingLedgerId = null;
  resetLedgerForm();

  const saveBtn = document.getElementById('ledger-save-btn');
  if (saveBtn) saveBtn.innerHTML = '<i class="ti ti-plus"></i> Create Ledger';
  const cancelBtn = document.getElementById('ledger-cancel-edit-btn');
  if (cancelBtn) cancelBtn.style.display = 'none';
}

async function populateAccountGroups() {
  try {
    const res = await fetch('/api/tally/account_groups');
    const groups = await res.json();
    const select = document.getElementById('ledger-new-group');
    if (select) {
      select.innerHTML = '<option value="">-- Select Group --</option>' +
        groups.map(g => `<option value="${g.id}">${g.name}</option>`).join('');
    }
  } catch (err) { console.error(err); }
}

function populateLedgerDropdowns(ledgers) {
    // For voucher party autocomplete (datalists)
    const partyLists = ['vp-party-list', 'vr-party-list'];
    partyLists.forEach(id => {
        const dl = document.getElementById(id);
        if (dl) {
            dl.innerHTML = ledgers.map(l => `<option value="${l.name}"></option>`).join('');
        }
    });
    
    // For selects (voucher forms AND ledger statement)
    const selects = [
        'ls-ledger'          // Ledger Statement (NEW)
    ];
    selects.forEach(id => {
        const sel = document.getElementById(id);
        if (sel) {
            const current = sel.value;
            sel.innerHTML = '<option value="">Select Ledger</option>' +
                '<option value="all" ' + (current === 'all' ? 'selected' : '') + '>All</option>' +
                ledgers.map(l => `<option value="${l.id}" ${l.id == current ? 'selected' : ''}>${l.name}</option>`).join('');
        }
    });
}

let ledgerOptions = '';

async function refreshLedgerOptions() {
  try {
    const res = await fetch('/api/tally/ledgers');
    const ledgers = await res.json();
    ledgerOptions = ledgers.map(l => `<option value="${l.id}">${l.name}</option>`).join('');
  } catch (err) { console.error(err); }
}

