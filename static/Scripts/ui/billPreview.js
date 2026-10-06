// =========================================================================
// ui/billPreview.js
// Shared detail modal & print preview panel used by Sales, Purchases and
// Reports. Displays aesthetic detailed breakdown panels for "Details" clicks
// and thermal-receipt preview for "Show Bill / Print" clicks.
// =========================================================================

function buildPurchaseBillDetailHTML(shopInfo, bill) {
  shopInfo = shopInfo || {};
  const dateFormatted = bill.date ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

  let subTotal = 0;
  let totalQty = 0;
  let totalSold = 0;

  const rowsHtml = bill.items.map((itm, idx) => {
    const rate = round2(itm.buy != null ? itm.buy : itm.buy_price);
    const qty = itm.qty || 0;
    const sold = +itm.sold || 0;
    const remaining = Math.max(0, qty - sold);
    const amount = round2(itm.buyTotal != null ? itm.buyTotal : rate * qty);
    const margin = itm.margin != null ? itm.margin : 0;
    subTotal += amount;
    totalQty += qty;
    totalSold += sold;

    const remainPct = qty > 0 ? Math.round((remaining / qty) * 100) : 0;
    const stockColor = remainPct > 50 ? '#10b981' : remainPct > 20 ? '#f59e0b' : '#ef4444';

    return `
      <tr style="border-bottom: 1px solid var(--color-border-tertiary); transition: background 0.15s ease;">
        <td style="padding: 10px 12px; font-size: 12px; text-align: center; color: var(--color-text-tertiary); font-weight: 600;">${idx + 1}</td>
        <td style="padding: 10px 12px; font-size: 13px; color: var(--color-text-primary); font-weight: 500;">
          ${itm.item || '—'}
          ${itm.department ? `<span style="display:inline-block; margin-left:6px; font-size:10px; padding:2px 6px; border-radius:4px; background:var(--color-background-tertiary); color:var(--color-text-secondary); border:1px solid var(--color-border-tertiary);">${itm.department}</span>` : ''}
        </td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: center;">
          <span style="display:inline-block; padding:2px 8px; border-radius:6px; background:var(--color-background-tertiary); color:var(--color-text-primary); font-size:11px; font-weight:600;">${itm.size || 'Free'}</span>
        </td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: center; color: var(--color-text-primary); font-weight: 600;">${qty}</td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: center;">
          <span style="font-size:11px; color:${stockColor}; font-weight:600;">${sold} sold / ${remaining} left</span>
        </td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: right; color: var(--color-text-secondary);">₹ ${fmtNum(rate)}</td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: center;">
          <span style="display:inline-block; padding:2px 6px; border-radius:4px; background:rgba(99, 102, 241, 0.15); color:#818cf8; font-size:11px; font-weight:700;">${margin}%</span>
        </td>
        <td style="padding: 10px 12px; font-size: 13px; text-align: right; color: var(--color-text-primary); font-weight: 700;">₹ ${fmtNum(amount)}</td>
      </tr>`;
  }).join('');

  subTotal = round2(subTotal);
  const discountPct = bill.discountPct || bill.discount || 0;
  const taxableAmount = subTotal;
  const discountAmt = round2(Math.max(0, subTotal - taxableAmount));
  const grandTotal = round2(bill.totalWithGST || taxableAmount);
  const cgstRate = bill.cgst != null ? bill.cgst : (bill.cgst_rate || 0);
  const sgstRate = bill.sgst != null ? bill.sgst : (bill.sgst_rate || 0);
  const igstRate = bill.igst != null ? bill.igst : (bill.igst_rate || 0);
  const totalGstRate = cgstRate + sgstRate + igstRate;
  const gstAmt = round2(Math.max(0, grandTotal - taxableAmount));
  const cgstAmt = round2(taxableAmount * cgstRate / 100);
  const sgstAmt = round2(taxableAmount * sgstRate / 100);
  const igstAmt = round2(taxableAmount * igstRate / 100);
  const paid = round2(bill.paidAmount || 0);
  const remaining = round2(bill.remainingAmount != null ? bill.remainingAmount : Math.max(0, grandTotal - paid));

  const statusLower = (bill.status || '').toLowerCase();
  const statusBg = statusLower === 'cash' || statusLower === 'paid' ? 'rgba(16, 185, 129, 0.15)' : statusLower === 'credit' || statusLower === 'overdue' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.15)';
  const statusColor = statusLower === 'cash' || statusLower === 'paid' ? '#10b981' : statusLower === 'credit' || statusLower === 'overdue' ? '#ef4444' : '#f59e0b';
  const statusText = bill.status || 'Cash';

  return `
    <div class="aesthetic-detail-panel" style="font-family:var(--font-sans); color:var(--color-text-primary); max-width:700px; margin:0 auto;">
      
      <!-- Top Card Header -->
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; padding:16px; border-radius:12px; background:var(--color-background-tertiary); border:1px solid var(--color-border-secondary); margin-bottom:16px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="width:42px; height:42px; border-radius:10px; background:linear-gradient(135deg, #6366f1, #4f46e5); display:flex; align-items:center; justify-content:center; color:#fff; font-size:20px; box-shadow:0 4px 12px rgba(99,102,241,0.3);">
            <i class="ti ti-file-invoice"></i>
          </div>
          <div>
            <div style="font-size:16px; font-weight:700; letter-spacing:0.2px;">Purchase Invoice #${bill.invoiceNo || bill.invoice_no || bill.purchase_id}</div>
            <div style="font-size:12px; color:var(--color-text-tertiary); display:flex; align-items:center; gap:6px; margin-top:2px;">
              <i class="ti ti-calendar" style="font-size:13px;"></i> ${dateFormatted}
              ${bill.department ? `<span>•</span><i class="ti ti-building-store" style="font-size:13px;"></i> ${bill.department}` : ''}
              ${totalGstRate > 0 ? `<span style="padding:1px 6px; border-radius:4px; background:rgba(168, 85, 247, 0.15); color:#c084fc; border:1px solid rgba(168, 85, 247, 0.3); font-weight:700; font-size:11px;">GST ${totalGstRate}%</span>` : ''}
            </div>
          </div>
        </div>
        <div style="padding:6px 14px; border-radius:20px; background:${statusBg}; color:${statusColor}; border:1px solid ${statusColor}44; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">
          ${statusText}
        </div>
      </div>

      <!-- Info Cards Grid -->
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:12px; margin-bottom:16px;">
        
        <!-- Seller Info Card -->
        <div style="padding:14px; border-radius:10px; background:var(--color-background-secondary); border:1px solid var(--color-border-tertiary);">
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:var(--color-text-tertiary); letter-spacing:0.5px; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
            <i class="ti ti-building-store" style="color:var(--color-accent); font-size:14px;"></i> Seller / Party Details
          </div>
          <div style="font-size:14px; font-weight:700; color:var(--color-text-primary);">${bill.party || bill.seller_name || 'Walk-in Vendor'}</div>
          ${bill.sellerNo || bill.seller_no ? `<div style="font-size:12px; color:var(--color-text-secondary); margin-top:4px;"><i class="ti ti-phone" style="font-size:12px;"></i> ${bill.sellerNo || bill.seller_no}</div>` : ''}
          ${bill.sellerAddress || bill.seller_address ? `<div style="font-size:12px; color:var(--color-text-secondary); margin-top:2px;"><i class="ti ti-map-pin" style="font-size:12px;"></i> ${bill.sellerAddress || bill.seller_address}</div>` : ''}
          ${bill.sellerGstNo || bill.seller_gst_no ? `<div style="font-size:12px; color:var(--color-text-secondary); margin-top:2px;"><i class="ti ti-receipt-tax" style="font-size:12px;"></i> GSTIN: <b>${bill.sellerGstNo || bill.seller_gst_no}</b></div>` : ''}
        </div>

        <!-- Summary Stats Card -->
        <div style="padding:14px; border-radius:10px; background:var(--color-background-secondary); border:1px solid var(--color-border-tertiary); display:flex; justify-content:space-around; align-items:center;">
          <div style="text-align:center;">
            <div style="font-size:11px; font-weight:600; color:var(--color-text-tertiary);">Total Items</div>
            <div style="font-size:20px; font-weight:800; color:var(--color-text-primary); margin-top:2px;">${bill.items.length}</div>
          </div>
          <div style="width:1px; height:32px; background:var(--color-border-tertiary);"></div>
          <div style="text-align:center;">
            <div style="font-size:11px; font-weight:600; color:var(--color-text-tertiary);">Purchased Qty</div>
            <div style="font-size:20px; font-weight:800; color:var(--color-accent); margin-top:2px;">${totalQty}</div>
          </div>
          <div style="width:1px; height:32px; background:var(--color-border-tertiary);"></div>
          <div style="text-align:center;">
            <div style="font-size:11px; font-weight:600; color:var(--color-text-tertiary);">Sold / Remaining</div>
            <div style="font-size:14px; font-weight:700; color:var(--color-text-primary); margin-top:6px;">${totalSold} / <span style="color:#10b981;">${totalQty - totalSold}</span></div>
          </div>
        </div>

      </div>

      <!-- Items Breakdown Table -->
      <div style="margin-bottom:16px; border-radius:10px; border:1px solid var(--color-border-tertiary); overflow:hidden; background:var(--color-background-secondary);">
        <div style="padding:10px 14px; font-size:12px; font-weight:700; text-transform:uppercase; color:var(--color-text-tertiary); background:var(--color-background-tertiary); border-bottom:1px solid var(--color-border-tertiary); display:flex; align-items:center; gap:6px;">
          <i class="ti ti-packages" style="color:var(--color-accent);"></i> Purchased Items List
        </div>
        <div style="overflow-x:auto;">
          <table style="width:100%; border-collapse:collapse;">
            <thead>
              <tr style="background:var(--color-background-tertiary); border-bottom:1px solid var(--color-border-tertiary);">
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center; width:40px;">#</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:left;">Item Name</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center;">Size</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center;">Qty</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center;">Status</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:right;">Buy Rate</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center;">Margin</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:right;">Total</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Financial Calculation Card -->
      <div style="display:flex; justify-content:flex-end;">
        <div style="width:100%; max-width:340px; padding:16px; border-radius:10px; background:var(--color-background-secondary); border:1px solid var(--color-border-tertiary);">
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>Sub Total</span>
            <span style="font-weight:600; color:var(--color-text-primary);">₹ ${fmtNum(subTotal)}</span>
          </div>
          ${discountPct > 0 ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>Discount (${discountPct}%)</span>
            <span style="font-weight:600; color:#ef4444;">- ₹ ${fmtNum(discountAmt)}</span>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>Taxable Amount</span>
            <span style="font-weight:600; color:var(--color-text-primary);">₹ ${fmtNum(taxableAmount)}</span>
          </div>` : ''}
          ${cgstRate > 0 ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>CGST (${cgstRate}%)</span>
            <span style="font-weight:600; color:var(--color-text-primary);">+ ₹ ${fmtNum(cgstAmt)}</span>
          </div>` : ''}
          ${sgstRate > 0 ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>SGST (${sgstRate}%)</span>
            <span style="font-weight:600; color:var(--color-text-primary);">+ ₹ ${fmtNum(sgstAmt)}</span>
          </div>` : ''}
          ${igstRate > 0 ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>IGST (${igstRate}%)</span>
            <span style="font-weight:600; color:var(--color-text-primary);">+ ₹ ${fmtNum(igstAmt)}</span>
          </div>` : ''}
          ${gstAmt > 0 && !(cgstRate > 0 || sgstRate > 0 || igstRate > 0) ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>GST Amount</span>
            <span style="font-weight:600; color:var(--color-text-primary);">+ ₹ ${fmtNum(gstAmt)}</span>
          </div>` : ''}
          <div style="height:1px; background:var(--color-border-tertiary); margin:8px 0;"></div>
          <div style="display:flex; justify-content:space-between; font-size:15px; font-weight:800; color:var(--color-text-primary); margin-bottom:8px;">
            <span>Grand Total</span>
            <span style="color:var(--color-accent);">₹ ${fmtNum(grandTotal)}</span>
          </div>
          ${remaining > 0 ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:#ef4444; font-weight:700; padding-top:4px; border-top:1px dashed var(--color-border-tertiary);">
            <span>Remaining Balance</span>
            <span>₹ ${fmtNum(remaining)}</span>
          </div>` : ''}
        </div>
      </div>

      <div style="font-size:11px; color:var(--color-text-tertiary); margin-top:12px; text-align:right; font-style:italic;">
        Amount in words: ${amountInWords(grandTotal)}
      </div>

    </div>
  `;
}

