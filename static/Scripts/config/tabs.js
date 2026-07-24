// =========================================================================
// config/tabs.js
// Tab configuration: defines every main-tab and its sub-tabs (id, label,
// icon, panel) and builds a reverse lookup (sub-tab id -> main-tab id).
// Loaded first since every other file needs this config.
// =========================================================================

const MAIN_SUB_TABS = {
  dashboard: [],
  purchases: [
    { id: 'purchase', label: 'Purchase bill entry', icon: 'ti ti-file-invoice', panel: 'purchase-panel' },
    { id: 'purchase-return', label: 'Purchase return entry', icon: 'ti ti-rotate-2', panel: 'purchase-return-panel' },
    { id: 'purchase-bills', label: 'Bills (date wise)', icon: 'ti ti-calendar', panel: 'purchase-bills-panel' },
    { id: 'purchase-return-bills', label: 'Return bills', icon: 'ti ti-file-invoice', panel: 'purchase-return-bills-panel' },
    { id: 'purchase-borrow', label: 'Borrow', icon: 'ti ti-receipt-2', panel: 'purchase-borrow-panel' },
  ],
  sales: [
    { id: 'sell', label: 'Sale bill entry', icon: 'ti ti-file-invoice', panel: 'sell-panel' },
    { id: 'sale-bills', label: 'Bills (date wise)', icon: 'ti ti-calendar', panel: 'sale-bills-panel' },
    { id: 'sales-return', label: 'Sales return entry', icon: 'ti ti-rotate-2', panel: 'sales-return-panel' },
    { id: 'sales-return-bills', label: 'Return bills', icon: 'ti ti-file-invoice', panel: 'sales-return-bills-panel' },
    { id: 'sales-borrow', label: 'Borrow', icon: 'ti ti-receipt-2', panel: 'sales-borrow-panel' },
  ],
  'items-stock': [
    { id: 'items-list', label: 'All items list', icon: 'ti ti-packages', panel: 'items-list-panel' },
    { id: 'items-create', label: 'Create new items', icon: 'ti ti-package', panel: 'items-create-panel' },
    { id: 'item-stock', label: 'Stock valuation', icon: 'ti ti-chart-pie', panel: 'item-stock-panel' }
  ],
  parties: [
    { id: 'parties', label: 'Manage Parties', icon: 'ti ti-users', panel: 'parties-panel' }
  ],
  departments: [
    { id: 'departments', label: 'Manage Departments', icon: 'ti ti-building-store', panel: 'departments-panel' }
  ],
  reports: [
    { id: 'analyze', label: 'Purchase & Sales reports', icon: 'ti ti-chart-bar', panel: 'analyze-panel' },
    { id: 'monthly-report', label: 'Monthly reports', icon: 'ti ti-calendar-stats', panel: 'monthly-report-panel' },
    { id: 'profit-report', label: 'Profit report', icon: 'ti ti-trending-up', panel: 'profit-report-panel' }
  ],
  tally: [
    { id: 'tally-ledgers', label: 'Ledgers', icon: 'ti ti-book', panel: 'tally-ledgers-panel' },
    { id: 'tally-trial-balance', label: 'Trial Balance', icon: 'ti ti-list', panel: 'tally-trial-balance-panel' },
    { id: 'tally-balance-sheet', label: 'Balance Sheet', icon: 'ti ti-balance', panel: 'tally-balance-sheet-panel' },
    { id: 'tally-profit-loss', label: 'Profit & Loss', icon: 'ti ti-trending-up', panel: 'tally-profit-loss-panel' },
    { id: 'ledger-statement', label: 'Ledger Statement', icon: 'ti ti-file-text', panel: 'ledger-statement-panel' },
    { id: 'day-book', label: 'Day Book', icon: 'ti ti-calendar', panel: 'day-book-panel' },
    { id: 'voucher-list', label: 'Vouchers', icon: 'ti ti-list', panel: 'voucher-list-panel' },
    { id: 'voucher-payment', label: 'Payment entry', icon: 'ti ti-arrow-up-circle', panel: 'voucher-payment-panel' },
    { id: 'voucher-receipt', label: 'Receipt entry', icon: 'ti ti-arrow-down-circle', panel: 'voucher-receipt-panel' },
    { id: 'voucher-contra', label: 'Contra entry', icon: 'ti ti-transfer', panel: 'voucher-contra-panel' },
    { id: 'voucher-journal', label: 'Journal entry', icon: 'ti ti-notebook', panel: 'voucher-journal-panel' }
  ],
  settings: [
    { id: 'settings-backup', label: 'Data backup', icon: 'ti ti-database-export', panel: 'settings-backup-panel' },
    { id: 'settings-export', label: 'Data export', icon: 'ti ti-file-export', panel: 'settings-export-panel' },
    { id: 'settings-import', label: 'Data import', icon: 'ti ti-file-import', panel: 'settings-import-panel' },
    { id: 'settings-users', label: 'Manage users', icon: 'ti ti-users-group', panel: 'settings-users-panel' },
    { id: 'settings-accounts', label: 'Manage accounts', icon: 'ti ti-wallet', panel: 'settings-accounts-panel' },
    { id: 'settings-shop-info', label: 'Shop info', icon: 'ti ti-building-store', panel: 'settings-shop-info-panel' }
  ]
};

const SUB_TO_MAIN = {};
for (const [main, tabs] of Object.entries(MAIN_SUB_TABS)) {
  for (const tab of tabs) {
    SUB_TO_MAIN[tab.id] = main;
  }
}

