// =========================================================================
// core/toast.js
// Small helper to show a temporary toast notification message.
// =========================================================================

function showToast(msg, color = '#16a34a') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = color;
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 2500);
}

