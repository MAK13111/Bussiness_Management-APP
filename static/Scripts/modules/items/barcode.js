// =========================================================================
// modules/items/barcode.js
// Generating and printing barcodes, both for a single entry and for
// all sizes saved against a purchase.
// =========================================================================

// ─── Barcode size setting (Purchase → Generated Barcodes section only) ───
// Temporary: resets to 'medium' every time a fresh purchase's barcodes are shown.
const PURCHASE_BARCODE_SIZE_PRESETS = {
  small:  { barWidth: 1.2, barHeight: 38, fontSize: 9,  canvasMaxWidth: 100 },
  medium: { barWidth: 1.8, barHeight: 55, fontSize: 11, canvasMaxWidth: 130 },
  large:  { barWidth: 2.6, barHeight: 78, fontSize: 14, canvasMaxWidth: 170 }
};

let purchaseBarcodeGroups = [];
let purchaseBarcodeSize = { ...PURCHASE_BARCODE_SIZE_PRESETS.medium, preset: 'medium' };

function setPurchaseBarcodeSizePreset(preset) {
  const p = PURCHASE_BARCODE_SIZE_PRESETS[preset];
  if (!p) return;
  purchaseBarcodeSize = { ...p, preset };

  document.querySelectorAll('.psb-size-preset').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.size === preset);
  });
  const wEl = document.getElementById('psb-custom-width');
  const hEl = document.getElementById('psb-custom-height');
  if (wEl) wEl.value = p.barWidth;
  if (hEl) hEl.value = p.barHeight;

  renderPurchaseBarcodeCanvases();
}

function onPurchaseBarcodeCustomSize() {
  const wEl = document.getElementById('psb-custom-width');
  const hEl = document.getElementById('psb-custom-height');
  const w = parseFloat(wEl?.value);
  const h = parseFloat(hEl?.value);
  if (!w || !h || w <= 0 || h <= 0) return;

  purchaseBarcodeSize = {
    barWidth: w,
    barHeight: h,
    fontSize: Math.max(8, Math.round(h / 5)),
    canvasMaxWidth: Math.round(h * 2.3),
    preset: 'custom'
  };
  document.querySelectorAll('.psb-size-preset').forEach(btn => btn.classList.remove('active'));

  renderPurchaseBarcodeCanvases();
}

function renderPurchaseBarcodeCanvases() {
  purchaseBarcodeGroups.forEach(group => {
    group.barcodes.forEach((bc, idx) => {
      const canvas = document.getElementById(`psb-canvas-${group.purchase_item_id}-${idx}`);
      if (!canvas) return;
      canvas.style.maxWidth = purchaseBarcodeSize.canvasMaxWidth + 'px';
      try {
        JsBarcode(canvas, bc.code, {
          format: 'CODE128',
          width: purchaseBarcodeSize.barWidth,
          height: purchaseBarcodeSize.barHeight,
          displayValue: true,
          fontSize: purchaseBarcodeSize.fontSize,
          margin: 6,
          background: '#ffffff',
          lineColor: '#000000',
          font: 'monospace'
        });
      } catch (e) { console.error(e); }
    });
  });
}

