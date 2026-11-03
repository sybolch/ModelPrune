# Benchmarking reference

Install first using [the installation guide](../QUICKSTART.md).

Installed-model discovery, **EvalScope-powered evaluation**, skill comparisons and directional overlap review. ModelPrune manages local runtimes and presents results; EvalScope runs every dataset and assigns every task score. The main tables, domain sections, overall ratings and overlap suggestions all consume that one set of scored EvalScope reviews.

## Run

Python 3.10+ for the orchestration CLI, plus a separate working EvalScope installation. Verified with EvalScope 1.14.1.

```bash
cd /path/to/ModelPrune
./modelprune.py list
./modelprune.py list --scan-path /path/to/models --output inventory.json
./modelprune.py run --models d3:2b lfm3:1.7b --standard-limit 25 --output runs/evaluation
```

The default `run` engine is EvalScope. Without `--models`, it evaluates all supported Ollama registrations, including remote models. Remote inference is labelled in the report; it uses your configured Ollama account/provider and its limits. Speech-capable models require an existing local CPU evaluator:

```bash
./modelprune.py run --standard-limit 25 \
  --asr-python /path/to/python-with-faster-whisper \
  --asr-model /path/to/local-whisper-snapshot \
  --comfyui /path/to/ComfyUI --comfy-python /path/to/ComfyUI/venv/bin/python \
  --output runs/all-skills
```

ComfyUI checkpoints are evaluated through a native EvalScope dataset/model adapter. A private loopback ComfyUI server starts with custom nodes disabled and stops before the worker exits. Standalone VAEs/adapters do not get generator scores. Omit ComfyUI arguments when no image runtime is configured; its discovered weights remain explicitly unbenchmarked. No model weights are downloaded, deleted or unpickled by discovery.

`--evalscope-python` chooses the interpreter containing EvalScope. `--context`, `--tokens` and `--thinking-tokens` configure the native local transport (defaults 4096, 256, 2048). Standard generation uses 1024 output tokens, temperature 0, zero-shot prompts, seed 42, and reasoning disabled where advertised; dedicated thinking fixtures enable it. One repeat is currently supported by the unified importer. Standard dataset limits apply **per subset**, not to the entire combined run.

```bash
# Checkpoint resume: completed jobs are retained; an incomplete job restarts
./modelprune.py run --resume runs/all-skills/run.json
# Regenerate the report from saved EvalScope evidence
./modelprune.py report runs/all-skills/run.json
```

Resume verifies EvalScope version and Ollama model digests. Interrupted job directories are archived before rerunning; completed jobs are skipped. Legacy runs cannot be resumed into the new engine. They can still be rendered as historical reports.

## Evaluation architecture

| Coverage | EvalScope dataset / adapter |
| --- | --- |
| Reading comprehension | Built-in BoolQ, shared by text and native decision models |
| Multi-step arithmetic | Built-in GSM8K, zero-shot |
| Instruction following | Built-in IFEval, prompt-level strict score |
| Local completion / decisions | Registered `modelprune_core` dataset, native Ollama chat/System One transports |
| Coding | Registered `modelprune_coding`: three tracing and three Python/SQL debugging fixtures |
| Vision | Registered `modelprune_vision`: real image color, counting and spatial tasks |
| Listening | Registered `modelprune_audio`: neural spoken recordings and structured extraction |
| Speech output | Registered `modelprune_speech`: generated WAVs, graded by local CPU Whisper transcripts |
| Tools | Registered `modelprune_tools`: function names/arguments; calls never executed |
| Thinking | Registered `modelprune_thinking`: correct final answers and nonempty thinking required |
| Image generation | Registered `modelprune_image_generation`: ComfyUI generation and color/layout metrics |

The local fixtures are **custom EvalScope datasets**, not published standard benchmarks. Their transport returns unscored evidence; EvalScope's scoring stage assigns accuracy. The report imports those reviews rather than regrading answers. Built-in suites use their own EvalScope grading and primary metric semantics. Raw configurations, predictions, reviews and framework reports remain available under each job folder.

First use may download public dataset/tokenizer resources. IFEval requires `langdetect` and `nltk` in the EvalScope environment. No external judge is used. Remote registrations use their configured cloud inference through Ollama when included. Generated programs are never executed: coding fixtures test tracing/debugging; HumanEval/MBPP code-execution benchmarks would require a configured sandbox.

## Ratings and overlap

Generative and decision models have separate compact tables: model, parameters, context, skill icons, task success, speed and overall rating. Coding is a measured skill for completion models. Domain sections show coding, vision, image generation and separate listening/speech comparisons, with image/audio previews.

Task scores come exclusively from EvalScope. Standard samples have weight 1; local difficulty levels have weights 1–3. Per-skill quality is difficulty-weighted success. Overall = (80% mean skill quality + 20% relative speed) × skill coverage. Unknown or incomplete skills block overlap recommendations. Speed compares models with identical skill sets and execution location (local/remote) and includes loading; standard timings additionally include isolation-proxy checks. Results are specific to the scheduled workloads and settings.

**A better model can replace a worse one only if it has all of the worse model's skills.** Replacement requires strictly higher overall rating and complete tested skill coverage; fewer skills or lower/equal rating cannot replace a model. A reduced advertised context is flagged as a tradeoff. A local-to-remote replacement is flagged as a remote execution tradeoff rather than an unconditional removal suggestion, since offline execution would be lost. Nothing is deleted.

