import csv
import datetime
import json
import threading
from pathlib import Path


_lock = threading.Lock()
_latest = None
BASE_DIR = Path(__file__).resolve().parent / "logs" / "benchmarks"


def save_benchmark(result):
    global _latest
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    json_path = BASE_DIR / f"controller_benchmark_{timestamp}.json"
    csv_path = BASE_DIR / f"controller_benchmark_{timestamp}.csv"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    samples = result.get("samples") or []
    if samples:
        fieldnames = sorted({key for sample in samples for key in sample})
        with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(samples)
    result = dict(result)
    result["json_file"] = str(json_path)
    result["csv_file"] = str(csv_path) if samples else None
    with _lock:
        _latest = result
    return result


def get_latest():
    with _lock:
        return dict(_latest) if _latest else None
