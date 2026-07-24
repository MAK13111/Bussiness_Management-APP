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
  try {
    if (reset) { itemsPage = 1; }
    const search = document.getElementById('items-search') ? document.getElementById('items-search').value : '';
    const params = new URLSearchParams({ page: itemsPage, limit: ITEMS_PAGE_SIZE });
    if (search) params.set('search', search);
    const res = await fetch(`/api/items?${params.toString()}`);
    const data = await res.json();
    itemsTotal = data.total || 0;
    allItems = data.items;
    renderItems(allItems);
    renderPaginationBar('items-pagination', itemsPage, ITEMS_PAGE_SIZE, itemsTotal, gotoItemsPage);
  } catch(err) { console.error('Error loading items:', err); }
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
      <td>${i+1}</td>
      <td>${item.name}</td>
      <td>${item.size ? `<span class="item-size-badge">${item.size}</span>` : '—'}</td>
      <td>${item.department || '—'}</td>
      <td>${item.purchaseStock || 0}</td>
      <td>${item.sold || 0}</td>
      <td><span class="status-badge ${stockClass}">${remaining}</span></td>
      <td><span class="margin-badge">₹${fmtNum(item.projectedMargin || 0)}</span></td>
      <td><button class="edit-btn" onclick="editItem(${item.id})"><i class="ti ti-pencil"></i></button><button class="del-btn" onclick="deleteItem(${item.id})"><i class="ti ti-trash"></i></button></td>
    </tr>`;
  }).join('');
}

function filterItems() {
  // Search now runs on the server against the whole Items Master list
  // (not just the rows currently loaded on screen), so an item that
  // hasn't been paged into view yet is still found.
  loadItems(true);
}

async function createItem() {
  const name = document.getElementById('ci-name').value.trim();
  const size = document.getElementById('ci-size').value.trim();
  const dept = document.getElementById('ci-dept').value;
  const hsn = document.getElementById('ci-hsn').value.trim();
  const unit = document.getElementById('ci-unit').value.trim();
  const margin = parseFloat(document.getElementById('ci-margin').value) || 0;
  const gst = parseFloat(document.getElementById('ci-gst').value) || 0;
  const minStock = parseFloat(document.getElementById('ci-min-stock').value) || 0;
  if (!name) { showToast('Item name required', '#ef4444'); return; }
  try {
    const res = await fetch('/api/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, size, department: dept, hsn, unit, defaultMargin: margin, defaultGST: gst, min_stock: minStock })
    });
    if (res.ok) {
      showToast('Item created successfully');
      document.getElementById('ci-name').value = '';
      document.getElementById('ci-size').value = '';
      document.getElementById('ci-hsn').value = '';
      document.getElementById('ci-unit').value = '';
      document.getElementById('ci-margin').value = '0';
      document.getElementById('ci-gst').value = '0';
      document.getElementById('ci-min-stock').value = '0';
      loadItems();
    } else {
      const data = await res.json();
      showToast(data.error || 'Error creating item', '#ef4444');
    }
  } catch(err) { showToast('Error creating item', '#ef4444'); }
}

let currentEditItemId = null;

function closeItemEditModal() {
  document.getElementById('item-edit-modal').style.display = 'none';
  currentEditItemId = null;
}

function editItem(id) {
  const item = allItems.find(i => i.id === id);
  if (!item) return;
  currentEditItemId = id;

  const deptOptions = (typeof departments !== 'undefined' ? departments : [])
    .map(d => `<option value="${d}" ${d === item.department ? 'selected' : ''}>${d}</option>`)
    .join('');

  document.getElementById('item-edit-modal-title').textContent = 'Edit Item — ' + (item.name || '');
  document.getElementById('item-edit-modal-body').innerHTML = `
    <div class="fields" style="grid-template-columns: 1fr 1fr 1fr;">
      <div class="field"><label>Item Name *</label><input id="ei-name" type="text" value="${item.name || ''}"/></div>
      <div class="field"><label>Size</label><input id="ei-size" type="text" value="${item.size || ''}"/></div>
      <div class="field"><label>Department</label><select id="ei-dept"><option value="">-- Select Department --</option>${deptOptions}</select></div>
      <div class="field"><label>HSN Code</label><input id="ei-hsn" type="text" value="${item.hsn || ''}"/></div>
      <div class="field"><label>Unit</label><input id="ei-unit" type="text" value="${item.unit || ''}"/></div>
      <div class="field"><label>Default Margin (%)</label><input id="ei-margin" type="number" min="0" step="0.1" value="${item.defaultMargin || 0}"/></div>
      <div class="field"><label>Default GST (%)</label><input id="ei-gst" type="number" min="0" step="0.01" value="${item.defaultGST || 0}"/></div>
      <div class="field"><label>Min Stock</label><input id="ei-min-stock" type="number" min="0" step="1" value="${item.min_stock || 0}"/></div>
    </div>`;
  document.getElementById('item-edit-modal').style.display = 'flex';
}

async function saveEditItem() {
  const id = currentEditItemId;
  if (!id) return;
  const name = document.getElementById('ei-name').value.trim();
  if (!name) { showToast('Item name required', '#ef4444'); return; }
  const payload = {
    name,
    size: document.getElementById('ei-size').value.trim(),
    department: document.getElementById('ei-dept').value,
    hsn: document.getElementById('ei-hsn').value.trim(),
    unit: document.getElementById('ei-unit').value.trim(),
    defaultMargin: parseFloat(document.getElementById('ei-margin').value) || 0,
    defaultGST: parseFloat(document.getElementById('ei-gst').value) || 0,
    min_stock: parseFloat(document.getElementById('ei-min-stock').value) || 0
  };
  try {
    const res = await fetch(`/api/items/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeItemEditModal();
      showToast('Item updated');
      loadItems();
    } else { showToast('Error updating item', '#ef4444'); }
  } catch(err) { showToast('Error updating item', '#ef4444'); }
}

async function deleteItem(id) {
  if (!confirm('Delete this item?')) return;
  try {
    const res = await fetch(`/api/items/${id}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Item deleted');
      loadItems();
    } else { showToast('Error deleting item', '#ef4444'); }
  } catch(err) { showToast('Error deleting item', '#ef4444'); }
}
