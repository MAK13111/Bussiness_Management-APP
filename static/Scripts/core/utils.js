// =========================================================================
// core/utils.js
// Generic, reusable helper functions: number formatting, rounding,
// and search-term highlighting.
// =========================================================================

function fmt(n) {
  const num = Number(n) || 0;
  return '₹' + num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function fmtNum(n) {
  const num = Number(n) || 0;
  return num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function round2(n) { return Math.round(n * 100) / 100; }

function roundToNearest5(n) {
  return Math.round(parseFloat(n || 0) / 5) * 5;
}

function hl(text, query) {
  if (!query || !text) return text || '—';
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return String(text).replace(new RegExp(`(${escaped})`, 'gi'), '<mark class="highlight">$1</mark>');
}

// Returns today's date as YYYY-MM-DD in the browser's local timezone
// (avoids the UTC-shift bug you get from new Date().toISOString()).
function todayLocalDate() {
  const d = new Date();
  const offsetMs = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - offsetMs).toISOString().slice(0, 10);
}