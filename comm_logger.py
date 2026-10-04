import threading
import os
import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / 'logs'
PDF_DIR = LOG_DIR / 'pdf'
os.makedirs(PDF_DIR, exist_ok=True)

_log_entries = []
_log_lock = threading.Lock()
_socketio = None


def register_socketio(socketio):
    global _socketio
    _socketio = socketio


def append_entry(level, target, event):
    now = datetime.datetime.now()
    entry = {
        'time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'target': target,
        'event': event,
        'level': level,
    }
    with _log_lock:
        _log_entries.append(entry)
        del _log_entries[:-1000]
    if _socketio is not None:
        try:
            _socketio.emit('comm_log_entry', entry, broadcast=True)
        except Exception:
            pass
    return entry


def record_test_event(target, event, level='正常'):
    return append_entry(level, target or '系统', str(event))


def get_entries():
    with _log_lock:
        return list(_log_entries)


def get_log_title():
    with _log_lock:
        if not _log_entries:
            return '通讯日志记录'
        last = _log_entries[-1]
        return f"通讯日志记录 - {last['target']} {last['event']}"


def get_alerts(limit=5):
    with _log_lock:
        entries = list(_log_entries)

    alerts = []
    seen = set()
    for entry in reversed(entries):
        if entry['level'] == '正常':
            continue
        summary = f"{entry['target']} {entry['event']}"
        if summary in seen:
            continue
        seen.add(summary)
        severity = 'critical' if entry['level'] in ('严重', 'Critical', 'ERROR', 'FAIL', 'fail') else 'warning'
        alerts.append({
            'summary': summary,
            'status': severity,
            'level': entry['level'],
            'time': entry['time'],
        })
        if len(alerts) >= limit:
            break
    return alerts


def _pdf_hex(text):
    return text.encode('utf-16-be').hex().upper()


def _wrap_text(text, width):
    text = str(text or '')
    return [text[index:index + width] for index in range(0, len(text), width)] or ['']


def _write_simple_pdf(filepath, title, entries):
    lines = [
        title,
        f"导出时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for entry in entries:
        header = f"{entry['time']} | {entry['target']} | {entry['level']}"
        lines.append(header)
        lines.extend(_wrap_text(entry['event'], 44))
        lines.append("")

    page_line_capacity = 32
    pages = [lines[i:i + page_line_capacity] for i in range(0, len(lines), page_line_capacity)] or [[]]
    objects = []
    page_ids = []

    font_obj = (
        "<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H "
        "/DescendantFonts [<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>] >>"
    )
    objects.append(font_obj)
    font_id = len(objects)

    for page_lines in pages:
        content_lines = ["BT", "/F1 14 Tf", "18 TL", "50 780 Td"]
        for index, line in enumerate(page_lines):
            if index:
                content_lines.append("T*")
            content_lines.append(f"<{_pdf_hex(line)}> Tj")
        content_lines.append("ET")
        content_stream = "\n".join(content_lines).encode('ascii')
        stream_obj = (
            f"<< /Length {len(content_stream)} >>\nstream\n".encode('ascii') +
            content_stream +
            b"\nendstream"
        )
        objects.append(stream_obj)
        content_id = len(objects)

        page_obj = (
            f"<< /Type /Page /Parent PAGES_REF /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects.append(page_obj)
        page_ids.append(len(objects))

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    pages_obj = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>"
    objects.append(pages_obj)
    pages_id = len(objects)

    resolved_objects = []
    for obj in objects:
        if isinstance(obj, bytes):
            resolved_objects.append(obj)
        else:
            resolved_objects.append(obj.replace("PAGES_REF", f"{pages_id} 0 R").encode('utf-8'))

    catalog_obj = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode('ascii')
    resolved_objects.append(catalog_obj)
    catalog_id = len(resolved_objects)

    pdf = bytearray(b"%PDF-1.4\n%\xB5\xED\xAE\xFB\n")
    offsets = [0]
    for index, obj in enumerate(resolved_objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode('ascii'))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode('ascii'))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode('ascii'))
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode('ascii')
    )

    with open(filepath, 'wb') as stream:
        stream.write(pdf)


def build_pdf(title, entries):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'comm_log_{ts}.pdf'
    filepath = os.path.join(PDF_DIR, filename)
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.units import inch

        c = Canvas(filepath, pagesize=letter)
        width, height = letter
        x = inch
        y = height - inch
        c.setFont('Helvetica-Bold', 16)
        c.drawString(x, y, title)
        y -= 0.5 * inch
        c.setFont('Helvetica', 10)
        c.drawString(x, y, f'导出时间：{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        y -= 0.4 * inch
        c.setFont('Helvetica-Bold', 11)
        c.drawString(x, y, '时间')
        c.drawString(x + 1.8 * inch, y, '模块')
        c.drawString(x + 3.8 * inch, y, '事件')
        c.drawString(x + 6.8 * inch, y, '级别')
        y -= 0.25 * inch
        c.setFont('Helvetica', 10)
        line_height = 0.24 * inch
        for entry in entries:
            if y < inch:
                c.showPage()
                y = height - inch
                c.setFont('Helvetica', 10)
            c.drawString(x, y, entry['time'])
            c.drawString(x + 1.8 * inch, y, entry['target'])
            event_text = entry['event']
            max_width = 3.8 * inch
            words = event_text.split(' ')
            line = ''
            col = x + 3.8 * inch
            for word in words:
                test_line = f"{line} {word}".strip()
                if c.stringWidth(test_line, 'Helvetica', 10) < max_width:
                    line = test_line
                else:
                    c.drawString(col, y, line)
                    y -= line_height
                    if y < inch:
                        c.showPage()
                        y = height - inch
                        c.setFont('Helvetica', 10)
                    line = word
            c.drawString(col, y, line)
            c.drawString(x + 6.8 * inch, y, entry['level'])
            y -= line_height
        c.save()
    except Exception:
        _write_simple_pdf(filepath, title, entries)
    return filepath
