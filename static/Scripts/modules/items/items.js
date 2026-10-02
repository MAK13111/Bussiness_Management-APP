// =========================================================================
// modules/items/items.js
// Manage the items master list: loading, rendering, searching, and
// creating / editing / deleting items.
// =========================================================================

// Only the current page's items are ever held/rendered -- moving to another
// page (Prev/Next or typing a page number) replaces them, it doesn't
// accumulate pages on top of each other.
let allItems = [];
let itemsPage = 1;
let itemsTotal = 0;
const ITEMS_PAGE_SIZE = 100;

async function loadItems(reset = true) {
  if (reset) { itemsPage = 1; itemsTotal = 0; }
  const search = document.getElementById('items-search') ? document.getElementById('items-search').value : '';
  const params = new URLSearchParams({ page: itemsPage, limit: ITEMS_PAGE_SIZE });
  if (search) params.set('search', search);
  if (!reset && itemsTotal > 0) params.set('total', itemsTotal);

  showPageLoader('items-list-tbody', allItems.length || ITEMS_PAGE_SIZE);

  try {
    const res = await fetch(`/api/items?${params.toString()}`);
    const data = await res.json();
    itemsTotal = data.total || 0;
    allItems = data.items;
    renderItems(allItems);
    renderPaginationBar('items-pagination', itemsPage, ITEMS_PAGE_SIZE, itemsTotal, gotoItemsPage);
  } catch (err) { console.error('Error loading items:', err); }
  finally { hidePageLoader('items-list-tbody'); }
}

async function gotoItemsPage(page) {
  itemsPage = page;
  await loadItems(false);
}

function renderItems(items) {
  const tbody = document.getElementById('items-list-tbody');
  const empty = document.getElementById('items-list-empty');
  if (!items || items.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = items.map((item, i) => {
    const remaining = item.remainingStock || 0;
    const minStock = item.min_stock || 0;
    // Color the remaining-stock pill: red when out, amber when at/below the
    // minimum threshold, green when healthy — gives an at-a-glance status.
    let stockClass = 'paid';
    if (remaining <= 0) stockClass = 'overdue';
    else if (minStock > 0 && remaining <= minStock) stockClass = 'pending';

    return `
    <tr>
      <td>${i + 1}</td>
      <td>${item.name}</td>
      <td>${item.size ? `<span class="item-size-badge">${item.size}</span>` : '—'}</td>
      <td>${item.department || '—'}</td>
      <td>${item.purchaseStock || 0}</td>
      <td>${item.sold || 0}</td>
      <td><span class="status-badge ${stockClass}">${remaining}</span></td>
      <td><span class="margin-badge">₹${fmtNum(item.projectedMargin || 0)}</span></td>
    </tr>`;
  }).join('');
}

function filterItems() {
  // Search now runs on the server against the whole Items Master list
  // (not just the rows currently loaded on screen), so an item that
  // hasn't been paged into view yet is still found.
  loadItems(true);
}