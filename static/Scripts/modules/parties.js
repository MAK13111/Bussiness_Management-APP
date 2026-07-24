// =========================================================================
// modules/parties.js
// Manage parties (customers/suppliers): loading, rendering the party
// list/datalist, and adding/deleting a party.
// =========================================================================

let parties = [];

async function loadParties() {
  try {
    const res = await fetch('/api/parties');
    parties = await res.json();
    renderPartyList();
    updatePartyDatalist();
  } catch(err){ console.error(err); }
}

function filterParties() {
  const q = document.getElementById('party-search').value.trim().toLowerCase();
  renderPartyList(q);
}

function renderPartyList(search = '') {
  const list = document.getElementById('party-list');
  if (!list) return;
  const filtered = search
    ? parties.filter(p => (p.name || '').toLowerCase().includes(search))
    : parties;
  if (filtered.length === 0) {
    list.innerHTML = `<span style="color:var(--color-text-tertiary);font-size:13px">${search ? 'No matching parties.' : 'No parties added yet.'}</span>`;
    return;
  }
  list.innerHTML = filtered.map(p =>
    `<div class="dept-chip" style="flex-direction:column;align-items:flex-start;border-radius:var(--border-radius-md);padding:8px 12px;gap:2px;min-width:180px">
      <div style="display:flex;align-items:center;justify-content:space-between;width:100%;gap:8px">
        <span style="font-weight:500;color:var(--color-text-primary)">${p.name}</span>
        <button class="dept-del-btn" onclick="deleteParty('${p.name.replace(/'/g,"\\'")}')"><i class="ti ti-x"></i></button>
      </div>
      ${p.seller_no ? `<span style="font-size:12px;color:var(--color-text-secondary)"><i class="ti ti-phone" style="font-size:11px"></i> ${p.seller_no}</span>` : ''}
      ${p.address  ? `<span style="font-size:12px;color:var(--color-text-secondary);white-space:normal"><i class="ti ti-map-pin" style="font-size:11px"></i> ${p.address}</span>` : ''}
      ${p.gst_no  ? `<span style="font-size:12px;color:var(--color-text-secondary)"><i class="ti ti-file-invoice" style="font-size:11px"></i> ${p.gst_no}</span>` : ''}
    </div>`
  ).join('');
}

function updatePartyDatalist() {
  const dl = document.getElementById('party-datalist');
  if (!dl) return;
  dl.innerHTML = parties.map(p => `<option value="${p.name}"></option>`).join('');
}

function onPartyInput(val) {
  const match = parties.find(p => p.name.toLowerCase() === val.toLowerCase());
  if (match) {
    document.getElementById('f-seller-no').value = match.seller_no || '';
    document.getElementById('f-seller-address').value = match.address || '';
    const gstField = document.getElementById('f-gst-no');
    if (gstField) gstField.value = match.gst_no || '';
  }
}

async function addParty() {
  const name = document.getElementById('party-new-name').value.trim();
  const sellerNo = document.getElementById('party-new-seller-no').value.trim();
  const address = document.getElementById('party-new-address').value.trim();
  const gstNo = document.getElementById('party-new-gst').value.trim();
  if (!name) { showToast('Party name enter karo.', '#ef4444'); return; }
  const res = await fetch('/api/parties', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, sellerNo, address, gstNo })
  });
  if (res.ok) {
    const data = await res.json();
    parties = data.parties;
    document.getElementById('party-new-name').value = '';
    document.getElementById('party-new-seller-no').value = '';
    document.getElementById('party-new-address').value = '';
    document.getElementById('party-new-gst').value = '';
    renderPartyList();
    updatePartyDatalist();
    showToast('✓ Party added!');
  } else if (res.status === 409) {
    showToast('Yeh party pehle se hai!', '#ef4444');
  } else {
    showToast('Error!', '#ef4444');
  }
}

async function deleteParty(name) {
  if (!confirm(`"${name}"delete this party?`)) return;
  const res = await fetch(`/api/parties/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (res.ok) {
    const data = await res.json();
    parties = data.parties;
    renderPartyList();
    updatePartyDatalist();
    showToast('Party deleted.', '#ef4444');
  } else {
    showToast('Error!', '#ef4444');
  }
}

