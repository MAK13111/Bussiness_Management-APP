// =========================================================================
// modules/reports/monthly.js
// Monthly report: populating the year dropdown and loading/rendering
// the month-by-month figures.
// =========================================================================

function populateYearDropdown() {
  const select = document.getElementById('mr-year');
  if (!select) return;
  const currentYear = new Date().getFullYear();
  select.innerHTML = '';
  for (let year = currentYear; year >= currentYear - 10; year--) {
    const opt = document.createElement('option');
    opt.value = year;
    opt.textContent = year;
    if (year === currentYear) opt.selected = true;
    select.appendChild(opt);
  }
}

async function loadMonthlyReport() {
  const year = document.getElementById('mr-year').value;
  if (!year) return;
  try {
    const res = await fetch(`/api/reports/monthly?year=${year}`);
    const data = await res.json();
    renderMonthlyReport(data);
  } catch(err) { console.error('Error loading monthly report:', err); }
}

function renderMonthlyReport(data) {
  const tbody = document.getElementById('mr-tbody');
  const empty = document.getElementById('mr-empty');
  if (!data || data.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = data.map(row => `
    <tr><td>${row.month}</td><td>${fmt(row.purchases || 0)}</td><td>${fmt(row.sales || 0)}</td><td class="profit-cell">${fmt(row.profit || 0)}</td><td>${row.itemsSold || 0}</td></tr>
  `).join('');
}

