# Maintenance: duplicates, screenshots, XMP sidecars (Phase 9 + 10)

All of this lives on the **Duplicates** page in the UI, or via CLI / the
`/api/maintenance/*` endpoints. Code: `services/duplicates.py`, `services/sidecars.py`,
`routes/maintenance.py`.

## Duplicate detection (Phase 9)

- **Exact duplicates** — files with the same `sha256_hash`. `GET /api/maintenance/duplicates?kind=exact`.
- **Near-duplicates** — grouped by perceptual hash (phash) within a hamming distance
  (default 6, `?max_distance=`). Union-find over active files; O(n²), fine for a personal
  library. `GET /api/maintenance/duplicates?kind=near`.
- Nothing is deleted automatically — the page shows groups for review. LoRA export removes
  near-dupes at export time (its own `dedupe` option).
- CLI: `python -m photoindex duplicates`.

## Screenshot / meme flagging (Phase 9)

- `POST /api/maintenance/flag-screenshots` (or `python -m photoindex duplicates --flag-screenshots`)
  sets `files.is_screenshot` for every active file.
- Heuristic: filename matches `screenshot|screen shot|capture|snip`, OR the image has OCR
  text (>15 chars) AND zero detected faces.
- **Run captions + faces first** — the OCR/faces signals come from analysis. Filename-only
  detection works without them.
- Uses: Search "screenshots only" / "photos only"; LoRA export `exclude_screenshots` (on by default).

## XMP sidecars (Phase 10) — opt-in, non-destructive

- **Off by default.** Set `WRITE_XMP_SIDECARS=true` in `.env` to enable automatic-eligible
  writes, or force a one-off from the UI button / `python -m photoindex sidecars --write --force`.
- Writes `<original>.xmp` **next to** the original. The original photo file is **never
  modified** — an XMP sidecar is a separate companion file.
- Contents: `dc:subject` + `MicrosoftPhoto:LastKeywordXMP` keyword bags (person names +
  object tags) and a `digiKam:TagsList` with `People/<Name>` entries. Read by Windows
  Explorer/Photos, Lightroom, digiKam.
- We do NOT write MWG face-region rectangles (face boxes) — only keywords. Adding regions
  later would let digiKam import face boxes; see PROJECT_CHECKLIST.
- Reading: `sidecars.read_sidecar(path)` parses `dc:subject` back into keywords (used to
  ingest tags made in other apps — wiring that into scan is a future option).
- `files.sidecar_written_at` records the last write time.

## Safety recap

- Duplicate detection and screenshot flagging only read + set DB flags. Nothing is deleted.
- Hard-delete of a *source* (Sources page) removes DB records only — never the photos. See
  docs/source_management.md.
- Sidecars are opt-in and additive; originals are untouched.
