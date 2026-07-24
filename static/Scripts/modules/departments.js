// =========================================================================
// modules/departments.js
// Manage departments: loading, rendering the department list, keeping
// every department dropdown on the page in sync, and adding/deleting.
// =========================================================================

async function loadDepartments() {
  try {
    const res = await fetch('/api/departments');
    departments = await res.json();
    renderDeptList();
    updateDeptDropdowns();
  } catch(err){ console.error(err); }
}

function renderDeptList() {
  const list = document.getElementById('dept-list');
  if (!list) return;
  if (departments.length === 0) {
    list.innerHTML = '<span style="color:var(--color-text-tertiary);font-size:13px">No departments added yet.</span>';
    return;
  }
  list.innerHTML = departments.map(d =>
    `<div class="dept-chip"><i class="ti ti-building-store" style="font-size:13px;opacity:.6"></i><span>${d}</span><button class="dept-del-btn" onclick="deleteDepartment('${d.replace(/'/g,"\\'")}')"><i class="ti ti-x"></i></button></div>`
  ).join('');
}

function updateDeptDropdowns() {
  // Update the single common department dropdown in the size modal
  const smCommon = document.getElementById('sm-common-dept');
  if (smCommon) {
    const cur = smCommon.value;
    smCommon.innerHTML = '<option value="">-- Select Department --</option>' + departments.map(d => `<option value="${d}"${d===cur?' selected':''}>${d}</option>`).join('');
  }
  const sel = document.getElementById('f-department');
  if (sel) {
    const cur = sel.value;
    sel.innerHTML = '<option value="">-- Select Department --</option>' + departments.map(d => `<option value="${d}"${d===cur?' selected':''}>${d}</option>`).join('');
  }
  const fsel = document.getElementById('f-fil-dept');
  if (fsel) {
    const cur2 = fsel.value;
    fsel.innerHTML = '<option value="">All Departments</option>' + departments.map(d => `<option value="${d}"${d===cur2?' selected':''}>${d}</option>`).join('');
  }
  const idept = document.getElementById('ci-dept');
  if (idept) {
    const cur3 = idept.value;
    idept.innerHTML = '<option value="">-- Select Department --</option>' + departments.map(d => `<option value="${d}"${d===cur3?' selected':''}>${d}</option>`).join('');
  }
}

async function addDepartment() {
  const input = document.getElementById('dept-new-input');
  const name = input.value.trim();
  if (!name) { showToast('Department name enter karo.', '#ef4444'); return; }
  const res = await fetch('/api/departments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  });
  if (res.ok) {
    const data = await res.json();
    departments = data.departments;
    input.value = '';
    renderDeptList();
    updateDeptDropdowns();
    showToast('✓ Department added!');
  } else if (res.status === 409) {
    showToast('Yeh department pehle se hai!', '#ef4444');
  } else {
    showToast('Error!', '#ef4444');
  }
}

async function deleteDepartment(name) {
  if (!confirm(`"${name}" department delete karo?`)) return;
  const res = await fetch(`/api/departments/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (res.ok) {
    const data = await res.json();
    departments = data.departments;
    renderDeptList();
    updateDeptDropdowns();
    showToast('Department deleted.', '#ef4444');
  } else {
    showToast('Error!', '#ef4444');
  }
}

