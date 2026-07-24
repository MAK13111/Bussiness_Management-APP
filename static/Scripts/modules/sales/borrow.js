// =========================================================================
// modules/sales/borrow.js
// Thin wrapper that loads the sales "Borrow" tab (the actual data loading
// lives in ui/payment.js since it's shared between purchases and sales).
// =========================================================================

async function loadSalesBorrow() {
    await loadBorrowData('sales');
}