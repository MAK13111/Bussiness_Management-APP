# =========================================================================
# core/thermal_printer.py
# ESC/POS receipt printing to a USB thermal printer (python-escpos).
# =========================================================================

import textwrap

# NOTE: escpos / pyusb are imported lazily inside the functions that need them,
# so the app still starts (and the Settings tab still saves) even if the
# libraries are not installed yet.

# Printable characters per line (Font A) for each paper width.
CHARS_PER_LINE = {58: 32, 80: 48}


def _txt(value):
    """Thermal printers use a single-byte code page. Keep output plain ASCII
    so a stray symbol (for example the rupee sign) never prints as garbage."""
    s = "" if value is None else str(value)
    s = s.replace("\u20b9", "Rs.")
    return s.encode("ascii", "replace").decode("ascii")


def _money(value):
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _lr(left, right, width):
    """Left text and right text on one line, padded in between."""
    left, right = _txt(left), _txt(right)
    room = max(1, width - len(right) - 1)
    left = left[:room]
    return left + " " * (width - len(left) - len(right)) + right


def _render(p, data, shop, width, cut):
    """Write the receipt to any python-escpos printer object (real or Dummy)."""
    shop = shop or {}
    header = data.get("header") or {}
    items = data.get("items") or []
    line = "-" * width
    dashed = "=" * width

    # ---- Shop block -------------------------------------------------------
    p.set(align="center", bold=True, double_height=True, double_width=False)
    if shop.get("shop_name"):
        for part in textwrap.wrap(_txt(shop["shop_name"]).upper(), width) or [""]:
            p.text(part + "\n")
    p.set(align="center", bold=False, double_height=False, double_width=False)
    for key, prefix in (("address", ""), ("phone", "Phone: "), ("gst_no", "GSTIN: ")):
        if shop.get(key):
            for part in textwrap.wrap(prefix + _txt(shop[key]), width):
                p.text(part + "\n")

    p.text(line + "\n")
    p.set(align="center", bold=True)
    p.text("SALE RECEIPT\n")
    p.set(align="left", bold=False)
    p.text(line + "\n")

    # ---- Bill details -----------------------------------------------------
    customer = str(header.get("customer_name") or "").strip()
    if not customer or customer.lower() == "null":
        customer = "Cash"
    p.text(_lr("Bill No: " + str(header.get("bill_no") or data.get("saleId") or ""),
               "Date: " + str(header.get("date") or ""), width) + "\n")
    if data.get("time"):
        p.text("Time: " + _txt(data["time"]) + "\n")
    p.text("Customer: " + _txt(customer) + "\n")
    if header.get("customer_no"):
        p.text("Mobile: " + _txt(header["customer_no"]) + "\n")
    if header.get("payment_mode"):
        p.text("Payment: " + _txt(header["payment_mode"]) + "\n")
    if header.get("payment_mode") == "Split":
        p.text(_lr("Cash: " + _money(header.get("cash_amount")),
                   "Online: " + _money(header.get("online_amount")), width) + "\n")
    p.text(line + "\n")

    # ---- Items ------------------------------------------------------------
    # Each item: name on its own line(s), then "qty x rate ........ amount".
    # This layout fits both 58mm and 80mm paper without column math.
    p.set(bold=True)
    p.text(_lr("Item", "Amount", width) + "\n")
    p.set(bold=False)
    p.text(line + "\n")
    for idx, it in enumerate(items, 1):
        name = f"{idx}. {it.get('item') or '-'}"
        if it.get("size"):
            name += f" ({it['size']})"
        for part in textwrap.wrap(_txt(name), width) or [""]:
            p.text(part + "\n")
        qty = it.get("qty") or 1
        p.text(_lr(f"   {qty} x {_money(it.get('rate'))}", _money(it.get("amount")), width) + "\n")
    p.text(line + "\n")

    # ---- Totals -----------------------------------------------------------
    p.text(_lr("Sub Total", _money(data.get("subTotal")), width) + "\n")
    if float(data.get("discount") or 0) > 0:
        p.text(_lr(f"Discount ({data.get('discount')}%)", _money(data.get("discountAmt")), width) + "\n")
    p.set(bold=True, double_height=True)
    p.text(_lr("Amount Paid", _money(data.get("amountPaid")), width) + "\n")
    p.set(bold=False, double_height=False)
    if data.get("amountInWords"):
        p.text(dashed + "\n")
        for part in textwrap.wrap(_txt(data["amountInWords"]), width):
            p.text(part + "\n")
    p.text(dashed + "\n")

    # ---- Footer -----------------------------------------------------------
    p.set(align="center", bold=True)
    for part in textwrap.wrap(_txt(shop.get("footer_note") or "Thank You! Visit Again!!"), width):
        p.text(part + "\n")
    p.set(align="left", bold=False)
    p.text("\n\n\n")
    if cut:
        p.cut()


def build_receipt_bytes(data, shop, paper_width_mm=80, cut=True):
    """Render the receipt into raw ESC/POS bytes without touching hardware.
    Useful for tests and previews."""
    from escpos.printer import Dummy
    width = CHARS_PER_LINE.get(int(paper_width_mm), 48)
    d = Dummy()
    d.hw("INIT")
    _render(d, data, shop, width, cut)
    return d.output


def _usb_args():
    # libusb-package ships the libusb DLL for Windows so no manual install.
    try:
        import libusb_package
        return {"backend": libusb_package.get_libusb1_backend()}
    except Exception:
        return {}


def _find_out_endpoint(device):
    """Look up the bulk OUT endpoint instead of guessing 0x01."""
    import usb.util
    try:
        cfg = device.get_active_configuration()
        for intf in cfg:
            ep = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
            )
            if ep is not None:
                return ep.bEndpointAddress
    except Exception:
        pass
    return None


def _open_usb(vendor_id, product_id):
    from escpos.printer import Usb
    p = Usb(vendor_id, product_id, usb_args=_usb_args(), timeout=5000)
    p.open()
    ep = _find_out_endpoint(p.device)
    if ep:
        p.out_ep = ep
    return p


def parse_hex_id(value):
    """Accepts '0416', '0x0416' or 'VID_0416' style text and returns an int."""
    s = str(value or "").strip().lower()
    for junk in ("vid_", "pid_", "0x"):
        s = s.replace(junk, "")
    if not s:
        raise ValueError("ID is empty")
    return int(s, 16)


def print_receipt(vendor_id, product_id, data, shop, paper_width_mm=80, cut=True):
    p = _open_usb(vendor_id, product_id)
    try:
        _render(p, data, shop, CHARS_PER_LINE.get(int(paper_width_mm), 48), cut)
    finally:
        p.close()


def print_test_page(vendor_id, product_id, paper_width_mm=80, cut=True):
    width = CHARS_PER_LINE.get(int(paper_width_mm), 48)
    p = _open_usb(vendor_id, product_id)
    try:
        p.set(align="center", bold=True, double_height=True)
        p.text("PRINTER TEST\n")
        p.set(align="center", bold=False, double_height=False)
        p.text("-" * width + "\n")
        p.text("Thermal printer is connected.\n")
        p.text(f"Paper: {int(paper_width_mm)}mm ({width} chars)\n")
        p.text("\n\n\n")
        if cut:
            p.cut()
    finally:
        p.close()