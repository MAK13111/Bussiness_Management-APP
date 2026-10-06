# =========================================================================
# core/barcode_pdf.py
# Offline A4 barcode sheet (PDF) using ReportLab. Default: 4 x 12 = 48 labels
# per page. Barcodes are Code128, same as the on-screen JsBarcode ones.
# =========================================================================

import io

from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _txt(value):
    """Built-in PDF fonts only cover Latin-1, so swap the rupee sign and
    replace anything else unsupported instead of printing garbage."""
    s = "" if value is None else str(value)
    s = s.replace("\u20b9", "Rs.")
    return s.encode("latin-1", "replace").decode("latin-1")


def _price(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    return f"Rs.{v:,.0f}" if abs(v - round(v)) < 0.005 else f"Rs.{v:,.2f}"


def _fit(text, font, size, max_w, c):
    """Trim text with '..' so it fits max_w points."""
    text = _txt(text)
    if c.stringWidth(text, font, size) <= max_w:
        return text
    while text and c.stringWidth(text + "..", font, size) > max_w:
        text = text[:-1]
    return text + ".."


def build_barcode_pdf(labels, cols=4, rows=12, label_w=None, label_h=None,
                      margin_left=None, margin_top=None, gap_x=0.0, gap_y=0.0,
                      border=True, show_name=True, show_size=True, show_price=True):
    """labels: list of {code, name, size, price}. Sizes are in millimetres.
    If label_w/label_h are not given they are worked out so the grid fills A4
    with a 5mm side and 8.5mm top/bottom margin. If margins are not given the
    grid is centred on the page."""
    page_w, page_h = A4
    cols, rows = int(cols), int(rows)
    gap_x, gap_y = float(gap_x) * mm, float(gap_y) * mm

    if label_w is None:
        lw = (page_w - 2 * 5 * mm - gap_x * (cols - 1)) / cols
    else:
        lw = float(label_w) * mm
    if label_h is None:
        lh = (page_h - 2 * 8.5 * mm - gap_y * (rows - 1)) / rows
    else:
        lh = float(label_h) * mm

    grid_w = cols * lw + (cols - 1) * gap_x
    grid_h = rows * lh + (rows - 1) * gap_y
    ml = (page_w - grid_w) / 2 if margin_left is None else float(margin_left) * mm
    mt = (page_h - grid_h) / 2 if margin_top is None else float(margin_top) * mm

    per_page = cols * rows
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Barcodes")

    pad = 1.5 * mm
    for i, lab in enumerate(labels):
        pos = i % per_page
        if i and pos == 0:
            c.showPage()
        r, col = divmod(pos, cols)
        x = ml + col * (lw + gap_x)
        y = page_h - mt - (r + 1) * lh - r * gap_y  # bottom-left of this label

        if border:
            c.setLineWidth(0.3)
            c.setStrokeGray(0.7)
            c.rect(x, y, lw, lh)

        code = _txt(lab.get("code"))
        if not code:
            continue

        # Text lines at the top, barcode in the middle, number at the bottom.
        top = y + lh - pad
        fs_name = min(7.5, lh / mm * 0.3)
        fs_small = min(6.5, lh / mm * 0.27)
        fs_code = min(7.0, lh / mm * 0.28)
        c.setFillGray(0)

        if show_name and lab.get("name"):
            top -= fs_name
            c.setFont(FONT_BOLD, fs_name)
            c.drawCentredString(x + lw / 2, top, _fit(lab["name"], FONT_BOLD, fs_name, lw - 2 * pad, c))
            top -= 1
        info = []
        if show_size and lab.get("size"):
            info.append("Size: " + _txt(lab["size"]))
        if show_price and _price(lab.get("price")):
            info.append(_price(lab.get("price")))
        if info:
            top -= fs_small
            c.setFont(FONT, fs_small)
            c.drawCentredString(x + lw / 2, top, _fit("   ".join(info), FONT, fs_small, lw - 2 * pad, c))
            top -= 1

        bottom = y + pad + fs_code + 1
        bar_h = top - bottom - 1
        if bar_h < 4 * mm:
            bar_h = 4 * mm

        # Pick the bar width so the barcode plus a 10-module blank margin on
        # each side (the Code128 "quiet zone" scanners need) fits in the label.
        probe = code128.Code128(code, barWidth=1, barHeight=bar_h, quiet=False)
        modules = probe.width  # width in modules, since barWidth=1
        bw = min((lw - 2 * pad) / (modules + 20), 0.5 * mm)
        bc = code128.Code128(code, barWidth=bw, barHeight=bar_h, quiet=False)
        bc.drawOn(c, x + (lw - bc.width) / 2, bottom)

        c.setFont("Courier", fs_code)
        c.drawCentredString(x + lw / 2, y + pad, code)

    c.save()
    return buf.getvalue()