function buildSaleBillDetailHTML(shopInfo, bill) {
  shopInfo = shopInfo || {};
  const dateFormatted = bill.date ? new Date(bill.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

  let grandTotal = 0;
  let totalQty = 0;

  const rowsHtml = bill.items.map((itm, idx) => {
    const rate = round2(itm.sellUnit);
    const qty = itm.qty || 0;
    const amount = round2(itm.sellTotal != null ? itm.sellTotal : rate * qty);
    grandTotal += amount;
    totalQty += qty;

    return `
      <tr style="border-bottom: 1px solid var(--color-border-tertiary); transition: background 0.15s ease;">
        <td style="padding: 10px 12px; font-size: 12px; text-align: center; color: var(--color-text-tertiary); font-weight: 600;">${idx + 1}</td>
        <td style="padding: 10px 12px; font-size: 13px; color: var(--color-text-primary); font-weight: 500;">
          ${itm.item || '—'}
        </td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: center;">
          <span style="display:inline-block; padding:2px 8px; border-radius:6px; background:var(--color-background-tertiary); color:var(--color-text-primary); font-size:11px; font-weight:600;">${itm.size || 'Free'}</span>
        </td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: center; color: var(--color-text-primary); font-weight: 700;">${qty}</td>
        <td style="padding: 10px 12px; font-size: 12px; text-align: right; color: var(--color-text-secondary);">₹ ${fmtNum(rate)}</td>
        <td style="padding: 10px 12px; font-size: 13px; text-align: right; color: var(--color-text-primary); font-weight: 700;">₹ ${fmtNum(amount)}</td>
      </tr>`;
  }).join('');

  grandTotal = round2(grandTotal);
  const discountPct = bill.discountPct || 0;
  // Real pre-discount subtotal, stored directly at sale time -- no reverse
  // calculation from Grand Total / discount% anymore.
  const subTotal = round2(bill.subTotal || 0);
  const discountAmt = round2(Math.max(0, subTotal - grandTotal));
  const paid = round2(bill.paidAmount != null ? bill.paidAmount : grandTotal);
  const remaining = round2(bill.remainingAmount || 0);

  const pmLower = (bill.paymentMode || '').toLowerCase();
  const statusBg = pmLower === 'cash' ? 'rgba(16, 185, 129, 0.15)' : pmLower.includes('credit') ? 'rgba(239, 68, 68, 0.15)' : 'rgba(99, 102, 241, 0.15)';
  const statusColor = pmLower === 'cash' ? '#10b981' : pmLower.includes('credit') ? '#ef4444' : '#6366f1';
  const pmIcon = pmLower === 'cash' ? 'coin' : pmLower.includes('credit') ? 'credit-card' : pmLower.includes('split') ? 'arrows-split' : 'device-mobile';

  return `
    <div class="aesthetic-detail-panel" style="font-family:var(--font-sans); color:var(--color-text-primary); max-width:680px; margin:0 auto;">
      
      <!-- Top Card Header -->
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; padding:16px; border-radius:12px; background:var(--color-background-tertiary); border:1px solid var(--color-border-secondary); margin-bottom:16px;">
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="width:42px; height:42px; border-radius:10px; background:linear-gradient(135deg, #10b981, #059669); display:flex; align-items:center; justify-content:center; color:#fff; font-size:20px; box-shadow:0 4px 12px rgba(16,185,129,0.3);">
            <i class="ti ti-receipt"></i>
          </div>
          <div>
            <div style="font-size:16px; font-weight:700; letter-spacing:0.2px;">Sale Invoice #${bill.billNo || bill.sale_id}</div>
            <div style="font-size:12px; color:var(--color-text-tertiary); display:flex; align-items:center; gap:6px; margin-top:2px;">
              <i class="ti ti-calendar" style="font-size:13px;"></i> ${dateFormatted}
            </div>
          </div>
        </div>
        <div style="padding:6px 14px; border-radius:20px; background:${statusBg}; color:${statusColor}; border:1px solid ${statusColor}44; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; display:flex; align-items:center; gap:6px;">
          <i class="ti ti-${pmIcon}"></i> ${bill.paymentMode || 'Cash'}
        </div>
      </div>

      <!-- Info Cards Grid -->
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:12px; margin-bottom:16px;">
        
        <!-- Customer Info Card -->
        <div style="padding:14px; border-radius:10px; background:var(--color-background-secondary); border:1px solid var(--color-border-tertiary);">
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:var(--color-text-tertiary); letter-spacing:0.5px; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
            <i class="ti ti-user" style="color:var(--color-accent); font-size:14px;"></i> Customer Details
          </div>
          <div style="font-size:14px; font-weight:700; color:var(--color-text-primary);">${bill.customerName || 'Walk-in Customer'}</div>
          ${bill.customerNo ? `<div style="font-size:12px; color:var(--color-text-secondary); margin-top:4px;"><i class="ti ti-phone" style="font-size:12px;"></i> ${bill.customerNo}</div>` : ''}
        </div>

        <!-- Summary Stats Card -->
        <div style="padding:14px; border-radius:10px; background:var(--color-background-secondary); border:1px solid var(--color-border-tertiary); display:flex; justify-content:space-around; align-items:center;">
          <div style="text-align:center;">
            <div style="font-size:11px; font-weight:600; color:var(--color-text-tertiary);">Total Items</div>
            <div style="font-size:20px; font-weight:800; color:var(--color-text-primary); margin-top:2px;">${bill.items.length}</div>
          </div>
          <div style="width:1px; height:32px; background:var(--color-border-tertiary);"></div>
          <div style="text-align:center;">
            <div style="font-size:11px; font-weight:600; color:var(--color-text-tertiary);">Total Qty Sold</div>
            <div style="font-size:20px; font-weight:800; color:#10b981; margin-top:2px;">${totalQty}</div>
          </div>
        </div>

      </div>

      <!-- Items Breakdown Table -->
      <div style="margin-bottom:16px; border-radius:10px; border:1px solid var(--color-border-tertiary); overflow:hidden; background:var(--color-background-secondary);">
        <div style="padding:10px 14px; font-size:12px; font-weight:700; text-transform:uppercase; color:var(--color-text-tertiary); background:var(--color-background-tertiary); border-bottom:1px solid var(--color-border-tertiary); display:flex; align-items:center; gap:6px;">
          <i class="ti ti-package-export" style="color:var(--color-accent);"></i> Sold Items List
        </div>
        <div style="overflow-x:auto;">
          <table style="width:100%; border-collapse:collapse;">
            <thead>
              <tr style="background:var(--color-background-tertiary); border-bottom:1px solid var(--color-border-tertiary);">
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center; width:40px;">#</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:left;">Item Name</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center;">Size</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:center;">Qty</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:right;">Sell Rate</th>
                <th style="padding:8px 12px; font-size:11px; font-weight:700; color:var(--color-text-secondary); text-align:right;">Total</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Financial Calculation Card -->
      <div style="display:flex; justify-content:flex-end;">
        <div style="width:100%; max-width:340px; padding:16px; border-radius:10px; background:var(--color-background-secondary); border:1px solid var(--color-border-tertiary);">
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>Sub Total</span>
            <span style="font-weight:600; color:var(--color-text-primary);">₹ ${fmtNum(subTotal)}</span>
          </div>
          ${discountPct > 0 ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:6px;">
            <span>Discount (${discountPct}%)</span>
            <span style="font-weight:600; color:#ef4444;">- ₹ ${fmtNum(discountAmt)}</span>
          </div>` : ''}
          <div style="height:1px; background:var(--color-border-tertiary); margin:8px 0;"></div>
          <div style="display:flex; justify-content:space-between; font-size:15px; font-weight:800; color:var(--color-text-primary); margin-bottom:8px;">
            <span>Grand Total</span>
            <span style="color:#10b981;">₹ ${fmtNum(grandTotal)}</span>
          </div>
          ${pmLower === 'split' ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:4px;">
            <span>Cash Component</span>
            <span style="font-weight:600; color:var(--color-text-primary);">₹ ${fmtNum(bill.cashAmount || 0)}</span>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:4px;">
            <span>Online Component</span>
            <span style="font-weight:600; color:var(--color-text-primary);">₹ ${fmtNum(bill.onlineAmount || 0)}</span>
          </div>` : ''}
          <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); margin-bottom:4px;">
            <span>Paid Amount</span>
            <span style="font-weight:700; color:#10b981;">₹ ${fmtNum(paid)}</span>
          </div>
          ${remaining > 0 ? `
          <div style="display:flex; justify-content:space-between; font-size:12px; color:#ef4444; font-weight:700; padding-top:4px; border-top:1px dashed var(--color-border-tertiary);">
            <span>Remaining Balance</span>
            <span>₹ ${fmtNum(remaining)}</span>
          </div>` : ''}
        </div>
      </div>

      <div style="font-size:11px; color:var(--color-text-tertiary); margin-top:12px; text-align:right; font-style:italic;">
        Amount in words: ${amountInWords(grandTotal)}
      </div>

    </div>
  `;
}

// Opens the centered bill-preview modal with either an aesthetic details panel
// or thermal receipt HTML.
function openBillPreviewModal(html, title, isReceipt = false) {
  const titleEl = document.getElementById('bill-preview-title');
  const bodyEl = document.getElementById('bill-preview-body');
  const modalEl = document.getElementById('bill-preview-modal');
  const contentEl = modalEl ? modalEl.querySelector('.modal-content') : null;

  if (!titleEl || !bodyEl || !modalEl) return;

  titleEl.innerHTML = `<i class="ti ti-${isReceipt ? 'receipt' : 'file-description'}"></i> ${title || 'Bill Details'}`;
  bodyEl.innerHTML = html;

  if (contentEl) {
    contentEl.style.maxWidth = isReceipt ? '380px' : '720px';
  }
  if (bodyEl) {
    bodyEl.style.background = isReceipt ? '#fff' : 'var(--color-background-primary)';
    bodyEl.style.padding = isReceipt ? '12px' : '16px';
    bodyEl.style.display = isReceipt ? 'flex' : 'block';
    bodyEl.style.justifyContent = isReceipt ? 'center' : 'initial';
  }

  modalEl.style.display = 'flex';
}

function closeBillPreviewModal() {
  const bodyEl = document.getElementById('bill-preview-body');
  const modalEl = document.getElementById('bill-preview-modal');
  if (modalEl) modalEl.style.display = 'none';
  if (bodyEl) bodyEl.innerHTML = '';
}