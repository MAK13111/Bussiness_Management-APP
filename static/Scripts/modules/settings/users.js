// =========================================================================
// modules/settings/users.js
// Manage app users: loading, rendering, adding, and deleting.
// =========================================================================

let userEditId = null;
let userPasswordId = null;

async function loadUsers() {
  try {
    const res = await fetch('/api/users');
    const users = await res.json();
    renderUsers(users);
  } catch (err) { console.error('Error loading users:', err); }
}

function renderUsers(users) {
  const list = document.getElementById('user-list');
  if (!list) return;
  if (!users || users.length === 0) {
    list.innerHTML = '<div style="color:var(--color-text-tertiary);font-size:13px">No users found.</div>';
    return;
  }
  list.innerHTML = users.map(user => `
    <div class="user-row">
      <div>
        <div style="font-weight:500;color:var(--color-text-primary)">${escapeHtmlUser(user.username)}</div>
        <div style="font-size:12px;color:var(--color-text-tertiary)">${escapeHtmlUser(user.role || 'user')}</div>
      </div>
      <span class="user-status-pill ${user.is_active ? 'active' : 'inactive'}">${user.is_active ? 'Active' : 'Inactive'}</span>
      <button class="del-btn" title="${user.is_active ? 'Deactivate' : 'Activate'}" onclick="toggleUserActive(${user.id}, ${user.is_active ? 1 : 0})">
        <i class="ti ${user.is_active ? 'ti-toggle-right' : 'ti-toggle-left'}"></i>
      </button>
      <div class="user-row-actions">
        <button class="del-btn" title="Edit user" onclick="openUserEditModal(${user.id}, '${escapeAttrUser(user.username)}', '${escapeAttrUser(user.role || 'user')}')"><i class="ti ti-pencil"></i></button>
        <button class="del-btn" title="Reset password" onclick="openUserPasswordModal(${user.id})"><i class="ti ti-key"></i></button>
        <button class="del-btn" title="Delete user" onclick="deleteUser(${user.id}, '${escapeAttrUser(user.username)}')"><i class="ti ti-trash"></i></button>
      </div>
    </div>
  `).join('');
}

function escapeHtmlUser(str) {
  return String(str || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function escapeAttrUser(str) {
  return String(str || '').replace(/'/g, "\\'");
}

// ─── ADD ─────────────────────────────────────────────────────────────────

async function addUser() {
  const username = document.getElementById('user-new-username').value.trim();
  const password = document.getElementById('user-new-password').value;
  const role = document.getElementById('user-new-role')?.value || 'user';
  if (!username || !password) { showToast('Username and password required', '#ef4444'); return; }
  if (password.length < 6) { showToast('Password must be at least 6 characters', '#ef4444'); return; }
  try {
    const res = await fetch('/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, role })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('User added');
      document.getElementById('user-new-username').value = '';
      document.getElementById('user-new-password').value = '';
      loadUsers();
    } else {
      showToast(data.error || 'Error adding user', '#ef4444');
    }
  } catch (err) { showToast('Error adding user', '#ef4444'); }
}

// ─── EDIT (username / role) ────────────────────────────────────────────────

function openUserEditModal(id, username, role) {
  userEditId = id;
  document.getElementById('ue-username').value = username;
  document.getElementById('ue-role').value = role || 'user';
  document.getElementById('ue-error').style.display = 'none';
  document.getElementById('user-edit-modal').style.display = 'flex';
}

function closeUserEditModal() {
  userEditId = null;
  document.getElementById('user-edit-modal').style.display = 'none';
}

async function saveUserEdit() {
  const errEl = document.getElementById('ue-error');
  errEl.style.display = 'none';
  const username = document.getElementById('ue-username').value.trim();
  const role = document.getElementById('ue-role').value;
  if (!username) { errEl.textContent = 'Username is required'; errEl.style.display = 'block'; return; }
  try {
    const res = await fetch(`/api/users/${userEditId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, role })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('User updated');
      closeUserEditModal();
      loadUsers();
    } else {
      errEl.textContent = data.error || 'Error updating user';
      errEl.style.display = 'block';
    }
  } catch (err) {
    errEl.textContent = 'Network error';
    errEl.style.display = 'block';
  }
}

// ─── RESET PASSWORD ─────────────────────────────────────────────────────

function openUserPasswordModal(id) {
  userPasswordId = id;
  document.getElementById('up-password').value = '';
  document.getElementById('up-password-confirm').value = '';
  document.getElementById('up-error').style.display = 'none';
  document.getElementById('user-password-modal').style.display = 'flex';
}

function closeUserPasswordModal() {
  userPasswordId = null;
  document.getElementById('user-password-modal').style.display = 'none';
}

async function saveUserPassword() {
  const errEl = document.getElementById('up-error');
  errEl.style.display = 'none';
  const password = document.getElementById('up-password').value;
  const confirmPassword = document.getElementById('up-password-confirm').value;
  if (!password || password.length < 6) {
    errEl.textContent = 'Password must be at least 6 characters';
    errEl.style.display = 'block';
    return;
  }
  if (password !== confirmPassword) {
    errEl.textContent = 'Passwords do not match';
    errEl.style.display = 'block';
    return;
  }
  try {
    const res = await fetch(`/api/users/${userPasswordId}/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('Password updated');
      closeUserPasswordModal();
    } else {
      errEl.textContent = data.error || 'Error updating password';
      errEl.style.display = 'block';
    }
  } catch (err) {
    errEl.textContent = 'Network error';
    errEl.style.display = 'block';
  }
}

// ─── ACTIVATE / DEACTIVATE ─────────────────────────────────────────────────

async function toggleUserActive(id, currentlyActive) {
  const action = currentlyActive ? 'deactivate' : 'activate';
  if (!confirm(`Are you sure you want to ${action} this user?`)) return;
  try {
    const res = await fetch(`/api/users/${id}/toggle`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast(`User ${data.is_active ? 'activated' : 'deactivated'}`);
      loadUsers();
    } else {
      showToast(data.error || 'Error updating user status', '#ef4444');
    }
  } catch (err) { showToast('Error updating user status', '#ef4444'); }
}

// ─── DELETE ─────────────────────────────────────────────────────────────

async function deleteUser(id, username) {
  if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
  try {
    const res = await fetch(`/api/users/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) {
      showToast('User deleted');
      loadUsers();
    } else {
      showToast(data.error || 'Error deleting user', '#ef4444');
    }
  } catch (err) { showToast('Error deleting user', '#ef4444'); }
}

