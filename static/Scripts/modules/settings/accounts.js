// =========================================================================
// modules/settings/accounts.js
// Manage accounts: loading, rendering, populating account dropdowns,
// adding, and deleting.
// =========================================================================

async function loadAccounts() {
  try {
    const res = await fetch('/api/accounts');
    const accounts = await res.json();
    renderAccounts(accounts);
    populateAccountDropdowns(accounts);
  } catch(err) { console.error('Error loading accounts:', err); }
}

function renderAccounts(accounts) {
  const list = document.getElementById('account-list');
  if (!list) return;
  if (!accounts || accounts.length === 0) {
    list.innerHTML = '<div style="color:var(--color-text-tertiary);font-size:13px">No accounts added yet.</div>';
    return;
  }
  list.innerHTML = accounts.map(acc => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:0.5px solid var(--color-border-tertiary)">
      <div><div style="font-weight:500;color:var(--color-text-primary)">${acc.name}</div><div style="font-size:12px;color:var(--color-text-tertiary)">${acc.type} • Balance: ${fmt(acc.currentBalance)}</div></div>
      <button class="del-btn" onclick="deleteAccount('${acc.name}')"><i class="ti ti-trash"></i></button>
    </div>
  `).join('');
}

function populateAccountDropdowns(accounts) {
  const dropdowns = ['vp-from-account', 'vr-to-account', 'vc-from-account', 'vc-to-account', 'vj-account'];
  dropdowns.forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">Select Account</option>';
    accounts.forEach(acc => {
      const opt = document.createElement('option');
      opt.value = acc.name;
      opt.textContent = `${acc.name} (${fmt(acc.currentBalance)})`;
      if (acc.name === current) opt.selected = true;
      select.appendChild(opt);
    });
  });
}

async function addAccount() {
  const name = document.getElementById('acc-new-name').value.trim();
  const type = document.getElementById('acc-new-type').value;
  const balance = parseFloat(document.getElementById('acc-new-balance').value) || 0;
  const number = document.getElementById('acc-new-number').value.trim();
  if (!name) { showToast('Account name required', '#ef4444'); return; }
  try {
    const res = await fetch('/api/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, type, openingBalance: balance, accountNo: number })
    });
    if (res.ok) {
      showToast('Account added');
      document.getElementById('acc-new-name').value = '';
      document.getElementById('acc-new-balance').value = '0';
      document.getElementById('acc-new-number').value = '';
      loadAccounts();
    } else {
      showToast('Error adding account', '#ef4444');
    }
  } catch(err) { showToast('Error adding account', '#ef4444'); }
}

async function deleteAccount(name) {
  if (!confirm(`Delete account "${name}"?`)) return;
  try {
    const res = await fetch(`/api/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Account deleted');
      loadAccounts();
    } else {
      showToast('Error deleting account', '#ef4444');
    }
  } catch(err) { showToast('Error deleting account', '#ef4444'); }
}

