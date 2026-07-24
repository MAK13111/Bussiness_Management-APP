// =========================================================================
// modules/settings/backup.js
// Data backup / import / export: creating backups, listing existing
// backups, importing a backup file, and loading exportable tables.
// =========================================================================

async function createBackup() {
  try {
    const res = await fetch('/api/settings/backup', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast(`Backup created: ${data.filename}`);
      loadBackups();
    } else {
      showToast(data.error || 'Error creating backup', '#ef4444');
    }
  } catch(err) { showToast('Error creating backup', '#ef4444'); }
}

async function loadBackups() {
  try {
    const res = await fetch('/api/settings/backups');
    const backups = await res.json();
    const list = document.getElementById('backup-list');
    if (!list) return;
    if (!backups || backups.length === 0) {
      list.innerHTML = '<div style="font-size:13px;color:var(--color-text-tertiary)">No backups found.</div>';
      return;
    }
    list.innerHTML = backups.map(b => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:0.5px solid var(--color-border-tertiary)">
        <div><div style="color:var(--color-text-primary)">${b.name}</div><div style="font-size:12px;color:var(--color-text-tertiary)">${b.size} • ${b.modified}</div></div>
        <a href="/api/settings/backup/${b.name}" class="add-btn" download style="font-size:12px;padding:0 12px;height:30px;text-decoration:none"><i class="ti ti-download"></i> Download</a>
      </div>
    `).join('');
  } catch(err) { console.error('Error loading backups:', err); }
}

async function importBackup() {
  const fileInput = document.getElementById('import-file');
  if (!fileInput.files || fileInput.files.length === 0) { showToast('Select a backup file', '#ef4444'); return; }
  if (!confirm('This will overwrite all existing data. Continue?')) return;
  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append('backup', file);
  try {
    const res = await fetch('/api/settings/import', { method: 'POST', body: formData });
    const data = await res.json();
    if (res.ok) {
      showToast('Data imported successfully');
      location.reload();
    } else {
      showToast(data.error || 'Error importing data', '#ef4444');
    }
  } catch(err) { showToast('Error importing data', '#ef4444'); }
}

async function loadExportTables() {
  try {
    const res = await fetch('/api/export/tables');
    const tables = await res.json();
    const list = document.getElementById('export-tables-list');
    if (list) { list.innerHTML = tables.map(t => `<div style="padding:4px 0">• ${t}</div>`).join(''); }
  } catch(err) { console.error('Error loading export tables:', err); }
}

