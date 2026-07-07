# LoRA export (Phase 8) — IMPLEMENTED (session 2, 2026-07-06)

Built and verified. Code: `backend/photoindex/services/lora_export.py`; API
`POST /api/people/{id}/export`; UI on the Person page ("Export LoRA dataset"); CLI
`python -m photoindex export-lora --person "George Clooney" --trigger "clooney_person" --zip`.

Target: **ai-toolkit** (https://github.com/ostris/ai-toolkit) first; kohya_ss later.

Notes on what shipped: captions are `trigger, <Florence caption>` (natural) or
`trigger, <object tags>` (tag style). Attribute words like "adult man, beard" from the
spec examples are NOT auto-derived (we don't run an attribute model) — the Florence caption
stands in. Near-duplicate removal uses the stored perceptual_hash (hamming threshold).

## Output layout

```
data/exports/<PersonName>_aitoolkit_<YYYY-MM-DD>/
  person_0001.jpg      person_0001.txt
  person_0002.jpg      person_0002.txt
  manifest.json        contact_sheet.jpg
  rejected/            (images excluded by filters, for review)
```

- Each image gets a same-basename `.txt` caption file (ai-toolkit convention).
- Caption styles: natural sentence, or LoRA tag style
  (`clooney_person, adult man, short hair, beard, indoor photo, natural lighting`).
- Trigger word goes first in every caption; original paths appear ONLY in manifest.json.
- manifest.json: original file paths, source ids, face ids, quality scores, caption text,
  export settings.

## Filters (all optional)

confirmed-only, exclude group photos, min face quality, min image size, max images,
near-duplicate removal (perceptual hash distance), export mode: full image / face crop /
smart crop around person.

## CLI

`python -m photoindex export-lora --person "George Clooney" --trigger "clooney_person"`
plus `scripts\export_person_lora.bat "George Clooney" clooney_person` (currently a placeholder).
