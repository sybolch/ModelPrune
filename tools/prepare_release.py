#!/usr/bin/env python3
"""Validate a release tag and extract its changelog notes without network access."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')


def prepare(tag, root=ROOT):
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError('Use a version tag such as v1.0.0 or v1.1.0-rc.1')
    prerelease = match.group(4)
    if prerelease and any(part.isdigit() and len(part) > 1 and part.startswith('0') for part in prerelease.split('.')):
        raise ValueError('Numeric prerelease identifiers cannot have leading zeroes')
    version = json.loads((root / 'runtime-versions.json').read_text())['package_version']
    if tag != 'v' + version:
        raise ValueError(f'Tag {tag} does not match package version {version}')
    changelog = (root / 'CHANGELOG.md').read_text()
    headings = list(re.finditer(r'^##[ \t]+([^\s]+)[^\n]*$', changelog, re.MULTILINE))
    matching = [i for i, heading in enumerate(headings) if heading.group(1) == version]
    if len(matching) != 1:
        raise ValueError('Changelog must have exactly one section for ' + version)
    index = matching[0]
    start = headings[index].end()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
    notes = changelog[start:end].strip()
    if not notes:
        raise ValueError('Release changelog section is empty')
    notes += '\n\n## Installation\n\nCheck out this tag and run `./install.sh --open`. See `QUICKSTART.md` in the tagged source for requirements and options.\n'
    return notes, bool(prerelease)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--notes-file', type=Path, required=True)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    try:
        notes, prerelease = prepare(args.tag)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    args.notes_file.write_text(notes)
    if args.github_output:
        with args.github_output.open('a') as output:
            output.write('prerelease=' + str(prerelease).lower() + '\n')
    print('Release metadata and changelog validated')


if __name__ == '__main__':
    main()
