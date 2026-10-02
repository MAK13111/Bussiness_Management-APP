// =========================================================================
// modules/purchases/filters.js
// Search and filter controls for the purchase entries list.
// =========================================================================

function getFilteredPurchaseEntries() {
  let list = [...entries];
  const q = purchaseQuery.toLowerCase();
  if (q) list = list.filter(e => (e.item||'').toLowerCase().includes(q) || (e.party||'').toLowerCase().includes(q));
  if (purchaseFilters.party) list = list.filter(e => (e.party||'').toLowerCase().includes(purchaseFilters.party));
  if (purchaseFilters.item)  list = list.filter(e => (e.item||'').toLowerCase().includes(purchaseFilters.item));
  if (purchaseFilters.dept)  list = list.filter(e => (e.department||'') === purchaseFilters.dept);
  if (purchaseFilters.priceMin !== null) list = list.filter(e => +e.buy >= purchaseFilters.priceMin);
  if (purchaseFilters.priceMax !== null) list = list.filter(e => +e.buy <= purchaseFilters.priceMax);
  if (purchaseFilters.dateFrom) list = list.filter(e => e.date && e.date.slice(0,10) >= purchaseFilters.dateFrom);
  if (purchaseFilters.dateTo)   list = list.filter(e => e.date && e.date.slice(0,10) <= purchaseFilters.dateTo);
  const sort = purchaseFilters.sort;
  if (sort === 'item-asc')    list.sort((a,b) => (a.item||'').localeCompare(b.item||''));
  if (sort === 'item-desc')   list.sort((a,b) => (b.item||'').localeCompare(a.item||''));
  if (sort === 'party-asc')   list.sort((a,b) => (a.party||'').localeCompare(b.party||''));
  if (sort === 'party-desc')  list.sort((a,b) => (b.party||'').localeCompare(a.party||''));
  if (sort === 'dept-asc')    list.sort((a,b) => (a.department||'').localeCompare(b.department||''));
  if (sort === 'dept-desc')   list.sort((a,b) => (b.department||'').localeCompare(a.department||''));
  if (sort === 'price-asc')   list.sort((a,b) => +a.buy - +b.buy);
  if (sort === 'price-desc')  list.sort((a,b) => +b.buy - +a.buy);
  if (sort === 'date-asc')    list.sort((a,b) => (a.date||'').localeCompare(b.date||''));
  if (sort === 'date-desc')   list.sort((a,b) => (b.date||'').localeCompare(a.date||''));
  return list;
}

