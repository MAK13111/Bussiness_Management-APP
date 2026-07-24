def get_or_create_ledger(name, group_name, balance_type, conn):
    if not name:
        name = "Unknown"
    ledger = conn.execute("SELECT id FROM ledgers WHERE name=?", (name,)).fetchone()
    if ledger:
        return ledger['id']
    group = conn.execute("SELECT id FROM account_groups WHERE name=?", (group_name,)).fetchone()
    if not group:
        group = conn.execute("SELECT id FROM account_groups WHERE name='Sundry Creditors'").fetchone()
    group_id = group['id'] if group else None
    cur = conn.execute("""
        INSERT INTO ledgers (name, group_id, balance_type, is_active)
        VALUES (?, ?, ?, ?)
    """, (name, group_id, balance_type, 1))
    # No commit here — this runs inside the caller's transaction (get_conn()
    # commits once at the end). Committing early meant that if a later step
    # in the same request failed, this insert would already be permanent
    # instead of rolling back with the rest of the transaction.
    return cur.lastrowid