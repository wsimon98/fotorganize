"""Florence-2 captioning / tags / OCR. Model loads once per process (lazy singleton).

See docs/ai_pipeline.md. Runs on GPU when available, else CPU (slow but works).
Every result records model_name + model_version so a newer model can re-run later.
"""
from __future__ import annotations

import logging

from PIL import Image, ImageOps

from .. import config

log = logging.getLogger(__name__)

_MODEL = None
_PROCESSOR = None
_DEVICE = None
_DTYPE = None
MODEL_VERSION = "1"  # bump when prompt set / postprocessing changes


def _load():
    global _MODEL, _PROCESSOR, _DEVICE, _DTYPE
    if _MODEL is not None:
        return
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    _DEVICE = "cuda" if (config.GPU_ENABLED and torch.cuda.is_available()) else "cpu"
    _DTYPE = torch.float16 if _DEVICE == "cuda" else torch.float32
    name = config.CAPTION_MODEL
    log.info("loading caption model %s on %s (%s)", name, _DEVICE, _DTYPE)
    _MODEL = AutoModelForCausalLM.from_pretrained(
        name, trust_remote_code=True, torch_dtype=_DTYPE).to(_DEVICE)
    _PROCESSOR = AutoProcessor.from_pretrained(name, trust_remote_code=True)


def _run_task(img: Image.Image, prompt: str, max_new_tokens: int = 1024):
    import torch
    inputs = _PROCESSOR(text=prompt, images=img, return_tensors="pt").to(_DEVICE, _DTYPE)
    with torch.no_grad():
        ids = _MODEL.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=max_new_tokens,
            num_beams=3,
            do_sample=False,
        )
    text = _PROCESSOR.batch_decode(ids, skip_special_tokens=False)[0]
    return _PROCESSOR.post_process_generation(
        text, task=prompt, image_size=(img.width, img.height))


def analyze(full_path: str) -> dict:
    """Return caption_short, caption_detailed, object_tags(list), ocr_text, model_name/version.

    Raises on unrecoverable errors (caller marks the file failed and continues).
    """
    _load()
    with Image.open(full_path) as im:
        img = ImageOps.exif_transpose(im).convert("RGB")

        short = _run_task(img, "<CAPTION>").get("<CAPTION>", "").strip()
        detailed = _run_task(img, "<MORE_DETAILED_CAPTION>").get(
            "<MORE_DETAILED_CAPTION>", "").strip()

        tags: list[str] = []
        try:
            od = _run_task(img, "<OD>").get("<OD>", {})
            tags = sorted(set(od.get("labels", [])))
        except Exception as e:
            log.warning("OD failed for %s: %s", full_path, e)

        ocr = ""
        try:
            ocr = _run_task(img, "<OCR>").get("<OCR>", "").strip()
        except Exception as e:
            log.warning("OCR failed for %s: %s", full_path, e)

    return {
        "caption_short": short,
        "caption_detailed": detailed,
        "object_tags": tags,
        "ocr_text": ocr,
        "model_name": config.CAPTION_MODEL,
        "model_version": MODEL_VERSION,
    }
