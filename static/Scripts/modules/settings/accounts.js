// =========================================================================
// modules/settings/accounts.js
// Manage accounts: loading, rendering, populating account dropdowns,
// adding, and deleting.
// =========================================================================

async function loadAccounts() {
  try {
    const res = await fetch('/api/accounts');
    const accounts = await res.json();
    populateAccountDropdowns(accounts);
  } catch(err) { console.error('Error loading accounts:', err); }
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

