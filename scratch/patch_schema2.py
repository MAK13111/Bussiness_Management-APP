import sys

schema_path = r'C:\Projects\Management_system\APP_REDESIGNED\core\schema.py'
with open(schema_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Insert _post_old_stock_opening_entry before populate_defaults
needle = "def populate_defaults():"
helper_func = '''
def _post_old_stock_opening_entry(conn):
    """Post a one-time JOURNAL voucher that establishes the cost basis of the
    imported old stock in the double-entry accounting system.

    Debit  "Old Stock-in-Hand"       = SUM(remaining * buy_mrp) across old_data
    Credit "Opening Balance Equity"  = same amount

    This is guarded by the app_state flag old_stock_opening_posted so it
    runs at most once even if the function is somehow called twice.
    """
    # ── idempotency guard ────────────────────────────────────────────────────
    flag_row = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='app_state' AND column_name='old_stock_opening_posted'"
    ).fetchone()
    if not flag_row:
        conn.execute(
            "ALTER TABLE app_state ADD COLUMN IF NOT EXISTS "
            "old_stock_opening_posted BOOLEAN DEFAULT FALSE"
        )
        conn.commit()

    already = conn.execute(
        "SELECT COALESCE(old_stock_opening_posted, FALSE) AS done FROM app_state WHERE id = 1"
    ).fetchone()
    if already and already["done"]:
        print("[old_data] Opening Stock journal already posted – skipping.")
        return

    # ── compute total opening stock value ────────────────────────────────────
    total_row = conn.execute(
        "SELECT COALESCE(SUM(remaining * buy_mrp), 0) AS opening_value FROM old_data"
    ).fetchone()
    opening_value = float(total_row["opening_value"]) if total_row else 0.0

    if opening_value <= 0:
        print("[old_data] Opening stock value is zero – skipping journal entry.")
        conn.execute(
            "UPDATE app_state SET old_stock_opening_posted = TRUE WHERE id = 1"
        )
        conn.commit()
        return

    # ── create / look up ledgers ──────────────────────────────────────────────
    from core.shared_helpers import get_or_create_ledger
    from core.accounting import VoucherEngine
    from datetime import datetime

    old_stock_ledger_id = get_or_create_ledger(
        "Old Stock-in-Hand", "Current Assets", "Debit", conn
    )
    equity_ledger_id = get_or_create_ledger(
        "Opening Balance Equity", "Capital Account", "Credit", conn
    )

    # ── post the journal voucher ──────────────────────────────────────────────
    today = datetime.now().strftime("%Y-%m-%d")
    VoucherEngine.create_voucher({
        "voucher_type": "JOURNAL",
        "date": today,
        "reference": "OLD-STOCK-OPENING",
        "narration": (
            f"Opening Stock-in-Hand for legacy inventory imported from old_purchase_data.xlsx "
            f"(value = {opening_value:.2f})"
        ),
        "created_by": "admin",
        "entries": [
            {"ledger_id": old_stock_ledger_id, "debit": opening_value, "credit": 0},
            {"ledger_id": equity_ledger_id,    "debit": 0, "credit": opening_value},
        ]
    }, conn=conn)

    conn.execute(
        "UPDATE app_state SET old_stock_opening_posted = TRUE WHERE id = 1"
    )
    conn.commit()
    print(
        f"[old_data] Opening Stock journal posted: "
        f"Debit 'Old Stock-in-Hand' {opening_value:.2f} / "
        f"Credit 'Opening Balance Equity' {opening_value:.2f}"
    )


'''

if needle in content:
    content = content.replace(needle, helper_func + needle, 1)
    print("_post_old_stock_opening_entry inserted OK")
else:
    print("populate_defaults not found – appending to end of file")
    content += helper_func

with open(schema_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("schema.py written")
