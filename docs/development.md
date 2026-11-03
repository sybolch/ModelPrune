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
