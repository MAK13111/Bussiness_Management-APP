// =========================================================================
// modules/sales/entry.js
// Sale bill entry form: saving a new sale, auto-filling the invoice
// number, and managing the cash/credit mode for both purchases and sales.
// =========================================================================

function setPurchaseMode(mode) {
    purchaseMode = mode;
    const cashTab = document.getElementById('purchase-mode-cash');
    const creditTab = document.getElementById('purchase-mode-credit');
    const advanceFields = document.getElementById('purchase-credit-advance-fields');
    
    if (mode === 'cash') {
        cashTab.classList.add('active');
        creditTab.classList.remove('active');
        if (advanceFields) advanceFields.style.display = 'none';
    } else {
        cashTab.classList.remove('active');
        creditTab.classList.add('active');
        if (advanceFields) advanceFields.style.display = '';
            }
    
    const modeLabel = document.getElementById('sidebar-mode-label');
    if (modeLabel) {
        modeLabel.textContent = mode === 'cash' ? 'Cash mode' : 'Credit mode';
    }
}
// Default the Date field to today when the page loads
const saleDateInput = document.getElementById('f-sale-date');
if (saleDateInput) saleDateInput.value = todayLocalDate();