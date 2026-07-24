// =========================================================================
// modules/sales/entry.js
// Sale bill entry form: saving a new sale, auto-filling the invoice
// number, and managing the cash/credit mode for both purchases and sales.
// =========================================================================

function setPurchaseMode(mode) {
    purchaseMode = mode;
    const cashTab = document.getElementById('purchase-mode-cash');
    const creditTab = document.getElementById('purchase-mode-credit');
    
    if (mode === 'cash') {
        cashTab.classList.add('active');
        creditTab.classList.remove('active');
    } else {
        cashTab.classList.remove('active');
        creditTab.classList.add('active');
    }
    
    const modeLabel = document.getElementById('sidebar-mode-label');
    if (modeLabel) {
        modeLabel.textContent = mode === 'cash' ? 'Cash mode' : 'Credit mode';
    }
}

function setSaleMode(mode) {
    saleMode = mode;
    const cashTab = document.getElementById('sale-mode-cash');
    const creditTab = document.getElementById('sale-mode-credit');
    
    if (mode === 'cash') {
        cashTab.classList.add('active');
        creditTab.classList.remove('active');
        // Show payment mode dropdown
        const paymentMode = document.getElementById('f-payment-mode');
        if (paymentMode) paymentMode.style.display = '';
        document.getElementById('split-payment-fields').style.display = 'none';
        document.getElementById('credit-advance-fields').style.display = 'none';
    } else {
        cashTab.classList.remove('active');
        creditTab.classList.add('active');
        // Hide payment mode dropdown for credit
        const paymentMode = document.getElementById('f-payment-mode');
        if (paymentMode) paymentMode.style.display = 'none';
        document.getElementById('split-payment-fields').style.display = 'none';
        document.getElementById('credit-advance-fields').style.display = '';
    }
    
    const modeLabel = document.getElementById('sidebar-mode-label');
    if (modeLabel) {
        modeLabel.textContent = mode === 'cash' ? 'Cash mode' : 'Credit mode';
    }
}

// Default the Date field to today when the page loads
const saleDateInput = document.getElementById('f-sale-date');
if (saleDateInput) saleDateInput.value = todayLocalDate();