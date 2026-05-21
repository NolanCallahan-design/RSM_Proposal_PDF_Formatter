"""
Western Aircraft — Proposal Formatter
Streamlit web app wrapping the v15 formatting logic.

Install and run:
    pip install streamlit pymupdf pypdf
    streamlit run proposal_formatter_app.py
"""

import io
import re
import tempfile
from pathlib import Path
from datetime import datetime

import streamlit as st
import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    NameObject, BooleanObject, NumberObject,
    ArrayObject, DictionaryObject, TextStringObject,
    FloatObject, IndirectObject, RectangleObject, StreamObject,
)

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Proposal Formatter — Western Aircraft",
    page_icon="✈️",
    layout="centered",
)

# ─────────────────────────────────────────────
# STYLING
# ─────────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Page background */
.stApp {
    background: #f7f8fa;
}

/* Header strip */
.wa-header {
    background: #1a2744;
    color: white;
    padding: 28px 36px 24px 36px;
    border-radius: 12px;
    margin-bottom: 28px;
    display: flex;
    align-items: center;
    gap: 16px;
}
.wa-header h1 {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.3px;
    color: white;
}
.wa-header p {
    margin: 4px 0 0 0;
    font-size: 13px;
    color: #8fa3c8;
    font-weight: 400;
}
.wa-badge {
    background: #2e4a8a;
    color: #a8c4ff;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 20px;
    display: inline-block;
    margin-top: 8px;
}

/* Cards */
.wa-card {
    background: white;
    border: 1px solid #e4e8f0;
    border-radius: 10px;
    padding: 24px;
    margin-bottom: 16px;
}
.wa-card h3 {
    margin: 0 0 6px 0;
    font-size: 14px;
    font-weight: 600;
    color: #1a2744;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.wa-card p {
    margin: 0;
    font-size: 13px;
    color: #6b7a99;
    line-height: 1.6;
}

/* Status items */
.status-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid #f0f2f7;
    font-size: 13px;
    font-family: 'DM Mono', monospace;
    color: #3d4f7a;
}
.status-row:last-child { border-bottom: none; }
.status-icon { min-width: 18px; }

