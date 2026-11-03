# Development and publication

## Local checks

No evaluation runtime is required for the standard-library unit suite:

```bash
python3 -m unittest discover -q
python3 tools/make_preview.py
python3 tools/check_repository.py
```

CI runs these checks on Python 3.11 and 3.14. It does not load models, download large runtimes or call cloud inference.

The actual installation profiles are pinned in `requirements/*.lock` and `runtime-versions.json`. To test them, install into a separate prefix and use `doctor`. Use `--no-service` and an unused port to keep an existing installation intact. A unit test pass does not prove GPU, provider or full benchmark behavior.

## Documentation previews

Run `python3 tools/make_preview.py` for a deterministic, offline synthetic report, then `node tools/capture_previews.mjs` for screenshots. Node.js 22+ and Chromium are required only for screenshot generation. See [previews](previews.md).

Change the synthetic fixture generator when updating demo content. Never replace it with a personal run or real private scores.

## Before publication

1. Run tests and `tools/check_repository.py`; inspect `git status` and the staged diff.
2. Ensure the README images render and documentation links resolve.
3. Keep original code MIT-licensed, fixture provenance intact and dependency licenses separate.
4. Check the version in the application, runtime manifest and changelog.
5. Create the intended GitHub repository, add its URL as `origin`, and push `main` when publication is authorized. This prepared checkout does not require a remote to run.

Release versions belong in application/package metadata, Git tags and the changelog. Runtime outputs, tokens, model weights and venvs are ignored. Source is distributed through Git; no release ZIP builder is required.


## Release workflow

[The release workflow](../.github/workflows/release.yml) runs when a version tag (`v*`) is pushed. It checks the tag against `runtime-versions.json`, requires matching nonempty changelog notes, runs the unit suite and repository checks on Python 3.11 and 3.14, and verifies the generated preview matches the committed file.

To release:

1. Update `modelprune.VERSION` and `package_version` in `runtime-versions.json` to the new version.
2. Move the relevant `Unreleased` changelog entries into a dated version section.
3. Commit the release changes and push `main`.
4. Tag that commit and push the tag, for example:

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

Use a new tag for subsequent releases. If a local tag already exists, verify it points at the intended release commit instead of recreating it. The tagged commit must contain the release workflow.

Once both check jobs pass, the publish job creates the GitHub release from that existing tag using the built-in `GITHUB_TOKEN`. No extra secret is needed. Notes come only from that version's changelog section, plus installation instructions. Tags such as `v1.1.0-rc.1` are marked as prereleases. Reruns leave an existing release untouched.

GitHub supplies the standard source-code downloads. The workflow does not upload model weights, private reports, venvs or a custom distribution archive, and it never starts inference.
