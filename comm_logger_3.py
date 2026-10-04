import threading
import os
import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import inch

LOG_DIR = os.path.join(os.getcwd(), 'logs')
PDF_DIR = os.path.join(LOG_DIR, 'pdf')
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


def build_pdf(title, entries):
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'comm_log_{ts}.pdf'
    filepath = os.path.join(PDF_DIR, filename)
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
    return filepath
