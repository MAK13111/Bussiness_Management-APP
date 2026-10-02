import sys

path = r'C:\Projects\Management_system\APP_REDESIGNED\routes\sales.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# The voucher-building block ends with the Sales Cr entry then calls
# VoucherEngine.create_voucher. We need to insert old_data COGS entries
# INTO the same entries list, right before the create_voucher call.
# The pivot text we'll insert BEFORE is the "if len(entries) > 1:" check.
#
# We insert a new block that:
#   1. Computes the total old_data buy cost for this sale
#   2. Adds Debit Purchase + Credit Old Stock-in-Hand to entries

needle = (
    "            if sales_ledger:\n"
    '                entries.append({"ledger_id": sales_ledger["id"], "debit": 0, "credit": gross_sale})\n'
    "\n"
    "            if len(entries) > 1:\n"
)

old_data_cogs_block = (
    "            if sales_ledger:\n"
    '                entries.append({"ledger_id": sales_ledger["id"], "debit": 0, "credit": gross_sale})\n'
    "\n"
    "            # ── Old Stock-in-Hand COGS entry (Bug B fix) ─────────────────────────\n"
    "            # For every old_data line in this sale, post a cost-transfer entry in\n"
    "            # the SAME voucher so that P&L shows the purchase cost:\n"
    "#   Debit  Purchase          = qty * buy_price  (COGS expense)\n"
    "#   Credit Old Stock-in-Hand = qty * buy_price  (reduce asset)\n"
    "            old_data_buy_total = round2(sum(\n"
    '                p["buy_total"] for p in processed_items if p.get("is_old_data")\n'
    "            ))\n"
    "            if old_data_buy_total > 0:\n"
    "                purchase_ledger = conn.execute(\n"
    "                    \"SELECT id FROM ledgers WHERE LOWER(name) = 'purchase'\"\n"
    "                ).fetchone()\n"
    "                if not purchase_ledger:\n"
    "                    purchase_ledger_id = get_or_create_ledger(\n"
    '                        "Purchase", "Purchase Accounts", "Debit", conn\n'
    "                    )\n"
    "                else:\n"
    '                    purchase_ledger_id = purchase_ledger["id"]\n'
    "                old_stock_ledger_id = get_or_create_ledger(\n"
    '                    "Old Stock-in-Hand", "Current Assets", "Debit", conn\n'
    "                )\n"
    '                entries.append({"ledger_id": purchase_ledger_id, "debit": old_data_buy_total, "credit": 0})\n'
    '                entries.append({"ledger_id": old_stock_ledger_id, "debit": 0, "credit": old_data_buy_total})\n'
    "            # ─────────────────────────────────────────────────────────────────────\n"
    "\n"
    "            if len(entries) > 1:\n"
)

found = needle in content
if not found:
    needle_crlf = needle.replace('\n', '\r\n')
    found = needle_crlf in content
    if found:
        content = content.replace(needle_crlf, old_data_cogs_block, 1)
    else:
        print("NEEDLE NOT FOUND in sales.py")
        # Print surrounding area for debug
        idx = content.find('if len(entries) > 1:')
        print(repr(content[max(0,idx-200):idx+50]))
        sys.exit(1)
else:
    content = content.replace(needle, old_data_cogs_block, 1)

print("Bug B COGS entry applied OK")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("sales.py written successfully")
