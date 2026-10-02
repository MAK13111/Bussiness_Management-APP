"""
core/calculations.py

Single source of truth for money-formula calculations that were previously
duplicated (or only present) in frontend JS. Pure functions only -- no Flask,
no DB access -- so routes and (later) tests can both import this safely.

The live-typing preview in static/Scripts/core/... still mirrors these
formulas in JS on purpose (so the UI updates instantly per keystroke without
a network round trip). Everything that gets *saved* or *reported* should
come from here.
"""


from core.shared_helpers import round2


def compute_purchase_item_totals(qty, buy_price, margin_pct=0, discount_pct=0,
                                  cgst_pct=0, sgst_pct=0, igst_pct=0, sell_price=None):
    """
    Mirrors the formula used when saving a purchase bill (routes/purchases.py
    L187-199) and the live preview in static/Scripts/modules/purchases/entry.js
    (recalcRow, L190-208).

    - sell_unit: margin is applied to the RAW buy price (before supplier
      discount), then rounded to the nearest 5 -- a supplier discount never
      reduces the selling price or margin, it only reduces cost (see
      entry.js L198-199 comment). Skipped when an explicit sell_price is given.
    - effective_buy: buy price after the supplier discount -- this is what
      drives buy_total, GST, and profit. It does NOT feed into sell_unit.
    - GST is charged on the BUY (cost) side -- the amount payable to the
      supplier -- not on the sell side.
    """
    qty = qty or 0
    buy_price = buy_price or 0
    margin_pct = margin_pct or 0
    discount_pct = discount_pct or 0

    if sell_price is not None:
        sell_unit = sell_price
    else:
        sell_unit = round(buy_price * (1 + margin_pct / 100) / 5) * 5

    sell_total = round2(sell_unit * qty)

    effective_buy = buy_price * (1 - discount_pct / 100)
    buy_total = round2(effective_buy * qty)
    profit = round2(sell_total - buy_total)

    gst_pct = (cgst_pct or 0) + (sgst_pct or 0) + (igst_pct or 0)
    total_with_gst = round2(buy_total * (1 + gst_pct / 100))
    gst_total = round2(total_with_gst - buy_total)

    return {
        "effectiveBuy": round2(effective_buy),
        "sellUnit": round2(sell_unit),
        "buyTotal": buy_total,
        "sellTotal": sell_total,
        "profit": profit,
        "gstTotal": gst_total,
        "totalWithGST": total_with_gst,
    }


def profit_margin_pct(total_profit, total_sales):
    """
    Was computed client-side in static/Scripts/modules/reports/profit.js:
        margin = totals.sales > 0 ? (totals.profit / totals.sales) * 100 : 0
    Moved here so the API can return it directly.
    """
    total_sales = total_sales or 0
    total_profit = total_profit or 0
    if total_sales <= 0:
        return 0.0
    return round2((total_profit / total_sales) * 100)
