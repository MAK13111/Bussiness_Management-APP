// =========================================================================
// modules/settings/users.js
// Manage app users: loading, rendering, adding, and deleting.
// =========================================================================

async function loadUsers() {
  try {
    const res = await fetch('/api/users');
    const users = await res.json();
    renderUsers(users);
  } catch(err) { console.error('Error loading users:', err); }
}

function renderUsers(users) {
  const list = document.getElementById('user-list');
  if (!list) return;
  if (!users || users.length === 0) {
    list.innerHTML = '<div style="color:var(--color-text-tertiary);font-size:13px">No users found.</div>';
    return;
  }
  list.innerHTML = users.map(user => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:0.5px solid var(--color-border-tertiary)">
      <div><div style="font-weight:500;color:var(--color-text-primary)">${user.username}</div><div style="font-size:12px;color:var(--color-text-tertiary)">${user.role || 'user'}</div></div>
      <button class="del-btn" onclick="deleteUser('${user.username}')"><i class="ti ti-trash"></i></button>
    </div>
  `).join('');
}

async function addUser() {
  const username = document.getElementById('user-new-username').value.trim();
  const password = document.getElementById('user-new-password').value.trim();
  if (!username || !password) { showToast('Username and password required', '#ef4444'); return; }
  try {
    const res = await fetch('/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    if (res.ok) {
      showToast('User added');
      document.getElementById('user-new-username').value = '';
      document.getElementById('user-new-password').value = '';
      loadUsers();
    } else {
      showToast('Error adding user', '#ef4444');
    }
  } catch(err) { showToast('Error adding user', '#ef4444'); }
}

async function deleteUser(username) {
  if (!confirm(`Delete user "${username}"?`)) return;
  try {
    const res = await fetch(`/api/users/${encodeURIComponent(username)}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('User deleted');
      loadUsers();
    } else {
      showToast('Error deleting user', '#ef4444');
    }
  } catch(err) { showToast('Error deleting user', '#ef4444'); }
}

