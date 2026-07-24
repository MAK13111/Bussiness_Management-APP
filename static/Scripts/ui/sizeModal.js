// =========================================================================
// ui/sizeModal.js
// "Add Sizes" modal used when an item has multiple sizes/quantities.
// =========================================================================

let activeSizeRowIdx = null;
let sizeModalRowCount = 0;

function openSizeModal(itemIdx) {
  activeSizeRowIdx = itemIdx;
  sizeModalRowCount = 0;
  document.getElementById('size-modal-rows').innerHTML = '';

  // Populate common dept dropdown
  const deptSel = document.getElementById('sm-common-dept');
  if (deptSel) {
    const existing = itemSizeData[itemIdx] || [];
    const prefillDept = existing.length > 0 ? (existing[0].dept || '') : '';
    deptSel.innerHTML = '<option value="">-- Select Department --</option>' +
      departments.map(d => `<option value="${d}"${d === prefillDept ? ' selected' : ''}>${d}</option>`).join('');
  }

  const existing = itemSizeData[itemIdx] || [];
  if (existing.length > 0) {
    existing.forEach(s => addSizeModalRow(s));
  } else {
    addSizeModalRow();
  }
  document.getElementById('size-modal-overlay').style.display = 'flex';
  setTimeout(() => {
    const firstInput = document.querySelector('#size-modal-rows .sm-size-input');
    if (firstInput) firstInput.focus();
  }, 50);
}

function closeSizeModal() {
  document.getElementById('size-modal-overlay').style.display = 'none';
  activeSizeRowIdx = null;
}

function addSizeModalRow(prefill = {}) {
  sizeModalRowCount++;
  const n = sizeModalRowCount;
  const container = document.getElementById('size-modal-rows');
  const row = document.createElement('div');
  row.className = 'sm-row';
  row.id = `sm-row-${n}`;
  row.innerHTML = `
    <input class="sm-size-input" id="sm-size-${n}" type="text" placeholder="Size (e.g. L, 42, 5m)" value="${prefill.size||''}"/>
    <input class="sm-qty-input"  id="sm-qty-${n}"  type="number" placeholder="Qty" min="1" value="${prefill.qty||''}"/>
    <button class="sm-del-btn" onclick="removeSizeModalRow(${n})" type="button" title="Remove"><i class="ti ti-trash"></i></button>
  `;
  container.appendChild(row);
  updateSizeModalDelBtns();
}

function removeSizeModalRow(n) {
  const el = document.getElementById(`sm-row-${n}`);
  if (el) el.remove();
  updateSizeModalDelBtns();
}

function updateSizeModalDelBtns() {
  const rows = document.querySelectorAll('#size-modal-rows .sm-row');
  rows.forEach(r => {
    const btn = r.querySelector('.sm-del-btn');
    if (btn) btn.style.display = rows.length > 1 ? '' : 'none';
  });
}

function saveSizeModal() {
  const rows = document.querySelectorAll('#size-modal-rows .sm-row');
  const sizes = [];
  const commonDept = document.getElementById('sm-common-dept')?.value || '';
  for (const row of rows) {
    const n    = row.id.replace('sm-row-', '');
    const size = document.getElementById(`sm-size-${n}`)?.value.trim() || '';
    const qty  = parseFloat(document.getElementById(`sm-qty-${n}`)?.value) || 0;
    if (!size) { alert('Har size row mein size name enter karo.'); return; }
    if (qty <= 0) { alert(`Size "${size}" ki quantity 0 se zyada honi chahiye.`); return; }
    sizes.push({ size, qty, dept: commonDept });
  }
  if (sizes.length === 0) { alert('Kam se kam ek size add karo.'); return; }
  itemSizeData[activeSizeRowIdx] = sizes;
  updateSizeLabel(activeSizeRowIdx);
  recalcRow(activeSizeRowIdx);
  closeSizeModal();
}

function updateSizeLabel(idx) {
  const labelEl = document.getElementById(`ir-size-label-${idx}`);
  const btnEl   = document.getElementById(`ir-size-btn-${idx}`);
  const sizes   = itemSizeData[idx] || [];
  if (!labelEl) return;
  if (sizes.length === 0) {
    labelEl.textContent = 'Add Sizes';
    if (btnEl) btnEl.classList.remove('has-sizes');
  } else {
    const names = sizes.map(s => s.size).join(', ');
    const totalQty = sizes.reduce((sum, s) => sum + s.qty, 0);
    labelEl.textContent = `${sizes.length} size${sizes.length > 1 ? 's' : ''} · ${names} (Total: ${totalQty})`;
    if (btnEl) btnEl.classList.add('has-sizes');
  }
}