async function showBarcodes(entryId) {
  const e = entries.find(x => x.id === entryId);
  if (!e) return;

  const sec = document.getElementById('bc-section');
  const grid = document.getElementById('bc-grid');
  const titleEl = document.getElementById('bc-title');
  const metaEl = document.getElementById('bc-meta');

  sec.style.display = 'block';
  sec.dataset.entryId = e.id;
  titleEl.textContent = (e.item || e.party || 'Item') + ' — barcodes';
  metaEl.textContent = `${e.qty} barcodes · ${e.party||''} · Sell: ${fmt(e.sellUnit)}/unit`;

  // Fetch actual barcodes from the database
  let barcodes = [];
  try {
    const res = await fetch(`/api/barcodes/purchase/${entryId}`);
    barcodes = await res.json();
  } catch (err) {
    console.error('Error fetching barcodes:', err);
    grid.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-danger)">Could not load barcodes.</div>';
    return;
  }

  if (barcodes.length === 0) {
    grid.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-tertiary)">No barcodes found for this purchase.</div>';
    return;
  }

  grid.innerHTML = '';
  barcodes.forEach((bc, idx) => {
    const isUsed = bc.status === 'sold';
    const card = document.createElement('div');
    card.className = 'bc-card';
    if (isUsed) card.style.opacity = '0.4';

    const nameEl = document.createElement('div');
    nameEl.className = 'bc-item-name';
    nameEl.textContent = e.item || e.party || 'Item';

    const sizeEl = document.createElement('div');
    sizeEl.style.cssText = 'font-size:11px;color:var(--color-text-secondary);margin-top:-4px';
    sizeEl.textContent = e.size ? `Size: ${e.size}` : '';

    const priceEl = document.createElement('div');
    priceEl.style.cssText = 'font-size:13px;font-weight:600;color:#16a34a;margin:4px 0 6px 0';
    priceEl.textContent = fmt(e.sellUnit);

    const canvas = document.createElement('canvas');

    const numEl = document.createElement('div');
    numEl.className = 'bc-num';
    numEl.textContent = isUsed ? `#${idx+1} — USED` : `#${idx+1}`;
    if (isUsed) numEl.style.color = '#dc2626';

    card.appendChild(nameEl);
    card.appendChild(sizeEl);
    card.appendChild(priceEl);
    card.appendChild(canvas);
    card.appendChild(numEl);
    grid.appendChild(card);

    try {
      JsBarcode(canvas, bc.code, {
        format: 'CODE128',
        width: 2,
        height: 65,
        displayValue: true,
        fontSize: 12,
        margin: 8,
        background: '#ffffff',
        lineColor: '#000000',
        font: 'monospace'
      });
    } catch (err) {
      console.error('JsBarcode error:', err);
    }
  });
  sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeBarcodes() {
  document.getElementById('bc-section').style.display = 'none';
  document.getElementById('bc-grid').innerHTML = '';
}

function printBarcodes() {
  const grid = document.getElementById('bc-grid');
  const title = document.getElementById('bc-title').textContent;
  const cards = grid.querySelectorAll('.bc-card');
  let imgs = '';
  cards.forEach((card,i) => {
    const name = card.querySelector('.bc-item-name').textContent;
    const sizeEl = card.querySelectorAll('div')[1];
    const size = sizeEl ? sizeEl.textContent : '';
    const priceEl = card.querySelectorAll('div')[2];
    const price = priceEl ? priceEl.textContent : '';
    const canvas = card.querySelector('canvas');
    imgs += `<div style="display:inline-block;margin:8px;padding:12px;border:1px solid #ddd;border-radius:8px;text-align:center;vertical-align:top;background:#fff;max-width:190px">
      <div style="font-size:13.5px;font-weight:600;margin-bottom:4px">${name}</div>
      ${size ? `<div style="font-size:12px;color:#555;margin-bottom:6px">${size}</div>` : ''}
      <div style="font-size:15px;font-weight:700;color:#16a34a;margin-bottom:8px">${price}</div>
      <img src="${canvas.toDataURL()}" style="display:block;width:175px" />
      <div style="font-size:11px;color:#444;margin-top:6px">#${i+1}</div>
    </div>`;
  });
  const w = window.open('','_blank');
  w.document.write(`<!DOCTYPE html><html><head><title>${title}</title>
    <style>body{font-family:sans-serif;padding:20px}h2{margin-bottom:20px}@media print{button{display:none}}</style>
    </head><body><h2>${title}</h2>${imgs}
    <br/><button onclick="window.print()" style="margin-top:20px;padding:10px 25px;cursor:pointer">Print</button>
    </body></html>`);
  w.document.close();
}

