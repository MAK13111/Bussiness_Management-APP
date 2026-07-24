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


def round2(value):
    """Round to 2 decimal places, tolerant of None."""
    return round((value or 0) + 1e-9, 2)


def compute_purchase_item_totals(qty, buy_price, margin_pct=0, discount_pct=0,
                                  cgst_pct=0, sgst_pct=0, igst_pct=0, sell_price=None):
    """
    Mirrors the formula used when saving a purchase bill (routes/purchases.py)
    and the live preview in static/Scripts/modules/purchases/entry.js.

    - effective_buy: buy price after discount
    - sell_unit: derived from margin, unless an explicit sell_price is given
    - gst on the sell side
    """
    qty = qty or 0
    buy_price = buy_price or 0
    margin_pct = margin_pct or 0
    discount_pct = discount_pct or 0

    effective_buy = buy_price * (1 - discount_pct / 100)
    buy_total = round2(effective_buy * qty)

    if sell_price is not None:
        sell_unit = sell_price
    else:
        sell_unit = effective_buy * (1 + margin_pct / 100)

    sell_total = round2(sell_unit * qty)
    profit = round2(sell_total - buy_total)

    gst_pct = (cgst_pct or 0) + (sgst_pct or 0) + (igst_pct or 0)
    gst_total = round2(sell_total * gst_pct / 100)

    return {
        "effectiveBuy": round2(effective_buy),
        "sellUnit": round2(sell_unit),
        "buyTotal": buy_total,
        "sellTotal": sell_total,
        "profit": profit,
        "gstTotal": gst_total,
        "totalWithGST": round2(sell_total + gst_total),
    }


def compute_sale_item_totals(qty, buy_price, sell_price, discount_pct=0):
    """
    Mirrors the formula used when saving a sale bill (routes/sales.py) and
    the live preview in static/Scripts/ui/discount.js.
    """
    qty = qty or 0
    buy_price = buy_price or 0
    sell_price = sell_price or 0
    discount_pct = discount_pct or 0

    effective_sell = sell_price * (1 - discount_pct / 100)
    sell_total = round2(effective_sell * qty)
    buy_total = round2(buy_price * qty)
    profit = round2(sell_total - buy_total)

    return {
        "effectiveSell": round2(effective_sell),
        "sellTotal": sell_total,
        "buyTotal": buy_total,
        "profit": profit,
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
