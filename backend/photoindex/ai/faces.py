"""InsightFace face detection + 512-d ArcFace embeddings. Lazy singleton model.

See docs/ai_pipeline.md. Face crops are content-addressed under FACE_CROP_DIR like
thumbnails: <sha[:2]>/<sha>_<idx>.jpg.
"""
from __future__ import annotations

import logging

import numpy as np
from PIL import Image, ImageOps

from .. import config

log = logging.getLogger(__name__)

_APP = None
MODEL_VERSION = "1"


def _add_cuda_dlls():
    """onnxruntime-gpu needs CUDA/cuDNN DLLs on the search path. torch bundles them;
    expose torch's lib dir so onnxruntime can load the CUDA provider (else it silently
    falls back to CPU). Best-effort; safe if it fails."""
    import os
    try:
        import torch
        libdir = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(libdir):
            os.add_dll_directory(libdir)
    except Exception as e:
        log.debug("could not add torch cuda dll dir: %s", e)


def _load():
    global _APP
    if _APP is not None:
        return
    if config.GPU_ENABLED:
        _add_cuda_dlls()
    import onnxruntime
    if config.GPU_ENABLED and hasattr(onnxruntime, "preload_dlls"):
        try:
            onnxruntime.preload_dlls()  # onnxruntime>=1.19 loads CUDA/cuDNN from nvidia wheels
        except Exception as e:
            log.debug("onnxruntime.preload_dlls failed: %s", e)
    from insightface.app import FaceAnalysis

    providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                 if config.GPU_ENABLED and "CUDAExecutionProvider"
                 in onnxruntime.get_available_providers()
                 else ["CPUExecutionProvider"])
    log.info("loading face model %s providers=%s", config.FACE_MODEL, providers)
    _APP = FaceAnalysis(name=config.FACE_MODEL, providers=providers)
    _APP.prepare(ctx_id=0 if "CUDAExecutionProvider" in providers else -1,
                 det_size=(640, 640))


def face_crop_path(sha256: str, idx: int):
    return config.FACE_CROP_DIR / sha256[:2] / f"{sha256}_{idx}.jpg"


def detect(full_path: str, sha256: str) -> list[dict]:
    """Detect faces; write crops; return one dict per face with embedding + scores.

    Raises on unreadable image (caller marks file failed).
    """
    _load()
    with Image.open(full_path) as im:
        # right-side-up first: detection quality and bbox coords depend on it
        img = ImageOps.exif_transpose(im).convert("RGB")
        arr = np.array(img)[:, :, ::-1]  # RGB -> BGR for insightface
        faces = _APP.get(arr)
        out = []
        for idx, f in enumerate(faces):
            x1, y1, x2, y2 = [int(v) for v in f.bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.width, x2), min(img.height, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            # pad crop 30% for a friendlier face thumbnail
            pw, ph = int((x2 - x1) * 0.3), int((y2 - y1) * 0.3)
            crop = img.crop((max(0, x1 - pw), max(0, y1 - ph),
                             min(img.width, x2 + pw), min(img.height, y2 + ph)))
            cp = face_crop_path(sha256, idx)
            cp.parent.mkdir(parents=True, exist_ok=True)
            crop.save(cp, "JPEG", quality=88)

            emb = f.normed_embedding.astype("float32")
            pose = getattr(f, "pose", None)
            pose_score = float(abs(pose[1])) if pose is not None else None  # |yaw|
            sex = getattr(f, "sex", None)  # 'M' / 'F' from the genderage model
            gender = {"M": "male", "F": "female"}.get(sex)
            age = getattr(f, "age", None)
            out.append({
                "gender": gender,
                "age": int(age) if age is not None else None,
                "idx": idx,
                "crop_path": str(cp),
                "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                "landmarks": f.kps.astype(float).tolist() if f.kps is not None else None,
                "embedding": emb.tobytes(),
                "quality_score": float(f.det_score),
                "blur_score": None,
                "pose_score": pose_score,
                "model_name": config.FACE_MODEL,
                "model_version": MODEL_VERSION,
            })
        return out
