#!/usr/bin/env python3
"""Check publication essentials without inference, downloads or installed runtimes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    required = ['README.md', 'QUICKSTART.md', 'AGENTS.md', 'LICENSE', 'CHANGELOG.md',
                'THIRD_PARTY_NOTICES.md', 'install.sh', 'install.py', 'runtime-versions.json',
                '.github/workflows/checks.yml', '.github/workflows/release.yml', 'tools/prepare_release.py', 'docs/architecture.md', 'docs/development.md',
                'docs/benchmarking.md', 'docs/previews.md', 'docs/preview.html',
                'docs/images/report-overview.png', 'docs/images/model-comparison.png']
    for name in required:
        assert (root / name).is_file(), 'Missing ' + name
    assert (root / 'install.sh').stat().st_mode & 0o111, 'install.sh must be executable'
    assert 'MIT License' in (root / 'LICENSE').read_text(), 'Missing MIT license'
    version = json.loads((root / 'runtime-versions.json').read_text())['package_version']
    assert re.search(r"VERSION = ['\"]" + re.escape(version) + r"['\"]", (root / 'modelprune.py').read_text()), 'Application version mismatch'
    assert '## ' + version in (root / 'CHANGELOG.md').read_text(), 'Changelog version mismatch'
    manifest = json.loads((root / 'fixtures/audio-manifest.json').read_text())
    assert manifest['voice'] == 'Piper en_US-ljspeech-high', 'Unexpected public audio provenance'
    checks = manifest['verification']['results']
    assert len(checks) == len(manifest['clips']) and all(row['matched'] for row in checks), 'Audio is not independently verified'
    for clip in manifest['clips']:
        assert hashlib.sha256((root / 'fixtures' / clip['file']).read_bytes()).hexdigest() == clip['sha256'], 'Audio checksum mismatch'
    for lock in ['evalscope', 'speech', 'comfyui']:
        lines = [line for line in (root / 'requirements' / (lock + '.lock')).read_text().splitlines() if line and not line.startswith('#')]
        assert lines and all(re.fullmatch(r'[A-Za-z0-9_.-]+==[^\s]+', line) for line in lines), 'Dependencies must be exact pins'
    for doc in [root / 'README.md', root / 'QUICKSTART.md', root / 'AGENTS.md', *sorted((root / 'docs').glob('*.md'))]:
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', doc.read_text()):
            target = target.split('#')[0]
            if target and '://' not in target:
                assert (doc.parent / target).exists(), f'Broken documentation link: {doc.name}: {target}'
    preview = (root / 'docs/preview.html').read_text()
    assert 'Fictional models and synthetic scores. Not benchmark results.' in preview
    assert "setInterval(poll" not in preview, 'Preview must not poll a control service'
    payload = json.loads(re.search(r'id="run-config" type="application/json">(.*?)</script>', preview).group(1))
    assert not payload['token'] and not payload['url'], 'Preview contains service credentials'
    for image in (root / 'docs/images').glob('*.png'):
        assert image.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), 'Invalid screenshot'
    if (root / '.git').exists():
        tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
        forbidden = {'runs', 'outputs', 'venvs', '.venv', 'runtimes', 'models', 'nltk_data', '__pycache__'}
        for name in filter(None, tracked):
            path = Path(name)
            assert not forbidden.intersection(path.parts) and path.name not in {'.report-server.json', '.env'}, 'Private artifact tracked: ' + name
    return version


if __name__ == '__main__':
    try:
        version = check()
    except (AssertionError, KeyError, OSError, ValueError) as error:
        raise SystemExit('Repository check failed: ' + str(error))
    print('Repository checks passed')
