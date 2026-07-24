// =========================================================================
// core/theme.js
// Dark / light theme handling. Applies a theme, toggles between themes,
// and restores the previously saved theme when the page first loads.
// =========================================================================

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const icon = document.getElementById('theme-toggle-icon');
  if (icon) icon.className = theme === 'light' ? 'ti ti-sun' : 'ti ti-moon';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  const next = current === 'light' ? 'dark' : 'light';
  applyTheme(next);
  localStorage.setItem('pt-theme', next);
}

(function initTheme() {
  const saved = localStorage.getItem('pt-theme') || 'dark';
  applyTheme(saved);
})();

