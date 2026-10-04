"""Run via sudo; only manages a named trace instance and its evidence files."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import time


def fault_line(line):
    return any(s in line for s in (
        'MOCK fault latched',
        'Deactivating following hardware components as their read cycle resulted in an error',
        'process has died',
    ))


def watch(log, stop, seconds):
    deadline = time.monotonic() + seconds
    pending = ''
    with log.open(errors='replace') as stream:
        while True:
            chunk = stream.read(65536)
            if chunk:
                pending += chunk
                lines = pending.split('\n')
                pending = lines.pop()
                for line in lines:
                    if fault_line(line):
                        return {'reason': 'launch_fault', 'line': line}
                if fault_line(pending):
                    return {'reason': 'launch_fault', 'line': pending}
                continue
            if stop.exists():
                return {'reason': 'test_ended_or_interrupted'}
            if time.monotonic() >= deadline:
                return {'reason': 'duration_limit'}
            time.sleep(0.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('launch', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('instance')
    args = parser.parse_args()
    out = args.output
    started = False
    signal.signal(signal.SIGTERM, lambda *_: (out / 'stop-request').touch())
    signal.signal(signal.SIGINT, lambda *_: (out / 'stop-request').touch())
    try:
        subprocess.run(['trace-cmd', 'start', '-B', args.instance, '-b', '32768',
                        '-e', 'sched:sched_switch', '-e', 'sched:sched_wakeup'], check=True)
        started = True
        (out / 'ready').touch()
        result = watch(args.launch, out / 'stop-request', 7260)
        result['detected_wall'] = time.time()
        result['detected_monotonic'] = time.monotonic()
        # Stop BEFORE reporting to the shell or extracting: preserve the ring now.
        subprocess.run(['trace-cmd', 'stop', '-B', args.instance], check=True)
        result['frozen_wall'] = time.time()
        (out / 'trigger.json').write_text(json.dumps(result, indent=2))
        with (out / 'extract.log').open('w') as stream:
            subprocess.run(['trace-cmd', 'extract', '-B', args.instance,
                            '-o', str(out / 'trace.dat')], stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        (out / 'trace.dat').chmod(0o644)
        subprocess.run(['trace-cmd', 'reset', '-B', args.instance, '-d'], check=True)
        started = False
        (out / 'capture-complete').touch()
    except BaseException as exc:
        if started:
            subprocess.run(['trace-cmd', 'stop', '-B', args.instance], check=False)
        (out / 'capture-error.txt').write_text(
            f'{type(exc).__name__}: {exc}\nInstance retained if started: {args.instance}\n')
        raise


if __name__ == '__main__':
    main()
