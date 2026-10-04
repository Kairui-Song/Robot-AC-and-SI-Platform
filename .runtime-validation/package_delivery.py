"""Stage a clean source-only release; never modify a user's existing VM workspace."""
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
source = root / 'ros2_ws'
release_id = (source / 'src/linglong_control/RELEASE_ID').read_text().strip()
base = root / 'delivery' / release_id
target = base / 'ros2_ws'
target.mkdir(parents=True, exist_ok=True)
for folder in ('src', 'tools'):
    for file in (source / folder).rglob('*'):
        if not file.is_file() or any(p in ('__pycache__', '.pytest_cache') or p.endswith('.egg-info')
                                    for p in file.parts) or file.suffix in ('.pyc', '.bak'):
            continue
        relative = file.relative_to(source)
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dest)
for file in source.glob('*.md'):
    shutil.copy2(file, target / file.name)
skill = root / '.cursor/skills/linglong-control-reliability/SKILL.md'
dest = base / '.cursor/skills/linglong-control-reliability/SKILL.md'
dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(skill, dest)
files = sorted(p for p in target.rglob('*') if p.is_file() and p.name != 'SOURCE_MANIFEST.json'
               and not any(part.startswith(('build-', 'install-', 'log-')) or part in ('verification', '__pycache__', '.pytest_cache')
                           for part in p.relative_to(target).parts))
manifest = dict(release_id=release_id, sha256={p.relative_to(target).as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
(target / 'SOURCE_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
zip_path = root / (release_id + '.zip')
with ZipFile(zip_path, 'w', ZIP_DEFLATED) as z:
    for file in [*files, target / 'SOURCE_MANIFEST.json', dest]:
        z.write(file, file.relative_to(base.parent).as_posix())
print(zip_path)
print('sha256=' + hashlib.sha256(zip_path.read_bytes()).hexdigest())