A full engine migration does not imply exhaustive testing. Small standard subsets and custom fixtures do not establish general capability or definitive removal advice. Image grading checks coarse colors/background/layout, not shape accuracy or artistic quality. Speech uses transcript matching with punctuation/case/common number-spelling normalization, not naturalness; ASR can make mistakes. Thinking traces are present/absent checks, not independently verified reasoning. Shared fixed prompts do not establish generalization.

## Isolation and discovery

Before each model/job all loaded Ollama models stop. Native EvalScope skill transports check `/api/ps` before and after every task. Built-in suites use a temporary loopback proxy that enforces the expected model/endpoint, serializes requests and verifies isolation before delivering responses. Streaming is disabled. Speech generators unload before CPU ASR. The image worker runs after the Ollama jobs and owns its server. Other applications are not continuously monitored: avoid unrelated GPU workloads.

Discovery scans accessible configured Ollama, Hugging Face, AI Lab, ComfyUI, LM Studio, Jan, GPT4All and standalone weight locations. Shards/snapshots are grouped; complete shared weight sets are deduplicated. Config-only caches are excluded. `--scan-path` adds roots; `--scan-limit` bounds traversal (default 5,000,000 entries). Permission/truncation warnings are retained. External weights without runtime adapters remain visible and unscored. Disk sizes are logical, context is advertised rather than measured, and MoE metadata describes total parameters plus expert counts.

## Development

```bash
python3 -m unittest -q
```

`evalscope_native.py` defines native datasets/metrics and unscored transports; `evalscope_worker.py` runs them inside EvalScope; `evalscope_run.py` orchestrates jobs and imports scored reviews. `evalscope_bridge.py` supplies the guarded standard endpoint and schema-v2 report reader. The former pilot command remains available for diagnostics; the normal `run` and report use one unified score system.

## Report insights and radar charts

The self-contained report includes an interactive SVG radar with individual model visibility toggles and no model-count limit. Choose generative/decision models and skill/benchmark axes. Show all/hide all buttons act on the selected group; individual choices persist when switching groups, and each model keeps its color. Every axis uses a fixed 0–100% quality scale; only higher-is-better ratio metrics are eligible. Shared axes are the default. Unmeasured or incomplete skills stay missing, and disabling shared axes shows gaps rather than zero scores or a filled profile. Radar area is not an overall rating. Exact values remain in an accessible table; decision models default to benchmark axes because their skill profiles may have fewer than three dimensions.

Expandable EvalScope breakdowns show primary metric names, sample counts, completion status and indicative 95% Wilson intervals for standard binary accuracy samples. Fixed small subsets do not establish population-level confidence, and local diagnostic fixtures receive no such intervals. Confidence losses (NLL/Brier/ECE/AURC) have their own lower-is-better table. Performance summaries show recorded P50/P95 latency and runtime/output-limit errors; unavailable TTFT is not inferred. Task evidence can be filtered by model/task/category and outcome.

Charts use embedded data and local SVG/JavaScript with no CDN or network dependencies. Regenerate these report features from a saved run; inference does not need to run again.

## Run from the report

The report's **Run benchmark** button talks to an authenticated loopback-only local service. While a run is active the button is replaced by a progress bar with scored sample/suite counts and the current model. Discovery shows indeterminate progress until the job plan exists. Reloading the page reconnects to an active run. Successful completion publishes fresh HTML/CSV/inventory/raw results then reloads the page. Failures preserve the previous report and restore the button with an error message. Duplicate starts are rejected.

The installer enables `modelprune-report.service` as a user service that starts at login (unless `--no-service` is selected). Inspect it with `systemctl --user status modelprune-report.service`. Its private `.report-server.json` configuration fixes the run options and publish directory; the page cannot submit arbitrary commands or options. Current settings benchmark all supported installed registrations (including remote models) with the saved standard sample limit and speech/ComfyUI adapters. Clicking Run actually starts inference and may use your remote provider allowance.

For another installation create a private service configuration containing a random token (at least 32 characters), `port`, `publish_dir`, and applicable run options, then run `python3 report_server.py --config /path/to/config.json`. The report and local control token should remain private. No service is exposed on a network interface; other website origins and unauthenticated calls are rejected.

**Rerun discovery** refreshes installed-model metadata without inference or unloading models. It shows indeterminate scanning progress, republishes the inventory/report, and preserves existing benchmark results and their evaluation dates. Discovery and benchmarking share a single operation lock so neither can overwrite the other's publication. The inventory refresh timestamp is displayed separately from benchmark dates.

**Benchmark new models** evaluates only currently installed, supported Ollama registrations that lack saved scores or have changed weights/capabilities, plus new ComfyUI checkpoints when configured. Existing per-task results and evidence are retained; scores for a changed model are replaced by its fresh run and prior results remain in history. The operation reuses the saved benchmark settings and refuses to mix incompatible EvalScope/fixture versions. Relative speed ratings and replacement suggestions can change when the comparison group changes. With nothing new it returns without inference. Its progress covers only the incremental work.

After discovery, all visible comparisons, radars, details and replacement suggestions are restricted to models present in the current inventory with matching weight digests. Removed/replaced models remain in saved history rather than in the active report. New aliases are unbenchmarked until explicitly evaluated; scores are not silently copied from their base model.

Ollama registrations with matching weight-blob identities, architecture, capabilities, quantization and adapters are grouped as aliases. Parent links select the canonical registration when available; names alone never establish identity. Parameter/context presets such as `*-work` remain visible under their base model rather than receiving separate rows or partial-benchmark jobs. Runtime defaults can differ between aliases. Explicit alias selections resolve to the canonical registration, and existing canonical scores are preferred when multiple variants were previously benchmarked. Different weights or adapters remain separate models.
