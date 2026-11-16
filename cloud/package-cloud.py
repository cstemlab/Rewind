"""Build a source-only Cloud Shell bundle without caches, recordings or secrets."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import zipfile

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', default='rewind-cloud-deploy.zip')
args = parser.parse_args()
if not re.fullmatch(r'rewind-cloud-deploy(?:-r[0-9]+)?\.zip', args.output):
    parser.error('Use a versioned rewind-cloud-deploy-rN.zip filename.')
output = root.parent / args.output
if output.exists():
    parser.error('Output already exists. Choose a new revision; prior bundles are preserved.')
top = {'Dockerfile', '.dockerignore', '.gcloudignore', 'requirements.txt', 'cloudbuild.yaml',
       'prepare-cloud.sh', 'build-and-deploy.sh', 'deploy.ps1', 'provision-secret.py',
       'DEPLOY.md', 'API.md', 'verify.py', 'package-cloud.py', 'remote-smoke.py'}
blocked_names = {'direct_url.json', 'RECORD', 'INSTALLER', 'REQUESTED'}
files = []
for path in sorted(root.rglob('*')):
    if not path.is_file():
        continue
    rel = path.relative_to(root)
    if '__pycache__' in rel.parts or path.suffix == '.pyc' or path.name in blocked_names:
        continue
    if 'vendor' in rel.parts and ('bin' in rel.parts or 'Scripts' in rel.parts):
        continue
    include = len(rel.parts) == 1 and rel.name in top
    include |= rel.parts[0] == 'tests' and path.suffix == '.py'
    include |= rel.parts[0] == 'service' and (path.suffix == '.py' or 'vendor' in rel.parts)
    if include and path.name not in ('google_smoke_test.py', 'google_live_smoke_test.py'):
        files.append((path, rel))
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path, rel in files:
        archive.write(path, Path('rewind-cloud') / rel)
manifest = {'file': output.name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'bytes': output.stat().st_size, 'file_count': len(files)}
(root / (output.stem + '-manifest.json')).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print(json.dumps(manifest, indent=2))
