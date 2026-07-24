// =========================================================================
// modules/sales/filters.js
// Search and filter controls for the sale entries list.
// =========================================================================

function getFilteredSellEntries() {
  let list = [...sellEntries];
  const q = sellQuery.toLowerCase();
  if (q) list = list.filter(e =>
    (e.customerName||'').toLowerCase().includes(q) ||
    (e.customerNo||'').toLowerCase().includes(q) ||
    (e.billNo||'').toLowerCase().includes(q)
  );
  if (sellFilters.customer) list = list.filter(e => (e.customerName||'').toLowerCase().includes(sellFilters.customer));
  if (sellFilters.item)     list = list.filter(e => (e.item||'').toLowerCase().includes(sellFilters.item));
  if (sellFilters.priceMin !== null) list = list.filter(e => +e.sellUnit >= sellFilters.priceMin);
  if (sellFilters.priceMax !== null) list = list.filter(e => +e.sellUnit <= sellFilters.priceMax);
  if (sellFilters.dateFrom) list = list.filter(e => e.date && e.date.slice(0,10) >= sellFilters.dateFrom);
  if (sellFilters.dateTo)   list = list.filter(e => e.date && e.date.slice(0,10) <= sellFilters.dateTo);
  if (sellFilters.payment)  list = list.filter(e => (e.paymentMode||'') === sellFilters.payment);
  if (sellFilters.bill)     list = list.filter(e => (e.billNo||'').toLowerCase().includes(sellFilters.bill));
  const sort = sellFilters.sort;
  if (sort === 'item-asc')      list.sort((a,b) => (a.item||'').localeCompare(b.item||''));
  if (sort === 'item-desc')     list.sort((a,b) => (b.item||'').localeCompare(a.item||''));
  if (sort === 'customer-asc')  list.sort((a,b) => (a.customerName||'').localeCompare(b.customerName||''));
  if (sort === 'customer-desc') list.sort((a,b) => (b.customerName||'').localeCompare(a.customerName||''));
  if (sort === 'price-asc')     list.sort((a,b) => +a.sellUnit - +b.sellUnit);
  if (sort === 'price-desc')    list.sort((a,b) => +b.sellUnit - +a.sellUnit);
  if (sort === 'date-asc')      list.sort((a,b) => (a.date||'').localeCompare(b.date||''));
  if (sort === 'date-desc')     list.sort((a,b) => (b.date||'').localeCompare(a.date||''));
  if (sort === 'payment-asc')   list.sort((a,b) => (a.paymentMode||'').localeCompare(b.paymentMode||''));
  if (sort === 'payment-desc')  list.sort((a,b) => (b.paymentMode||'').localeCompare(a.paymentMode||''));
  return list;
}

