# Database schema

SQLite at `data/app.db`, WAL mode, foreign keys ON. Migrations are numbered scripts in
`backend/photoindex/database.py` (`MIGRATIONS` list); applied versions tracked in
`schema_version`. **Never edit an old migration — append a new one.**

## Migration 1 (Phase 1)

### sources
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | display name |
| root_path | TEXT UNIQUE | normalized (see utils/paths.py) — the reconnect key |
| path_type | TEXT | `local` \| `mapped` \| `unc` |
| status | TEXT | `active` \| `paused` \| `inactive` \| `missing` |
| last_scan_at, created_at, updated_at | TEXT | UTC ISO |

### files
Unique on `(source_id, relative_path)` — this is the scan upsert key.

| column | notes |
|---|---|
| id, source_id (FK) | |
| relative_path | forward slashes, relative to source root — stable across scans |
| full_path | OS-native absolute path at last scan (may go stale; rebuilt each scan) |
| file_size, modified_time | change detection: same size+mtime → skip re-hash |
| sha256_hash | exact-duplicate identity; also derives the thumbnail path |
| perceptual_hash | ImageHash phash hex string (near-dupes, Phase 9) |
| mime_type, width, height | |
| date_taken, camera_model, gps_lat, gps_lon | from EXIF, best-effort |
| status | `active` \| `missing` \| `deleted` \| `ignored` — missing files are marked, never deleted |
| thumb_status | `pending` \| `ok` \| `failed` (thumbnail path is derived from sha256, not stored) |
| created_at, updated_at | |

### jobs
| column | notes |
|---|---|
| id, job_type | `scan_source` \| `thumbnails` (more types in later phases) |
| status | `pending` \| `running` \| `done` \| `failed` |
| payload_json | e.g. `{"source_id": 1}` |
| error_message | failure reason |
| progress | free text; on success holds the result summary JSON |
| created_at, started_at, finished_at | |

## Planned (drafted, NOT yet migrated)

Phase 3: `image_analysis` — file_id, caption_short, caption_detailed, object_tags_json,
scene_tags_json, ocr_text, model_name, model_version, analysis_version, status, error_message, processed_at.

Phase 4: `faces` — file_id, face_crop_path, bounding_box_json, landmarks_json,
embedding_vector (BLOB or sqlite-vec), quality/blur/pose scores, cluster_id, person_id,
confirmed_by_user, status, model_name/version.

Phase 5: `face_clusters`, `people`, `image_people`. Phase 8: `exports`.

## Migration 3 (Phase 9/10) — IMPLEMENTED

Added to `files`:
- `is_screenshot` INTEGER (NULL = not evaluated, 0/1 = result of the screenshot heuristic)
- `sidecar_written_at` TEXT (UTC ISO of the last XMP sidecar write, NULL = never)

No new tables. Duplicate groups are computed on demand (exact by sha256, near by
perceptual_hash) — nothing persisted. See services/duplicates.py and services/sidecars.py.
