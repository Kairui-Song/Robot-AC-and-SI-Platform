#!/usr/bin/env python3
"""Reject mixed or edited delivery sources; optionally verify installed runtime files."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installed', action='store_true')
    parser.add_argument('--record-install', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'SOURCE_MANIFEST.json').read_text())
    failures = []
    for relative, expected in manifest['sha256'].items():
        file = root / relative
        if not file.is_file() or digest(file) != expected:
            failures.append(relative)
    # Extra source modules/scripts are a version mix, not an allowed overlay.
    for file in (root / 'src').rglob('*'):
        if file.is_file() and not any(p in ('__pycache__', '.pytest_cache') or p.endswith('.egg-info')
                                      for p in file.parts):
            if file.relative_to(root).as_posix() not in manifest['sha256']:
                failures.append('unexpected source: ' + str(file.relative_to(root)))
    receipt = None
    if args.installed or args.record_install:
        from ament_index_python.packages import get_package_prefix
        for package, module in (('linglong_control', 'linglong_control_tools'), ('arm_control', 'arm_control')):
            prefix = Path(get_package_prefix(package)).resolve()
            if prefix != (root / 'install-release' / package).resolve():
                failures.append('wrong package prefix: ' + str(prefix))
            for file in (root / 'src' / package / module).glob('*.py'):
                installed = list(prefix.glob(f'lib/python*/site-packages/{module}/{file.name}'))
                if len(installed) != 1 or digest(installed[0]) != digest(file):
                    failures.append('installed module: ' + str(file))
            for folder in ('launch', 'config', 'urdf', 'rviz'):
                for file in (root / 'src' / package / folder).glob('*'):
                    if file.is_file():
                        installed = prefix / 'share' / package / folder / file.name
                        if not installed.is_file() or digest(installed) != digest(file):
                            failures.append('installed resource: ' + str(file))
        prefix = Path(get_package_prefix('linglong_control'))
        installed_library = prefix / 'lib/liblinglong_sim_system.so'
        if not installed_library.is_file():
            failures.append('installed MOCK library missing')
        else:
            # CMake rewrites ELF RPATH on install, so build/install file hashes
            # legitimately differ. Record the installed hash after a clean build.
            receipt = dict(manifest_sha256=digest(root / 'SOURCE_MANIFEST.json'),
                           library_sha256=digest(installed_library))
            if args.installed:
                saved = root / 'install-release/BUILD_RECEIPT.json'
                if not saved.is_file() or json.loads(saved.read_text()) != receipt:
                    failures.append('installation receipt missing or changed; rebuild this release')
        for file in (root / 'src/linglong_control/scripts').iterdir():
            if file.is_file():
                installed = prefix / 'lib/linglong_control' / file.name
                if not installed.is_file() or digest(installed) != digest(file):
                    failures.append('installed executable: ' + str(file))
    if failures:
        raise SystemExit('Release verification FAILED:\n' + '\n'.join(failures))
    if args.record_install:
        (root / 'install-release/BUILD_RECEIPT.json').write_text(json.dumps(receipt, indent=2))
    print('Release verified: ' + manifest['release_id'])


if __name__ == '__main__':
    main()
