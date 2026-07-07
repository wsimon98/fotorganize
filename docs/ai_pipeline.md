# AI pipeline (Phases 3-5) — IMPLEMENTED (session 2, 2026-07-06)

Built and verified end-to-end on GPU. This file describes what shipped. Code lives in
`backend/photoindex/ai/` (captioner, faces, clustering), `services/analysis.py`,
`workers/worker.py`. What actually differs from the original plan:
- Face detection currently runs on CPU (onnxruntime/cuDNN — see TROUBLESHOOTING); captioning on GPU.
- Clustering is numpy greedy cosine (no sklearn) + auto-assign to named people.
- transformers pinned <4.50 for Florence remote-code compatibility.

## Principles (from project spec)

- All models run locally on the GPU (RTX 5060 Ti 16GB). Model *downloads* (HF Hub) are the
  only permitted network access — never image data.
- Every AI result row stores `model_name` + `model_version` + `analysis_version` so a newer
  model can re-run later without losing old results.
- AI failures are per-image: log, mark row failed, continue the batch.
- Resumable: work is claimed from the `jobs` table; a crash mid-batch loses nothing.

## Architecture

Separate worker process — `python -m photoindex worker` — polls `jobs` for
`caption_batch` / `face_batch` rows. Models load once per worker lifetime, NOT inside
the FastAPI process. The web app only enqueues jobs and reads results.

## Phase 3 — captioning (Florence-2)

- Model: `microsoft/Florence-2-base` first (fits easily in VRAM, fast); `-large` optional
  via `CAPTION_MODEL` in .env.
- Tasks per image: `<CAPTION>` (short), `<MORE_DETAILED_CAPTION>` (detailed),
  `<OD>` object tags, `<OCR>` text — exactly the Lora-Captioner approach (see ATTRIBUTION).
- New table `image_analysis` (schema in database_schema.md) via migration 2.
- Search: SQLite FTS5 virtual table over caption_short + caption_detailed + ocr_text + tags.

## Phase 4 — faces (InsightFace)

- `insightface` + `onnxruntime-gpu`, `buffalo_l` model pack (det + 512-d ArcFace embeddings).
- Face crops to `data/face_crops/<sha[:2]>/<sha>_<n>.jpg` (content-addressed like thumbnails).
- Embeddings: BLOB column first; evaluate sqlite-vec when cluster counts grow.

## Phase 5 — clustering

- Start simple: greedy agglomerative over cosine similarity with a config threshold
  (~0.5-0.6 for ArcFace, tune in .env), or DBSCAN via scikit-learn.
- Manual naming/merging/splitting through the People Review UI; user labels are ground
  truth and are NEVER overwritten by re-clustering (re-cluster only unnamed faces).
