# Working on ModelPrune

## Project and commands

ModelPrune discovers installed models, orchestrates isolated EvalScope evaluations and renders a self-contained HTML report. The saved-run schema/protocol version is independent; do not renumber historical data merely to match the product version.

Run from the repository root:

```bash
python3 -m unittest discover -q
python3 tools/check_repository.py
python3 tools/make_preview.py
```

Unit tests and demo generation use only the standard library and do not need Ollama, GPU inference or dependency installation. Preview screenshots can be regenerated with `node tools/capture_previews.mjs` using Node.js 22+ and Chromium; these are optional documentation tools, not application dependencies.

## Structure

- `modelprune.py`: CLI, capability-aware aggregation and overlap recommendations.
- `discovery.py`, `model_aliases.py`: read-only discovery and weight identity.
- `evalscope_run.py`, `evalscope_native.py`, `evalscope_bridge.py`: evaluation orchestration, registered datasets/metrics, guarded standard-suite transport.
- `isolation.py`: checks around local inference.
- `skill_tasks.py`, `fixtures/`: multilevel fixtures and verified audio.
- `report_ui.py`, `report_insights.py`, `report_control.py`, `report_server.py`: report, charts and authenticated loopback controls.
- `install.py`, `launcher.py`, `requirements/`, `runtime-versions.json`: installation and exact environment snapshots.
- `docs/`, `tools/`: documentation, synthetic preview and publication checks.

## Behavioral requirements

1. EvalScope owns production task scores. Preserve raw evidence and errors; never convert missing, truncated or failed evaluations into successes.
2. Keep advertised skills distinct from demonstrated quality. A replacement needs strictly higher overall rating and all target skills with complete coverage. Preserve context/remote tradeoff tags.
3. Group aliases by weight identity and compatible metadata, never by name suffix alone. Keep removed/changed models out of current comparisons without deleting history.
4. Preserve sequential evaluation, unload/check behavior and explicit isolation failures. Do not stop unrelated applications or run costly/remote benchmarks as part of routine tests.
5. Discovery is read-only; do not load arbitrary discovered model code or unpickle weights.
6. Escape model-provided strings in HTML and script payloads. Keep report controls authenticated and bound to loopback; accept only fixed actions.
7. Preserve public fixture provenance and hashes. Audio changes need intelligibility checks and independent transcript verification. Treat fixture/rubric changes as incompatible for incremental scoring.
8. Preserve exact dependency pins unless deliberately updating and verifying a runtime. Keep image GPU requirements and known metadata mismatches documented.

## Verification and publication

Use focused unit tests plus the full suite for scoring, discovery, installation or report changes. Verify rendered previews when changing the report UI. New tests should exercise behavior, not duplicate implementation.

Keep `modelprune.VERSION`, `runtime-versions.json` and the changelog consistent. Use ModelPrune as the project name; reserve version numbers for release metadata, tags and explicit version output. Update the changelog for user-visible changes.

Never commit private reports, run logs, `.report-server.json`, tokens, venvs, downloaded runtimes or model weights. Preview data must stay synthetic and clearly labelled. Run `tools/check_repository.py` before preparing a commit. Keep original code MIT-licensed and document third-party provenance.
