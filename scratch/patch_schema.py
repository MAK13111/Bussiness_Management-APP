import sys

path = r'C:\Projects\Management_system\APP_REDESIGNED\core\schema.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# -----------------------------------------------------------------------
# Fix 1: Change ON CONFLICT DO NOTHING -> accumulate remaining+sold
# -----------------------------------------------------------------------
needle1 = (
    '                INSERT INTO old_data (item_code, buy_mrp, sell_mrp, remaining, sold)\n'
    '                VALUES %s\n'
    '                ON CONFLICT (item_code) DO NOTHING\n'
    '                '
)
replacement1 = (
    '                INSERT INTO old_data (item_code, buy_mrp, sell_mrp, remaining, sold)\n'
    '                VALUES %s\n'
    '                ON CONFLICT (item_code) DO UPDATE SET\n'
    '                    remaining = old_data.remaining + EXCLUDED.remaining,\n'
    '                    sold      = old_data.sold      + EXCLUDED.sold\n'
    '                '
)

found1 = needle1 in content
if not found1:
    needle1 = needle1.replace('\n', '\r\n')
    replacement1 = replacement1.replace('\n', '\r\n')
    found1 = needle1 in content

if found1:
    content = content.replace(needle1, replacement1, 1)
    print('Fix 1 applied OK')
else:
    print('Fix 1: needle NOT found - manual inspection needed')
    sys.exit(1)

# -----------------------------------------------------------------------
# Fix 2: Replace log line + add _post_old_stock_opening_entry() call
# -----------------------------------------------------------------------
needle2_lf = (
    "        # Mark as imported\n"
    "        conn.execute(\n"
    '            "UPDATE app_state SET old_data_imported = TRUE WHERE id = 1"\n'
    "        )\n"
    "        conn.commit()\n"
    '        print(f"[old_data] Import complete: {inserted} rows inserted, {skipped} skipped.")\n'
)
replacement2 = (
    "        # Mark as imported\n"
    "        conn.execute(\n"
    '            "UPDATE app_state SET old_data_imported = TRUE WHERE id = 1"\n'
    "        )\n"
    "        conn.commit()\n"
    "\n"
    "        # Accurate log: report ACTUAL distinct codes + totals in the table\n"
    "        stats = conn.execute(\n"
    '            "SELECT COUNT(*) AS distinct_codes, "\n'
    '            "COALESCE(SUM(remaining),0) AS total_remaining, "\n'
    '            "COALESCE(SUM(sold),0) AS total_sold "\n'
    '            "FROM old_data"\n'
    "        ).fetchone()\n"
    '        distinct_codes  = stats["distinct_codes"]  if stats else "?"\n'
    '        total_remaining = stats["total_remaining"] if stats else "?"\n'
    '        total_sold      = stats["total_sold"]      if stats else "?"\n'
    "        print(\n"
    '            f"[old_data] Import complete: {distinct_codes} distinct items, "\n'
    '            f"total remaining={total_remaining}, total sold={total_sold}, "\n'
    '            f"{skipped} rows skipped (blank item_code). "\n'
    '            f"({inserted} xlsx rows processed)"\n'
    "        )\n"
    "\n"
    "        # One-time Opening Stock journal entry (Bug B fix part 1):\n"
    "        # Posts AFTER commit so old_data rows are visible for the SUM query.\n"
    "        _post_old_stock_opening_entry(conn)\n"
)

found2 = needle2_lf in content
if not found2:
    needle2_crlf = needle2_lf.replace('\n', '\r\n')
    found2 = needle2_crlf in content
    if found2:
        content = content.replace(needle2_crlf, replacement2, 1)
    else:
        print('Fix 2: needle NOT found')
        sys.exit(1)
else:
    content = content.replace(needle2_lf, replacement2, 1)
print('Fix 2 applied OK')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('schema.py written successfully')
