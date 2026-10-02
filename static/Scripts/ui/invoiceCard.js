// =========================================================================
// ui/invoiceCard.js
// Single shared renderer for every "Bills (date wise)" style card --
// Purchases > Bills, Sales > Bills, and their Reports-tab counterparts.
// These four panels used to each carry their own copy-pasted card markup
// (only the CSS class prefix, columns and footer buttons ever changed).
// Now every one of them builds a config object describing just those
// differences and calls buildInvoiceCardHTML() once -- the actual
// card/header/table/footer markup is written here, in exactly one place.
//
// Loaded before modules/purchases/bills.js, modules/sales/bills.js and
// modules/reports/filters.js (see templates/base.html), since all three
// call buildInvoiceCardHTML().
// =========================================================================

/**
 * @param {Object} cfg
 * @param {string} cfg.prefix          CSS class prefix already used by that panel's stylesheet, e.g. 'pb' or 'sb'.
 * @param {string} cfg.uid             Unique id for this card (passed to toggleBillDetail).
 * @param {string} cfg.headerLabel     'Invoice' / 'Bill'.
 * @param {string} cfg.headerNo        Invoice/bill number, already formatted (e.g. '#1234').
 * @param {Array}  [cfg.subInfo]       [{icon, text, size, textStyle}] lines under the header no (party/customer name, phone...).
 * @param {Array}  cfg.chips           [{icon, text, style, className}] header-right chips (date, mode, department, items, total...).
 * @param {Array}  cfg.tableHeaders    [{label, align: 'center'|'right', width}] column headers for the item table.
 * @param {string} cfg.itemRowsHtml    Pre-built <tr> markup for the item table body (columns differ per panel, so each caller still builds its own rows).
 * @param {Array}  cfg.footerStats     [{label, value, style}] left-side footer stat blocks (a divider is inserted automatically between them).
 * @param {string} cfg.totalLabel      Usually 'Grand Total'.
 * @param {string} cfg.totalAmount     Pre-formatted grand total, e.g. fmt(123).
 * @param {string} [cfg.totalWithGSTAmount] Pre-formatted GST-inclusive total; shown only when it differs from totalAmount.
 * @param {Array}  cfg.footerButtons   [{icon, label, onclick, title}] right-side action buttons.
 * @returns {string} HTML for one invoice card.
 */
function buildInvoiceCardHTML(cfg) {
  const p = cfg.prefix;

  const chipsHtml = (cfg.chips || []).map(c => `
    <span class="${p}-meta-chip ${c.className || ''}" ${c.style ? `style="${c.style}"` : ''}>
      ${c.icon ? `<i class="ti ti-${c.icon}"></i>` : ''}${c.text}
    </span>
  `).join('');

  const subInfoHtml = (cfg.subInfo || []).map(s => `
    <div class="${p}-party-wrap">
      <i class="ti ti-${s.icon}" style="color:var(--color-text-tertiary); font-size:${s.size || '13px'};"></i>
      <span class="${p}-party-name" ${s.textStyle ? `style="${s.textStyle}"` : ''}>${s.text}</span>
    </div>
  `).join('');

  const theadHtml = (cfg.tableHeaders || []).map(h => `
    <th class="${p}-th${h.align === 'center' ? ` ${p}-th-center` : h.align === 'right' ? ` ${p}-th-right` : ''}" ${h.width ? `style="width:${h.width}"` : ''}>${h.label}</th>
  `).join('');

  const footerStatsHtml = (cfg.footerStats || []).map((s, i) => `
    ${i > 0 ? `<span class="${p}-footer-divider"></span>` : ''}
    <span class="${p}-footer-stat">
      <span class="${p}-footer-stat-label">${s.label}</span>
      <span class="${p}-footer-stat-val" ${s.style ? `style="${s.style}"` : ''}>${s.value}</span>
    </span>
  `).join('');

  const footerButtonsHtml = (cfg.footerButtons || []).map(b => {
    const isDanger = b.icon === 'trash' || b.variant === 'danger';
    const isDull = !!b.dull || !!b.disabled;
    const btnClass = `invoice-card-btn ${p}-footer-edit-btn ${isDanger ? 'btn-danger' : ''} ${isDull ? 'btn-dull' : ''}`;
    const defaultMsg = 'Not able to delete this bill because one or more items of this bill have been sold.';
    const clickHandler = isDull
      ? `event.stopPropagation();showToast('${(b.disabledMessage || defaultMsg).replace(/'/g, "\\'")}', '#dc2626', 3000)`
      : `event.stopPropagation();${b.onclick}`;
    return `
      <button class="${btnClass}" onclick="${clickHandler}" title="${b.title || (isDull ? (b.disabledMessage || defaultMsg) : '')}">
        <i class="ti ti-${b.icon}"></i> ${b.label}
      </button>
    `;
  }).join('');


  const gstHtml = (cfg.totalWithGSTAmount && cfg.totalWithGSTAmount !== cfg.totalAmount) ? `
    <span class="${p}-total-gst-wrap">
      <span class="${p}-total-label">With GST</span>
      <span class="${p}-total-amount ${p}-total-amount-gst">${cfg.totalWithGSTAmount}</span>
    </span>
  ` : '';

  return `
    <div class="${p}-invoice-card">
      <div class="${p}-invoice-header" style="cursor:pointer" onclick="toggleBillDetail('${cfg.uid}')">
        <div class="${p}-invoice-header-left">
          <div class="${p}-invoice-no-wrap">
            <span class="${p}-invoice-label">${cfg.headerLabel}</span>
            <span class="${p}-invoice-no">${cfg.headerNo}</span>
          </div>
          ${subInfoHtml}
        </div>
        <div class="${p}-invoice-header-right">
          ${chipsHtml}
          <button onclick="event.stopPropagation();toggleBillDetail('${cfg.uid}')" id="btn-${cfg.uid}" style="background:none;border:none;color:var(--color-accent);cursor:pointer;padding:2px 4px;font-size:16px" title="View details"><i class="ti ti-chevron-down"></i></button>
        </div>
      </div>
      <div id="${cfg.uid}" style="display:none">
        <div class="${p}-table-wrap">
          <table class="${p}-table">
            <thead><tr>${theadHtml}</tr></thead>
            <tbody>${cfg.itemRowsHtml}</tbody>
          </table>
        </div>
        <div class="${p}-invoice-footer">
          <div class="${p}-footer-stats">${footerStatsHtml}</div>
          <div class="${p}-invoice-total">
            <span class="${p}-total-label">${cfg.totalLabel}</span>
            <span class="${p}-total-amount">${cfg.totalAmount}</span>
            ${gstHtml}
          </div>
          <div style="display:flex;align-items:center;gap:8px;justify-self:end;">
            ${footerButtonsHtml}
          </div>
        </div>
      </div>
    </div>
  `;
}