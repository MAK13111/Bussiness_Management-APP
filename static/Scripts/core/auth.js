// =========================================================================
// core/auth.js
// Login / first-run-setup overlay: checks session status on load, shows
// the right form, handles login/setup submission, and logout. The rest of
// the app's own startup (initApp, in main.js) is only triggered once a
// valid session is confirmed.
// =========================================================================

let authMode = 'login'; // 'login' | 'setup'
let currentAppUser = null;

function updateSidebarUser() {
  const nameEl = document.getElementById('sidebar-user-name');
  const roleEl = document.getElementById('sidebar-user-role');
  const avatarEl = document.getElementById('sidebar-user-avatar');
  if (!nameEl || !roleEl || !avatarEl) return;

  const user = currentAppUser;
  if (user && user.username) {
    nameEl.textContent = user.username;
    roleEl.textContent = user.role || '';
    avatarEl.textContent = user.username.charAt(0);
  } else {
    nameEl.textContent = 'Not logged in';
    roleEl.textContent = '';
    avatarEl.textContent = '?';
  }
}

async function checkAuthStatus() {
  try {
    const res = await fetch('/api/auth/status');
    const data = await res.json();
    if (data.setup_required) {
      showAuthOverlay('setup');
    } else if (!data.logged_in) {
      showAuthOverlay('login');
    } else {
      currentAppUser = data.user;
      updateSidebarUser();
      hideAuthOverlay();
      if (typeof initApp === 'function') initApp();
    }
  } catch (err) {
    console.error('Auth status check failed:', err);
    showAuthOverlay('login');
  }
}

function showAuthOverlay(mode) {
  authMode = mode;
  const overlay = document.getElementById('auth-overlay');
  const title = document.getElementById('auth-card-title');
  const subtitle = document.getElementById('auth-card-subtitle');
  const confirmField = document.getElementById('auth-confirm-field');
  const submitLabel = document.getElementById('auth-submit-label');

  if (mode === 'setup') {
    title.textContent = 'Create Admin Account';
    subtitle.textContent = 'No users exist yet — set up the first admin account to get started.';
    confirmField.style.display = 'block';
    submitLabel.textContent = 'Create Account';
  } else {
    title.textContent = 'Sign in';
    subtitle.textContent = 'Enter your credentials to continue';
    confirmField.style.display = 'none';
    submitLabel.textContent = 'Login';
  }

  hideAuthError();
  document.getElementById('auth-username').value = '';
  document.getElementById('auth-password').value = '';
  document.getElementById('auth-confirm-password').value = '';

  overlay.classList.add('active');
  document.body.classList.add('auth-locked');
  setTimeout(() => document.getElementById('auth-username')?.focus(), 50);
}

function hideAuthOverlay() {
  document.getElementById('auth-overlay').classList.remove('active');
  document.body.classList.remove('auth-locked');
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg;
  el.style.display = 'block';
}

function hideAuthError() {
  const el = document.getElementById('auth-error');
  el.style.display = 'none';
  el.textContent = '';
}

async function handleAuthSubmit() {
  hideAuthError();
  const username = document.getElementById('auth-username').value.trim();
  const password = document.getElementById('auth-password').value;

  if (!username || !password) {
    showAuthError('Please enter both username and password.');
    return;
  }

  const btn = document.getElementById('auth-submit-btn');
  btn.disabled = true;

  try {
    if (authMode === 'setup') {
      const confirmPassword = document.getElementById('auth-confirm-password').value;
      if (password.length < 6) {
        showAuthError('Password must be at least 6 characters.');
        return;
      }
      if (password !== confirmPassword) {
        showAuthError('Passwords do not match.');
        return;
      }
      const res = await fetch('/api/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        showAuthError(data.error || 'Could not create admin account.');
        return;
      }
      currentAppUser = data.user;
    } else {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (!res.ok) {
        showAuthError(data.error || 'Invalid username or password.');
        return;
      }
      currentAppUser = data.user;
    }
    updateSidebarUser();
    hideAuthOverlay();
    if (typeof initApp === 'function') initApp();
  } catch (err) {
    showAuthError('Network error. Please try again.');
  } finally {
    btn.disabled = false;
  }
}

async function logoutUser() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch (err) {
    console.error('Logout error:', err);
  }
  currentAppUser = null;
  updateSidebarUser();
  location.reload();
}

// Allow pressing Enter inside the login form fields to submit.
document.addEventListener('DOMContentLoaded', function () {
  const form = document.getElementById('auth-form');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      handleAuthSubmit();
    });
  }
  checkAuthStatus();
});

// Strict session: tab close, refresh, or navigating away all end the
// session immediately. sendBeacon fires reliably even as the page is
// unloading and still carries the session cookie (same-origin).
window.addEventListener('pagehide', function () {
  if (currentAppUser && navigator.sendBeacon) {
    navigator.sendBeacon('/api/auth/logout');
  }
});