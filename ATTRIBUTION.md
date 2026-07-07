# ATTRIBUTION

Open-source projects used, adapted, or studied for fotorganize.
Update this file whenever code or ideas are borrowed.

## Used (installed as dependencies)

| Project | URL | License | How used |
|---|---|---|---|
| FastAPI | https://github.com/fastapi/fastapi | MIT | Web API framework |
| Uvicorn | https://github.com/encode/uvicorn | BSD-3 | ASGI server |
| Pillow | https://github.com/python-pillow/Pillow | MIT-CMU (HPND) | Image decoding, EXIF, thumbnails |
| ImageHash | https://github.com/JohannesBuchner/imagehash | BSD-2 | Perceptual hashing (phash) stored per file |
| python-dotenv | https://github.com/theskumar/python-dotenv | BSD-3 | .env config loading |
| pytest | https://github.com/pytest-dev/pytest | MIT | Tests (dev only) |
| PyTorch (cu128) | https://github.com/pytorch/pytorch | BSD-3 | Florence-2 inference on GPU |
| transformers | https://github.com/huggingface/transformers | Apache-2.0 | Loads/runs Florence-2 |
| Florence-2-base | https://huggingface.co/microsoft/Florence-2-base | MIT | Caption / object tags / OCR (weights + trust_remote_code) |
| InsightFace | https://github.com/deepinsight/insightface | MIT (code) | Face detection + ArcFace embeddings (buffalo_l) |
| buffalo_l models | (insightface model zoo) | **non-commercial** | Face models — fine for this personal, non-commercial project |
| onnxruntime-gpu | https://github.com/microsoft/onnxruntime | MIT | Runs InsightFace ONNX models |
| numpy | https://github.com/numpy/numpy | BSD-3 | Embedding math / clustering |
| timm, einops, accelerate | (HF ecosystem) | Apache-2.0/MIT | Florence-2 dependencies |

## Studied (ideas adapted, no code copied yet)

| Project | URL | License | What was studied |
|---|---|---|---|
| Immich | https://github.com/immich-app/immich | AGPL-3.0 | Job-queue-driven ML pipeline, thumbnail cache design, person/face workflow. AGPL: study ideas only — do NOT copy code into this MIT-style personal project without accepting AGPL terms. |
| digiKam | https://github.com/KDE/digikam | GPL-2.0+ | People view UX, "mark missing not delete" library behavior, XMP sidecar approach (Phase 10) |
| Lap | https://github.com/julyx10/lap | (check repo) | Local-first folder-based library UX |
| InsightFace | https://github.com/deepinsight/insightface | MIT (code; some models non-commercial) | Planned for Phase 4 face detection/embeddings. NOTE: buffalo_l model weights are for non-commercial use — fine for this personal project. |
| Florence-2 | https://huggingface.co/microsoft/Florence-2-base | MIT | Planned for Phase 3 captioning/OCR |
| Lora-Captioner | https://github.com/RevOzzy/Lora-Captioner | (check repo) | Florence-2 prompt modes for LoRA captions (Phase 3/8) |
| AutoCap | https://github.com/hoodini/autocap | (check repo) | Trigger-word caption flow (Phase 8) |
| dataset-tag-editor-standalone | https://github.com/toshiaki1729/dataset-tag-editor-standalone | MIT | Caption review UI ideas (Phase 8) |
| ai-toolkit | https://github.com/ostris/ai-toolkit | MIT | LoRA dataset target format: image + same-basename .txt (Phase 8) |
| kohya_ss | https://github.com/bmaltais/kohya_ss | Apache-2.0 | Second LoRA export target (later) |
| imagededup | https://github.com/idealo/imagededup | Apache-2.0 | Near-duplicate strategy studied; we implemented our own phash union-find in services/duplicates.py (no dep added) |
| sqlite-vec | https://github.com/asg017/sqlite-vec | MIT/Apache-2.0 | Candidate for face-embedding search in SQLite; NOT used — numpy over BLOB embeddings is enough at personal-library scale |
| ExifTool | https://github.com/exiftool/exiftool | Perl Artistic/GPL | Considered for Phase 10; NOT used — Pillow reads EXIF and we write our own minimal XMP (services/sidecars.py), so no external binary needed |
| CompreFace | https://github.com/exadel-inc/CompreFace | Apache-2.0 | Face API/workflow shapes only (Docker-based, not used directly) |

## Required attribution text

None triggered yet (no code copied). If code is copied from any repo above, paste its
license header here and note the exact files.
