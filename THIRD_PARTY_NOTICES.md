# Third-party notices

The MIT license covers original ModelPrune code. Dependencies retain their own licenses and are downloaded during installation rather than vendored into this source distribution.

- EvalScope 1.14.1: Apache-2.0 — https://github.com/modelscope/evalscope
- ComfyUI (pinned commit in `runtime-versions.json`): GPL-3.0 — https://github.com/comfyanonymous/ComfyUI. Installed in a separate runtime tree with its upstream license; custom nodes are disabled.
- PyTorch and NVIDIA runtime packages: retain their upstream BSD/NVIDIA and component licenses. The exact working Linux CUDA snapshot is in `requirements/comfyui.lock`.
- faster-whisper: MIT — https://github.com/SYSTRAN/faster-whisper
- Whisper tiny.en: downloaded separately from the pinned Systran model revision; retain its model card and upstream terms.
- uv: MIT/Apache-2.0 — https://github.com/astral-sh/uv
- Piper is used only to create the bundled release recordings, not installed as an application runtime dependency. Its engine has its own license. The release recordings use `en_US-ljspeech-high`; its model card identifies the LJ Speech source dataset as public domain: https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/high/MODEL_CARD

Only LJSpeech-based audio fixtures are included, with transcripts, SHA-256 hashes and independent verification in `fixtures/audio-manifest.json`. Personal benchmark reports, control tokens, cached models and virtual environments are excluded. Preview screenshots use fictional models and synthetic illustrative scores; they are not benchmark claims.

Public benchmark datasets are downloaded on first evaluation and retain their dataset-specific licenses. No Ollama, SDXL or other large generative model weights are bundled or downloaded by the installer. Users provide the models they want to evaluate.