/* Metric boxes */
.metric-row {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
}
.metric-box {
    flex: 1;
    background: white;
    border: 1px solid #e4e8f0;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}
.metric-box .value {
    font-size: 28px;
    font-weight: 600;
    color: #1a2744;
    line-height: 1;
    font-family: 'DM Mono', monospace;
}
.metric-box .label {
    font-size: 11px;
    color: #8fa3c8;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
}

/* Success banner */
.success-banner {
    background: #edfaf3;
    border: 1px solid #6ddea8;
    border-radius: 8px;
    padding: 16px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    color: #1a6640;
    font-size: 14px;
    font-weight: 500;
    margin-bottom: 16px;
}

/* Warning banner */
.warn-banner {
    background: #fff8ec;
    border: 1px solid #f5c842;
    border-radius: 8px;
    padding: 14px 18px;
    color: #7a5800;
    font-size: 13px;
    margin-bottom: 12px;
}

/* Upload zone override */
[data-testid="stFileUploader"] {
    border: 2px dashed #c5cfe8 !important;
    border-radius: 10px !important;
    background: #fafbfd !important;
}

/* Download button */
.stDownloadButton > button {
    background: #1a2744 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    padding: 10px 24px !important;
    width: 100% !important;
}
.stDownloadButton > button:hover {
    background: #2e4a8a !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

CHECKBOX_Y_OFFSET = -1
RADIO_FLAG = NumberObject(1 << 15)

# ─────────────────────────────────────────────
# CORE LOGIC (v15)
# ─────────────────────────────────────────────

def find_placeholder_squares(page):
    squares = []
    for draw in page.get_drawings():
        rect = draw.get("rect")
        if rect is None:
            continue
        w, h = rect.width, rect.height
        if 8 <= w <= 20 and 8 <= h <= 20 and abs(w - h) <= 4:
            squares.append(rect)
    return squares


def find_nearest_square(squares, label_rect, max_dist=60):
    best, best_dist = None, max_dist
    for sq in squares:
        if abs(sq.y0 - label_rect.y0) > 8:
            continue
        if sq.x0 >= label_rect.x0:
            continue
        dist = label_rect.x0 - sq.x1
        if dist < best_dist:
            best_dist = dist
            best = sq
    return best


def detect_line_items(doc):
    line_items = []
    seen_ids = set()
    row_counters = {}
    pattern = re.compile(r'\b(\d{1,2}\.\d{1,2})\b')

    for page_num in range(len(doc)):
        page = doc[page_num]
        if "Accept" not in page.get_text():
            continue

        accept_rects = page.search_for("Accept")
        decline_rects = page.search_for("Decline")
        squares = find_placeholder_squares(page)

        for accept_rect in accept_rects:
            decline_rect = None
            for d in decline_rects:
                if abs(d.y0 - accept_rect.y0) < 5:
                    decline_rect = d
                    break
            if decline_rect is None:
                continue

            search_area = fitz.Rect(0, max(0, accept_rect.y0 - 300), 150, accept_rect.y0 - 2)
            text_in_area = page.get_text("text", clip=search_area)
            matches = list(pattern.finditer(text_in_area))

            if matches:
                item_id = matches[-1].group(1)
                safe_name = item_id.replace(".", "_")
            else:
                row_counters.setdefault(page_num, 0)
                row_counters[page_num] += 1
                item_id = f"pg{page_num + 1}_{row_counters[page_num]}"
                safe_name = item_id

            key = (page_num, item_id)
            if key in seen_ids:
                continue
            seen_ids.add(key)

            line_items.append({
                "id":             item_id,
                "safe_name":      safe_name,
                "page":           page_num,
                "accept_rect":    accept_rect,
                "decline_rect":   decline_rect,
                "accept_square":  find_nearest_square(squares, accept_rect),
                "decline_square": find_nearest_square(squares, decline_rect),
                "numerical":      bool(matches),
            })

    line_items.sort(key=lambda x: (x["page"], x["accept_rect"].y0))
    return line_items


def pymupdf_rect_to_pdf(rect, page_height, y_offset=0):
    return [rect.x0, page_height - rect.y1 - y_offset,
            rect.x1, page_height - rect.y0 - y_offset]


def fallback_accept_rect(r):
    return fitz.Rect(r.x0 - 26, r.y0, r.x0 - 14, r.y0 + 12)


def fallback_decline_rect(r):
    return fitz.Rect(r.x0 - 26, r.y0, r.x0 - 14, r.y0 + 12)


def _make_appearance_stream(writer, on_state, size=12):
    if on_state:
        cx = cy = size / 2
        r = size / 3
        k = 0.5523 * r
        content = (
            f"q\n0 0 0 rg\n"
            f"{cx+r} {cy} m\n"
            f"{cx+r} {cy+k} {cx+k} {cy+r} {cx} {cy+r} c\n"
            f"{cx-k} {cy+r} {cx-r} {cy+k} {cx-r} {cy} c\n"
            f"{cx-r} {cy-k} {cx-k} {cy-r} {cx} {cy-r} c\n"
            f"{cx+k} {cy-r} {cx+r} {cy-k} {cx+r} {cy} c\n"
            f"f\nQ"
        ).encode()
    else:
        content = b""
    stream = StreamObject()
    stream[NameObject("/Type")]      = NameObject("/XObject")
    stream[NameObject("/Subtype")]   = NameObject("/Form")
    stream[NameObject("/FormType")]  = NumberObject(1)
    stream[NameObject("/BBox")]      = ArrayObject([
        FloatObject(0), FloatObject(0), FloatObject(size), FloatObject(size)
    ])
    stream[NameObject("/Resources")] = DictionaryObject()
    stream._data = content
    return writer._add_object(stream)


def _ensure_acroform(writer):
    root = writer._root_object
    if "/AcroForm" not in root:
        af = DictionaryObject({NameObject("/Fields"): ArrayObject()})
        root[NameObject("/AcroForm")] = writer._add_object(af)
    af = root["/AcroForm"]
    if isinstance(af, IndirectObject):
        af = af.get_object()
    if "/Fields" not in af:
        af[NameObject("/Fields")] = ArrayObject()
    return af


def add_radio_group(writer, page, group_name, options):
    parent = DictionaryObject({
        NameObject("/FT"): NameObject("/Btn"),
        NameObject("/Ff"): RADIO_FLAG,
        NameObject("/T"):  TextStringObject(group_name),
        NameObject("/V"):  NameObject("/Off"),
        NameObject("/DV"): NameObject("/Off"),
    })
    parent_ref = writer._add_object(parent)
    kids = ArrayObject()

    for opt in options:
        export = opt["export_value"]
        rect   = opt["rect"]
        size   = min(rect[2] - rect[0], rect[3] - rect[1])
        on_xobj  = _make_appearance_stream(writer, True, size=size)
        off_xobj = _make_appearance_stream(writer, False, size=size)
        appearance = DictionaryObject({
            NameObject("/N"): DictionaryObject({
                NameObject(f"/{export}"): on_xobj,
                NameObject("/Off"):       off_xobj,
            }),
        })
        widget = DictionaryObject({
            NameObject("/Type"):    NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"):      NameObject("/Btn"),
            NameObject("/Ff"):      RADIO_FLAG,
            NameObject("/Rect"):    RectangleObject(rect),
            NameObject("/Parent"):  parent_ref,
            NameObject("/AS"):      NameObject("/Off"),
            NameObject("/AP"):      appearance,
            NameObject("/F"):       NumberObject(4),
            NameObject("/BS"):      DictionaryObject({
                NameObject("/W"): NumberObject(1),
                NameObject("/S"): NameObject("/S"),
            }),
            NameObject("/MK"):      DictionaryObject({
                NameObject("/BC"): ArrayObject([FloatObject(0.2), FloatObject(0.4), FloatObject(0.7)]),
                NameObject("/BG"): ArrayObject([FloatObject(0.95), FloatObject(0.97), FloatObject(1.0)]),
                NameObject("/CA"): TextStringObject("l"),
            }),
        })
        widget_ref = writer._add_object(widget)
        kids.append(widget_ref)
        if "/Annots" in page:
            page["/Annots"].append(widget_ref)
        else:
            page[NameObject("/Annots")] = ArrayObject([widget_ref])

    parent[NameObject("/Kids")] = kids
    af = _ensure_acroform(writer)
    af["/Fields"].append(parent_ref)
    return parent_ref


def add_text_field(page, rect, field_name):
    widget = fitz.Widget()
    widget.field_type    = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_name    = field_name
    widget.rect          = fitz.Rect(rect)
    widget.border_color  = (0.2, 0.4, 0.7)
    widget.fill_color    = (0.95, 0.97, 1.0)
    widget.border_width  = 1
    widget.text_fontsize = 9
    try:
        page.add_widget(widget)
    except Exception:
        pass


def add_signature_field(page, rect, field_name):
    widget = fitz.Widget()
    widget.field_type   = fitz.PDF_WIDGET_TYPE_SIGNATURE
    widget.field_name   = field_name
    widget.rect         = fitz.Rect(rect)
    widget.border_color = (0.1, 0.5, 0.1)
    widget.fill_color   = (0.93, 1.0, 0.93)
    widget.border_width = 1.5
    try:
        page.add_widget(widget)
    except Exception:
        pass


def find_page_containing(doc, search_text):
    for i in range(len(doc)):
        if search_text.lower() in doc[i].get_text().lower():
            return i
    return None


def find_on_right_side(page, label):
    mid = page.rect.width / 2
    instances = page.search_for(label)
    right = [r for r in instances if r.x0 > mid]
    return right[0] if right else None


def find_signature_line_y(page, tc_rect):
    mid = page.rect.width / 2
    candidates = []
    for draw in page.get_drawings():
        for item in draw.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) > 2:
                continue
            if p1.y < tc_rect.y1:
                continue
            if p1.x < mid and p2.x < mid:
                continue
            if abs(p2.x - p1.x) < 80:
                continue
            candidates.append(p1.y)
    return sorted(candidates)[0] if candidates else None


def add_signature_block(page, log):
    pw = page.rect.width
    fw = 195

    tc = find_on_right_side(page, "Terms and Conditions:")
    by = find_on_right_side(page, "By:")
    ti = find_on_right_side(page, "Title:")
    dt = find_on_right_side(page, "Date:")

    if tc:
        sig_y = find_signature_line_y(page, tc)
        top = (sig_y - 22) if sig_y else tc.y1 + 10
        add_signature_field(page, [tc.x0, top, pw - 40, top + 26], "CustomerSignature")
        log.append(("✅", "Signature field placed"))
    else:
        log.append(("⚠️", "'Terms and Conditions:' not found"))

    def fr(r):
        x0 = r.x1 + 5
        return [x0, r.y0 - 2, min(x0 + fw, pw - 40), r.y1 + 2]

    if by:
        add_text_field(page, fr(by), "CustomerName")
        log.append(("✅", "By: field added"))
    if ti:
        add_text_field(page, fr(ti), "CustomerTitle")
        log.append(("✅", "Title: field added"))
    if dt:
        add_text_field(page, fr(dt), "CustomerDate")
        log.append(("✅", "Date: field added"))


def process_pdf_bytes(pdf_bytes: bytes) -> tuple[bytes, dict]:
    """
    Core processing function. Takes raw PDF bytes, returns
    (formatted_pdf_bytes, stats_dict).
    """
    log = []
    stats = {"total_pages": 0, "line_items": 0, "numbered": 0,
             "non_numbered": 0, "acceptance_page": None}

    # Pass 1 — PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    stats["total_pages"] = len(doc)
    log.append(("📄", f"{len(doc)} pages loaded"))

    line_items = detect_line_items(doc)
    if not line_items:
        doc.close()
        raise ValueError("No Accept/Decline line items found in this PDF.")

    numbered     = [i for i in line_items if i["numerical"]]
    non_numbered = [i for i in line_items if not i["numerical"]]
    stats["line_items"]    = len(line_items)
    stats["numbered"]      = len(numbered)
    stats["non_numbered"]  = len(non_numbered)
    log.append(("✅", f"{len(line_items)} line items detected ({len(numbered)} numbered, {len(non_numbered)} non-numbered)"))

    page_heights = {i: doc[i].rect.height for i in range(len(doc))}

    acc_page_num = find_page_containing(doc, "XII. Acceptance")
    if acc_page_num is None:
        acc_page_num = len(doc) - 1
    stats["acceptance_page"] = acc_page_num + 1
    log.append(("📝", f"Acceptance page: {acc_page_num + 1}"))
    add_signature_block(doc[acc_page_num], log)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        intermediate_path = tmp.name
    doc.save(intermediate_path, deflate=True)
    doc.close()

    # Pass 2 — pypdf radio injection
    try:
        reader = PdfReader(intermediate_path)
        writer = PdfWriter(clone_from=reader)

        for item in line_items:
            page_obj = writer.pages[item["page"]]
            ph = page_heights[item["page"]]
            a_rect = item["accept_square"]  or fallback_accept_rect(item["accept_rect"])
            d_rect = item["decline_square"] or fallback_decline_rect(item["decline_rect"])
            a_pdf  = pymupdf_rect_to_pdf(a_rect, ph, CHECKBOX_Y_OFFSET)
            d_pdf  = pymupdf_rect_to_pdf(d_rect, ph, CHECKBOX_Y_OFFSET)
            add_radio_group(
                writer, page_obj,
                f"Choice_{item['safe_name']}",
                [{"export_value": "Accept", "rect": a_pdf},
                 {"export_value": "Decline", "rect": d_pdf}],
            )

        af = _ensure_acroform(writer)
        af[NameObject("/NeedAppearances")] = BooleanObject(True)

        out_buf = io.BytesIO()
        writer.write(out_buf)
        out_buf.seek(0)
        result_bytes = out_buf.read()
    finally:
        Path(intermediate_path).unlink(missing_ok=True)

    log.append(("✅", f"Radio buttons injected for all {len(line_items)} rows"))
    log.append(("✅", f"Output ready ({len(result_bytes) / 1024:.1f} KB)"))

    return result_bytes, {"log": log, **stats}


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────

# Header
st.markdown("""
<div class="wa-header">
    <div>
        <h1>✈️ &nbsp;Proposal Formatter</h1>
        <p>Western Aircraft — MRO Sales Operations</p>
        <span class="wa-badge">v15 · PyMuPDF + pypdf</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Instructions card
st.markdown("""
<div class="wa-card">
    <h3>How it works</h3>
    <p>Upload a Corridor-generated proposal PDF. The formatter scans every Accept/Decline row and injects interactive radio buttons — one mutually exclusive pair per line item. The formatted PDF is ready to send via DocuSign.</p>
</div>
""", unsafe_allow_html=True)

# Upload
uploaded_file = st.file_uploader(
    "Drop a proposal PDF here",
    type=["pdf"],
    label_visibility="collapsed",
)

if uploaded_file is not None:
    st.markdown(f"""
    <div class="warn-banner">
        📎 &nbsp;<strong>{uploaded_file.name}</strong> &nbsp;·&nbsp; {uploaded_file.size / 1024:.1f} KB
    </div>
    """, unsafe_allow_html=True)

    if st.button("Format Proposal", type="primary", use_container_width=True):
        with st.spinner("Processing…"):
            try:
                pdf_bytes = uploaded_file.read()
                result_bytes, stats = process_pdf_bytes(pdf_bytes)

                # Store in session state so download persists
                st.session_state["result_bytes"] = result_bytes
                st.session_state["result_name"]  = f"FORMATTED_{uploaded_file.name}"
                st.session_state["stats"]        = stats

            except Exception as e:
                st.error(f"Processing failed: {e}")
                st.session_state.pop("result_bytes", None)

# Results
if "result_bytes" in st.session_state:
    stats = st.session_state["stats"]

    st.markdown(f"""
    <div class="success-banner">
        ✅ &nbsp; Formatting complete — {stats['line_items']} line items processed
    </div>
    """, unsafe_allow_html=True)

    # Metrics
    st.markdown(f"""
    <div class="metric-row">
        <div class="metric-box">
            <div class="value">{stats['total_pages']}</div>
            <div class="label">Pages</div>
        </div>
        <div class="metric-box">
            <div class="value">{stats['line_items']}</div>
            <div class="label">Line Items</div>
        </div>
        <div class="metric-box">
            <div class="value">{stats['numbered']}</div>
            <div class="label">Numbered</div>
        </div>
        <div class="metric-box">
            <div class="value">{stats['non_numbered']}</div>
            <div class="label">Non-numbered</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Log
    with st.expander("Processing log", expanded=False):
        log_html = '<div class="wa-card" style="margin:0">'
        for icon, msg in stats["log"]:
            log_html += f'<div class="status-row"><span class="status-icon">{icon}</span><span>{msg}</span></div>'
        log_html += '</div>'
        st.markdown(log_html, unsafe_allow_html=True)

    # Download
    st.download_button(
        label="⬇️  Download Formatted PDF",
        data=st.session_state["result_bytes"],
        file_name=st.session_state["result_name"],
        mime="application/pdf",
        use_container_width=True,
    )

    st.markdown("""
    <div style="font-size:12px; color:#8fa3c8; text-align:center; margin-top:12px;">
        Open the downloaded PDF in Adobe Acrobat to verify radio buttons before sending via DocuSign.
    </div>
    """, unsafe_allow_html=True)

# Footer
st.markdown("""
<div style="margin-top:48px; text-align:center; font-size:11px; color:#b0bcd4;">
    Western Aircraft · Proposal Formatter · Built by Nolan Callahan, BPA Intern
</div>
""", unsafe_allow_html=True)
