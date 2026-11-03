# Install and run ModelPrune

Target: **Linux x86_64**. Python 3 (bootstrap), internet access, and Ollama running with installed models are required. The full image profile additionally needs `git`, a compatible NVIDIA driver/CUDA-capable GPU, disk space for several GB of runtime packages, and your existing image checkpoints.

Once the repository has been published, clone it as below. For a local checkout, enter its directory and run `./install.sh --open` directly.

```bash
git clone https://github.com/sybolch/ModelPrune.git
cd ModelPrune
./install.sh --open
```

The installer fetches uv 0.13.6 if needed, verifies its wheel hash, automatically obtains the exact Python versions, and creates isolated **EvalScope, speech and ComfyUI venvs** using the checked-in full dependency snapshots. It also downloads pinned Whisper tiny.en grading weights and NLTK tokenizer data, creates a private local-service configuration, initializes a usable report, and enables a user service. No system Python packages or Ollama model weights are changed.

Installation defaults to `~/.local/share/modelprune`. Then:

```bash
~/.local/share/modelprune/modelprune doctor
~/.local/share/modelprune/modelprune open
```

In the report use **Rerun discovery**, **Benchmark new models**, or **Run benchmark**. No benchmark runs during installation. Remote Ollama registrations participate when you start a benchmark. Stop other applications' local inference during an isolated benchmark.

## Image weights and optional profiles

The pinned ComfyUI runtime is installed automatically, but image model weights are not downloaded. Point it at an existing ComfyUI models folder:

```bash
./install.sh --model-path ~/ai/ComfyUI/models --open
```

To reuse a source checkout at the exact pinned revision while still creating a dedicated pinned dependency venv:

```bash
./install.sh --comfyui ~/ai/ComfyUI --model-path ~/ai/ComfyUI/models
```

For machines without the image runtime:

```bash
./install.sh --no-images --open
```

This installs EvalScope plus CPU speech grading. Image weights can still be discovered, but cannot be evaluated until an image runtime is configured. Exact pins reproduce the observed working runtime, including ComfyUI's existing dependency-metadata mismatch; they are a snapshot, not a newly resolved compatibility recommendation. Image evaluation is limited to the tested ComfyUI workflow.

## Installation controls

```bash
./install.sh --prefix "$HOME/Apps/ModelPrune" --port 8792 --service-name modelprune-second
./install.sh --no-images --no-service
```

An existing service pointing at another installation is not overwritten. With `--no-service`, start it yourself:

```bash
~/.local/share/modelprune/modelprune serve
```

The initialized report is under `~/.local/share/modelprune/outputs/ModelPrune-report.html`. Installation can be repeated with the same prefix; existing reports, private token and benchmark history are retained. The service is loopback-only and authenticated. To stop automatic startup: `systemctl --user disable --now modelprune-report.service`.

## Reproducibility and publication

`runtime-versions.json` records Python versions, EvalScope version, ComfyUI commit, Whisper revision and platform. `requirements/*.lock` pins every package from the three environments used during development. Model weights, the GPU driver and public benchmark dataset downloads remain external. This is an online installer, not an offline wheel bundle.

The repository contains source, tests, fixtures, documentation, preview screenshots, licenses, installer and dependency snapshots. Personal reports, logs, machine-specific configuration, service tokens, venvs and model weights are excluded. Run `python3 tools/check_repository.py` before publication. Read [the benchmarking reference](docs/benchmarking.md) for scoring and limitations.

The installer auto-detects existing checkpoints under common ComfyUI locations (`~/ai/ComfyUI/models`, `~/ComfyUI/models`) or `COMFYUI_MODELS_DIR`. On systems with another installation it selects a free default port and a distinct default service name, preserving the existing service. Explicitly supplied service names are checked for conflicts.
