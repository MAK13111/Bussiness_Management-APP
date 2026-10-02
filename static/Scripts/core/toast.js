// =========================================================================
// core/toast.js
// Small helper to show a temporary toast notification message.
// =========================================================================

function showToast(msg, color = '#16a34a', duration = 3000) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.style.background = color;
  t.style.display = 'block';
  if (t._timer) clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.display = 'none'; }, duration);
}

