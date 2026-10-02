// =========================================================================
// modules/settings/shopInfo.js
// Shop info settings: loading and saving.
// =========================================================================

async function loadShopInfo() {
  try {
    const res = await fetch('/api/shop_settings');
    const info = await res.json();
    document.getElementById('shop-name').value = info.shop_name || '';
    document.getElementById('shop-address').value = info.address || '';
    document.getElementById('shop-phone').value = info.phone || '';
    document.getElementById('shop-gst').value = info.gst_no || '';
    document.getElementById('shop-footer').value = info.footer_note || '';
  } catch (err) { console.error('Error loading shop info:', err); }
}

async function saveShopInfo() {
  const payload = {
    shop_name: document.getElementById('shop-name').value.trim(),
    address: document.getElementById('shop-address').value.trim(),
    phone: document.getElementById('shop-phone').value.trim(),
    gst_no: document.getElementById('shop-gst').value.trim(),
    footer_note: document.getElementById('shop-footer').value.trim()
  };
  try {
    const res = await fetch('/api/shop_settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) showToast('Shop info saved');
    else showToast('Error saving shop info', '#ef4444');
  } catch (err) { showToast('Error saving shop info', '#ef4444'); }
}

