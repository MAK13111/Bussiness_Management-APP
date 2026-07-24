// =========================================================================
// modules/purchases/borrow.js
// Thin wrapper that loads the purchase "Borrow" tab (the actual data
// loading lives in ui/payment.js since it's shared between purchases and
// sales).
// =========================================================================

async function loadPurchaseBorrow() {
    await loadBorrowData('purchase');
}