async function showPurchaseSavedBarcodes(purchaseId) {
    const sec = document.getElementById('purchase-saved-barcodes');
    if (!sec) return;
    sec.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--color-text-secondary)"><i class="ti ti-loader" style="animation:spin 1s linear infinite"></i> Loading barcodes...</div>';
    sec.style.display = 'block';
    sec.scrollIntoView({ behavior: 'smooth', block: 'start' });

    let groups = [];
    try {
        const res = await fetch(`/api/barcodes/by_purchase/${purchaseId}`);
        groups = await res.json();
    } catch (e) {
        sec.innerHTML = '<div style="color:var(--color-text-danger);padding:1rem">Could not load barcodes.</div>';
        return;
    }

    if (!groups || groups.length === 0) {
        sec.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-tertiary)">No barcodes generated.</div>';
        return;
    }

    // Reset the size setting to Medium each time a fresh purchase's barcodes load
    purchaseBarcodeGroups = groups;
    purchaseBarcodeSize = { ...PURCHASE_BARCODE_SIZE_PRESETS.medium, preset: 'medium' };

    let html = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
            <span style="font-weight:700;font-size:15px"><i class="ti ti-barcode" style="margin-right:6px"></i>Generated Barcodes</span>
            <div style="display:flex;gap:8px">
                <button onclick="printPurchaseSavedBarcodes()" style="background:var(--color-accent);color:#fff;border:none;padding:6px 14px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:500"><i class="ti ti-printer"></i> Print All</button>
                <button onclick="document.getElementById('purchase-saved-barcodes').style.display='none'" style="background:var(--color-background-tertiary);border:1px solid var(--color-border-secondary);color:var(--color-text-primary);padding:6px 14px;border-radius:8px;font-size:13px;cursor:pointer">Close</button>
            </div>
        </div>
        <div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:10px 12px;margin-bottom:1.25rem;background:var(--color-background-tertiary);border:1px solid var(--color-border-secondary);border-radius:10px">
            <span style="font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--color-text-tertiary)"><i class="ti ti-ruler-2" style="margin-right:5px"></i>Barcode Setting</span>
            <div style="display:flex;align-items:center;gap:6px">
                <button type="button" class="psb-size-preset" data-size="small"  onclick="setPurchaseBarcodeSizePreset('small')"  style="padding:5px 12px;border-radius:6px;border:1px solid var(--color-border-secondary);background:var(--color-background-secondary);color:var(--color-text-primary);font-size:12px;cursor:pointer">Small</button>
                <button type="button" class="psb-size-preset active" data-size="medium" onclick="setPurchaseBarcodeSizePreset('medium')" style="padding:5px 12px;border-radius:6px;border:1px solid var(--color-border-secondary);background:var(--color-background-secondary);color:var(--color-text-primary);font-size:12px;cursor:pointer">Medium</button>
                <button type="button" class="psb-size-preset" data-size="large"  onclick="setPurchaseBarcodeSizePreset('large')"  style="padding:5px 12px;border-radius:6px;border:1px solid var(--color-border-secondary);background:var(--color-background-secondary);color:var(--color-text-primary);font-size:12px;cursor:pointer">Large</button>
            </div>
            <span style="font-size:12px;color:var(--color-text-tertiary)">or custom</span>
            <input id="psb-custom-width" type="number" min="0.5" step="0.1" placeholder="Width" value="${purchaseBarcodeSize.barWidth}" oninput="onPurchaseBarcodeCustomSize()"
                style="width:64px;padding:5px 8px;border-radius:6px;border:1px solid var(--color-border-secondary);background:var(--color-background-secondary);color:var(--color-text-primary);font-size:12px"/>
            <span style="font-size:11px;color:var(--color-text-tertiary)">×</span>
            <input id="psb-custom-height" type="number" min="10" step="1" placeholder="Height" value="${purchaseBarcodeSize.barHeight}" oninput="onPurchaseBarcodeCustomSize()"
                style="width:64px;padding:5px 8px;border-radius:6px;border:1px solid var(--color-border-secondary);background:var(--color-background-secondary);color:var(--color-text-primary);font-size:12px"/>
        </div>`;

    groups.forEach(group => {
        html += `
        <div style="margin-bottom:1.5rem">
            <div style="font-size:13px;font-weight:600;color:var(--color-text-primary);padding:6px 0 8px 0;border-bottom:1px solid var(--color-border-secondary);margin-bottom:10px;display:flex;align-items:center;gap:8px">
                <span style="background:var(--color-accent);color:#fff;border-radius:6px;padding:2px 8px;font-size:12px">${group.item}</span>
                ${group.size ? `<span style="color:var(--color-text-secondary);font-size:12px">Size: <strong>${group.size}</strong></span>` : ''}
                <span style="color:var(--color-text-tertiary);font-size:12px;margin-left:auto">${group.barcodes.length} barcodes · ${fmt(group.sell_price)}/unit</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:10px">
                ${group.barcodes.map((bc, idx) => `
                <div class="psb-card" style="background:var(--color-background-secondary);border:1px solid var(--color-border-secondary);border-radius:10px;padding:10px;text-align:center;min-width:140px">
                    <div style="font-size:12px;font-weight:600;color:var(--color-text-primary)">${group.item}${group.size ? ' · '+group.size : ''}</div>
                    <div style="font-size:11px;color:var(--color-text-success);margin-bottom:6px">${fmt(group.sell_price)}</div>
                    <canvas id="psb-canvas-${group.purchase_item_id}-${idx}" style="max-width:${purchaseBarcodeSize.canvasMaxWidth}px"></canvas>
                    <div style="font-size:10px;color:var(--color-text-tertiary);margin-top:4px">#${idx+1}</div>
                </div>`).join('')}
            </div>
        </div>`;
    });

    sec.innerHTML = html;

    renderPurchaseBarcodeCanvases();
}

async function showBillBarcodes(purchaseId) {
    const modal = document.getElementById('bill-barcode-modal');
    const body = document.getElementById('bill-barcode-modal-body');
    const title = document.getElementById('bill-barcode-modal-title');
    if (!modal || !body) return;

    title.textContent = 'Bill #' + purchaseId + ' — Barcodes';
    body.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--color-text-secondary)"><i class="ti ti-loader" style="animation:spin 1s linear infinite"></i> Loading barcodes...</div>';
    modal.style.display = 'flex';

    let groups = [];
    try {
        const res = await fetch(`/api/barcodes/by_purchase/${purchaseId}`);
        groups = await res.json();
    } catch (e) {
        body.innerHTML = '<div style="color:var(--color-text-danger);padding:1rem">Could not load barcodes.</div>';
        return;
    }

    if (!groups || groups.length === 0) {
        body.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--color-text-tertiary)">No barcodes generated for this bill.</div>';
        return;
    }

    let html = '';
    groups.forEach(group => {
        html += `
        <div style="margin-bottom:1.5rem">
            <div style="font-size:13px;font-weight:600;color:var(--color-text-primary);padding:6px 0 8px 0;border-bottom:1px solid var(--color-border-secondary);margin-bottom:10px;display:flex;align-items:center;gap:8px">
                <span style="background:var(--color-accent);color:#fff;border-radius:6px;padding:2px 8px;font-size:12px">${group.item}</span>
                ${group.size ? `<span style="color:var(--color-text-secondary);font-size:12px">Size: <strong>${group.size}</strong></span>` : ''}
                <span style="color:var(--color-text-tertiary);font-size:12px;margin-left:auto">${group.barcodes.length} barcodes · ${fmt(group.sell_price)}/unit</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:10px">
                ${group.barcodes.map((bc, idx) => `
                <div class="bbc-card" style="background:var(--color-background-secondary);border:1px solid var(--color-border-secondary);border-radius:10px;padding:10px;text-align:center;min-width:140px">
                    <div style="font-size:12px;font-weight:600;color:var(--color-text-primary)">${group.item}${group.size ? ' · '+group.size : ''}</div>
                    <div style="font-size:11px;color:var(--color-text-success);margin-bottom:6px">${fmt(group.sell_price)}</div>
                    <canvas id="bbc-canvas-${group.purchase_item_id}-${idx}" style="max-width:130px"></canvas>
                    <div style="font-size:10px;color:var(--color-text-tertiary);margin-top:4px">#${idx+1}</div>
                </div>`).join('')}
            </div>
        </div>`;
    });

    body.innerHTML = html;

    groups.forEach(group => {
        group.barcodes.forEach((bc, idx) => {
            const canvas = document.getElementById(`bbc-canvas-${group.purchase_item_id}-${idx}`);
            if (!canvas) return;
            try {
                JsBarcode(canvas, bc.code, {
                    format: 'CODE128', width: 1.8, height: 55,
                    displayValue: true, fontSize: 11, margin: 6,
                    background: '#ffffff', lineColor: '#000000', font: 'monospace'
                });
            } catch(e) { console.error(e); }
        });
    });
}

function closeBillBarcodes() {
    const modal = document.getElementById('bill-barcode-modal');
    if (modal) modal.style.display = 'none';
}

function printBillBarcodes() {
    const cards = document.querySelectorAll('#bill-barcode-modal-body .bbc-card');
    if (!cards.length) return;
    let printHtml = '<html><head><style>body{font-family:monospace;margin:0}.card{display:inline-block;border:1px solid #ccc;border-radius:8px;padding:8px;margin:6px;text-align:center;vertical-align:top}img{max-width:130px;display:block;margin:0 auto}@media print{body{margin:0}}</style></head><body>';
    cards.forEach(c => {
        const clone = c.cloneNode(true);
        const originalCanvas = c.querySelector('canvas');
        const cloneCanvas = clone.querySelector('canvas');
        if (originalCanvas && cloneCanvas) {
            const img = document.createElement('img');
            img.src = originalCanvas.toDataURL();
            cloneCanvas.replaceWith(img);
        }
        printHtml += `<div class="card">${clone.innerHTML}</div>`;
    });
    printHtml += '</body></html>';
    const w = window.open('', '_blank');
    w.document.write(printHtml);
    w.document.close();
    w.focus();
    setTimeout(() => { w.print(); w.close(); }, 400);
}

function printPurchaseSavedBarcodes() {
    const cards = document.querySelectorAll('#purchase-saved-barcodes .psb-card');
    if (!cards.length) return;
    const imgMaxWidth = purchaseBarcodeSize.canvasMaxWidth;
    let printHtml = `<html><head><style>body{font-family:monospace;margin:0}.card{display:inline-block;border:1px solid #ccc;border-radius:8px;padding:8px;margin:6px;text-align:center;vertical-align:top}img{max-width:${imgMaxWidth}px;display:block;margin:0 auto}@media print{body{margin:0}}</style></head><body>`;
    cards.forEach(c => {
        // Canvas content is NOT copied by innerHTML, so we convert each
        // canvas to a data-URL image before injecting it into the print HTML.
        const clone = c.cloneNode(true);
        const originalCanvas = c.querySelector('canvas');
        const cloneCanvas = clone.querySelector('canvas');
        if (originalCanvas && cloneCanvas) {
            const img = document.createElement('img');
            img.src = originalCanvas.toDataURL();
            cloneCanvas.replaceWith(img);
        }
        printHtml += `<div class="card">${clone.innerHTML}</div>`;
    });
    printHtml += '</body></html>';
    const w = window.open('', '_blank');
    w.document.write(printHtml);
    w.document.close();
    w.focus();
    setTimeout(() => { w.print(); w.close(); }, 400);
}

