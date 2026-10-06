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
        <button class="add-btn" onclick="downloadBackupWithProgress('${b.name}', '${b.size}')" style="font-size:12px;padding:0 12px;height:30px"><i class="ti ti-download"></i> Download</button>
      </div>
      <div id="dl-progress-wrap-${b.name.replace(/\./g,'-')}" style="display:none;padding:8px 0 4px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
          <span id="dl-progress-label-${b.name.replace(/\./g,'-')}" style="font-size:11px;color:var(--color-text-secondary)">Downloading...</span>
          <span id="dl-progress-pct-${b.name.replace(/\./g,'-')}" style="font-size:11px;font-weight:600;color:var(--color-accent)">0%</span>
        </div>
        <div style="height:5px;background:var(--color-border-secondary);border-radius:99px;overflow:hidden">
          <div id="dl-progress-bar-${b.name.replace(/\./g,'-')}" style="height:100%;width:0%;background:linear-gradient(90deg,var(--color-accent),var(--color-accent-hover,#60a5fa));border-radius:99px;transition:width 0.15s ease"></div>
        </div>
      </div>
    `).join('');
  } catch(err) { console.error('Error loading backups:', err); }
}

// ── Format helpers ──────────────────────────────────────────────────────────
function _fmtBytes(bytes) {
  if (bytes < 1024)       return bytes + ' B';
  if (bytes < 1048576)    return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
  return (bytes / 1073741824).toFixed(2) + ' GB';
}
function _fmtSpeed(bps) { return _fmtBytes(bps) + '/s'; }

// ── EXPORT: full database download ─────────────────────────────────────────
// For large databases (19 GB+) we must NOT use fetch+accumulate — the browser
// cannot hold that much in memory.  We redirect the browser directly to the
// download URL so the OS/browser's native download manager streams it straight
// to the Downloads folder.  A ticking timer bar gives the user visual feedback.
async function exportBackupWithProgress() {
  const btn  = document.getElementById('export-download-btn');
  const wrap = document.getElementById('export-progress-wrap');
  const bar  = document.getElementById('export-progress-bar');
  const lbl  = document.getElementById('export-progress-label');
  const pct  = document.getElementById('export-progress-pct');

  if (btn) { btn.disabled = true; btn.style.opacity = '0.6'; }
  if (wrap) wrap.style.display = 'block';
  if (bar)  { bar.style.width = '0%'; bar.style.background = ''; }
  if (pct)  pct.textContent = '';

  // Pulse animation: grows slowly for 10s then stays at ~90% until user sees it
  const startMs = Date.now();
  let animFrame;
  function animate() {
    const elapsed = (Date.now() - startMs) / 1000;
    // Logarithmic fill: reaches ~70% in 10s, ~88% in 60s — never reaches 100
    const fill = Math.min(Math.log1p(elapsed) / Math.log1p(60) * 88, 88);
    if (bar) bar.style.width = fill + '%';
    if (lbl) lbl.textContent = `Downloading... ${elapsed.toFixed(0)}s elapsed — check browser's download bar`;
    animFrame = requestAnimationFrame(animate);
  }
  animFrame = requestAnimationFrame(animate);

  // Trigger native browser download — no memory limit, saves to Downloads folder
  const ts = new Date().toISOString().slice(0,19).replace(/[T:]/g, '-');
  const a  = document.createElement('a');
  a.href     = `/api/export/backup`;
  a.download = `backup_${ts}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();

  // Show a "done" state after a few seconds (we can't detect completion from JS)
  // The user's browser download bar will show real progress and completion.
  setTimeout(() => {
    cancelAnimationFrame(animFrame);
    if (bar) { bar.style.width = '100%'; bar.style.background = 'linear-gradient(90deg,#22c55e,#16a34a)'; }
    if (lbl) lbl.textContent = '✓ Download started — see your browser\'s download bar at the bottom';
    if (pct) pct.textContent = '';

    setTimeout(() => {
      if (wrap) wrap.style.display = 'none';
      if (bar)  { bar.style.width = '0%'; bar.style.background = ''; }
      if (btn)  { btn.disabled = false; btn.style.opacity = ''; }
    }, 5000);
  }, 3000);
}

// ── INDIVIDUAL BACKUP DOWNLOAD: real fetch+progress ─────────────────────────
// These files already exist on the server and have a known Content-Length,
// so we can show an accurate percentage bar.
// For files > 500 MB we fall back to the same native-download approach.
async function downloadBackupWithProgress(name, sizeLabel) {
  const safeId = name.replace(/\./g, '-');
  const wrap   = document.getElementById(`dl-progress-wrap-${safeId}`);
  const bar    = document.getElementById(`dl-progress-bar-${safeId}`);
  const lbl    = document.getElementById(`dl-progress-label-${safeId}`);
  const pct    = document.getElementById(`dl-progress-pct-${safeId}`);
  const btns   = document.querySelectorAll(`[onclick="downloadBackupWithProgress('${name}', '${sizeLabel}')"]`);
  const btnEl  = btns.length ? btns[0] : null;

  const _set = (widthPct, labelTxt, pctTxt, color) => {
    if (widthPct !== null && bar) { bar.style.width = widthPct + '%'; if (color) bar.style.background = color; }
    if (lbl) lbl.textContent = labelTxt;
    if (pct) pct.textContent = pctTxt;
  };

  if (btnEl) { btnEl.disabled = true; btnEl.style.opacity = '0.6'; }
  if (wrap)  wrap.style.display = 'block';
  _set(2, 'Connecting...', '', '');

  const startMs = Date.now();

  try {
    const res = await fetch(`/api/settings/backup/${name}`);
    if (!res.ok) throw new Error(`Server error: ${res.status}`);

    const contentLength = res.headers.get('Content-Length');
    const total = contentLength ? parseInt(contentLength, 10) : 0;

    // Large file (> 500 MB) or unknown size → native download
    if (!total || total > 500 * 1024 * 1024) {
      res.body.cancel();   // release the fetch body we started

      let animFrame2;
      const startMs2 = Date.now();
      function animate2() {
        const e = (Date.now() - startMs2) / 1000;
        const f = Math.min(Math.log1p(e) / Math.log1p(60) * 88, 88);
        if (bar) bar.style.width = f + '%';
        if (lbl) lbl.textContent = `Downloading... ${e.toFixed(0)}s — see browser download bar`;
        animFrame2 = requestAnimationFrame(animate2);
      }
      animFrame2 = requestAnimationFrame(animate2);

      const a = document.createElement('a');
      a.href = `/api/settings/backup/${name}`;
      a.download = name;
      document.body.appendChild(a); a.click(); a.remove();

      setTimeout(() => {
        cancelAnimationFrame(animFrame2);
        _set(100, '✓ Download started — see your browser\'s download bar', '', 'linear-gradient(90deg,#22c55e,#16a34a)');
        setTimeout(() => {
          if (wrap) wrap.style.display = 'none';
          if (bar)  { bar.style.width = '0%'; bar.style.background = ''; }
          if (btnEl) { btnEl.disabled = false; btnEl.style.opacity = ''; }
        }, 5000);
      }, 3000);
      return;
    }

    // Small/medium file: stream with real progress
    const reader = res.body.getReader();
    const chunks = [];
    let received = 0;
    let speedWindow = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;

      const now = Date.now();
      speedWindow.push({ bytes: value.length, ts: now });
      speedWindow = speedWindow.filter(s => now - s.ts < 3000);
      const wBytes = speedWindow.reduce((a, s) => a + s.bytes, 0);
      const wSecs  = Math.max((now - speedWindow[0].ts) / 1000, 0.1);
      const speed  = wBytes / wSecs;

      const pctVal = Math.min((received / total) * 100, 99);
      _set(pctVal,
        `${_fmtBytes(received)} / ${_fmtBytes(total)} • ${_fmtSpeed(speed)}`,
        Math.round(pctVal) + '%', '');
    }

    // Trigger save-as dialog
    const blob   = new Blob(chunks);
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(objUrl);

    const elapsed = ((Date.now() - startMs) / 1000).toFixed(1);
    _set(100, `✓ Download complete in ${elapsed}s`, '100%', 'linear-gradient(90deg,#22c55e,#16a34a)');

    setTimeout(() => {
      if (wrap) wrap.style.display = 'none';
      if (bar)  { bar.style.width = '0%'; bar.style.background = ''; }
    }, 3000);

  } catch (err) {
    _set(100, '✗ Download failed: ' + err.message, '', '#ef4444');
    showToast('Download failed: ' + err.message, '#ef4444');
    setTimeout(() => {
      if (wrap) wrap.style.display = 'none';
      if (bar)  { bar.style.background = ''; bar.style.width = '0%'; }
    }, 4000);
  } finally {
    if (btnEl) { btnEl.disabled = false; btnEl.style.opacity = ''; }
  }
}

// ── IMPORT: full-screen blocking overlay with real progress ────────────────

function _createImportOverlay() {
  // Remove existing overlay if any
  const existing = document.getElementById('import-loading-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'import-loading-overlay';
  overlay.style.cssText = `
    position:fixed;inset:0;z-index:99999;
    background:rgba(10,12,20,0.97);
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    backdrop-filter:blur(8px);
    font-family:'Inter',system-ui,sans-serif;
  `;
  overlay.innerHTML = `
    <div style="
      background:linear-gradient(145deg,#141824,#1e2438);
      border:1px solid rgba(99,120,255,0.25);
      border-radius:20px;padding:48px 52px;
      text-align:center;max-width:520px;width:90%;
      box-shadow:0 32px 80px rgba(0,0,0,0.7),0 0 0 1px rgba(99,120,255,0.1);
    ">
      <!-- Animated icon -->
      <div id="imp-icon-wrap" style="margin-bottom:28px">
        <div style="
          width:72px;height:72px;border-radius:50%;
          background:linear-gradient(135deg,#6378ff22,#a78bfa22);
          border:2px solid rgba(99,120,255,0.4);
          display:flex;align-items:center;justify-content:center;
          margin:0 auto;
          animation:imp-pulse 2s ease-in-out infinite;
        ">
          <i id="imp-icon" class="ti ti-database-import" style="font-size:30px;color:#818cf8"></i>
        </div>
      </div>

      <div id="imp-title" style="font-size:20px;font-weight:700;color:#f1f5f9;margin-bottom:8px">
        Data Import In Progress
      </div>
      <div id="imp-subtitle" style="font-size:13px;color:#94a3b8;margin-bottom:32px;line-height:1.6">
        Do not close this window — please wait until all data has loaded
      </div>

      <!-- Phase indicators -->
      <div style="display:flex;gap:8px;justify-content:center;margin-bottom:28px" id="imp-phases">
        <div id="imp-phase-upload" style="
          display:flex;align-items:center;gap:6px;padding:6px 14px;
          border-radius:99px;font-size:12px;font-weight:600;
          background:rgba(99,120,255,0.15);color:#818cf8;
          border:1px solid rgba(99,120,255,0.3);
          transition:all 0.3s;
        "><span id="imp-phase-upload-dot" style="width:6px;height:6px;border-radius:50%;background:#818cf8;display:inline-block"></span> Upload</div>
        <div id="imp-phase-safetybak" style="
          display:flex;align-items:center;gap:6px;padding:6px 14px;
          border-radius:99px;font-size:12px;font-weight:600;
          background:rgba(255,255,255,0.04);color:#475569;
          border:1px solid rgba(255,255,255,0.08);
          transition:all 0.3s;
        "><span style="width:6px;height:6px;border-radius:50%;background:#475569;display:inline-block"></span> Safety Bak</div>
        <div id="imp-phase-restore" style="
          display:flex;align-items:center;gap:6px;padding:6px 14px;
          border-radius:99px;font-size:12px;font-weight:600;
          background:rgba(255,255,255,0.04);color:#475569;
          border:1px solid rgba(255,255,255,0.08);
          transition:all 0.3s;
        "><span style="width:6px;height:6px;border-radius:50%;background:#475569;display:inline-block"></span> Restore</div>
      </div>

      <!-- Main progress bar -->
      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <span id="imp-bar-label" style="font-size:12px;color:#64748b">Starting...</span>
          <span id="imp-bar-pct" style="font-size:13px;font-weight:700;color:#818cf8">0%</span>
        </div>
        <div style="height:8px;background:rgba(255,255,255,0.06);border-radius:99px;overflow:hidden">
          <div id="imp-bar" style="
            height:100%;width:0%;border-radius:99px;
            background:linear-gradient(90deg,#6378ff,#a78bfa);
            transition:width 0.4s ease;
            box-shadow:0 0 12px rgba(99,120,255,0.5);
          "></div>
        </div>
      </div>

      <!-- Detail message -->
      <div id="imp-detail" style="
        font-size:12px;color:#475569;margin-top:12px;
        min-height:18px;line-height:1.5;
      ">Uploading file to server...</div>

      <!-- Size info -->
      <div id="imp-size-info" style="
        margin-top:20px;padding:12px 16px;
        background:rgba(255,255,255,0.03);border-radius:10px;
        border:1px solid rgba(255,255,255,0.06);
        font-size:12px;color:#64748b;
      ">
        <span id="imp-transferred">0 B</span> / <span id="imp-total-size">— </span>
        &nbsp;•&nbsp; Speed: <span id="imp-speed">—</span>
        &nbsp;•&nbsp; ETA: <span id="imp-eta">—</span>
      </div>

      <div style="margin-top:24px;font-size:11px;color:#334155;line-height:1.7">
        ⚠️ Do not close or refresh this window<br>The app will automatically restart once the import is complete
      </div>
    </div>

    <style>
      @keyframes imp-pulse {
        0%,100% { box-shadow:0 0 0 0 rgba(99,120,255,0.4); transform:scale(1); }
        50%      { box-shadow:0 0 0 12px rgba(99,120,255,0); transform:scale(1.05); }
      }
      @keyframes imp-spin {
        to { transform:rotate(360deg); }
      }
    </style>
  `;
  document.body.appendChild(overlay);
  return overlay;
}

function _setImportPhaseActive(phase) {
  const phases = { upload: 'imp-phase-upload', safetybak: 'imp-phase-safetybak', restore: 'imp-phase-restore' };
  const activeStyle = 'display:flex;align-items:center;gap:6px;padding:6px 14px;border-radius:99px;font-size:12px;font-weight:600;background:rgba(99,120,255,0.18);color:#818cf8;border:1px solid rgba(99,120,255,0.4);transition:all 0.3s;';
  const doneStyle   = 'display:flex;align-items:center;gap:6px;padding:6px 14px;border-radius:99px;font-size:12px;font-weight:600;background:rgba(34,197,94,0.12);color:#4ade80;border:1px solid rgba(34,197,94,0.3);transition:all 0.3s;';
  const idleStyle   = 'display:flex;align-items:center;gap:6px;padding:6px 14px;border-radius:99px;font-size:12px;font-weight:600;background:rgba(255,255,255,0.04);color:#475569;border:1px solid rgba(255,255,255,0.08);transition:all 0.3s;';

  const order = ['upload', 'safetybak', 'restore'];
  const currentIdx = order.indexOf(phase);
  order.forEach((p, i) => {
    const el = document.getElementById(phases[p]);
    if (!el) return;
    if (i < currentIdx)       el.style.cssText = doneStyle;
    else if (i === currentIdx) el.style.cssText = activeStyle;
    else                       el.style.cssText = idleStyle;
  });
}

function _updateImportBar(pct, label, detail) {
  const bar = document.getElementById('imp-bar');
  const pctEl = document.getElementById('imp-bar-pct');
  const lblEl = document.getElementById('imp-bar-label');
  const detEl = document.getElementById('imp-detail');
  if (bar)   bar.style.width   = Math.min(pct, 100) + '%';
  if (pctEl) pctEl.textContent = Math.round(pct) + '%';
  if (lblEl && label) lblEl.textContent = label;
  if (detEl && detail !== undefined) detEl.textContent = detail;
}

async function importBackup() {
  const fileInput = document.getElementById('import-file');
  if (!fileInput.files || fileInput.files.length === 0) {
    showToast('Please select a backup file (.zip or .sql) first', '#ef4444'); return;
  }
  if (!confirm('⚠️ This will replace ALL existing data with the backup file.\n\nBefore anything is changed, your current data will be automatically saved to the Previous_data/ folder as a safety backup.\n\nFor large files (6 GB+) the import may take 5–15 minutes.\n\nDo you want to continue?')) return;

  const file = fileInput.files[0];
  const overlay = _createImportOverlay();

  // Prevent accidental close
  const _beforeUnload = (e) => { e.preventDefault(); e.returnValue = ''; };
  window.addEventListener('beforeunload', _beforeUnload);

  // ─── PHASE 1: Upload file with XHR progress ───────────────────────────
  _setImportPhaseActive('upload');
  const totalSizeEl      = document.getElementById('imp-total-size');
  const transferredEl    = document.getElementById('imp-transferred');
  const speedEl          = document.getElementById('imp-speed');
  const etaEl            = document.getElementById('imp-eta');

  if (totalSizeEl) totalSizeEl.textContent = _fmtBytes(file.size);

  let uploadStartMs = Date.now();
  let speedWindow   = [];

  await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/settings/import');

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const now = Date.now();
      const pct = (e.loaded / e.total) * 100;

      speedWindow.push({ bytes: e.loaded, ts: now });
      speedWindow = speedWindow.filter(s => now - s.ts < 4000);
      const deltaBytes = speedWindow.length > 1 ? speedWindow[speedWindow.length-1].bytes - speedWindow[0].bytes : 0;
      const deltaSecs  = speedWindow.length > 1 ? (speedWindow[speedWindow.length-1].ts - speedWindow[0].ts) / 1000 : 1;
      const speed      = deltaBytes / Math.max(deltaSecs, 0.1);
      const remaining  = speed > 0 ? (e.total - e.loaded) / speed : 0;

      if (transferredEl) transferredEl.textContent = _fmtBytes(e.loaded);
      if (speedEl)       speedEl.textContent       = _fmtSpeed(speed);
      if (etaEl)         etaEl.textContent         = remaining > 0 ? _fmtEta(remaining) : '—';

      _updateImportBar(pct * 0.4,   // Upload = first 40% of overall bar
        `Uploading file... ${_fmtBytes(e.loaded)} / ${_fmtBytes(e.total)}`,
        `Upload speed: ${_fmtSpeed(speed)}`
      );
    };

    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 202) {
        try {
          const resp = JSON.parse(xhr.responseText);
          if (resp.status === 'started') resolve(resp);
          else reject(new Error(resp.error || 'Unknown error'));
        } catch { reject(new Error('Bad server response')); }
      } else {
        try {
          const resp = JSON.parse(xhr.responseText);
          reject(new Error(resp.error || `Server error ${xhr.status}`));
        } catch { reject(new Error(`Server error ${xhr.status}`)); }
      }
    };
    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.ontimeout = () => reject(new Error('Upload timed out'));
    xhr.timeout = 0; // no timeout for large files

    const fd = new FormData();
    fd.append('backup', file);
    xhr.send(fd);
  }).catch(err => {
    window.removeEventListener('beforeunload', _beforeUnload);
    overlay.remove();
    showToast('Import failed: ' + err.message, '#ef4444');
    throw err;
  });

  // ─── PHASE 2 & 3: Poll /api/settings/import/status ───────────────────
  _updateImportBar(42, 'File saved on server...', 'Preparing to reset the database...');

  let pollInterval = setInterval(async () => {
    try {
      const res  = await fetch('/api/settings/import/status');
      const data = await res.json();

      if (data.phase === 'safetybak') {
        _setImportPhaseActive('safetybak');
        _updateImportBar(44, 'Creating safety backup...', data.message || 'Saving your current data to Previous_data/ before any changes...');
        if (speedEl) speedEl.textContent = '—';
        if (etaEl)   etaEl.textContent   = '—';
      }
      else if (data.phase === 'recreating') {
        _setImportPhaseActive('safetybak'); // still in the safetybak visual slot (legacy SQL path only)
        _updateImportBar(50, 'Resetting database...', data.message || 'Dropping old database and creating a fresh one...');
        if (transferredEl && data.file_size) transferredEl.textContent = _fmtBytes(data.file_size);
        if (speedEl) speedEl.textContent = '—';
        if (etaEl)   etaEl.textContent   = '—';
      }
      else if (data.phase === 'recovering') {
        // Import failed — auto-restoring from safety backup
        const bar = document.getElementById('imp-bar');
        if (bar) bar.style.background = 'linear-gradient(90deg,#f59e0b,#d97706)';
        const icon = document.getElementById('imp-icon');
        if (icon) { icon.className = 'ti ti-refresh'; icon.style.color = '#fbbf24'; }
        _updateImportBar(80, '⟳ Recovering original data...', data.message || 'Restoring your previous data from safety backup...');
        if (speedEl) speedEl.textContent = '—';
        if (etaEl)   etaEl.textContent   = 'please wait...';
      }
      else if (data.phase === 'restoring') {
        _setImportPhaseActive('restore');
        // Simulate slow progress from 55% → 95% based on lines processed
        const lines = data.lines_done || 0;
        // Logarithmic: lots of lines at start, slows down
        const restorePct = Math.min(55 + Math.log1p(lines) / Math.log1p(50000) * 40, 95);
        _updateImportBar(
          restorePct,
          `Restoring data... (${lines.toLocaleString()} commands processed)`,
          data.message || 'psql restore is running, please wait...'
        );
        if (speedEl) speedEl.textContent = `${lines.toLocaleString()} cmds`;
        if (etaEl)   etaEl.textContent   = 'calculating...';
      }
      else if (data.phase === 'done') {
        clearInterval(pollInterval);
        window.removeEventListener('beforeunload', _beforeUnload);

        // Show success state
        _updateImportBar(100, '✓ Import Complete!', 'All data imported successfully!');
        const bar = document.getElementById('imp-bar');
        if (bar) bar.style.background = 'linear-gradient(90deg,#22c55e,#16a34a)';
        const icon = document.getElementById('imp-icon');
        if (icon) { icon.className = 'ti ti-circle-check'; icon.style.color = '#4ade80'; }
        const title = document.getElementById('imp-title');
        if (title) title.textContent = 'Import Complete! 🎉';
        const sub = document.getElementById('imp-subtitle');
        if (sub) sub.textContent = 'App will restart in 3 seconds...';
        if (speedEl) speedEl.textContent = '—';
        if (etaEl)   etaEl.textContent   = '3s...';

        // Auto-restart countdown
        let countdown = 3;
        const countTimer = setInterval(() => {
          countdown--;
          if (etaEl) etaEl.textContent = countdown + 's...';
          if (countdown <= 0) {
            clearInterval(countTimer);
            location.reload();
          }
        }, 1000);
      }
      else if (data.phase === 'error') {
        clearInterval(pollInterval);
        window.removeEventListener('beforeunload', _beforeUnload);

        const bar = document.getElementById('imp-bar');
        if (bar) bar.style.background = '#ef4444';
        const icon = document.getElementById('imp-icon');
        if (icon) { icon.className = 'ti ti-alert-circle'; icon.style.color = '#ef4444'; }
        const title = document.getElementById('imp-title');
        if (title) title.textContent = 'Import Failed ✗';
        const sub = document.getElementById('imp-subtitle');
        if (sub) { sub.textContent = data.error || 'Unknown error occurred'; sub.style.color = '#f87171'; }
        _updateImportBar(100, 'Error occurred', data.error || '');

        setTimeout(() => overlay.remove(), 8000);
        showToast('Import failed: ' + (data.error || 'Unknown error'), '#ef4444');
      }
    } catch (e) {
      // Network blip during polling — keep trying
    }
  }, 1200);
}

function _fmtEta(seconds) {
  if (seconds < 60)   return Math.round(seconds) + 's';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
  return Math.round(seconds / 3600) + 'h ' + Math.round((seconds % 3600) / 60) + 'm';
}
