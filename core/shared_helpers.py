from decimal import Decimal, ROUND_HALF_UP


def round2(value):
    """Round a money value to 2 decimals the way a human would (half-up),
    avoiding the classic float precision drift where round(699.995, 2)
    can come out as 699.99 instead of 700.0."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_or_create_ledger(name, group_name, balance_type, conn):
    if not name:
        name = "Unknown"
    name = str(name).strip()
    group_name = str(group_name).strip()
    group = conn.execute("SELECT id FROM account_groups WHERE LOWER(name)=LOWER(?)", (group_name,)).fetchone()
    if not group:
        # Fallback aliases — prevent silent wrong-group assignment
        fallback_map = {
            "sundry": "Indirect Expenses",
            "expenses": "Indirect Expenses",
            "income": "Indirect Income",
        }
        fallback_name = fallback_map.get(group_name.lower())
        if fallback_name:
            group = conn.execute("SELECT id FROM account_groups WHERE LOWER(name)=LOWER(?)", (fallback_name,)).fetchone()
        if not group:
            raise ValueError(f"Account group '{group_name}' not found — cannot create ledger '{name}'")
    group_id = group['id']

    ledger = conn.execute("SELECT id, group_id FROM ledgers WHERE LOWER(name)=LOWER(?)", (name,)).fetchone()
    if ledger:
        if ledger['group_id'] is None and group_id:
            conn.execute("UPDATE ledgers SET group_id=? WHERE id=?", (group_id, ledger['id']))
        return ledger['id']
    cur = conn.execute("""
        INSERT INTO ledgers (name, group_id, balance_type, is_active)
        VALUES (?, ?, ?, ?)
    """, (name, group_id, balance_type, True))
    return cur.lastrowid

_CAMEL_CASE_KEYS = {
    "returnbillno": "returnBillNo",
    "buytotal": "buyTotal",
    "basecode": "baseCode",
    "originalinvoiceno": "originalInvoiceNo",
    "originaltable": "originalTable",
    "customername": "customerName",
    "customerno": "customerNo",
    "sellunit": "sellUnit",
    "selltotal": "sellTotal",
    "originalbillno": "originalBillNo",
    "originalid": "originalId",
    "replacebillno": "replaceBillNo",
    "oldtotal": "oldTotal",
    "newtotal": "newTotal",
    "openingbalance": "openingBalance",
    "currentbalance": "currentBalance",
    "accountno": "accountNo",
    "createdat": "createdAt",
    "defaultmargin": "defaultMargin",
    "defaultgst": "defaultGST",
}


def to_camel_row(row):
    """dict(row), but with the lowercase-folded column names above restored
    to the camelCase the frontend expects."""
    return {_CAMEL_CASE_KEYS.get(k, k): v for k, v in dict(row).items()}