"""Compare two source directories (local repo vs VM snapshot) and print a summary.
Usage: python tools/compare_vm_sources.py /path/to/vm_source /path/to/local_repo
Produces a simple file list diff and optional unified diffs for mismatched files.
"""
import sys
import os
from pathlib import Path
import filecmp
import difflib


def list_files(root):
    root = Path(root)
    files = []
    for p in root.rglob('*'):
        if any(part in {'.git', '__pycache__', '.pytest_cache', '.venv', '.venv_local', 'venv', 'node_modules', 'build', 'dist', 'logs'} for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            files.append(p.relative_to(root).as_posix())
    return set(files)


def main():
    if len(sys.argv) < 3:
        print('Usage: compare_vm_sources.py <vm_source_dir> <local_dir>')
        return 2
    vm_dir = Path(sys.argv[1])
    local_dir = Path(sys.argv[2])
    if not vm_dir.is_dir():
        print('VM source dir not found:', vm_dir)
        return 2
    if not local_dir.is_dir():
        print('Local dir not found:', local_dir)
        return 2

    vm_files = list_files(vm_dir)
    local_files = list_files(local_dir)

    only_in_vm = sorted(vm_files - local_files)
    only_in_local = sorted(local_files - vm_files)
    common = sorted(vm_files & local_files)

    print('Files only in VM:', len(only_in_vm))
    for f in only_in_vm[:50]:
        print('  ', f)
    if len(only_in_vm) > 50:
        print('  ...')

    print('\nFiles only in local:', len(only_in_local))
    for f in only_in_local[:50]:
        print('  ', f)
    if len(only_in_local) > 50:
        print('  ...')

    diffs = []
    errors = []
    for f in common:
        vm_file = vm_dir / f
        local_file = local_dir / f
        try:
            if not filecmp.cmp(vm_file, local_file, shallow=False):
                if diffs:
                    diffs.append(f)
                    continue
                with open(vm_file, 'r', encoding='utf-8', errors='ignore') as a, open(local_file, 'r', encoding='utf-8', errors='ignore') as b:
                    a_lines = a.readlines()
                    b_lines = b.readlines()
                ud = difflib.unified_diff(a_lines, b_lines, fromfile=str(vm_file), tofile=str(local_file))
                diffs.append('\n'.join(list(ud)))
        except OSError as exc:
            errors.append(f'{f}: {exc}')
    print('\nDiffering files:', len(diffs))
    if diffs:
        print('\n--- Unified diffs for first file ---')
        print(diffs[0][:2000])
    for error in errors:
        print('Comparison failed:', error)
    print('\nDone')
    return 2 if errors else (1 if diffs or only_in_vm or only_in_local else 0)

if __name__ == '__main__':
    raise SystemExit(main())
