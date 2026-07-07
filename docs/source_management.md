# Source management

## Path types accepted

- Local: `C:\Photos`, `F:\fotorganize\data\test_photos`
- Mapped drive: `Z:\family\photos` (classified `mapped` only if Windows reports the drive as remote)
- UNC: `\\nas-server\homes\family\photos` (preferred over Z: — survives reboots/logins)
- Forward-slash forms of any of the above are normalized (`//server/share/x` → `\\server\share\x`)

**Warning:** `Z:\family\photos` and `\\nas-server\homes\family\photos` are the *same folder*
on this machine but normalize to *different* root_paths. Add only one.

## Normalization (utils/paths.py `normalize_root`)

backslash-canonical, drive letter upper-cased, trailing slash stripped, quotes stripped.
The normalized value is the UNIQUE key in `sources.root_path`.

## Lifecycle

| status | scanned? | visible in UI? | how it happens |
|---|---|---|---|
| active | yes | yes | default |
| paused | no | yes | user action |
| inactive | no | hidden by default (`SHOW_INACTIVE_SOURCES` in .env) | user action ("Deactivate") |
| missing | retried on next scan | yes | scanner found root unreachable |

- Deactivating **never deletes** files/labels — they're hidden.
- Re-adding a source whose normalized path matches an existing row (any status)
  **reconnects** that row (`{"reconnected": true}` in the API response) — all prior
  file records and (later) person labels come back.
- **Hard delete** (`POST /api/sources/{id}/delete` with `{"confirm": true}`, UI "Delete"
  button with double-confirm): permanently removes ALL database records for the source
  (files, faces, captions, person links, FTS rows) and the source row itself. **Original
  photos on disk are never touched.** Prefer "Deactivate" — it keeps everything for a later
  re-add. Hard delete is for sources you truly never want back.

## Scan behavior

- Upsert key: `(source_id, relative_path)` → rescans never duplicate rows.
- Unchanged file (same size + mtime): skipped, no re-hash. Changed: re-hashed, EXIF re-read, thumbnail regenerated.
- File gone from disk: `status='missing'` (row kept). File back: `status='active'`.
- Source root unreachable: source marked `missing`; **file rows untouched** (an offline NAS is not proof of deletion).
- Skipped dirs: `$RECYCLE.BIN`, `System Volume Information`, `@eaDir`, `#recycle` (Synology).
- Per-file errors are logged (`data/logs/scan_<jobid>.log`) and skipped; scan continues.
- Commit batch: every `SCAN_BATCH_SIZE` files (default 200) — a crashed scan resumes cleanly
  on re-run because of the upsert key.
