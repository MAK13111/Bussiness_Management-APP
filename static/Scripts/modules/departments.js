// =========================================================================
// modules/departments.js
// Manage departments: loading, rendering the department list, keeping
// every department dropdown on the page in sync, searching, and adding/deleting.
// =========================================================================

let deptFilterQuery = '';

const DEPT_ICON_MAP = {
  accessories: 'ti ti-watch',
  casual: 'ti ti-shirt',
  ethnic: 'ti ti-hanger',
  footwear: 'ti ti-shoe',
  formal: 'ti ti-tie',
  general: 'ti ti-box',
  hardware: 'ti ti-tools',
  kids: 'ti ti-mood-smile',
  'mens wear': 'ti ti-user',
  men: 'ti ti-user',
  mens: 'ti ti-user',
  sports: 'ti ti-ball-football',
  western: 'ti ti-sparkles',
  winter: 'ti ti-snowflake',
  'womens wear': 'ti ti-woman',
  women: 'ti ti-woman',
  womens: 'ti ti-woman',
};

function getDeptIcon(name) {
  const key = (name || '').toLowerCase();
  for (const [k, icon] of Object.entries(DEPT_ICON_MAP)) {
    if (key.includes(k)) return icon;
  }
  return 'ti ti-building-store';
}

async function loadDepartments() {
  try {
    const res = await fetch('/api/departments');
    departments = await res.json();
    renderDeptList();
    updateDeptDropdowns();
  } catch(err){ console.error(err); }
}

function filterDepartments(query) {
  deptFilterQuery = (query || '').trim().toLowerCase();
  const clearBtn = document.getElementById('dept-search-clear');
  if (clearBtn) clearBtn.style.display = deptFilterQuery ? '' : 'none';
  renderDeptList();
}

function clearDeptSearch() {
  const input = document.getElementById('dept-search-input');
  if (input) input.value = '';
  filterDepartments('');
}

function renderDeptList() {
  const list = document.getElementById('dept-list');
  const countEl = document.getElementById('dept-total-count');
  if (countEl) countEl.textContent = departments.length;
  if (!list) return;

  let filtered = departments;
  if (deptFilterQuery) {
    filtered = departments.filter(d => d.toLowerCase().includes(deptFilterQuery));
  }

  if (departments.length === 0) {
    list.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 3rem 1rem; color:var(--color-text-tertiary);">
      <i class="ti ti-building-store" style="font-size:36px; display:block; margin-bottom:10px; opacity:0.4;"></i>
      <span style="font-size:14px;">No departments added yet. Use the form above to add your first department.</span>
    </div>`;
    return;
  }

  if (filtered.length === 0) {
    list.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 2.5rem 1rem; color:var(--color-text-tertiary);">
      <i class="ti ti-search-off" style="font-size:28px; display:block; margin-bottom:8px; opacity:0.5;"></i>
      No matching departments found for "<strong>${deptFilterQuery}</strong>".
    </div>`;
    return;
  }

  list.innerHTML = filtered.map(d => {
    const icon = getDeptIcon(d);
    const escaped = d.replace(/'/g, "\\'");
    return `
      <div class="dept-card">
        <div class="dept-card-icon-wrap">
          <i class="${icon}"></i>
        </div>
        <div class="dept-card-body">
          <div class="dept-card-name" title="${d}">${d}</div>
          <div class="dept-card-count">Category</div>
        </div>
        <button class="dept-card-del-btn" onclick="deleteDepartment('${escaped}')" title="Delete department">
          <i class="ti ti-trash"></i>
        </button>
      </div>
    `;
  }).join('');
}

function updateDeptDropdowns() {
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
  if (!name) { showToast('Please enter a department name.', '#ef4444'); return; }
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
    showToast('This department already exists!', '#ef4444');
  } else {
    showToast('Error!', '#ef4444');
  }
}

async function deleteDepartment(name) {
  if (!confirm(`Delete department "${name}"?`)) return;
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
